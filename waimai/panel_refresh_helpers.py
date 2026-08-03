# 全站静默刷新（进度 80）：Panel 请求识别与统一 JSON 响应

from __future__ import annotations

from django.http import HttpRequest, JsonResponse

# 与前端 panel_refresh.js 一致
PANEL_REQUEST_HEADER = 'YecaoPanel'


def is_panel_refresh(request: HttpRequest) -> bool:
    """是否为 Panel 局部刷新请求（Ajax POST）"""
    value = (request.headers.get('X-Requested-With') or '').strip()
    if not value:
        value = (request.META.get('HTTP_X_REQUESTED_WITH') or '').strip()
    return value == PANEL_REQUEST_HEADER


def panel_refresh_ok(
    *,
    html: str = '',
    message: str = '',
    panel_id: str = '',
    extra: dict | None = None,
) -> JsonResponse:
    """Panel 成功：替换局部 HTML + 可选白话提示"""
    payload: dict = {
        'ok': True,
        'html': html,
        'message': message or '',
        'panel_id': panel_id or '',
    }
    if extra:
        payload.update(extra)
    return JsonResponse(payload)


def panel_refresh_fail(message: str, *, status: int = 400) -> JsonResponse:
    """Panel 失败：白话说明，不改页面 DOM"""
    text = (message or '操作未成功，请稍后再试').strip()
    return JsonResponse({'ok': False, 'message': text}, status=status)
