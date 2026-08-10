# 写操作幂等（进度 80 · 幂等第 1 步）：全站共用零件
# 用法：run_idempotent(request, scope, lambda: 真正改库的返回)
# 前端：YcIdempotency.newKey() + 请求头 Idempotency-Key 或表单 idempotency_key

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import timedelta

from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from .time_helpers import now_local_wall

from .models import IdempotencyRecord

# 与前端 idempotency_client.js 一致
IDEMPOTENCY_HEADER = 'Idempotency-Key'
IDEMPOTENCY_FORM_FIELD = 'idempotency_key'
DEFAULT_TTL = timedelta(hours=24)
PENDING_STALE = timedelta(seconds=60)
MAX_KEY_LEN = 128
_KEY_PATTERN = re.compile(r'^[A-Za-z0-9._-]{8,128}$')
_REDIRECT_KIND = '_yc_idempotency_redirect'


def extract_idempotency_key(request: HttpRequest) -> str:
    """从请求头或 POST 字段读取幂等键；无效或缺失返回空字符串。"""
    raw = (request.headers.get(IDEMPOTENCY_HEADER) or '').strip()
    if not raw:
        raw = (request.POST.get(IDEMPOTENCY_FORM_FIELD) or '').strip()
    if not raw or len(raw) > MAX_KEY_LEN:
        return ''
    if not _KEY_PATTERN.match(raw):
        return ''
    return raw


def idempotency_scope(*parts: str) -> str:
    """拼作用域字符串，供不同业务隔离同名键。"""
    cleaned = [p.strip() for p in parts if (p or '').strip()]
    return ':'.join(cleaned)[:128]


def _default_expires_at():
    return now_local_wall() + DEFAULT_TTL


def _is_redirect_response(response: HttpResponse) -> bool:
    return (
        response.status_code in (301, 302, 303, 307, 308)
        and bool(response.get('Location'))
    )


def _replay_record(record: IdempotencyRecord) -> HttpResponse:
    """重复请求：返回已存响应（含整页跳转）。"""
    body = (record.response_body or '').strip()
    if body.startswith('{'):
        try:
            data = json.loads(body)
            if data.get('_yc_kind') == _REDIRECT_KIND:
                return HttpResponseRedirect(
                    data['location'],
                    status=record.response_status or 302,
                )
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    return HttpResponse(
        content=record.response_body,
        status=record.response_status,
        content_type='application/json; charset=utf-8',
    )


def _store_response(record: IdempotencyRecord, response: HttpResponse) -> None:
    if _is_redirect_response(response):
        payload = json.dumps({
            '_yc_kind': _REDIRECT_KIND,
            'location': response['Location'],
        }, ensure_ascii=False)
        record.response_body = payload
    else:
        charset = getattr(response, 'charset', None) or 'utf-8'
        record.response_body = response.content.decode(charset, errors='replace')
    record.state = IdempotencyRecord.STATE_COMPLETED
    record.response_status = response.status_code
    record.completed_at = now_local_wall()
    record.save(update_fields=[
        'state', 'response_status', 'response_body', 'completed_at',
    ])


def _pending_conflict_response() -> JsonResponse:
    return JsonResponse(
        {'ok': False, 'message': '相同操作正在处理，请稍候'},
        status=409,
    )


def run_idempotent(
    request: HttpRequest,
    scope: str,
    execute: Callable[[], HttpResponse],
) -> HttpResponse:
    """
    幂等守卫：无键则直接 execute；有键则同一 scope+键 只 execute 一次。
    重复请求返回首次成功时的同一 HTTP 响应。
    """
    key = extract_idempotency_key(request)
    if not key:
        return execute()

    scope = (scope or '').strip()[:128]
    now = now_local_wall()

    with transaction.atomic():
        try:
            record = (
                IdempotencyRecord.objects.select_for_update()
                .get(scope=scope, idempotency_key=key)
            )
        except IdempotencyRecord.DoesNotExist:
            record = None

        if record:
            if record.is_expired():
                record.delete()
                record = None
            elif record.state == IdempotencyRecord.STATE_COMPLETED:
                return _replay_record(record)
            elif record.state == IdempotencyRecord.STATE_PENDING:
                if now - record.created_at < PENDING_STALE:
                    return _pending_conflict_response()
                record.delete()
                record = None

        if record is None:
            record = IdempotencyRecord.objects.create(
                scope=scope,
                idempotency_key=key,
                state=IdempotencyRecord.STATE_PENDING,
                expires_at=_default_expires_at(),
            )

    try:
        response = execute()
    except Exception:
        IdempotencyRecord.objects.filter(
            pk=record.pk, state=IdempotencyRecord.STATE_PENDING,
        ).delete()
        raise

    with transaction.atomic():
        locked = IdempotencyRecord.objects.select_for_update().get(pk=record.pk)
        if locked.state == IdempotencyRecord.STATE_COMPLETED:
            return _replay_record(locked)
        _store_response(locked, response)
    return response
