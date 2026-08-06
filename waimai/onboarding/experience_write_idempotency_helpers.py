# 体验引导可写演示幂等（幂等第 11 步 · 80-8）

from __future__ import annotations

from django.http import HttpRequest


EXPERIENCE_MENU_WRITE_KEYS = (
    'create_menu_profile',
    'toggle_menu_item_listed',
    'toggle_menu_item_general',
    'toggle_menu_item_member',
    'toggle_menu_item_special',
    'activate_menu_profile',
    'delete_menu_profile',
)

EXPERIENCE_PRODUCT_WRITE_KEYS = (
    'add_dish',
    'edit_dish',
    'experience_demo_image_upload',
)


def _resolve_experience_actor(request: HttpRequest) -> str:
    """须先确保 session 已落库，避免首包 actor=anon、重试 actor=真实键不一致。"""
    if getattr(request.user, 'is_authenticated', False):
        return str(request.user.pk)
    if not request.session.session_key:
        request.session.save()
    return (request.session.session_key or 'anon')[:32]


def detect_experience_menu_write_action(request: HttpRequest) -> str | None:
    """识别体验商品页 · 清单相关写操作。"""
    for key in EXPERIENCE_MENU_WRITE_KEYS:
        if key in request.POST:
            return key
    return None


def detect_experience_products_write_action(request: HttpRequest) -> str | None:
    """识别体验商品页 · 商品相关写操作。"""
    if request.POST.get('experience_demo_image_upload') == '1':
        return 'experience_demo_image_upload'
    for key in ('add_dish', 'edit_dish'):
        if key in request.POST:
            return key
    return None


def detect_experience_dine_write_action(request: HttpRequest) -> str | None:
    """识别体验堂食页 · 桌台相关写操作。"""
    if request.POST.get('add_table') == '1':
        return 'add_table'
    if request.POST.get('table_batch_action') == '1':
        batch = (request.POST.get('batch_action') or 'unknown').strip()[:32]
        return f'table_batch_{batch}'
    for key in (
        'add_virtual_code',
        'virtual_batch_action',
        'open_share_order',
    ):
        if request.POST.get(key) == '1':
            return key
    return None


def run_experience_write_idempotent(
    request: HttpRequest,
    seller_id: str,
    action: str,
    execute,
):
    """
    体验引导写操作：同一 scope+键只执行一次，重复请求回放首次 HTTP 响应。
    无幂等键时仍直接 execute（与全站 run_idempotent 一致）。
    """
    from waimai.idempotency_helpers import idempotency_scope, run_idempotent

    action = (action or 'write').strip()[:64]
    actor = _resolve_experience_actor(request)
    scope = idempotency_scope('experience_write', seller_id, action, actor)
    return run_idempotent(request, scope, execute)
