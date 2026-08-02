# 新版新手体验：启动数据

from __future__ import annotations

import json
from typing import Any

from django.urls import reverse

from .constants import (
    AUTO_ADVANCE_SECONDS,
    AUTO_ADVANCE_SECONDS_TYPE_DEMO,
    SESSION_MAJOR_KEY,
    SESSION_MICRO_KEY,
    SESSION_TRACK_KEY,
    SKIP_HINT_SEEN_KEY,
    URL_FLAG,
    URL_MAJOR,
    URL_MICRO,
    URL_TRACK,
    WELCOME_SEEN_KEY,
)
from .official_shop import OFFICIAL_SHOP_NAME, get_official_shop_profile, official_shop_ready
from .tour_common import TOUR_PAGES
from .tour_seller import seller_tour_majors


def experience_shop_ready() -> bool:
    return official_shop_ready()


def _attach_major_meta(majors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, major in enumerate(majors):
        item = dict(major)
        item['index'] = i
        item['isLast'] = i >= len(majors) - 1
        item['nextTitle'] = majors[i + 1]['title'] if i + 1 < len(majors) else ''
        out.append(item)
    return out


def build_experience_boot_payload() -> dict[str, Any]:
    shop = get_official_shop_profile()
    seller_id = shop.seller_id if shop else ''
    from waimai.plugin_runtime.registry import is_plugin_enabled

    dining_enabled = is_plugin_enabled('dining', seller_id) if seller_id else False
    fulfillment_enabled = is_plugin_enabled('fulfillment', seller_id) if seller_id else False
    seller_majors = _attach_major_meta(
        seller_tour_majors(
            dining_enabled=dining_enabled,
            fulfillment_enabled=fulfillment_enabled,
            seller_id=seller_id,
        ),
    )
    demo_copy_profile_id = ''
    if seller_id:
        from waimai.menu_helpers import get_active_menu_profile

        active_profile = get_active_menu_profile(seller_id)
        if active_profile:
            demo_copy_profile_id = str(active_profile.profile_id)
    demo_dish_edit_pick = ''
    if seller_id:
        from .demo_cleanup import get_demo_dish_for_seller

        demo_dish = get_demo_dish_for_seller(seller_id)
        if demo_dish:
            demo_dish_edit_pick = demo_dish.dish_id.hex[:8]
    pages = dict(TOUR_PAGES)
    if seller_id:
        from waimai.models import BuyOrder

        demo_order = BuyOrder.objects.filter(seller_id=seller_id).order_by('-created_at').first()
        if demo_order:
            pages['preview_order_detail'] = reverse(
                'experience_preview_order_detail',
                kwargs={'order_id': demo_order.order_id},
            )
    return {
        'enabled': bool(shop),
        'version': 2,
        'officialShopName': shop.shop_name if shop else OFFICIAL_SHOP_NAME,
        'officialSellerId': seller_id,
        'demoCopyProfileId': demo_copy_profile_id,
        'demoDishEditPick': demo_dish_edit_pick,
        'cleanupUrl': reverse('experience_cleanup'),
        'writablePages': ['preview_products', 'preview_dine'],
        'welcomeSeenKey': WELCOME_SEEN_KEY,
        'skipHintSeenKey': SKIP_HINT_SEEN_KEY,
        'sessionTrackKey': SESSION_TRACK_KEY,
        'sessionMajorKey': SESSION_MAJOR_KEY,
        'sessionMicroKey': SESSION_MICRO_KEY,
        'urlFlag': URL_FLAG,
        'urlTrack': URL_TRACK,
        'urlMajor': URL_MAJOR,
        'urlMicro': URL_MICRO,
        'pages': pages,
        'tracks': {'seller': seller_majors},
        'homeUrl': reverse('experience_home'),
        'exitHomeUrl': reverse('home'),
        'autoAdvanceSeconds': AUTO_ADVANCE_SECONDS,
        'autoAdvanceSecondsTypeDemo': AUTO_ADVANCE_SECONDS_TYPE_DEMO,
    }


def build_experience_boot_json() -> str:
    return json.dumps(build_experience_boot_payload(), ensure_ascii=False)


def should_inject_experience_boot(request) -> bool:
    """换页引导（?exp=1）、新版入口页、服务器主页需要注入启动数据"""
    path = request.path or ''
    if path.startswith('/experience/'):
        return True
    if path in ('/', '/directory/') or path.startswith('/directory/'):
        return True
    return request.GET.get(URL_FLAG) == '1'
