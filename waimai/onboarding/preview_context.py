# 新版新手体验：只读演示页公共上下文（v2 路由）

from __future__ import annotations

from django.urls import reverse

from .official_shop import get_official_shop_profile
from waimai.plugin_runtime.registry import collect_seller_nav_items, is_plugin_enabled


def _experience_section_url(section: str) -> str:
    if section == 'operating':
        return reverse('experience_preview_operating')
    if section == 'products':
        return reverse('experience_preview_products')
    if section == 'workbench':
        return reverse('experience_preview_workbench')
    if section == 'dine':
        return reverse('experience_preview_dine')
    if section == 'delivery':
        return reverse('experience_preview_delivery')
    if section == 'payment':
        return reverse('experience_preview_payment')
    if section == 'orders':
        return reverse('experience_preview_orders')
    if section == 'homepage':
        return reverse('experience_preview_homepage')
    # 其余 Tab 尚未定稿：回到新版入口
    return reverse('experience_home')


def build_experience_preview_nav(seller_id: str, active_section: str) -> list[dict]:
    """卖家 Tab：营业状态、商品上架链到 v2 演示；其它回到新版入口"""
    items = []
    for item in collect_seller_nav_items(seller_id):
        sec = item.section
        if sec in ('dishes', 'menus'):
            continue
        items.append({
            'section': sec,
            'label': item.label,
            'icon': item.icon,
            'mobile_label': item.mobile_label or item.label,
            'href': _experience_section_url(sec),
            'active': sec == active_section,
        })
    return items


def base_experience_preview_context(page_title: str, section: str) -> dict:
    shop = get_official_shop_profile()
    seller_id = shop.seller_id if shop else ''
    from waimai.product_shell_helpers import build_product_shell

    shell = build_product_shell(seller_id) if seller_id else {}
    dining = is_plugin_enabled('dining', seller_id) if seller_id else False
    fulfillment = is_plugin_enabled('fulfillment', seller_id) if seller_id else False
    return {
        'onboarding_preview': True,
        'onboarding_readonly': True,
        'experience_preview': True,
        'onboarding_page_title': page_title,
        'official_shop': shop,
        'seller_id': seller_id,
        'shop_profile': shop,
        'section': section,
        'product_shell': shell,
        'dining_enabled': dining,
        'fulfillment_enabled': fulfillment,
        'seller_nav_items': build_experience_preview_nav(seller_id, section) if seller_id else [],
        'home_url': reverse('experience_home'),
        'showcase_preview_url': (
            f"/s/{shop.shop_code.strip()}/home/" if shop and (shop.shop_code or '').strip() else '/'
        ),
        'shop_order_preview_url': f'/shop/?seller_id={seller_id}' if seller_id else '/shop/',
    }
