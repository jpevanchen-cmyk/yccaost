# 留言板 Ajax 新建主题幂等（幂等第 10 步 · 80-8）

from __future__ import annotations

from django.http import HttpRequest


def run_guestbook_post_idempotent(request: HttpRequest, execute):
    """
    主页留言板 Ajax 提交：同一 scope+键只建一条主题，重复请求回放首次 JSON。
    无键时仍走旧逻辑（含 2 分钟同内容去重）。
    """
    from .guestbook_rate_helpers import resolve_guestbook_actor
    from .idempotency_helpers import idempotency_scope, run_idempotent

    actor_key, _ = resolve_guestbook_actor(request)
    actor = (actor_key or 'anon')[:32]
    scope = idempotency_scope('guestbook_post', actor)
    return run_idempotent(request, scope, execute)
