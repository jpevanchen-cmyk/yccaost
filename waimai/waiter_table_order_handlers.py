# 服务员代客点菜页 · 进入校验与上下文

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect

from waimai.models import ShopProfile
from waimai.plugins.dining.table_helpers import get_open_order_for_session
from waimai.plugins.dining.waiter_table_order_helpers import (
    bind_waiter_table_order_session,
    build_waiter_table_order_path,
    resolve_waiter_table_for_order,
)
from waimai.shop_work_helpers import build_shop_work_path


def prepare_waiter_table_order_page(
    request,
    *,
    shop_code: str,
    table_id,
    work_user,
    auto_open_if_idle: bool = False,
) -> tuple[dict | None, redirect | None]:
    """校验权限并绑定桌台；成功返回 shop 页 extra，失败返回 redirect。"""
    from waimai.shop_work_auth import user_belongs_to_shop
    from waimai.staff_account_helpers import PERM_DINING_WAITER, staff_has_permission

    shop_profile = ShopProfile.objects.filter(shop_code__iexact=(shop_code or '').strip()).first()
    if not shop_profile:
        return None, redirect('directory')

    seller_id = shop_profile.seller_id
    code = (shop_profile.shop_code or '').strip()

    if not work_user or not user_belongs_to_shop(work_user, seller_id):
        messages.error(request, '请先登录本店工作台')
        return None, redirect(build_shop_work_path(code, view='waiter'))

    if not staff_has_permission(work_user, PERM_DINING_WAITER):
        messages.error(request, '您没有服务员代客点菜权限')
        return None, redirect(build_shop_work_path(code, view='waiter'))

    table, err = resolve_waiter_table_for_order(
        seller_id, table_id, auto_open_if_idle=auto_open_if_idle,
    )
    if not table:
        messages.error(request, err or '无法进入代客点菜')
        return None, redirect(build_shop_work_path(code, view='waiter'))

    open_sess, bind_err = bind_waiter_table_order_session(
        request,
        seller_id,
        table,
        operator_username=work_user.username,
        shop_code=code,
    )
    if not open_sess:
        messages.error(request, bind_err or '绑定桌台失败')
        return None, redirect(build_shop_work_path(code, view='waiter'))

    open_order = get_open_order_for_session(open_sess)
    return {
        'waiter_table_order_mode': True,
        'waiter_table_number': table.table_number,
        'waiter_return_url': build_shop_work_path(code, view='waiter'),
        'waiter_table_order_url': build_waiter_table_order_path(code, table.table_id),
        'waiter_table_open_order': open_order,
        'shop_work_code': code,
    }, None
