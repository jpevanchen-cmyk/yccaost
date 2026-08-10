# 登录暂锁邮件：只通知被锁账号本人邮箱

from __future__ import annotations

import logging

from .email_helpers import is_email_ready, send_yecao_mail
from .email_rate_limit_helpers import KIND_LOGIN_LOCKED
from .login_guard_helpers import LOGIN_GUARD_LOCK_MINUTES, SCOPE_SHOP_WORK
from .staff_account_helpers import staff_internal_username

logger = logging.getLogger('waimai')


def resolve_locked_account_email(
    scope: str,
    *,
    username: str = '',
    seller_id: str = '',
) -> str:
    """根据登录名查找账号邮箱；找不到或没填邮箱则返回空。"""
    from django.contrib.auth import get_user_model

    login = (username or '').strip()
    if not login:
        return ''

    User = get_user_model()
    user = None
    if scope == SCOPE_SHOP_WORK:
        shop = (seller_id or '').strip()
        if shop:
            user = User.objects.filter(
                username=staff_internal_username(shop, login),
            ).first()
        if user is None:
            user = User.objects.filter(username__iexact=login).first()
    else:
        user = User.objects.filter(username__iexact=login).first()

    if not user:
        return ''
    return (getattr(user, 'email', '') or '').strip()


def notify_login_locked_email(
    *,
    scope: str,
    username: str = '',
    seller_id: str = '',
    portal_label: str = '',
) -> bool:
    """暂锁时给账号邮箱发提醒；发不出去不打断登录流程。"""
    login = (username or '').strip() or '（未填用户名）'
    label = portal_label or ('店铺工作台' if scope == SCOPE_SHOP_WORK else '野草生态')
    email = resolve_locked_account_email(
        scope, username=username, seller_id=seller_id,
    )
    if not email:
        logger.info('登录暂锁邮件：账号 %s 无邮箱，跳过', login)
        return False
    if not is_email_ready():
        logger.info('登录暂锁邮件：发信未配置，跳过')
        return False

    subject = '账户登录暂锁提醒'
    body = (
        f'您好，\n\n'
        f'您的账户（{login}）在{label}因密码错误次数过多，'
        f'已被暂锁约 {LOGIN_GUARD_LOCK_MINUTES} 分钟。\n\n'
        f'如非本人操作，请注意盗号风险，并尽快修改密码。\n\n'
        f'—— 野草系统'
    )
    shop = (seller_id or '').strip()
    dedupe_key = f'login_lock:{scope}:{login.lower()}:{shop}'
    try:
        return send_yecao_mail(
            subject=subject,
            message=body,
            recipient_list=[email],
            kind=KIND_LOGIN_LOCKED,
            dedupe_key=dedupe_key,
        )
    except Exception:
        logger.exception('登录暂锁邮件发送失败 account=%s', login)
        return False
