# 微信支付 Native 扫码（APIv2）：下单、查单、验签、处理通知

import hashlib
import secrets
import xml.etree.ElementTree as ET
from decimal import Decimal
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.utils import timezone

from ..models import BuyOrder, PaymentRecord, ShopPaymentSettings
from .base import PaymentInitResult

WECHAT_UNIFIEDORDER_URL = 'https://api.mch.weixin.qq.com/pay/unifiedorder'
WECHAT_ORDERQUERY_URL = 'https://api.mch.weixin.qq.com/pay/orderquery'


def _nonce_str(length=32):
    """随机字符串"""
    return secrets.token_hex(length // 2)[:length]


def _to_xml(params: dict) -> bytes:
    """字典转微信 XML"""
    parts = ['<xml>']
    for key, value in params.items():
        if value is None:
            continue
        parts.append(f'<{key}><![CDATA[{value}]]></{key}>')
    parts.append('</xml>')
    return ''.join(parts).encode('utf-8')


def _from_xml(xml_bytes: bytes) -> dict:
    """微信 XML 转字典"""
    root = ET.fromstring(xml_bytes)
    return {child.tag: (child.text or '') for child in root}


def _sign_params(params: dict, api_key: str) -> str:
    """APIv2 签名"""
    items = sorted((k, v) for k, v in params.items() if v and k != 'sign')
    raw = '&'.join(f'{k}={v}' for k, v in items)
    raw = f'{raw}&key={api_key}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest().upper()


def _verify_sign(params: dict, api_key: str) -> bool:
    """校验微信回调签名"""
    sign = params.get('sign', '')
    if not sign:
        return False
    return _sign_params(params, api_key) == sign


def _post_xml(url: str, params: dict) -> dict:
    """向微信服务器 POST XML"""
    body = _to_xml(params)
    req = Request(url, data=body, method='POST', headers={'Content-Type': 'application/xml'})
    try:
        with urlopen(req, timeout=15) as resp:
            return _from_xml(resp.read())
    except URLError as exc:
        return {'return_code': 'FAIL', 'return_msg': str(exc)}


def _amount_fen(amount: Decimal) -> int:
    """元转分（微信金额单位）"""
    return int((amount * 100).quantize(Decimal('1')))


def _notify_url(settings: ShopPaymentSettings) -> str:
    """拼微信异步通知地址"""
    base = (settings.public_site_url or '').strip().rstrip('/')
    if not base:
        return ''
    return f'{base}/pay/wechat/notify/'


def _make_out_trade_no(order: BuyOrder) -> str:
    """商户订单号（微信要求 32 字符内）"""
    return order.order_id.hex[:32]


def _get_or_create_pending_record(order: BuyOrder) -> PaymentRecord:
    """获取或创建待支付的微信流水"""
    existing = (
        order.payment_records.filter(payment_method='wechat', status='pending')
        .exclude(code_url='')
        .order_by('-created_at')
        .first()
    )
    if existing:
        return existing

    order.payment_records.filter(
        payment_method='wechat', status='pending', code_url='',
    ).update(status='closed')

    out_trade_no = _make_out_trade_no(order)
    while PaymentRecord.objects.filter(out_trade_no=out_trade_no).exists():
        out_trade_no = f"{order.order_id.hex[:24]}{_nonce_str(8)}"[:32]

    return PaymentRecord.objects.create(
        buy_order=order,
        payment_method='wechat',
        out_trade_no=out_trade_no,
        amount=order.total_amount,
        status='pending',
    )


def create_native_payment(order: BuyOrder, settings: ShopPaymentSettings, client_ip: str) -> PaymentInitResult:
    """调用微信统一下单，返回扫码链接"""
    if not settings.wechat_config_ready():
        return PaymentInitResult(ok=False, message='微信商户参数未配置完整，请联系店家')

    notify_url = _notify_url(settings)
    record = _get_or_create_pending_record(order)

    params = {
        'appid': settings.wechat_app_id.strip(),
        'mch_id': settings.wechat_mch_id.strip(),
        'nonce_str': _nonce_str(),
        'body': f'野草订单{order.get_display_order_no()}',
        'out_trade_no': record.out_trade_no,
        'total_fee': str(_amount_fen(order.total_amount)),
        'spbill_create_ip': client_ip or '127.0.0.1',
        'trade_type': 'NATIVE',
    }
    if notify_url:
        params['notify_url'] = notify_url

    params['sign'] = _sign_params(params, settings.wechat_api_key.strip())
    result = _post_xml(WECHAT_UNIFIEDORDER_URL, params)

    if result.get('return_code') != 'SUCCESS':
        from ..audit_helpers import log_payment_issue
        log_payment_issue(
            '微信统一下单通信失败 order=%s msg=%s',
            order.order_id, result.get('return_msg', ''),
        )
        return PaymentInitResult(ok=False, message=result.get('return_msg', '微信通信失败'))
    if result.get('result_code') != 'SUCCESS':
        from ..audit_helpers import log_payment_issue
        log_payment_issue(
            '微信统一下单业务失败 order=%s msg=%s',
            order.order_id, result.get('err_code_des', ''),
        )
        return PaymentInitResult(ok=False, message=result.get('err_code_des', '微信下单失败'))

    code_url = result.get('code_url', '')
    if not code_url:
        return PaymentInitResult(ok=False, message='微信未返回扫码链接')

    record.code_url = code_url
    record.save(update_fields=['code_url', 'updated_at'])

    order.payment_method = 'wechat'
    order.save(update_fields=['payment_method', 'updated_at'])

    return PaymentInitResult(
        ok=True,
        template_name='waimai/pay_wechat.html',
        extra_context={
            'code_url': code_url,
            'out_trade_no': record.out_trade_no,
            'use_notify': bool(notify_url),
        },
    )


def query_wechat_order(record: PaymentRecord, settings: ShopPaymentSettings) -> dict:
    """主动向微信查单（无公网回调时的备用）"""
    params = {
        'appid': settings.wechat_app_id.strip(),
        'mch_id': settings.wechat_mch_id.strip(),
        'out_trade_no': record.out_trade_no,
        'nonce_str': _nonce_str(),
    }
    params['sign'] = _sign_params(params, settings.wechat_api_key.strip())
    return _post_xml(WECHAT_ORDERQUERY_URL, params)


def apply_wechat_success(record: PaymentRecord, provider_trade_no: str, notify_payload: dict | None = None):
    """流水与订单标记为已支付（幂等）"""
    from .service import confirm_order_paid

    if record.status == 'success':
        return

    record.status = 'success'
    record.provider_trade_no = provider_trade_no or ''
    if notify_payload:
        record.notify_payload = notify_payload
    record.paid_at = timezone.now()
    record.save()

    order = record.buy_order
    if order.payment_status != 'paid':
        confirm_order_paid(order, 'wechat', paid_at=record.paid_at)


def try_sync_wechat_payment(record: PaymentRecord, settings: ShopPaymentSettings) -> bool:
    """查单并同步支付状态，成功返回 True"""
    if record.status == 'success':
        return True

    result = query_wechat_order(record, settings)
    if result.get('return_code') != 'SUCCESS' or result.get('result_code') != 'SUCCESS':
        return False
    if result.get('trade_state') != 'SUCCESS':
        return False

    apply_wechat_success(record, result.get('transaction_id', ''), notify_payload=result)
    return True


def parse_and_handle_notify(xml_body: bytes, settings_by_mch: dict) -> tuple[bool, str]:
    """
    处理微信异步通知。
    settings_by_mch: {mch_id: ShopPaymentSettings} 用于验签（按商户号找配置）
    返回 (是否成功响应微信, 错误信息)
    """
    try:
        data = _from_xml(xml_body)
    except ET.ParseError:
        from ..audit_helpers import log_payment_issue
        log_payment_issue('微信回调 XML 解析失败')
        return False, 'XML 解析失败'

    mch_id = data.get('mch_id', '')
    settings = settings_by_mch.get(mch_id)
    if not settings:
        from ..audit_helpers import log_payment_issue
        log_payment_issue('微信回调未知商户号 mch_id=%s', mch_id)
        return False, '未知商户号'

    if not _verify_sign(data, settings.wechat_api_key.strip()):
        from ..audit_helpers import log_payment_issue
        log_payment_issue('微信回调验签失败 mch_id=%s out_trade_no=%s', mch_id, data.get('out_trade_no', ''))
        return False, '签名校验失败'

    if data.get('return_code') != 'SUCCESS' or data.get('result_code') != 'SUCCESS':
        return True, '非成功通知，已忽略'

    out_trade_no = data.get('out_trade_no', '')
    try:
        record = PaymentRecord.objects.select_related('buy_order').get(
            out_trade_no=out_trade_no, payment_method='wechat',
        )
    except PaymentRecord.DoesNotExist:
        from ..audit_helpers import log_payment_issue
        log_payment_issue('微信回调流水不存在 out_trade_no=%s', out_trade_no)
        return False, '流水不存在'

    apply_wechat_success(record, data.get('transaction_id', ''), notify_payload=data)
    return True, 'OK'


def notify_success_xml() -> bytes:
    """告诉微信：通知已收到"""
    return _to_xml({'return_code': 'SUCCESS', 'return_msg': 'OK'})


def notify_fail_xml(msg: str) -> bytes:
    """告诉微信：处理失败"""
    return _to_xml({'return_code': 'FAIL', 'return_msg': msg[:128]})
