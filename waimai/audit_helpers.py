# A.12 操作审计与技术日志：写入、查询、清理、查看权限

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db.models import Q, QuerySet
from django.utils import timezone
from .time_helpers import now_local_wall

from .models import OperationAuditLog

# 操作审计默认保留半年
AUDIT_RETENTION_DAYS = 180

# 卖家后台「操作审计与技术日志」三个 Tab
AUDIT_VIEW_AUDIT = 'audit'
AUDIT_VIEW_TECH_RUNTIME = 'tech_runtime'
AUDIT_VIEW_TECH_ERROR = 'tech_error'
AUDIT_VIEW_CHOICES = (
    AUDIT_VIEW_AUDIT,
    AUDIT_VIEW_TECH_RUNTIME,
    AUDIT_VIEW_TECH_ERROR,
)
AUDIT_VIEW_LABELS = {
    AUDIT_VIEW_AUDIT: '操作审计',
    AUDIT_VIEW_TECH_RUNTIME: '普通技术日志',
    AUDIT_VIEW_TECH_ERROR: '错误与支付日志',
}

logger = logging.getLogger('waimai')
payment_logger = logging.getLogger('waimai.payment')


def client_ip_from_request(request) -> str:
    """从请求取来源 IP（白话：访客电脑地址）"""
    if request is None:
        return ''
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()[:64]
    return (request.META.get('REMOTE_ADDR') or '')[:64]


def write_audit_log(
    *,
    action_code: str,
    summary: str = '',
    seller_id: str = '',
    actor=None,
    actor_username: str = '',
    actor_role: str = '',
    action_label: str = '',
    target_type: str = '',
    target_id: str = '',
    result: str = 'ok',
    request=None,
    ip_address: str = '',
) -> OperationAuditLog | None:
    """写入一条操作审计；失败时只记技术日志，不打断业务"""
    try:
        if actor is not None:
            actor_username = actor_username or getattr(actor, 'username', '') or ''
            actor_role = actor_role or getattr(actor, 'role', '') or ''
            if not seller_id:
                role = getattr(actor, 'role', '')
                if role == 'seller':
                    seller_id = actor.username
                elif role in ('staff', 'waiter', 'kitchen', 'rider', 'manager'):
                    seller_id = getattr(actor, 'employer_seller_id', '') or ''

        if not action_label:
            labels = dict(OperationAuditLog.ACTION_CHOICES)
            action_label = labels.get(action_code, action_code)

        ip = (ip_address or client_ip_from_request(request))[:64]
        return OperationAuditLog.objects.create(
            seller_id=(seller_id or '')[:64],
            actor=actor if getattr(actor, 'pk', None) else None,
            actor_username=(actor_username or '')[:128],
            actor_role=(actor_role or '')[:16],
            action_code=action_code,
            action_label=(action_label or '')[:64],
            target_type=(target_type or '')[:32],
            target_id=str(target_id or '')[:64],
            summary=(summary or '')[:500],
            result=result if result in ('ok', 'fail') else 'ok',
            ip_address=ip,
        )
    except Exception:
        logger.exception('写入操作审计失败 action=%s', action_code)
        return None


def audit_order_status(
    *,
    order,
    actor=None,
    summary: str,
    request=None,
    result: str = 'ok',
) -> OperationAuditLog | None:
    """订单状态类操作的统一留痕"""
    return write_audit_log(
        action_code='order_status',
        summary=summary,
        seller_id=getattr(order, 'seller_id', '') or '',
        actor=actor,
        target_type='order',
        target_id=str(getattr(order, 'order_id', '') or ''),
        result=result,
        request=request,
    )


def purge_expired_audit_logs(retention_days: int = AUDIT_RETENTION_DAYS) -> int:
    """删除超过保留天数的操作审计；返回删除条数"""
    cutoff = now_local_wall() - timedelta(days=max(1, int(retention_days)))
    deleted, _ = OperationAuditLog.objects.filter(created_at__lt=cutoff).delete()
    return deleted


def query_audit_logs(
    *,
    seller_id: str,
    only_username: str | None = None,
    keyword: str = '',
    limit: int = 100,
) -> QuerySet:
    """按店查询操作审计；支持关键词搜索摘要、账号、动作等。"""
    purge_expired_audit_logs()
    qs = OperationAuditLog.objects.filter(seller_id=seller_id)
    if only_username:
        qs = qs.filter(actor_username=only_username)
    q = (keyword or '').strip()
    if q:
        qs = qs.filter(
            Q(summary__icontains=q)
            | Q(actor_username__icontains=q)
            | Q(action_label__icontains=q)
            | Q(action_code__icontains=q)
            | Q(ip_address__icontains=q)
        )
    return qs.order_by('-created_at')[: max(1, min(int(limit), 500))]


def parse_audit_view_params(get_params) -> dict:
    """解析审计页 Tab、范围、搜索词。"""
    view = (get_params.get('view') or AUDIT_VIEW_AUDIT).strip()
    if view not in AUDIT_VIEW_CHOICES:
        view = AUDIT_VIEW_AUDIT
    scope = (get_params.get('scope') or 'all').strip()
    return {
        'view': view,
        'scope': 'mine' if scope == 'mine' else 'all',
        'q': (get_params.get('q') or '').strip()[:128],
    }


def build_seller_audit_querystring(*, scope: str = 'all', q: str = '') -> str:
    """卖家操作留痕页网址参数（仅范围 + 搜索）。"""
    parts: list[str] = []
    if scope == 'mine':
        parts.append('scope=mine')
    text = (q or '').strip()
    if text:
        from urllib.parse import quote

        parts.append(f'q={quote(text)}')
    return ('?' + '&'.join(parts)) if parts else ''


def parse_tech_log_view_params(get_params) -> dict:
    """服务器设置 · 技术排错日志 Tab 与搜索。"""
    view = (get_params.get('view') or AUDIT_VIEW_TECH_RUNTIME).strip()
    if view not in (AUDIT_VIEW_TECH_RUNTIME, AUDIT_VIEW_TECH_ERROR):
        view = AUDIT_VIEW_TECH_RUNTIME
    return {
        'view': view,
        'q': (get_params.get('q') or '').strip()[:128],
    }


def build_tech_log_querystring(*, view: str, q: str = '') -> str:
    """拼技术排错日志页网址参数。"""
    parts: list[str] = []
    if view and view != AUDIT_VIEW_TECH_RUNTIME:
        parts.append(f'view={view}')
    text = (q or '').strip()
    if text:
        from urllib.parse import quote

        parts.append(f'q={quote(text)}')
    return ('?' + '&'.join(parts)) if parts else ''


def build_audit_view_querystring(params: dict, **overrides) -> str:
    """拼审计页网址参数（切换 Tab / 范围时保留其它条件）。"""
    merged = {
        'view': params.get('view') or AUDIT_VIEW_AUDIT,
        'scope': params.get('scope') or 'all',
        'q': (params.get('q') or '').strip(),
    }
    merged.update(overrides)
    parts: list[str] = []
    view = merged.get('view') or AUDIT_VIEW_AUDIT
    if view != AUDIT_VIEW_AUDIT:
        parts.append(f'view={view}')
    if merged.get('scope') == 'mine':
        parts.append('scope=mine')
    q = (merged.get('q') or '').strip()
    if q:
        from urllib.parse import quote

        parts.append(f'q={quote(q)}')
    return ('?' + '&'.join(parts)) if parts else ''


def filter_log_lines(lines: list[str], keyword: str = '') -> list[str]:
    """技术日志行内关键词过滤（大小写不敏感）。"""
    q = (keyword or '').strip().lower()
    if not q:
        return lines
    return [line for line in lines if q in line.lower()]


def read_tech_log_filtered(
    filename: str,
    keyword: str = '',
    max_lines: int = 200,
) -> list[str]:
    """读日志末尾若干行，再按关键词筛。"""
    return filter_log_lines(
        read_tech_log_tail(filename, max_lines),
        keyword,
    )


def can_view_all_shop_audit(user) -> bool:
    """店主（兼本店服务器管理员）可看本店全部操作审计"""
    return bool(user and getattr(user, 'is_authenticated', False) and user.role == 'seller')


def can_view_tech_logs(user) -> bool:
    """第一阶段：店主可看技术日志；授权维护人员待 J.6 落地后再开"""
    return can_view_all_shop_audit(user)


def log_dir() -> Path:
    """技术日志目录（不进 Git）"""
    path = Path(getattr(settings, 'YECAO_LOG_DIR', Path(settings.BASE_DIR) / 'logs'))
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_tech_log_tail(filename: str, max_lines: int = 200) -> list[str]:
    """读取某个技术日志文件末尾若干行；文件不存在则返回空列表"""
    path = log_dir() / filename
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        logger.exception('读取技术日志失败 file=%s', filename)
        return []
    lines = text.splitlines()
    return lines[-max(1, min(int(max_lines), 1000)):]


def log_payment_issue(message: str, *args, exc_info: bool = False) -> None:
    """支付相关问题写入技术日志（保留 90 天策略的那份文件）"""
    payment_logger.error(message, *args, exc_info=exc_info)


def log_runtime_error(message: str, *args, exc_info: bool = False) -> None:
    """一般运行错误写入技术日志"""
    logger.error(message, *args, exc_info=exc_info)
