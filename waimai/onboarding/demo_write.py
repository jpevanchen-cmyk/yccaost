# 新版新手体验：菜单清单可写演示（POST 处理，redirect 或 AJAX 刷新菜单区）

from __future__ import annotations

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from waimai.menu_helpers import (
    copy_profile_items,
    find_menu_profile_by_pick_id,
    menu_profile_name_taken,
    populate_profile_with_dishes,
)
from waimai.models import MenuProfile, MenuProfileItem
from waimai.operating_helpers import get_operating_settings
from waimai.product_shell_helpers import build_product_shell
from waimai.product_seller_handlers import _get_menu_item, _is_active_menu_profile
from waimai.scroll_helpers import redirect_with_anchor

from .constants import URL_FLAG, URL_MAJOR, URL_MICRO, URL_TRACK
from .demo_cleanup import DEMO_MENU_PROFILE_NAME, register_demo_menu_profile
from .tour_session import touch_experience_tour_session, tour_query_for_redirect


def _is_menu_ajax(request) -> bool:
    return (
        request.headers.get('X-Experience-Menu-Ajax') == '1'
        or request.POST.get('experience_menu_ajax') == '1'
    )


def _collect_message_list(request) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    storage = messages.get_messages(request)
    for msg in storage:
        level = 'info'
        if msg.level_tag == 'error':
            level = 'error'
        elif msg.level_tag == 'success':
            level = 'ok'
        elif msg.level_tag == 'warning':
            level = 'warning'
        out.append({'level': level, 'text': str(msg)})
    return out


def _ajax_menu_panel_response(request, seller_id: str, profile_pick: str = '', *, ok: bool = True):
    from .preview_helpers import build_experience_products_context

    touch_experience_tour_session(request)
    ctx = build_experience_products_context(request, profile_pick=profile_pick)
    html = render_to_string('waimai/seller/_menu_catalog_panel.html', ctx, request=request)
    return JsonResponse({
        'ok': ok,
        'menuPanelHtml': html,
        'messages': _collect_message_list(request),
        'tourQuery': ctx.get('experience_tour_query') or {},
    })


def _experience_products_redirect(request, anchor=None, query=None):
    """POST 后回到新版商品演示页，并尽量保留 exp 引导参数"""
    from django.urls import reverse

    touch_experience_tour_session(request)
    base = reverse('experience_preview_products')
    parts = list(tour_query_for_redirect(request))
    if query:
        parts.insert(0, query)
    qs = '&'.join(parts)
    url = f'{base}?{qs}' if qs else base
    return redirect_with_anchor(url, anchor)


def _menus_query(profile_id=None):
    if profile_id:
        return f'profile={profile_id}'
    return ''


def _finish_menu_post(request, seller_id: str, *, anchor='menu-panel', profile_q='', ok: bool = True):
    profile_pick = ''
    if profile_q and profile_q.startswith('profile='):
        profile_pick = profile_q.split('=', 1)[1]
    if _is_menu_ajax(request):
        return _ajax_menu_panel_response(request, seller_id, profile_pick, ok=ok)
    return _experience_products_redirect(request, anchor, profile_q or None)


def handle_experience_menu_post(request, seller_id: str):
    """仅处理菜单清单相关 POST（新版体验第 3 大步）"""
    catalog_shell = build_product_shell(seller_id)
    catalog_word = catalog_shell.get('catalog_word', '商品列表')

    allowed = {
        'create_menu_profile',
        'toggle_menu_item_listed',
        'toggle_menu_item_member',
        'toggle_menu_item_special',
        'activate_menu_profile',
        'delete_menu_profile',
    }
    if not any(k in request.POST for k in allowed):
        messages.error(request, '本步演示仅开放菜单清单相关操作')
        return _finish_menu_post(request, seller_id, ok=False)

    if 'create_menu_profile' in request.POST:
        name = (request.POST.get('profile_name') or '').strip()
        copy_from_raw = (request.POST.get('copy_from_profile_id') or '').strip()
        created = False
        if not name:
            messages.error(request, '请填写清单名称')
        elif menu_profile_name_taken(seller_id, name):
            messages.error(request, f'已有同名{catalog_word}「{name}」，请换一个名称')
        else:
            profile = MenuProfile.objects.create(seller_id=seller_id, name=name)
            source = find_menu_profile_by_pick_id(seller_id, copy_from_raw) if copy_from_raw else None
            if copy_from_raw and not source:
                profile.delete()
                messages.error(request, '要复制的清单不存在，请重新选择')
            elif source:
                copy_profile_items(source, profile)
                messages.success(request, f'已创建「{name}」，并复制自「{source.name}」')
                created = True
                if name == DEMO_MENU_PROFILE_NAME:
                    register_demo_menu_profile(profile.profile_id)
            else:
                populate_profile_with_dishes(profile, seller_id)
                messages.success(request, f'已创建{catalog_word}「{name}」，已纳入本店全部商品')
                created = True
                if name == DEMO_MENU_PROFILE_NAME:
                    register_demo_menu_profile(profile.profile_id)
        # 体验引导：创建成功后仍显示「使用中」清单，不自动选中新清单，以免打乱小步脚本
        return _finish_menu_post(request, seller_id, profile_q='', ok=created)

    if 'toggle_menu_item_listed' in request.POST:
        profile_id = request.POST.get('profile_id')
        item = _get_menu_item(seller_id, profile_id, request.POST.get('item_id'))
        item.is_listed = not item.is_listed
        item.save(update_fields=['is_listed'])
        state = '上架' if item.is_listed else '下架'
        messages.success(request, f'「{item.dish.name}」在本清单已{state}')
        return _finish_menu_post(request, seller_id, profile_q=_menus_query(profile_id))

    if 'toggle_menu_item_member' in request.POST:
        profile_id = request.POST.get('profile_id')
        item = _get_menu_item(seller_id, profile_id, request.POST.get('item_id'))
        if not item.dish.member_price_enabled:
            messages.error(request, f'「{item.dish.name}」尚未在商品管理中配置会员价')
            return _finish_menu_post(request, seller_id, profile_q=_menus_query(profile_id), ok=False)
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
        return _finish_menu_post(request, seller_id, profile_q=_menus_query(profile_id))

    if 'toggle_menu_item_special' in request.POST:
        profile_id = request.POST.get('profile_id')
        item = _get_menu_item(seller_id, profile_id, request.POST.get('item_id'))
        if not item.dish.special_price_enabled:
            messages.error(request, f'「{item.dish.name}」尚未在商品管理中配置特价')
            return _finish_menu_post(request, seller_id, profile_q=_menus_query(profile_id), ok=False)
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
        return _finish_menu_post(request, seller_id, profile_q=_menus_query(profile_id))

    if 'activate_menu_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        settings = get_operating_settings(seller_id)
        settings.active_menu_profile = profile
        settings.save(update_fields=['active_menu_profile'])
        MenuProfileItem.objects.filter(profile=profile).update(sold_count=0)
        messages.success(
            request,
            f'已切换为{catalog_word}「{profile.name}」，店铺页面已同步更新',
        )
        return _finish_menu_post(request, seller_id, profile_q=_menus_query(profile_id))

    if 'delete_menu_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        settings = get_operating_settings(seller_id)
        if settings.active_menu_profile_id == profile.profile_id:
            messages.error(request, f'「{profile.name}」正在使用中，请先切换到其他清单再删除')
            return _finish_menu_post(request, seller_id, profile_q=_menus_query(profile_id), ok=False)
        name = profile.name
        profile.delete()
        messages.success(request, f'已删除{catalog_word}「{name}」')
        return _finish_menu_post(request, seller_id)

    return _finish_menu_post(request, seller_id)
