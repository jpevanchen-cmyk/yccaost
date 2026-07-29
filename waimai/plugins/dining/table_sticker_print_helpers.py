# 实体桌码桌贴 · 网页预览（体验引导用，正式店仍走 PDF 下载）

from __future__ import annotations

import base64

from django.http import HttpRequest

from waimai.models import ShopProfile, ShopTable
from waimai.plugins.dining.table_helpers import build_table_scan_path
from waimai.workbench_qr import build_work_login_qr_png


def _resolve_public_base_url(request: HttpRequest, seller_id: str) -> str:
    """桌贴二维码用的根地址（与 PDF 导出优先级一致，但不依赖 fpdf）"""
    from waimai.operating_helpers import get_operating_settings
    from waimai.payments import get_payment_settings

    operating = get_operating_settings(seller_id)
    lan = (getattr(operating, 'table_lan_base_url', '') or '').strip().rstrip('/')
    if lan:
        return lan
    ps = get_payment_settings(seller_id)
    custom = (ps.public_site_url or '').strip().rstrip('/')
    if custom:
        return custom
    return request.build_absolute_uri('/').rstrip('/')


def build_table_sticker_print_cards(
    request: HttpRequest,
    seller_id: str,
    tables: list[ShopTable],
    *,
    shop_profile: ShopProfile | None = None,
) -> list[dict]:
    """生成桌贴预览卡片（含二维码 data URL）"""
    base = _resolve_public_base_url(request, seller_id)
    shop_name = (shop_profile.shop_name if shop_profile else '') or seller_id
    shop_code = ((shop_profile.shop_code if shop_profile else '') or '').strip()

    def sort_key(t: ShopTable):
        num = (t.table_number or '').strip()
        return (0, int(num)) if num.isdigit() else (1, num)

    cards: list[dict] = []
    for table in sorted(tables, key=sort_key):
        scan_url = f'{base.rstrip("/")}{build_table_scan_path(seller_id, table.qr_token)}'
        png = build_work_login_qr_png(scan_url)
        cards.append({
            'table_number': table.table_number,
            'title': f'桌 {table.table_number}',
            'shop_name': shop_name,
            'shop_code': shop_code,
            'data_url': 'data:image/png;base64,' + base64.b64encode(png).decode('ascii'),
            'footer': '微信扫码 · 一桌一单 · 可加点',
        })
    return cards
