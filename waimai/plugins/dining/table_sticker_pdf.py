# 实体桌码桌贴 PDF 导出（饮食插件包内 · A.11 · P2）

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import qrcode
from django.conf import settings
from django.http import HttpRequest
from fpdf import FPDF
from qrcode.constants import ERROR_CORRECT_M

from waimai.models import ShopProfile, ShopTable, VirtualTableCode
from waimai.plugins.dining.table_helpers import (
    build_table_scan_path,
    build_virtual_scan_path,
)

# A4 竖版；每页 3 列 x 4 行，共 12 张桌贴
_COLS = 3
_ROWS = 4
_PAGE_W = 210
_PAGE_H = 297
_MARGIN = 12


def resolve_public_base_url(request: HttpRequest, seller_id: str) -> str:
    """
    桌码/桌贴用的网站根地址，优先级：
    1. 堂食设置「桌码局域网固定地址」（店内扫码推荐）
    2. 支付设置「店铺公网网址」
    3. 当前浏览器访问地址（本机测试）
    """
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


def build_table_scan_absolute_url(base_url: str, seller_id: str, qr_token: str) -> str:
    """桌码完整网址（印在二维码里）"""
    return f'{base_url.rstrip("/")}{build_table_scan_path(seller_id, qr_token)}'


def _register_font(pdf: FPDF) -> str:
    """加载中文字体；找不到则用西文字体（店名可能显示不全）"""
    candidates = [
        Path(settings.BASE_DIR) / 'waimai' / 'static' / 'waimai' / 'fonts' / 'NotoSansSC-Regular.ttf',
        Path('C:/Windows/Fonts/simhei.ttf'),
        Path('C:/Windows/Fonts/msyh.ttf'),
    ]
    for path in candidates:
        if path.is_file():
            try:
                pdf.add_font('YCJK', '', str(path))
                return 'YCJK'
            except Exception:
                continue
    return 'Helvetica'


def _qr_image_bytes(url: str) -> bytes:
    """把扫码网址生成二维码图片（RGB JPEG，避免 fpdf 嵌入 1 位 PNG 花屏）"""
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    # qrcode 默认是 1 位黑白图，直接塞进 PDF 会显示成横纹；须转成 RGB
    img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return buf.getvalue()


def _sort_tables(tables: list[ShopTable]) -> list[ShopTable]:
    def key_fn(t: ShopTable):
        num = (t.table_number or '').strip()
        return (0, int(num)) if num.isdigit() else (1, num)

    return sorted(tables, key=key_fn)


@dataclass(frozen=True)
class _Sticker:
    """实体桌与虚拟码共用的桌贴资料。"""

    title: str
    scan_url: str
    footer: str


def _build_stickers_pdf(
    *,
    stickers: list[_Sticker],
    seller_id: str,
    shop_profile: ShopProfile | None,
    empty_text: str,
) -> bytes:
    """实体桌与虚拟码共用的 PDF 排版。"""
    shop_name = (shop_profile.shop_name if shop_profile else '') or seller_id
    shop_code = ((shop_profile.shop_code if shop_profile else '') or '').strip()

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(False)
    font = _register_font(pdf)

    usable_w = _PAGE_W - 2 * _MARGIN
    usable_h = _PAGE_H - 2 * _MARGIN
    cell_w = usable_w / _COLS
    cell_h = usable_h / _ROWS
    # 底部多一行 WiFi 提示，二维码略留空
    qr_size = min(cell_w - 14, cell_h - 52, 42)

    if not stickers:
        pdf.add_page()
        pdf.set_font(font, size=14)
        pdf.set_xy(0, 140)
        pdf.cell(0, 10, empty_text, align='C')
        return bytes(pdf.output())

    for idx, sticker in enumerate(stickers):
        if idx % (_COLS * _ROWS) == 0:
            pdf.add_page()

        pos = idx % (_COLS * _ROWS)
        col = pos % _COLS
        row = pos // _COLS
        x0 = _MARGIN + col * cell_w
        y0 = _MARGIN + row * cell_h

        qr_bytes = _qr_image_bytes(sticker.scan_url)

        pdf.set_draw_color(210, 210, 210)
        pdf.rect(x0 + 2, y0 + 2, cell_w - 4, cell_h - 4)

        pdf.set_font(font, size=24)
        pdf.set_xy(x0, y0 + 8)
        pdf.cell(cell_w, 10, sticker.title, align='C')

        pdf.set_font(font, size=9)
        pdf.set_xy(x0, y0 + 20)
        # 店名过长时截断，避免压住二维码
        pdf.cell(cell_w, 5, shop_name[:24], align='C')

        if shop_code:
            pdf.set_xy(x0, y0 + 26)
            pdf.cell(cell_w, 5, f'店码 {shop_code}', align='C')

        qr_x = x0 + (cell_w - qr_size) / 2
        qr_y = y0 + 32
        pdf.image(io.BytesIO(qr_bytes), x=qr_x, y=qr_y, w=qr_size, h=qr_size, type='JPEG')

        pdf.set_font(font, size=7)
        pdf.set_xy(x0 + 2, y0 + cell_h - 20)
        pdf.cell(cell_w - 4, 4, '先连店内访客 WiFi → 再扫此码点餐', align='C')
        pdf.set_font(font, size=8)
        pdf.set_xy(x0, y0 + cell_h - 14)
        pdf.cell(cell_w, 5, sticker.footer, align='C')

    return bytes(pdf.output())


def build_table_stickers_pdf(
    *,
    request: HttpRequest,
    seller_id: str,
    tables: list[ShopTable],
    shop_profile: ShopProfile | None,
) -> bytes:
    """生成所选实体桌台的桌贴 PDF（二进制）。"""
    base = resolve_public_base_url(request, seller_id)
    stickers = [
        _Sticker(
            title=f'桌 {table.table_number}',
            scan_url=f'{base}{build_table_scan_path(seller_id, table.qr_token)}',
            footer='微信扫码 · 一桌一单 · 可加点',
        )
        for table in _sort_tables(tables)
    ]
    return _build_stickers_pdf(
        stickers=stickers,
        seller_id=seller_id,
        shop_profile=shop_profile,
        empty_text='未选择桌台',
    )


def build_virtual_stickers_pdf(
    *,
    request: HttpRequest,
    seller_id: str,
    codes: list[VirtualTableCode],
    shop_profile: ShopProfile | None,
) -> bytes:
    """生成所选虚拟桌码的桌贴 PDF（二进制）。"""
    base = resolve_public_base_url(request, seller_id)
    stickers = [
        _Sticker(
            title=f'虚拟码 {code.code_label}',
            scan_url=f'{base}{build_virtual_scan_path(seller_id, code.qr_token)}',
            footer='微信扫码 · 拼桌虚拟码 · 可加点',
        )
        for code in codes
    ]
    return _build_stickers_pdf(
        stickers=stickers,
        seller_id=seller_id,
        shop_profile=shop_profile,
        empty_text='未选择虚拟桌码',
    )


def sticker_pdf_filename(seller_id: str) -> str:
    """下载文件名（ASCII，避免浏览器乱码）"""
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in seller_id)[:32]
    return f'table-stickers-{safe or "shop"}.pdf'


def virtual_sticker_pdf_filename(seller_id: str) -> str:
    """虚拟桌码下载文件名（ASCII，避免浏览器乱码）。"""
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in seller_id)[:32]
    return f'virtual-table-stickers-{safe or "shop"}.pdf'
