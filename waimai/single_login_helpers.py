# 同账号单设备登录：新登录取得资格，旧设备在下次请求时退出。


def ensure_session_key(request) -> str:
    """确保当前浏览器已有稳定会话编号。"""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key or ''


def claim_single_login(request, user) -> str:
    """把当前会话登记为该账号唯一有效会话。"""
    key = ensure_session_key(request)
    if user and key and user.active_session_key != key:
        user.active_session_key = key
        user.save(update_fields=['active_session_key'])
    return key


def single_login_is_current(request, user) -> bool:
    """当前请求是否仍是该账号最新登录的设备。"""
    if not user:
        return True
    # 尚未登记过（升级前的旧会话）：视为有效，等下次登录再启用单点，避免升级瞬间集体掉线。
    if not (user.active_session_key or ''):
        return True
    key = request.session.session_key or ''
    return user.active_session_key == key


def release_single_login(request, user) -> None:
    """仅当前设备仍持有资格时才清登记，避免旧设备误清新设备。"""
    if not user:
        return
    key = request.session.session_key or ''
    if key and user.active_session_key == key:
        user.active_session_key = ''
        user.save(update_fields=['active_session_key'])
