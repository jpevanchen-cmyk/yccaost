# A.11.4 菜单清单与限购

import uuid

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
            general_price_listed=item.general_price_listed,
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
                'general_price_listed': True,
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
                'general_price_listed': True,
                'member_price_listed': dish.member_price_enabled,
                'special_price_listed': dish.special_price_enabled,
            },
        )


def dish_visible_on_shop(seller_id: str, dish_id) -> bool:
    """买家店铺页是否应展示该商品（须上架且至少有一档客人可见的价格）"""
    profile = get_active_menu_profile(seller_id)
    if not profile:
        return Dish.objects.filter(seller_id=seller_id, dish_id=dish_id, is_active=True).exists()
    item = MenuProfileItem.objects.filter(
        profile=profile, dish_id=dish_id, is_listed=True,
    ).select_related('dish').first()
    if not item:
        return False
    return menu_item_has_visible_tier(item, seller_id)


def menu_item_has_visible_tier(
    menu_item: MenuProfileItem, seller_id: str | None = None,
) -> bool:
    """
    本清单条目是否至少有一档客人可见的价格。
    与 build_dish_tier_options 同一套规则，避免列表过滤与点菜页不一致。
    """
    from .product_helpers import build_dish_tier_options

    dish = menu_item.dish
    sid = seller_id or menu_item.profile.seller_id
    return bool(build_dish_tier_options(dish, None, sid, {}, menu_item=menu_item))


def menu_item_allows_tier(
    menu_item: MenuProfileItem | None, tier: str, seller_id: str | None = None,
) -> bool:
    """
    有使用中清单时：各档须「商品允许（会员/特价）」且「本清单勾选展示」。
    无使用中清单时：通用价始终允许；会员/特价沿用商品是否配置。
    """
    profile = get_active_menu_profile(seller_id) if seller_id else None
    if profile:
        if not menu_item:
            return False
        dish = menu_item.dish
        if tier == 'general':
            return bool(menu_item.general_price_listed)
        if tier == 'member':
            return bool(menu_item.member_price_listed and dish.member_price_enabled)
        if tier == 'special':
            return bool(menu_item.special_price_listed and dish.special_price_enabled)
        return True

    if tier == 'general':
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

    dish_ids = []
    for item in MenuProfileItem.objects.filter(
        profile=profile, is_listed=True,
    ).select_related('dish'):
        if menu_item_has_visible_tier(item, seller_id):
            dish_ids.append(item.dish_id)
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
    """
    已废止：下单即加已售（进度 79 改付款后占名额）。
    保留函数名避免旧引用报错；请改用 try_apply_catalog_sales_for_order。
    """
    return


def aggregate_dish_quantities_from_order(order) -> dict[str, int]:
    """按 dish_id（无连字符）汇总订单件数；各档共享清单可售上限。"""
    totals: dict[str, int] = {}
    for row in order.dish_items or []:
        dish_id = str(row.get('dish_id', '')).replace('-', '').lower()
        qty = int(row.get('quantity', 0) or 0)
        if dish_id and qty > 0:
            totals[dish_id] = totals.get(dish_id, 0) + qty
    return totals


def _catalog_sales_shortfall_message(dish_name: str) -> str:
    return f'当前「{dish_name}」可售数量不足，无法完成支付'


def check_catalog_sales_cap_for_order(order) -> tuple[bool, list[str]]:
    """
    检查本单相对已占用明细的增量是否超出清单可售上限。
    返回 (可否占用, 不足说明列表)。
    """
    from .models import Dish
    from .product_shell_helpers import catalog_controls_shop_display

    if not catalog_controls_shop_display(order.seller_id):
        return True, []

    profile = get_active_menu_profile(order.seller_id)
    if not profile:
        return True, []

    needed = aggregate_dish_quantities_from_order(order)
    applied = order.catalog_sales_detail or {}
    errors: list[str] = []

    for dish_hex, total_qty in needed.items():
        prev = int(applied.get(dish_hex, 0) or 0)
        delta = total_qty - prev
        if delta <= 0:
            continue
        try:
            dish = Dish.objects.get(
                dish_id=uuid.UUID(dish_hex), seller_id=order.seller_id,
            )
        except Dish.DoesNotExist:
            errors.append(_catalog_sales_shortfall_message('部分商品'))
            continue
        menu_item = MenuProfileItem.objects.filter(
            profile=profile, dish_id=dish.dish_id,
        ).select_related('dish').first()
        if not menu_item or menu_item.sales_cap is None:
            continue
        if menu_item.sold_count + delta > menu_item.sales_cap:
            errors.append(_catalog_sales_shortfall_message(dish.name))

    return (len(errors) == 0, errors)


def try_apply_catalog_sales_for_order(order) -> tuple[bool, list[str]]:
    """
    为订单占用清单可售名额（幂等；支持主单加点增量）。
    须在 transaction 内调用；失败时不部分占用。
    """
    from django.db import transaction

    from .models import BuyOrder, Dish
    from .product_shell_helpers import catalog_controls_shop_display

    if not catalog_controls_shop_display(order.seller_id):
        return True, []

    profile = get_active_menu_profile(order.seller_id)
    if not profile:
        return True, []

    needed = aggregate_dish_quantities_from_order(order)
    if not needed:
        return True, []

    with transaction.atomic():
        locked = BuyOrder.objects.select_for_update().get(pk=order.pk)
        applied = dict(locked.catalog_sales_detail or {})
        deltas: list[tuple] = []
        errors: list[str] = []

        for dish_hex, total_qty in needed.items():
            prev = int(applied.get(dish_hex, 0) or 0)
            delta = total_qty - prev
            if delta <= 0:
                continue
            try:
                dish = Dish.objects.get(
                    dish_id=uuid.UUID(dish_hex), seller_id=locked.seller_id,
                )
            except Dish.DoesNotExist:
                errors.append(_catalog_sales_shortfall_message('部分商品'))
                continue
            menu_item = (
                MenuProfileItem.objects.select_for_update()
                .filter(profile=profile, dish_id=dish.dish_id)
                .select_related('dish')
                .first()
            )
            if not menu_item:
                errors.append(_catalog_sales_shortfall_message(dish.name))
                continue
            if menu_item.sales_cap is not None:
                if menu_item.sold_count + delta > menu_item.sales_cap:
                    errors.append(_catalog_sales_shortfall_message(dish.name))
                    continue
            deltas.append((menu_item, delta, dish_hex, total_qty))

        if errors:
            return False, errors

        for menu_item, delta, dish_hex, total_qty in deltas:
            MenuProfileItem.objects.filter(pk=menu_item.pk).update(
                sold_count=F('sold_count') + delta,
            )
            applied[dish_hex] = total_qty

        locked.catalog_sales_detail = applied
        locked.catalog_sales_applied = bool(applied)
        locked.save(update_fields=[
            'catalog_sales_detail', 'catalog_sales_applied', 'updated_at',
        ])
        order.catalog_sales_detail = locked.catalog_sales_detail
        order.catalog_sales_applied = locked.catalog_sales_applied

    return True, []


def release_catalog_sales_for_order(order) -> bool:
    """取消或改模拟支付时释放本单已占清单名额；幂等。"""
    from django.db import transaction

    from .models import BuyOrder
    from .product_shell_helpers import catalog_controls_shop_display

    if not order.catalog_sales_applied and not (order.catalog_sales_detail or {}):
        return False
    if not catalog_controls_shop_display(order.seller_id):
        return False

    profile = get_active_menu_profile(order.seller_id)
    if not profile:
        return False

    applied = order.catalog_sales_detail or {}
    if not applied:
        return False

    with transaction.atomic():
        locked = BuyOrder.objects.select_for_update().get(pk=order.pk)
        applied = dict(locked.catalog_sales_detail or {})
        if not applied:
            locked.catalog_sales_applied = False
            locked.save(update_fields=['catalog_sales_applied', 'updated_at'])
            return False

        for dish_hex, qty in applied.items():
            qty = int(qty or 0)
            if qty <= 0:
                continue
            menu_item = (
                MenuProfileItem.objects.select_for_update()
                .filter(profile=profile, dish_id=uuid.UUID(dish_hex))
                .first()
            )
            if menu_item:
                menu_item.sold_count = max(0, menu_item.sold_count - qty)
                menu_item.save(update_fields=['sold_count'])

        locked.catalog_sales_detail = {}
        locked.catalog_sales_applied = False
        locked.save(update_fields=[
            'catalog_sales_detail', 'catalog_sales_applied', 'updated_at',
        ])
        order.catalog_sales_detail = {}
        order.catalog_sales_applied = False

    return True
