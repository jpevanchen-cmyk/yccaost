# 页面操作通知：展示一次即失效（进度 83 · 手机/电脑同一套）

from __future__ import annotations

import hashlib
import json
import uuid

from django.contrib import messages

SESSION_CONSUMED_KEY = 'yc_consumed_notice_ids'
SESSION_PENDING_KEY = 'yc_pending_notices'
MAX_CONSUMED = 200
MAX_PENDING = 30


def _notice_id(level: str, text: str) -> str:
    raw = f'{level}|{text}'.encode('utf-8', errors='replace')
    return hashlib.sha256(raw).hexdigest()[:24]


def flash_notice(request, level: str, text: str, *, must_ack: bool | None = None) -> None:
    """写入待展示通知（带唯一 id，消费后不再出现）。"""
    level = (level or 'ok').strip().lower()
    text = (text or '').strip()
    if not text:
        return
    if must_ack is None:
        must_ack = level in ('error', 'warning', 'warn')
    pending = list(request.session.get(SESSION_PENDING_KEY) or [])
    item = {
        'id': str(uuid.uuid4()),
        'level': level,
        'text': text,
        'mustAck': bool(must_ack),
    }
    pending.append(item)
    request.session[SESSION_PENDING_KEY] = pending[-MAX_PENDING:]
    request.session.modified = True


def flash_notice_from_message(request, message) -> None:
    """把 Django message 转成带 id 的待展示通知（同文案同 id，避免重复弹出）。"""
    tags = (message.tags or 'ok').split()[-1] if message.tags else 'ok'
    text = str(message)
    level = tags
    if not text:
        return
    must_ack = level in ('error', 'warning', 'warn')
    pending = list(request.session.get(SESSION_PENDING_KEY) or [])
    item = {
        'id': _notice_id(level, text),
        'level': level,
        'text': text,
        'mustAck': bool(must_ack),
    }
    pending.append(item)
    request.session[SESSION_PENDING_KEY] = pending[-MAX_PENDING:]
    request.session.modified = True


def collect_page_notices(request) -> list[dict]:
    """
    取出本页应展示的通知并标记已消费。
    同时吸收 django.contrib.messages 里尚未处理的条目。
    """
    consumed = set(request.session.get(SESSION_CONSUMED_KEY) or [])
    pending = list(request.session.get(SESSION_PENDING_KEY) or [])
    request.session[SESSION_PENDING_KEY] = []

    for message in messages.get_messages(request):
        flash_notice_from_message(request, message)

    pending = list(request.session.get(SESSION_PENDING_KEY) or [])
    request.session[SESSION_PENDING_KEY] = []

    out: list[dict] = []
    for item in pending:
        nid = item.get('id') or _notice_id(item.get('level', ''), item.get('text', ''))
        if nid in consumed:
            continue
        consumed.add(nid)
        out.append({
            'level': item.get('level') or 'ok',
            'text': item.get('text') or '',
            'mustAck': bool(item.get('mustAck')),
        })

    request.session[SESSION_CONSUMED_KEY] = list(consumed)[-MAX_CONSUMED:]
    request.session.modified = True
    return out


def page_notices_json(request) -> str:
    """供模板 yc_notice_boot 使用。"""
    items = collect_page_notices(request)
    if not items:
        return ''
    return json.dumps(items, ensure_ascii=False)
