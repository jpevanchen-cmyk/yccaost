# 发信：主邮箱优先，失败自动试备用；网页配置优先于 .env

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

logger = logging.getLogger('waimai')

ROUTE_PRIMARY = 'primary'
ROUTE_BACKUP = 'backup'


@dataclass(frozen=True)
class EmailConfig:
    host: str
    port: int
    username: str
    password: str
    use_tls: bool
    use_ssl: bool
    from_email: str
    route: str = ROUTE_PRIMARY


def list_email_configs(*, force_route: str = '') -> list[EmailConfig]:
    """
    返回按顺序尝试的发信配置。
    force_route=primary|backup 时只返回指定通道（测试用）。
    """
    db_configs = _load_configs_from_database()
    if db_configs:
        configs = db_configs
    else:
        env_cfg = _load_from_env()
        configs = [env_cfg] if env_cfg else []

    route = (force_route or '').strip().lower()
    if route == ROUTE_PRIMARY:
        return [c for c in configs if c.route == ROUTE_PRIMARY]
    if route == ROUTE_BACKUP:
        return [c for c in configs if c.route == ROUTE_BACKUP]
    return configs


def get_email_config() -> EmailConfig | None:
    """兼容旧调用：返回主邮箱配置"""
    for cfg in list_email_configs():
        if cfg.route == ROUTE_PRIMARY:
            return cfg
    configs = list_email_configs()
    return configs[0] if configs else None


def is_email_ready() -> bool:
    return bool(list_email_configs())


def _cfg_from_row(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    from_email: str,
    use_tls: bool,
    use_ssl: bool,
    route: str,
) -> EmailConfig | None:
    if not (host.strip() and user.strip() and password):
        return None
    return EmailConfig(
        host=host.strip(),
        port=int(port or 465),
        username=user.strip(),
        password=password,
        use_tls=bool(use_tls),
        use_ssl=bool(use_ssl) and not bool(use_tls),
        from_email=(from_email or user).strip(),
        route=route,
    )


def _load_configs_from_database() -> list[EmailConfig]:
    try:
        from .models import ServerEmailSettings

        row = ServerEmailSettings.objects.filter(singleton_id=1).first()
        if not row:
            return []
        configs: list[EmailConfig] = []
        primary = _cfg_from_row(
            host=row.smtp_host,
            port=row.smtp_port,
            user=row.smtp_user,
            password=row.smtp_password,
            from_email=row.from_email or row.smtp_user,
            use_tls=row.use_tls,
            use_ssl=row.use_ssl,
            route=ROUTE_PRIMARY,
        )
        if primary:
            configs.append(primary)
        if row.is_backup_configured():
            backup = _cfg_from_row(
                host=row.backup_smtp_host,
                port=row.backup_smtp_port,
                user=row.backup_smtp_user,
                password=row.backup_smtp_password,
                from_email=row.backup_from_email or row.backup_smtp_user,
                use_tls=row.backup_use_tls,
                use_ssl=row.backup_use_ssl,
                route=ROUTE_BACKUP,
            )
            if backup:
                configs.append(backup)
        return configs
    except Exception:
        return []


def _load_from_env() -> EmailConfig | None:
    host = getattr(settings, 'EMAIL_HOST', '') or ''
    user = getattr(settings, 'EMAIL_HOST_USER', '') or ''
    password = getattr(settings, 'EMAIL_HOST_PASSWORD', '') or ''
    if not (host and user and password):
        return None
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', '') or user
    return EmailConfig(
        host=host,
        port=int(getattr(settings, 'EMAIL_PORT', 465) or 465),
        username=user,
        password=password,
        use_tls=bool(getattr(settings, 'EMAIL_USE_TLS', False)),
        use_ssl=bool(getattr(settings, 'EMAIL_USE_SSL', True)),
        from_email=from_email.strip(),
        route=ROUTE_PRIMARY,
    )


def _send_with_config(cfg: EmailConfig, *, subject: str, message: str, recipients: list[str]) -> bool:
    connection = get_connection(
        host=cfg.host,
        port=cfg.port,
        username=cfg.username,
        password=cfg.password,
        use_tls=cfg.use_tls,
        use_ssl=cfg.use_ssl,
        timeout=getattr(settings, 'EMAIL_TIMEOUT', 10),
    )
    email = EmailMessage(
        subject=subject,
        body=message,
        from_email=cfg.from_email,
        to=recipients,
        connection=connection,
    )
    email.send(fail_silently=False)
    return True


def send_yecao_mail(
    *,
    subject: str,
    message: str,
    recipient_list: list[str],
    kind: str = 'generic',
    dedupe_key: str = '',
    force_route: str = '',
) -> bool:
    """统一发信：防刷检查后，主邮箱失败则自动试备用"""
    from .email_rate_limit_helpers import filter_recipients_by_rate_limit, record_email_sent

    recipients = [r.strip() for r in recipient_list if (r or '').strip()]
    if not recipients:
        return False
    recipients = filter_recipients_by_rate_limit(
        recipients, kind=kind, dedupe_key=dedupe_key,
    )
    if not recipients:
        return False

    configs = list_email_configs(force_route=force_route)
    if not configs:
        return False

    last_error = None
    for cfg in configs:
        try:
            _send_with_config(cfg, subject=subject, message=message, recipients=recipients)
            record_email_sent(
                recipients, kind=kind, dedupe_key=dedupe_key, sender_route=cfg.route,
            )
            if cfg.route == ROUTE_BACKUP:
                logger.warning('邮件已通过备用邮箱发出：%s', subject)
            return True
        except Exception as exc:
            last_error = exc
            logger.exception('邮件发送失败（%s）：%s', cfg.route, subject)

    if last_error is not None:
        logger.error('主备邮箱均发送失败：%s', subject)
    return False


def parse_recipient_list(raw: str) -> list[str]:
    """把逗号分隔的邮箱字符串拆成列表"""
    if not raw:
        return []
    text = raw.replace('；', ',').replace(';', ',').replace(' ', ',')
    return [e.strip() for e in text.split(',') if e.strip()]


def email_rate_limit_status() -> dict:
    """发信设置页展示用：今日已发数量与上限"""
    from .email_rate_limit_helpers import email_send_stats

    return email_send_stats()
