# 操作锁设置：店铺管理内保存 PIN 与自动锁定时长

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect

from .operation_lock_helpers import (
    clear_operation_lock_pin,
    operation_lock_configured,
    operation_lock_idle_seconds,
    set_operation_lock_pin,
    verify_operation_lock_pin,
)
from .owner_helpers import get_site_settings


def _audit_operation_lock(request, summary: str, *, result: str = 'ok') -> None:
    from .audit_helpers import write_audit_log

    seller_id = ''
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False) and getattr(user, 'role', '') == 'seller':
        seller_id = user.username
    write_audit_log(
        action_code='operation_lock',
        summary=summary,
        seller_id=seller_id,
        actor=user if getattr(user, 'is_authenticated', False) else None,
        result=result,
        request=request,
    )


def operation_lock_settings_context():
    """店铺管理 · 操作锁分区模板上下文。"""
    site = get_site_settings()
    return {
        'site_settings': site,
        'lock_configured': operation_lock_configured(site),
        'idle_seconds': operation_lock_idle_seconds(site),
    }


def handle_operation_lock_settings_post(request):
    """处理操作锁设置表单；成功或失败后 redirect 回操作锁分区。"""
    site = get_site_settings()
    redirect_name = 'seller_panel_section'
    redirect_kwargs = {'section': 'operation_lock'}

    if request.POST.get('disable_lock') == '1':
        if operation_lock_configured(site):
            old_pin = (request.POST.get('old_pin') or '').strip()
            if not verify_operation_lock_pin(site, old_pin):
                messages.error(request, '旧 PIN 不正确，无法关闭操作锁。')
                return redirect(redirect_name, **redirect_kwargs)
        clear_operation_lock_pin(site)
        site.save(
            update_fields=[
                'operation_lock_enabled',
                'operation_lock_pin_salt',
                'operation_lock_pin_hash',
                'updated_at',
            ],
        )
        _audit_operation_lock(request, '操作锁已关闭')
        messages.success(request, '操作锁已关闭。')
        return redirect(redirect_name, **redirect_kwargs)

    enable = request.POST.get('operation_lock_enabled') == '1'
    new_pin = (request.POST.get('new_pin') or '').strip()
    confirm_pin = (request.POST.get('confirm_pin') or '').strip()
    old_pin = (request.POST.get('old_pin') or '').strip()
    try:
        idle_seconds = max(
            60,
            min(3600, int(request.POST.get('operation_lock_idle_seconds') or 300)),
        )
    except (TypeError, ValueError):
        idle_seconds = 300

    if operation_lock_configured(site):
        if not verify_operation_lock_pin(site, old_pin):
            messages.error(request, '旧 PIN 不正确。')
            return redirect(redirect_name, **redirect_kwargs)
    if enable:
        if len(new_pin) < 4:
            messages.error(request, '新 PIN 至少 4 位。')
            return redirect(redirect_name, **redirect_kwargs)
        if new_pin != confirm_pin:
            messages.error(request, '两次输入的新 PIN 不一致。')
            return redirect(redirect_name, **redirect_kwargs)
        set_operation_lock_pin(site, new_pin)
        site.operation_lock_enabled = True
    else:
        if operation_lock_configured(site):
            site.operation_lock_enabled = False
        else:
            clear_operation_lock_pin(site)
    site.operation_lock_idle_seconds = idle_seconds
    site.save(
        update_fields=[
            'operation_lock_enabled',
            'operation_lock_idle_seconds',
            'operation_lock_pin_salt',
            'operation_lock_pin_hash',
            'updated_at',
        ],
    )
    if enable:
        _audit_operation_lock(
            request,
            f'操作锁已启用，无操作 {idle_seconds} 秒后自动锁定',
        )
    elif operation_lock_configured(site):
        _audit_operation_lock(request, '操作锁已停用（PIN 仍保留）')
    else:
        _audit_operation_lock(request, '操作锁设置已保存')
    messages.success(request, '操作锁设置已保存。')
    return redirect(redirect_name, **redirect_kwargs)
