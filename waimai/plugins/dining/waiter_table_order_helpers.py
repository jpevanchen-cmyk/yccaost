# 服务员代客点菜（工作台 · 绑桌堂食 · B 阶段）

from __future__ import annotations

from django.http import HttpRequest
from django.urls import reverse

from waimai.models import ShopTable
from waimai.plugins.dining.buyer_entry import bind_buyer_table_session
from waimai.plugins.dining.table_helpers import (
    get_open_main_session_for_table,
    open_table_main_session,
)


def waiter_table_order_session_key(seller_id: str) -> str:
    """标记当前浏览器处于服务员代客点菜模式（便于下单口识别）。"""
    return f'waiter_table_order_{seller_id}'


def activate_waiter_table_order(
    request: HttpRequest,
    seller_id: str,
    *,
    table_id,
    operator_username: str,
    page_url: str = '',
) -> None:
    request.session[waiter_table_order_session_key(seller_id)] = {
        'table_id': str(table_id),
        'operator': (operator_username or '').strip(),
    }
    if page_url:
        request.session[f'waiter_table_order_page_url_{seller_id}'] = page_url
    request.session.modified = True


def clear_waiter_table_order(request: HttpRequest, seller_id: str) -> None:
    for key in (
        waiter_table_order_session_key(seller_id),
        f'waiter_table_order_page_url_{seller_id}',
    ):
        if key in request.session:
            request.session.pop(key, None)
    request.session.modified = True


def get_waiter_table_order_page_url(request: HttpRequest, seller_id: str) -> str:
    return (request.session.get(f'waiter_table_order_page_url_{seller_id}') or '').strip()


def get_waiter_table_order_meta(request: HttpRequest, seller_id: str) -> dict | None:
    raw = request.session.get(waiter_table_order_session_key(seller_id))
    return raw if isinstance(raw, dict) else None


def is_waiter_table_order_active(request: HttpRequest, seller_id: str) -> bool:
    return bool(get_waiter_table_order_meta(request, seller_id))


def build_waiter_table_order_path(shop_code: str, table_id) -> str:
    return reverse(
        'shop_work_waiter_table_order',
        kwargs={'shop_code': (shop_code or '').strip(), 'table_id': table_id},
    )


def resolve_waiter_table_for_order(
    seller_id: str,
    table_id,
    *,
    auto_open_if_idle: bool = False,
) -> tuple[ShopTable | None, str]:
    """取实体桌；可选在空闲时自动开台。"""
    table = ShopTable.objects.filter(
        table_id=table_id,
        seller_id=seller_id,
        is_active=True,
    ).first()
    if not table:
        return None, '桌台不存在或已停用'
    if get_open_main_session_for_table(table):
        return table, ''
    if auto_open_if_idle:
        session, err = open_table_main_session(table)
        if session:
            return table, ''
        return None, err or '开台失败'
    return None, '该桌尚未开台，请先代客开台'


def bind_waiter_table_order_session(
    request: HttpRequest,
    seller_id: str,
    table: ShopTable,
    *,
    operator_username: str,
    shop_code: str = '',
) -> tuple[object | None, str]:
    """绑定桌台会话 + 堂食通道 + 服务员代点标记。"""
    open_sess = get_open_main_session_for_table(table)
    if not open_sess:
        return None, '该桌尚未开台'
    bind_buyer_table_session(request, seller_id, open_sess)
    page_url = build_waiter_table_order_board_url(seller_id, table, shop_code)
    activate_waiter_table_order(
        request,
        seller_id,
        table_id=table.table_id,
        operator_username=operator_username,
        page_url=page_url,
    )
    return open_sess, ''


def build_waiter_table_order_board_url(seller_id: str, table: ShopTable, shop_code: str) -> str:
    """看板用：进入代客点菜页。"""
    if not (shop_code or '').strip():
        from waimai.models import ShopProfile

        profile = ShopProfile.objects.filter(seller_id=seller_id).first()
        shop_code = (profile.shop_code or '').strip() if profile else ''
    if not shop_code:
        return ''
    return build_waiter_table_order_path(shop_code, table.table_id)
