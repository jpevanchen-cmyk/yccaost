# 兼容旧引用路径：堂食页 POST 已迁入饮食插件包
# 新代码请改从 waimai.plugins.dining.seller_handlers 导入 handle_dine_post
# 菜单清单 POST 仍属商品壳，暂留本文件（当前无其它入口引用）

from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.urls import reverse

from waimai.plugins.dining.seller_handlers import handle_dine_post  # noqa: F401

from .models import Dish, MenuProfile, MenuProfileItem
from .operating_helpers import get_operating_settings, has_open_orders
from .scroll_helpers import redirect_with_anchor


def _seller_redirect(section, anchor=None, query=None):
    url = reverse('seller_panel_section', kwargs={'section': section})
    if query:
        url = f'{url}?{query}'
    return redirect_with_anchor(url, anchor)


def _menus_query(profile_id=None):
    if profile_id:
        return f'profile={profile_id}'
    return ''


def handle_menus_post(request, seller_id):
    """菜单清单分区 POST（商品壳；未并入饮食插件）"""
    profile_q = request.POST.get('profile_id', '')

    if 'create_menu_profile' in request.POST:
        name = (request.POST.get('profile_name') or '').strip()
        if not name:
            messages.error(request, '请填写清单名称')
        else:
            profile = MenuProfile.objects.create(seller_id=seller_id, name=name)
            messages.success(request, f'已创建菜单清单「{name}」')
            profile_q = str(profile.profile_id)
        return _seller_redirect('menus', 'menu-panel', _menus_query(profile_q))

    if 'add_dish_to_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        dish_id = request.POST.get('dish_id')
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        dish = get_object_or_404(Dish, dish_id=dish_id, seller_id=seller_id)
        cap = request.POST.get('sales_cap', '').strip()
        sales_cap = int(cap) if cap.isdigit() else None
        item, created = MenuProfileItem.objects.get_or_create(
            profile=profile, dish=dish,
            defaults={'sales_cap': sales_cap, 'is_listed': True},
        )
        if not created:
            item.sales_cap = sales_cap
            item.is_listed = True
            item.save()
        messages.success(request, f'已将「{dish.name}」加入清单「{profile.name}」')
        return _seller_redirect('menus', 'menu-panel', _menus_query(profile_id))

    if 'activate_menu_profile' in request.POST:
        if has_open_orders(seller_id):
            messages.error(request, '尚有未结束订单，不能切换菜单清单')
            return _seller_redirect('menus', 'menu-panel', _menus_query(profile_q))
        profile_id = request.POST.get('profile_id')
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
        messages.success(request, f'已切换为菜单清单「{profile.name}」')
        return _seller_redirect('menus', 'menu-panel', _menus_query(profile_id))

    if 'copy_menu_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        source = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        new_name = (request.POST.get('new_name') or '').strip() or f'{source.name} 副本'
        new_profile = MenuProfile.objects.create(seller_id=seller_id, name=new_name)
        for item in source.items.all():
            MenuProfileItem.objects.create(
                profile=new_profile,
                dish=item.dish,
                sort_order=item.sort_order,
                is_listed=item.is_listed,
                sales_cap=item.sales_cap,
                sold_count=0,
            )
        messages.success(request, f'已复制为「{new_name}」')
        return _seller_redirect('menus', 'menu-panel', _menus_query(new_profile.profile_id))

    if 'update_dish_limits' in request.POST:
        dish_id = request.POST.get('dish_id')
        dish = get_object_or_404(Dish, dish_id=dish_id, seller_id=seller_id)
        dish.require_registered = bool(request.POST.get('require_registered'))
        dish.new_member_only = bool(request.POST.get('new_member_only'))
        max_val = request.POST.get('max_per_user', '').strip()
        dish.max_per_user = int(max_val) if max_val.isdigit() and int(max_val) > 0 else None
        sort_val = request.POST.get('sort_order', '0').strip()
        dish.sort_order = int(sort_val) if sort_val.lstrip('-').isdigit() else 0
        dish.save()
        messages.success(request, f'已更新「{dish.name}」限购与排序')
        return _seller_redirect('menus', 'dish-limits')

    return None
