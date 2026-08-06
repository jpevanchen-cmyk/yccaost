# 自动测试 / 智能体临时调试 · 共用测试店铺（勿在业务代码中引用）

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client

from waimai.models import Dish, MenuProfileItem, ShopProfile

User = get_user_model()

# 固定一家「临时测试店」：manage.py test 用临时库；shell 调试 get_or_create 不增生
SCRATCH_SELLER_USERNAME = 'yc_scratch_test_seller'
SCRATCH_SHOP_CODE = 'ycscratch'
SCRATCH_SHOP_NAME = '智能体临时测试店'
DEFAULT_TEST_PASSWORD = 'pass12345'


@dataclass
class TestShopBundle:
    """一次测试常用的卖家 + 店铺 + 可选清单/商品。"""

    seller: User
    shop: ShopProfile
    profile=None
    dish: Dish | None = None
    item: MenuProfileItem | None = None


def create_test_shop_bundle(
    *,
    username: str = SCRATCH_SELLER_USERNAME,
    password: str = DEFAULT_TEST_PASSWORD,
    shop_code: str = SCRATCH_SHOP_CODE,
    shop_name: str = SCRATCH_SHOP_NAME,
    address: str = '临时测试地址',
    is_listed: bool = True,
    with_menu: bool = False,
    with_dish: bool = False,
    dish_name: str = '测试商品',
    dish_price: Decimal | str = Decimal('10.00'),
    listed_on_menu: bool = True,
    reuse_existing: bool = False,
) -> TestShopBundle:
    """
    建测试用卖家与店铺。

    - manage.py test：默认每次 create（临时库，跑完即毁）。
    - shell / 临时调试：reuse_existing=True，固定 username+shop_code，get_or_create 不堆店。
    """
    if reuse_existing:
        seller, _ = User.objects.get_or_create(
            username=username,
            defaults={'role': 'seller'},
        )
        if not seller.check_password(password):
            seller.set_password(password)
            seller.role = 'seller'
            seller.save(update_fields=['password', 'role'])
        shop, _ = ShopProfile.objects.get_or_create(
            seller_id=seller.username,
            defaults={
                'shop_name': shop_name,
                'shop_code': shop_code,
                'address': address,
                'is_listed': is_listed,
            },
        )
    else:
        seller = User.objects.create_user(
            username=username,
            password=password,
            role='seller',
        )
        shop = ShopProfile.objects.create(
            seller_id=seller.username,
            shop_name=shop_name,
            shop_code=shop_code,
            address=address,
            is_listed=is_listed,
        )

    bundle = TestShopBundle(seller=seller, shop=shop)
    if with_menu or with_dish:
        from waimai.menu_helpers import ensure_active_menu_catalog

        bundle.profile = ensure_active_menu_catalog(seller.username)
    if with_dish:
        bundle.dish = Dish.objects.create(
            seller_id=seller.username,
            name=dish_name,
            price=Decimal(str(dish_price)),
            is_active=True,
        )
        if bundle.profile:
            bundle.item = MenuProfileItem.objects.create(
                profile=bundle.profile,
                dish=bundle.dish,
                is_listed=listed_on_menu,
                general_price_listed=listed_on_menu,
            )
    return bundle


def get_or_create_scratch_test_shop(**kwargs) -> TestShopBundle:
    """智能体 manage.py shell / 临时脚本专用：永远复用同一家 scratch 店。"""
    kwargs.setdefault('username', SCRATCH_SELLER_USERNAME)
    kwargs.setdefault('shop_code', SCRATCH_SHOP_CODE)
    kwargs.setdefault('shop_name', SCRATCH_SHOP_NAME)
    kwargs['reuse_existing'] = True
    return create_test_shop_bundle(**kwargs)


def create_logged_in_seller_client(
    bundle: TestShopBundle,
    *,
    password: str = DEFAULT_TEST_PASSWORD,
) -> Client:
    """已登录卖家后台的测试客户端。"""
    client = Client()
    client.login(username=bundle.seller.username, password=password)
    return client


def create_official_experience_test_shop(
    *,
    shop_name: str,
    shop_code: str = 'ycexpscratch',
    username: str = 'yc_exp_scratch_seller',
    reuse_existing: bool = False,
) -> TestShopBundle:
    """体验引导测试：官方演示店（须 mark_shop_official）。"""
    from waimai.experience_helpers import mark_shop_official
    from waimai.menu_helpers import get_active_menu_profile, populate_profile_with_dishes
    from waimai.models import MenuProfile

    bundle = create_test_shop_bundle(
        username=username,
        shop_code=shop_code,
        shop_name=shop_name,
        reuse_existing=reuse_existing,
    )
    mark_shop_official(bundle.seller.username)
    if not Dish.objects.filter(seller_id=bundle.seller.username).exists():
        Dish.objects.create(
            seller_id=bundle.seller.username,
            name='演示矿泉水',
            price=Decimal('2.00'),
            is_active=True,
        )
    if not MenuProfile.objects.filter(seller_id=bundle.seller.username).exists():
        profile = MenuProfile.objects.create(
            seller_id=bundle.seller.username,
            name='通用清单',
        )
        populate_profile_with_dishes(profile, bundle.seller.username)
    profile = get_active_menu_profile(bundle.seller.username)
    from waimai.operating_helpers import get_operating_settings

    settings = get_operating_settings(bundle.seller.username)
    settings.active_menu_profile = profile
    settings.save(update_fields=['active_menu_profile'])
    bundle.profile = profile
    return bundle
