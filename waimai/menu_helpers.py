# A.11.4 菜单清单与限购

from django.db.models import F

from .models import BuyOrder, Dish, MenuProfile, MenuProfileItem
from .operating_helpers import get_operating_settings


def _allocate_default_menu_profile_name(seller_id: str) -> str:
    """为本店取一个不撞名的默认清单名（商品列表 1、2…）。"""
    from .product_shell_helpers import build_product_shell

    word = build_product_shell(seller_id).get('catalog_word', '商品列表')
    n = 1
    while True:
        name = f'{word} {n}'
        if not menu_profile_name_taken(seller_id, name):
            return name
        n += 1


def ensure_active_menu_catalog(seller_id: str) -> MenuProfile:
    """
    A.11.12：保证本店始终有一份「使用中」的商品清单。
    无清单则新建并纳入全部商品；有清单但未切换使用则启用最早那份。
    """
    settings = get_operating_settings(seller_id)
    profile = settings.active_menu_profile
    if profile and profile.seller_id == seller_id:
        return profile

    profiles = list(
        MenuProfile.objects.filter(seller_id=seller_id).order_by('created_at', 'profile_id')
    )
    if profiles:
        profile = profiles[0]
    else:
        profile = MenuProfile.objects.create(
            seller_id=seller_id,
            name=_allocate_default_menu_profile_name(seller_id),
        )
        populate_profile_with_dishes(profile, seller_id)

    settings.active_menu_profile = profile
    settings.save(update_fields=['active_menu_profile'])
    return profile


def get_active_menu_profile(seller_id: str) -> MenuProfile | None:
    """当前启用的商品清单；主体店铺须始终有一份使用中清单。"""
    from .product_shell_helpers import build_product_shell

    if not build_product_shell(seller_id).get('show_menu_catalog', True):
        settings = get_operating_settings(seller_id)
        return settings.active_menu_profile

    settings = get_operating_settings(seller_id)
    profile = settings.active_menu_profile
    if profile and profile.seller_id == seller_id:
        return profile
    return ensure_active_menu_catalog(seller_id)


def normalize_profile_id(profile_id) -> str:
    """统一清单 ID 字符串便于比对"""
    return str(profile_id).replace('-', '').lower()


def find_menu_profile_by_pick_id(seller_id: str, pick_id: str) -> MenuProfile | None:
    """按网址参数选中菜单清单"""
    pick_norm = normalize_profile_id(pick_id)
    if not pick_norm:
        return None
    for profile in MenuProfile.objects.filter(seller_id=seller_id):
        if normalize_profile_id(profile.profile_id) == pick_norm:
            return profile
    return None


def menu_profile_name_taken(seller_id: str, name: str, exclude_profile_id=None) -> bool:
    """同店是否已有同名清单"""
    qs = MenuProfile.objects.filter(seller_id=seller_id, name=name)
    if exclude_profile_id:
        qs = qs.exclude(profile_id=exclude_profile_id)
    return qs.exists()


def copy_profile_items(source: MenuProfile, target: MenuProfile):
    """复制一份清单的商品条目到另一份（已售数量归零）"""
    for item in source.items.select_related('dish').all():
        MenuProfileItem.objects.create(
            profile=target,
            dish=item.dish,
            sort_order=item.sort_order,
            is_listed=item.is_listed,
            member_price_listed=item.member_price_listed,
            special_price_listed=item.special_price_listed,
            sales_cap=item.sales_cap,
            sold_count=0,
        )


def populate_profile_with_dishes(profile: MenuProfile, seller_id: str):
    """新建清单时：纳入本店全部已添加商品"""
    dishes = Dish.objects.filter(seller_id=seller_id).order_by('sort_order', 'name')
    for dish in dishes:
        MenuProfileItem.objects.get_or_create(
            profile=profile,
            dish=dish,
            defaults={
                'sort_order': dish.sort_order,
                'is_listed': True,
                'member_price_listed': dish.member_price_enabled,
                'special_price_listed': dish.special_price_enabled,
            },
        )


def sync_new_dish_to_menu_profiles(dish: Dish, *, list_on_all_menus: bool = False):
    """新商品加入本店已有各份菜单清单；默认不上架，勾选「全部上架」时各清单均为上架中"""
    listed = bool(list_on_all_menus)
    for profile in MenuProfile.objects.filter(seller_id=dish.seller_id):
        MenuProfileItem.objects.get_or_create(
            profile=profile,
            dish=dish,
            defaults={
                'sort_order': dish.sort_order,
                'is_listed': listed,
                'member_price_listed': dish.member_price_enabled,
                'special_price_listed': dish.special_price_enabled,
            },
        )


def dish_visible_on_shop(seller_id: str, dish_id) -> bool:
    """买家店铺页是否应展示该商品"""
    profile = get_active_menu_profile(seller_id)
    if not profile:
        return Dish.objects.filter(seller_id=seller_id, dish_id=dish_id, is_active=True).exists()
    return MenuProfileItem.objects.filter(
        profile=profile, dish_id=dish_id, is_listed=True,
    ).exists()


def menu_item_allows_tier(
    menu_item: MenuProfileItem | None, tier: str, seller_id: str | None = None,
) -> bool:
    """
    有使用中清单时：会员/特价须「商品允许」且「本清单勾选展示」。
    无使用中清单时：只看商品是否配置了该档位。
    """
    if tier == 'general':
        return True

    profile = get_active_menu_profile(seller_id) if seller_id else None
    if profile:
        if not menu_item:
            return False
        dish = menu_item.dish
        if tier == 'member':
            return bool(menu_item.member_price_listed and dish.member_price_enabled)
        if tier == 'special':
            return bool(menu_item.special_price_listed and dish.special_price_enabled)
        return True

    return True


def get_shop_dishes_for_sale(seller_id: str):
    """
    买家可见菜品：有激活菜单则仅清单内且 is_listed 的条目；否则沿用 is_active 菜品。
    返回 (queryset, using_menu: bool)
    """
    profile = get_active_menu_profile(seller_id)
    if not profile:
        return Dish.objects.filter(seller_id=seller_id, is_active=True).prefetch_related(
            'product_images',
        ).order_by(
            'sort_order', '-created_at',
        ), False

    dish_ids = MenuProfileItem.objects.filter(
        profile=profile, is_listed=True,
    ).values_list('dish_id', flat=True)
    return Dish.objects.filter(
        seller_id=seller_id, dish_id__in=dish_ids,
    ).prefetch_related('product_images').order_by('sort_order', '-created_at'), True


def get_active_menu_items_map(seller_id: str) -> dict:
    """使用中清单的条目（按 dish_id 索引），供店铺页批量读取"""
    profile = get_active_menu_profile(seller_id)
    if not profile:
        return {}
    items = MenuProfileItem.objects.filter(profile=profile).select_related('dish')
    return {item.dish_id: item for item in items}


def get_menu_item_for_dish(seller_id: str, dish_id, menu_items_map=None) -> MenuProfileItem | None:
    profile = get_active_menu_profile(seller_id)
    if not profile:
        return None
    if menu_items_map is not None:
        return menu_items_map.get(dish_id)
    return MenuProfileItem.objects.filter(
        profile=profile, dish_id=dish_id,
    ).select_related('dish').first()


def buyer_is_new_member(buyer_id: str, seller_id: str) -> bool:
    """新会员：本店从未有过已完成订单"""
    return not BuyOrder.objects.filter(
        buyer_id=buyer_id, seller_id=seller_id, order_status='completed',
    ).exists()


def count_user_dish_purchases(buyer_id: str, seller_id: str, dish_id) -> int:
    """统计买家在本店购买某菜品的历史数量（含进行中订单）"""
    orders = BuyOrder.objects.filter(
        buyer_id=buyer_id, seller_id=seller_id,
    ).exclude(order_status='cancelled')
    total = 0
    dish_hex = str(dish_id).replace('-', '')
    for order in orders:
        for item in order.dish_items or []:
            item_id = str(item.get('dish_id', '')).replace('-', '')
            if item_id == dish_hex or item.get('dish_id') == str(dish_id):
                total += int(item.get('quantity', 0))
    return total


def validate_dish_purchase(
    dish: Dish, buyer, seller_id: str, quantity: int,
) -> tuple[bool, str]:
    """兼容旧调用：按通用价档位校验"""
    from .product_helpers import PRICE_TIER_GENERAL, validate_tier_purchase
    return validate_tier_purchase(dish, PRICE_TIER_GENERAL, buyer, seller_id, quantity, {})


def sanitize_cart_for_active_catalog(cart: dict, seller_id: str) -> tuple[dict, list[str]]:
    """
    结算前：从购物车里去掉已下架或不在「使用中清单」的商品行。
    返回 (清理后的购物车, 移除说明列表)。
    """
    from .order_helpers import normalize_cart_keys
    from .product_helpers import TIER_LABELS, parse_cart_line_key
    from .product_shell_helpers import build_product_shell, catalog_controls_shop_display

    cart = normalize_cart_keys(cart)
    removed: list[str] = []
    cleaned = dict(cart)

    for line_key, qty in list(cart.items()):
        if int(qty or 0) <= 0:
            continue
        dish_id, tier = parse_cart_line_key(line_key)
        try:
            dish = Dish.objects.get(dish_id=dish_id, seller_id=seller_id)
        except Dish.DoesNotExist:
            cleaned.pop(line_key, None)
            removed.append('部分商品已不存在，已从购物车移除')
            continue

        if not dish.is_active:
            cleaned.pop(line_key, None)
            removed.append(f'「{dish.name}」已下架，已从购物车移除')
            continue

        if catalog_controls_shop_display(seller_id):
            if not dish_visible_on_shop(seller_id, dish.dish_id):
                word = build_product_shell(seller_id).get('catalog_word', '商品列表')
                cleaned.pop(line_key, None)
                removed.append(f'「{dish.name}」不在当前{word}中，已从购物车移除')
                continue
            menu_item = get_menu_item_for_dish(seller_id, dish.dish_id)
            if not menu_item_allows_tier(menu_item, tier, seller_id):
                tier_label = TIER_LABELS.get(tier, tier)
                cleaned.pop(line_key, None)
                removed.append(f'「{dish.name}」当前不可售{tier_label}，已从购物车移除')

    # 去掉数量已为 0 的行，避免会话里留垃圾键
    for key, qty in list(cleaned.items()):
        if int(qty or 0) <= 0:
            cleaned.pop(key, None)

    return cleaned, removed


def increment_menu_sold_counts(seller_id: str, cart_items):
    """下单成功后增加商品列表/菜单清单已售计数"""
    from .product_shell_helpers import catalog_controls_shop_display

    if not catalog_controls_shop_display(seller_id):
        return
    profile = get_active_menu_profile(seller_id)
    if not profile:
        return
    for item in cart_items:
        MenuProfileItem.objects.filter(
            profile=profile, dish_id=item['dish'].dish_id,
        ).update(sold_count=F('sold_count') + item['quantity'])
