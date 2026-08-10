# 商品分档二维码 · 扫码登录加购（A.11.11 · 批次 G · G1-6）

from __future__ import annotations

from django.urls import reverse

from .product_display_code_helpers import normalize_display_code
from .product_helpers import (
    PRICE_TIER_GENERAL,
    PRICE_TIER_MEMBER,
    PRICE_TIER_SPECIAL,
    TIER_LABELS,
    cart_line_key,
    resolve_tier_price,
    validate_tier_purchase,
)

SCAN_TIERS = (
    PRICE_TIER_GENERAL,
    PRICE_TIER_MEMBER,
    PRICE_TIER_SPECIAL,
)

SESSION_PENDING_PRODUCT_SCAN = 'pending_product_scan'


def normalize_scan_tier(tier: str) -> str:
    """扫码 URL 里的档位名统一小写。"""
    return (tier or '').strip().lower()


def build_product_scan_path(seller_id: str, display_code: str, tier: str) -> str:
    """相对路径：商品扫码加购入口。"""
    code = normalize_display_code(display_code)
    tier = normalize_scan_tier(tier)
    base = reverse(
        'product_scan_add',
        kwargs={'display_code': code, 'tier': tier},
    )
    return f'{base}?seller_id={seller_id}'


def build_product_scan_absolute_url(base_url: str, seller_id: str, display_code: str, tier: str) -> str:
    """完整网址：印在二维码里。"""
    rel = build_product_scan_path(seller_id, display_code, tier)
    return f'{base_url.rstrip("/")}{rel}'


def resolve_dish_for_scan(seller_id: str, display_code: str):
    """按展示编号找在架商品；找不到返回 None。"""
    from .models import Dish

    code = normalize_display_code(display_code)
    if not code:
        return None
    return Dish.objects.filter(
        seller_id=seller_id,
        display_code=code,
        is_active=True,
    ).first()


def scan_tier_listed_on_shop(dish, tier: str, seller_id: str) -> bool:
    """当前使用中的商品列表是否允许展示该档位。"""
    from .menu_helpers import get_menu_item_for_dish, menu_item_allows_tier
    from .product_shell_helpers import catalog_controls_shop_display

    if resolve_tier_price(dish, tier) is None:
        return False
    if not catalog_controls_shop_display(seller_id):
        return True
    menu_item = get_menu_item_for_dish(seller_id, dish.dish_id)
    return menu_item_allows_tier(menu_item, tier, seller_id)


def evaluate_product_scan(dish, tier: str, seller_id: str) -> tuple[str, str]:
    """
    评估扫码是否可售。
    返回 (状态, 文案)：
    - ok / 无商品 / 须登录 / 会员不可用 / 其它拒绝原因
    """
    from .menu_helpers import dish_visible_on_shop
    from .product_shell_helpers import catalog_controls_shop_display

    tier = normalize_scan_tier(tier)
    if tier not in SCAN_TIERS:
        return 'unavailable', '无商品'

    if not dish or not dish.is_active:
        return 'unavailable', '无商品'

    if catalog_controls_shop_display(seller_id) and not dish_visible_on_shop(seller_id, dish.dish_id):
        return 'unavailable', '无商品'

    if not scan_tier_listed_on_shop(dish, tier, seller_id):
        return 'unavailable', '无商品'

    return 'ok', ''


def evaluate_product_scan_for_buyer(dish, tier: str, seller_id: str, buyer, cart: dict) -> tuple[str, str]:
    """登录后：校验通道、限购、会员资格等。"""
    status, msg = evaluate_product_scan(dish, tier, seller_id)
    if status != 'ok':
        return status, msg

    ok, reason = validate_tier_purchase(dish, tier, buyer, seller_id, 1, cart)
    if ok:
        return 'ok', ''

    tier = normalize_scan_tier(tier)
    if tier == PRICE_TIER_MEMBER:
        return 'member_denied', reason or '当前账号无法使用会员价'
    if tier == PRICE_TIER_SPECIAL:
        return 'tier_denied', reason or '当前无法使用特价'
    return 'tier_denied', reason or '暂时无法加购'


def product_scan_qr_missing_lan(request, dish, seller_id: str) -> bool:
    """有展示编号与可售档位，但没有店内可扫根地址（禁止用 127 凑数）。"""
    from .operating_helpers import resolve_shop_access_base_url

    code = normalize_display_code(getattr(dish, 'display_code', ''))
    if not code:
        return False
    if resolve_shop_access_base_url(request, seller_id):
        return False
    return any(resolve_tier_price(dish, tier) is not None for tier in SCAN_TIERS)


def build_product_scan_qr_rows(request, dish, seller_id: str) -> list[dict]:
    """卖家后台：为本商品各可用档位生成二维码数据（根地址与工作台码共用）。"""
    from .operating_helpers import resolve_shop_access_base_url
    from .workbench_qr import build_work_login_qr_png
    import base64

    code = normalize_display_code(dish.display_code)
    if not code:
        return []

    # 与工作台/桌码一致：优先局域网/公网根地址，禁止用 127 冒充店内可扫地址
    base = resolve_shop_access_base_url(request, seller_id)
    if not base:
        return []
    rows: list[dict] = []
    for tier in SCAN_TIERS:
        if resolve_tier_price(dish, tier) is None:
            continue
        url = build_product_scan_absolute_url(base, seller_id, code, tier)
        png = build_work_login_qr_png(url)
        rows.append({
            'tier': tier,
            'label': TIER_LABELS.get(tier, tier),
            'url': url,
            'data_url': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
        })
    return rows


def add_scanned_product_to_cart(request, dish, tier: str, seller_id: str) -> tuple[bool, str]:
    """扫码成功后写入购物车。"""
    from waimai.plugins.dining.buyer_entry import get_buyer_table_session

    from .channel_helpers import auto_pick_single_homepage_channel, require_shop_channel
    from .order_helpers import get_shop_cart, set_shop_cart

    tier = normalize_scan_tier(tier)
    cart = get_shop_cart(request.session, seller_id)
    buyer = request.user

    status, msg = evaluate_product_scan_for_buyer(dish, tier, seller_id, buyer, cart)
    if status in ('member_denied', 'tier_denied'):
        return False, msg
    if status != 'ok':
        return False, msg or '无商品'

    table_sess = get_buyer_table_session(request, seller_id)
    auto_pick_single_homepage_channel(request, seller_id, table_sess)
    _ft, ch_err = require_shop_channel(request, seller_id, table_sess)
    if ch_err:
        return False, ch_err

    line_key = cart_line_key(dish.dish_id, tier)
    cart[line_key] = cart.get(line_key, 0) + 1
    set_shop_cart(request.session, seller_id, cart)
    return True, ''


def dish_scroll_anchor_for_scan(dish, tier: str) -> str:
    """加购成功后滚到对应商品卡片。"""
    from .scroll_helpers import dish_scroll_anchor

    return dish_scroll_anchor(str(dish.dish_id), normalize_scan_tier(tier))
