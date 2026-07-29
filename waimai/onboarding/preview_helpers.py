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
        from waimai.product_scan_helpers import build_product_scan_qr_rows

        for dish in dishes:
            if dish.dish_id.hex[:8] == edit_pick:
                ctx['edit_scan_qr_rows'] = build_product_scan_qr_rows(
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
    from waimai.product_qr_print_helpers import build_catalog_qr_print_cards

    ctx = base_experience_preview_context('批量打印商品二维码（演示）', 'products')
    ctx.update({
        'onboarding_readonly': True,
        'experience_writable': False,
        'experience_tour_query': _experience_tour_query(request),
        'print_cards': build_catalog_qr_print_cards(request, seller_id),
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
        work_login_url = request.build_absolute_uri(reverse('onboarding_work_login'))
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
