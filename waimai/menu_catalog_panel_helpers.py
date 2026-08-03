# 卖家商品页 · 菜单清单 Panel 片段（与 products 页、80 Panel 试点共用）

from __future__ import annotations

from django.http import HttpRequest
from django.template.loader import render_to_string

from .menu_helpers import find_menu_profile_by_pick_id, get_active_menu_profile
from .models import MenuProfile
from .operating_helpers import get_operating_settings
from .product_shell_helpers import build_product_shell


def build_menu_catalog_panel_context(
    request: HttpRequest,
    seller_id: str,
    *,
    profile_pick: str | None = None,
) -> dict:
    """组装 _menu_catalog_panel.html 所需上下文（与 seller products 清单区一致）"""
    product_shell = build_product_shell(seller_id)
    operating = get_operating_settings(seller_id)
    profiles: list[MenuProfile] = []
    active_profile = None
    selected = None
    if product_shell['show_menu_catalog']:
        profiles = list(
            MenuProfile.objects.filter(seller_id=seller_id)
            .prefetch_related('items__dish')
            .order_by('-updated_at'),
        )
        active_profile = get_active_menu_profile(seller_id)
        pick_id = (profile_pick if profile_pick is not None else request.GET.get('profile', '')).strip()
        selected = find_menu_profile_by_pick_id(seller_id, pick_id) if pick_id else None
        if not selected:
            selected = active_profile or (profiles[0] if profiles else None)
    return {
        'operating': operating,
        'product_shell': product_shell,
        'menu_profiles': profiles,
        'selected_profile': selected,
        'active_profile': active_profile,
        'seller_id': seller_id,
    }


def render_menu_catalog_panel_html(
    request: HttpRequest,
    seller_id: str,
    *,
    profile_pick: str | None = None,
) -> str:
    """渲染菜单清单 Panel HTML 片段"""
    ctx = build_menu_catalog_panel_context(request, seller_id, profile_pick=profile_pick)
    return render_to_string('waimai/seller/_menu_catalog_panel.html', ctx, request=request)
