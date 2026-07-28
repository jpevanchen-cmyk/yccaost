# H4 新手体验引导：启动数据、官方演示店（规则见手册 A.10.9）

from __future__ import annotations

import json
from typing import Any

from django.urls import reverse

from .onboarding_tour_common import (
    AUTO_ADVANCE_SECONDS,
    AUTO_ADVANCE_SECONDS_TYPE_DEMO,
    TOUR_PAGES,
)
from .onboarding_tour_catalog import buyer_tour_majors
from .onboarding_tour_seller import seller_tour_majors

OFFICIAL_SHOP_NAME = '野草官方小店'

WELCOME_SEEN_STORAGE_KEY = 'yc_onboarding_welcome_seen'

SESSION_TRACK_KEY = 'yc_onboarding_track'
SESSION_MAJOR_KEY = 'yc_onboarding_major'
SESSION_MICRO_KEY = 'yc_onboarding_micro'


def get_official_shop_profile():
    """取官方演示店；优先店名「野草官方小店」"""
    from .models import ShopProfile

    qs = ShopProfile.objects.filter(is_official=True).order_by('shop_name')
    named = qs.filter(shop_name=OFFICIAL_SHOP_NAME).first()
    if named:
        return named
    return qs.first()


def official_shop_ready() -> bool:
    return get_official_shop_profile() is not None


def _attach_major_meta(majors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为各大步补上下一步名称、是否最后一步"""
    out = []
    for i, major in enumerate(majors):
        item = dict(major)
        item['index'] = i
        item['isLast'] = i >= len(majors) - 1
        item['nextTitle'] = majors[i + 1]['title'] if i + 1 < len(majors) else ''
        out.append(item)
    return out


def build_onboarding_boot_payload() -> dict[str, Any]:
    shop = get_official_shop_profile()
    seller_id = shop.seller_id if shop else ''
    has_demo_orders = False
    if seller_id:
        from .models import BuyOrder

        has_demo_orders = BuyOrder.objects.filter(seller_id=seller_id).exists()

    from .plugin_runtime.registry import is_plugin_enabled
    from .product_shell_helpers import build_product_shell

    product_shell = build_product_shell(seller_id) if seller_id else {}
    dining_enabled = is_plugin_enabled('dining', seller_id) if seller_id else False
    fulfillment_enabled = is_plugin_enabled('fulfillment', seller_id) if seller_id else False

    seller_majors = _attach_major_meta(
        seller_tour_majors(
            official_seller_id=seller_id,
            product_shell=product_shell,
            dining_enabled=dining_enabled,
            fulfillment_enabled=fulfillment_enabled,
        ),
    )
    buyer_majors = _attach_major_meta(
        buyer_tour_majors(official_seller_id=seller_id, has_demo_orders=has_demo_orders),
    )

    pages = dict(TOUR_PAGES)
    if seller_id:
        from .models import BuyOrder

        demo_order = BuyOrder.objects.filter(seller_id=seller_id).order_by('-created_at').first()
        if demo_order:
            pages['preview_order_detail'] = reverse(
                'onboarding_seller_order_detail',
                kwargs={'order_id': demo_order.order_id},
            )

    return {
        'enabled': bool(shop),
        'officialShopName': shop.shop_name if shop else OFFICIAL_SHOP_NAME,
        'officialSellerId': seller_id,
        'officialShopCode': (shop.shop_code or '').strip() if shop else '',
        'diningEnabled': dining_enabled,
        'fulfillmentEnabled': fulfillment_enabled,
        'productShell': product_shell,
        'welcomeSeenKey': WELCOME_SEEN_STORAGE_KEY,
        'sessionTrackKey': SESSION_TRACK_KEY,
        'sessionMajorKey': SESSION_MAJOR_KEY,
        'sessionMicroKey': SESSION_MICRO_KEY,
        'pages': pages,
        'tracks': {
            'seller': seller_majors,
            'buyer': buyer_majors,
        },
        'homeUrl': reverse('home'),
        'autoAdvanceSeconds': AUTO_ADVANCE_SECONDS,
        'autoAdvanceSecondsTypeDemo': AUTO_ADVANCE_SECONDS_TYPE_DEMO,
    }


def build_onboarding_boot_json() -> str:
    return json.dumps(build_onboarding_boot_payload(), ensure_ascii=False)


def enrich_server_home_onboarding(context: dict) -> dict:
    """服务器主页追加体验引导上下文（与 context_processor 字段一致）"""
    boot = build_onboarding_boot_payload()
    context['onboarding_enabled'] = boot['enabled']
    context['onboarding_boot_json'] = json.dumps(boot, ensure_ascii=False)
    context['official_shop_name'] = boot['officialShopName']
    return context
