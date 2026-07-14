# 店铺工作台登录二维码图片

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def build_work_login_qr_png(work_url: str) -> bytes:
    """生成工作台登录链接的 PNG 二维码"""
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(work_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()
