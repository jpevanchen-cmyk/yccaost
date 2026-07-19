# 卖家「商品上架管理」：上新、编辑、菜单清单

from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404

from django.urls import reverse

from .menu_helpers import (
    copy_profile_items,
    find_menu_profile_by_pick_id,
    menu_profile_name_taken,
    populate_profile_with_dishes,
    sync_new_dish_to_menu_profiles,
)
from .models import Dish, MenuProfile, MenuProfileItem
from .operating_helpers import get_operating_settings, has_open_orders
from .product_helpers import parse_decimal_field, parse_optional_int
from .scroll_helpers import redirect_with_anchor


_DINING_MENU_ACTIONS = {
    'create_menu_profile',
    'toggle_menu_item_listed',
    'toggle_menu_item_member',
    'toggle_menu_item_special',
    'save_menu_item_cap',
    'add_dish_to_profile',
    'activate_menu_profile',
    'delete_menu_profile',
    'copy_menu_profile',
    'rename_menu_profile',
}


def _products_redirect(anchor=None, query=None):
    url = reverse('seller_panel_section', kwargs={'section': 'products'})
    if query:
        url = f'{url}?{query}'
    return redirect_with_anchor(url, anchor)


def _dish_row_anchor(dish):
    """商品行在页面上的锚点（保存后滚回该行）"""
    return f'dish-{dish.dish_id.hex[:8]}'


def _edit_anchor(dish):
    """编辑表单锚点（校验失败时仍停在编辑区）"""
    return f'edit-{dish.dish_id.hex[:8]}'


def _menus_query(profile_id=None):
    if profile_id:
        return f'profile={profile_id}'
    return ''


def _edit_query(dish):
    return f'edit={dish.dish_id.hex[:8]}'


def _is_active_menu_profile(settings, profile_id) -> bool:
    """判断是否为当前使用中的菜单清单"""
    if not settings.active_menu_profile_id or not profile_id:
        return False
    return str(settings.active_menu_profile_id) == str(profile_id)


def _read_price_mode(post, prefix):
    """读取会员价/特价按百分比还是固定金额"""
    mode = post.get(f'{prefix}_price_mode', 'percent')
    return mode if mode in ('percent', 'fixed') else 'percent'


def _get_menu_item(seller_id, profile_id, item_id):
    """取菜单清单条目（含商品信息）"""
    return get_object_or_404(
        MenuProfileItem.objects.select_related('dish'),
        item_id=item_id,
        profile_id=profile_id,
        profile__seller_id=seller_id,
    )


def _fill_dish_prices(dish, post, prefix):
    if prefix == 'member':
        dish.member_price_enabled = bool(post.get('member_price_enabled'))
        dish.member_price_mode = _read_price_mode(post, 'member')
        dish.member_price_fixed = parse_decimal_field(post.get('member_price_fixed'))
        dish.member_price_percent = parse_decimal_field(post.get('member_price_percent'), Decimal('100'))
        dish.member_daily_limit = parse_optional_int(post.get('member_daily_limit'))
        dish.member_total_limit = parse_optional_int(post.get('member_total_limit'))
    elif prefix == 'special':
        dish.special_price_enabled = bool(post.get('special_price_enabled'))
        dish.special_price_mode = _read_price_mode(post, 'special')
        dish.special_price_fixed = parse_decimal_field(post.get('special_price_fixed'))
        dish.special_price_percent = parse_decimal_field(post.get('special_price_percent'), Decimal('100'))
        dish.special_per_dish_limit = parse_optional_int(post.get('special_per_dish_limit'))


def _apply_new_dish_special_defaults(dish):
    """新商品启用特价时：每人限购默认 1，防止忘填导致不限购"""
    if dish.special_price_enabled and dish.special_per_dish_limit is None:
        dish.special_per_dish_limit = 1


def handle_products_post(request, seller_id):
    """商品上架管理分区 POST"""
    from .plugin_runtime.registry import is_plugin_enabled

    if not is_plugin_enabled('dining', seller_id) and any(
        action in request.POST for action in _DINING_MENU_ACTIONS
    ):
        messages.error(request, '菜单清单由饮食插件提供；当前插件已停用')
        return _products_redirect('product-list')

    if 'save_special_pool' in request.POST:
        settings = get_operating_settings(seller_id)
        settings.special_pool_code = (request.POST.get('special_pool_code') or '').strip()
        settings.special_max_per_user = parse_optional_int(request.POST.get('special_max_per_user'))
        settings.save(update_fields=['special_pool_code', 'special_max_per_user'])
        messages.success(request, '特价活动规则已保存')
        return _products_redirect('special-pool')

    if 'add_dish' in request.POST:
        name = (request.POST.get('name') or '').strip()
        price = parse_decimal_field(request.POST.get('price'))
        if not name or not price or price <= 0:
            messages.error(request, '请填写有效的商品名称和通用价格')
            return _products_redirect('product-add')
        list_on_all_menus = bool(request.POST.get('list_on_all_menus'))
        has_menu_profiles = MenuProfile.objects.filter(seller_id=seller_id).exists()
        if list_on_all_menus and not has_menu_profiles:
            messages.error(request, '本店还没有菜单清单，不能勾选「添加后在本店所有菜单清单中设为已上架」')
            return _products_redirect('product-add')
        dish = Dish(
            seller_id=seller_id,
            name=name,
            price=price,
            description=(request.POST.get('description') or '').strip(),
            sort_order=int(request.POST.get('sort_order') or 0)
            if str(request.POST.get('sort_order', '0')).lstrip('-').isdigit() else 0,
            is_active=True,
        )
        _fill_dish_prices(dish, request.POST, 'member')
        _fill_dish_prices(dish, request.POST, 'special')
        _apply_new_dish_special_defaults(dish)
        dish.save()
        sync_new_dish_to_menu_profiles(dish, list_on_all_menus=list_on_all_menus)
        if list_on_all_menus:
            messages.success(request, f'已添加商品「{dish.name}」，已在本店全部菜单清单中上架')
        else:
            messages.success(request, f'已添加商品「{dish.name}」')
        return _products_redirect('product-list')

    if 'edit_dish' in request.POST:
        dish = get_object_or_404(Dish, dish_id=request.POST.get('dish_id'), seller_id=seller_id)
        name = (request.POST.get('name') or '').strip()
        price = parse_decimal_field(request.POST.get('price'))
        if not name or not price or price <= 0:
            messages.error(request, '名称和通用价格无效')
            return _products_redirect(_edit_anchor(dish), _edit_query(dish))
        dish.name = name
        dish.price = price
        dish.description = (request.POST.get('description') or '').strip()
        sort_val = (request.POST.get('sort_order') or '0').strip()
        dish.sort_order = int(sort_val) if sort_val.lstrip('-').isdigit() else 0
        _fill_dish_prices(dish, request.POST, 'member')
        _fill_dish_prices(dish, request.POST, 'special')
        dish.save()
        messages.success(request, f'已保存「{dish.name}」')
        return _products_redirect(_dish_row_anchor(dish))

    if 'delete_dish' in request.POST:
        dish = get_object_or_404(Dish, dish_id=request.POST.get('dish_id'), seller_id=seller_id)
        name = dish.name
        dish.delete()
        messages.success(request, f'已删除商品「{name}」')
        return _products_redirect('product-list')

    if 'create_menu_profile' in request.POST:
        name = (request.POST.get('profile_name') or '').strip()
        copy_from_raw = (request.POST.get('copy_from_profile_id') or '').strip()
        profile_q = ''
        if not name:
            messages.error(request, '请填写清单名称')
        elif menu_profile_name_taken(seller_id, name):
            messages.error(request, f'已有同名菜单清单「{name}」，请换一个名称')
        else:
            profile = MenuProfile.objects.create(seller_id=seller_id, name=name)
            source = find_menu_profile_by_pick_id(seller_id, copy_from_raw) if copy_from_raw else None
            if copy_from_raw and not source:
                profile.delete()
                messages.error(request, '要复制的清单不存在，请重新选择')
            elif source:
                copy_profile_items(source, profile)
                messages.success(request, f'已创建「{name}」，并复制自「{source.name}」')
                profile_q = str(profile.profile_id)
            else:
                populate_profile_with_dishes(profile, seller_id)
                messages.success(request, f'已创建菜单清单「{name}」，已纳入本店全部商品')
                profile_q = str(profile.profile_id)
        return _products_redirect('menu-panel', _menus_query(profile_q) if profile_q else None)

    if 'toggle_menu_item_listed' in request.POST:
        profile_id = request.POST.get('profile_id')
        item = _get_menu_item(seller_id, profile_id, request.POST.get('item_id'))
        item.is_listed = not item.is_listed
        item.save(update_fields=['is_listed'])
        state = '上架' if item.is_listed else '下架'
        messages.success(request, f'「{item.dish.name}」在本清单已{state}')
        return _products_redirect('menu-panel', _menus_query(profile_id))

    if 'toggle_menu_item_member' in request.POST:
        profile_id = request.POST.get('profile_id')
        item = _get_menu_item(seller_id, profile_id, request.POST.get('item_id'))
        if not item.dish.member_price_enabled:
            messages.error(request, f'「{item.dish.name}」尚未在商品管理中配置会员价')
        else:
            item.member_price_listed = not item.member_price_listed
            item.save(update_fields=['member_price_listed'])
            state = '展示' if item.member_price_listed else '不展示'
            settings = get_operating_settings(seller_id)
            if _is_active_menu_profile(settings, profile_id):
                messages.success(request, f'「{item.dish.name}」会员价已{state}，店铺页已同步')
            else:
                messages.success(
                    request,
                    f'「{item.dish.name}」会员价已{state}；须将本清单「切换使用」后客人才看得到',
                )
        return _products_redirect('menu-panel', _menus_query(profile_id))

    if 'toggle_menu_item_special' in request.POST:
        profile_id = request.POST.get('profile_id')
        item = _get_menu_item(seller_id, profile_id, request.POST.get('item_id'))
        if not item.dish.special_price_enabled:
            messages.error(request, f'「{item.dish.name}」尚未在商品管理中配置特价')
        else:
            item.special_price_listed = not item.special_price_listed
            item.save(update_fields=['special_price_listed'])
            state = '展示' if item.special_price_listed else '不展示'
            settings = get_operating_settings(seller_id)
            if _is_active_menu_profile(settings, profile_id):
                messages.success(request, f'「{item.dish.name}」特价已{state}，店铺页已同步')
            else:
                messages.success(
                    request,
                    f'「{item.dish.name}」特价已{state}；须将本清单「切换使用」后客人才看得到',
                )
        return _products_redirect('menu-panel', _menus_query(profile_id))

    if 'save_menu_item_cap' in request.POST:
        profile_id = request.POST.get('profile_id')
        item = _get_menu_item(seller_id, profile_id, request.POST.get('item_id'))
        cap = request.POST.get('sales_cap', '').strip()
        item.sales_cap = int(cap) if cap.isdigit() else None
        item.save(update_fields=['sales_cap'])
        messages.success(request, f'已更新「{item.dish.name}」可售上限')
        return _products_redirect('menu-panel', _menus_query(profile_id))

    if 'add_dish_to_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        dish_id = request.POST.get('dish_id')
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        dish = get_object_or_404(Dish, dish_id=dish_id, seller_id=seller_id)
        cap = request.POST.get('sales_cap', '').strip()
        sales_cap = int(cap) if cap.isdigit() else None
        item, created = MenuProfileItem.objects.get_or_create(
            profile=profile, dish=dish,
            defaults={
                'sales_cap': sales_cap,
                'is_listed': True,
                'member_price_listed': dish.member_price_enabled,
                'special_price_listed': dish.special_price_enabled,
            },
        )
        if not created:
            item.sales_cap = sales_cap
            item.is_listed = True
            item.save()
        messages.success(request, f'已将「{dish.name}」加入清单「{profile.name}」')
        return _products_redirect('menu-panel', _menus_query(profile_id))

    if 'activate_menu_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        if has_open_orders(seller_id):
            messages.error(request, '尚有未结束订单，不能切换菜单清单')
            return _products_redirect('menu-panel', _menus_query(profile_id))
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        settings = get_operating_settings(seller_id)
        settings.active_menu_profile = profile
        settings.save(update_fields=['active_menu_profile'])
        MenuProfileItem.objects.filter(profile=profile).update(sold_count=0)
        from .audit_helpers import write_audit_log
        write_audit_log(
            action_code='menu_switch',
            summary=f'切换菜单清单为「{profile.name}」',
            seller_id=seller_id,
            actor=request.user,
            target_type='menu_profile',
            target_id=str(profile.profile_id),
            request=request,
        )
        messages.success(
            request,
            f'已切换为菜单清单「{profile.name}」，店铺页面已同步更新',
        )
        return _products_redirect('menu-panel', _menus_query(profile_id))

    if 'delete_menu_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        settings = get_operating_settings(seller_id)
        if settings.active_menu_profile_id == profile.profile_id:
            messages.error(request, f'「{profile.name}」正在使用中，请先切换到其他清单再删除')
            return _products_redirect('menu-panel', _menus_query(profile_id))
        name = profile.name
        profile.delete()
        messages.success(request, f'已删除菜单清单「{name}」')
        return _products_redirect('menu-panel')

    if 'copy_menu_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        source = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        new_name = (request.POST.get('new_name') or '').strip() or f'{source.name} 副本'
        if menu_profile_name_taken(seller_id, new_name):
            messages.error(request, f'已有同名菜单清单「{new_name}」，请换一个名称')
            return _products_redirect('menu-panel', _menus_query(profile_id))
        new_profile = MenuProfile.objects.create(seller_id=seller_id, name=new_name)
        copy_profile_items(source, new_profile)
        messages.success(request, f'已复制为「{new_name}」')
        return _products_redirect('menu-panel', _menus_query(new_profile.profile_id))

    return None
