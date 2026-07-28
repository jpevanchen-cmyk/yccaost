# H4 新手体验：只读后台演示页公共上下文

from __future__ import annotations

from django.urls import reverse

from .onboarding_helpers import get_official_shop_profile
from .plugin_runtime.registry import collect_seller_nav_items, is_plugin_enabled


def _preview_section_url(section: str) -> str:
    mapping = {
        'orders': 'onboarding_seller_orders',
        'products': 'onboarding_seller_products',
        'operating': 'onboarding_seller_operating',
        'workbench': 'onboarding_seller_workbench_manage',
        'payment': 'onboarding_seller_payment',
        'homepage': 'onboarding_seller_homepage',
        'dine': 'onboarding_seller_dine',
        'delivery': 'onboarding_seller_delivery',
    }
    name = mapping.get(section)
    if not name:
        return reverse('home')
    return reverse(name)


def build_seller_preview_nav(seller_id: str, active_section: str) -> list[dict]:
    """仿卖家后台 Tab；链接到各只读演示页"""
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
            'href': _preview_section_url(sec),
            'active': sec == active_section,
        })
    return items


def base_preview_context(page_title: str, section: str) -> dict:
    shop = get_official_shop_profile()
    seller_id = shop.seller_id if shop else ''
    from .product_shell_helpers import build_product_shell

    shell = build_product_shell(seller_id) if seller_id else {}
    dining = is_plugin_enabled('dining', seller_id) if seller_id else False
    fulfillment = is_plugin_enabled('fulfillment', seller_id) if seller_id else False
    return {
        'onboarding_preview': True,
        'onboarding_page_title': page_title,
        'official_shop': shop,
        'seller_id': seller_id,
        'shop_profile': shop,
        'section': section,
        'product_shell': shell,
        'dining_enabled': dining,
        'fulfillment_enabled': fulfillment,
        'seller_nav_items': build_seller_preview_nav(seller_id, section) if seller_id else [],
        'home_url': reverse('home'),
        'showcase_preview_url': (
            f"/s/{shop.shop_code.strip()}/home/" if shop and (shop.shop_code or '').strip() else '/'
        ),
        'shop_order_preview_url': f'/shop/?seller_id={seller_id}' if seller_id else '/shop/',
    }
