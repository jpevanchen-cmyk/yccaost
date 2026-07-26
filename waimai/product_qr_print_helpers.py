# G1-7：使用中清单商品二维码批量打印

from __future__ import annotations

import base64

from .product_helpers import TIER_LABELS, build_tier_purchase_hints, resolve_tier_price
from .product_scan_helpers import (
    SCAN_TIERS,
    build_product_scan_absolute_url,
    normalize_display_code,
    scan_tier_listed_on_shop,
)

# 160px 宽二维码下，中文名约 8 字内可印（超出则不印名称）
QR_PRINT_MAX_NAME_CHARS = 8


def dish_name_fits_qr_print(name: str) -> bool:
    """名称是否短到可以印在二维码下方。"""
    return len((name or '').strip()) <= QR_PRINT_MAX_NAME_CHARS


def build_tier_print_caption(dish, tier: str, seller_id: str, menu_item=None) -> str:
    """档位说明：标签 + 价格 + 购买条件（与编辑页/店铺页一致）。"""
    price = resolve_tier_price(dish, tier)
    if price is None:
        return ''
    parts = [f'{TIER_LABELS.get(tier, tier)} ¥{price}']
    hints = build_tier_purchase_hints(dish, tier, seller_id, menu_item)
    parts.extend(hints)
    return ' · '.join(parts)


def build_catalog_qr_print_cards(request, seller_id: str) -> list[dict]:
    """使用中清单内全部商品的打印用二维码卡片。"""
    from .menu_helpers import get_active_menu_items_map, get_shop_dishes_for_sale
    from .workbench_qr import build_work_login_qr_png

    dishes_qs, using_menu = get_shop_dishes_for_sale(seller_id)
    dishes = list(dishes_qs)
    menu_map = get_active_menu_items_map(seller_id) if using_menu else {}
    base = request.build_absolute_uri('/').rstrip('/')

    cards: list[dict] = []
    for dish in dishes:
        code = normalize_display_code(dish.display_code)
        if not code:
            continue
        menu_item = menu_map.get(dish.dish_id)
        tier_cards: list[dict] = []
        for tier in SCAN_TIERS:
            if resolve_tier_price(dish, tier) is None:
                continue
            if not scan_tier_listed_on_shop(dish, tier, seller_id):
                continue
            url = build_product_scan_absolute_url(base, seller_id, code, tier)
            png = build_work_login_qr_png(url)
            tier_cards.append({
                'tier': tier,
                'label': TIER_LABELS.get(tier, tier),
                'data_url': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
                'caption': build_tier_print_caption(dish, tier, seller_id, menu_item),
            })
        if tier_cards:
            cards.append({
                'dish': dish,
                'display_code': code.upper(),
                'show_name': dish_name_fits_qr_print(dish.name),
                'tiers': tier_cards,
            })
    return cards
