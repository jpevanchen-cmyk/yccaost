# 本机控制台问店内地址：与堂食营业同一套测号/写入，仅允许本机访问

from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .lan_base_helpers import (
    apply_detected_lan_base_url,
    compare_saved_and_detected,
    json_lan_payload,
    lan_sync_ui_allowed,
    request_is_loopback,
)
from .owner_helpers import get_site_settings
from .v1_local_helpers import v1_local_mode_enabled


def _deny(message: str, status: int = 403):
    """拒绝时返回人话。"""
    return json_lan_payload({'ok': False, 'message': message}, status=status)


def _decorate_snapshot(payload: dict) -> dict:
    """补上控制台还要的字段，与堂食对比结果同一份真源。"""
    site = get_site_settings()
    payload['ok'] = payload.get('ok', True)
    payload['lan_base_url'] = payload.get('saved_lan') or ''
    payload['lan_message'] = payload.get('message') or ''
    payload['setup_completed'] = bool(site.v1_setup_completed)
    payload['v1_local_mode'] = v1_local_mode_enabled()
    return payload


@never_cache
@csrf_exempt
@require_http_methods(['GET', 'POST'])
def v1_tray_lan(request):
    """
    GET：对比已保存 / 当前探测（与堂食「检测当前 IP」同一套）。
    POST：把当前探测写入堂食真源（与堂食「一键更新」同一套）。
    只接受本机访问。
    """
    if not request_is_loopback(request):
        return _deny('只能在装野草的这台电脑上使用。')
    if not lan_sync_ui_allowed(request):
        return _deny('当前环境不提供本机控制台更新店内地址。')

    if request.method == 'GET':
        payload = compare_saved_and_detected()
        payload['ok'] = True
        return json_lan_payload(_decorate_snapshot(payload))

    ok, msg, payload = apply_detected_lan_base_url()
    payload['ok'] = ok
    payload['message'] = msg
    status = 200 if ok else 400
    return json_lan_payload(_decorate_snapshot(payload), status=status)
