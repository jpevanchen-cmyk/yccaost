# 新版新手体验：添加/编辑商品可写演示（第 5、6 大步 POST）

from __future__ import annotations

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from waimai.models import Dish
from waimai.product_helpers import parse_decimal_field
from waimai.product_seller_handlers import (
    _apply_new_dish_special_defaults,
    _dish_row_anchor,
    _edit_anchor,
    _edit_query,
    _fill_dish_descriptions,
    _fill_dish_prices,
)
from waimai.menu_helpers import sync_new_dish_to_menu_profiles

from .demo_cleanup import DEMO_DISH_NAME, register_demo_dish
from .demo_product_image import attach_demo_preset_image
from .demo_write import _collect_message_list
from .tour_session import touch_experience_tour_session, tour_query_for_redirect


def is_experience_product_post(request) -> bool:
    """是否为商品添加/编辑/演示传图 POST（须与菜单 POST 分流）"""
    return any(k in request.POST for k in (
        'add_dish',
        'edit_dish',
        'experience_demo_image_upload',
    ))


def _is_product_ajax(request) -> bool:
    return (
        request.headers.get('X-Experience-Product-Ajax') == '1'
        or request.POST.get('experience_product_ajax') == '1'
    )


def _experience_products_redirect(request, anchor=None, query=None):
    from django.urls import reverse

    from waimai.scroll_helpers import redirect_with_anchor

    touch_experience_tour_session(request)
    base = reverse('experience_preview_products')
    parts = list(tour_query_for_redirect(request))
    if query:
        parts.insert(0, query)
    qs = '&'.join(parts)
    url = f'{base}?{qs}' if qs else base
    return redirect_with_anchor(url, anchor)


def _attach_edit_scan_qr(ctx, request, seller_id: str) -> None:
    """编辑区打开时补上分档二维码数据"""
    edit_pick = (ctx.get('edit_dish_id') or '').strip()
    if not edit_pick:
        return
    from waimai.product_scan_helpers import build_product_scan_qr_rows

    for dish in ctx.get('dishes') or []:
        if dish.dish_id.hex[:8] == edit_pick:
            ctx['edit_scan_qr_rows'] = build_product_scan_qr_rows(
                request,
                dish,
                seller_id,
            )
            break


def _ajax_product_list_response(
    request,
    seller_id: str,
    *,
    ok: bool = True,
    edit_query: str = '',
):
    from .preview_helpers import build_experience_products_context

    touch_experience_tour_session(request)
    ctx = build_experience_products_context(request)
    if edit_query:
        ctx['edit_dish_id'] = edit_query.replace('edit=', '')
    _attach_edit_scan_qr(ctx, request, seller_id)
    html = render_to_string(
        'waimai/seller/_experience_product_list_body.html',
        ctx,
        request=request,
    )
    return JsonResponse({
        'ok': ok,
        'productListHtml': html,
        'messages': _collect_message_list(request),
        'tourQuery': ctx.get('experience_tour_query') or {},
        'editDishPick': ctx.get('tour_demo_dish_edit_pick') or ctx.get('edit_dish_id') or '',
    })


def _finish_product_post(
    request,
    seller_id: str,
    *,
    anchor=None,
    query=None,
    ok: bool = True,
):
    if _is_product_ajax(request):
        edit_q = query or ''
        return _ajax_product_list_response(request, seller_id, ok=ok, edit_query=edit_q)
    return _experience_products_redirect(request, anchor, query)


def _is_registered_demo_dish(dish: Dish) -> bool:
    from .demo_cleanup import is_demo_dish

    return is_demo_dish(dish)


def handle_experience_demo_image_upload(request, seller_id: str):
    """编辑区：演示再传一张预设图（第 6 大步）"""
    dish = get_object_or_404(Dish, dish_id=request.POST.get('dish_id'), seller_id=seller_id)
    if not _is_registered_demo_dish(dish):
        messages.error(request, '本步仅可为演示商品上传演示图片')
        return _finish_product_post(
            request,
            seller_id,
            anchor=_edit_anchor(dish),
            query=_edit_query(dish),
            ok=False,
        )
    _payload, err = attach_demo_preset_image(dish)
    if err:
        messages.error(request, err)
        return _finish_product_post(
            request,
            seller_id,
            anchor=_edit_anchor(dish),
            query=_edit_query(dish),
            ok=False,
        )
    messages.success(request, '演示图片已上传')
    return _finish_product_post(
        request,
        seller_id,
        anchor=_edit_anchor(dish),
        query=_edit_query(dish),
        ok=True,
    )


def handle_experience_product_post(request, seller_id: str):
    """仅处理商品添加/编辑/演示传图 POST（新版体验第 5、6 大步）"""
    if request.POST.get('experience_demo_image_upload') == '1':
        return handle_experience_demo_image_upload(request, seller_id)

    allowed = {'add_dish', 'edit_dish'}
    if not any(k in request.POST for k in allowed):
        messages.error(request, '本步演示仅开放商品添加与编辑相关操作')
        return _finish_product_post(request, seller_id, ok=False)

    if 'add_dish' in request.POST:
        name = (request.POST.get('name') or '').strip()
        price = parse_decimal_field(request.POST.get('price'))
        if not name or not price or price <= 0:
            messages.error(request, '请填写有效的商品名称和通用价格')
            return _finish_product_post(request, seller_id, anchor='product-add', ok=False)
        if Dish.objects.filter(seller_id=seller_id, name=name).exists():
            messages.error(request, f'已有同名商品「{name}」，请换一个名称')
            return _finish_product_post(request, seller_id, anchor='product-add', ok=False)
        dish = Dish(
            seller_id=seller_id,
            name=name,
            price=price,
            sort_order=int(request.POST.get('sort_order') or 0)
            if str(request.POST.get('sort_order', '0')).lstrip('-').isdigit() else 0,
            is_active=True,
        )
        _fill_dish_descriptions(dish, request.POST)
        _fill_dish_prices(dish, request.POST, 'member')
        _fill_dish_prices(dish, request.POST, 'special')
        _apply_new_dish_special_defaults(dish)
        dish.save()
        list_on_all_menus = bool(request.POST.get('list_on_all_menus'))
        sync_new_dish_to_menu_profiles(dish, list_on_all_menus=list_on_all_menus)
        if request.POST.get('experience_demo_image') == '1' or name == DEMO_DISH_NAME:
            _payload, img_err = attach_demo_preset_image(dish)
            if img_err:
                messages.warning(request, img_err)
        if name == DEMO_DISH_NAME:
            register_demo_dish(dish.dish_id)
        if list_on_all_menus:
            messages.success(request, f'已添加商品「{dish.name}」，已在本店全部清单中上架')
        else:
            messages.success(request, f'已添加商品「{dish.name}」')
        return _finish_product_post(
            request,
            seller_id,
            anchor='product-list',
            query=_edit_query(dish),
            ok=True,
        )

    if 'edit_dish' in request.POST:
        dish = get_object_or_404(Dish, dish_id=request.POST.get('dish_id'), seller_id=seller_id)
        if not _is_registered_demo_dish(dish):
            messages.error(request, '本步仅可编辑本次体验创建的演示商品')
            return _finish_product_post(
                request,
                seller_id,
                anchor=_edit_anchor(dish),
                query=_edit_query(dish),
                ok=False,
            )
        name = (request.POST.get('name') or '').strip()
        price = parse_decimal_field(request.POST.get('price'))
        if not name or not price or price <= 0:
            messages.error(request, '名称和通用价格无效')
            return _finish_product_post(
                request,
                seller_id,
                anchor=_edit_anchor(dish),
                query=_edit_query(dish),
                ok=False,
            )
        dish.name = name
        dish.price = price
        _fill_dish_descriptions(dish, request.POST)
        sort_val = (request.POST.get('sort_order') or '0').strip()
        dish.sort_order = int(sort_val) if sort_val.lstrip('-').isdigit() else 0
        _fill_dish_prices(dish, request.POST, 'member')
        _fill_dish_prices(dish, request.POST, 'special')
        dish.save()
        messages.success(request, f'已保存「{dish.name}」')
        return _finish_product_post(
            request,
            seller_id,
            anchor=_dish_row_anchor(dish),
            query=_edit_query(dish),
            ok=True,
        )

    return _finish_product_post(request, seller_id)
