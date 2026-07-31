# H4 新手体验：演示页上下文（必须复用真实卖家/工作台模板）

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

from django.urls import reverse

from .models import Dish, MenuProfile, ShopProfile, User
from .onboarding_helpers import get_official_shop_profile
from .onboarding_preview_context import base_preview_context, build_seller_preview_nav
from .order_message_helpers import shop_unread_message_summary
from .plugin_runtime.registry import collect_seller_nav_items, is_plugin_enabled


def _official_seller_id() -> str:
    shop = get_official_shop_profile()
    if not shop:
        return ''
    return shop.seller_id


def _seller_shell_context(request, section: str) -> dict[str, Any]:
    """卖家后台公共壳：Tab 导航指向演示路由"""
    seller_id = _official_seller_id()
    shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()
    unread = shop_unread_message_summary(seller_id)
    ctx = base_preview_context('', section)
    ctx.update({
        'section': section,
        'seller_id': seller_id,
        'shop_profile': shop_profile,
        'shop_unread_msg_total': unread['total'],
        'seller_nav_items': build_seller_preview_nav(seller_id, section),
        'onboarding_readonly': True,
    })
    return ctx


def build_onboarding_seller_section_context(request, section: str) -> dict[str, Any]:
    """按真实 seller_panel 逻辑组装上下文，供 waimai/seller/{section}.html 使用"""
    seller_id = _official_seller_id()
    if not seller_id:
        return {}
    ctx = _seller_shell_context(request, section)

    if section == 'operating':
        from .forms import ShopStatusSettingsForm
        from .operating_helpers import get_operating_settings

        operating = get_operating_settings(seller_id)
        ctx['operating'] = operating
        ctx['status_form'] = ShopStatusSettingsForm(instance=operating)
        ctx['is_shop_open'] = (
            (not operating.closed_for_today) and (not operating.pause_new_orders)
        )
    elif section == 'products':
        from .menu_helpers import find_menu_profile_by_pick_id, get_active_menu_profile
        from .operating_helpers import get_operating_settings
        from .product_image_helpers import (
            MAX_DISH_IMAGES_PER_PRODUCT,
            MAX_DISH_IMAGE_UPLOAD_BYTES,
            dish_image_quota_hint,
        )
        from .product_shell_helpers import build_product_shell
        from .sales_helpers import get_dish_sales_rankings

        operating = get_operating_settings(seller_id)
        product_shell = build_product_shell(seller_id)
        ctx['operating'] = operating
        ctx['product_shell'] = product_shell
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
        profiles = []
        active_profile = None
        selected = None
        if product_shell['show_menu_catalog']:
            profiles = list(
                MenuProfile.objects.filter(seller_id=seller_id)
                .prefetch_related('items__dish')
                .order_by('-updated_at')
            )
            active_profile = get_active_menu_profile(seller_id)
            pick_id = request.GET.get('profile', '').strip()
            selected = find_menu_profile_by_pick_id(seller_id, pick_id) if pick_id else None
            if not selected:
                selected = active_profile or (profiles[0] if profiles else None)
        ctx['menu_profiles'] = profiles
        ctx['selected_profile'] = selected
        ctx['active_profile'] = active_profile
        edit_pick = request.GET.get('edit', '').strip()
        ctx['edit_dish_id'] = edit_pick
        if not edit_pick and dishes:
            ctx['edit_dish_id'] = dishes[0].dish_id.hex[:8]
            edit_pick = ctx['edit_dish_id']
        if edit_pick:
            from .product_scan_helpers import build_product_scan_qr_rows

            for dish in dishes:
                if dish.dish_id.hex[:8] == edit_pick:
                    ctx['edit_scan_qr_rows'] = build_product_scan_qr_rows(
                        request, dish, seller_id,
                    )
                    break
        ctx['shop_order_preview_url'] = f'/shop/?seller_id={seller_id}'
    elif section == 'workbench':
        from .forms import (
            CreateStaffAccountForm,
            EditStaffAccountForm,
            ShopWorkbenchSettingsForm,
        )
        from .operating_helpers import get_operating_settings
        from .staff_account_helpers import (
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
        ctx['workbench_settings_form'] = workbench_form
        ctx['management_staff_form'] = CreateStaffAccountForm(
            seller_id=seller_id,
            account_type='management',
        )
        ctx['employee_staff_form'] = CreateStaffAccountForm(
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
        ctx['staff_account_rows'] = staff_account_rows
        attendance_ctx = build_workbench_attendance_context(
            request,
            seller_id,
            operating.attendance_retention_days,
            staff_users,
            default_today=True,
        )
        ctx.update(attendance_ctx)
        ctx['attendance_status_choices'] = attendance_status_options()
        ctx['attendance_full_url'] = ''
        ctx['attendance_logs_query'] = ''
        work_login_url = ''
        work_qr_data_url = ''
        shop_profile = ctx['shop_profile']
        if shop_profile and (shop_profile.shop_code or '').strip():
            work_login_url = request.build_absolute_uri(
                reverse('onboarding_work_login'),
            )
            png = build_work_login_qr_png(
                request.build_absolute_uri(
                    reverse('shop_work', kwargs={'shop_code': shop_profile.shop_code.strip()}),
                ),
            )
            work_qr_data_url = 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')
        ctx['work_login_url'] = work_login_url
        ctx['work_qr_data_url'] = work_qr_data_url
    elif section == 'orders':
        from .forms import ShopBossOrderNotifyForm
        from .models import BuyOrder
        from .operating_helpers import get_operating_settings
        from .order_alert_helpers import list_shop_new_order_links
        from .order_notify_ui_helpers import smtp_not_ready_message
        from .order_search_helpers import (
            ORDER_DATE_RANGE_CHOICES,
            build_seller_orders_list_context,
        )
        from .order_shell_helpers import (
            fulfillment_filter_choices,
            order_search_placeholder,
        )

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
    elif section == 'payment':
        from .experience_helpers import experience_site_enabled, seller_blocked_from_real_wechat
        from .forms import ShopPaymentSettingsForm
        from .payments import get_payment_settings
        from .rider_cash_helpers import rider_cash_summary

        fulfillment_on = is_plugin_enabled('fulfillment', seller_id)
        payment_form = ShopPaymentSettingsForm(instance=get_payment_settings(seller_id))
        if not fulfillment_on and 'enable_cod' in payment_form.fields:
            del payment_form.fields['enable_cod']
        ctx['payment_form'] = payment_form
        ctx['experience_block_wechat'] = seller_blocked_from_real_wechat(seller_id)
        ctx['experience_site'] = experience_site_enabled()
        ctx['show_rider_cash'] = fulfillment_on
        ctx['rider_cash'] = rider_cash_summary(seller_id) if fulfillment_on else None
    elif section == 'homepage':
        from .home_block_media import block_display_image_src, photo_quota_hint
        from .home_page_helpers import (
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

        shop_profile = ctx['shop_profile']
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
        ctx.update(photo_quota_hint(seller_user) if seller_user else {})
        ctx['home_page'] = page
        ctx['home_blocks'] = blocks
        ctx['custom_block_count'] = custom_count
        ctx['max_custom_blocks'] = MAX_SHOP_CUSTOM_BLOCKS
        ctx['can_add_custom_block'] = custom_count < MAX_SHOP_CUSTOM_BLOCKS
        ctx['save_block_action_name'] = 'save_home_block'
        ctx['delete_block_action_name'] = 'delete_home_block'
    elif section == 'dine':
        from .forms import ShopOperatingSettingsForm
        from .models import ShopTable, TableSession, VirtualTableCode
        from .operating_helpers import get_operating_settings
        from waimai.plugins.dining.table_bulk_helpers import sort_shop_tables, sort_virtual_codes
        from waimai.plugins.dining.table_helpers import (
            build_table_scan_path,
            build_virtual_scan_path,
            virtual_code_is_busy,
        )

        operating = get_operating_settings(seller_id)
        ctx['operating'] = operating
        ctx['operating_form'] = ShopOperatingSettingsForm(instance=operating)
        ctx['wait_time_rules'] = list(operating.wait_time_rules.all())
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
    elif section == 'delivery':
        from .delivery_helpers import get_delivery_settings
        from .forms import ShopDeliverySettingsForm
        from .plugins.fulfillment.ownership import fulfillment_plugin_enabled

        if not fulfillment_plugin_enabled(seller_id):
            ctx['_redirect'] = reverse('onboarding_seller_payment')
        else:
            ctx['settings_form'] = ShopDeliverySettingsForm(
                instance=get_delivery_settings(seller_id),
            )
    return ctx


def build_onboarding_print_qr_context(request) -> dict[str, Any]:
    seller_id = _official_seller_id()
    ctx = _seller_shell_context(request, 'products')
    from .menu_helpers import get_active_menu_profile
    from .product_qr_print_helpers import build_catalog_qr_print_cards

    ctx.update({
        'print_cards': build_catalog_qr_print_cards(request, seller_id),
        'active_profile': get_active_menu_profile(seller_id),
    })
    return ctx


def build_onboarding_work_login_context(request) -> dict[str, Any]:
    shop = get_official_shop_profile()
    return {
        'onboarding_preview': True,
        'onboarding_readonly': True,
        'shop_profile': shop,
        'home_url': reverse('home'),
        'onboarding_work_hub_url': reverse('onboarding_work_hub', kwargs={'view': 'orders'}),
    }


def _preview_work_tab_url(view: str) -> str:
    return reverse('onboarding_work_hub', kwargs={'view': view})


def build_onboarding_work_hub_context(request, view: str) -> dict[str, Any]:
    """演示工作台：复用 shop_work_hub.html，用官方店 seller 账号 + 真实面板数据"""
    shop = get_official_shop_profile()
    if not shop:
        return {}
    seller_id = shop.seller_id
    work_user = User.objects.filter(username=seller_id, role='seller').first()
    if not work_user:
        return {}

    from .dispatch_helpers import operator_can_manual_dispatch
    from .shop_work_helpers import (
        WORK_VIEWS,
        build_kitchen_board_context,
        build_rider_board_context,
        build_shop_work_daily_history,
        build_waiter_board_context,
        get_delivery_dispatch_role,
    )
    from .staff_account_helpers import (
        PERM_DINING_RIDER,
        is_shop_staff_account,
        staff_has_any_order_desk_permission,
        staff_has_permission,
        staff_job_title,
    )
    from .workbench_shell_helpers import build_workbench_shell
    from .workbench_sort_helpers import resolve_workbench_sort

    workbench_shell = build_workbench_shell(seller_id)
    enabled_views = [
        v for v in workbench_shell.get('enabled_views', []) if v in WORK_VIEWS
    ]
    current_view = (view or 'orders').strip()
    if current_view not in enabled_views:
        current_view = enabled_views[0] if enabled_views else 'orders'
    work_order_sort = resolve_workbench_sort(request)

    def _tab(view_name: str, sort_mode: str = work_order_sort) -> str:
        base = _preview_work_tab_url(view_name)
        return f'{base}?sort={sort_mode}'

    perms = {'orders': True, 'waiter': True, 'kitchen': True, 'rider': True}
    perms = {k: bool(v and k in enabled_views) for k, v in perms.items()}
    form_action = _tab(current_view)

    ctx = {
        'onboarding_preview': True,
        'onboarding_readonly': True,
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
        'shop_work_logout_url': reverse('home'),
        'dispatch_role': get_delivery_dispatch_role(seller_id),
        'workbench_shell': workbench_shell,
        'home_url': reverse('home'),
    }
    ctx.update(build_shop_work_daily_history(seller_id, work_user))

    if current_view == 'orders':
        from .order_desk_helpers import build_order_desk_context

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
        # 演示骑手现金交款（seller 预览时真数据常为空，注入与真模板同结构的演示块）
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


def build_onboarding_order_detail_context(request, order_id) -> dict[str, Any] | None:
    from .delivery_helpers import build_delivery_fee_breakdown
    from .models import BuyOrder, ShopProfile
    from .order_helpers import build_order_timeline, dish_items_with_line_totals
    from .order_shell_helpers import build_order_shell

    seller_id = _official_seller_id()
    if not seller_id:
        return None
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
    return {
        'onboarding_preview': True,
        'onboarding_readonly': True,
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
        'home_url': reverse('onboarding_seller_orders'),
    }


def seller_template_for_section(section: str) -> str:
    return f'waimai/seller/{section}.html'
