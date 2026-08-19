# 本机隐私条款：看过条款的会话标记（注册闸门用）

from __future__ import annotations

SESSION_PRIVACY_VIEWED_KEY = 'yc_privacy_policy_viewed'


def mark_privacy_policy_viewed(request) -> None:
    """打开条款页后记下：本次浏览可以注册。"""
    if request is None:
        return
    request.session[SESSION_PRIVACY_VIEWED_KEY] = True
    request.session.modified = True


def privacy_policy_was_viewed(request) -> bool:
    if request is None:
        return False
    return bool(request.session.get(SESSION_PRIVACY_VIEWED_KEY))
