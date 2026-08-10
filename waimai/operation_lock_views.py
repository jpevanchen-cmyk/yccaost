# V1 操作锁 · 解锁与手动锁定

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .operation_lock_helpers import (
    manual_operation_lock,
    operation_lock_is_engaged,
    site_operation_lock_enabled,
    unlock_operation_lock,
)
from .owner_helpers import user_is_server_manager


def _safe_next_path(request) -> str:
    nxt = (request.GET.get('next') or request.POST.get('next') or '').strip()
    if nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return ''


def _wants_json_response(request) -> bool:
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return True
    if request.POST.get('ajax') == '1':
        return True
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept


@never_cache
@require_http_methods(['GET', 'POST'])
def operation_lock_unlock(request):
    """操作锁解锁（遮罩 Ajax 或备用整页）。"""
    if not site_operation_lock_enabled():
        nxt = _safe_next_path(request)
        if _wants_json_response(request):
            return JsonResponse({'ok': True, 'message': '操作锁未启用'})
        return redirect(nxt or 'seller_panel')

    user = request.user
    if not getattr(user, 'is_authenticated', False):
        if _wants_json_response(request):
            return JsonResponse({'ok': False, 'message': '请先登录'}, status=401)
        return redirect('login')

    next_path = _safe_next_path(request) or '/seller-panel/orders/'

    if request.method == 'POST':
        pin = (request.POST.get('pin') or '').strip()
        ok, msg = unlock_operation_lock(request, pin)
        from .audit_helpers import write_audit_log

        seller_id = ''
        if getattr(user, 'role', '') == 'seller':
            seller_id = user.username
        write_audit_log(
            action_code='operation_lock',
            summary='操作锁解锁成功' if ok else '操作锁解锁失败：PIN 不正确',
            seller_id=seller_id,
            actor=user,
            result='ok' if ok else 'fail',
            request=request,
        )
        if _wants_json_response(request):
            if ok:
                return JsonResponse({'ok': True, 'message': msg})
            return JsonResponse({'ok': False, 'message': msg}, status=400)
        if ok:
            messages.success(request, msg)
            return redirect(next_path)
        messages.error(request, msg)

    if request.method == 'GET' and not operation_lock_is_engaged(request):
        return redirect(next_path)

    return render(
        request,
        'waimai/operation_lock_unlock.html',
        {
            'next_path': next_path,
            'is_seller': getattr(user, 'role', '') == 'seller',
            'is_manager': user_is_server_manager(user),
        },
    )


@login_required
@require_POST
def operation_lock_manual(request):
    """手动立即锁定；刷新当前页并显示遮罩。"""
    if not site_operation_lock_enabled():
        return redirect('seller_panel')
    user = request.user
    if getattr(user, 'role', '') != 'seller':
        return redirect('seller_panel')
    manual_operation_lock(request)
    from .audit_helpers import write_audit_log

    write_audit_log(
        action_code='operation_lock',
        summary='手动锁定店铺管理',
        seller_id=user.username,
        actor=user,
        request=request,
    )
    messages.info(request, '已锁定，请输入操作 PIN 继续。')
    nxt = _safe_next_path(request)
    if not nxt:
        referer = (request.META.get('HTTP_REFERER') or '').strip()
        if referer.startswith('/') and not referer.startswith('//'):
            from urllib.parse import urlparse

            nxt = urlparse(referer).path or '/seller-panel/orders/'
        else:
            nxt = '/seller-panel/orders/'
    return redirect(nxt)


@login_required
@require_http_methods(['GET', 'POST'])
def operation_lock_touch(request):
    """前端报平安：延长操作锁解锁状态（不算登出）。"""
    from .operation_lock_helpers import (
        operation_lock_is_engaged,
        request_user_subject_to_operation_lock,
        touch_operation_lock_activity,
    )

    if (
        site_operation_lock_enabled()
        and request_user_subject_to_operation_lock(request)
        and not operation_lock_is_engaged(request)
    ):
        touch_operation_lock_activity(request)
    return JsonResponse({'ok': True})
