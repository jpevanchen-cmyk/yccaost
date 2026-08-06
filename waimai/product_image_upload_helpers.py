# 商品图 Ajax 单张上传幂等（幂等第 9 步 · 80-8）

from __future__ import annotations

from django.http import HttpRequest


def run_product_image_upload_idempotent(
    request: HttpRequest,
    seller_id: str,
    dish_id: str,
    execute,
):
    """
    卖家商品图 Ajax 上传：同一 scope+键只保存一张，重复请求返回首次 JSON。
    """
    from .idempotency_helpers import idempotency_scope, run_idempotent

    dish_id = (dish_id or '').strip()
    if getattr(request.user, 'is_authenticated', False):
        actor = str(request.user.pk)
    else:
        actor = (request.session.session_key or 'anon')[:32]
    scope = idempotency_scope('product_image_upload', seller_id, dish_id, actor)
    return run_idempotent(request, scope, execute)
