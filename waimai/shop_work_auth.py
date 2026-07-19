# 店铺工作台独立登录状态（与野草生态 Django 登录严格分开）

from django.contrib.auth import get_user_model

from .shop_work_helpers import SESSION_SHOP_WORK_CODE, SHOP_STAFF_ROLES, user_belongs_to_shop

# 工作台会话键（不走 django.contrib.auth.login）
SESSION_SHOP_WORK_USER_ID = 'shop_work_user_id'
SESSION_SHOP_WORK_SELLER_ID = 'shop_work_seller_id'
SHOP_WORK_SESSION_KEYS = (
    SESSION_SHOP_WORK_USER_ID,
    SESSION_SHOP_WORK_SELLER_ID,
    SESSION_SHOP_WORK_CODE,
)


def snapshot_shop_work_session(request) -> dict:
    """备份工作台会话字段，避免生态 logout 整表清空时被误删"""
    return {
        key: request.session.get(key)
        for key in SHOP_WORK_SESSION_KEYS
        if key in request.session
    }


def restore_shop_work_session(request, snapshot: dict | None) -> None:
    """把备份的工作台会话写回"""
    if not snapshot:
        return
    for key, value in snapshot.items():
        if value is not None:
            request.session[key] = value
    request.session.modified = True


def get_shop_work_user(request):
    """读取当前工作台登录用户；无效则返回 None"""
    user_id = request.session.get(SESSION_SHOP_WORK_USER_ID)
    seller_id = (request.session.get(SESSION_SHOP_WORK_SELLER_ID) or '').strip()
    if not user_id or not seller_id:
        return None
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        clear_shop_work_session(request)
        return None
    if not user.is_active:
        clear_shop_work_session(request)
        return None
    if not user_belongs_to_shop(user, seller_id):
        clear_shop_work_session(request)
        return None
    return user


def get_shop_work_seller_id(request) -> str:
    """当前工作台会话对应的店铺 ID"""
    return (request.session.get(SESSION_SHOP_WORK_SELLER_ID) or '').strip()


def establish_shop_work_session(request, user, *, seller_id: str, shop_code: str) -> None:
    """写入工作台登录状态（不影响野草生态登录）"""
    request.session[SESSION_SHOP_WORK_USER_ID] = user.pk
    request.session[SESSION_SHOP_WORK_SELLER_ID] = (seller_id or '').strip()
    request.session[SESSION_SHOP_WORK_CODE] = (shop_code or '').strip()
    request.session.modified = True
    request.shop_work_user = user


def clear_shop_work_session(request) -> None:
    """清除工作台登录状态（不影响野草生态登录）"""
    for key in SHOP_WORK_SESSION_KEYS:
        if key in request.session:
            del request.session[key]
    request.session.modified = True
    request.shop_work_user = None


def is_shop_staff_role(user) -> bool:
    """是否为店铺子账户身份（不含店主）"""
    from .staff_account_helpers import is_shop_staff_account

    return bool(
        user
        and getattr(user, 'is_authenticated', False)
        and is_shop_staff_account(user)
    )


def path_is_shop_work(path: str) -> bool:
    """是否店铺工作台相关路径"""
    path = path or ''
    if path.startswith('/s/') and '/work' in path:
        return True
    # 服务员在工作台内跳转的收款页，仍属工作台通道
    if path.startswith('/waiter-home/pay/'):
        return True
    return False
