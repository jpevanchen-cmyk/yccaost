# 订单码：收银台找单二维码、一维条码与打印（第三期 · 公共逻辑）

from __future__ import annotations

import base64
import io
import logging
from urllib.parse import urlencode

from .models import BuyOrder
from .payments.core import get_payment_settings
from .workbench_qr import build_work_login_qr_png

logger = logging.getLogger(__name__)


def order_show_cashier_qr(order: BuyOrder, seller_id: str) -> bool:
    """今天待支付且店主已开收银台时，可展示/打印订单码。"""
    from .cashier_helpers import _order_in_cashier_scope

    if not _order_in_cashier_scope(order):
        return False
    if (order.seller_id or '').strip() != (seller_id or '').strip():
        return False
    return bool(get_payment_settings(seller_id).enable_cashier)


def build_cashier_lookup_url(base_url: str, shop_code: str, order: BuyOrder) -> str:
    """
    二维码内容：打开本店工作台收银台并带上订单号搜索。
    收银员扫码后（须已登录）直达该单。
    """
    code = (shop_code or '').strip()
    q = order.get_display_order_no()
    query = urlencode({'view': 'cashier', 'q': q})
    return f'{base_url.rstrip("/")}/s/{code}/work/?{query}'


def build_order_qr_png_data_url(payload: str) -> str:
    """把任意文本（通常为收银台找单网址）制成二维码图片。"""
    png = build_work_login_qr_png(payload)
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def build_order_barcode_payload(order: BuyOrder) -> str:
    """
    一维条码内容：完整展示订单号（供普通扫码枪扫进收银台搜索框）。
    Code128 只认 ASCII；若展示号异常则退回 8 位短号。
    """
    display = (order.get_display_order_no() or '').strip()
    if not display:
        return order.get_order_short_code()
    try:
        display.encode('ascii')
    except UnicodeEncodeError:
        return order.get_order_short_code()
    return display


def build_order_barcode_png(payload: str) -> bytes:
    """生成 Code128 一维条码 PNG（收银用扫码枪常见格式）。"""
    text = (payload or '').strip()
    if not text:
        raise ValueError('条码内容为空')

    # 延迟导入：服务器未 pip install 时，不影响订单详情/二维码
    from barcode.codex import Code128
    from barcode.writer import ImageWriter

    writer = ImageWriter()
    code = Code128(text, writer=writer)
    buffer = io.BytesIO()
    code.write(buffer, options={
        'module_width': 0.25,
        'module_height': 10.0,
        'quiet_zone': 2.5,
        'write_text': False,
    })
    return buffer.getvalue()


def build_order_barcode_png_data_url(payload: str) -> str:
    """一维条码图片（内嵌页面/打印用）；失败时返回空字符串。"""
    try:
        png = build_order_barcode_png(payload)
    except ImportError:
        logger.warning('未安装 python-barcode，订单一维条码跳过（请 pip install -r requirements.txt）')
        return ''
    except Exception:
        logger.exception('生成订单一维条码失败 payload=%r', payload)
        return ''
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def build_order_cashier_qr_bundle(request, order: BuyOrder, shop_code: str) -> dict | None:
    """订单详情/打印页用的订单码数据包。"""
    seller_id = (order.seller_id or '').strip()
    if not order_show_cashier_qr(order, seller_id):
        return None
    base = request.build_absolute_uri('/').rstrip('/')
    lookup_url = build_cashier_lookup_url(base, shop_code, order)
    barcode_payload = build_order_barcode_payload(order)
    return {
        'display_no': order.get_display_order_no(),
        'short_code': order.get_order_short_code(),
        'lookup_url': lookup_url,
        'qr_data_url': build_order_qr_png_data_url(lookup_url),
        'barcode_payload': barcode_payload,
        'barcode_data_url': build_order_barcode_png_data_url(barcode_payload),
        'amount': order.total_amount,
        'shop_code': (shop_code or '').strip(),
    }


def resolve_shop_code_for_order(order: BuyOrder) -> str:
    """取订单所属店铺码（展示/拼网址用）。"""
    from .models import ShopProfile

    return (
        ShopProfile.objects.filter(seller_id=order.seller_id)
        .values_list('shop_code', flat=True)
        .first() or ''
    ).strip()


def order_cashier_qr_template_context(
    request,
    order: BuyOrder,
    *,
    shop_code: str = '',
    print_url: str = '',
    show_buyer_hint: bool = False,
) -> dict:
    """订单详情/工作台订单页用的订单码展示数据。"""
    code = (shop_code or resolve_shop_code_for_order(order)).strip()
    bundle = build_order_cashier_qr_bundle(request, order, code)
    if not bundle:
        return {
            'order_cashier_qr': None,
            'order_cashier_qr_print_url': '',
            'order_cashier_qr_show_buyer_hint': False,
        }
    return {
        'order_cashier_qr': bundle,
        'order_cashier_qr_print_url': print_url,
        'order_cashier_qr_show_buyer_hint': show_buyer_hint,
    }
