# 公开留言壁：大厅发帖 + 管理者藏/删/楼下说明

from __future__ import annotations

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .guestbook_helpers import apply_guestbook_actor_cookie
from .home_page_tier_helpers import community_page_anchor_url
from .owner_helpers import user_is_server_manager
from .public_wall_helpers import (
    create_public_wall_post,
    posted_wall_action,
    run_public_wall_post_idempotent,
)
from .public_wall_models import PublicWallPost


def _manager_required(view_fn):
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
def public_wall_post(request):
    """大厅公开墙发帖。连点同一编号只写一楼。"""

    def execute():
        ok, payload = create_public_wall_post(
            request,
            body=request.POST.get('body') or '',
            nickname=request.POST.get('nickname') or '',
            is_anonymous=request.POST.get('is_anonymous') == '1',
        )
        if ok:
            floor_no = getattr(payload, 'floor_no', '')
            messages.success(request, f'已贴上 {floor_no} 楼')
        else:
            messages.error(request, payload or '发帖失败')
        return redirect(community_page_anchor_url('block-public_wall'))

    response = run_public_wall_post_idempotent(request, execute)
    return apply_guestbook_actor_cookie(request, response)


@_manager_required
@csrf_protect
def server_settings_public_wall(request):
    """服务器设置 · 公开留言壁：看原文、隐藏/删除、楼下说明。"""
    from .public_wall_helpers import (
        build_public_wall_admin_context,
        moderate_public_wall_post,
        run_public_wall_mod_idempotent,
    )

    if request.method == 'POST':
        page_raw = (request.POST.get('page') or '1').strip() or '1'

        def execute():
            post = PublicWallPost.objects.filter(pk=request.POST.get('post_id') or '').first()
            if post is None:
                messages.error(request, '找不到这一楼')
                return redirect(_admin_redirect(page_raw))
            ok, msg = moderate_public_wall_post(
                post,
                action=posted_wall_action(request),
                note=request.POST.get('note') or '',
                signer_name=request.POST.get('signer') or '',
            )
            if ok:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
            return redirect(_admin_redirect(page_raw))

        return run_public_wall_mod_idempotent(request, execute)

    ctx = build_public_wall_admin_context(request)
    ctx['section'] = 'public_wall'
    return render(request, 'waimai/owner/public_wall_admin.html', ctx)


def _admin_redirect(page_raw: str):
    url = reverse('server_settings_public_wall')
    try:
        page_no = int(page_raw)
    except (TypeError, ValueError):
        page_no = 1
    if page_no > 1:
        return f'{url}?p={page_no}'
    return url
