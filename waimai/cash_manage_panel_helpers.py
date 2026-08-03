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
