# 新版新手体验：演示页上下文（当前仅营业状态）

from __future__ import annotations

from typing import Any

from waimai.models import Dish, MenuProfile, ShopProfile
from waimai.order_message_helpers import shop_unread_message_summary

from .demo_cleanup import DEMO_DISH_NAME
from .official_shop import get_official_shop_profile
from .preview_context import base_experience_preview_context
from .tour_session import load_tour_query, touch_experience_tour_session


def _experience_print_qr_url(request) -> str:
    """带 exp 引导参数的打印页链接"""
    from django.urls import reverse
    from urllib.parse import urlencode

    base = reverse('experience_preview_print_qr')
    q = load_tour_query(request)
    if not q:
        return base
    return f'{base}?{urlencode(q)}'


def _experience_tour_query(request) -> dict[str, str]:
    """从 URL 与 session 取出 exp 引导参数，供模板 hidden 字段使用"""
    touch_experience_tour_session(request)
    return load_tour_query(request)


def _ensure_menu_tour_demo_dish(seller_id: str) -> None:
    """确保官方演示店至少有一个可演示会员价/特价的商品"""
    dish = Dish.objects.filter(
        seller_id=seller_id,
        member_price_enabled=True,
        special_price_enabled=True,
    ).first()
    if dish:
        return
    dish = Dish.objects.filter(seller_id=seller_id).order_by('sort_order', 'name').first()
    if not dish:
        return
    dish.member_price_enabled = True
    dish.special_price_enabled = True
    if not dish.member_price_mode:
        dish.member_price_mode = 'percent'
    if not dish.special_price_mode:
        dish.special_price_mode = 'percent'
    dish.save(update_fields=[
        'member_price_enabled',
        'special_price_enabled',
        'member_price_mode',
        'special_price_mode',
    ])


def build_experience_operating_context(request) -> dict[str, Any]:
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.forms import ShopStatusSettingsForm
    from waimai.operating_helpers import get_operating_settings

    ctx = base_experience_preview_context('营业状态（演示）', 'operating')
    operating = get_operating_settings(seller_id)
    unread = shop_unread_message_summary(seller_id)
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    ctx.update({
        'operating': operating,
        'status_form': ShopStatusSettingsForm(instance=operating),
        'is_shop_open': (not operating.closed_for_today) and (not operating.pause_new_orders),
        'shop_profile': shop_profile,
        'shop_unread_msg_total': unread['total'],
    })
    return ctx


def build_experience_products_context(request, *, profile_pick: str = '') -> dict[str, Any]:
    """新版商品演示页：菜单清单可写，其余卡片仍只读展示"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.menu_helpers import find_menu_profile_by_pick_id, get_active_menu_profile
    from waimai.operating_helpers import get_operating_settings
    from waimai.product_image_helpers import (
        MAX_DISH_IMAGES_PER_PRODUCT,
        MAX_DISH_IMAGE_UPLOAD_BYTES,
        dish_image_quota_hint,
    )
    from waimai.product_shell_helpers import build_product_shell
    from waimai.sales_helpers import get_dish_sales_rankings

    _ensure_menu_tour_demo_dish(seller_id)
    operating = get_operating_settings(seller_id)
    product_shell = build_product_shell(seller_id)
    ctx = base_experience_preview_context('商品上架（演示）', 'products')
    ctx.update({
        'onboarding_readonly': False,
        'experience_writable': True,
        'experience_tour_query': _experience_tour_query(request),
        'operating': operating,
        'product_shell': product_shell,
        'shop_unread_msg_total': shop_unread_message_summary(seller_id)['total'],
    })
    dishes = list(
        Dish.objects.filter(seller_id=seller_id)
        .prefetch_related('product_images')
        .order_by('sort_order', 'name')
    )
    for dish in dishes:
        dish.image_quota = dish_image_quota_hint(dish)
    ctx['dishes'] = dishes
    ctx['dish_image_max'] = MAX_DISH_IMAGES_PER_PRODUCT
    ctx['dish_image_max_mb'] = MAX_DISH_IMAGE_UPLOAD_BYTES // (1024 * 1024)
    ctx['dish_image_remaining'] = MAX_DISH_IMAGES_PER_PRODUCT
    ctx['sales_rankings'] = get_dish_sales_rankings(seller_id)
    profiles: list[MenuProfile] = []
    active_profile = None
    selected = None
    tour_demo_item_id = None
    if product_shell['show_menu_catalog']:
        profiles = list(
            MenuProfile.objects.filter(seller_id=seller_id)
            .prefetch_related('items__dish')
            .order_by('-updated_at')
        )
        active_profile = get_active_menu_profile(seller_id)
        pick_id = profile_pick or request.GET.get('profile', '').strip()
        selected = find_menu_profile_by_pick_id(seller_id, pick_id) if pick_id else None
        if not selected:
            selected = active_profile or (profiles[0] if profiles else None)
        if selected:
            for item in selected.items.all():
                dish = item.dish
                if dish.member_price_enabled and dish.special_price_enabled:
                    tour_demo_item_id = item.item_id
                    break
            if not tour_demo_item_id:
                first = selected.items.first()
                tour_demo_item_id = first.item_id if first else None
    ctx['menu_profiles'] = profiles
    ctx['selected_profile'] = selected
    ctx['active_profile'] = active_profile
    ctx['tour_demo_menu_item_id'] = tour_demo_item_id
    ctx['edit_dish_id'] = (request.GET.get('edit') or '').strip()
    ctx['shop_order_preview_url'] = f'/shop/?seller_id={seller_id}'
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    ctx['shop_profile'] = shop_profile
    ctx['experience_print_qr_url'] = _experience_print_qr_url(request)
    ctx['tour_demo_dish_name'] = DEMO_DISH_NAME
    from .demo_cleanup import get_demo_dish_for_seller
    from .constants import URL_MAJOR, URL_TRACK
    from .tour_session import load_tour_query

    q = load_tour_query(request)
    try:
        major_idx = int(q.get(URL_MAJOR, '-1'))
    except (TypeError, ValueError):
        major_idx = -1
    track = (q.get(URL_TRACK) or '').strip()
    if track == 'seller' and major_idx >= 0:
        from .demo_major_seed import ensure_seller_major_prepared

        prep = ensure_seller_major_prepared(seller_id, track=track, major_index=major_idx)
        if major_idx == 5:
            # 第 6 大步：固定截图演示，不展开真编辑区
            ctx['experience_seller6_screenshots'] = True
            ctx['edit_dish_id'] = ''
        elif prep.get('edit_dish_id'):
            ctx['edit_dish_id'] = prep['edit_dish_id']
        elif major_idx == 4:
            # 第 5 大步独立进入：不沿用上一步的编辑区展开状态
            ctx['edit_dish_id'] = ''
            ctx['experience_seller5_step12_available'] = True

    demo_dish = get_demo_dish_for_seller(seller_id)
    ctx['tour_demo_dish_edit_pick'] = demo_dish.dish_id.hex[:8] if demo_dish else ''
    edit_pick = (ctx.get('edit_dish_id') or '').strip()
    if edit_pick:
        from waimai.product_scan_helpers import (
            build_product_scan_qr_rows,
            product_scan_qr_missing_lan,
        )

        for dish in dishes:
            if dish.dish_id.hex[:8] == edit_pick:
                ctx['edit_scan_qr_rows'] = build_product_scan_qr_rows(
                    request,
                    dish,
                    seller_id,
                )
                ctx['edit_scan_qr_missing_lan'] = product_scan_qr_missing_lan(
                    request,
                    dish,
                    seller_id,
                )
                break
    return ctx


def build_experience_print_qr_context(request) -> dict[str, Any]:
    """新版批量打印演示页（只读）"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.menu_helpers import get_active_menu_profile
    from waimai.operating_helpers import resolve_shop_access_base_url
    from waimai.product_qr_print_helpers import build_catalog_qr_print_cards

    missing_lan = not bool(resolve_shop_access_base_url(request, seller_id))
    ctx = base_experience_preview_context('批量打印商品二维码（演示）', 'products')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'print_cards': [] if missing_lan else build_catalog_qr_print_cards(request, seller_id),
        'print_qr_missing_lan': missing_lan,
        'active_profile': get_active_menu_profile(seller_id),
        'experience_products_url': reverse_experience_products(request),
    })
    return ctx


def reverse_experience_products(request) -> str:
    from django.urls import reverse
    from urllib.parse import urlencode

    base = reverse('experience_preview_products')
    q = load_tour_query(request)
    if not q:
        return base
    return f'{base}?{urlencode(q)}'


def build_experience_workbench_context(request) -> dict[str, Any]:
    """新版员工工作台管理演示页（只观摩 · 演示数据不写库）"""
    import base64

    from django.urls import reverse

    from waimai.forms import CreateStaffAccountForm, EditStaffAccountForm, ShopWorkbenchSettingsForm
    from waimai.operating_helpers import get_operating_settings
    from waimai.plugins.fulfillment.ownership import fulfillment_plugin_enabled
    from waimai.staff_account_helpers import (
        attendance_status_options,
        staff_account_type_label,
        staff_job_title,
        staff_permission_codes,
    )
    from waimai.workbench_qr import build_work_login_qr_png

    from .workbench_demo_helpers import (
        build_experience_workbench_attendance_context,
        build_experience_workbench_demo_logs,
        build_experience_workbench_demo_staff,
    )

    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    ctx = base_experience_preview_context('员工工作台管理（演示）', 'workbench')
    unread = shop_unread_message_summary(seller_id)
    operating = get_operating_settings(seller_id)
    operating.alert_volume = 80
    workbench_form = ShopWorkbenchSettingsForm(instance=operating)
    if not fulfillment_plugin_enabled(seller_id):
        for fname in ('delivery_handoff_mode', 'auto_dispatch_enabled'):
            workbench_form.fields.pop(fname, None)
    demo_staff = build_experience_workbench_demo_staff(seller_id)
    demo_logs = build_experience_workbench_demo_logs(seller_id)
    staff_account_rows = []
    for staff_user in demo_staff:
        staff_account_rows.append({
            'user': staff_user,
            'account_type_label': staff_account_type_label(staff_user),
            'job_title': staff_job_title(staff_user),
            'permission_codes': sorted(staff_permission_codes(staff_user)),
            'edit_form': EditStaffAccountForm(seller_id=seller_id, user=staff_user),
        })
    attendance_ctx = build_experience_workbench_attendance_context(
        request,
        seller_id,
        staff_users=demo_staff,
        demo_logs=demo_logs,
    )
    work_login_url = ''
    work_qr_data_url = ''
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    if shop_profile and (shop_profile.shop_code or '').strip():
        work_login_url = request.build_absolute_uri(reverse('experience_work_login'))
        png = build_work_login_qr_png(
            request.build_absolute_uri(
                reverse('shop_work', kwargs={'shop_code': shop_profile.shop_code.strip()}),
            ),
        )
        work_qr_data_url = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'shop_unread_msg_total': unread['total'],
        'workbench_settings_form': workbench_form,
        'management_staff_form': CreateStaffAccountForm(
            seller_id=seller_id,
            account_type='management',
        ),
        'employee_staff_form': CreateStaffAccountForm(
            seller_id=seller_id,
            account_type='employee',
        ),
        'staff_account_rows': staff_account_rows,
        'attendance_status_choices': attendance_status_options(),
        'attendance_full_url': '',
        'attendance_logs_query': '',
        'work_login_url': work_login_url,
        'work_qr_data_url': work_qr_data_url,
    })
    ctx.update(attendance_ctx)
    return ctx


def build_experience_dine_context(request) -> dict[str, Any]:
    """新版堂食营业演示页：接单细则观摩 + 桌台可写演示"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.forms import ShopOperatingSettingsForm
    from waimai.models import ShopTable, TableSession, VirtualTableCode
    from waimai.operating_helpers import get_operating_settings
    from waimai.plugin_runtime.registry import is_plugin_enabled
    from waimai.plugins.dining.table_bulk_helpers import sort_shop_tables, sort_virtual_codes
    from waimai.plugins.dining.table_helpers import (
        build_table_scan_path,
        build_virtual_scan_path,
        virtual_code_is_busy,
    )

    if not is_plugin_enabled('dining', seller_id):
        return {'_redirect': 'experience_home'}

    from .constants import URL_MAJOR, URL_MICRO, URL_TRACK
    from .dine_demo_helpers import ensure_dine_tour_prepared
    from .tour_session import load_tour_query

    q = load_tour_query(request)
    try:
        major_idx = int(q.get(URL_MAJOR, '-1'))
    except (TypeError, ValueError):
        major_idx = -1
    try:
        micro_idx = int(q.get(URL_MICRO, '0') or '0')
    except (TypeError, ValueError):
        micro_idx = 0
    track = (q.get(URL_TRACK) or '').strip()
    if track == 'seller' and major_idx == 7 and micro_idx == 0:
        ensure_dine_tour_prepared(seller_id)

    operating = get_operating_settings(seller_id)
    ctx = base_experience_preview_context('堂食营业（演示）', 'dine')
    ctx.update({
        'onboarding_readonly': False,
        'experience_writable': True,
        'experience_tour_query': _experience_tour_query(request),
        'operating': operating,
        'operating_form': ShopOperatingSettingsForm(instance=operating),
        'wait_time_rules': list(operating.wait_time_rules.all()),
        'shop_unread_msg_total': shop_unread_message_summary(seller_id)['total'],
    })
    tables = sort_shop_tables(list(ShopTable.objects.filter(seller_id=seller_id)))
    for t in tables:
        t.scan_path = build_table_scan_path(seller_id, t.qr_token)
    ctx['tables'] = tables
    if operating.share_table_enabled and operating.share_table_mode == 'virtual':
        vcodes = sort_virtual_codes(list(VirtualTableCode.objects.filter(seller_id=seller_id)))
        for v in vcodes:
            v.scan_path = build_virtual_scan_path(seller_id, v.qr_token)
            v.is_busy = virtual_code_is_busy(v)
        ctx['virtual_codes'] = vcodes
    if operating.share_table_enabled and operating.share_table_mode == 'waiter':
        ctx['share_sessions'] = TableSession.objects.filter(
            seller_id=seller_id, session_type='share_waiter', status='open',
        )[:20]
    return ctx


def build_experience_delivery_context(request) -> dict[str, Any]:
    """新版配送费规则演示页：只观摩，表单不真保存"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.delivery_helpers import get_delivery_settings
    from waimai.plugin_runtime.registry import is_plugin_enabled
    from waimai.plugins.fulfillment.forms import ShopDeliverySettingsForm

    if not is_plugin_enabled('fulfillment', seller_id):
        return {'_redirect': 'experience_home'}

    ctx = base_experience_preview_context('配送费规则（演示）', 'delivery')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'settings_form': ShopDeliverySettingsForm(instance=get_delivery_settings(seller_id)),
    })
    return ctx


def build_experience_payment_context(request) -> dict[str, Any]:
    """新版支付设置演示页：只观摩，表单不真保存"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.experience_helpers import experience_site_enabled, seller_blocked_from_real_wechat
    from waimai.forms import ShopPaymentSettingsForm
    from waimai.payments import get_payment_settings
    from waimai.plugin_runtime.registry import is_plugin_enabled
    from waimai.rider_cash_helpers import rider_cash_summary

    from waimai.payment_cert_helpers import build_wechat_cert_display, wechat_cert_status_label

    fulfillment_on = is_plugin_enabled('fulfillment', seller_id)
    payment_form = ShopPaymentSettingsForm(instance=get_payment_settings(seller_id))
    if not fulfillment_on and 'enable_cod' in payment_form.fields:
        del payment_form.fields['enable_cod']
    ctx = base_experience_preview_context('支付设置（演示）', 'payment')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'payment_form': payment_form,
        'experience_block_wechat': seller_blocked_from_real_wechat(seller_id),
        'experience_site': experience_site_enabled(),
        'wechat_cert_status': wechat_cert_status_label(get_payment_settings(seller_id)),
        'wechat_cert_display': build_wechat_cert_display(get_payment_settings(seller_id)),
        'show_rider_cash': fulfillment_on,
        'rider_cash': rider_cash_summary(seller_id) if fulfillment_on else None,
    })
    return ctx


def build_experience_orders_context(request) -> dict[str, Any]:
    """新版订单管理演示页：只观摩，表单不真保存"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.forms import ShopBossOrderNotifyForm
    from waimai.models import BuyOrder
    from waimai.operating_helpers import get_operating_settings
    from waimai.order_alert_helpers import list_shop_new_order_links
    from waimai.order_notify_ui_helpers import smtp_not_ready_message
    from waimai.order_search_helpers import (
        ORDER_DATE_RANGE_CHOICES,
        build_seller_orders_list_context,
    )
    from waimai.order_shell_helpers import (
        fulfillment_filter_choices,
        order_search_placeholder,
    )

    ctx = base_experience_preview_context('订单管理（演示）', 'orders')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
    })
    ctx.update(build_seller_orders_list_context(seller_id, request.GET))
    ctx['order_search_placeholder'] = order_search_placeholder(seller_id)
    ctx['order_date_range_choices'] = ORDER_DATE_RANGE_CHOICES
    ctx['order_status_choices'] = BuyOrder.ORDER_STATUS_CHOICES
    ctx['payment_status_choices'] = BuyOrder.PAYMENT_STATUS_CHOICES
    ctx['fulfillment_type_choices'] = fulfillment_filter_choices(seller_id)
    new_order_links = list_shop_new_order_links(seller_id)
    ctx['seller_new_order_links'] = new_order_links
    ctx['seller_new_order_ts'] = max((x['created_ts'] for x in new_order_links), default=0)
    ctx['shop_unread_msg_orders'] = shop_unread_message_summary(seller_id)['orders']
    operating = get_operating_settings(seller_id)
    ctx['boss_order_notify_form'] = ShopBossOrderNotifyForm(instance=operating)
    ctx['boss_order_notify_smtp_warn'] = smtp_not_ready_message(
        operating.boss_order_notify_enabled,
    )
    return ctx


def build_experience_order_detail_context(request, order_id) -> dict[str, Any] | None:
    """新版订单详情演示页：只观摩"""
    from django.urls import reverse

    from waimai.delivery_helpers import build_delivery_fee_breakdown
    from waimai.models import BuyOrder
    from waimai.order_helpers import build_order_timeline, dish_items_with_line_totals
    from waimai.order_shell_helpers import build_order_shell

    shop = get_official_shop_profile()
    if not shop:
        return None
    seller_id = shop.seller_id
    order = BuyOrder.objects.filter(seller_id=seller_id, order_id=order_id).select_related(
        'delivery_order', 'table_session',
    ).first()
    if not order:
        order = BuyOrder.objects.filter(seller_id=seller_id).select_related(
            'delivery_order', 'table_session',
        ).order_by('-created_at').first()
    if not order:
        return None
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    fee_detail = order.delivery_fee_detail
    if not fee_detail:
        _, fee_detail = build_delivery_fee_breakdown(
            order.seller_id, float(order.distance_km), order.get_subtotal(),
        )
    order_messages = list(order.messages.order_by('created_at'))
    ctx = {
        'order': order,
        'order_shell': build_order_shell(order),
        'shop_profile': shop_profile,
        'timeline': build_order_timeline(order),
        'dish_lines': dish_items_with_line_totals(order.dish_items),
        'subtotal': order.get_subtotal(),
        'delivery_fee': order.get_delivery_fee_amount(),
        'delivery_fee_detail': fee_detail,
        'viewer_role': 'seller',
        'order_messages': order_messages,
        'can_order_chat': False,
        'show_contact_guest': True,
        'can_buyer_cancel': False,
        'show_buyer_cancel_blocked': False,
        'can_shop_cancel': False,
        'shop_has_chat_history': bool(order_messages),
        'home_url': reverse('experience_preview_orders'),
    }
    ctx.update(base_experience_preview_context('订单详情（演示）', 'orders'))
    ctx['experience_tour_query'] = _experience_tour_query(request)
    return ctx


def build_experience_work_login_context(request) -> dict[str, Any]:
    """演示工作台登录页（只观摩，不真登录）"""
    from django.urls import reverse

    shop = get_official_shop_profile()
    return {
        'onboarding_preview': True,
        'onboarding_readonly': True,
        'experience_preview': True,
        'shop_profile': shop,
        'home_url': reverse('experience_home'),
        'experience_work_hub_url': reverse('experience_work_hub', kwargs={'view': 'orders'}),
    }


def _experience_work_tab_url(view: str) -> str:
    from django.urls import reverse

    return reverse('experience_work_hub', kwargs={'view': view})


def build_experience_work_hub_context(request, view: str) -> dict[str, Any]:
    """演示工作台：复用 shop_work_hub.html，官方店 + 真实面板数据"""
    from types import SimpleNamespace

    from django.urls import reverse

    from waimai.models import User
    from waimai.dispatch_helpers import operator_can_manual_dispatch
    from waimai.shop_work_helpers import (
        WORK_VIEWS,
        build_kitchen_board_context,
        build_rider_board_context,
        build_shop_work_daily_history,
        build_waiter_board_context,
        get_delivery_dispatch_role,
    )
    from waimai.staff_account_helpers import (
        is_shop_staff_account,
        staff_job_title,
    )
    from waimai.workbench_shell_helpers import build_workbench_shell
    from waimai.workbench_sort_helpers import resolve_workbench_sort

    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    work_user = User.objects.filter(username=seller_id, role='seller').first()
    if not work_user:
        return {}

    workbench_shell = build_workbench_shell(seller_id)
    enabled_views = [
        v for v in workbench_shell.get('enabled_views', []) if v in WORK_VIEWS
    ]
    current_view = (view or 'orders').strip()
    if current_view not in enabled_views:
        current_view = enabled_views[0] if enabled_views else 'orders'
    work_order_sort = resolve_workbench_sort(request)

    def _tab(view_name: str, sort_mode: str = work_order_sort) -> str:
        base = _experience_work_tab_url(view_name)
        return f'{base}?sort={sort_mode}'

    perms = {'orders': True, 'waiter': True, 'kitchen': True, 'rider': True}
    perms = {k: bool(v and k in enabled_views) for k, v in perms.items()}
    form_action = _tab(current_view)

    ctx = {
        'onboarding_preview': True,
        'onboarding_readonly': True,
        'experience_preview': True,
        'shop_profile': shop,
        'work_user': work_user,
        'current_view': current_view,
        'enabled_work_views': enabled_views,
        'form_action': form_action,
        'tab_orders_url': _tab('orders'),
        'tab_waiter_url': _tab('waiter'),
        'tab_kitchen_url': _tab('kitchen'),
        'tab_rider_url': _tab('rider'),
        'work_order_sort': work_order_sort,
        'sort_newest_url': _tab(current_view, 'newest'),
        'sort_oldest_url': _tab(current_view, 'oldest'),
        'can_operate_orders': perms.get('orders', False),
        'can_open_orders': True,
        'can_operate_waiter': perms['waiter'],
        'can_operate_kitchen': perms['kitchen'],
        'can_operate_rider': perms['rider'],
        'can_use_order_alert': True,
        'show_rider_extras': False,
        'is_work_staff': is_shop_staff_account(work_user),
        'work_user_title': (
            staff_job_title(work_user)
            if is_shop_staff_account(work_user)
            else work_user.get_role_display()
        ),
        'shop_work_code': (shop.shop_code or '').strip(),
        'shop_work_logout_url': reverse('experience_home'),
        'dispatch_role': get_delivery_dispatch_role(seller_id),
        'workbench_shell': workbench_shell,
        'home_url': reverse('experience_home'),
    }
    ctx.update(build_shop_work_daily_history(seller_id, work_user))

    if current_view == 'orders':
        from waimai.order_desk_helpers import build_order_desk_context

        ctx.update(build_order_desk_context(
            seller_id, work_user=work_user, sort_mode=work_order_sort,
        ))
    elif current_view == 'waiter':
        ctx.update(build_waiter_board_context(
            seller_id,
            allow_dispatch=operator_can_manual_dispatch(work_user, seller_id, 'waiter'),
            sort_mode=work_order_sort,
        ))
    elif current_view == 'kitchen':
        ctx.update(build_kitchen_board_context(
            seller_id,
            allow_dispatch=operator_can_manual_dispatch(work_user, seller_id, 'kitchen'),
            sort_mode=work_order_sort,
        ))
    elif current_view == 'rider':
        ctx.update(build_rider_board_context(
            work_user, seller_id, sort_mode=work_order_sort,
        ))
        ctx['onboarding_demo_rider_cash'] = SimpleNamespace(
            available_count=2,
            available_total='58.00',
            requests=[
                SimpleNamespace(
                    created_at=SimpleNamespace(strftime=lambda fmt: '07-27 18:30'),
                    order_count=2,
                    total_amount='58.00',
                    get_status_display=lambda: '待店主确认',
                    review_note='',
                ),
            ],
        )

    return ctx


def build_experience_homepage_context(request) -> dict[str, Any]:
    """新版展示主页演示页：只观摩，表单不真保存"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.home_block_media import block_display_image_src, photo_quota_hint
    from waimai.home_page_helpers import (
        BLOCK_CUSTOM,
        BLOCK_DIRECTORY,
        BLOCK_ORDER_CTA,
        MAX_SHOP_CUSTOM_BLOCKS,
        SERVER_ONLY_BLOCK_TYPES,
        SHOP_LEGACY_BLOCK_TYPES,
        block_dom_id,
        count_shop_custom_blocks,
        ensure_home_page_for_seller,
        get_shop_block_spec,
    )
    from waimai.models import User

    shop_profile = shop
    page = ensure_home_page_for_seller(seller_id, shop_profile)
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
        b.display_image_src = block_display_image_src(b)
        b.shows_rich_media = b.block_type not in (BLOCK_ORDER_CTA, BLOCK_DIRECTORY)
    custom_count = count_shop_custom_blocks(page)
    seller_user = User.objects.filter(username=seller_id, role='seller').first()
    ctx = base_experience_preview_context('展示主页（演示）', 'homepage')
    ctx.update(photo_quota_hint(seller_user) if seller_user else {})
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'home_page': page,
        'home_blocks': blocks,
        'custom_block_count': custom_count,
        'max_custom_blocks': MAX_SHOP_CUSTOM_BLOCKS,
        'can_add_custom_block': custom_count < MAX_SHOP_CUSTOM_BLOCKS,
        'save_block_action_name': 'save_home_block',
        'delete_block_action_name': 'delete_home_block',
    })
    if shop_profile and (shop_profile.shop_code or '').strip():
        ctx['showcase_preview_url'] = f"/s/{shop_profile.shop_code.strip()}/home/"
    return ctx


def build_experience_homepage_showcase_context(request) -> dict[str, Any]:
    """新版店铺主页预览演示（假 UI，结构与 showcase_home 一致）"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    ctx = base_experience_preview_context('店铺主页预览（演示）', 'homepage')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'demo_shop_name': shop.shop_name,
        'demo_shop_address': shop.address or '演示地址',
        'home_url': reverse_experience_homepage(request),
    })
    return ctx


def reverse_experience_homepage(request) -> str:
    from django.urls import reverse
    from urllib.parse import urlencode

    base = reverse('experience_preview_homepage')
    q = load_tour_query(request)
    if not q:
        return base
    return f'{base}?{urlencode(q)}'


def build_experience_table_stickers_context(request) -> dict[str, Any]:
    """桌贴预览页（体验引导 · 替代 PDF 下载）"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    from waimai.models import ShopProfile, ShopTable
    from waimai.plugin_runtime.registry import is_plugin_enabled
    from waimai.plugins.dining.table_sticker_print_helpers import build_table_sticker_print_cards

    if not is_plugin_enabled('dining', seller_id):
        return {'_redirect': 'experience_home'}

    raw_ids = (request.GET.get('tables') or '').strip()
    ids = [x.strip() for x in raw_ids.split(',') if x.strip()]
    tables = list(ShopTable.objects.filter(seller_id=seller_id, table_id__in=ids))
    profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    ctx = base_experience_preview_context('桌贴预览（演示）', 'dine')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'sticker_cards': build_table_sticker_print_cards(
            request, seller_id, tables, shop_profile=profile,
        ),
        'experience_dine_url': reverse_experience_dine(request),
    })
    return ctx


def reverse_experience_dine(request) -> str:
    from django.urls import reverse
    from urllib.parse import urlencode

    base = reverse('experience_preview_dine')
    q = load_tour_query(request)
    if not q:
        return base
    return f'{base}?{urlencode(q)}'


def experience_menu_panel_json(request, seller_id: str):
    """体验引导：GET 切换清单时只刷新菜单区 JSON（不整页跳转）"""
    from django.http import JsonResponse
    from django.template.loader import render_to_string

    shop = get_official_shop_profile()
    if not shop or shop.seller_id != seller_id:
        return JsonResponse({'ok': False, 'error': 'no_shop'}, status=400)
    touch_experience_tour_session(request)
    ctx = build_experience_products_context(request)
    if not ctx:
        return JsonResponse({'ok': False, 'error': 'no_ctx'}, status=400)
    html = render_to_string('waimai/seller/_menu_catalog_panel.html', ctx, request=request)
    return JsonResponse({
        'ok': True,
        'menuPanelHtml': html,
        'tourQuery': ctx.get('experience_tour_query') or {},
    })
