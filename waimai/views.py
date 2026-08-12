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
from django.views.decorators.cache import never_cache
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
    try_apply_catalog_sales_for_order,
    validate_dish_purchase,
)
from .operating_helpers import check_order_admission, get_operating_settings
from waimai.plugins.dining.table_helpers import (
    build_addon_scan_path,
    build_table_scan_path,
    build_virtual_scan_path,
    ensure_addon_token,
    get_open_main_session_for_table,
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
    prepare_checkout_cart,
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

    def post(self, request, *args, **kwargs):
        from .login_guard_helpers import (
            SCOPE_ECOSYSTEM,
            audit_login_locked,
            check_login_allowed,
        )

        username = (request.POST.get('username') or '').strip()
        allowed, lock_msg = check_login_allowed(
            request, SCOPE_ECOSYSTEM, username=username,
        )
        if not allowed:
            audit_login_locked(
                request,
                scope=SCOPE_ECOSYSTEM,
                username=username,
                portal_label='野草生态',
            )
            form = self.get_form()
            form.add_error(None, lock_msg)
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        from .experience_helpers import can_accept_online, touch_online_user

        user = form.get_user()
        ok, msg = can_accept_online(user)
        if not ok:
            form.add_error(None, msg)
            return self.render_to_response(self.get_context_data(form=form))

        response = super().form_valid(form)
        from .single_login_helpers import claim_single_login
        claim_single_login(self.request, self.request.user)
        from .audit_helpers import write_audit_log
        from .login_guard_helpers import SCOPE_ECOSYSTEM, clear_login_guard

        user = self.request.user
        username = (self.request.POST.get('username') or '').strip()
        clear_login_guard(self.request, SCOPE_ECOSYSTEM, username=username)
        touch_online_user(user)
        write_audit_log(
            action_code='login',
            summary='野草生态登录成功',
            actor=user,
            request=self.request,
        )
        return response

    def form_invalid(self, form):
        from .login_guard_helpers import SCOPE_ECOSYSTEM, handle_failed_login_attempt

        username = (self.request.POST.get('username') or '').strip()
        msg = handle_failed_login_attempt(
            self.request,
            SCOPE_ECOSYSTEM,
            username=username,
            portal_label='野草生态',
            failed_summary=f'野草生态登录失败：{username or "（未填用户名）"}',
        )
        display_form = self.get_form()
        display_form.add_error(None, msg)
        return self.render_to_response(self.get_context_data(form=display_form))

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to:
            return redirect_to
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


def home_block_download(request, block_id):
    """服务器主页文件下载积木：先记账再发文件"""
    from .home_block_download_helpers import serve_home_block_download

    return serve_home_block_download(request, block_id)


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
            PERM_FULFILLMENT_CASH_MANAGE,
            PERM_ORDERS_CASHIER,
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

        if (
            'cashier' in enabled_views
            and work_user.role != 'seller'
            and not staff_has_permission(work_user, PERM_ORDERS_CASHIER)
        ):
            enabled_views = [view for view in enabled_views if view != 'cashier']

        if (
            'cash_manage' in enabled_views
            and work_user.role != 'seller'
            and not staff_has_permission(work_user, PERM_FULFILLMENT_CASH_MANAGE)
        ):
            enabled_views = [view for view in enabled_views if view != 'cash_manage']

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
        from .remittance_alert_helpers import work_user_can_use_remittance_alert

        can_use_remittance_alert = work_user_can_use_remittance_alert(work_user)

        if request.method == 'POST':
            is_status_action = 'staff_work_status_action' in request.POST
            if current_view == 'orders':
                if not is_status_action and not can_open_orders:
                    messages.error(request, '您没有权限执行此操作')
                    return redirect(build_shop_work_path(code, view=current_view))
            elif not is_status_action and not perms.get(current_view):
                messages.error(request, '您没有权限执行此操作')
                return redirect(build_shop_work_path(code, view=current_view))
            from .workbench_panel_helpers import (
                detect_workbench_panel_action,
                run_workbench_idempotent,
            )
            from .cash_manage_panel_helpers import (
                detect_cash_manage_panel_action,
                run_cash_manage_idempotent,
            )

            cash_action = detect_cash_manage_panel_action(request)
            if cash_action:
                response = run_cash_manage_idempotent(
                    request,
                    seller_id,
                    work_user,
                    cash_action,
                    lambda: handle_shop_work_post(
                        request, seller_id, code, current_view, perms, work_user=work_user,
                    ),
                )
            else:
                wb_action = detect_workbench_panel_action(request)
                if wb_action:
                    response = run_workbench_idempotent(
                        request,
                        seller_id,
                        work_user,
                        wb_action,
                        lambda: handle_shop_work_post(
                            request, seller_id, code, current_view, perms, work_user=work_user,
                        ),
                    )
                else:
                    response = handle_shop_work_post(
                        request, seller_id, code, current_view, perms, work_user=work_user,
                    )
            if response:
                return response

        form_action = _work_url(current_view)

        # 进度 80：现金管理 · 汇总月份下拉 Panel 静默刷新（不整页 reload）
        if (
            request.method == 'GET'
            and current_view == 'cash_manage'
            and request.GET.get('cash_month') is not None
        ):
            from .cash_manage_panel_helpers import render_workbench_cash_manage_panel_html
            from .panel_refresh_helpers import is_panel_refresh, panel_refresh_ok

            if is_panel_refresh(request):
                html = render_workbench_cash_manage_panel_html(
                    request,
                    seller_id,
                    work_user=work_user,
                    form_action=form_action,
                )
                return panel_refresh_ok(
                    html=html,
                    panel_id='work-cash-manage-panel-body',
                    message='',
                )

        context = {
            'shop_profile': shop_profile,
            'current_view': current_view,
            'enabled_work_views': enabled_views,
            'form_action': form_action,
            'tab_orders_url': _work_url('orders'),
            'tab_cashier_url': _work_url('cashier'),
            'tab_cash_manage_url': _work_url('cash_manage'),
            'tab_waiter_url': _work_url('waiter'),
            'tab_kitchen_url': _work_url('kitchen'),
            'tab_rider_url': _work_url('rider'),
            'work_order_sort': work_order_sort,
            'sort_newest_url': _work_url(current_view, 'newest'),
            'sort_oldest_url': _work_url(current_view, 'oldest'),
            'can_operate_orders': perms.get('orders', False),
            'can_operate_cashier': perms.get('cashier', False),
            'can_operate_cash_manage': perms.get('cash_manage', False),
            'can_open_orders': can_open_orders,
            'can_operate_waiter': perms['waiter'],
            'can_operate_kitchen': perms['kitchen'],
            'can_operate_rider': perms['rider'],
            'can_use_order_alert': can_use_order_alert,
            'can_use_remittance_alert': can_use_remittance_alert,
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
        context.update(build_shop_work_daily_history(
            seller_id, work_user, request=request, list_base_url=form_action,
        ))
        if work_user.role == 'seller':
            from .forms import ShopDutyOrderNotifyForm, ShopDutyRemittanceNotifyForm
            from .operating_helpers import get_operating_settings
            from .order_notify_ui_helpers import smtp_not_ready_message

            operating = get_operating_settings(seller_id)
            context['duty_order_notify_form'] = ShopDutyOrderNotifyForm(instance=operating)
            context['duty_order_notify_smtp_warn'] = smtp_not_ready_message(
                operating.duty_order_notify_enabled,
            )
            context['duty_remittance_notify_form'] = ShopDutyRemittanceNotifyForm(instance=operating)
            context['duty_remittance_notify_smtp_warn'] = smtp_not_ready_message(
                operating.duty_remittance_notify_enabled,
            )
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
                request=request,
                shop_code=code,
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
        elif current_view == 'cashier':
            from .cashier_helpers import build_cashier_context

            context.update(build_cashier_context(
                seller_id, work_user=work_user, request=request,
            ))
        elif current_view == 'cash_manage':
            from .cash_manage_helpers import build_workbench_cash_manage_context

            context.update(build_workbench_cash_manage_context(
                seller_id, work_user=work_user, request=request,
            ))
        if (
            request.method == 'GET'
            and current_view == 'waiter'
            and (request.GET.get('yc_table_board') or '').strip() == '1'
        ):
            from .panel_refresh_helpers import is_panel_refresh, panel_refresh_ok
            from waimai.plugins.dining.waiter_table_helpers import (
                render_waiter_table_board_inner_html,
            )

            if is_panel_refresh(request):
                html = render_waiter_table_board_inner_html(
                    request,
                    seller_id=seller_id,
                    shop_code=code,
                    can_operate=bool(perms.get('waiter')),
                    form_action=form_action,
                )
                return panel_refresh_ok(
                    html=html,
                    panel_id='waiter-table-board-body',
                    message='',
                )
        return render(request, 'waimai/shop_work_hub.html', context)

    if request.method == 'POST':
        from .audit_helpers import write_audit_log
        from .login_guard_helpers import (
            SCOPE_SHOP_WORK,
            audit_login_locked,
            check_login_allowed,
            clear_login_guard,
            handle_failed_login_attempt,
        )
        from .staff_account_helpers import (
            activate_staff_on_login,
            authenticate_shop_work_user,
            is_shop_staff_account,
        )

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        allowed, lock_msg = check_login_allowed(
            request,
            SCOPE_SHOP_WORK,
            username=username,
            seller_id=seller_id,
        )
        if not allowed:
            audit_login_locked(
                request,
                scope=SCOPE_SHOP_WORK,
                username=username,
                seller_id=seller_id,
                portal_label='店铺工作台',
            )
            messages.error(request, lock_msg)
            return render(request, 'waimai/shop_work_login.html', {'shop_profile': shop_profile})

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
            clear_login_guard(
                request,
                SCOPE_SHOP_WORK,
                username=username,
                seller_id=seller_id,
            )
            write_audit_log(
                action_code='login',
                summary='店铺工作台登录成功',
                seller_id=seller_id,
                actor=user,
                request=request,
            )
            return redirect(build_shop_work_path(code, view=default_work_view(user)))
        err = handle_failed_login_attempt(
            request,
            SCOPE_SHOP_WORK,
            username=username,
            seller_id=seller_id,
            portal_label='店铺工作台',
            failed_summary=f'店铺工作台登录失败：{username or "（未填用户名）"}',
        )
        messages.error(request, err)

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


@require_GET
def shop_work_pending_remittances_json(request, shop_code):
    """店铺工作台轮询：待核对入金申请数量与最新时间戳。"""
    from .remittance_alert_helpers import remittance_alert_snapshot, work_user_can_use_remittance_alert
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
        or not work_user_can_use_remittance_alert(work_user)
    ):
        return JsonResponse({'ok': False, 'count': 0, 'latest_ts': 0}, status=403)

    count, latest_ts = remittance_alert_snapshot(seller_id)
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
    from .order_helpers import dish_items_with_line_totals, build_order_timeline
    from .order_timeline_helpers import VIEWER_WORK
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

    from .payments import poll_wechat_refund
    from .payments.wechat_refund_helpers import shop_cancel_refund_hint

    if order.order_status == 'cancelled' or order.payment_status == 'paid':
        poll_wechat_refund(order)
        order.refresh_from_db()

    from .workbench_shell_helpers import build_workbench_shell
    from .order_qr_helpers import order_cashier_qr_template_context

    qr_ctx = order_cashier_qr_template_context(
        request,
        order,
        shop_code=code,
        print_url=reverse(
            'shop_work_cashier_order_print',
            kwargs={'shop_code': code, 'order_id': order.order_id},
        ),
    )

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
        'shop_cancel_refund_hint': shop_cancel_refund_hint(order),
        'back_url': build_shop_work_path(code, view='orders'),
        'shop_work_logout_url': reverse('shop_work_logout', kwargs={'shop_code': code}),
        'workbench_shell': build_workbench_shell(seller_id),
        'timeline': build_order_timeline(order, viewer=VIEWER_WORK),
        **qr_ctx,
    })


def _rewrite_waiter_shop_redirect(response, request, seller_id: str):
    """服务员代客点菜：把店铺页跳转改回工作台点菜页。"""
    from waimai.plugins.dining.waiter_table_order_helpers import get_waiter_table_order_page_url

    if response.status_code not in (301, 302):
        return response
    custom = get_waiter_table_order_page_url(request, seller_id)
    if not custom:
        return response
    location = response.get('Location', '')
    if location.startswith('/shop/') or 'seller_id=' in location:
        response['Location'] = custom
    return response


def shop_work_waiter_table_order(request, shop_code, table_id):
    """服务员代客点菜：绑桌堂食，复用店铺菜单与购物车。"""
    from .order_helpers import get_shop_cart
    from .shop_work_auth import get_shop_work_user
    from .shop_work_helpers import get_shop_profile_by_code
    from .waiter_table_order_handlers import prepare_waiter_table_order_page

    work_user = get_shop_work_user(request)
    extra, err_redirect = prepare_waiter_table_order_page(
        request,
        shop_code=shop_code,
        table_id=table_id,
        work_user=work_user,
        auto_open_if_idle=True,
    )
    if err_redirect:
        return err_redirect

    shop_profile = get_shop_profile_by_code(shop_code)
    seller_id = shop_profile.seller_id

    if request.method == 'POST':
        mutable_get = request.GET.copy()
        mutable_get['seller_id'] = seller_id
        request.GET = mutable_get
        response = shop_page(request)
        return _rewrite_waiter_shop_redirect(response, request, seller_id)

    cart = get_shop_cart(request.session, seller_id)
    return _shop_render(request, seller_id, cart, shop_profile, extra=extra)


def _shop_work_cashier_auth(request, shop_code: str):
    """收银台微信页：校验工作台登录与收银权限。"""
    from .shop_work_auth import get_shop_work_user
    from .shop_work_helpers import (
        build_shop_work_path,
        get_shop_profile_by_code,
        user_belongs_to_shop,
    )
    from .staff_account_helpers import PERM_ORDERS_CASHIER, staff_has_permission

    shop_profile = get_shop_profile_by_code(shop_code)
    if not shop_profile:
        return None, None, None, redirect('directory')

    code = (shop_profile.shop_code or '').strip()
    seller_id = shop_profile.seller_id
    work_user = get_shop_work_user(request)
    if not work_user or not user_belongs_to_shop(work_user, seller_id):
        messages.error(request, '请先登录本店工作台')
        return None, None, None, redirect(build_shop_work_path(code, view='cashier'))
    if not staff_has_permission(work_user, PERM_ORDERS_CASHIER):
        messages.error(request, '您没有收银台操作权限')
        return None, None, None, redirect(build_shop_work_path(code, view='cashier'))
    return shop_profile, work_user, seller_id, None


def shop_work_cashier_wechat(request, shop_code, order_id):
    """收银台：微信 Native 扫码收款页（工作台内）。"""
    from .cashier_helpers import cashier_wechat_page_context
    from .shop_work_helpers import build_shop_work_path

    shop_profile, work_user, seller_id, denied = _shop_work_cashier_auth(request, shop_code)
    if denied:
        return denied

    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
    if order.payment_status == 'paid':
        messages.success(request, '该订单已收款')
        return redirect(build_shop_work_path(shop_profile.shop_code, view='cashier'))

    ctx, err = cashier_wechat_page_context(
        order, seller_id, client_ip=_client_ip(request),
    )
    if err:
        messages.error(request, err)
        return redirect(build_shop_work_path(shop_profile.shop_code, view='cashier'))

    code = (shop_profile.shop_code or '').strip()
    ctx.update({
        'shop_profile': shop_profile,
        'shop_work_code': code,
        'work_user': work_user,
        'cashier_back_url': build_shop_work_path(code, view='cashier'),
        'cashier_status_url': reverse(
            'shop_work_cashier_wechat_status',
            kwargs={'shop_code': code, 'order_id': order.order_id},
        ),
    })
    return render(request, 'waimai/shop_work_cashier_wechat.html', ctx)


@require_GET
def shop_work_cashier_wechat_status(request, shop_code, order_id):
    """收银台微信扫码页：轮询是否已支付。"""
    from .audit_helpers import audit_order_status
    from .payments import poll_wechat_payment
    from .shop_work_helpers import build_shop_work_path

    shop_profile, work_user, seller_id, denied = _shop_work_cashier_auth(request, shop_code)
    if denied:
        return JsonResponse({'paid': False})

    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
    back = build_shop_work_path(shop_profile.shop_code, view='cashier')
    if order.payment_status == 'paid':
        return JsonResponse({'paid': True, 'redirect': back})

    was_paid = False
    if poll_wechat_payment(order):
        order.refresh_from_db()
        was_paid = order.payment_status == 'paid'
    else:
        order.refresh_from_db()
        was_paid = order.payment_status == 'paid'

    if was_paid:
        audit_order_status(
            order=order,
            actor=work_user,
            summary=f'收银台微信收款 {order.get_display_order_no()} · ¥{order.total_amount}',
            request=request,
        )
        return JsonResponse({
            'paid': True,
            'redirect': build_shop_work_path(shop_profile.shop_code, view='cashier'),
        })
    return JsonResponse({'paid': False})


def shop_work_cashier_order_print(request, shop_code, order_id):
    """收银台：打印订单码小票（待支付单）。"""
    from .order_qr_helpers import build_order_cashier_qr_bundle
    from .shop_work_helpers import build_shop_work_path

    shop_profile, work_user, seller_id, denied = _shop_work_cashier_auth(request, shop_code)
    if denied:
        return denied

    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)
    code = (shop_profile.shop_code or '').strip()
    qr_bundle = build_order_cashier_qr_bundle(request, order, code)
    if not qr_bundle:
        messages.error(request, '该订单不可打印收银码（须为今天待支付且已启用收银台）')
        return redirect(build_shop_work_path(code, view='cashier'))

    return render(request, 'waimai/order_cashier_qr_print.html', {
        'order': order,
        'qr_bundle': qr_bundle,
        'shop_name': shop_profile.shop_name,
        'back_url': build_shop_work_path(code, view='cashier'),
    })


@login_required
def seller_order_cashier_qr_print(request, order_id):
    """卖家后台：打印订单码小票。"""
    from .order_qr_helpers import build_order_cashier_qr_bundle, resolve_shop_code_for_order

    if request.user.role != 'seller':
        messages.error(request, '只有店主可以打印订单码')
        return redirect('seller_panel_section', section='orders')

    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=request.user.username)
    shop_code = resolve_shop_code_for_order(order)
    qr_bundle = build_order_cashier_qr_bundle(request, order, shop_code)
    if not qr_bundle:
        messages.error(request, '该订单不可打印收银码（须为待支付且已启用实体收银台）')
        return redirect('order_detail', order_id=order.order_id)

    shop_profile = ShopProfile.objects.filter(seller_id=order.seller_id).first()
    return render(request, 'waimai/order_cashier_qr_print.html', {
        'order': order,
        'qr_bundle': qr_bundle,
        'shop_name': shop_profile.shop_name if shop_profile else '',
        'back_url': reverse('order_detail', kwargs={'order_id': order.order_id}),
    })


def _execute_waiter_pay_order_post(request, order):
    """服务员协助收款 POST（幂等第 7 步 · 由 run_idempotent 包裹）。"""
    from .payments import build_pay_page_context
    from .shop_work_helpers import resolve_waiter_return_url
    from .waiter_handlers import handle_waiter_pay_post
    from .waiter_helpers import sync_waiter_service_status

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


def waiter_pay_order(request, order_id):
    """服务员协助收款：选择支付方式（绑定本单）；认工作台登录身份"""
    from .idempotency_helpers import extract_idempotency_key
    from .initiate_payment_helpers import run_initiate_payment_idempotent
    from .payments import build_pay_page_context
    from .shop_work_auth import get_shop_work_user
    from .waiter_helpers import ensure_waiter_employer
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

    if request.method == 'POST' and extract_idempotency_key(request):
        return run_initiate_payment_idempotent(
            request, order, lambda: _execute_waiter_pay_order_post(request, order),
        )

    if order.payment_status != 'pending_payment':
        messages.info(request, '该订单无需再收款')
        return redirect(resolve_waiter_return_url(request))

    if request.method == 'POST':
        return run_initiate_payment_idempotent(
            request, order, lambda: _execute_waiter_pay_order_post(request, order),
        )

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


def _shop_cart_redirect(
    seller_id, keep_cart_open=False, dish_id=None, price_tier=None, *, request=None,
):
    """加减购物车后跳回店铺；服务员代客点菜时跳回工作台点菜页。"""
    url = f'/shop/?seller_id={seller_id}'
    if request is not None:
        from waimai.plugins.dining.waiter_table_order_helpers import get_waiter_table_order_page_url

        custom = get_waiter_table_order_page_url(request, seller_id)
        if custom:
            url = custom
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


def _shop_cart_panel_ok(request, cart, seller_id, shop_profile):
    """无刷新购物车操作成功后，返回 Panel 统一 JSON。"""
    from .shop_cart_panel_helpers import shop_cart_panel_ok
    return shop_cart_panel_ok(request, cart, seller_id, shop_profile)


def _shop_cart_error(request, message: str):
    """Panel 请求返回白话错误；普通提交继续由原页面显示。"""
    from .shop_cart_panel_helpers import shop_cart_panel_fail_or_none
    return shop_cart_panel_fail_or_none(request, message)


def _execute_shop_cart_add_to_cart(request, seller_id, shop_profile):
    """加购（幂等第 3 步 · 由 run_shop_cart_idempotent 包裹）。"""
    from .channel_helpers import require_shop_channel
    from .panel_refresh_helpers import is_panel_refresh
    from .product_shell_helpers import build_product_shell, catalog_controls_shop_display

    table_sess = get_buyer_table_session(request, seller_id)
    cart = get_shop_cart(request.session, seller_id)
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
    from .product_shell_helpers import build_product_shell, catalog_controls_shop_display

    if catalog_controls_shop_display(seller_id) and not dish_visible_on_shop(seller_id, dish_id):
        catalog_word = build_product_shell(seller_id).get('catalog_word', '商品列表')
        err_text = f'该商品不在当前使用中的{catalog_word}里'
        fetch_error = _shop_cart_error(request, err_text)
        if fetch_error:
            return fetch_error
        return _shop_render(request, seller_id, cart, shop_profile, error=err_text)
    line_key = cart_line_key(dish_id, tier)
    qty = cart.get(line_key, 0) + 1
    ok, msg = validate_tier_purchase(
        dish, tier, request.user, seller_id, qty, cart, line_key=line_key,
    )
    if not ok:
        fetch_error = _shop_cart_error(request, msg)
        if fetch_error:
            return fetch_error
        return _shop_render(request, seller_id, cart, shop_profile, error=msg)
    cart[line_key] = qty
    set_shop_cart(request.session, seller_id, cart)
    if is_panel_refresh(request):
        return _shop_cart_panel_ok(request, cart, seller_id, shop_profile)
    if request.POST.get('stay_in_cart'):
        return _shop_cart_redirect(seller_id, keep_cart_open=True, request=request)
    return _shop_cart_redirect(seller_id, dish_id=dish_id, price_tier=tier, request=request)


def _execute_shop_cart_decrease_from_cart(request, seller_id, shop_profile):
    """减购（幂等第 3 步）。"""
    from .panel_refresh_helpers import is_panel_refresh

    cart = get_shop_cart(request.session, seller_id)
    line_key = request.POST.get('line_key') or cart_line_key(
        request.POST.get('dish_id'), request.POST.get('price_tier', PRICE_TIER_GENERAL),
    )
    cart = normalize_cart_keys(cart)
    if line_key in cart:
        cart[line_key] = cart.get(line_key, 0) - 1
        if cart[line_key] < 0:
            cart[line_key] = 0
    set_shop_cart(request.session, seller_id, cart)
    if is_panel_refresh(request):
        return _shop_cart_panel_ok(request, cart, seller_id, shop_profile)
    return _shop_cart_redirect(seller_id, keep_cart_open=True, request=request)


def _execute_shop_cart_remove_from_cart(request, seller_id, shop_profile):
    """删行（幂等第 3 步）。"""
    from .panel_refresh_helpers import is_panel_refresh

    cart = get_shop_cart(request.session, seller_id)
    line_key = request.POST.get('line_key') or cart_line_key(
        request.POST.get('dish_id'), request.POST.get('price_tier', PRICE_TIER_GENERAL),
    )
    cart = normalize_cart_keys(cart)
    cart.pop(line_key, None)
    set_shop_cart(request.session, seller_id, cart)
    if is_panel_refresh(request):
        return _shop_cart_panel_ok(request, cart, seller_id, shop_profile)
    return _shop_cart_redirect(seller_id, keep_cart_open=True, request=request)


def _execute_shop_cart_update_cart(request, seller_id, shop_profile):
    """改数量（幂等第 3 步）。"""
    from .panel_refresh_helpers import is_panel_refresh

    cart = get_shop_cart(request.session, seller_id)
    line_key = request.POST.get('line_key') or cart_line_key(
        request.POST.get('dish_id'), request.POST.get('price_tier', PRICE_TIER_GENERAL),
    )
    qty = int(request.POST.get('quantity', 1))
    if qty < 0:
        qty = 0
    cart = normalize_cart_keys(cart)
    cart[line_key] = qty
    set_shop_cart(request.session, seller_id, cart)
    if is_panel_refresh(request):
        return _shop_cart_panel_ok(request, cart, seller_id, shop_profile)
    return _shop_cart_redirect(seller_id, keep_cart_open=True, request=request)


def _shop_page_dishes(seller_id):
    """店铺页商品列表；业态插件可接管目录过滤。"""
    from .product_shell_helpers import get_shop_products_for_sale

    dishes, using_menu = get_shop_products_for_sale(seller_id)
    return dishes, using_menu


def _redirect_after_table_main_merge(request, merged, *, is_guest, seller_id):
    """桌码主单合并加点成功后的跳转（幂等第 8 步）。"""
    from .guest_order_helpers import apply_guest_onsite_cash
    from .menu_helpers import try_apply_catalog_sales_for_order
    from .order_qr_helpers import order_cash_code_url

    if merged.payment_method == 'cash' or (is_guest and merged.catalog_sales_applied):
        ok_cap, cap_errors = try_apply_catalog_sales_for_order(merged)
        if not ok_cap:
            for err in cap_errors:
                messages.error(request, err)
            return redirect(f'/shop/?seller_id={seller_id}')
    if is_guest:
        if not merged.payment_method:
            ok_cash, cash_errors = apply_guest_onsite_cash(merged)
            if not ok_cash:
                for err in cash_errors:
                    messages.error(request, err)
                return redirect(f'/shop/?seller_id={seller_id}')
        return redirect(order_cash_code_url(merged.order_id))
    return redirect('pay_order', order_id=merged.order_id)


def _shop_render(request, seller_id, cart, shop_profile, error='', extra=None):
    """店铺页统一渲染（含菜单过滤、桌台与下单通道）"""
    from .channel_helpers import (
        auto_pick_single_homepage_channel,
        channel_template_flags,
        dining_plugin_enabled,
        homepage_channel_switch_enabled,
        is_channel_repick,
        list_homepage_channels,
        resolve_shop_channel,
    )

    from .product_shell_helpers import build_product_shell
    from .product_helpers import build_dish_tier_options, build_dish_shop_compact
    from .product_image_helpers import build_dish_image_gallery

    product_shell = build_product_shell(seller_id)
    dishes, using_menu = _shop_page_dishes(seller_id)
    menu_items_map = get_active_menu_items_map(seller_id) if using_menu else {}
    table_session = get_buyer_table_session(request, seller_id)
    auto_pick_single_homepage_channel(request, seller_id, table_session)
    shop_channel = resolve_shop_channel(request, seller_id, table_session)
    table_session_expired = bool(getattr(request, 'yc_table_session_expired', False))
    channel_repick_mode = (not table_session) and is_channel_repick(request.session, seller_id)
    need_channel_pick = (
        (not table_session)
        and (not shop_channel)
        and not table_session_expired
    )
    show_channel_pick = need_channel_pick or channel_repick_mode
    # 本桌进行中的订单：游客/买家回店后可一点打开详情（结账翻台后不再显示）
    table_open_order = get_open_order_for_session(table_session) if table_session else None
    table_addon_scan_path = ''
    if table_session and table_session.session_type == 'main' and table_session.status == 'open':
        addon_token = ensure_addon_token(table_session)
        if addon_token:
            table_addon_scan_path = build_addon_scan_path(seller_id, addon_token)

    dish_rows = []
    if shop_channel and not channel_repick_mode:
        for dish in dishes:
            gallery = build_dish_image_gallery(dish)
            tier_options = build_dish_tier_options(
                dish, request.user, seller_id, cart,
                menu_item=menu_items_map.get(dish.dish_id),
            )
            # 清单模式下无任何可展示档位时不渲染空壳商品
            if using_menu and not tier_options:
                continue
            dish_rows.append({
                'dish': dish,
                'image_gallery': gallery,
                'tier_options': tier_options,
                'compact': build_dish_shop_compact(dish, tier_options, gallery),
            })
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
        'table_addon_scan_path': table_addon_scan_path,
        'need_channel_pick': need_channel_pick,
        'channel_repick_mode': channel_repick_mode,
        'show_channel_pick': show_channel_pick,
        'dining_plugin_enabled': dining_plugin_enabled(seller_id),
        'channel_options': list_homepage_channels(seller_id) if show_channel_pick else [],
        'can_switch_shop_channel': (
            (not table_session) and homepage_channel_switch_enabled(seller_id)
        ),
        'error': error or request.GET.get('error', '') or (
            '本桌已翻台或会话已失效，请重新扫描专属加点码进入。'
            if table_session_expired else ''
        ),
        **channel_template_flags(shop_channel),
        **_shop_cart_context(cart, seller_id),
    }
    notices = []
    err_text = ctx.get('error') or ''
    if err_text:
        notices.append({'level': 'error', 'text': err_text, 'mustAck': True})
    if ctx.get('success'):
        ff = ctx.get('success_fulfillment') or ''
        ok_text = '支付成功！'
        if ff == 'order':
            ok_text += '订单已提交，店家将按商品说明或沟通约定处理。'
        elif ff == 'dine_in':
            ok_text += '请入座用餐，店铺将为您备餐。'
        elif ff == 'takeaway':
            ok_text += '请按约定到店取餐。'
        else:
            ok_text += '店铺将备货并派给本店骑手配送。'
        notices.append({'level': 'ok', 'text': ok_text, 'mustAck': False})
    if notices:
        import json

        ctx['yc_notice_boot'] = json.dumps(notices, ensure_ascii=False)
    if extra:
        ctx.update(extra)
    return render(request, 'waimai/shop.html', ctx)


def product_scan_add(request, display_code, tier):
    """商品分档二维码入口：须登录买家；成功则加购并跳转店铺页。"""
    from urllib.parse import quote

    from .product_helpers import TIER_LABELS
    from .product_scan_helpers import (
        SCAN_TIERS,
        add_scanned_product_to_cart,
        build_product_scan_path,
        dish_scroll_anchor_for_scan,
        evaluate_product_scan,
        normalize_scan_tier,
        resolve_dish_for_scan,
    )
    from .scroll_helpers import redirect_with_anchor

    seller_id = (request.GET.get('seller_id') or '').strip()
    tier_norm = normalize_scan_tier(tier)
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first() if seller_id else None
    dish = resolve_dish_for_scan(seller_id, display_code) if seller_id else None

    def _message_ctx(**extra):
        base = {
            'shop_profile': shop_profile,
            'dish': dish,
            'tier_label': TIER_LABELS.get(tier_norm, ''),
            'shop_url': f'/shop/?seller_id={seller_id}' if seller_id else '/directory/',
        }
        base.update(extra)
        return base

    if tier_norm not in SCAN_TIERS or not seller_id:
        return render(
            request,
            'waimai/product_scan_message.html',
            _message_ctx(ok=False, message='无商品'),
        )

    status, msg = evaluate_product_scan(dish, tier_norm, seller_id)
    if status != 'ok':
        return render(
            request,
            'waimai/product_scan_message.html',
            _message_ctx(ok=False, message=msg or '无商品'),
        )

    scan_path = build_product_scan_path(seller_id, display_code, tier_norm)
    login_url = reverse('login') + '?next=' + quote(scan_path)

    if not request.user.is_authenticated:
        return render(
            request,
            'waimai/product_scan_message.html',
            _message_ctx(
                ok=False,
                message='请先登录买家账号后再扫码加购。',
                login_url=login_url,
            ),
        )

    if request.user.role != 'buyer':
        return render(
            request,
            'waimai/product_scan_message.html',
            _message_ctx(
                ok=False,
                message='请使用买家账号登录后再扫码加购。',
                login_url=login_url,
            ),
        )

    ok, err = add_scanned_product_to_cart(request, dish, tier_norm, seller_id)
    if not ok:
        return render(
            request,
            'waimai/product_scan_message.html',
            _message_ctx(ok=False, message=err),
        )

    messages.success(
        request,
        f'已加入购物车：{dish.name}（{TIER_LABELS.get(tier_norm, tier_norm)}）',
    )
    return redirect_with_anchor(
        f'/shop/?seller_id={seller_id}',
        dish_scroll_anchor_for_scan(dish, tier_norm),
    )


def shop_page(request):
    """店铺页面：选通道 + 菜品展示 + 购物车 + 下单确认"""
    from django.shortcuts import redirect

    from .channel_helpers import (
        CHANNEL_DELIVERY,
        build_address_and_distance,
        get_shop_channel,
        is_channel_repick,
        require_shop_channel,
        set_channel_repick,
        try_set_homepage_channel,
    )
    from .panel_refresh_helpers import is_panel_refresh

    seller_id = request.GET.get('seller_id', 'seller_001')
    cart = get_shop_cart(request.session, seller_id)
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    delivery_settings = get_delivery_settings(seller_id)

    if request.method == 'POST':
        action = request.POST.get('action', '')
        table_sess = get_buyer_table_session(request, seller_id)

        if action == 'set_channel':
            # 选通道：仅当通道真的变更时才清空购物车（同通道 = 取消重选）
            old_channel = get_shop_channel(request.session, seller_id)
            new_channel = (request.POST.get('channel') or '').strip()
            ok, msg = try_set_homepage_channel(
                request, seller_id, new_channel, table_sess,
            )
            if not ok:
                return _shop_render(request, seller_id, cart, shop_profile, error=msg)
            set_channel_repick(request.session, seller_id, False)
            if old_channel and new_channel and old_channel != new_channel:
                set_shop_cart(request.session, seller_id, {})
            return redirect(f'/shop/?seller_id={seller_id}')

        if action == 'start_channel_repick':
            if table_sess:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='扫桌码模式下为堂食通道，不能切换为外卖或打包。',
                )
            set_channel_repick(request.session, seller_id, True)
            return redirect(f'/shop/?seller_id={seller_id}')

        if action == 'cancel_channel_repick':
            set_channel_repick(request.session, seller_id, False)
            return redirect(f'/shop/?seller_id={seller_id}')

        if action == 'add_to_cart':
            from .shop_cart_panel_helpers import run_shop_cart_idempotent
            return run_shop_cart_idempotent(
                request, seller_id, action,
                lambda: _execute_shop_cart_add_to_cart(request, seller_id, shop_profile),
            )

        if action == 'decrease_from_cart':
            from .shop_cart_panel_helpers import run_shop_cart_idempotent
            return run_shop_cart_idempotent(
                request, seller_id, action,
                lambda: _execute_shop_cart_decrease_from_cart(request, seller_id, shop_profile),
            )

        if action == 'remove_from_cart':
            from .shop_cart_panel_helpers import run_shop_cart_idempotent
            return run_shop_cart_idempotent(
                request, seller_id, action,
                lambda: _execute_shop_cart_remove_from_cart(request, seller_id, shop_profile),
            )

        if action == 'update_cart':
            from .shop_cart_panel_helpers import run_shop_cart_idempotent
            return run_shop_cart_idempotent(
                request, seller_id, action,
                lambda: _execute_shop_cart_update_cart(request, seller_id, shop_profile),
            )

        if action == 'checkout':
            from .channel_helpers import CHANNEL_DINE_IN
            from .guest_order_helpers import normalize_guest_nickname
            from waimai.plugins.dining.waiter_table_order_helpers import (
                get_waiter_table_order_page_url,
                is_waiter_table_order_active,
            )

            is_logged_buyer = (
                request.user.is_authenticated and request.user.role == 'buyer'
            )
            waiter_dine = is_waiter_table_order_active(request, seller_id)
            # 堂食 + 有效桌台会话：游客或服务员代点可结算
            is_guest_dine = bool(table_sess and (not is_logged_buyer or waiter_dine))
            if not is_logged_buyer and not is_guest_dine:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='请先登录买家账号再下单（堂食扫桌码可免登录）',
                )

            cart, cart_items, subtotal, removed_notes = prepare_checkout_cart(cart, seller_id)
            if removed_notes:
                set_shop_cart(request.session, seller_id, cart)
            if not cart_items:
                err = '请至少选择一份数量大于 0 的商品再结算'
                if removed_notes:
                    err = '；'.join(dict.fromkeys(removed_notes)) + '。购物车已无可结算商品，请重新选购。'
                return _shop_render(request, seller_id, cart, shop_profile, error=err)

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
                    item['dish'],
                    item['price_tier'],
                    request.user,
                    seller_id,
                    item['quantity'],
                    cart,
                    line_key=cart_line_key(item['dish'].dish_id, item['price_tier']),
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
            cart_removed_notice = ''
            if removed_notes:
                cart_removed_notice = '；'.join(dict.fromkeys(removed_notes))
            confirm_ctx = {
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
                'cart_removed_notice': cart_removed_notice,
                **channel_template_flags(fulfillment_type),
            }
            if waiter_dine:
                from .shop_work_auth import SESSION_SHOP_WORK_CODE
                from .shop_work_helpers import build_shop_work_path

                code = (request.session.get(SESSION_SHOP_WORK_CODE) or '').strip()
                confirm_ctx.update({
                    'waiter_table_order_mode': True,
                    'waiter_table_order_url': get_waiter_table_order_page_url(request, seller_id),
                    'waiter_return_url': build_shop_work_path(code, view='waiter') if code else '',
                })
            return render(request, 'waimai/confirm_order.html', confirm_ctx)

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
    from django.contrib import messages
    from django.shortcuts import redirect

    from .experience_helpers import experience_hint_context, touch_online_user
    from .v1_local_helpers import v1_local_block_message, v1_local_mode_enabled

    if v1_local_mode_enabled():
        messages.info(request, v1_local_block_message())
        return redirect('login')

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
    from django.contrib import messages
    from django.shortcuts import redirect

    from .experience_helpers import experience_hint_context, touch_online_user
    from .v1_local_helpers import v1_local_block_message, v1_local_mode_enabled

    if v1_local_mode_enabled():
        messages.info(request, v1_local_block_message())
        return redirect('login')

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
@require_GET
def seller_pending_remittances_json(request):
    """卖家支付页轮询：待核对入金申请数量与最新时间戳。"""
    if request.user.role != 'seller':
        return JsonResponse({'ok': False, 'count': 0, 'latest_ts': 0}, status=403)
    seller_id = request.user.username
    from .plugin_runtime.registry import is_plugin_enabled
    from .remittance_alert_helpers import remittance_alert_snapshot

    if not is_plugin_enabled('fulfillment', seller_id):
        return JsonResponse({'ok': True, 'count': 0, 'latest_ts': 0})
    count, latest_ts = remittance_alert_snapshot(seller_id)
    from .operating_helpers import build_order_alert_config

    return JsonResponse({
        'ok': True, 'count': count, 'latest_ts': latest_ts,
        'config': build_order_alert_config(seller_id),
    })


@login_required
@require_GET
def seller_fund_ledger_entry_drawer(request, ledger_id):
    """资金流水页：Ajax 拉单笔流水浮层 HTML。"""
    if request.user.role != 'seller':
        return JsonResponse({'ok': False, 'message': '请先登录卖家账号'}, status=403)
    seller_id = request.user.username
    from django.template.loader import render_to_string

    from .fund_ledger_helpers import build_ledger_entry_drawer_context
    from .models import FundLedgerEntry

    entry = (
        FundLedgerEntry.objects.filter(ledger_id=ledger_id, seller_id=seller_id)
        .select_related('buy_order', 'related_ledger')
        .prefetch_related('status_tracks')
        .first()
    )
    if not entry:
        return JsonResponse({'ok': False, 'message': '找不到这条流水'}, status=404)
    html = render_to_string(
        'waimai/seller/_fund_ledger_entry_drawer_body.html',
        build_ledger_entry_drawer_context(entry),
        request=request,
    )
    return JsonResponse({'ok': True, 'html': html})


@login_required
@require_GET
def seller_fund_ledger_order_drawer(request, order_id):
    """资金流水页：Ajax 拉订单摘要浮层 HTML。"""
    if request.user.role != 'seller':
        return JsonResponse({'ok': False, 'message': '请先登录卖家账号'}, status=403)
    seller_id = request.user.username
    from django.template.loader import render_to_string

    from .fund_ledger_helpers import build_order_drawer_context
    from .models import BuyOrder

    order = BuyOrder.objects.filter(order_id=order_id, seller_id=seller_id).first()
    if not order:
        return JsonResponse({'ok': False, 'message': '找不到这笔订单'}, status=404)
    html = render_to_string(
        'waimai/seller/_fund_ledger_order_drawer_body.html',
        build_order_drawer_context(order),
        request=request,
    )
    return JsonResponse({'ok': True, 'html': html})


@login_required
def seller_panel(request):
    """卖家管理入口：默认进入订单页（仅店主生态登录）"""
    if request.user.role != 'seller':
        return redirect('/accounts/login/')
    return redirect('seller_panel_section', section='orders')


@login_required
def seller_product_qr_print(request):
    """G1-7：使用中清单全部商品二维码 · 批量打印页"""
    if request.user.role != 'seller':
        return redirect('/accounts/login/')

    seller_id = request.user.username
    from .menu_helpers import get_active_menu_profile
    from .operating_helpers import resolve_shop_access_base_url
    from .product_qr_print_helpers import build_catalog_qr_print_cards

    missing_lan = not bool(resolve_shop_access_base_url(request, seller_id))
    return render(
        request,
        'waimai/seller/product_qr_print.html',
        {
            'print_cards': [] if missing_lan else build_catalog_qr_print_cards(request, seller_id),
            'print_qr_missing_lan': missing_lan,
            'active_profile': get_active_menu_profile(seller_id),
            'shop_profile': ShopProfile.objects.filter(seller_id=seller_id).first(),
        },
    )


@login_required
def seller_panel_attendance_logs(request):
    """员工考勤流水全表（新窗口打开；支持筛选与分页）"""
    if request.user.role != 'seller':
        return redirect('/accounts/login/')

    from .operating_helpers import get_operating_settings
    from .order_message_helpers import shop_unread_message_summary
    from .plugin_runtime.registry import collect_seller_nav_items
    from .staff_account_helpers import (
        attendance_logs_querystring,
        attendance_status_options,
        build_workbench_attendance_context,
        get_shop_staff_users,
    )

    seller_id = request.user.username
    operating = get_operating_settings(seller_id)
    staff_users = list(get_shop_staff_users(seller_id))
    attendance_ctx = build_workbench_attendance_context(
        request,
        seller_id,
        operating.attendance_retention_days,
        staff_users,
        default_today=False,
    )
    unread_summary = shop_unread_message_summary(seller_id)
    return render(
        request,
        'waimai/seller/attendance_logs.html',
        {
            'seller_id': seller_id,
            'shop_profile': ShopProfile.objects.filter(seller_id=seller_id).first(),
            'shop_unread_msg_total': unread_summary['total'],
            'seller_nav_items': collect_seller_nav_items(seller_id),
            'attendance_status_choices': attendance_status_options(),
            'attendance_logs_query': attendance_logs_querystring(request),
            'workbench_url': reverse('seller_panel_section', kwargs={'section': 'workbench'}),
            **attendance_ctx,
        },
    )


@login_required
@never_cache
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
        'payment', 'cash_manage', 'fund_ledger', 'audit', 'homepage', 'plugins',
        'operation_lock',
    )
    if section not in valid:
        return redirect('seller_panel_section', section='orders')

    from .v1_local_helpers import seller_section_hidden_in_v1, v1_local_block_message

    if seller_section_hidden_in_v1(section):
        from django.contrib import messages

        messages.info(request, v1_local_block_message())
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

    # 进度 80-2a：清单下拉换 Panel（GET + YecaoPanel 头，不整页 reload）
    if (
        request.method == 'GET'
        and section == 'products'
        and request.GET.get('profile') is not None
    ):
        from .menu_catalog_panel_helpers import render_menu_catalog_panel_html
        from .panel_refresh_helpers import is_panel_refresh, panel_refresh_ok

        if is_panel_refresh(request):
            profile_pick = request.GET.get('profile', '').strip()
            html = render_menu_catalog_panel_html(
                request,
                seller_id,
                profile_pick=profile_pick or None,
            )
            return panel_refresh_ok(html=html, panel_id='menu-panel-body', message='')

    # 进度 80：现金管理 · 汇总月份下拉 Panel 静默刷新（不整页 reload）
    if (
        request.method == 'GET'
        and section == 'cash_manage'
        and request.GET.get('cash_month') is not None
    ):
        from .cash_manage_panel_helpers import render_seller_cash_manage_panel_html
        from .panel_refresh_helpers import is_panel_refresh, panel_refresh_ok

        if is_panel_refresh(request):
            html = render_seller_cash_manage_panel_html(request, seller_id)
            return panel_refresh_ok(html=html, panel_id='cash-manage-panel-body', message='')

    if request.method == 'POST':
        if section == 'operation_lock':
            from .operation_lock_settings_helpers import handle_operation_lock_settings_post

            response = handle_operation_lock_settings_post(request)
            if response:
                return response
        response = None
        if section == 'operating':
            response = handle_operating_post(request, seller_id)
        elif section == 'dine':
            response = handle_dine_post(request, seller_id)
        elif section == 'products':
            if request.POST.get('upload_dish_image') == '1':
                from .product_seller_handlers import handle_upload_dish_image_ajax

                return handle_upload_dish_image_ajax(request, seller_id)
            from .menu_catalog_panel_helpers import (
                detect_menu_catalog_panel_action,
                run_menu_catalog_idempotent,
            )

            menu_action = detect_menu_catalog_panel_action(request)
            if menu_action:
                response = run_menu_catalog_idempotent(
                    request,
                    seller_id,
                    menu_action,
                    lambda: handle_products_post(request, seller_id),
                )
            else:
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
            build_seller_orders_list_context,
        )
        from .models import BuyOrder

        context.update(build_seller_orders_list_context(seller_id, request.GET))
        from .order_shell_helpers import (
            fulfillment_filter_choices,
            order_search_placeholder,
        )

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
        from .forms import ShopBossOrderNotifyForm
        from .order_notify_ui_helpers import smtp_not_ready_message

        operating = get_operating_settings(seller_id)
        context['boss_order_notify_form'] = ShopBossOrderNotifyForm(instance=operating)
        context['boss_order_notify_smtp_warn'] = smtp_not_ready_message(
            operating.boss_order_notify_enabled,
        )
    elif section == 'products':
        from .menu_helpers import find_menu_profile_by_pick_id, get_active_menu_profile
        from .product_shell_helpers import build_product_shell
        from .product_image_helpers import (
            MAX_DISH_IMAGES_PER_PRODUCT,
            MAX_DISH_IMAGE_UPLOAD_BYTES,
            dish_image_quota_hint,
        )
        from .sales_helpers import get_dish_sales_rankings
        operating = get_operating_settings(seller_id)
        product_shell = build_product_shell(seller_id)
        context['operating'] = operating
        context['product_shell'] = product_shell
        dishes = list(
            Dish.objects.filter(seller_id=seller_id)
            .prefetch_related('product_images')
            .order_by('sort_order', 'name')
        )
        for dish in dishes:
            dish.image_quota = dish_image_quota_hint(dish)
        context['dishes'] = dishes
        context['dish_image_max'] = MAX_DISH_IMAGES_PER_PRODUCT
        context['dish_image_max_mb'] = MAX_DISH_IMAGE_UPLOAD_BYTES // (1024 * 1024)
        context['dish_image_remaining'] = MAX_DISH_IMAGES_PER_PRODUCT
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
        edit_pick = context['edit_dish_id']
        if edit_pick:
            from .product_scan_helpers import (
                build_product_scan_qr_rows,
                product_scan_qr_missing_lan,
            )

            for dish in dishes:
                if dish.dish_id.hex[:8] == edit_pick:
                    context['edit_scan_qr_rows'] = build_product_scan_qr_rows(
                        request, dish, seller_id,
                    )
                    context['edit_scan_qr_missing_lan'] = product_scan_qr_missing_lan(
                        request, dish, seller_id,
                    )
                    break
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
            open_sess = get_open_main_session_for_table(t)
            t.is_busy = open_sess is not None
            if open_sess:
                token = ensure_addon_token(open_sess)
                t.addon_scan_path = build_addon_scan_path(seller_id, token) if token else ''
            else:
                t.addon_scan_path = ''
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
            attendance_logs_querystring,
            attendance_status_options,
            build_workbench_attendance_context,
            get_shop_staff_users,
            staff_account_type_label,
            staff_job_title,
            staff_permission_codes,
        )
        from .workbench_qr import build_work_login_qr_png

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
        attendance_ctx = build_workbench_attendance_context(
            request,
            seller_id,
            operating.attendance_retention_days,
            staff_users,
            default_today=True,
        )
        context.update(attendance_ctx)
        context['attendance_status_choices'] = attendance_status_options()
        context['attendance_logs_query'] = attendance_logs_querystring(request)
        context['attendance_full_url'] = (
            reverse('seller_panel_attendance_logs') + '?' + attendance_logs_querystring(request)
        )
        work_login_url = ''
        work_qr_data_url = ''
        work_qr_missing_lan = False
        if shop_profile and (shop_profile.shop_code or '').strip():
            from .operating_helpers import resolve_shop_access_base_url

            work_path = reverse(
                'shop_work',
                kwargs={'shop_code': shop_profile.shop_code.strip()},
            )
            base = resolve_shop_access_base_url(request, seller_id)
            if base:
                work_login_url = base.rstrip('/') + work_path
                png = build_work_login_qr_png(work_login_url)
                work_qr_data_url = (
                    'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
                )
            else:
                # 禁止用 127.0.0.1 生成给手机扫的码
                work_qr_missing_lan = True
        context['work_login_url'] = work_login_url
        context['work_qr_data_url'] = work_qr_data_url
        context['work_qr_missing_lan'] = work_qr_missing_lan
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
        from .payment_cert_helpers import build_wechat_cert_display, wechat_cert_status_label

        pay_settings = get_payment_settings(seller_id)
        context['wechat_cert_status'] = wechat_cert_status_label(pay_settings)
        context['wechat_cert_display'] = build_wechat_cert_display(pay_settings)
    elif section == 'cash_manage':
        from .cash_manage_helpers import build_seller_cash_manage_context

        context.update(build_seller_cash_manage_context(seller_id, request=request))
        context['cash_manage_form_action'] = reverse(
            'seller_panel_section', kwargs={'section': 'cash_manage'},
        )
        return render(request, 'waimai/seller/cash_manage.html', context)
    elif section == 'fund_ledger':
        from .fund_ledger_helpers import build_seller_fund_ledger_context

        context.update(build_seller_fund_ledger_context(seller_id, request))
        return render(request, 'waimai/seller/fund_ledger.html', context)
    elif section == 'audit':
        from .audit_helpers import (
            build_seller_audit_querystring,
            parse_audit_view_params,
            query_audit_logs,
            write_audit_log,
        )

        params = parse_audit_view_params(request.GET)
        only_me = params['scope'] == 'mine'
        keyword = params['q']
        write_audit_log(
            action_code='view_audit',
            summary='查看操作留痕' + ('（仅本人）' if only_me else '（本店全部）'),
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        context['audit_scope'] = params['scope']
        context['audit_q'] = keyword
        context['audit_query_scope_all'] = build_seller_audit_querystring(
            scope='all', q=keyword,
        )
        context['audit_query_scope_mine'] = build_seller_audit_querystring(
            scope='mine', q=keyword,
        )
        context['audit_logs'] = list(query_audit_logs(
            seller_id=seller_id,
            only_username=request.user.username if only_me else None,
            keyword=keyword,
            limit=100,
        ))
    elif section == 'homepage':
        from .home_page_helpers import (
            MAX_SHOP_CUSTOM_BLOCKS,
            count_shop_custom_blocks,
            ensure_home_page_for_seller,
        )
        from .home_page_panel_helpers import (
            SHOP_HOME_BLOCKS_PANEL_ID,
            build_shop_home_blocks,
        )

        page = ensure_home_page_for_seller(seller_id, shop_profile)
        blocks = build_shop_home_blocks(request, seller_id, shop_profile)
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
        context['home_blocks_panel_id'] = SHOP_HOME_BLOCKS_PANEL_ID
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
    elif section == 'operation_lock':
        from .operation_lock_settings_helpers import operation_lock_settings_context

        context.update(operation_lock_settings_context())

    return render(request, f'waimai/seller/{section}.html', context)


def place_order(request):
    """创建订单（服务端重新验价）。堂食游客持有效桌台会话可免登录；外卖/打包仍须登录买家。"""
    if request.method != 'POST':
        return redirect('shop')

    from .idempotency_helpers import idempotency_scope, run_idempotent

    seller_id = (request.POST.get('seller_id') or 'seller_001').strip()
    session_key = (request.session.session_key or 'anon')[:32]
    scope = idempotency_scope('place_order', seller_id, session_key)
    return run_idempotent(request, scope, lambda: _execute_place_order(request))


def _execute_place_order(request):
    """place_order 实际建单逻辑（幂等第 2 步 · 由 run_idempotent 包裹）。"""
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
    from waimai.plugins.dining.waiter_table_order_helpers import (
        get_waiter_table_order_meta,
        is_waiter_table_order_active,
    )

    seller_id = (request.POST.get('seller_id') or 'seller_001').strip()
    is_logged_buyer = (
        request.user.is_authenticated and request.user.role == 'buyer'
    )
    waiter_dine = is_waiter_table_order_active(request, seller_id)
    if waiter_dine and get_buyer_table_session(request, seller_id):
        is_logged_buyer = False
    if request.user.is_authenticated and not is_logged_buyer and not waiter_dine:
        # 店主/员工等非买家账号不能走买家下单口（服务员代客点菜除外）
        if seller_id:
            return redirect(f'/shop/?seller_id={seller_id}&error=请用买家账号或扫桌码免登录下单')
        return redirect('shop')
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

    cart, cart_items, subtotal, removed_notes = prepare_checkout_cart(cart, seller_id)
    if removed_notes:
        set_shop_cart(request.session, seller_id, cart)
    if not cart_items:
        msg = '购物车已没有可下单的商品，请重新选购'
        if removed_notes:
            msg = '；'.join(dict.fromkeys(removed_notes)) + '。请返回店铺重新选购。'
        messages.error(request, msg)
        return redirect(f'/shop/?seller_id={seller_id}')
    if removed_notes:
        messages.warning(request, '；'.join(dict.fromkeys(removed_notes)))

    ok_admit, admit_msg = check_order_admission(seller_id, fulfillment_type)
    if not ok_admit:
        return redirect(f'/shop/?seller_id={seller_id}&error={admit_msg}')

    for item in cart_items:
        ok, msg = validate_tier_purchase(
            item['dish'],
            item['price_tier'],
            request.user,
            seller_id,
            item['quantity'],
            cart,
            line_key=cart_line_key(item['dish'].dish_id, item['price_tier']),
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
            'prepared_count': 0,
            'served_count': 0,
        })

    table_label = ''
    order_kind = 'normal'
    order = None
    if table_sess:
        table_label = table_sess.display_label()
        if table_sess.session_type == 'main':
            order_kind = 'table_main'
            from waimai.plugins.dining.table_main_merge_helpers import (
                place_or_merge_table_main_order,
            )

            def _create_table_main_order():
                return BuyOrder.objects.create(
                    buyer_id=buyer_id,
                    seller_id=seller_id,
                    total_amount=total_amount,
                    subtotal_amount=subtotal,
                    delivery_fee=delivery_fee,
                    delivery_fee_detail=fee_detail,
                    dish_items=dish_items_json,
                    payment_status='pending_payment',
                    order_status='created',
                    delivery_address=delivery_address,
                    fulfillment_type=fulfillment_type,
                    distance_km=distance_km,
                    table_session=table_sess,
                    table_label=table_label,
                    order_kind=order_kind,
                    guest_nickname=guest_nickname,
                )

            action, order = place_or_merge_table_main_order(
                table_sess,
                cart_items,
                seller_id,
                distance_km,
                fulfillment_type,
                create_order_fn=_create_table_main_order,
            )
            if action == 'failed':
                return redirect(f'/shop/?seller_id={seller_id}&error=距离超过配送范围')
            if action == 'merged':
                if guest_nickname and not (order.guest_nickname or '').strip():
                    order.guest_nickname = guest_nickname
                    order.save(update_fields=['guest_nickname', 'updated_at'])
                set_shop_cart(request.session, seller_id, {})
                return _redirect_after_table_main_merge(
                    request, order, is_guest=is_guest, seller_id=seller_id,
                )
        elif table_sess.session_type == 'virtual':
            order_kind = 'virtual'
        elif table_sess.session_type == 'share_waiter':
            order_kind = 'share_waiter'

    if order is None:
        order = BuyOrder.objects.create(
            buyer_id=buyer_id,
            seller_id=seller_id,
            total_amount=total_amount,
            subtotal_amount=subtotal,
            delivery_fee=delivery_fee,
            delivery_fee_detail=fee_detail,
            dish_items=dish_items_json,
            payment_status='pending_payment',
            order_status='created',
            delivery_address=delivery_address,
            fulfillment_type=fulfillment_type,
            distance_km=distance_km,
            table_session=table_sess,
            table_label=table_label,
            order_kind=order_kind,
            guest_nickname=guest_nickname,
        )

    set_shop_cart(request.session, seller_id, {})
    from .audit_helpers import write_audit_log
    from .shop_work_auth import get_shop_work_user

    waiter_meta = get_waiter_table_order_meta(request, seller_id) if waiter_dine else None
    work_user = get_shop_work_user(request) if waiter_meta else None
    if waiter_meta:
        actor_label = f'服务员代下（{waiter_meta.get("operator") or "工作台"}）'
        audit_actor = work_user
    elif is_guest:
        actor_label = '游客'
        audit_actor = None
    else:
        actor_label = '买家'
        audit_actor = request.user if is_logged_buyer else None
    write_audit_log(
        action_code='order_place',
        summary=f'{actor_label}下单 {order.get_display_order_no()} · ¥{order.total_amount}',
        seller_id=seller_id,
        actor=audit_actor,
        target_type='order',
        target_id=str(order.order_id),
        request=request,
    )

    # 游客堂食：直接现场付现金，跳过在线支付页
    if is_guest:
        from .order_qr_helpers import order_cash_code_url

        ok_cash, cash_errors = apply_guest_onsite_cash(order)
        if not ok_cash:
            from .order_status_transition_helpers import transition_order_status

            transition_order_status(
                order, 'cancelled', source='views.create_order.guest_catalog_cap_fail',
            )
            order.payment_status = 'cancelled'
            order.save(update_fields=['payment_status', 'updated_at'])
            for err in cash_errors:
                messages.error(request, err)
            return redirect(f'/shop/?seller_id={seller_id}')
        return redirect(order_cash_code_url(order.order_id))

    return redirect('pay_order', order_id=order.order_id)


def _execute_pay_order_post(request, order):
    """支付页 POST：选支付方式（幂等第 7 步 · 由 run_idempotent 包裹）。"""
    method = request.POST.get('payment_method', '').strip()
    result = initiate_payment(order, method, _client_ip(request))
    if not result.ok:
        for err in (result.messages or [result.message]):
            if err:
                messages.error(request, err)
        return redirect('pay_order', order_id=order.order_id)
    if result.redirect_url:
        return redirect(result.redirect_url)
    if result.template_name:
        ctx = build_pay_page_context(order)
        ctx.update(result.extra_context or {})
        ctx['wechat_pay_mode'] = True
        return render(request, result.template_name, ctx)
    return redirect('pay_order', order_id=order.order_id)


def pay_order(request, order_id):
    """待支付页：多支付方式选择 / 微信扫码。游客堂食单靠桌台会话认领。"""
    from .guest_order_helpers import buyer_or_guest_can_access_order
    from .idempotency_helpers import extract_idempotency_key
    from .initiate_payment_helpers import run_initiate_payment_idempotent
    from .order_qr_helpers import order_cash_code_url

    order = get_object_or_404(BuyOrder, order_id=order_id)
    table_sess = get_buyer_table_session(request, order.seller_id)
    if not buyer_or_guest_can_access_order(request, order, table_sess):
        if request.user.is_authenticated:
            return redirect('order_history')
        return redirect('login')

    # 带幂等键的 POST 须先重放，避免首单已付清后被「非待支付」挡在外面
    if request.method == 'POST' and extract_idempotency_key(request):
        return run_initiate_payment_idempotent(
            request, order, lambda: _execute_pay_order_post(request, order),
        )

    if order.payment_status != 'pending_payment':
        if order.is_guest_order():
            return redirect('order_detail', order_id=order.order_id)
        return redirect('order_history')

    if order.is_cash_awaiting_confirm():
        return redirect(order_cash_code_url(order.order_id))

    # 游客堂食单不应进在线支付页：补走现场付
    if order.is_guest_order() and order.is_dine_in():
        from .guest_order_helpers import apply_guest_onsite_cash

        ok_cash, cash_errors = apply_guest_onsite_cash(order)
        if not ok_cash:
            for err in cash_errors:
                messages.error(request, err)
            return redirect('pay_order', order_id=order.order_id)
        return redirect(order_cash_code_url(order.order_id))

    ctx = build_pay_page_context(order)

    if request.method == 'POST':
        return run_initiate_payment_idempotent(
            request, order, lambda: _execute_pay_order_post(request, order),
        )

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


def order_cash_code(request, order_id):
    """买家轻页订单码（现金选单后 · 只读）。"""
    from .guest_order_helpers import buyer_or_guest_can_access_order
    from .order_qr_helpers import build_order_cash_code_page_context, order_cash_code_url

    order = get_object_or_404(BuyOrder, order_id=order_id)
    table_sess = get_buyer_table_session(request, order.seller_id)
    if not buyer_or_guest_can_access_order(request, order, table_sess):
        if request.user.is_authenticated:
            return redirect('order_history')
        return redirect('login')
    if order.payment_method != 'cash' or order.payment_status != 'pending_payment':
        return redirect('order_detail', order_id=order.order_id)
    context = build_order_cash_code_page_context(request, order)
    context['page_back_url'] = context['shop_url']
    context['page_back_label'] = '返回店铺继续点菜'
    return render(request, 'waimai/order_cash_code.html', context)


def order_cash_code_print(request, order_id):
    """买家轻页订单码 · 打印版（只读）。"""
    from .guest_order_helpers import buyer_or_guest_can_access_order
    from .order_qr_helpers import build_order_cashier_qr_bundle, order_cash_code_url, resolve_shop_code_for_order

    order = get_object_or_404(BuyOrder, order_id=order_id)
    table_sess = get_buyer_table_session(request, order.seller_id)
    if not buyer_or_guest_can_access_order(request, order, table_sess):
        if request.user.is_authenticated:
            return redirect('order_history')
        return redirect('login')
    shop_profile = ShopProfile.objects.filter(seller_id=order.seller_id).first()
    qr_bundle = build_order_cashier_qr_bundle(
        request, order, resolve_shop_code_for_order(order),
    )
    if not qr_bundle:
        messages.info(request, '当前订单暂不可打印收银码，请查看轻页说明。')
        return redirect(order_cash_code_url(order.order_id))
    return render(request, 'waimai/order_cashier_qr_print.html', {
        'order': order,
        'qr_bundle': qr_bundle,
        'shop_name': shop_profile.shop_name if shop_profile else '',
        'back_url': order_cash_code_url(order.order_id),
    })


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
            messages.error(request, '只有本订单买家可以确认实际支付金额')
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

    from .payments import poll_wechat_refund
    from .payments.wechat_refund_helpers import shop_cancel_refund_hint

    if user and getattr(user, 'role', '') == 'seller' and order.seller_id == user.username:
        poll_wechat_refund(order)
        order.refresh_from_db()

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
    from .order_qr_helpers import order_cashier_qr_template_context, resolve_shop_code_for_order

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

    shop_code_for_qr = resolve_shop_code_for_order(order)
    qr_print_url = ''
    qr_buyer_hint = viewer_role in ('buyer', 'guest')
    if viewer_role == 'seller':
        qr_print_url = reverse('seller_order_cashier_qr_print', kwargs={'order_id': order.order_id})
    qr_ctx = order_cashier_qr_template_context(
        request,
        order,
        shop_code=shop_code_for_qr,
        print_url=qr_print_url,
        show_buyer_hint=qr_buyer_hint,
    )

    timeline_viewer = viewer_role if viewer_role in ('buyer', 'seller', 'rider') else 'buyer'

    fund_ledger_rows = []
    if viewer_role == 'seller':
        from .fund_ledger_helpers import list_order_fund_ledger_entries

        fund_ledger_rows = list_order_fund_ledger_entries(order)

    return render(request, 'waimai/order_detail.html', {
        'order': order,
        'order_shell': order_shell,
        'shop_profile': shop_profile,
        'timeline': build_order_timeline(order, viewer=timeline_viewer),
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
        'shop_cancel_refund_hint': shop_cancel_refund_hint(order) if user else '',
        'shop_work_code': '',
        'shop_work_back_url': '',
        'guest_shop_back_url': f'/shop/?seller_id={order.seller_id}' if viewer_role == 'guest' else '',
        'fund_ledger_rows': fund_ledger_rows,
        **qr_ctx,
    })
