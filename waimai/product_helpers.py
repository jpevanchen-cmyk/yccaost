# 商品三档价格、购物车档位、限购校验

from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from .models import BuyOrder, Dish
from .operating_helpers import get_operating_settings
from .product_labels import (
    format_dish_limit_hint,
    format_shop_special_limit_hint,
    shop_hint_label,
)

PRICE_TIER_GENERAL = 'general'
PRICE_TIER_MEMBER = 'member'
PRICE_TIER_SPECIAL = 'special'

TIER_LABELS = {
    PRICE_TIER_GENERAL: '通用价',
    PRICE_TIER_MEMBER: '会员价',
    PRICE_TIER_SPECIAL: '特价',
}


def cart_line_key(dish_id, tier=PRICE_TIER_GENERAL) -> str:
    """购物车一行 = 菜品 + 价格档位"""
    return f'{dish_id}|{tier}'


def parse_cart_line_key(key: str) -> tuple[str, str]:
    """解析购物车键；兼容旧版仅 dish_id"""
    key = str(key)
    if '|' in key:
        dish_part, tier = key.rsplit('|', 1)
        return dish_part, tier
    return key, PRICE_TIER_GENERAL


def resolve_tier_price(dish: Dish, tier: str) -> Decimal | None:
    """按档位算出实际单价"""
    if tier == PRICE_TIER_GENERAL:
        return dish.price
    if tier == PRICE_TIER_MEMBER:
        if not dish.member_price_enabled:
            return None
        if dish.member_price_mode == 'percent':
            pct = dish.member_price_percent if dish.member_price_percent is not None else Decimal('100')
            return (dish.price * pct / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
        if dish.member_price_fixed is None:
            return None
        return dish.member_price_fixed.quantize(Decimal('0.01'), ROUND_HALF_UP)
    if tier == PRICE_TIER_SPECIAL:
        if not dish.special_price_enabled:
            return None
        if dish.special_price_mode == 'percent':
            pct = dish.special_price_percent if dish.special_price_percent is not None else Decimal('100')
            return (dish.price * pct / Decimal('100')).quantize(Decimal('0.01'), ROUND_HALF_UP)
        if dish.special_price_fixed is None:
            return None
        return dish.special_price_fixed.quantize(Decimal('0.01'), ROUND_HALF_UP)
    return None


def _today_start():
    return timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)


def _iter_order_tier_lines(buyer_id, seller_id, dish_id=None, tier=None, today_only=False):
    """遍历订单明细中符合档位的行"""
    qs = BuyOrder.objects.filter(
        buyer_id=buyer_id, seller_id=seller_id,
    ).exclude(order_status__in=('cancelled', 'awaiting_payment'))
    if today_only:
        qs = qs.filter(created_at__gte=_today_start())
    dish_hex = str(dish_id).replace('-', '') if dish_id else None
    for order in qs.only('dish_items', 'created_at'):
        for item in order.dish_items or []:
            item_tier = item.get('price_tier', PRICE_TIER_GENERAL)
            if tier and item_tier != tier:
                continue
            if dish_id:
                item_id = str(item.get('dish_id', '')).replace('-', '')
                if item_id != dish_hex and item.get('dish_id') != str(dish_id):
                    continue
            yield int(item.get('quantity', 0) or 0)


def count_tier_purchases(
    buyer_id: str, seller_id: str, dish_id=None, tier=None, today_only=False,
) -> int:
    """统计买家已购数量（含进行中订单）"""
    if not buyer_id:
        return 0
    return sum(_iter_order_tier_lines(buyer_id, seller_id, dish_id, tier, today_only))


def count_tier_in_cart(cart: dict, seller_id: str, dish_id=None, tier=None) -> int:
    """购物车里某档位已有几件"""
    total = 0
    target_dish = str(dish_id) if dish_id else None
    for key, qty in cart.items():
        did, t = parse_cart_line_key(key)
        if tier and t != tier:
            continue
        if target_dish and did != target_dish and did.replace('-', '') != target_dish.replace('-', ''):
            continue
        total += int(qty or 0)
    return total


def special_pool_remaining(buyer_id: str, seller_id: str, cart: dict) -> int | None:
    """
    全店特价合计剩余可买份数；未设置上限返回 None 表示不限。
    """
    settings = get_operating_settings(seller_id)
    cap = settings.special_max_per_user
    if not cap:
        return None
    if not buyer_id:
        return 0
    bought = count_tier_purchases(buyer_id, seller_id, tier=PRICE_TIER_SPECIAL)
    in_cart = count_tier_in_cart(cart, seller_id, tier=PRICE_TIER_SPECIAL)
    return max(0, cap - bought - in_cart)


def buyer_special_pool_exhausted(buyer_id: str, seller_id: str, cart: dict) -> bool:
    """该买家特价总配额是否已用完"""
    remain = special_pool_remaining(buyer_id, seller_id, cart)
    return remain is not None and remain <= 0


def validate_tier_purchase(
    dish: Dish, tier: str, buyer, seller_id: str, quantity: int, cart: dict | None = None,
) -> tuple[bool, str]:
    """校验某一档位能否购买指定数量"""
    cart = cart or {}
    price = resolve_tier_price(dish, tier)
    if price is None:
        return False, f'「{dish.name}」未开放{TIER_LABELS.get(tier, tier)}'

    if tier == PRICE_TIER_GENERAL:
        pass  # 游客可买
    elif tier in (PRICE_TIER_MEMBER, PRICE_TIER_SPECIAL):
        if not buyer or not buyer.is_authenticated:
            return False, f'「{dish.name}」{TIER_LABELS[tier]}须登录后购买'
        if buyer.role != 'buyer':
            return False, f'「{dish.name}」仅买家账号可购'
    else:
        return False, '无效的价格档位'

    buyer_id = buyer.username if buyer and buyer.is_authenticated else ''

    if tier == PRICE_TIER_MEMBER:
        if dish.member_daily_limit:
            bought = count_tier_purchases(
                buyer_id, seller_id, dish.dish_id, PRICE_TIER_MEMBER, today_only=True,
            )
            in_cart = count_tier_in_cart(cart, seller_id, dish.dish_id, PRICE_TIER_MEMBER)
            if bought + in_cart + quantity > dish.member_daily_limit:
                return False, f'「{dish.name}」会员价今日限购 {dish.member_daily_limit} 份'
        if dish.member_total_limit:
            bought = count_tier_purchases(
                buyer_id, seller_id, dish.dish_id, PRICE_TIER_MEMBER,
            )
            in_cart = count_tier_in_cart(cart, seller_id, dish.dish_id, PRICE_TIER_MEMBER)
            if bought + in_cart + quantity > dish.member_total_limit:
                return False, f'「{dish.name}」会员价累计限购 {dish.member_total_limit} 份'

    if tier == PRICE_TIER_SPECIAL:
        remain = special_pool_remaining(buyer_id, seller_id, cart)
        if remain is not None and quantity > remain:
            return False, f'特价活动名额已用完（全店每人上限），无法再买特价'
        if dish.special_per_dish_limit:
            bought = count_tier_purchases(
                buyer_id, seller_id, dish.dish_id, PRICE_TIER_SPECIAL,
            )
            in_cart = count_tier_in_cart(cart, seller_id, dish.dish_id, PRICE_TIER_SPECIAL)
            if bought + in_cart + quantity > dish.special_per_dish_limit:
                return False, f'「{dish.name}」特价限购 {dish.special_per_dish_limit} 份'

    # 菜单清单可售上限（仍按菜品计，不区分档位）
    from .menu_helpers import get_menu_item_for_dish, menu_item_allows_tier
    menu_item = get_menu_item_for_dish(seller_id, dish.dish_id)
    if tier in (PRICE_TIER_MEMBER, PRICE_TIER_SPECIAL) and not menu_item_allows_tier(
        menu_item, tier, seller_id,
    ):
        return False, f'「{dish.name}」当前菜单未开放{TIER_LABELS.get(tier, tier)}'
    if menu_item and menu_item.sales_cap is not None:
        if menu_item.sold_count + quantity > menu_item.sales_cap:
            remain = max(0, menu_item.sales_cap - menu_item.sold_count)
            return False, f'「{dish.name}」本日清单仅剩 {remain} 份'

    return True, ''


def build_tier_purchase_hints(dish: Dish, tier: str, seller_id: str, menu_item=None) -> list[str]:
    """
    根据商品管理与全店规则，生成客人可见的购买条件说明（与下单校验一致，勿手写重复）。
    """
    hints: list[str] = []
    if tier == PRICE_TIER_GENERAL:
        return hints

    if tier in (PRICE_TIER_MEMBER, PRICE_TIER_SPECIAL):
        hints.append(shop_hint_label('login_required_buyer'))

    if tier == PRICE_TIER_MEMBER:
        if dish.member_daily_limit:
            hints.append(format_dish_limit_hint('member_daily_limit', dish.member_daily_limit))
        if dish.member_total_limit:
            hints.append(format_dish_limit_hint('member_total_limit', dish.member_total_limit))

    if tier == PRICE_TIER_SPECIAL:
        if dish.special_per_dish_limit:
            hints.append(format_dish_limit_hint('special_per_dish_limit', dish.special_per_dish_limit))
        settings = get_operating_settings(seller_id)
        if settings.special_max_per_user:
            hints.append(format_shop_special_limit_hint(
                'special_max_per_user', settings.special_max_per_user,
            ))
        code = (settings.special_pool_code or '').strip()
        if code:
            hints.append(f'{shop_hint_label("activity_prefix")}：{code}')

    if menu_item and menu_item.sales_cap is not None:
        hints.append(
            f'{shop_hint_label("menu_sales_cap")} {menu_item.sales_cap} 份 '
            f'{shop_hint_label("menu_sales_cap_shared")}'
        )

    return hints


def build_tier_display_name(dish: Dish, tier: str) -> str:
    """店铺页展示名：会员价/特价在菜名后标注"""
    if tier == PRICE_TIER_MEMBER:
        return f'{dish.name}（会员价）'
    if tier == PRICE_TIER_SPECIAL:
        return f'{dish.name}（特价）'
    return dish.name


def build_dish_tier_options(
    dish: Dish, buyer, seller_id: str, cart: dict, menu_item=None,
) -> list[dict]:
    """点菜页：该菜有哪些档位可选"""
    from .menu_helpers import get_menu_item_for_dish, menu_item_allows_tier

    options = []
    buyer_id = buyer.username if buyer and buyer.is_authenticated else ''
    special_exhausted = buyer_special_pool_exhausted(buyer_id, seller_id, cart)
    if menu_item is None:
        menu_item = get_menu_item_for_dish(seller_id, dish.dish_id)

    for tier in (PRICE_TIER_GENERAL, PRICE_TIER_MEMBER, PRICE_TIER_SPECIAL):
        if not menu_item_allows_tier(menu_item, tier, seller_id):
            continue
        price = resolve_tier_price(dish, tier)
        if price is None:
            continue
        ok, reason = validate_tier_purchase(dish, tier, buyer, seller_id, 1, cart)
        disabled = not ok
        if tier == PRICE_TIER_SPECIAL and special_exhausted:
            disabled = True
            reason = '特价名额已用完'
        options.append({
            'tier': tier,
            'label': TIER_LABELS[tier],
            'display_name': build_tier_display_name(dish, tier),
            'price': price,
            'disabled': disabled,
            'reason': reason if disabled else '',
            'purchase_hints': build_tier_purchase_hints(dish, tier, seller_id, menu_item),
        })
    return options


def parse_decimal_field(val, default=None):
    """表单小数解析"""
    val = (val or '').strip()
    if not val:
        return default
    try:
        return Decimal(val)
    except Exception:
        return default


def parse_optional_int(val):
    val = (val or '').strip()
    if not val:
        return None
    if val.isdigit() and int(val) > 0:
        return int(val)
    return None
