# 客人店页购物车 · Panel 局部刷新（进度 80-4）

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.template.loader import render_to_string

from .order_helpers import build_cart_items, cart_count_positive, cart_has_lines
from .panel_refresh_helpers import is_panel_refresh, panel_refresh_fail, panel_refresh_ok
from .product_helpers import TIER_LABELS

# 与 shop.html、panel_refresh.js 一致
SHOP_CART_PANEL_ID = 'shop-cart-shell'


def build_shop_cart_template_context(cart, seller_id, request) -> dict:
    """店铺页购物车展示用数据（含数量为 0 的行）。"""
    from .channel_helpers import channel_template_flags, resolve_shop_channel
    from .plugins.dining.buyer_entry import get_buyer_table_session
    from .product_shell_helpers import build_product_shell

    cart_items, subtotal = build_cart_items(cart, seller_id, for_checkout=False)
    cart_summary = [
        {
            'dish': item['dish'],
            'quantity': item['quantity'],
            'subtotal': item['item_total'],
            'unit_price': item['unit_price'],
            'price_tier': item['price_tier'],
            'tier_label': TIER_LABELS.get(item['price_tier'], ''),
            'line_key': item['line_key'],
        }
        for item in cart_items
    ]
    table_session = get_buyer_table_session(request, seller_id)
    shop_channel = resolve_shop_channel(request, seller_id, table_session)
    return {
        'seller_id': seller_id,
        'shop_profile': None,  # 由调用方填入
        'product_shell': build_product_shell(seller_id),
        **channel_template_flags(shop_channel),
        'cart': cart_summary,
        'cart_count': cart_count_positive(cart),
        'cart_total': subtotal,
        'cart_has_lines': cart_has_lines(cart),
    }


def shop_cart_panel_ok(
    request: HttpRequest,
    cart,
    seller_id: str,
    shop_profile,
) -> JsonResponse:
    """购物车变更成功：返回可替换 #shop-cart-shell 的 Panel JSON。"""
    ctx = build_shop_cart_template_context(cart, seller_id, request)
    ctx['shop_profile'] = shop_profile
    html = render_to_string('waimai/_shop_cart_shell.html', ctx, request=request)
    return panel_refresh_ok(html=html, panel_id=SHOP_CART_PANEL_ID, message='')


def shop_cart_panel_fail_or_none(request: HttpRequest, message: str) -> JsonResponse | None:
    """Panel 请求返回白话 JSON 失败；普通提交返回 None 由页面渲染。"""
    if is_panel_refresh(request):
        return panel_refresh_fail(message)
    return None


def run_shop_cart_idempotent(request, seller_id: str, action: str, execute):
    """
    购物车 Panel 写操作幂等（进度 80 · 幂等第 3 步）。
    同一 scope+键只改一次 session，重复请求返回首次 Panel JSON。
    """
    from .idempotency_helpers import idempotency_scope, run_idempotent

    session_key = (request.session.session_key or 'anon')[:32]
    scope = idempotency_scope('shop_cart', action, seller_id, session_key)
    return run_idempotent(request, scope, execute)
