# 生态统一账户：一个账号可同时具备买家与卖家资格（手册 A.2.5 第一刀）
# 工牌（role=staff）不走这里。

from __future__ import annotations

from django.db import transaction

ECO_ROLES = frozenset({'buyer', 'seller'})
STAFF_ROLE = 'staff'


def user_is_staff_badge(user) -> bool:
    """是否店铺工牌（工作台门），不是生态账户。"""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return getattr(user, 'role', '') == STAFF_ROLE


def user_has_buyer_capability(user) -> bool:
    """生态账户默认具备买家资格（含已开店的店主）。"""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return getattr(user, 'role', '') in ECO_ROLES


def user_has_seller_capability(user) -> bool:
    """是否已开通本机卖家。真源是本账号名下的店铺资料；旧号 role=seller 仍算。"""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    role = getattr(user, 'role', '') or ''
    if role in ('staff', 'waiter', 'kitchen', 'rider', 'manager'):
        return False
    if role == 'seller':
        return True
    if role != 'buyer':
        return False
    seller_id = (getattr(user, 'username', '') or '').strip()
    if not seller_id:
        return False
    from .models import ShopProfile

    return ShopProfile.objects.filter(seller_id=seller_id).exists()


def eco_is_order_buyer(user, order) -> bool:
    """此人是本单客人（店主买自己店的单时也算客人）。"""
    if not user_has_buyer_capability(user) or order is None:
        return False
    return (getattr(order, 'buyer_id', '') or '') == (getattr(user, 'username', '') or '')


def eco_is_order_shop(user, order) -> bool:
    """此人是本店店主且不是本单客人。"""
    if eco_is_order_buyer(user, order):
        return False
    if not user_has_seller_capability(user) or order is None:
        return False
    return (getattr(order, 'seller_id', '') or '') == (getattr(user, 'username', '') or '')


def create_shop_records_for_seller(
    user,
    *,
    shop_name: str,
    shop_type: str,
    address: str,
    raw_password: str,
) -> tuple[object, bool]:
    """
    为已有生态账号建立本店资料与店主工牌。
    已有店铺则原样返回，不新建（可安全重试）。
    返回 (店铺资料, 是否新开)。
    """
    from .experience_helpers import apply_experience_flags_for_new_user, experience_site_enabled
    from .home_page_helpers import ensure_home_page_for_seller, ensure_server_home_page
    from .menu_helpers import ensure_active_menu_catalog
    from .models import ShopDeliverySettings, ShopOperatingSettings, ShopPaymentSettings, ShopProfile
    from .shop_code_helpers import assign_shop_code_on_create
    from .staff_account_helpers import create_owner_workbench_staff

    seller_id = (getattr(user, 'username', '') or '').strip()
    if not seller_id:
        raise ValueError('账号无效，无法开店')

    with transaction.atomic():
        profile = ShopProfile.objects.filter(seller_id=seller_id).first()
        if profile is not None:
            # 已有店：不改身份。买家开店后仍是买家，卖家资格看店铺资料。
            return profile, False

        # 开店只加卖家资格，不把买家改成卖家
        apply_experience_flags_for_new_user(user, is_shop=True)

        from .shop_name_helpers import SHOP_NAME_TAKEN_MESSAGE, normalize_shop_name, shop_name_is_taken

        shop_name = normalize_shop_name(shop_name)
        if shop_name_is_taken(shop_name, exclude_seller_id=seller_id):
            raise ValueError(SHOP_NAME_TAKEN_MESSAGE)

        profile = ShopProfile.objects.create(
            seller_id=seller_id,
            shop_name=shop_name,
            shop_type=shop_type,
            address=address,
            is_listed=True,
            is_official=False,
        )
        assign_shop_code_on_create(profile)
        ShopDeliverySettings.objects.get_or_create(seller_id=seller_id)
        pay, _ = ShopPaymentSettings.objects.get_or_create(seller_id=seller_id)
        if experience_site_enabled():
            pay.enable_wechat = False
            pay.enable_simulate = True
            pay.save(update_fields=['enable_wechat', 'enable_simulate'])
        ShopOperatingSettings.objects.get_or_create(seller_id=seller_id)
        ensure_home_page_for_seller(seller_id, profile)
        ensure_active_menu_catalog(seller_id)
        ensure_server_home_page()
        create_owner_workbench_staff(user, raw_password)
        return profile, True
