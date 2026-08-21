# 邮件防刷：全服务器日上限、单收件人频率、同单同类型冷却

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings

from .time_helpers import now_local_wall

logger = logging.getLogger('waimai')

# 通知类型（写入发信记录，便于统计）
KIND_NEW_ORDER = 'new_order'
KIND_REMITTANCE_REQUEST = 'remittance_request'
KIND_BUYER_ORDER_MSG = 'buyer_order_msg'
KIND_BUYER_CASH_SHORTFALL = 'buyer_cash_shortfall'
KIND_GUESTBOOK_REPLY = 'guestbook_reply'
KIND_LOGIN_LOCKED = 'login_locked'
KIND_BUYER_TIMEOUT_REFUND = 'buyer_timeout_refund'
KIND_SHOP_TIMEOUT_REFUND = 'shop_timeout_refund'
KIND_GUEST_ORDER_VOUCHER = 'guest_order_voucher'
KIND_TEST = 'test_email'


def _daily_server_max() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_DAILY_SERVER_MAX', 400))


def _recipient_hourly_max() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_RECIPIENT_HOURLY_MAX', 5))


def _recipient_daily_max() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_RECIPIENT_DAILY_MAX', 20))


def _dedupe_cooldown_seconds() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_DEDUPE_COOLDOWN_SECONDS', 600))


def _dedupe_cooldown_seconds_for_kind(kind: str) -> int:
    """登录暂锁通知：同账号 1 小时内最多 1 封"""
    if kind == KIND_LOGIN_LOCKED:
        return 3600
    return _dedupe_cooldown_seconds()


def _local_day_start():
    """系统本地当天 0 点（查询用；USE_TZ=False 时必须是 naive）"""
    from .time_helpers import local_day_bounds_for_query

    start, _end = local_day_bounds_for_query()
    return start


def _normalize_email(email: str) -> str:
    return (email or '').strip().lower()


def recipient_send_block_reason(
    email: str,
    *,
    kind: str,
    dedupe_key: str = '',
) -> str:
    """
    判断单个收件邮箱是否被防刷规则拦住。
    返回空字符串表示可发；否则为 hourly / daily / server_daily / dedupe。
    """
    from .models import EmailSendLog

    addr = _normalize_email(email)
    if not addr:
        return 'invalid'

    day_start = _local_day_start()
    hour_ago = now_local_wall() - timedelta(hours=1)
    cooldown_since = now_local_wall() - timedelta(
        seconds=_dedupe_cooldown_seconds_for_kind(kind),
    )

    server_today = EmailSendLog.objects.filter(sent_at__gte=day_start).count()
    if server_today >= _daily_server_max():
        logger.warning('邮件防刷：全服务器今日已达上限 %s 封', _daily_server_max())
        return 'server_daily'

    if EmailSendLog.objects.filter(recipient=addr, sent_at__gte=hour_ago).count() >= _recipient_hourly_max():
        logger.info('邮件防刷：%s 每小时上限已满，跳过 %s', addr, kind)
        return 'hourly'

    if EmailSendLog.objects.filter(recipient=addr, sent_at__gte=day_start).count() >= _recipient_daily_max():
        logger.info('邮件防刷：%s 今日上限已满，跳过 %s', addr, kind)
        return 'daily'

    dedupe_key = (dedupe_key or '').strip()
    if dedupe_key and EmailSendLog.objects.filter(
        dedupe_key=dedupe_key,
        recipient=addr,
        sent_at__gte=cooldown_since,
    ).exists():
        logger.info('邮件防刷：%s 冷却中（%s），跳过', dedupe_key, kind)
        return 'dedupe'

    return ''


def filter_recipients_by_rate_limit(
    recipients: list[str],
    *,
    kind: str,
    dedupe_key: str = '',
) -> list[str]:
    """
    返回仍允许发信的收件邮箱；超限的跳过并写日志。
    dedupe_key 相同且在冷却期内：视为重复，不再发。
    """
    allowed: list[str] = []
    for raw in recipients:
        email = _normalize_email(raw)
        if not email:
            continue
        if recipient_send_block_reason(email, kind=kind, dedupe_key=dedupe_key):
            continue
        allowed.append(email)
    return allowed


def record_email_sent(
    recipients: list[str],
    *,
    kind: str,
    dedupe_key: str = '',
    sender_route: str = '',
) -> None:
    """发信成功后记一笔（不存正文）"""
    from .models import EmailSendLog

    dedupe_key = (dedupe_key or '').strip()
    route = (sender_route or '').strip()[:16]
    rows = [
        EmailSendLog(
            recipient=_normalize_email(r),
            kind=kind,
            dedupe_key=dedupe_key,
            sender_route=route,
        )
        for r in recipients
        if _normalize_email(r)
    ]
    if rows:
        EmailSendLog.objects.bulk_create(rows)

    # 顺带清理 7 天前的旧记录，避免表无限长大
    cutoff = now_local_wall() - timedelta(days=7)
    EmailSendLog.objects.filter(sent_at__lt=cutoff).delete()


def email_send_stats() -> dict:
    """今日发信统计（供服务器设置页展示）"""
    from .models import EmailSendLog

    day_start = _local_day_start()
    today_count = EmailSendLog.objects.filter(sent_at__gte=day_start).count()
    return {
        'server_daily_max': _daily_server_max(),
        'server_today': today_count,
        'recipient_hourly_max': _recipient_hourly_max(),
        'recipient_daily_max': _recipient_daily_max(),
        'dedupe_cooldown_minutes': _dedupe_cooldown_seconds() // 60,
    }
