# 服务员工作台 · 桌台看板（空闲/启用中、代客开台、专属加点码、翻台）

from __future__ import annotations

from django.http import HttpRequest

from waimai.models import ShopTable
from waimai.plugins.dining.table_bulk_helpers import sort_shop_tables
from waimai.plugins.dining.table_helpers import (
    build_addon_scan_path,
    close_table_session,
    ensure_addon_token,
    get_open_main_session_for_table,
    get_open_order_for_session,
    open_table_main_session,
)


def _addon_qr_data_url(scan_path: str, *, request: HttpRequest | None = None) -> str:
    """专属加点码二维码（服务员出示给客人扫）。"""
    if not scan_path:
        return ''
    from waimai.order_qr_helpers import build_order_qr_png_data_url

    url = scan_path
    if request and not scan_path.startswith('http'):
        url = request.build_absolute_uri(scan_path)
    return build_order_qr_png_data_url(url)


def build_waiter_table_board_context(
    seller_id: str, *, request: HttpRequest | None = None, shop_code: str = '',
) -> dict:
    """服务员 Tab 桌台看板数据；饮食插件未开时整块隐藏。"""
    from waimai.channel_helpers import dining_plugin_enabled

    if not dining_plugin_enabled(seller_id):
        return {'show_table_board': False, 'table_rows': []}

    from waimai.plugins.dining.waiter_table_order_helpers import build_waiter_table_order_board_url

    tables = sort_shop_tables(
        list(ShopTable.objects.filter(seller_id=seller_id, is_active=True)),
    )
    rows = []
    for table in tables:
        open_sess = get_open_main_session_for_table(table)
        is_busy = open_sess is not None
        addon_scan_path = ''
        addon_qr_data_url = ''
        can_close = False
        close_block_reason = ''
        if is_busy and open_sess:
            token = ensure_addon_token(open_sess)
            if token:
                addon_scan_path = build_addon_scan_path(seller_id, token)
                addon_qr_data_url = _addon_qr_data_url(addon_scan_path, request=request)
            ok_close, close_block_reason = waiter_can_close_table(open_sess)
            can_close = ok_close
        rows.append({
            'table_id': table.table_id,
            'table_number': table.table_number,
            'is_busy': is_busy,
            'can_open': not is_busy,
            'can_close': can_close,
            'close_block_reason': close_block_reason,
            'addon_scan_path': addon_scan_path,
            'addon_qr_data_url': addon_qr_data_url,
            'order_url': build_waiter_table_order_board_url(seller_id, table, shop_code),
            'state_label': '启用' if is_busy else '空闲',
        })
    return {'show_table_board': True, 'table_rows': rows}


def render_waiter_table_board_inner_html(
    request,
    *,
    seller_id: str,
    shop_code: str = '',
    can_operate: bool = False,
    form_action: str = '',
) -> str:
    """桌台看板内层 HTML（供静默刷新 / 定时轮询替换）。"""
    from django.template.loader import render_to_string

    ctx = build_waiter_table_board_context(
        seller_id, request=request, shop_code=shop_code,
    )
    ctx.update({
        'can_operate': can_operate,
        'form_action': form_action,
    })
    return render_to_string(
        'waimai/_shop_work_waiter_table_board_inner.html',
        ctx,
        request=request,
    )


def waiter_can_close_table(session) -> tuple[bool, str]:
    """空闲翻台：无进行中订单才可关。"""
    order = get_open_order_for_session(session)
    if order:
        return False, (
            f'本桌还有订单 {order.get_display_order_no()} 未完结，'
            f'请先「用餐完成」或处理订单后再翻台'
        )
    return True, ''


def waiter_open_table_for_guest(
    seller_id: str,
    table_id,
    *,
    operator,
) -> tuple[bool, str]:
    """服务员代客开台；仅空闲桌可开。"""
    from waimai.channel_helpers import dining_plugin_enabled

    if not dining_plugin_enabled(seller_id):
        return False, '饮食插件未启用，无法开台'

    table = ShopTable.objects.filter(
        table_id=table_id,
        seller_id=seller_id,
        is_active=True,
    ).first()
    if not table:
        return False, '桌台不存在或已停用'

    session, err = open_table_main_session(table)
    if not session:
        return False, err or '开台失败'

    from waimai.audit_helpers import write_audit_log

    write_audit_log(
        action_code='waiter_open_table',
        summary=f'服务员代客开台：{table.table_number}号桌',
        seller_id=seller_id,
        actor=operator,
    )
    return True, f'{table.table_number}号桌已开台，正在进入代客点菜…'


def waiter_close_table(
    seller_id: str,
    table_id,
    *,
    operator,
) -> tuple[bool, str]:
    """服务员手动翻台关桌。"""
    from waimai.channel_helpers import dining_plugin_enabled

    if not dining_plugin_enabled(seller_id):
        return False, '饮食插件未启用'

    table = ShopTable.objects.filter(
        table_id=table_id,
        seller_id=seller_id,
        is_active=True,
    ).first()
    if not table:
        return False, '桌台不存在或已停用'

    open_sess = get_open_main_session_for_table(table)
    if not open_sess:
        return False, f'{table.table_number}号桌当前空闲，无需翻台'

    ok, msg = waiter_can_close_table(open_sess)
    if not ok:
        return False, msg

    close_table_session(open_sess)

    from waimai.audit_helpers import write_audit_log

    write_audit_log(
        action_code='waiter_close_table',
        summary=f'服务员翻台关桌：{table.table_number}号桌',
        seller_id=seller_id,
        actor=operator,
    )
    return True, f'{table.table_number}号桌已翻台，恢复空闲'
