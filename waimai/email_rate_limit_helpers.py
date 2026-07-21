# 邮件防刷：全服务器日上限、单收件人频率、同单同类型冷却

from __future__ import annotations

import logging
from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('waimai')

BEIJING = ZoneInfo('Asia/Shanghai')

# 通知类型（写入发信记录，便于统计）
KIND_NEW_ORDER = 'new_order'
KIND_BUYER_ORDER_MSG = 'buyer_order_msg'
KIND_BUYER_CASH_SHORTFALL = 'buyer_cash_shortfall'
KIND_GUESTBOOK_REPLY = 'guestbook_reply'
KIND_TEST = 'test_email'


def _daily_server_max() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_DAILY_SERVER_MAX', 400))


def _recipient_hourly_max() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_RECIPIENT_HOURLY_MAX', 5))


def _recipient_daily_max() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_RECIPIENT_DAILY_MAX', 20))


def _dedupe_cooldown_seconds() -> int:
    return int(getattr(settings, 'YECAO_EMAIL_DEDUPE_COOLDOWN_SECONDS', 600))


def _beijing_day_start():
    """北京时间当天 0 点（转 UTC 存库对比）"""
    local_now = timezone.now().astimezone(BEIJING)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(dt_timezone.utc)


def _normalize_email(email: str) -> str:
    return (email or '').strip().lower()


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
    from .models import EmailSendLog

    allowed: list[str] = []
    day_start = _beijing_day_start()
    hour_ago = timezone.now() - timedelta(hours=1)
    cooldown_since = timezone.now() - timedelta(seconds=_dedupe_cooldown_seconds())

    server_today = EmailSendLog.objects.filter(sent_at__gte=day_start).count()
    if server_today >= _daily_server_max():
        logger.warning('邮件防刷：全服务器今日已达上限 %s 封', _daily_server_max())
        return []

    dedupe_key = (dedupe_key or '').strip()
    for raw in recipients:
        email = _normalize_email(raw)
        if not email:
            continue

        if EmailSendLog.objects.filter(recipient=email, sent_at__gte=hour_ago).count() >= _recipient_hourly_max():
            logger.info('邮件防刷：%s 每小时上限已满，跳过 %s', email, kind)
            continue

        if EmailSendLog.objects.filter(recipient=email, sent_at__gte=day_start).count() >= _recipient_daily_max():
            logger.info('邮件防刷：%s 今日上限已满，跳过 %s', email, kind)
            continue

        if dedupe_key and EmailSendLog.objects.filter(
            dedupe_key=dedupe_key,
            recipient=email,
            sent_at__gte=cooldown_since,
        ).exists():
            logger.info('邮件防刷：%s 冷却中（%s），跳过', dedupe_key, kind)
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
    cutoff = timezone.now() - timedelta(days=7)
    EmailSendLog.objects.filter(sent_at__lt=cutoff).delete()


def email_send_stats() -> dict:
    """今日发信统计（供服务器设置页展示）"""
    from .models import EmailSendLog

    day_start = _beijing_day_start()
    today_count = EmailSendLog.objects.filter(sent_at__gte=day_start).count()
    return {
        'server_daily_max': _daily_server_max(),
        'server_today': today_count,
        'recipient_hourly_max': _recipient_hourly_max(),
        'recipient_daily_max': _recipient_daily_max(),
        'dedupe_cooldown_minutes': _dedupe_cooldown_seconds() // 60,
    }
