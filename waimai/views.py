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
    CreateKitchenForm,
    CreateRiderForm,
    CreateWaiterForm,
    ShopDeliverySettingsForm,
    ShopOperatingSettingsForm,
    ShopPaymentSettingsForm,
    ShopRegistrationForm,
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
from .table_helpers import (
    build_table_scan_path,
    build_virtual_scan_path,
    get_open_order_for_session,
    get_table_by_token,
    get_virtual_by_token,
    open_table_main_session,
    open_virtual_session,
    virtual_code_is_busy,
)
from .table_bulk_helpers import sort_shop_tables, sort_virtual_codes
from .dine_seller_handlers import handle_dine_post
from .product_seller_handlers import handle_products_post
from .product_helpers import (
    build_dish_tier_options,
    cart_line_key,
    validate_tier_purchase,
    PRICE_TIER_GENERAL,
)
from .order_helpers import (
    build_cart_items,
    build_order_pricing,
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
    from .staff_account_helpers import deactivate_staff_on_logout, shop_code_from_request

    if request.method != 'POST':
        code = (shop_code or '').strip() or shop_code_from_request(request)
        if code:
            return redirect(build_shop_work_path(code))
        return redirect('directory')

    work_user = get_shop_work_user(request)
    code = (shop_code or '').strip() or shop_code_from_request(request)
    if work_user:
        write_audit_log(
            action_code='logout',
            summary='店铺工作台退出',
            actor=work_user,
            request=request,
        )
    if work_user and work_user.role in ('waiter', 'kitchen', 'rider'):
        deactivate_staff_on_logout(work_user)
    clear_shop_work_session(request)
    messages.success(request, '已退出店铺工作台')
    if code:
        return redirect(build_shop_work_path(code))
    return redirect('directory')


# 会话守护接口（心跳 / 关页尽量退出）
from .session_guard import session_beacon_logout, session_heartbeat  # noqa: E402


def home(request):
    """本服务器默认入口：拥有者展示主页（A.10）；无店时给开通引导"""
    from .home_page_helpers import build_home_view_context, resolve_entry_home_page

    page = resolve_entry_home_page()
    if not page:
        return render(request, 'waimai/home_empty.html')
    context = build_home_view_context(page, request)
    return render(request, 'waimai/showcase_home.html', context)


def directory(request):
    """旧名录地址：兼容跳到本服务器入口主页（名录改为可选积木块）"""
    return redirect('home')


def shop_showcase(request, shop_code=None):
    """按店铺码打开某店展示主页（非默认入口时也可直达）"""
    from .home_page_helpers import build_home_view_context, ensure_home_page_for_seller
    from .shop_work_helpers import get_shop_profile_by_code

    code = (shop_code or '').strip()
    profile = get_shop_profile_by_code(code) if code else None
    if not profile:
        seller_id = (request.GET.get('seller_id') or '').strip()
        profile = ShopProfile.objects.filter(seller_id=seller_id).first() if seller_id else None
    if not profile:
        return redirect('home')
    page = ensure_home_page_for_seller(profile.seller_id, profile)
    context = build_home_view_context(page, request)
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
    """旧地址：跳转到本店工作台"""
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
        current_view = (request.GET.get('view') or default_work_view(work_user)).strip()
        if current_view not in WORK_VIEWS:
            current_view = default_work_view(work_user)
        perms = work_permissions(work_user)

        if request.method == 'POST':
            if not perms.get(current_view):
                messages.error(request, '您没有权限执行此操作')
                return redirect(build_shop_work_path(code, view=current_view))
            response = handle_shop_work_post(
                request, seller_id, code, current_view, perms, work_user=work_user,
            )
            if response:
                return response

        form_action = build_shop_work_path(code, view=current_view)
        context = {
            'shop_profile': shop_profile,
            'current_view': current_view,
            'form_action': form_action,
            'tab_waiter_url': build_shop_work_path(code, view='waiter'),
            'tab_kitchen_url': build_shop_work_path(code, view='kitchen'),
            'tab_rider_url': build_shop_work_path(code, view='rider'),
            'can_operate_waiter': perms['waiter'],
            'can_operate_kitchen': perms['kitchen'],
            'can_operate_rider': perms['rider'],
            'show_rider_extras': work_user.role == 'rider',
            'shop_work_code': code,
            'shop_work_logout_url': reverse('shop_work_logout', kwargs={'shop_code': code}),
            'dispatch_role': get_delivery_dispatch_role(seller_id),
            'work_user': work_user,
        }
        context.update(build_shop_work_daily_history(seller_id, work_user))
        from .audit_helpers import query_audit_logs, write_audit_log
        # 服务方仅看本人操作记录（A.12）
        if work_user.role in ('waiter', 'kitchen', 'rider'):
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
        if current_view == 'waiter':
            context.update(build_waiter_board_context(
                seller_id,
                allow_dispatch=(work_user.role == 'seller' or get_delivery_dispatch_role(seller_id) == 'waiter'),
            ))
        elif current_view == 'kitchen':
            context.update(build_kitchen_board_context(
                seller_id,
                allow_dispatch=(work_user.role == 'seller' or get_delivery_dispatch_role(seller_id) == 'kitchen'),
            ))
        else:
            context.update(build_rider_board_context(work_user, seller_id))
        return render(request, 'waimai/shop_work_hub.html', context)

    if request.method == 'POST':
        from .audit_helpers import write_audit_log
        from .staff_account_helpers import activate_staff_on_login, authenticate_shop_work_user

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate_shop_work_user(request, seller_id, username, password)
        if user is not None:
            from .experience_helpers import can_accept_online, touch_online_user

            ok, msg = can_accept_online(user)
            if not ok:
                messages.error(request, msg)
                return render(request, 'waimai/shop_work_login.html', {'shop_profile': shop_profile})
            if user.role in ('waiter', 'kitchen', 'rider'):
                activate_staff_on_login(user)
            establish_shop_work_session(request, user, seller_id=seller_id, shop_code=code)
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


def waiter_pay_order(request, order_id):
    """服务员协助收款：选择支付方式（绑定本单）；认工作台登录身份"""
    from .payments import build_pay_page_context
    from .shop_work_auth import get_shop_work_user
    from .waiter_handlers import handle_waiter_pay_post
    from .waiter_helpers import ensure_waiter_employer, sync_waiter_service_status
    from .shop_work_helpers import resolve_waiter_return_url

    work_user = get_shop_work_user(request)
    if not work_user or work_user.role not in ('waiter', 'seller'):
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
                messages.success(request, '已选择现金，待店家确认接单后可点「确认已收现金」')
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

    work_user = get_shop_work_user(request)
    if not work_user or work_user.role not in ('waiter', 'seller'):
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


def _shop_cart_redirect(seller_id, keep_cart_open=False, dish_id=None):
    """加减购物车后跳回店铺；可打开购物车抽屉或定位到某菜品"""
    url = f'/shop/?seller_id={seller_id}'
    if keep_cart_open:
        return redirect_with_anchor(url, 'cart')
    anchor = dish_scroll_anchor(dish_id) if dish_id else None
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


def _shop_page_dishes(seller_id):
    """店铺页菜品列表（含菜单清单过滤）"""
    dishes, using_menu = get_shop_dishes_for_sale(seller_id)
    return dishes, using_menu


def _table_session_key(seller_id):
    return f'table_session_{seller_id}'


def _get_buyer_table_session(request, seller_id):
    """买家当前绑定的桌台会话"""
    raw = request.session.get(_table_session_key(seller_id))
    if not raw:
        return None
    return TableSession.objects.filter(
        session_id=raw, seller_id=seller_id, status='open',
    ).select_related('shop_table', 'virtual_code').first()


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
    """店铺页统一渲染（含菜单过滤与桌台信息）"""
    dishes, using_menu = _shop_page_dishes(seller_id)
    menu_items_map = get_active_menu_items_map(seller_id) if using_menu else {}
    table_session = _get_buyer_table_session(request, seller_id)
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
        'table_session': table_session,
        'table_label': table_session.display_label() if table_session else '',
        'error': error or request.GET.get('error', ''),
        **_shop_cart_context(cart, seller_id),
    }
    if extra:
        ctx.update(extra)
    return render(request, 'waimai/shop.html', ctx)


def shop_page(request):
    """店铺页面：菜品展示 + 购物车 + 下单确认"""
    seller_id = request.GET.get('seller_id', 'seller_001')
    cart = get_shop_cart(request.session, seller_id)
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    delivery_settings = get_delivery_settings(seller_id)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'add_to_cart':
            dish_id = request.POST.get('dish_id')
            tier = request.POST.get('price_tier', PRICE_TIER_GENERAL)
            cart = normalize_cart_keys(cart)
            table_sess = _get_buyer_table_session(request, seller_id)
            ft = 'dine_in' if table_sess else 'delivery'
            ok_admit, admit_msg = check_order_admission(seller_id, ft)
            if not ok_admit:
                return _shop_render(request, seller_id, cart, shop_profile, error=admit_msg)
            try:
                dish = Dish.objects.get(dish_id=dish_id, seller_id=seller_id, is_active=True)
            except Dish.DoesNotExist:
                return _shop_render(request, seller_id, cart, shop_profile, error='菜品不存在或已下架')
            if not dish_visible_on_shop(seller_id, dish_id):
                return _shop_render(request, seller_id, cart, shop_profile, error='该菜品不在当前使用中的菜单清单里')
            line_key = cart_line_key(dish_id, tier)
            qty = cart.get(line_key, 0) + 1
            ok, msg = validate_tier_purchase(dish, tier, request.user, seller_id, qty, cart)
            if not ok:
                return _shop_render(request, seller_id, cart, shop_profile, error=msg)
            cart[line_key] = qty
            set_shop_cart(request.session, seller_id, cart)
            if request.POST.get('stay_in_cart'):
                return _shop_cart_redirect(seller_id, keep_cart_open=True)
            return _shop_cart_redirect(seller_id, dish_id=dish_id)

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
            return _shop_cart_redirect(seller_id, keep_cart_open=True)

        if action == 'remove_from_cart':
            line_key = request.POST.get('line_key') or cart_line_key(
                request.POST.get('dish_id'), request.POST.get('price_tier', PRICE_TIER_GENERAL),
            )
            cart = normalize_cart_keys(cart)
            cart.pop(line_key, None)
            set_shop_cart(request.session, seller_id, cart)
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
            if not request.user.is_authenticated or request.user.role != 'buyer':
                return _shop_render(request, seller_id, cart, shop_profile, error='只有买家身份才能下单')

            cart_items, subtotal = build_cart_items(cart, seller_id, for_checkout=True)
            if not cart_items:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='请至少选择一份数量大于 0 的商品再结算',
                )

            table_sess = _get_buyer_table_session(request, seller_id)
            fulfillment_type = 'dine_in' if table_sess else 'delivery'
            ok_admit, admit_msg = check_order_admission(seller_id, fulfillment_type)
            if not ok_admit:
                return _shop_render(request, seller_id, cart, shop_profile, error=admit_msg)

            for item in cart_items:
                ok, msg = validate_tier_purchase(
                    item['dish'], item['price_tier'], request.user, seller_id, item['quantity'], cart,
                )
                if not ok:
                    return _shop_render(request, seller_id, cart, shop_profile, error=msg)

            distance_km = parse_distance_km(request.POST.get('distance_km'))
            delivery_address = request.POST.get('delivery_address', '默认地址').strip() or '默认地址'
            if table_sess:
                distance_km = 0
                delivery_address = store_delivery_address(shop_profile, 'dine_in')

            delivery_fee, fee_detail = build_order_pricing(
                seller_id, subtotal, distance_km, fulfillment_type,
            )
            if delivery_fee is None:
                return _shop_render(
                    request, seller_id, cart, shop_profile,
                    error='配送距离超过该店铺最远配送范围',
                )

            free_delivery = (
                delivery_settings.free_delivery_threshold
                and subtotal >= delivery_settings.free_delivery_threshold
            )
            total_amount = subtotal + delivery_fee

            return render(request, 'waimai/confirm_order.html', {
                'cart_items': cart_items,
                'subtotal': subtotal,
                'delivery_fee': delivery_fee,
                'delivery_fee_detail': fee_detail,
                'free_delivery': delivery_fee == 0 and subtotal > 0 and fulfillment_type == 'delivery',
                'total_amount': total_amount,
                'distance_km': distance_km,
                'delivery_address': delivery_address,
                'fulfillment_type': fulfillment_type,
                'seller_id': seller_id,
                'shop_profile': shop_profile,
                'table_label': table_sess.display_label() if table_sess else '',
            })

    return _shop_render(request, seller_id, cart, shop_profile, extra={
        'success': request.GET.get('success', False),
        'success_fulfillment': request.GET.get('fulfillment', ''),
    })


def dine_table_entry(request):
    """扫桌码/虚拟码入口：建立桌台会话后进入店铺点菜"""
    seller_id = (request.GET.get('seller_id') or '').strip()
    t_token = (request.GET.get('t') or '').strip()
    v_token = (request.GET.get('v') or '').strip()
    if not seller_id:
        return redirect('directory')

    device_key = request.session.session_key or ''

    if t_token:
        table = get_table_by_token(seller_id, t_token)
        if not table:
            return redirect(f'/shop/?seller_id={seller_id}&error=桌码无效或已停用')
        session, err = open_table_main_session(table, device_key)
    elif v_token:
        code = get_virtual_by_token(seller_id, v_token)
        if not code:
            return redirect(f'/shop/?seller_id={seller_id}&error=虚拟桌码无效或已停用')
        session, err = open_virtual_session(code, device_key)
    else:
        return redirect(f'/shop/?seller_id={seller_id}')

    if err:
        return redirect(f'/shop/?seller_id={seller_id}&error={err}')
    if not session:
        return redirect(f'/shop/?seller_id={seller_id}&error=无法开台')

    request.session[_table_session_key(seller_id)] = str(session.session_id)
    request.session.modified = True
    return redirect(f'/shop/?seller_id={seller_id}')


def my_deliveries(request):
    """旧地址：统一引导到店铺工作台骑手视角"""
    work_redirect = _redirect_to_shop_work(request, 'rider')
    if work_redirect:
        return work_redirect
    return redirect('directory')


def rider_delivery_history(request):
    """骑手配送记录：仅工作台骑手会话可看"""
    from .shop_work_auth import get_shop_work_user

    work_user = get_shop_work_user(request)
    if not work_user or work_user.role != 'rider':
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
            touch_online_user(user)
            return redirect('seller_panel')
    else:
        form = ShopRegistrationForm()
    ctx = {'form': form, **experience_hint_context()}
    return render(request, 'waimai/shop_register.html', ctx)


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

    valid = ('orders', 'products', 'dine', 'workbench', 'delivery', 'payment', 'audit', 'homepage')
    if section not in valid:
        return redirect('seller_panel_section', section='orders')

    seller_id = request.user.username

    if request.method == 'POST':
        response = None
        if section == 'dine':
            response = handle_dine_post(request, seller_id)
        elif section == 'products':
            response = handle_products_post(request, seller_id)
        elif section == 'workbench':
            from .workbench_handlers import handle_seller_workbench_post
            response = handle_seller_workbench_post(request, seller_id)
        elif section == 'homepage':
            from .home_page_handlers import handle_home_page_post
            response = handle_home_page_post(request, seller_id)
        elif section == 'audit':
            response = None
        else:
            response = handle_seller_post(request, seller_id, section)
        if response:
            return response

    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    context = {
        'section': section,
        'seller_id': seller_id,
        'shop_profile': shop_profile,
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
        orders = query_seller_orders(seller_id, order_search)
        context['orders'] = orders
        context['order_search'] = order_search
        context['order_date_range_choices'] = ORDER_DATE_RANGE_CHOICES
        context['order_status_choices'] = BuyOrder.ORDER_STATUS_CHOICES
        context['payment_status_choices'] = BuyOrder.PAYMENT_STATUS_CHOICES
        context['fulfillment_type_choices'] = BuyOrder.FULFILLMENT_TYPE_CHOICES
        new_orders = [o for o in orders if o.order_status == 'awaiting_prep']
        context['seller_new_order_ts'] = int(max((o.created_at.timestamp() for o in new_orders), default=0) * 1000)
    elif section == 'products':
        from .menu_helpers import find_menu_profile_by_pick_id, get_active_menu_profile
        from .sales_helpers import get_dish_sales_rankings
        operating = get_operating_settings(seller_id)
        context['operating'] = operating
        context['dishes'] = Dish.objects.filter(seller_id=seller_id).order_by('sort_order', 'name')
        context['sales_rankings'] = get_dish_sales_rankings(seller_id)
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
    elif section == 'dine':
        from .models import ShopTable, VirtualTableCode
        operating = get_operating_settings(seller_id)
        context['operating'] = operating
        context['operating_form'] = ShopOperatingSettingsForm(instance=operating)
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

        from .forms import CreateKitchenForm, CreateRiderForm, CreateWaiterForm, ShopWorkbenchSettingsForm
        from .kitchen_helpers import get_shop_kitchens
        from .staff_account_helpers import (
            AttendanceFilterForm,
            attendance_status_options,
            build_mobile_share_url,
            build_staff_status_rows,
            query_attendance_logs,
            staff_role_label,
        )
        from .waiter_helpers import get_shop_waiters
        from .workbench_qr import build_work_login_qr_png

        operating = get_operating_settings(seller_id)
        context['workbench_settings_form'] = ShopWorkbenchSettingsForm(instance=operating)
        context['waiters'] = get_shop_waiters(seller_id)
        context['waiter_form'] = CreateWaiterForm(seller_id=seller_id)
        context['kitchens'] = get_shop_kitchens(seller_id)
        context['kitchen_form'] = CreateKitchenForm(seller_id=seller_id)
        context['riders'] = get_shop_riders(seller_id, active_only=False)
        context['rider_form'] = CreateRiderForm(seller_id=seller_id)
        attendance_filter_form = AttendanceFilterForm(request.GET or None)
        attendance_filters = attendance_filter_form.cleaned_data if attendance_filter_form.is_valid() else {}
        staff_users = list(context['waiters']) + list(context['kitchens']) + list(context['riders'])
        staff_users.sort(key=lambda user: (staff_role_label(user.role), user.date_joined, user.username))
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
            work_mobile_url = build_mobile_share_url(work_login_url)
            if work_mobile_url:
                mobile_png = build_work_login_qr_png(work_mobile_url)
                work_mobile_qr_data_url = 'data:image/png;base64,' + base64.b64encode(mobile_png).decode('ascii')
        context['work_login_url'] = work_login_url
        context['work_qr_data_url'] = work_qr_data_url
        context['work_mobile_url'] = work_mobile_url
        context['work_mobile_qr_data_url'] = work_mobile_qr_data_url
    elif section == 'delivery':
        context['settings_form'] = ShopDeliverySettingsForm(
            instance=get_delivery_settings(seller_id)
        )
    elif section == 'payment':
        from .experience_helpers import experience_site_enabled, seller_blocked_from_real_wechat
        from .payments import get_payment_settings
        context['payment_form'] = ShopPaymentSettingsForm(
            instance=get_payment_settings(seller_id)
        )
        context['experience_block_wechat'] = seller_blocked_from_real_wechat(seller_id)
        context['experience_site'] = experience_site_enabled()
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
        from .home_page_helpers import ensure_home_page_for_seller, get_block_spec

        page = ensure_home_page_for_seller(seller_id, shop_profile)
        blocks = list(page.blocks.order_by('sort_order', 'block_type'))
        for b in blocks:
            b.spec = get_block_spec(b.block_type)
        context['home_page'] = page
        context['home_blocks'] = blocks
        context['showcase_preview_url'] = '/'
        if shop_profile and (shop_profile.shop_code or '').strip():
            context['showcase_preview_url'] = f"/s/{shop_profile.shop_code.strip()}/home/"

    return render(request, f'waimai/seller/{section}.html', context)


@login_required
def place_order(request):
    """创建待支付订单（服务端重新验价）"""
    if request.method != 'POST':
        return redirect('shop')

    if request.user.role != 'buyer':
        return redirect('shop')

    seller_id = request.POST.get('seller_id', 'seller_001')
    cart = get_shop_cart(request.session, seller_id)
    if not cart:
        return redirect(f'/shop/?seller_id={seller_id}')

    fulfillment_type = parse_fulfillment_type(request.POST.get('fulfillment_type'))
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    table_sess = _get_buyer_table_session(request, seller_id)

    if table_sess:
        fulfillment_type = 'dine_in'
    elif fulfillment_type == 'dine_in' and not request.POST.get('dine_in_at_shop'):
        messages.error(request, '堂食下单须勾选「我已在店内」')
        return redirect(f'/shop/?seller_id={seller_id}&error=堂食须勾选已在店内')

    if fulfillment_type in ('dine_in', 'takeaway'):
        delivery_address = store_delivery_address(shop_profile, fulfillment_type)
        distance_km = 0
    else:
        distance_km = parse_distance_km(request.POST.get('distance_km'))
        delivery_address = request.POST.get('delivery_address', '默认地址').strip() or '默认地址'

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
                    increment_menu_sold_counts(seller_id, cart_items)
                    set_shop_cart(request.session, seller_id, {})
                    return redirect('pay_order', order_id=merged.order_id)
        elif table_sess.session_type == 'virtual':
            order_kind = 'virtual'
        elif table_sess.session_type == 'share_waiter':
            order_kind = 'share_waiter'

    order = BuyOrder.objects.create(
        buyer_id=request.user.username,
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
    )

    increment_menu_sold_counts(seller_id, cart_items)
    set_shop_cart(request.session, seller_id, {})
    from .audit_helpers import write_audit_log
    write_audit_log(
        action_code='order_place',
        summary=f'买家下单 {order.get_display_order_no()} · ¥{order.total_amount}',
        seller_id=seller_id,
        actor=request.user,
        target_type='order',
        target_id=str(order.order_id),
        request=request,
    )
    return redirect('pay_order', order_id=order.order_id)


@login_required
def pay_order(request, order_id):
    """待支付页：多支付方式选择 / 微信扫码"""
    order = get_object_or_404(BuyOrder, order_id=order_id, buyer_id=request.user.username)

    if order.payment_status != 'pending_payment':
        return redirect('order_history')

    if order.is_cash_awaiting_confirm():
        return redirect(f'/order/{order.order_id}/?cash_pending=1')

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


@login_required
@require_GET
def pay_order_status(request, order_id):
    """买家扫码等待时轮询：是否已支付"""
    order = get_object_or_404(BuyOrder, order_id=order_id, buyer_id=request.user.username)
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
    order_rows = [
        {
            'order': o,
            'shop_name': shop_names.get(o.seller_id, o.seller_id),
        }
        for o in orders
    ]
    return render(request, 'waimai/order_history.html', {'order_rows': order_rows})


@login_required
def order_detail(request, order_id):
    """订单详情（买家、卖家均可查看自己的订单）"""
    order = get_object_or_404(
        BuyOrder.objects.select_related('delivery_order'),
        order_id=order_id,
    )
    user = request.user
    if user.role == 'buyer' and order.buyer_id != user.username:
        return redirect('order_history')
    if user.role == 'seller' and order.seller_id != user.username:
        return redirect('seller_panel_section', section='orders')
    if user.role == 'waiter':
        from .waiter_helpers import ensure_waiter_employer
        employer = ensure_waiter_employer(user)
        if not employer or order.seller_id != employer:
            return redirect('waiter_home')
    if user.role == 'rider':
        delivery = getattr(order, 'delivery_order', None)
        if not delivery or delivery.rider_id != user.username:
            return redirect('rider_home')

    shop_profile = ShopProfile.objects.filter(seller_id=order.seller_id).first()
    fee_detail = order.delivery_fee_detail
    if not fee_detail:
        _, fee_detail = build_delivery_fee_breakdown(
            order.seller_id, float(order.distance_km), order.get_subtotal()
        )

    back_url = 'order_history'
    if user.role == 'seller':
        back_url = 'seller_panel_section'
    elif user.role == 'rider':
        back_url = 'my_deliveries'
    elif user.role == 'waiter':
        back_url = 'waiter_home'

    return render(request, 'waimai/order_detail.html', {
        'order': order,
        'shop_profile': shop_profile,
        'timeline': build_order_timeline(order),
        'dish_lines': dish_items_with_line_totals(order.dish_items),
        'subtotal': order.get_subtotal(),
        'delivery_fee': order.get_delivery_fee_amount(),
        'delivery_fee_detail': fee_detail,
        'back_url': back_url,
        'viewer_role': user.role,
    })
