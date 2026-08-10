# 饮食插件：买家扫桌码 / 加点码 / 虚拟码入口与浏览器桌台会话绑定

from django.shortcuts import redirect

from waimai.models import TableSession

from .table_helpers import (
    PHYSICAL_TABLE_BUSY_MSG,
    bind_addon_session,
    get_open_main_session_for_table,
    get_table_by_token,
    get_virtual_by_token,
    open_table_main_session,
    open_virtual_session,
)


def table_session_key(seller_id: str) -> str:
    """浏览器会话里存放本店桌台会话编号的键名。"""
    return f'table_session_{seller_id}'


def addon_token_session_key(seller_id: str) -> str:
    """浏览器会话里备份的专属加点码（桌台编号失效时可恢复绑定）。"""
    return f'dine_addon_token_{seller_id}'


def clear_buyer_table_session(request, seller_id: str) -> None:
    """清掉本店桌台会话与加点码备份。"""
    changed = False
    for key in (table_session_key(seller_id), addon_token_session_key(seller_id)):
        if key in request.session:
            request.session.pop(key, None)
            changed = True
    if changed:
        request.session.modified = True


def _try_recover_table_session_from_addon(request, seller_id: str) -> TableSession | None:
    """会话里若存了加点码，尝试重新绑定进行中主单。"""
    token = (request.session.get(addon_token_session_key(seller_id)) or '').strip()
    if not token:
        return None
    device_key = request.session.session_key or ''
    session, err = bind_addon_session(seller_id, token, device_key)
    if not session:
        if err:
            request.session.pop(addon_token_session_key(seller_id), None)
            request.session.modified = True
        return None
    bind_buyer_table_session(request, seller_id, session)
    return session


def get_buyer_table_session(request, seller_id: str):
    """买家当前绑定的进行中桌台会话；无则 None。失效 cookie 会清理并标记过期。"""
    from waimai.plugin_runtime.registry import is_plugin_enabled

    if not is_plugin_enabled('dining', seller_id):
        return None
    raw = request.session.get(table_session_key(seller_id))
    if raw:
        sess = TableSession.objects.filter(
            session_id=raw, seller_id=seller_id, status='open',
        ).select_related('shop_table', 'virtual_code').first()
        if sess:
            return sess
        clear_buyer_table_session(request, seller_id)
        request.yc_table_session_expired = True
    return _try_recover_table_session_from_addon(request, seller_id)


def bind_buyer_table_session(request, seller_id: str, session: TableSession) -> None:
    """把桌台会话写入买家浏览器，锁定堂食通道。"""
    from waimai.channel_helpers import CHANNEL_DINE_IN, set_channel_repick, set_shop_channel

    request.session[table_session_key(seller_id)] = str(session.session_id)
    if session.session_type == 'main' and (session.addon_token or '').strip():
        request.session[addon_token_session_key(seller_id)] = session.addon_token.strip()
    set_shop_channel(request.session, seller_id, CHANNEL_DINE_IN)
    set_channel_repick(request.session, seller_id, False)
    request.session.modified = True


def dine_table_entry(request):
    """扫物理桌码 / 专属加点码 / 虚拟码入口：建立或恢复桌台会话后进入点菜。"""
    seller_id = (request.GET.get('seller_id') or '').strip()
    t_token = (request.GET.get('t') or '').strip()
    s_token = (request.GET.get('s') or '').strip()
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
        existing = get_open_main_session_for_table(table)
        if existing:
            buyer_sess = get_buyer_table_session(request, seller_id)
            if buyer_sess and str(buyer_sess.session_id) == str(existing.session_id):
                session, err = existing, ''
            else:
                session, err = None, PHYSICAL_TABLE_BUSY_MSG
        else:
            session, err = open_table_main_session(table, device_key)
    elif s_token:
        session, err = bind_addon_session(seller_id, s_token, device_key)
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


def build_table_continue_dine_url(seller_id: str, table_sess: TableSession | None) -> str:
    """继续点菜：优先走加点码入口，确保重新锁定堂食。"""
    if not table_sess or table_sess.status != 'open':
        return f'/shop/?seller_id={seller_id}'
    if table_sess.session_type == 'main':
        from .table_helpers import build_addon_scan_path, ensure_addon_token

        token = ensure_addon_token(table_sess)
        if token:
            return build_addon_scan_path(seller_id, token)
    return f'/shop/?seller_id={seller_id}'
