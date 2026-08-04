# 留言板视图（正式功能）

from __future__ import annotations

import json

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from waimai.owner_helpers import user_is_server_manager


def _wants_json(request) -> bool:
    if request.headers.get('X-YC-Guestbook') == '1':
        return True
    accept = (request.headers.get('Accept') or '').lower()
    return 'application/json' in accept


def _manager_required(view_fn):
    from functools import wraps

    from django.contrib.auth.decorators import login_required

    @login_required
    @wraps(view_fn)
    def _wrapped(request, *args, **kwargs):
        if user_is_server_manager(request.user):
            return view_fn(request, *args, **kwargs)
        messages.error(request, '需要服务器管理者权限')
        return redirect('home')
    return _wrapped


@require_POST
@csrf_protect
def guestbook_post(request):
    """服务器主页「联系我们」提交留言（支持 Ajax JSON）"""
    from .guestbook_helpers import apply_guestbook_actor_cookie, post_guestbook_message

    ok, payload = post_guestbook_message(
        request,
        body=request.POST.get('body') or '',
        guest_name=request.POST.get('guest_name') or '',
        guest_email=request.POST.get('guest_email') or '',
        guest_password=request.POST.get('guest_password') or '',
    )

    if _wants_json(request):
        if ok:
            resp = JsonResponse({'ok': True, **payload})
        else:
            resp = JsonResponse({'ok': False, 'error': payload.get('error', '提交失败')}, status=400)
        return apply_guestbook_actor_cookie(request, resp)

    if ok:
        messages.success(request, payload.get('message') or '留言已提交')
    else:
        messages.error(request, payload.get('error') or '提交失败')
    anchor = (request.POST.get('return_anchor') or 'block-contact_us').strip()
    response = redirect(f'/#{anchor}')
    return apply_guestbook_actor_cookie(request, response)


@require_http_methods(['GET', 'POST'])
@csrf_protect
def guestbook_thread_public(request, public_code: str):
    """访客按编号查看留言并继续沟通"""
    from .guestbook_code_helpers import normalize_public_code
    from .guestbook_helpers import (
        get_guestbook_settings,
        guest_reply_thread,
        is_thread_unlocked,
        mark_thread_unlocked,
        update_guestbook_email,
        verify_guest_password,
    )
    from .guestbook_models import GuestbookMessage, GuestbookThread
    from .guestbook_ui_helpers import guestbook_thread_page_ui

    code = normalize_public_code(public_code)
    thread = get_object_or_404(GuestbookThread, public_code=code)
    settings_obj = get_guestbook_settings()
    need_password = thread.has_view_password and not is_thread_unlocked(request, thread)
    password_error = ''

    if request.method == 'POST':
        if 'unlock_password' in request.POST:
            pwd = request.POST.get('view_password') or ''
            if verify_guest_password(thread, pwd):
                mark_thread_unlocked(request, thread)
                need_password = False
            else:
                password_error = '密码不正确，请重试'
        elif 'guest_reply' in request.POST and not need_password:
            ok, msg = guest_reply_thread(request, thread, body=request.POST.get('body') or '')
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
            return redirect('guestbook_thread_public', public_code=code)
        elif 'update_guest_email' in request.POST and not need_password:
            ok, msg = update_guestbook_email(
                request, thread, request.POST.get('guest_email') or '',
            )
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
            return redirect('guestbook_thread_public', public_code=code)

    messages_list = []
    page_ui = {'notice': '', 'notice_level': '', 'show_email_update': False}
    if not need_password:
        messages_list = list(
            GuestbookMessage.objects.filter(thread=thread).order_by('created_at')
        )
        page_ui = guestbook_thread_page_ui(thread)

    return render(request, 'waimai/guestbook/thread_public.html', {
        'thread': thread,
        'messages_list': messages_list,
        'guestbook_settings': settings_obj,
        'need_password': need_password,
        'password_error': password_error,
        'thread_notice': page_ui.get('notice', ''),
        'thread_notice_level': page_ui.get('notice_level', ''),
        'show_email_update': page_ui.get('show_email_update', False),
        'home_url': '/',
    })


@require_POST
@csrf_protect
def guestbook_open_search(request):
    """留言板内按编号搜索跳转"""
    from .guestbook_code_helpers import is_valid_public_code_format, normalize_public_code

    code = normalize_public_code(request.POST.get('public_code') or '')
    if not code:
        messages.error(request, '请输入留言编号')
        return redirect('/#block-contact_us')
    if not is_valid_public_code_format(code):
        messages.error(request, '留言编号格式不正确，应为 YC-月日-8位字母数字')
        return redirect('/#block-contact_us')
    from .guestbook_models import GuestbookThread

    if not GuestbookThread.objects.filter(public_code=code).exists():
        messages.error(request, '找不到该留言编号，请核对是否输入正确')
        return redirect('/#block-contact_us')
    return redirect('guestbook_thread_public', public_code=code)


@_manager_required
def server_settings_guestbook(request):
    """留言列表与联系我们设置"""
    from .guestbook_helpers import get_guestbook_settings
    from .guestbook_models import GuestbookThread

    settings_obj = get_guestbook_settings()
    if request.method == 'POST':
        if 'save_contact_settings' in request.POST:
            settings_obj.public_display_name = (request.POST.get('public_display_name') or '')[:80]
            settings_obj.public_contact_email = (request.POST.get('public_contact_email') or '')[:254]
            settings_obj.block_intro = request.POST.get('block_intro') or ''
            settings_obj.save()
            messages.success(request, '联系我们信息已保存')
            return redirect('server_settings_guestbook')

    threads = list(GuestbookThread.objects.all()[:200])
    unread = sum(1 for t in threads if t.owner_unread)
    return render(request, 'waimai/owner/guestbook_inbox.html', {
        'section': 'guestbook',
        'guestbook_settings': settings_obj,
        'threads': threads,
        'unread_count': unread,
    })


@_manager_required
def server_settings_guestbook_thread(request, public_code: str):
    from .guestbook_helpers import owner_reply_thread
    from .guestbook_models import GuestbookMessage, GuestbookThread

    thread = get_object_or_404(GuestbookThread, public_code=public_code)
    if request.method == 'POST' and 'owner_reply' in request.POST:
        ok, msg = owner_reply_thread(
            thread,
            body=request.POST.get('body') or '',
            manager_user=request.user,
        )
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('server_settings_guestbook_thread', public_code=thread.public_code)

    if request.method == 'POST' and 'mark_email_suspect' in request.POST:
        thread.email_delivery_suspect = request.POST.get('email_suspect') == '1'
        thread.save(update_fields=['email_delivery_suspect'])
        messages.success(request, '邮箱标记已更新')
        return redirect('server_settings_guestbook_thread', public_code=thread.public_code)

    thread.owner_read_at = timezone.now()
    thread.save(update_fields=['owner_read_at'])
    messages_list = list(GuestbookMessage.objects.filter(thread=thread).order_by('created_at'))
    return render(request, 'waimai/owner/guestbook_thread.html', {
        'section': 'guestbook',
        'thread': thread,
        'messages_list': messages_list,
    })
