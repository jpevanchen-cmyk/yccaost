# 现金管理 · Panel 局部刷新片段（进度 80 · 月份下拉不整页 reload）

from __future__ import annotations

from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse


def render_seller_cash_manage_panel_html(
    request: HttpRequest,
    seller_id: str,
) -> str:
    """卖家后台 · 现金管理 Panel 片段（#cash-manage-panel-body 内层）"""
    from .cash_manage_helpers import build_seller_cash_manage_context

    ctx = build_seller_cash_manage_context(seller_id, request=request)
    form_action = reverse('seller_panel_section', kwargs={'section': 'cash_manage'})
    ctx.update({
        'cash_manage_form_action': form_action,
        'cash_month_form_action': form_action,
        'cash_month_preserve_section': 'cash_manage',
        'cash_manage_link_mode': 'seller',
        'cash_manage_intro': '',
        'cash_panel_id': 'cash-manage-panel-body',
        'form_action': form_action,
    })
    return render_to_string('waimai/_cash_manage_fold_panels.html', ctx, request=request)


def render_workbench_cash_manage_panel_html(
    request: HttpRequest,
    seller_id: str,
    *,
    work_user,
    form_action: str,
) -> str:
    """店铺工作台 · 现金管理 Tab Panel 片段（#work-cash-manage-panel-body 内层）"""
    from .cash_manage_helpers import build_workbench_cash_manage_context

    ctx = build_workbench_cash_manage_context(
        seller_id, work_user=work_user, request=request,
    )
    ctx.update({
        'form_action': form_action,
        'cash_month_form_action': form_action,
        'cash_month_preserve_view': 'cash_manage',
        'cash_manage_link_mode': 'workbench',
        'cash_manage_intro': (
            '处理骑手交款与货到付款少收争议。确认收款、备货交付请在各岗位 Tab 操作。'
        ),
        'cash_panel_id': 'work-cash-manage-panel-body',
    })
    return render_to_string('waimai/_cash_manage_fold_panels.html', ctx, request=request)


def attach_seller_cash_manage_panel_ctx(
    request: HttpRequest,
    seller_id: str,
    *,
    redirect_to: str,
) -> None:
    """卖家后台 POST 前挂上现金管理 Panel 重渲染上下文"""
    request.cash_manage_panel_ctx = {
        'mode': 'seller',
        'seller_id': seller_id,
        'panel_id': 'cash-manage-panel-body',
        'work_user': request.user,
        'form_action': redirect_to,
    }


def _resolve_cash_manage_panel_ctx(request: HttpRequest) -> dict | None:
    """工作台 / 卖家后台共用：解析当前 Panel 上下文"""
    panel_ctx = getattr(request, 'cash_manage_panel_ctx', None)
    if panel_ctx:
        return panel_ctx
    shop_ctx = getattr(request, 'shop_work_panel_ctx', None)
    if shop_ctx and shop_ctx.get('view') == 'cash_manage':
        return {
            'mode': 'workbench',
            'seller_id': shop_ctx['seller_id'],
            'panel_id': 'work-cash-manage-panel-body',
            'work_user': shop_ctx['work_user'],
            'form_action': shop_ctx['form_action'],
        }
    return None


def render_cash_manage_panel_html_from_ctx(
    request: HttpRequest,
    panel_ctx: dict,
) -> str:
    """按上下文渲染现金管理 Panel HTML"""
    seller_id = panel_ctx['seller_id']
    if panel_ctx.get('mode') == 'workbench':
        return render_workbench_cash_manage_panel_html(
            request,
            seller_id,
            work_user=panel_ctx['work_user'],
            form_action=panel_ctx['form_action'],
        )
    return render_seller_cash_manage_panel_html(request, seller_id)


def respond_cash_manage_action(
    request: HttpRequest,
    redirect_to: str,
    *,
    ok: bool,
    message: str,
):
    """现金管理操作：Panel 请求走 JSON；否则 messages + redirect"""
    from django.contrib import messages
    from django.shortcuts import redirect

    from .panel_refresh_helpers import is_panel_refresh, panel_refresh_fail, panel_refresh_ok

    panel_ctx = _resolve_cash_manage_panel_ctx(request)
    if panel_ctx and is_panel_refresh(request):
        if not ok:
            return panel_refresh_fail(message)
        html = render_cash_manage_panel_html_from_ctx(request, panel_ctx)
        return panel_refresh_ok(
            html=html,
            message=message,
            panel_id=panel_ctx.get('panel_id') or '',
        )
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect(redirect_to)
