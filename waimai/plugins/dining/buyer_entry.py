# 饮食插件：买家扫桌码 / 虚拟码入口与浏览器桌台会话绑定

from django.shortcuts import redirect

from waimai.models import TableSession

from .table_helpers import (
    get_table_by_token,
    get_virtual_by_token,
    open_table_main_session,
    open_virtual_session,
)


def table_session_key(seller_id: str) -> str:
    """浏览器会话里存放本店桌台会话编号的键名。"""
    return f'table_session_{seller_id}'


def get_buyer_table_session(request, seller_id: str):
    """买家当前绑定的进行中桌台会话；无则 None。"""
    from waimai.plugin_runtime.registry import is_plugin_enabled

    if not is_plugin_enabled('dining', seller_id):
        return None
    raw = request.session.get(table_session_key(seller_id))
    if not raw:
        return None
    return TableSession.objects.filter(
        session_id=raw, seller_id=seller_id, status='open',
    ).select_related('shop_table', 'virtual_code').first()


def bind_buyer_table_session(request, seller_id: str, session: TableSession) -> None:
    """把桌台会话写入买家浏览器，进入店内点餐态。"""
    request.session[table_session_key(seller_id)] = str(session.session_id)
    request.session.modified = True


def dine_table_entry(request):
    """扫桌码/虚拟码入口：建立桌台会话后进入店铺点菜。"""
    seller_id = (request.GET.get('seller_id') or '').strip()
    t_token = (request.GET.get('t') or '').strip()
    v_token = (request.GET.get('v') or '').strip()
    if not seller_id:
        return redirect('directory')

    from waimai.plugin_runtime.registry import is_plugin_enabled

    if not is_plugin_enabled('dining', seller_id):
        return redirect(
            f'/shop/?seller_id={seller_id}&error=当前店铺未启用饮食插件，桌码入口不可用'
        )

    device_key = request.session.session_key or ''

    if t_token:
        table = get_table_by_token(seller_id, t_token)
        if not table:
            return redirect(f'/shop/?seller_id={seller_id}&error=桌码无效或已停用')
        session, err = open_table_main_session(table, device_key)
    elif v_token:
        code = get_virtual_by_token(seller_id, v_token)
        if not code:
            return redirect(f'/shop/?seller_id={seller_id}&error=虚拟桌码无效或已停用')
        session, err = open_virtual_session(code, device_key)
    else:
        return redirect(f'/shop/?seller_id={seller_id}')

    if err:
        return redirect(f'/shop/?seller_id={seller_id}&error={err}')
    if not session:
        return redirect(f'/shop/?seller_id={seller_id}&error=无法开台')

    bind_buyer_table_session(request, seller_id, session)
    return redirect(f'/shop/?seller_id={seller_id}')
