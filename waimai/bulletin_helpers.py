# 整机公告：现行正文唯一真源；历史是改过之后的留痕（与大厅积木分开）。

from __future__ import annotations

from .time_helpers import now_local_wall


def get_bulletin():
    """整机公告现行行（没有就建空的）。"""
    from .models import ServerBulletin

    obj, _ = ServerBulletin.objects.get_or_create(
        singleton_id=1,
        defaults={'body': '', 'revision': 0},
    )
    return obj


def bulletin_public_state() -> dict:
    """给顶栏按钮和大厅弹窗用。"""
    from django.db.utils import OperationalError, ProgrammingError

    try:
        obj = get_bulletin()
        history_n = obj.history_rows.count()
    except (OperationalError, ProgrammingError):
        return {
            'show_header_button': False,
            'popup_body': '',
            'popup_revision': 0,
        }
    body = (obj.body or '').strip()
    return {
        'show_header_button': bool(body) or history_n > 0,
        'popup_body': body,
        'popup_revision': int(obj.revision or 0) if body else 0,
    }


def list_bulletin_history():
    """历史从新到旧。"""
    from django.db.utils import OperationalError, ProgrammingError

    try:
        return list(get_bulletin().history_rows.all())
    except (OperationalError, ProgrammingError):
        return []


def save_bulletin_body(raw_body: str) -> str:
    """
    保存现行公告。正文没变则不写历史（可安全重试）。
    返回给人看的结果说明。
    """
    from .models import ServerBulletinHistory

    new_body = (raw_body or '').strip()
    obj = get_bulletin()
    old_body = (obj.body or '').strip()
    if new_body == old_body:
        return '内容没有变化，未重复记录。'
    now = now_local_wall()
    if old_body:
        ServerBulletinHistory.objects.create(
            bulletin=obj,
            body=old_body,
            revision=int(obj.revision or 0),
            archived_at=now,
        )
    obj.body = new_body
    obj.revision = int(obj.revision or 0) + 1
    obj.published_at = now if new_body else None
    obj.save(update_fields=['body', 'revision', 'published_at', 'updated_at'])
    if new_body:
        return '整机公告已更新。客人进大厅时会弹一次最新内容。'
    return '已清空现行公告。历史仍可在「公告」按钮里查看。'
