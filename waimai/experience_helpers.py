# 体验机：额度、日清、在线名额、禁真付、通知（约定见 docs/体验机与官方小店约定.md）

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger('waimai')

ONLINE_SET_KEY = 'yc_exp_online_set'
NOTIFY_COOLDOWN_KEY = 'yc_exp_notify_cooldown'
NOTIFY_COOLDOWN_SECONDS = 30 * 60
ONLINE_TTL_SECONDS = 2 * 60  # 约 2 分钟无心跳则不算在线


def experience_site_enabled() -> bool:
    return bool(getattr(settings, 'YECAO_EXPERIENCE_SITE', False))


def daily_shop_limit() -> int:
    return int(getattr(settings, 'YECAO_EXPERIENCE_DAILY_SHOPS', 15))


def daily_account_limit() -> int:
    return int(getattr(settings, 'YECAO_EXPERIENCE_DAILY_ACCOUNTS', 30))


def concurrent_online_limit() -> int:
    return int(getattr(settings, 'YECAO_EXPERIENCE_CONCURRENT', 10))


def notify_email() -> str:
    return (getattr(settings, 'YECAO_EXPERIENCE_NOTIFY_EMAIL', '') or '').strip()


def beijing_today_range():
    """当天北京时间 0 点～次日 0 点（用本地时区感知）"""
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


def count_today_experience_accounts() -> int:
    from .models import User

    start, end = beijing_today_range()
    return User.objects.filter(
        is_experience=True,
        is_permanent=False,
        date_joined__gte=start,
        date_joined__lt=end,
    ).count()


def count_today_experience_shops() -> int:
    from .models import ShopProfile

    start, end = beijing_today_range()
    # 官方小店不计入；当日注册的非官方店都算体验名额
    return ShopProfile.objects.filter(
        is_official=False,
        registered_at__gte=start,
        registered_at__lt=end,
    ).count()


def can_register_experience_account() -> tuple[bool, str]:
    if not experience_site_enabled():
        return True, ''
    if count_today_experience_accounts() >= daily_account_limit():
        maybe_notify('今日体验账号已达上限', f'上限 {daily_account_limit()}')
        return False, '今日体验用户数量已达上限，明日请早！'
    return True, ''


def can_register_experience_shop() -> tuple[bool, str]:
    if not experience_site_enabled():
        return True, ''
    ok, msg = can_register_experience_account()
    if not ok:
        return False, msg
    if count_today_experience_shops() >= daily_shop_limit():
        maybe_notify('今日体验店铺已达上限', f'上限 {daily_shop_limit()}')
        return False, '今日体验开店名额已满，明日请早！'
    return True, ''


def mark_user_experience(user) -> None:
    user.is_experience = True
    user.is_permanent = False
    user.save(update_fields=['is_experience', 'is_permanent'])


def mark_shop_official(seller_id: str) -> None:
    """将某店标为官方小店，店主标为正式保留（不占体验额度、不日清）"""
    from .models import ShopProfile, User

    seller_id = (seller_id or '').strip()
    ShopProfile.objects.filter(seller_id=seller_id).update(is_official=True)
    User.objects.filter(username=seller_id).update(
        is_experience=False,
        is_permanent=True,
    )
    # 本店员工子账号一并保留
    User.objects.filter(employer_seller_id=seller_id).update(
        is_experience=False,
        is_permanent=True,
    )


def user_exempt_from_online_limit(user) -> bool:
    """正式/官方相关账号不占用繁忙限制，或始终放行"""
    if not user:
        return False
    if getattr(user, 'is_permanent', False):
        return True
    if getattr(user, 'is_superuser', False):
        return True
    return False


def count_online() -> int:
    # 扫描在线集合并清理过期
    raw = cache.get(ONLINE_SET_KEY) or {}
    now = timezone.now().timestamp()
    alive = {str(uid): ts for uid, ts in raw.items() if now - float(ts) < ONLINE_TTL_SECONDS}
    cache.set(ONLINE_SET_KEY, alive, timeout=ONLINE_TTL_SECONDS * 3)
    return len(alive)


def touch_online_user(user) -> None:
    if not experience_site_enabled() or not user or not getattr(user, 'pk', None):
        return
    raw = cache.get(ONLINE_SET_KEY) or {}
    raw[str(user.pk)] = timezone.now().timestamp()
    now = timezone.now().timestamp()
    raw = {uid: ts for uid, ts in raw.items() if now - float(ts) < ONLINE_TTL_SECONDS}
    cache.set(ONLINE_SET_KEY, raw, timeout=ONLINE_TTL_SECONDS * 3)


def can_accept_online(user) -> tuple[bool, str]:
    """是否允许占用同时在线名额；已在线或正式号放行"""
    if not experience_site_enabled():
        return True, ''
    if user_exempt_from_online_limit(user):
        return True, ''
    raw = cache.get(ONLINE_SET_KEY) or {}
    now = timezone.now().timestamp()
    raw = {uid: ts for uid, ts in raw.items() if now - float(ts) < ONLINE_TTL_SECONDS}
    uid = str(getattr(user, 'pk', ''))
    if uid and uid in raw:
        return True, ''
    if len(raw) >= concurrent_online_limit():
        maybe_notify('同时在线已达上限', f'上限 {concurrent_online_limit()}')
        return False, '当前体验服务器繁忙，请稍后再试。'
    return True, ''


def shop_is_official(seller_id: str) -> bool:
    from .models import ShopProfile

    return ShopProfile.objects.filter(seller_id=seller_id, is_official=True).exists()


def seller_blocked_from_real_wechat(seller_id: str) -> bool:
    """体验店禁止开通/发起真微信；官方小店放行"""
    if not experience_site_enabled():
        return False
    if not seller_id:
        return False
    if shop_is_official(seller_id):
        return False
    from .models import User

    seller = User.objects.filter(username=seller_id).first()
    if seller and getattr(seller, 'is_permanent', False):
        return False
    # 体验机上：非官方店一律禁真付（含未标记 is_experience 的遗留店）
    return True


def apply_experience_flags_for_new_user(user, *, is_shop: bool = False) -> None:
    """体验机模式下给新注册用户打体验标记"""
    if not experience_site_enabled():
        return
    user.is_experience = True
    user.is_permanent = False
    user.save(update_fields=['is_experience', 'is_permanent'])


def inherit_experience_from_employer(user, seller_id: str) -> None:
    """员工跟随店铺：体验店员工也是体验号；官方店员工为正式号"""
    if not experience_site_enabled():
        return
    if shop_is_official(seller_id):
        user.is_experience = False
        user.is_permanent = True
    else:
        user.is_experience = True
        user.is_permanent = False
    user.save(update_fields=['is_experience', 'is_permanent'])


def request_presence_user(request):
    """当前应计入同时在线的用户（生态或工作台）"""
    if getattr(request.user, 'is_authenticated', False):
        return request.user
    work = getattr(request, 'shop_work_user', None)
    if work is not None:
        return work
    return None


def maybe_notify(subject: str, body: str) -> None:
    email = notify_email()
    if not email:
        return
    if cache.get(NOTIFY_COOLDOWN_KEY):
        return
    try:
        send_mail(
            subject=f'[野草体验机] {subject}',
            message=body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None) or email,
            recipient_list=[email],
            fail_silently=True,
        )
        cache.set(NOTIFY_COOLDOWN_KEY, '1', timeout=NOTIFY_COOLDOWN_SECONDS)
    except Exception:
        logger.exception('体验机通知邮件发送失败')


def purge_experience_data() -> dict:
    """清空所有体验帐户及相关体验店数据；不动官方小店与正式号"""
    from .models import (
        BuyOrder,
        DeliveryOrder,
        Dish,
        MenuProfile,
        ShopDeliverySettings,
        ShopHomePage,
        ShopOperatingSettings,
        ShopPaymentSettings,
        ShopProfile,
        User,
    )

    official_ids = set(
        ShopProfile.objects.filter(is_official=True).values_list('seller_id', flat=True)
    )
    exp_sellers = list(
        User.objects.filter(is_experience=True, role='seller', is_permanent=False)
        .exclude(username__in=official_ids)
        .values_list('username', flat=True)
    )
    # 非官方且店主为体验号的店，也清掉（防漏标）
    extra_shops = list(
        ShopProfile.objects.filter(is_official=False)
        .exclude(seller_id__in=official_ids)
        .filter(seller_id__in=User.objects.filter(is_experience=True, is_permanent=False).values_list('username', flat=True))
        .values_list('seller_id', flat=True)
    )
    exp_sellers = list(dict.fromkeys([*exp_sellers, *extra_shops]))

    stats = {'shops': 0, 'users': 0, 'orders': 0}
    order_qs = BuyOrder.objects.filter(seller_id__in=exp_sellers)
    stats['orders'] = order_qs.count()
    DeliveryOrder.objects.filter(buy_order__seller_id__in=exp_sellers).delete()
    order_qs.delete()

    for sid in exp_sellers:
        Dish.objects.filter(seller_id=sid).delete()
        MenuProfile.objects.filter(seller_id=sid).delete()
        ShopHomePage.objects.filter(seller_id=sid).delete()
        ShopDeliverySettings.objects.filter(seller_id=sid).delete()
        ShopPaymentSettings.objects.filter(seller_id=sid).delete()
        ShopOperatingSettings.objects.filter(seller_id=sid).delete()
    stats['shops'] = ShopProfile.objects.filter(seller_id__in=exp_sellers, is_official=False).count()
    ShopProfile.objects.filter(seller_id__in=exp_sellers, is_official=False).delete()

    buyer_names = list(
        User.objects.filter(is_experience=True, role='buyer', is_permanent=False).values_list('username', flat=True)
    )
    BuyOrder.objects.filter(buyer_id__in=buyer_names).delete()

    stats['users'] = User.objects.filter(is_experience=True, is_permanent=False).count()
    User.objects.filter(is_experience=True, is_permanent=False).delete()
    return stats


def experience_hint_context() -> dict:
    return {
        'experience_site': experience_site_enabled(),
        'experience_hint': (
            '这是一次体验注册：可体验完整功能，但无法开通真实支付。'
            '若要测试真实支付，请到官方小店。'
            '所有体验帐户将在每天 24 点自动清空重置。'
        ) if experience_site_enabled() else '',
        'daily_shop_limit': daily_shop_limit(),
        'daily_account_limit': daily_account_limit(),
    }
