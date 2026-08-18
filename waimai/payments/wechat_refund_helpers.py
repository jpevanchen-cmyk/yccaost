# 微信退款（APIv2）：发起退款、查退款结果（V1 最小版 · 整单全额）

from __future__ import annotations

import secrets
import ssl
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.utils import timezone
from waimai.time_helpers import now_local_wall

from ..models import BuyOrder, PaymentRecord, ShopPaymentSettings
from .wechat_native import (
    _amount_fen,
    _from_xml,
    _post_xml,
    _sign_params,
    _to_xml,
    wechat_order_goods_body,
)

WECHAT_REFUND_URL = 'https://api.mch.weixin.qq.com/secapi/pay/refund'
WECHAT_REFUNDQUERY_URL = 'https://api.mch.weixin.qq.com/pay/refundquery'


def _nonce_str(length=32) -> str:
    return secrets.token_hex(length // 2)[:length]


def _post_xml_secapi(url: str, params: dict, settings: ShopPaymentSettings) -> dict:
    """带商户证书 POST（退款接口专用）"""
    cert_path = (settings.wechat_apiclient_cert_path or '').strip()
    key_path = (settings.wechat_apiclient_key_path or '').strip()
    body = _to_xml(params)
    ctx = ssl.create_default_context()
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    req = Request(url, data=body, method='POST', headers={'Content-Type': 'application/xml'})
    try:
        with urlopen(req, timeout=15, context=ctx) as resp:
            return _from_xml(resp.read())
    except URLError as exc:
        return {'return_code': 'FAIL', 'return_msg': str(exc)}


def _make_out_refund_no(record: PaymentRecord) -> str:
    """生成商户退款单号（32 字符内）"""
    base = f'R{record.out_trade_no}'[:28]
    candidate = base
    n = 0
    while PaymentRecord.objects.filter(out_refund_no=candidate).exclude(pk=record.pk).exists():
        n += 1
        candidate = f'{base[:24]}{n:04d}'[:32]
    return candidate


def get_wechat_success_record(order: BuyOrder) -> PaymentRecord | None:
    """取本单已成功收款的微信流水"""
    return (
        order.payment_records.filter(
            payment_method='wechat',
            status='success',
        )
        .order_by('-paid_at', '-created_at')
        .first()
    )


def request_wechat_refund(
    record: PaymentRecord,
    settings: ShopPaymentSettings,
    *,
    operator: str = 'system',
) -> tuple[bool, str]:
    """
    向微信发起整单全额退款。
    成功或处理中返回 True；明确失败返回 False。
    """
    if record.refund_status == 'success':
        return True, '该笔已退款'

    if not settings.wechat_refund_config_ready():
        return False, '微信退款证书未配置或文件不存在，请店主在支付设置中填写 apiclient 证书路径'

    order = record.buy_order
    if not record.out_refund_no:
        record.out_refund_no = _make_out_refund_no(record)
        record.save(update_fields=['out_refund_no', 'updated_at'])

    total_fen = _amount_fen(record.amount)
    params = {
        'appid': settings.wechat_app_id.strip(),
        'mch_id': settings.wechat_mch_id.strip(),
        'nonce_str': _nonce_str(),
        'out_trade_no': record.out_trade_no,
        'out_refund_no': record.out_refund_no,
        'total_fee': str(total_fen),
        'refund_fee': str(total_fen),
        'refund_desc': wechat_order_goods_body(order, refund=True),
        'op_user_id': settings.wechat_mch_id.strip(),
    }
    params['sign'] = _sign_params(params, settings.wechat_api_key.strip())
    result = _post_xml_secapi(WECHAT_REFUND_URL, params, settings)

    if result.get('return_code') != 'SUCCESS':
        from ..audit_helpers import log_payment_issue

        log_payment_issue(
            '微信退款通信失败 order=%s msg=%s',
            order.order_id, result.get('return_msg', ''),
        )
        record.refund_status = 'failed'
        record.refund_payload = result
        record.save(update_fields=['refund_status', 'refund_payload', 'updated_at'])
        return False, result.get('return_msg', '微信退款通信失败')

    if result.get('result_code') != 'SUCCESS':
        from ..audit_helpers import log_payment_issue

        log_payment_issue(
            '微信退款业务失败 order=%s msg=%s',
            order.order_id, result.get('err_code_des', result.get('err_code', '')),
        )
        record.refund_status = 'failed'
        record.refund_payload = result
        record.save(update_fields=['refund_status', 'refund_payload', 'updated_at'])
        err = result.get('err_code_des') or result.get('err_code') or '微信退款失败'
        return False, err

    record.refund_id = result.get('refund_id', '') or record.refund_id
    record.refund_payload = result
    wx_status = (result.get('refund_status') or '').upper()
    from ..fund_ledger_hooks import record_wechat_refund_processing

    if wx_status == 'SUCCESS':
        record_wechat_refund_processing(
            order,
            out_refund_no=record.out_refund_no,
            out_trade_no=record.out_trade_no,
            source='shop_cancel_refund',
            operator=operator,
        )
        apply_wechat_refund_success(record, operator=operator, payload=result)
        return True, '微信退款已成功'
    if wx_status in ('PROCESSING', 'CHANGE'):
        record.refund_status = 'processing'
        record.save(update_fields=['refund_id', 'refund_status', 'refund_payload', 'updated_at'])
        record_wechat_refund_processing(
            order,
            out_refund_no=record.out_refund_no,
            out_trade_no=record.out_trade_no,
            source='shop_cancel_refund',
            operator=operator,
        )
        return True, '微信退款已提交，系统将继续查询结果'

    record.refund_status = 'processing'
    record.save(update_fields=['refund_id', 'refund_status', 'refund_payload', 'updated_at'])
    record_wechat_refund_processing(
        order,
        out_refund_no=record.out_refund_no,
        out_trade_no=record.out_trade_no,
        source='shop_cancel_refund',
        operator=operator,
    )
    return True, '微信退款已提交，系统将继续查询结果'


def query_wechat_refund(record: PaymentRecord, settings: ShopPaymentSettings) -> dict:
    """查退款结果（无需证书）"""
    params = {
        'appid': settings.wechat_app_id.strip(),
        'mch_id': settings.wechat_mch_id.strip(),
        'nonce_str': _nonce_str(),
    }
    if record.out_refund_no:
        params['out_refund_no'] = record.out_refund_no
    else:
        params['out_trade_no'] = record.out_trade_no
    params['sign'] = _sign_params(params, settings.wechat_api_key.strip())
    return _post_xml(WECHAT_REFUNDQUERY_URL, params)


def apply_wechat_refund_success(
    record: PaymentRecord,
    *,
    operator: str = 'system',
    payload: dict | None = None,
) -> None:
    """退款成功：更新流水、订单支付状态、资金流水（幂等）"""
    if record.refund_status == 'success':
        return

    record.refund_status = 'success'
    if payload:
        record.refund_payload = payload
    record.refunded_at = now_local_wall()
    record.save(update_fields=['refund_status', 'refund_payload', 'refunded_at', 'updated_at'])

    order = record.buy_order
    # 现金已付清后又来一笔微信：只退微信，主单保持已付
    keep_paid = (
        order.payment_status == 'paid'
        and (order.payment_method or '') == 'cash'
        and order.order_status != 'cancelled'
    )
    if not keep_paid and order.payment_status != 'refunded':
        order.payment_status = 'refunded'
        order.save(update_fields=['payment_status', 'updated_at'])

    from ..fund_ledger_hooks import record_wechat_refund_success

    record_wechat_refund_success(
        order,
        out_refund_no=record.out_refund_no,
        out_trade_no=record.out_trade_no,
        source='wechat_refund_query',
        operator=operator,
    )
    if order.cancel_side == 'system':
        from ..pending_payment_timeout_helpers import notify_timeout_refund_update

        notify_timeout_refund_update(order, kind='success')


def try_sync_wechat_refund(record: PaymentRecord, settings: ShopPaymentSettings) -> bool:
    """查退款并同步；成功返回 True"""
    if record.refund_status == 'success':
        return True
    if not record.out_refund_no and record.refund_status != 'processing':
        return False

    result = query_wechat_refund(record, settings)
    if result.get('return_code') != 'SUCCESS' or result.get('result_code') != 'SUCCESS':
        return False

    wx_status = ''
    for key, value in result.items():
        if key.startswith('refund_status_') and key.endswith('0'):
            wx_status = (value or '').upper()
            break
    if not wx_status:
        wx_status = (result.get('refund_status_0') or '').upper()

    if wx_status == 'SUCCESS':
        if not record.refund_id and result.get('refund_id_0'):
            record.refund_id = result.get('refund_id_0', '')
        apply_wechat_refund_success(record, payload=result)
        return True
    if wx_status in ('PROCESSING', 'CHANGE'):
        if record.refund_status != 'processing':
            record.refund_status = 'processing'
            record.refund_payload = result
            record.save(update_fields=['refund_status', 'refund_payload', 'updated_at'])
        return False
    return False


def order_needs_wechat_refund(order: BuyOrder) -> bool:
    """是否须走微信原路退款（已微信到账且尚未退完；含超时取消后到账）"""
    if (order.payment_method or '') != 'wechat':
        return False
    if order.payment_status not in ('paid', 'cancelled') and order.order_status != 'cancelled':
        return False
    record = get_wechat_success_record(order)
    return bool(record and record.refund_status != 'success')


def is_shop_owner_account(user) -> bool:
    """是否店主主账号（非员工工牌）；买家开店后仍算店主。"""
    from waimai.account_helpers import user_has_seller_capability

    return user_has_seller_capability(user)


def initiate_wechat_refund_for_order(
    order: BuyOrder,
    settings: ShopPaymentSettings,
    *,
    operator: str,
) -> tuple[bool, str]:
    """店家取消时：对本单发起微信全额退款"""
    record = get_wechat_success_record(order)
    if not record:
        return False, '未找到本单的微信收款记录，无法退款'
    if record.refund_status == 'success':
        return True, '该笔已退款'
    if record.refund_status == 'processing':
        try_sync_wechat_refund(record, settings)
        record.refresh_from_db()
        if record.refund_status == 'success':
            return True, '微信退款已成功'
        return True, '微信退款处理中，请稍后在订单页查看'

    ok, msg = request_wechat_refund(record, settings, operator=operator)
    record.refresh_from_db()
    if ok and record.refund_status == 'processing':
        try_sync_wechat_refund(record, settings)
        record.refresh_from_db()
    return ok, msg


def poll_wechat_refund(order: BuyOrder) -> bool:
    """轮询查退款（无公网回调时的备用，与收款轮询对称）"""
    from .service import get_payment_settings

    settings = get_payment_settings(order.seller_id)
    if not settings.wechat_config_ready():
        return False

    record = (
        order.payment_records.filter(
            payment_method='wechat',
            refund_status='processing',
        )
        .order_by('-updated_at')
        .first()
    )
    if not record:
        record = get_wechat_success_record(order)
        if not record or record.refund_status in ('', 'success'):
            return order.payment_status == 'refunded'
        if record.refund_status != 'processing':
            return record.refund_status == 'success'

    return try_sync_wechat_refund(record, settings)


def shop_cancel_refund_hint(order: BuyOrder) -> str:
    """取消面板上的退款说明"""
    if order.payment_status == 'paid' and order.payment_method == 'wechat':
        return '取消后将自动向微信发起整单全额原路退款（须已配置退款证书）。'
    if order.payment_status == 'paid':
        return '取消后若已收款，请线下退款给客人。'
    return '操作会写入留痕。'
