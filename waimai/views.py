import uuid

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.urls import reverse, reverse_lazy
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .delivery_helpers import build_delivery_fee_breakdown, calc_order_delivery_fee, get_delivery_settings
from .dispatch_helpers import dispatch_buy_order, get_shop_riders
from .forms import (
    BuyerRegistrationForm,
    ShopDeliverySettingsForm,
    ShopOperatingSettingsForm,
    ShopPaymentSettingsForm,
    ShopRegistrationForm,
    ShopStatusSettingsForm,
)
from .models import BuyOrder, DeliveryOrder, Dish, MenuProfile, ShopProfile, TableSession, User
from .menu_helpers import (
    dish_visible_on_shop,
    get_active_menu_items_map,
    get_shop_dishes_for_sale,
    increment_menu_sold_counts,
    validate_dish_purchase,
)
from .operating_helpers import check_order_admission, get_operating_settings
from waimai.plugins.dining.table_helpers import (
    build_table_scan_path,
    build_virtual_scan_path,
    get_open_order_for_session,
    virtual_code_is_busy,
)
from waimai.plugins.dining.table_bulk_helpers import sort_shop_tables, sort_virtual_codes
from waimai.plugins.dining.seller_handlers import handle_dine_post
from waimai.plugins.dining.buyer_entry import (
    dine_table_entry,  # noqa: F401  # urls 仍从 views 引用
    get_buyer_table_session,
)
from .operating_seller_handlers import handle_operating_post
from .product_seller_handlers import handle_products_post
from .product_helpers import (
    build_dish_tier_options,
    cart_line_key,
    validate_tier_purchase,
    PRICE_TIER_GENERAL,
)
from .order_helpers import (
    build_cart_items,
    build_order_timeline,
    cart_count_positive,
    cart_has_lines,
    dish_items_with_line_totals,
    get_shop_cart,
    normalize_cart_keys,
    parse_distance_km,
    parse_fulfillment_type,
    store_delivery_address,
    set_shop_cart,
    parse_cart_line_key,
)
from .channel_helpers import build_order_pricing
from .payments import (
    build_pay_page_context,
    handle_wechat_notify,
    initiate_payment,
    poll_wechat_payment,
)
from .seller_helpers import handle_seller_post


def _client_ip(request):
    """取买家 IP（微信下单参数用）"""
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1') or '127.0.0.1'


class CustomLoginView(LoginView):
    """野草生态登录：仅买家、店主"""
    template_name = 'waimai/login.html'

    def get_form_class(self):
        from .ecosystem_auth import EcosystemAuthenticationForm
        return EcosystemAuthenticationForm

    def form_valid(self, form):
        from .experience_helpers import can_accept_online, touch_online_user

        user = form.get_user()
        ok, msg = can_accept_online(user)
        if not ok:
            form.add_error(None, msg)
            return self.form_invalid(form)

        response = super().form_valid(form)
        from .single_login_helpers import claim_single_login
        claim_single_login(self.request, self.request.user)
        from .audit_helpers import write_audit_log

        user = self.request.user
        touch_online_user(user)
        write_audit_log(
            action_code='login',
            summary='野草生态登录成功',
            actor=user,
            request=self.request,
        )
        return response

    def form_invalid(self, form):
        from .audit_helpers import write_audit_log

        username = (self.request.POST.get('username') or '').strip()
        write_audit_log(
            action_code='login_failed',
            summary=f'野草生态登录失败：{username or "（未填用户名）"}',
            actor_username=username,
            result='fail',
            request=self.request,
        )
        return super().form_invalid(form)

    def get_success_url(self):
        user = self.request.user
        if user.role == 'seller':
            return reverse_lazy('seller_panel')
        return reverse_lazy('directory')


class EcosystemLogoutView(LogoutView):
    """野草生态退出：只清生态登录，尽量保留店铺工作台会话"""

    next_page = '/accounts/login/'

    def dispatch(self, request, *args, **kwargs):
        from .audit_helpers import write_audit_log
        from .shop_work_auth import restore_shop_work_session, snapshot_shop_work_session

        user = request.user if getattr(request.user, 'is_authenticated', False) else None
        self._shop_work_snap = snapshot_shop_work_session(request)
        if user:
            from .single_login_helpers import release_single_login
            release_single_login(request, user)
            write_audit_log(
                action_code='logout',
                summary='野草生态退出',
                actor=user,
                request=request,
            )
        response = super().dispatch(request, *args, **kwargs)
        restore_shop_work_session(request, getattr(self, '_shop_work_snap', None))
        return response


def shop_work_logout(request, shop_code=None):
    """店铺工作台退出：只清工作台会话，不影响野草生态登录"""
    from .audit_helpers import write_audit_log
    from .shop_work_auth import clear_shop_work_session, get_shop_work_user
    from .shop_work_helpers import build_shop_work_path
    from .staff_account_helpers import (
        deactivate_staff_on_logout,
        is_shop_staff_account,
        shop_code_from_request,
    )

    if request.method != 'POST':
        code = (shop_code or '').strip() or shop_code_from_request(request)
        if code:
            return redirect(build_shop_work_path(code))
        return redirect('directory')

    work_user = get_shop_work_user(request)
    code = (shop_code or '').strip() or shop_code_from_request(request)
    if work_user:
        from .single_login_helpers import release_single_login
        release_single_login(request, work_user)
        write_audit_log(
            action_code='logout',
            summary='店铺工作台退出',
            actor=work_user,
            request=request,
        )
    if is_shop_staff_account(work_user):
        deactivate_staff_on_logout(work_user)
    clear_shop_work_session(request)
    messages.success(request, '已退出店铺工作台')
    if code:
        return redirect(build_shop_work_path(code))
    return redirect('directory')


# 会话守护接口（心跳 / 关页尽量退出）
from .session_guard import session_beacon_logout, session_heartbeat  # noqa: E402


def home(request):
    """本服务器主页（拥有者配置；与单店主页严格分开）"""
    from .home_page_helpers import build_server_home_view_context
    from .models import ShopProfile

    # 一台店都没有时仍给开通引导
    if not ShopProfile.objects.exists():
        return render(request, 'waimai/home_empty.html')
    context = build_server_home_view_context(request)
    return render(request, 'waimai/showcase_home.html', context)


def directory(request):
    """旧名录地址：兼容跳到服务器主页（名录为服务器主页积木）"""
    return redirect('home')


def shop_showcase(request, shop_code=None):
    """按店铺码打开某店店铺主页（单店门面）"""
    from .home_page_helpers import build_shop_home_view_context, ensure_home_page_for_seller
    from .shop_work_helpers import get_shop_profile_by_code

    code = (shop_code or '').strip()
    profile = get_shop_profile_by_code(code) if code else None
    if not profile:
        seller_id = (request.GET.get('seller_id') or '').strip()
        profile = ShopProfile.objects.filter(seller_id=seller_id).first() if seller_id else None
    if not profile:
        return redirect('home')
    page = ensure_home_page_for_seller(profile.seller_id, profile)
    context = build_shop_home_view_context(page, request)
    return render(request, 'waimai/showcase_home.html', context)


def _redirect_to_shop_work(request, view: str = ''):
    """有本店店码时，引导到店铺工作台（优先工作台会话用户）"""
    from .shop_work_auth import get_shop_work_user
    from .shop_work_helpers import build_shop_work_path, default_work_view, get_shop_code_for_user

    work_user = get_shop_work_user(request)
    user = work_user or (request.user if request.user.is_authenticated else None)
    if not user:
        return None
    code = get_shop_code_for_user(user)
    if not code:
        return None
    tab = (view or '').strip() or default_work_view(user)
    return redirect(build_shop_work_path(code, view=tab))


def rider_home(request):
    """旧地址：统一引导到店铺工作台骑手视角"""
    work_redirect = _redirect_to_shop_work(request, 'rider')
    if work_redirect:
        return work_redirect
    return redirect('directory')


def knight_hall_redirect(request):
    """旧地址兼容：跳转到骑手之家"""
    return redirect('rider_home')


def kitchen_home(request):
    """旧地址：统一引导到店铺工作台后厨视角"""
    work_redirect = _redirect_to_shop_work(request, 'kitchen')
    if work_redirect:
        return work_redirect
    return redirect('directory')


def waiter_home(request):
    """旧地址：统一引导到店铺工作台服务员视角"""
    work_redirect = _redirect_to_shop_work(request, 'waiter')
    if work_redirect:
        return work_redirect
    return redirect('directory')


def owner_hub(request):
    """旧地址：有管理者权限则进服务器设置，否则进本店工作台"""
    from .owner_helpers import user_is_server_manager

    if getattr(request.user, 'is_authenticated', False) and user_is_server_manager(request.user):
        return redirect('server_settings')
    return _redirect_to_shop_work(request) or redirect('seller_panel')


def shop_work(request, shop_code):
    """店铺工作台：登录 + 三岗位 Tab（独立于管理后台与野草生态登录）"""
    from .shop_work_auth import (
        clear_shop_work_session,
        establish_shop_work_session,
        get_shop_work_seller_id,
        get_shop_work_user,
    )
    from .shop_work_helpers import (
        WORK_VIEWS,
        build_kitchen_board_context,
        build_rider_board_context,
        build_shop_work_daily_history,
        build_shop_work_path,
        build_waiter_board_context,
        default_work_view,
        get_delivery_dispatch_role,
        get_shop_profile_by_code,
        user_belongs_to_shop,
        work_permissions,
    )
    from .workbench_handlers import handle_shop_work_post

    shop_profile = get_shop_profile_by_code(shop_code)
    if not shop_profile:
        return render(request, 'waimai/shop_work_login.html', {'shop_profile': None}, status=404)

    seller_id = shop_profile.seller_id
    code = (shop_profile.shop_code or '').strip()
    work_user = get_shop_work_user(request)

    # 工作台会话属于别的店时，清掉，避免串店
    if work_user and get_shop_work_seller_id(request) != seller_id:
        clear_shop_work_session(request)
        work_user = None

    if work_user and user_belongs_to_shop(work_user, seller_id):
        from .workbench_shell_helpers import build_workbench_shell

        from .staff_account_helpers import (
            PERM_DINING_RIDER,
            is_shop_staff_account,
            staff_has_any_order_desk_permission,
            staff_job_title,
            staff_has_permission,
        )

        workbench_shell = build_workbench_shell(seller_id)
        enabled_views = [
            view for view in workbench_shell.get('enabled_views', [])
            if view in WORK_VIEWS
        ]
        # 无订单台权限的员工不显示「订单处理」Tab
        if (
            'orders' in enabled_views
            and work_user.role != 'seller'
            and not staff_has_any_order_desk_permission(work_user)
        ):
            enabled_views = [view for view in enabled_views if view != 'orders']

        current_view = (request.GET.get('view') or default_work_view(work_user)).strip()
        if current_view not in enabled_views:
            current_view = enabled_views[0] if enabled_views else ''
        from .workbench_sort_helpers import resolve_workbench_sort

        work_order_sort = resolve_workbench_sort(request)

        def _work_url(view_name: str, sort_mode: str = work_order_sort) -> str:
            url = build_shop_work_path(code, view=view_name)
            joiner = '&' if '?' in url else '?'
            return f'{url}{joiner}sort={sort_mode}'

        perms = work_permissions(work_user)
        perms = {
            view: bool(perms.get(view) and view in enabled_views)
            for view in WORK_VIEWS
        }
        can_open_orders = (
            work_user.role == 'seller'
            or staff_has_any_order_desk_permission(work_user)
        ) and 'orders' in enabled_views
        # 订单台只读员工也能收到“有新单”提醒；提醒本身不授予操作权限。
        can_use_order_alert = bool(
            work_user.role == 'seller'
            or perms.get(current_view)
            or (current_view == 'orders' and can_open_orders)
        )

        if request.method == 'POST':
            is_status_action = 'staff_work_status_action' in request.POST
            if current_view == 'orders':
                if not is_status_action and not can_open_orders:
                    messages.error(request, '您没有权限执行此操作')
                    return redirect(build_shop_work_path(code, view=current_view))
            elif not is_status_action and not perms.get(current_view):
                messages.error(request, '您没有权限执行此操作')
                return redirect(build_shop_work_path(code, view=current_view))
            response = handle_shop_work_post(
                request, seller_id, code, current_view, perms, work_user=work_user,
            )
            if response:
                return response

        form_action = _work_url(current_view)

        context = {
            'shop_profile': shop_profile,
            'current_view': current_view,
            'enabled_work_views': enabled_views,
            'form_action': form_action,
            'tab_orders_url': _work_url('orders'),
            'tab_waiter_url': _work_url('waiter'),
            'tab_kitchen_url': _work_url('kitchen'),
            'tab_rider_url': _work_url('rider'),
            'work_order_sort': work_order_sort,
            'sort_newest_url': _work_url(current_view, 'newest'),
            'sort_oldest_url': _work_url(current_view, 'oldest'),
            'can_operate_orders': perms.get('orders', False),
            'can_open_orders': can_open_orders,
            'can_operate_waiter': perms['waiter'],
            'can_operate_kitchen': perms['kitchen'],
            'can_operate_rider': perms['rider'],
            'can_use_order_alert': can_use_order_alert,
            'show_rider_extras': staff_has_permission(work_user, PERM_DINING_RIDER),
            'is_work_staff': is_shop_staff_account(work_user),
            'work_user_title': (
                staff_job_title(work_user)
                if is_shop_staff_account(work_user)
                else work_user.get_role_display()
            ),
            'shop_work_code': code,
            'shop_work_logout_url': reverse('shop_work_logout', kwargs={'shop_code': code}),
            'dispatch_role': get_delivery_dispatch_role(seller_id),
            'work_user': work_user,
            'workbench_shell': workbench_shell,
        }
        context.update(build_shop_work_daily_history(seller_id, work_user))
        from .audit_helpers import query_audit_logs, write_audit_log
        # 服务方仅看本人操作记录（A.12）
        if is_shop_staff_account(work_user):
            if (request.GET.get('my_audit') or '').strip() == '1':
                write_audit_log(
                    action_code='view_audit',
                    summary='员工查看本人操作记录',
                    seller_id=seller_id,
                    actor=work_user,
                    request=request,
                )
            context['my_audit_logs'] = list(query_audit_logs(
                seller_id=seller_id,
                only_username=work_user.username,
                limit=30,
            ))
            context['show_my_audit'] = (request.GET.get('my_audit') or '').strip() == '1'
        if current_view == 'orders':
            from .order_desk_helpers import build_order_desk_context

            context.update(build_order_desk_context(
                seller_id, work_user=work_user, sort_mode=work_order_sort,
            ))
        elif current_view == 'waiter':
            from .dispatch_helpers import operator_can_manual_dispatch

            context.update(build_waiter_board_context(
                seller_id,
                allow_dispatch=operator_can_manual_dispatch(work_user, seller_id, 'waiter'),
                sort_mode=work_order_sort,
            ))
        elif current_view == 'kitchen':
            from .dispatch_helpers import operator_can_manual_dispatch

            context.update(build_kitchen_board_context(
                seller_id,
                allow_dispatch=operator_can_manual_dispatch(work_user, seller_id, 'kitchen'),
                sort_mode=work_order_sort,
            ))
        elif current_view == 'rider':
            context.update(build_rider_board_context(
                work_user, seller_id, sort_mode=work_order_sort,
            ))
        return render(request, 'waimai/shop_work_hub.html', context)

    if request.method == 'POST':
        from .audit_helpers import write_audit_log
        from .staff_account_helpers import (
            activate_staff_on_login,
            authenticate_shop_work_user,
            is_shop_staff_account,
        )

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate_shop_work_user(request, seller_id, username, password)
        if user is not None:
            from .experience_helpers import can_accept_online, touch_online_user

            ok, msg = can_accept_online(user)
            if not ok:
                messages.error(request, msg)
                return render(request, 'waimai/shop_work_login.html', {'shop_profile': shop_profile})
            if is_shop_staff_account(user):
                activate_staff_on_login(user)
            establish_shop_work_session(request, user, seller_id=seller_id, shop_code=code)
            from .single_login_helpers import claim_single_login
            claim_single_login(request, user)
            touch_online_user(user)
            write_audit_log(
                action_code='login',
                summary='店铺工作台登录成功',
                seller_id=seller_id,
                actor=user,
                request=request,
            )
            return redirect(build_shop_work_path(code, view=default_work_view(user)))
        write_audit_log(
            action_code='login_failed',
            summary=f'店铺工作台登录失败：{username or "（未填用户名）"}',
            seller_id=seller_id,
            actor_username=username,
            result='fail',
            request=request,
        )
        messages.error(request, '用户名或密码错误')

    return render(request, 'waimai/shop_work_login.html', {'shop_profile': shop_profile})


@require_GET
def shop_work_new_orders_json(request, shop_code):
    """店铺工作台轮询用：返回待备货新单数量与最新时间戳（毫秒）。

    只认工作台登录身份（店主或本店员工），供后厨/服务员页面开着时持续查新单。
    """
    from .shop_work_auth import get_shop_work_seller_id, get_shop_work_user
    from .shop_work_helpers import get_shop_profile_by_code, user_belongs_to_shop

    shop_profile = get_shop_profile_by_code(shop_code)
    if not shop_profile:
        return JsonResponse({'ok': False, 'count': 0, 'latest_ts': 0}, status=404)
    seller_id = shop_profile.seller_id
    work_user = get_shop_work_user(request)
    if (
        not work_user
        or get_shop_work_seller_id(request) != seller_id
        or not user_belongs_to_shop(work_user, seller_id)
    ):
        return JsonResponse({'ok': False, 'count': 0, 'latest_ts': 0}, status=403)

    # 骑手页签只提醒外卖待接单；纯配送员工亦然。其它页签/角色看全店待备货新单。
    from .shop_work_helpers import work_permissions

    permissions = work_permissions(work_user)
    view = (request.GET.get('view') or '').strip()
    if view not in ('orders', 'waiter', 'kitchen', 'rider'):
        return JsonResponse({'ok': False, 'count': 0, 'latest_ts': 0}, status=400)
    from .staff_account_helpers import staff_has_any_order_desk_permission

    can_read_orders = view == 'orders' and staff_has_any_order_desk_permission(work_user)
    if work_user.role != 'seller' and not permissions.get(view) and not can_read_orders:
        return JsonResponse({'ok': False, 'count': 0, 'latest_ts': 0}, status=403)
    count_delivery = permissions.get('rider') and view == 'rider'
    if count_delivery:
        from .dispatch_helpers import query_pending_dispatch_orders

        qs = query_pending_dispatch_orders(seller_id)
    else:
        from .order_alert_helpers import query_shop_new_orders

        qs = query_shop_new_orders(seller_id)
    count = qs.count()
    latest = qs.order_by('-created_at').values_list('created_at', flat=True).first()
    latest_ts = int(latest.timestamp() * 1000) if latest else 0
    from .operating_helpers import build_order_alert_config
    return JsonResponse({
        'ok': True, 'count': count, 'latest_ts': latest_ts,
        'config': build_order_alert_config(seller_id),
    })


def shop_work_order(request, shop_code, order_id):
    """
    工作台订单中转页：仅认工作台登录身份。
    员工可联系客人、留言沟通；有「允许取消订单」时才能取消。
    不进卖家后台，避免与店主生态登录串号。
    """
    from .order_cancel_helpers import (
        cancel_order_by_shop,
        shop_can_cancel_order,
        shop_has_cancel_communication,
    )
    from .order_helpers import dish_items_with_line_totals
    from .order_message_helpers import (
        mark_order_messages_read,
        post_order_message,
        viewer_can_use_order_chat,
    )
    from .shop_work_auth import get_shop_work_user
    from .shop_work_helpers import (
        build_shop_work_order_path,
        build_shop_work_path,
        get_shop_profile_by_code,
        user_belongs_to_shop,
    )

    shop_profile = get_shop_profile_by_code(shop_code)
    if not shop_profile:
        return render(request, 'waimai/shop_work_login.html', {'shop_profile': None}, status=404)

    code = (shop_profile.shop_code or '').strip()
    seller_id = shop_profile.seller_id
    work_user = get_shop_work_user(request)

    if not work_user or not user_belongs_to_shop(work_user, seller_id):
        messages.error(request, '请先登录本店工作台')
        return redirect(build_shop_work_path(code))

    order = get_object_or_404(
        BuyOrder.objects.select_related('delivery_order'),
        order_id=order_id,
        seller_id=seller_id,
    )

    can_chat = viewer_can_use_order_chat(work_user, order)
    can_shop_cancel = shop_can_cancel_order(work_user, order)
    from .staff_account_helpers import PERM_ORDERS_CONTACT, staff_has_permission

    # 店主天然通过公共权限函数；员工须勾选“可联系顾客”。
    show_contact = staff_has_permission(work_user, PERM_ORDERS_CONTACT)
    if not show_contact:
        can_chat = False

    self_url = build_shop_work_order_path(code, order.order_id)

    if request.method == 'POST' and 'send_order_message' in request.POST:
        if not can_chat:
            messages.error(request, '您没有联系顾客或留言的权限')
        else:
            ok, msg = post_order_message(order, work_user, request.POST.get('message_body', ''))
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        return redirect(self_url)

    if request.method == 'POST' and 'cancel_order_shop' in request.POST:
        ok, msg = cancel_order_by_shop(order, work_user, request.POST.get('cancel_note', ''))
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(self_url)

    if can_chat:
        mark_order_messages_read(order, work_user)

    from .workbench_shell_helpers import build_workbench_shell

    return render(request, 'waimai/shop_work_order.html', {
        'shop_profile': shop_profile,
        'shop_work_code': code,
        'work_user': work_user,
        'order': order,
        'dish_lines': dish_items_with_line_totals(order.dish_items),
        'order_messages': list(order.messages.order_by('created_at')),
        'can_order_chat': can_chat,
        'show_contact_guest': show_contact,
        'can_shop_cancel': can_shop_cancel,
        'shop_has_chat_history': shop_has_cancel_communication(order),
        'back_url': build_shop_work_path(code, view='orders'),
        'shop_work_logout_url': reverse('shop_work_logout', kwargs={'shop_code': code}),
        'workbench_shell': build_workbench_shell(seller_id),
    })


def waiter_pay_order(request, order_id):
    """服务员协助收款：选择支付方式（绑定本单）；认工作台登录身份"""
    from .payments import build_pay_page_context
    from .shop_work_auth import get_shop_work_user
    from .waiter_handlers import handle_waiter_pay_post
    from .waiter_helpers import ensure_waiter_employer, sync_waiter_service_status
    from .shop_work_helpers import resolve_waiter_return_url

    from .staff_account_helpers import PERM_DINING_WAITER, staff_has_permission

    work_user = get_shop_work_user(request)
    if not work_user or not staff_has_permission(work_user, PERM_DINING_WAITER):
        # 无工作台登录时，引导回工作台入口（若能解析店码）
        return _redirect_to_shop_work(request, 'waiter') or redirect('directory')
    seller_id = work_user.username if work_user.role == 'seller' else ensure_waiter_employer(work_user)
    if not seller_id:
        return redirect(resolve_waiter_return_url(request))

    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
    if order.payment_status != 'pending_payment':
        messages.info(request, '该订单无需再收款')
        return redirect(resolve_waiter_return_url(request))

    if request.method == 'POST':
        result = handle_waiter_pay_post(request, order, _client_ip(request))
        if not result.ok:
            messages.error(request, result.message)
            return redirect('waiter_pay_order', order_id=order.order_id)
        if result.redirect_url:
            if 'success=1' in result.redirect_url:
                fields = sync_waiter_service_status(order)
                if fields:
                    order.save(update_fields=fields)
                messages.success(request, '支付成功')
                return redirect(resolve_waiter_return_url(request))
            if result.redirect_url.startswith('/order/'):
                messages.success(request, '已选择现金，待店家备货后可点「确认已收现金」')
                return redirect(resolve_waiter_return_url(request))
            return redirect(result.redirect_url)
        if result.template_name:
            ctx = build_pay_page_context(order)
            ctx.update(result.extra_context or {})
            ctx['wechat_pay_mode'] = True
            tpl = (
                'waimai/waiter_pay_wechat.html'
                if result.template_name == 'waimai/pay_wechat.html'
                else result.template_name
            )
            return render(request, tpl, ctx)
        return redirect('waiter_pay_order', order_id=order.order_id)

    ctx = build_pay_page_context(order)
    ctx['waiter_pay_mode'] = True
    pending = ctx.get('pending_wechat_record')
    if pending and pending.code_url:
        ctx['code_url'] = pending.code_url
        ctx['out_trade_no'] = pending.out_trade_no
        ctx['use_notify'] = bool((ctx['payment_settings'].public_site_url or '').strip())
        ctx['wechat_pay_mode'] = True
        return render(request, 'waimai/waiter_pay_wechat.html', ctx)

    return render(request, 'waimai/waiter_pay_order.html', ctx)


@require_GET
def waiter_pay_order_status(request, order_id):
    """服务员收款页：轮询微信是否已支付（认工作台登录）"""
    from .payments import poll_wechat_payment
    from .shop_work_auth import get_shop_work_user
    from .waiter_helpers import ensure_waiter_employer, sync_waiter_service_status

    from .staff_account_helpers import PERM_DINING_WAITER, staff_has_permission

    work_user = get_shop_work_user(request)
    if not work_user or not staff_has_permission(work_user, PERM_DINING_WAITER):
        return JsonResponse({'paid': False})
    seller_id = work_user.username if work_user.role == 'seller' else ensure_waiter_employer(work_user)
    if not seller_id:
        return JsonResponse({'paid': False})

    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
    if order.payment_status == 'paid':
        return JsonResponse({'paid': True})
    if order.payment_method == 'wechat':
        poll_wechat_payment(order)
        order.refresh_from_db()
        if order.payment_status == 'paid':
            fields = sync_waiter_service_status(order)
            if fields:
                order.save(update_fields=fields)
    return JsonResponse({'paid': order.payment_status == 'paid'})


from .scroll_helpers import dish_scroll_anchor, redirect_with_anchor


def _shop_cart_redirect(seller_id, keep_cart_open=False, dish_id=None, price_tier=None):
    """加减购物车后跳回店铺；可打开购物车抽屉或定位到某菜品档位卡片"""
    url = f'/shop/?seller_id={seller_id}'
    if keep_cart_open:
        return redirect_with_anchor(url, 'cart')
    anchor = dish_scroll_anchor(dish_id, price_tier) if dish_id else None
    return redirect_with_anchor(url, anchor)


def _shop_cart_context(cart, seller_id):
    """店铺页购物车展示用数据（含数量为 0 的行）"""
    cart_items, subtotal = build_cart_items(cart, seller_id, for_checkout=False)
    from .product_helpers import TIER_LABELS
    cart_summary = [
        {
            'dish': item['dish'],
            'quantity': item['quantity'],
            'subtotal': item['item_total'],
            'unit_price': item['unit_price'],
            'price_tier': item['price_tier'],
            'tier_label': TIER_LABELS.get(item['price_tier'], ''),
            'line_key': item['line_key'],
        }
        for item in cart_items
    ]
    return {
        'cart': cart_summary,
        'cart_count': cart_count_positive(cart),
        'cart_total': subtotal,
        'cart_has_lines': cart_has_lines(cart),
    }


def _shop_cart_json(request, cart, seller_id, shop_profile):
    """无刷新购物车操作成功后，返回可整体替换的购物车外壳。"""
    from django.template.loader import render_to_string

    from .channel_helpers import channel_template_flags, resolve_shop_channel
    from .plugins.dining.buyer_entry import get_buyer_table_session
    from .product_shell_helpers import build_product_shell

    table_session = get_buyer_table_session(request, seller_id)
    shop_channel = resolve_shop_channel(request, seller_id, table_session)
    ctx = {
        'seller_id': seller_id,
        'shop_profile': shop_profile,
        'product_shell': build_product_shell(seller_id),
        **channel_template_flags(shop_channel),
        **_shop_cart_context(cart, seller_id),
    }
    return JsonResponse({
        'ok': True,
        'cart_count': ctx['cart_count'],
        'cart_total': str(ctx['cart_total']),
        'cart_shell_html': render_to_string(
            'waimai/_shop_cart_shell.html', ctx, request=request,
        ),
    })


def _is_cart_fetch(request) -> bool:
    """是否为店铺页的无刷新购物车请求。"""
    return request.headers.get('X-Requested-With') == 'YecaoCart'


def _shop_cart_error(request, message: str):
    """无刷新请求返回白话错误；普通提交继续由原页面显示。"""
    if _is_cart_fetch(request):
        return JsonResponse({'ok': False, 'message': message}, status=400)
    return None


def _shop_page_dishes(seller_id):
    """店铺页商品列表；业态插件可接管目录过滤。"""
    from .product_shell_helpers import get_shop_products_for_sale

    dishes, using_menu = get_shop_products_for_sale(seller_id)
    return dishes, using_menu


def _merge_cart_into_order(order, cart_items, seller_id, distance_km, fulfillment_type):
    """桌码主单：待支付单上合并加点"""
    from decimal import Decimal
    dish_map = {}
    for row in order.dish_items or []:
        did = str(row.get('dish_id', '')).replace('-', '')
        tier = row.get('price_tier', PRICE_TIER_GENERAL)
        dish_map[f'{did}:{tier}'] = dict(row)

    for item in cart_items:
        did = item['dish'].dish_id.hex
        tier = item.get('price_tier', PRICE_TIER_GENERAL)
        map_key = f'{did}:{tier}'
        if map_key in dish_map:
            dish_map[map_key]['quantity'] = int(dish_map[map_key].get('quantity', 0)) + item['quantity']
        else:
            dish_map[map_key] = {
                'line_id': uuid.uuid4().hex,
                'dish_id': did,
                'name': item['dish'].name,
                'price': float(item['unit_price']),
                'quantity': item['quantity'],
                'price_tier': tier,
                'served_count': 0,
            }

    merged = list(dish_map.values())
    subtotal = sum(Decimal(str(r['price'])) * r['quantity'] for r in merged)
    delivery_fee, fee_detail = build_order_pricing(
        seller_id, subtotal, distance_km, fulfillment_type,
    )
    if delivery_fee is None:
        return None
    order.dish_items = merged
    order.subtotal_amount = subtotal
    order.delivery_fee = delivery_fee
    order.delivery_fee_detail = fee_detail
    order.total_amount = subtotal + delivery_fee
    order.save()
    return order


def _shop_render(request, seller_id, cart, shop_profile, error='', extra=None):
    """店铺页统一渲染（含菜单过滤、桌台与下单通道）"""
    from .channel_helpers import (
        auto_pick_single_homepage_channel,
        channel_template_flags,
        dining_plugin_enabled,
        list_homepage_channels,
        resolve_shop_channel,
    )

    from .product_shell_helpers import build_product_shell

    product_shell = build_product_shell(seller_id)
    dishes, using_menu = _shop_page_dishes(seller_id)
    menu_items_map = get_active_menu_items_map(seller_id) if using_menu else {}
    table_session = get_buyer_table_session(request, seller_id)
    auto_pick_single_homepage_channel(request, seller_id, table_session)
    shop_channel = resolve_shop_channel(request, seller_id, table_session)
    need_channel_pick = (not table_session) and (not shop_channel)
    # 本桌进行中的订单：游客/买家回店后可一点打开详情（结账翻台后不再显示）
    table_open_order = get_open_order_for_session(table_session) if table_session else None

    dish_rows = []
    if shop_channel:
        dish_rows = [
            {
                'dish': dish,
                'tier_options': build_dish_tier_options(
                    dish, request.user, seller_id, cart,
                    menu_item=menu_items_map.get(dish.dish_id),
                ),
            }
            for dish in dishes
        ]
    ctx = {
        'dishes': dishes,
        'dish_rows': dish_rows,
        'seller_id': seller_id,
        'shop_profile': shop_profile,
        'using_menu': using_menu,
        'product_shell': product_shell,
        'table_session': table_session,
        'table_label': table_session.display_label() if table_session else '',
        'table_open_order': table_open_order,
        'need_channel_pick': need_channel_pick,
        'dining_plugin_enabled': dining_plugin_enabled(seller_id),
        'channel_options': list_homepage_channels(seller_id) if (need_channel_pick or not table_session) else [],
        'error': error or request.GET.get('error', ''),
        **channel_template_flags(shop_channel),
        **_shop_cart_context(cart, seller_id),
    }
    if extra:
        ctx.update(extra)
    return render(request, 'waimai/shop.html', ctx)


def shop_page(request):
    """店铺页面：选通道 + 菜品展示 + 购物车 + 下单确认"""
    from .channel_helpers import (
        CHANNEL_DELIVERY,
        build_address_and_distance,
        clear_shop_channel,
        get_shop_channel,
        require_shop_channel,
        try_set_homepage_channel,
    )

    seller_id = request.GET.get('seller_id', 'seller_001')
    cart = get_shop_cart(request.session, seller_id)
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    delivery_settings = get_delivery_settings(seller_id)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        table_sess = get_buyer_table_session(request, seller_id)

        if action == 'set_channel':
            # 批次 C：换通道时清空购物车，避免外卖菜带进打包
            old_channel = get_shop_channel(request.session, seller_id)
            new_channel = (request.POST.get('channel') or '').strip()
            ok, msg = try_set_homepage_channel(
                request, seller_id, new_channel, table_sess,
            )
            if not ok:
                return _shop_render(request, seller_id, cart, shop_profile, error=msg)
            if old_channel and new_channel and old_channel != new_channel:
                set_shop_cart(request.session, seller_id, {})
            return _shop_cart_redirect(seller_id)

        if action == 'clear_channel':
            if table_sess:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='扫桌码模式下为堂食通道，不能切换为外卖或打包。',
                )
            clear_shop_channel(request.session, seller_id)
            # 批次 C：点「更换通道」时一并清空购物车
            set_shop_cart(request.session, seller_id, {})
            return _shop_cart_redirect(seller_id)

        if action == 'add_to_cart':
            dish_id = request.POST.get('dish_id')
            tier = request.POST.get('price_tier', PRICE_TIER_GENERAL)
            cart = normalize_cart_keys(cart)
            ft, ch_err = require_shop_channel(request, seller_id, table_sess)
            if ch_err:
                fetch_error = _shop_cart_error(request, ch_err)
                if fetch_error:
                    return fetch_error
                return _shop_render(request, seller_id, cart, shop_profile, error=ch_err)
            ok_admit, admit_msg = check_order_admission(seller_id, ft)
            if not ok_admit:
                fetch_error = _shop_cart_error(request, admit_msg)
                if fetch_error:
                    return fetch_error
                return _shop_render(request, seller_id, cart, shop_profile, error=admit_msg)
            try:
                dish = Dish.objects.get(dish_id=dish_id, seller_id=seller_id, is_active=True)
            except Dish.DoesNotExist:
                fetch_error = _shop_cart_error(request, '商品不存在或已下架')
                if fetch_error:
                    return fetch_error
                return _shop_render(request, seller_id, cart, shop_profile, error='商品不存在或已下架')
            from .plugin_runtime.registry import is_plugin_enabled

            if is_plugin_enabled('dining', seller_id) and not dish_visible_on_shop(seller_id, dish_id):
                fetch_error = _shop_cart_error(request, '该菜品不在当前使用中的菜单清单里')
                if fetch_error:
                    return fetch_error
                return _shop_render(request, seller_id, cart, shop_profile, error='该菜品不在当前使用中的菜单清单里')
            line_key = cart_line_key(dish_id, tier)
            qty = cart.get(line_key, 0) + 1
            ok, msg = validate_tier_purchase(dish, tier, request.user, seller_id, qty, cart)
            if not ok:
                fetch_error = _shop_cart_error(request, msg)
                if fetch_error:
                    return fetch_error
                return _shop_render(request, seller_id, cart, shop_profile, error=msg)
            cart[line_key] = qty
            set_shop_cart(request.session, seller_id, cart)
            if _is_cart_fetch(request):
                return _shop_cart_json(request, cart, seller_id, shop_profile)
            if request.POST.get('stay_in_cart'):
                return _shop_cart_redirect(seller_id, keep_cart_open=True)
            return _shop_cart_redirect(seller_id, dish_id=dish_id, price_tier=tier)

        if action == 'decrease_from_cart':
            line_key = request.POST.get('line_key') or cart_line_key(
                request.POST.get('dish_id'), request.POST.get('price_tier', PRICE_TIER_GENERAL),
            )
            cart = normalize_cart_keys(cart)
            if line_key in cart:
                cart[line_key] = cart.get(line_key, 0) - 1
                if cart[line_key] < 0:
                    cart[line_key] = 0
            set_shop_cart(request.session, seller_id, cart)
            if _is_cart_fetch(request):
                return _shop_cart_json(request, cart, seller_id, shop_profile)
            return _shop_cart_redirect(seller_id, keep_cart_open=True)

        if action == 'remove_from_cart':
            line_key = request.POST.get('line_key') or cart_line_key(
                request.POST.get('dish_id'), request.POST.get('price_tier', PRICE_TIER_GENERAL),
            )
            cart = normalize_cart_keys(cart)
            cart.pop(line_key, None)
            set_shop_cart(request.session, seller_id, cart)
            if _is_cart_fetch(request):
                return _shop_cart_json(request, cart, seller_id, shop_profile)
            return _shop_cart_redirect(seller_id, keep_cart_open=True)

        if action == 'update_cart':
            line_key = request.POST.get('line_key') or cart_line_key(
                request.POST.get('dish_id'), request.POST.get('price_tier', PRICE_TIER_GENERAL),
            )
            qty = int(request.POST.get('quantity', 1))
            if qty < 0:
                qty = 0
            cart = normalize_cart_keys(cart)
            cart[line_key] = qty
            set_shop_cart(request.session, seller_id, cart)
            return _shop_cart_redirect(seller_id, keep_cart_open=True)

        if action == 'checkout':
            from .channel_helpers import CHANNEL_DINE_IN
            from .guest_order_helpers import normalize_guest_nickname

            is_logged_buyer = (
                request.user.is_authenticated and request.user.role == 'buyer'
            )
            # 堂食 + 有效桌台会话：游客也可结算；外卖/打包仍须登录买家
            is_guest_dine = bool(table_sess and not is_logged_buyer)
            if not is_logged_buyer and not is_guest_dine:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='请先登录买家账号再下单（堂食扫桌码可免登录）',
                )

            cart_items, subtotal = build_cart_items(cart, seller_id, for_checkout=True)
            if not cart_items:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='请至少选择一份数量大于 0 的商品再结算',
                )

            fulfillment_type, ch_err = require_shop_channel(request, seller_id, table_sess)
            if ch_err:
                return _shop_render(request, seller_id, cart, shop_profile, error=ch_err)
            if is_guest_dine and fulfillment_type != CHANNEL_DINE_IN:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='未登录只能堂食下单，外卖/打包请先登录',
                )
            ok_admit, admit_msg = check_order_admission(seller_id, fulfillment_type)
            if not ok_admit:
                return _shop_render(request, seller_id, cart, shop_profile, error=admit_msg)

            for item in cart_items:
                ok, msg = validate_tier_purchase(
                    item['dish'], item['price_tier'], request.user, seller_id, item['quantity'], cart,
                )
                if not ok:
                    return _shop_render(request, seller_id, cart, shop_profile, error=msg)

            delivery_address, distance_km = build_address_and_distance(
                request.POST, shop_profile, fulfillment_type,
            )
            delivery_fee, fee_detail = build_order_pricing(
                seller_id, subtotal, distance_km, fulfillment_type,
            )
            if delivery_fee is None:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='配送距离超过该店铺最远配送范围',
                )

            total_amount = subtotal + delivery_fee
            from .channel_helpers import channel_template_flags
            return render(request, 'waimai/confirm_order.html', {
                'cart_items': cart_items,
                'subtotal': subtotal,
                'delivery_fee': delivery_fee,
                'delivery_fee_detail': fee_detail,
                'free_delivery': (
                    delivery_fee == 0 and subtotal > 0 and fulfillment_type == CHANNEL_DELIVERY
                ),
                'total_amount': total_amount,
                'distance_km': distance_km,
                'delivery_address': delivery_address,
                'fulfillment_type': fulfillment_type,
                'channel_locked': True,
                'seller_id': seller_id,
                'shop_profile': shop_profile,
                'table_label': table_sess.display_label() if table_sess else '',
                'is_guest_checkout': is_guest_dine,
                'guest_nickname': normalize_guest_nickname(
                    request.POST.get('guest_nickname', ''),
                ),
                **channel_template_flags(fulfillment_type),
            })

    return _shop_render(request, seller_id, cart, shop_profile, extra={
        'success': request.GET.get('success', False),
        'success_fulfillment': request.GET.get('fulfillment', ''),
    })


def my_deliveries(request):
    """旧地址：统一引导到店铺工作台骑手视角"""
    work_redirect = _redirect_to_shop_work(request, 'rider')
    if work_redirect:
        return work_redirect
    return redirect('directory')


def rider_delivery_history(request):
    """骑手配送记录：仅工作台骑手会话可看"""
    from .shop_work_auth import get_shop_work_user
    from .staff_account_helpers import PERM_DINING_RIDER, staff_has_permission

    work_user = get_shop_work_user(request)
    if not work_user or not staff_has_permission(work_user, PERM_DINING_RIDER):
        work_redirect = _redirect_to_shop_work(request, 'rider')
        if work_redirect:
            return work_redirect
        return redirect('directory')

    rider_id = work_user.username
    completed_orders = (
        DeliveryOrder.objects.filter(
            rider_id=rider_id,
            delivery_status='completed',
        )
        .select_related('buy_order')
        .order_by('-completed_at', '-created_at')
    )

    seller_ids = {d.buy_order.seller_id for d in completed_orders}
    shop_names = {
        s.seller_id: s.shop_name
        for s in ShopProfile.objects.filter(seller_id__in=seller_ids)
    }

    history_rows = [
        {
            'delivery': d,
            'shop_name': shop_names.get(d.buy_order.seller_id, d.buy_order.seller_id),
        }
        for d in completed_orders
    ]

    return render(request, 'waimai/rider_delivery_history.html', {
        'rider_id': rider_id,
        'history_rows': history_rows,
        'total_count': len(history_rows),
    })




def register(request):
    """买家注册（仅买家）"""
    from .experience_helpers import experience_hint_context, touch_online_user

    if request.method == 'POST':
        form = BuyerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            from .single_login_helpers import claim_single_login
            claim_single_login(request, user)
            touch_online_user(user)
            return redirect('directory')
    else:
        form = BuyerRegistrationForm()
    ctx = {'form': form, **experience_hint_context()}
    return render(request, 'waimai/register.html', ctx)


def shop_register(request):
    """店铺注册服务器：创建卖家账号并进入名录"""
    from .experience_helpers import experience_hint_context, touch_online_user

    if request.method == 'POST':
        form = ShopRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            from .single_login_helpers import claim_single_login
            claim_single_login(request, user)
            touch_online_user(user)
            return redirect('seller_panel')
    else:
        form = ShopRegistrationForm()
    ctx = {'form': form, **experience_hint_context()}
    return render(request, 'waimai/shop_register.html', ctx)


@login_required
@require_GET
def seller_pending_orders_json(request):
    """店主订单页轮询用：返回待备货新单数量与最新时间戳（毫秒）。

    仅供网页内新单强提醒：页面开着时定时来查，有新单就持续提醒。
    """
    if request.user.role != 'seller':
        return JsonResponse({'ok': False, 'count': 0, 'latest_ts': 0}, status=403)
    seller_id = request.user.username
    from .order_alert_helpers import list_shop_new_order_links, query_shop_new_orders

    qs = query_shop_new_orders(seller_id)
    count = qs.count()
    latest = qs.order_by('-created_at').values_list('created_at', flat=True).first()
    latest_ts = int(latest.timestamp() * 1000) if latest else 0
    from .operating_helpers import build_order_alert_config

    return JsonResponse({
        'ok': True, 'count': count, 'latest_ts': latest_ts,
        'items': list_shop_new_order_links(seller_id),
        'config': build_order_alert_config(seller_id),
    })


@login_required
def seller_panel(request):
    """卖家管理入口：默认进入订单页（仅店主生态登录）"""
    if request.user.role != 'seller':
        return redirect('/accounts/login/')
    return redirect('seller_panel_section', section='orders')


@login_required
def seller_panel_section(request, section):
    """卖家管理分区（仅店主生态登录）"""
    if request.user.role != 'seller':
        return redirect('/accounts/login/')

    if section in ('dishes', 'menus'):
        return redirect('seller_panel_section', section='products')

    if section in ('riders', 'waiters', 'kitchen'):
        return redirect('seller_panel_section', section='workbench')

    valid = (
        'orders', 'products', 'operating', 'dine', 'workbench', 'delivery',
        'payment', 'audit', 'homepage', 'plugins',
    )
    if section not in valid:
        return redirect('seller_panel_section', section='orders')

    seller_id = request.user.username

    # 插件认领的分区：未启用则不许进（第一刀：堂食营业）
    from .plugin_runtime.registry import (
        is_plugin_enabled,
        plugin_owns_seller_section,
    )

    owner_plugin = plugin_owns_seller_section(section)
    if owner_plugin and not is_plugin_enabled(owner_plugin, seller_id):
        from django.contrib import messages

        messages.warning(
            request,
            '该功能由插件提供，当前店铺已停用对应插件。可在「插件试验」中重新启用。',
        )
        return redirect('seller_panel_section', section='plugins')

    if request.method == 'POST':
        response = None
        if section == 'operating':
            response = handle_operating_post(request, seller_id)
        elif section == 'dine':
            response = handle_dine_post(request, seller_id)
        elif section == 'products':
            response = handle_products_post(request, seller_id)
        elif section == 'workbench':
            from .workbench_handlers import handle_seller_workbench_post
            response = handle_seller_workbench_post(request, seller_id)
        elif section == 'homepage':
            from .home_page_handlers import handle_home_page_post
            response = handle_home_page_post(request, seller_id)
        elif section == 'plugins':
            from django.contrib import messages

            from .plugin_runtime.registry import set_plugin_enabled

            action = (request.POST.get('action') or '').strip()
            plugin_id = (request.POST.get('plugin_id') or '').strip()
            if action == 'enable_plugin' and plugin_id:
                ok, msg = set_plugin_enabled(plugin_id, seller_id, True)
                (messages.success if ok else messages.error)(request, msg)
            elif action == 'disable_plugin' and plugin_id:
                ok, msg = set_plugin_enabled(plugin_id, seller_id, False)
                (messages.success if ok else messages.error)(request, msg)
            from .scroll_helpers import redirect_with_anchor

            return redirect_with_anchor(
                reverse('seller_panel_section', kwargs={'section': 'plugins'}),
                'plugin-list',
            )
        elif section == 'audit':
            response = None
        else:
            response = handle_seller_post(request, seller_id, section)
        if response:
            return response

    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    from .order_message_helpers import shop_unread_message_summary
    from .plugin_runtime.registry import collect_seller_nav_items

    unread_summary = shop_unread_message_summary(seller_id)
    context = {
        'section': section,
        'seller_id': seller_id,
        'shop_profile': shop_profile,
        # 大标签「订单管理」红点：全店未读顾客沟通总数（各分区都带上）
        'shop_unread_msg_total': unread_summary['total'],
        # 插件试验：导航由核心 + 已启用插件拼装
        'seller_nav_items': collect_seller_nav_items(seller_id),
    }

    if section == 'orders':
        from .order_search_helpers import (
            ORDER_DATE_RANGE_CHOICES,
            build_order_search_querystring,
            parse_seller_order_search,
            query_seller_orders,
        )
        from .models import BuyOrder

        order_search = parse_seller_order_search(request.GET)
        orders = list(query_seller_orders(seller_id, order_search))
        from .order_message_helpers import unread_map_for_orders

        unread_map = unread_map_for_orders(orders, side='shop')
        for o in orders:
            o.unread_msg_count = unread_map.get(o.order_id, 0)
        from .order_shell_helpers import (
            build_order_shell,
            fulfillment_filter_choices,
            order_search_placeholder,
        )

        for o in orders:
            o.order_shell = build_order_shell(o)
        context['orders'] = orders
        context['order_search'] = order_search
        context['order_search_placeholder'] = order_search_placeholder(seller_id)
        context['order_date_range_choices'] = ORDER_DATE_RANGE_CHOICES
        context['order_status_choices'] = BuyOrder.ORDER_STATUS_CHOICES
        context['payment_status_choices'] = BuyOrder.PAYMENT_STATUS_CHOICES
        context['fulfillment_type_choices'] = fulfillment_filter_choices(seller_id)
        from .order_alert_helpers import list_shop_new_order_links

        new_order_links = list_shop_new_order_links(seller_id)
        context['seller_new_order_links'] = new_order_links
        context['seller_new_order_ts'] = max((x['created_ts'] for x in new_order_links), default=0)
        # 页顶：有未读顾客沟通的订单（不受当前搜索条件限制）
        context['shop_unread_msg_orders'] = unread_summary['orders']
    elif section == 'products':
        from .menu_helpers import find_menu_profile_by_pick_id, get_active_menu_profile
        from .product_shell_helpers import build_product_shell
        from .sales_helpers import get_dish_sales_rankings
        operating = get_operating_settings(seller_id)
        product_shell = build_product_shell(seller_id)
        context['operating'] = operating
        context['product_shell'] = product_shell
        context['dishes'] = Dish.objects.filter(seller_id=seller_id).order_by('sort_order', 'name')
        context['sales_rankings'] = get_dish_sales_rankings(seller_id)
        profiles = []
        active_profile = None
        selected = None
        if product_shell['show_menu_catalog']:
            profiles = list(MenuProfile.objects.filter(
                seller_id=seller_id,
            ).prefetch_related('items__dish').order_by('-updated_at'))
            active_profile = get_active_menu_profile(seller_id)
            pick_id = request.GET.get('profile', '').strip()
            selected = find_menu_profile_by_pick_id(seller_id, pick_id) if pick_id else None
            if not selected:
                selected = active_profile or (profiles[0] if profiles else None)
        context['menu_profiles'] = profiles
        context['selected_profile'] = selected
        context['active_profile'] = active_profile
        context['edit_dish_id'] = request.GET.get('edit', '').strip()
    elif section == 'operating':
        operating = get_operating_settings(seller_id)
        context['operating'] = operating
        context['status_form'] = ShopStatusSettingsForm(instance=operating)
        # 营业中 = 未打烊且未暂停
        context['is_shop_open'] = (
            (not operating.closed_for_today) and (not operating.pause_new_orders)
        )
    elif section == 'dine':
        from .models import ShopTable, VirtualTableCode
        operating = get_operating_settings(seller_id)
        context['operating'] = operating
        context['operating_form'] = ShopOperatingSettingsForm(instance=operating)
        context['wait_time_rules'] = list(operating.wait_time_rules.all())
        tables = sort_shop_tables(list(ShopTable.objects.filter(seller_id=seller_id)))
        for t in tables:
            t.scan_path = build_table_scan_path(seller_id, t.qr_token)
        context['tables'] = tables
        if operating.share_table_enabled and operating.share_table_mode == 'virtual':
            vcodes = sort_virtual_codes(list(VirtualTableCode.objects.filter(seller_id=seller_id)))
            for v in vcodes:
                v.scan_path = build_virtual_scan_path(seller_id, v.qr_token)
                v.is_busy = virtual_code_is_busy(v)
            context['virtual_codes'] = vcodes
        if operating.share_table_enabled and operating.share_table_mode == 'waiter':
            context['share_sessions'] = TableSession.objects.filter(
                seller_id=seller_id, session_type='share_waiter', status='open',
            )[:20]
    elif section == 'workbench':
        import base64

        from .forms import (
            CreateStaffAccountForm,
            EditStaffAccountForm,
            ShopWorkbenchSettingsForm,
        )
        from .staff_account_helpers import (
            AttendanceFilterForm,
            attendance_status_options,
            build_mobile_share_url,
            build_staff_status_rows,
            get_shop_staff_users,
            query_attendance_logs,
            staff_account_type_label,
            staff_job_title,
            staff_permission_codes,
        )
        from .workbench_qr import build_work_login_qr_png

        from django.conf import settings

        operating = get_operating_settings(seller_id)
        workbench_form = ShopWorkbenchSettingsForm(instance=operating)
        from .plugins.fulfillment.ownership import fulfillment_plugin_enabled
        if not fulfillment_plugin_enabled(seller_id):
            for fname in ('delivery_handoff_mode', 'auto_dispatch_enabled'):
                workbench_form.fields.pop(fname, None)
        context['workbench_settings_form'] = workbench_form
        context['management_staff_form'] = CreateStaffAccountForm(
            seller_id=seller_id,
            account_type='management',
        )
        context['employee_staff_form'] = CreateStaffAccountForm(
            seller_id=seller_id,
            account_type='employee',
        )
        attendance_filter_form = AttendanceFilterForm(request.GET or None, seller_id=seller_id)
        attendance_filters = attendance_filter_form.cleaned_data if attendance_filter_form.is_valid() else {}
        staff_users = list(get_shop_staff_users(seller_id))
        staff_users.sort(key=lambda user: (
            staff_account_type_label(user),
            staff_job_title(user),
            user.date_joined,
            user.username,
        ))
        staff_account_rows = []
        for staff_user in staff_users:
            staff_account_rows.append({
                'user': staff_user,
                'account_type_label': staff_account_type_label(staff_user),
                'job_title': staff_job_title(staff_user),
                'permission_codes': sorted(staff_permission_codes(staff_user)),
                'edit_form': EditStaffAccountForm(
                    seller_id=seller_id,
                    user=staff_user,
                ),
            })
        context['staff_account_rows'] = staff_account_rows
        attendance_logs = list(query_attendance_logs(
            seller_id,
            operating.attendance_retention_days,
            filters=attendance_filters,
        )[:100])
        context['staff_status_rows'] = build_staff_status_rows(staff_users, attendance_logs)
        context['attendance_logs'] = attendance_logs
        context['attendance_status_choices'] = attendance_status_options()
        context['attendance_filter_form'] = attendance_filter_form
        work_login_url = ''
        work_qr_data_url = ''
        work_mobile_url = ''
        work_mobile_qr_data_url = ''
        if shop_profile and (shop_profile.shop_code or '').strip():
            work_login_url = request.build_absolute_uri(
                reverse('shop_work', kwargs={'shop_code': shop_profile.shop_code.strip()}),
            )
            png = build_work_login_qr_png(work_login_url)
            work_qr_data_url = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
            if settings.DEBUG:
                mobile_candidate = build_mobile_share_url(work_login_url)
                if mobile_candidate and mobile_candidate != work_login_url:
                    work_mobile_url = mobile_candidate
                    mobile_png = build_work_login_qr_png(work_mobile_url)
                    work_mobile_qr_data_url = 'data:image/png;base64,' + base64.b64encode(mobile_png).decode('ascii')
        context['work_login_url'] = work_login_url
        context['work_qr_data_url'] = work_qr_data_url
        context['work_mobile_url'] = work_mobile_url
        context['work_mobile_qr_data_url'] = work_mobile_qr_data_url
    elif section == 'delivery':
        from .plugins.fulfillment.ownership import fulfillment_plugin_enabled
        if not fulfillment_plugin_enabled(seller_id):
            messages.error(request, '履约配送插件未启用，请先在「插件」里打开')
            return redirect('seller_panel_section', section='plugins')
        context['settings_form'] = ShopDeliverySettingsForm(
            instance=get_delivery_settings(seller_id)
        )
    elif section == 'payment':
        from .experience_helpers import experience_site_enabled, seller_blocked_from_real_wechat
        from .payments import get_payment_settings
        from .plugin_runtime.registry import is_plugin_enabled
        from .rider_cash_helpers import rider_cash_summary

        fulfillment_on = is_plugin_enabled('fulfillment', seller_id)
        payment_form = ShopPaymentSettingsForm(
            instance=get_payment_settings(seller_id)
        )
        # 履约关闭时不展示「外卖货到付款」开关（能力归属履约）
        if not fulfillment_on and 'enable_cod' in payment_form.fields:
            del payment_form.fields['enable_cod']
        context['payment_form'] = payment_form
        context['experience_block_wechat'] = seller_blocked_from_real_wechat(seller_id)
        context['experience_site'] = experience_site_enabled()
        context['show_rider_cash'] = fulfillment_on
        context['rider_cash'] = rider_cash_summary(seller_id) if fulfillment_on else None
    elif section == 'audit':
        from .audit_helpers import (
            can_view_tech_logs,
            query_audit_logs,
            read_tech_log_tail,
            write_audit_log,
        )

        scope = (request.GET.get('scope') or 'all').strip()
        show_tech = (request.GET.get('tech') or '').strip() == '1'
        only_me = scope == 'mine'
        write_audit_log(
            action_code='view_audit',
            summary='查看操作审计' + ('（仅本人）' if only_me else '（本店全部）'),
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        context['audit_logs'] = list(query_audit_logs(
            seller_id=seller_id,
            only_username=request.user.username if only_me else None,
            limit=100,
        ))
        context['audit_scope'] = 'mine' if only_me else 'all'
        context['show_tech'] = False
        context['runtime_log_lines'] = []
        context['error_payment_log_lines'] = []
        if show_tech and can_view_tech_logs(request.user):
            write_audit_log(
                action_code='view_tech_log',
                summary='查看技术运行日志摘要',
                seller_id=seller_id,
                actor=request.user,
                request=request,
            )
            context['show_tech'] = True
            context['runtime_log_lines'] = read_tech_log_tail('runtime.log', 150)
            context['error_payment_log_lines'] = read_tech_log_tail('error_payment.log', 150)
    elif section == 'homepage':
        from .home_page_helpers import (
            BLOCK_CUSTOM,
            MAX_SHOP_CUSTOM_BLOCKS,
            SERVER_ONLY_BLOCK_TYPES,
            SHOP_LEGACY_BLOCK_TYPES,
            block_dom_id,
            count_shop_custom_blocks,
            ensure_home_page_for_seller,
            get_shop_block_spec,
        )

        page = ensure_home_page_for_seller(seller_id, shop_profile)
        # 所有积木（含自定义）统一按排序数字比大小
        blocks = list(
            page.blocks.exclude(block_type__in=SERVER_ONLY_BLOCK_TYPES | SHOP_LEGACY_BLOCK_TYPES)
            .order_by('sort_order', 'block_type')
        )
        for b in blocks:
            b.spec = get_shop_block_spec(b.block_type)
            b.dom_id = block_dom_id(b)
            b.is_custom = b.block_type == BLOCK_CUSTOM
            if b.is_custom:
                b.fold_title = (b.title or '').strip() or '自定义积木'
            else:
                b.fold_title = b.spec.label if b.spec else b.block_type
            from .home_block_media import block_display_image_src
            from .home_page_helpers import BLOCK_DIRECTORY, BLOCK_ORDER_CTA
            b.display_image_src = block_display_image_src(b)
            b.shows_rich_media = b.block_type not in (BLOCK_ORDER_CTA, BLOCK_DIRECTORY)
        custom_count = count_shop_custom_blocks(page)
        from .home_block_media import photo_quota_hint
        context.update(photo_quota_hint(request.user))
        context['home_page'] = page
        context['home_blocks'] = blocks
        context['custom_block_count'] = custom_count
        context['max_custom_blocks'] = MAX_SHOP_CUSTOM_BLOCKS
        context['can_add_custom_block'] = custom_count < MAX_SHOP_CUSTOM_BLOCKS
        context['save_block_action_name'] = 'save_home_block'
        context['delete_block_action_name'] = 'delete_home_block'
        context['showcase_preview_url'] = '/'
        if shop_profile and (shop_profile.shop_code or '').strip():
            context['showcase_preview_url'] = f"/s/{shop_profile.shop_code.strip()}/home/"
    elif section == 'plugins':
        from .plugin_runtime.registry import is_plugin_enabled, list_plugins

        plugin_rows = []
        for p in list_plugins():
            plugin_rows.append({
                'id': p.id,
                'name': p.name,
                'description': p.description,
                'enabled': is_plugin_enabled(p.id, seller_id),
                'nav_labels': [i.label for i in p.seller_nav_items()],
            })
        context['plugin_rows'] = plugin_rows

    return render(request, f'waimai/seller/{section}.html', context)


def place_order(request):
    """创建订单（服务端重新验价）。堂食游客持有效桌台会话可免登录；外卖/打包仍须登录买家。"""
    if request.method != 'POST':
        return redirect('shop')

    from .channel_helpers import (
        CHANNEL_DINE_IN,
        build_address_and_distance,
        validate_place_order_channel,
    )
    from .guest_order_helpers import (
        apply_guest_onsite_cash,
        normalize_guest_nickname,
        resolve_order_buyer_id,
    )

    is_logged_buyer = (
        request.user.is_authenticated and request.user.role == 'buyer'
    )
    if request.user.is_authenticated and not is_logged_buyer:
        # 店主/员工等非买家账号不能走买家下单口
        return redirect('shop')

    seller_id = request.POST.get('seller_id', 'seller_001')
    cart = get_shop_cart(request.session, seller_id)
    if not cart:
        return redirect(f'/shop/?seller_id={seller_id}')

    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    table_sess = get_buyer_table_session(request, seller_id)
    fulfillment_type, ch_err = validate_place_order_channel(
        request, seller_id, request.POST.get('fulfillment_type'), table_sess,
    )
    if ch_err:
        messages.error(request, ch_err)
        return redirect(f'/shop/?seller_id={seller_id}&error={ch_err}')

    is_guest = not is_logged_buyer
    if is_guest:
        if fulfillment_type != CHANNEL_DINE_IN or not table_sess:
            messages.error(request, '未登录只能通过扫桌码堂食下单，外卖/打包请先登录')
            return redirect(f'/shop/?seller_id={seller_id}')

    if fulfillment_type == CHANNEL_DINE_IN and not table_sess:
        messages.error(request, '堂食请扫桌上的二维码进入')
        return redirect(f'/shop/?seller_id={seller_id}&error=堂食请扫桌码进入')
    if fulfillment_type == CHANNEL_DINE_IN and not request.POST.get('dine_in_at_shop'):
        # 扫桌码进店已视为在店；仍要求勾选时：桌码会话可免勾
        if not table_sess:
            messages.error(request, '堂食下单须勾选「我已在店内」')
            return redirect(f'/shop/?seller_id={seller_id}&error=堂食须勾选已在店内')

    delivery_address, distance_km = build_address_and_distance(
        request.POST, shop_profile, fulfillment_type,
    )

    cart_items, subtotal = build_cart_items(cart, seller_id, for_checkout=True)
    if not cart_items:
        return redirect(f'/shop/?seller_id={seller_id}')

    ok_admit, admit_msg = check_order_admission(seller_id, fulfillment_type)
    if not ok_admit:
        return redirect(f'/shop/?seller_id={seller_id}&error={admit_msg}')

    for item in cart_items:
        ok, msg = validate_tier_purchase(
            item['dish'], item['price_tier'], request.user, seller_id, item['quantity'], cart,
        )
        if not ok:
            return redirect(f'/shop/?seller_id={seller_id}&error={msg}')

    delivery_fee, fee_detail = build_order_pricing(
        seller_id, subtotal, distance_km, fulfillment_type,
    )
    if delivery_fee is None:
        return redirect(f'/shop/?seller_id={seller_id}&error=距离超过配送范围')

    total_amount = subtotal + delivery_fee
    guest_nickname = normalize_guest_nickname(request.POST.get('guest_nickname', ''))
    buyer_id = resolve_order_buyer_id(request)

    dish_items_json = []
    for item in cart_items:
        dish_items_json.append({
            'line_id': uuid.uuid4().hex,
            'dish_id': item['dish'].dish_id.hex,
            'name': item['dish'].name,
            'price': float(item['unit_price']),
            'quantity': item['quantity'],
            'price_tier': item['price_tier'],
            'served_count': 0,
        })

    table_label = ''
    order_kind = 'normal'
    if table_sess:
        table_label = table_sess.display_label()
        if table_sess.session_type == 'main':
            order_kind = 'table_main'
            open_order = get_open_order_for_session(table_sess)
            if open_order and open_order.payment_status == 'pending_payment':
                merged = _merge_cart_into_order(
                    open_order, cart_items, seller_id, distance_km, fulfillment_type,
                )
                if merged:
                    # 合并加点时若原单无称呼、本次填了，补上称呼
                    if guest_nickname and not (merged.guest_nickname or '').strip():
                        merged.guest_nickname = guest_nickname
                        merged.save(update_fields=['guest_nickname', 'updated_at'])
                    increment_menu_sold_counts(seller_id, cart_items)
                    set_shop_cart(request.session, seller_id, {})
                    if is_guest:
                        if not merged.payment_method:
                            apply_guest_onsite_cash(merged)
                        return redirect(
                            f'/order/{merged.order_id}/?cash_pending=1&dine_in=1'
                        )
                    return redirect('pay_order', order_id=merged.order_id)
        elif table_sess.session_type == 'virtual':
            order_kind = 'virtual'
        elif table_sess.session_type == 'share_waiter':
            order_kind = 'share_waiter'

    order = BuyOrder.objects.create(
        buyer_id=buyer_id,
        seller_id=seller_id,
        total_amount=total_amount,
        subtotal_amount=subtotal,
        delivery_fee=delivery_fee,
        delivery_fee_detail=fee_detail,
        dish_items=dish_items_json,
        payment_status='pending_payment',
        order_status='awaiting_payment',
        delivery_address=delivery_address,
        fulfillment_type=fulfillment_type,
        distance_km=distance_km,
        table_session=table_sess,
        table_label=table_label,
        order_kind=order_kind,
        guest_nickname=guest_nickname,
    )

    increment_menu_sold_counts(seller_id, cart_items)
    set_shop_cart(request.session, seller_id, {})
    from .audit_helpers import write_audit_log
    write_audit_log(
        action_code='order_place',
        summary=f'{"游客" if is_guest else "买家"}下单 {order.get_display_order_no()} · ¥{order.total_amount}',
        seller_id=seller_id,
        actor=request.user if is_logged_buyer else None,
        target_type='order',
        target_id=str(order.order_id),
        request=request,
    )

    # 游客堂食：直接现场付现金，跳过在线支付页
    if is_guest:
        apply_guest_onsite_cash(order)
        return redirect(f'/order/{order.order_id}/?cash_pending=1&dine_in=1')

    return redirect('pay_order', order_id=order.order_id)


def pay_order(request, order_id):
    """待支付页：多支付方式选择 / 微信扫码。游客堂食单靠桌台会话认领。"""
    from .guest_order_helpers import buyer_or_guest_can_access_order

    order = get_object_or_404(BuyOrder, order_id=order_id)
    table_sess = get_buyer_table_session(request, order.seller_id)
    if not buyer_or_guest_can_access_order(request, order, table_sess):
        if request.user.is_authenticated:
            return redirect('order_history')
        return redirect('login')

    if order.payment_status != 'pending_payment':
        if order.is_guest_order():
            return redirect('order_detail', order_id=order.order_id)
        return redirect('order_history')

    if order.is_cash_awaiting_confirm():
        return redirect(f'/order/{order.order_id}/?cash_pending=1')

    # 游客堂食单不应进在线支付页：补走现场付
    if order.is_guest_order() and order.is_dine_in():
        from .guest_order_helpers import apply_guest_onsite_cash
        apply_guest_onsite_cash(order)
        return redirect(f'/order/{order.order_id}/?cash_pending=1&dine_in=1')

    ctx = build_pay_page_context(order)

    if request.method == 'POST':
        method = request.POST.get('payment_method', '').strip()
        result = initiate_payment(order, method, _client_ip(request))
        if not result.ok:
            messages.error(request, result.message)
            return redirect('pay_order', order_id=order.order_id)
        if result.redirect_url:
            return redirect(result.redirect_url)
        if result.template_name:
            ctx.update(result.extra_context or {})
            ctx['wechat_pay_mode'] = True
            return render(request, result.template_name, ctx)
        return redirect('pay_order', order_id=order.order_id)

    pending = ctx.get('pending_wechat_record')
    if pending and pending.code_url:
        ctx['code_url'] = pending.code_url
        ctx['out_trade_no'] = pending.out_trade_no
        ctx['use_notify'] = bool((ctx['payment_settings'].public_site_url or '').strip())
        ctx['wechat_pay_mode'] = True
        return render(request, 'waimai/pay_wechat.html', ctx)

    return render(request, 'waimai/pay_order.html', ctx)


@require_GET
def pay_order_status(request, order_id):
    """买家扫码等待时轮询：是否已支付（游客堂食不走此页，但仍认会话归属）"""
    from .guest_order_helpers import buyer_or_guest_can_access_order

    order = get_object_or_404(BuyOrder, order_id=order_id)
    table_sess = get_buyer_table_session(request, order.seller_id)
    if not buyer_or_guest_can_access_order(request, order, table_sess):
        return JsonResponse({'paid': False}, status=403)
    if order.payment_status == 'paid':
        return JsonResponse({'paid': True})
    if order.payment_method == 'wechat':
        poll_wechat_payment(order)
        order.refresh_from_db()
    return JsonResponse({'paid': order.payment_status == 'paid'})


@csrf_exempt
@require_POST
def wechat_pay_notify(request):
    """微信支付异步通知（须公网 HTTPS 可达）"""
    body, status = handle_wechat_notify(request.body)
    return HttpResponse(body, content_type='application/xml', status=status)


@login_required
def order_history(request):
    """买家历史订单"""
    if request.user.role != 'buyer':
        return redirect('directory')

    from .order_message_helpers import unread_map_for_orders

    orders = list(
        BuyOrder.objects.filter(buyer_id=request.user.username)
        .select_related('delivery_order')
        .order_by('-created_at')
    )
    seller_ids = {o.seller_id for o in orders}
    shop_names = {
        s.seller_id: s.shop_name
        for s in ShopProfile.objects.filter(seller_id__in=seller_ids)
    }
    unread_map = unread_map_for_orders(orders, side='buyer')
    order_rows = [
        {
            'order': o,
            'shop_name': shop_names.get(o.seller_id, o.seller_id),
            'unread_msg_count': unread_map.get(o.order_id, 0),
        }
        for o in orders
    ]
    return render(request, 'waimai/order_history.html', {'order_rows': order_rows})


@login_required
def buyer_center(request):
    """买家中心：基本信息、当前订单与历史订单、邮件通知设置。"""
    if request.user.role != 'buyer':
        return redirect('directory')

    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError

    from .order_message_helpers import unread_map_for_orders

    user = request.user
    if request.method == 'POST' and 'save_buyer_notify' in request.POST:
        user.buyer_notify_enabled = request.POST.get('buyer_notify_enabled') == '1'
        email = (request.POST.get('buyer_notify_email') or '').strip()[:254]
        save_ok = True
        if user.buyer_notify_enabled and not email:
            messages.error(request, '开启邮件通知时请填写收件邮箱')
            save_ok = False
        elif email:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, '邮箱格式不正确')
                save_ok = False
            else:
                user.buyer_notify_email = email
        else:
            user.buyer_notify_email = ''
        if save_ok:
            user.save(update_fields=['buyer_notify_enabled', 'buyer_notify_email'])
            messages.success(request, '邮件通知设置已保存')

    orders = list(
        BuyOrder.objects.filter(buyer_id=request.user.username)
        .select_related('delivery_order')
        .order_by('-created_at')
    )
    seller_ids = {o.seller_id for o in orders}
    shop_names = {
        s.seller_id: s.shop_name
        for s in ShopProfile.objects.filter(seller_id__in=seller_ids)
    }
    unread_map = unread_map_for_orders(orders, side='buyer')

    def _row(order):
        return {
            'order': order,
            'shop_name': shop_names.get(order.seller_id, order.seller_id),
            'unread_msg_count': unread_map.get(order.order_id, 0),
        }

    current_rows = [
        _row(order) for order in orders
        if order.order_status not in ('completed', 'cancelled')
    ]
    history_rows = [
        _row(order) for order in orders
        if order.order_status in ('completed', 'cancelled')
    ]
    return render(request, 'waimai/buyer_center.html', {
        'current_order_rows': current_rows,
        'history_order_rows': history_rows,
        'buyer_notify_enabled': user.buyer_notify_enabled,
        'buyer_notify_email': user.buyer_notify_email,
    })


def account_password_change(request):
    """买家、店主、工作台员工共用的修改本人密码入口。"""
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.forms import PasswordChangeForm

    from .shop_work_auth import get_shop_work_user

    eco_user = request.user if getattr(request.user, 'is_authenticated', False) else None
    work_user = get_shop_work_user(request)
    account_user = eco_user or work_user
    if account_user is None:
        messages.error(request, '请先登录后再修改密码')
        return redirect('login')

    form = PasswordChangeForm(account_user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        changed_user = form.save()
        if eco_user and eco_user.pk == changed_user.pk:
            update_session_auth_hash(request, changed_user)
        from .single_login_helpers import claim_single_login
        claim_single_login(request, changed_user)
        messages.success(request, '密码已修改，请使用新密码登录')
        if changed_user.role == 'buyer':
            return redirect('buyer_center')
        if changed_user.role == 'seller':
            return redirect('seller_panel')
        from .shop_work_helpers import build_shop_work_path, get_shop_code_for_user

        code = get_shop_code_for_user(changed_user)
        return redirect(build_shop_work_path(code)) if code else redirect('directory')

    return render(request, 'waimai/account_password_change.html', {
        'form': form,
        'account_user': account_user,
    })


def _order_page_viewer(request):
    """
    生态订单详情页身份（仅买家 / 卖家后台 / 骑手）。
    工作台员工不走本页，见 shop_work_order。
    """
    eco = request.user if getattr(request.user, 'is_authenticated', False) else None
    if eco and eco.role in ('buyer', 'seller', 'rider'):
        return eco
    return None


def order_detail(request, order_id):
    """订单详情（买家、卖家后台、骑手、堂食游客本机）。员工请走工作台订单中转页。"""
    from .guest_order_helpers import guest_can_access_order
    from .order_cancel_helpers import (
        BUYER_BLOCKED_HINT,
        buyer_can_self_cancel,
        cancel_order_by_buyer,
        cancel_order_by_shop,
        shop_can_cancel_order,
        shop_has_cancel_communication,
    )
    from .order_message_helpers import (
        mark_order_messages_read,
        post_order_message,
        viewer_can_use_order_chat,
    )
    from .shop_work_auth import get_shop_work_user
    from .shop_work_helpers import (
        SHOP_STAFF_ROLES,
        build_shop_work_order_path,
        get_shop_code_for_user,
    )

    # 员工若误开后台详情，强制改走工作台中转页（避免串成店主身份）
    work = get_shop_work_user(request)
    if work and work.role in SHOP_STAFF_ROLES:
        code = get_shop_code_for_user(work) or (request.session.get('shop_work_code') or '').strip()
        if code:
            return redirect(build_shop_work_order_path(code, order_id))
        return redirect('directory')

    order = get_object_or_404(
        BuyOrder.objects.select_related('delivery_order', 'table_session'),
        order_id=order_id,
    )

    # 堂食游客：凭进行中的桌台会话查看本单（结账翻台后会话关闭即不可见）
    table_sess = get_buyer_table_session(request, order.seller_id)
    is_guest_viewer = guest_can_access_order(request, order, table_sess)

    user = _order_page_viewer(request)
    if not user and not is_guest_viewer:
        return redirect('login')

    if user and user.role == 'buyer' and order.buyer_id != user.username and not is_guest_viewer:
        return redirect('order_history')
    if user and user.role == 'seller' and order.seller_id != user.username:
        return redirect('seller_panel_section', section='orders')
    if user and user.role == 'rider':
        delivery = getattr(order, 'delivery_order', None)
        if not delivery or delivery.rider_id != user.username:
            return redirect('rider_home')

    viewer_role = 'guest' if (is_guest_viewer and not user) else user.role
    # 游客本机只看单，不开放沟通/取消（投诉以店内小票为准）
    can_chat = bool(user) and viewer_can_use_order_chat(user, order)
    can_buyer_cancel = bool(user) and user.role == 'buyer' and buyer_can_self_cancel(order)
    show_buyer_cancel_blocked = (
        bool(user)
        and user.role == 'buyer'
        and order.order_status not in ('cancelled',)
        and not buyer_can_self_cancel(order)
    )
    can_shop_cancel = bool(user) and shop_can_cancel_order(user, order)

    if request.method == 'POST' and 'cash_shortfall_response' in request.POST:
        if not user or user.role != 'buyer':
            messages.error(request, '只有本订单买家可以确认实付金额')
        else:
            from .payments import buyer_respond_cash_shortfall

            response = (request.POST.get('cash_shortfall_response') or '').strip()
            ok, msg = buyer_respond_cash_shortfall(
                order, user.username, accept=(response == 'accept'),
            )
            if ok:
                messages.success(request, msg)
                from .audit_helpers import audit_order_status

                audit_order_status(
                    order=order,
                    actor=user,
                    summary=(
                        f'买家{"确认" if response == "accept" else "拒绝"}'
                        f'实付金额 {order.get_display_order_no()}'
                    ),
                    request=request,
                )
            else:
                messages.error(request, msg)
        return redirect('order_detail', order_id=order.order_id)

    if request.method == 'POST' and 'send_order_message' in request.POST:
        if not can_chat:
            messages.error(request, '您不能在此订单留言')
        else:
            ok, msg = post_order_message(order, user, request.POST.get('message_body', ''))
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        return redirect('order_detail', order_id=order.order_id)

    if request.method == 'POST' and 'cancel_order_buyer' in request.POST:
        if not user:
            messages.error(request, '游客请联系店员处理取消')
            return redirect('order_detail', order_id=order.order_id)
        ok, msg = cancel_order_by_buyer(order, user)
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('order_detail', order_id=order.order_id)

    if request.method == 'POST' and 'cancel_order_shop' in request.POST:
        if not user:
            return redirect('login')
        ok, msg = cancel_order_by_shop(order, user, request.POST.get('cancel_note', ''))
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('order_detail', order_id=order.order_id)

    if can_chat and user:
        mark_order_messages_read(order, user)

    shop_profile = ShopProfile.objects.filter(seller_id=order.seller_id).first()
    fee_detail = order.delivery_fee_detail
    if not fee_detail:
        _, fee_detail = build_delivery_fee_breakdown(
            order.seller_id, float(order.distance_km), order.get_subtotal()
        )

    if viewer_role == 'seller':
        back_url = 'seller_panel_section'
    elif viewer_role == 'rider':
        back_url = 'my_deliveries'
    elif viewer_role == 'guest':
        back_url = 'shop'
    else:
        back_url = 'order_history'

    order_messages = list(order.messages.order_by('created_at')) if can_chat else []

    from .order_shell_helpers import build_order_shell

    order_shell = build_order_shell(order)
    # 游客详情页：堂食现金提示按查看角色微调（结账后不可见本机订单）
    if viewer_role == 'guest' and order.is_dine_in() and request.GET.get('cash_pending'):
        order_shell = {
            **order_shell,
            'cash_pending_banner': (
                '已选择<strong>堂食 · 到店付现金</strong>。订单已提交，店家将为您备餐并告知预计出餐时间。'
                '结账后本机将不再保留本桌订单查看（有问题请以店内小票为准）。'
            ),
        }

    return render(request, 'waimai/order_detail.html', {
        'order': order,
        'order_shell': order_shell,
        'shop_profile': shop_profile,
        'timeline': build_order_timeline(order),
        'dish_lines': dish_items_with_line_totals(order.dish_items),
        'subtotal': order.get_subtotal(),
        'delivery_fee': order.get_delivery_fee_amount(),
        'delivery_fee_detail': fee_detail,
        'back_url': back_url,
        'viewer_role': viewer_role,
        'order_messages': order_messages,
        'can_order_chat': can_chat,
        'show_contact_guest': viewer_role == 'seller',
        'can_buyer_cancel': can_buyer_cancel,
        'show_buyer_cancel_blocked': show_buyer_cancel_blocked,
        'buyer_cancel_blocked_hint': BUYER_BLOCKED_HINT,
        'can_shop_cancel': can_shop_cancel,
        'shop_has_chat_history': shop_has_cancel_communication(order) if user else False,
        'shop_work_code': '',
        'shop_work_back_url': '',
        'guest_shop_back_url': f'/shop/?seller_id={order.seller_id}' if viewer_role == 'guest' else '',
    })
