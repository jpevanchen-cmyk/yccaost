# 店铺工作台 Panel 局部刷新（进度 80-2b：后厨 / 服务员 / 订单台）

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.template.loader import render_to_string

from .panel_refresh_helpers import is_panel_refresh, panel_refresh_fail, panel_refresh_ok

PANEL_IDS = {
    'kitchen': 'work-kitchen-panel-body',
    'waiter': 'work-waiter-panel-body',
    'orders': 'work-orders-panel-body',
}


def attach_shop_work_panel_ctx(
    request: HttpRequest,
    *,
    seller_id: str,
    shop_code: str,
    view: str,
    work_user,
    sort_mode: str,
    form_action: str,
    redirect_to: str,
    can_operate_kitchen: bool = False,
    can_operate_waiter: bool = False,
) -> None:
    """POST 分发前挂上 Panel 重渲染所需上下文"""
    request.shop_work_panel_ctx = {
        'seller_id': seller_id,
        'shop_code': shop_code,
        'view': view,
        'work_user': work_user,
        'sort_mode': sort_mode,
        'form_action': form_action,
        'redirect_to': redirect_to,
        'panel_id': PANEL_IDS.get(view, ''),
        'can_operate_kitchen': can_operate_kitchen,
        'can_operate_waiter': can_operate_waiter,
    }


def render_workbench_panel_html(request: HttpRequest, panel_ctx: dict) -> str:
    """按当前 Tab 渲染 Panel 片段 HTML"""
    view = panel_ctx['view']
    seller_id = panel_ctx['seller_id']
    work_user = panel_ctx['work_user']
    sort_mode = panel_ctx.get('sort_mode') or 'newest'
    form_action = panel_ctx['form_action']

    from .dispatch_helpers import operator_can_manual_dispatch
    from .workbench_shell_helpers import build_workbench_shell

    workbench_shell = build_workbench_shell(seller_id)
    base = {
        'workbench_shell': workbench_shell,
        'form_action': form_action,
        'shop_work_code': panel_ctx['shop_code'],
        'work_user': work_user,
    }

    if view == 'kitchen':
        from .shop_work_helpers import build_kitchen_board_context

        ctx = build_kitchen_board_context(
            seller_id,
            allow_dispatch=operator_can_manual_dispatch(work_user, seller_id, 'kitchen'),
            sort_mode=sort_mode,
        )
        ctx.update(base)
        ctx['can_operate'] = bool(panel_ctx.get('can_operate_kitchen'))
        return render_to_string('waimai/_shop_work_kitchen_panel.html', ctx, request=request)

    if view == 'waiter':
        from .shop_work_helpers import build_waiter_board_context

        ctx = build_waiter_board_context(
            seller_id,
            allow_dispatch=operator_can_manual_dispatch(work_user, seller_id, 'waiter'),
            sort_mode=sort_mode,
        )
        ctx.update(base)
        ctx['can_operate'] = bool(panel_ctx.get('can_operate_waiter'))
        return render_to_string('waimai/_shop_work_waiter_panel.html', ctx, request=request)

    if view == 'orders':
        from .order_desk_helpers import build_order_desk_context

        ctx = build_order_desk_context(
            seller_id, work_user=work_user, sort_mode=sort_mode,
        )
        ctx.update(base)
        return render_to_string('waimai/_shop_work_orders_panel.html', ctx, request=request)

    return ''


def respond_workbench_action(
    request: HttpRequest,
    redirect_to: str,
    *,
    ok: bool,
    message: str,
) -> HttpResponse:
    """工作台操作：Panel 请求走 JSON；否则 messages + redirect"""
    panel_ctx = getattr(request, 'shop_work_panel_ctx', None)
    if panel_ctx and is_panel_refresh(request):
        if not ok:
            return panel_refresh_fail(message)
        html = render_workbench_panel_html(request, panel_ctx)
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
