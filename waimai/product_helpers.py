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
    from .time_helpers import local_day_start

    return local_day_start()


def _iter_order_tier_lines(buyer_id, seller_id, dish_id=None, tier=None, today_only=False):
    """遍历订单明细中符合档位的行（已下单即占名额，仅取消订单释放）。"""
    qs = BuyOrder.objects.filter(
        buyer_id=buyer_id, seller_id=seller_id,
    ).exclude(order_status='cancelled')
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


def _project_line_cart(cart: dict, line_key: str | None, line_qty: int) -> dict:
    """按单行目标件数生成校验用购物车快照。"""
    projected = dict(cart or {})
    if not line_key:
        return projected
    if line_qty <= 0:
        projected.pop(line_key, None)
    else:
        projected[line_key] = line_qty
    return projected


def _tier_quantity_after(cart: dict, line_key: str | None, line_qty: int, add_qty: int,
                         seller_id: str, dish_id, tier: str) -> int:
    """
    校验用：该档位在本店购物车中的目标总件数。
    line_key 有值时 line_qty 为该行目标件数；否则 add_qty 为拟追加件数。
    """
    if line_key:
        return count_tier_in_cart(
            _project_line_cart(cart, line_key, line_qty), seller_id, dish_id, tier,
        )
    return count_tier_in_cart(cart, seller_id, dish_id, tier) + int(add_qty or 0)


def _special_quantity_after(cart: dict, line_key: str | None, line_qty: int, add_qty: int,
                            seller_id: str) -> int:
    if line_key:
        return count_tier_in_cart(
            _project_line_cart(cart, line_key, line_qty), seller_id, tier=PRICE_TIER_SPECIAL,
        )
    return count_tier_in_cart(cart, seller_id, tier=PRICE_TIER_SPECIAL) + int(add_qty or 0)


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
    line_key: str | None = None,
) -> tuple[bool, str]:
    """
    校验某一档位能否购买指定数量。
    line_key 有值：quantity 为该行在购物车中的目标总件数；
    无 line_key：quantity 为拟追加件数（如再点一次「加入购物车」）。
    """
    cart = cart or {}
    from .product_shell_helpers import product_unit_label

    unit = product_unit_label(seller_id)
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
    add_qty = quantity if not line_key else 0
    line_qty = quantity if line_key else 0

    if tier == PRICE_TIER_MEMBER:
        if dish.member_daily_limit:
            bought = count_tier_purchases(
                buyer_id, seller_id, dish.dish_id, PRICE_TIER_MEMBER, today_only=True,
            )
            want = _tier_quantity_after(
                cart, line_key, line_qty, add_qty, seller_id, dish.dish_id, PRICE_TIER_MEMBER,
            )
            if bought + want > dish.member_daily_limit:
                return False, f'「{dish.name}」会员价今日限购 {dish.member_daily_limit} {unit}'
        if dish.member_total_limit:
            bought = count_tier_purchases(
                buyer_id, seller_id, dish.dish_id, PRICE_TIER_MEMBER,
            )
            want = _tier_quantity_after(
                cart, line_key, line_qty, add_qty, seller_id, dish.dish_id, PRICE_TIER_MEMBER,
            )
            if bought + want > dish.member_total_limit:
                return False, f'「{dish.name}」会员价累计限购 {dish.member_total_limit} {unit}'

    if tier == PRICE_TIER_SPECIAL:
        settings = get_operating_settings(seller_id)
        cap = settings.special_max_per_user
        if cap:
            bought = count_tier_purchases(buyer_id, seller_id, tier=PRICE_TIER_SPECIAL)
            want = _special_quantity_after(cart, line_key, line_qty, add_qty, seller_id)
            if bought + want > cap:
                return False, f'特价活动名额已用完（全店每人上限），无法再买特价'
        if dish.special_per_dish_limit:
            bought = count_tier_purchases(
                buyer_id, seller_id, dish.dish_id, PRICE_TIER_SPECIAL,
            )
            want = _tier_quantity_after(
                cart, line_key, line_qty, add_qty, seller_id, dish.dish_id, PRICE_TIER_SPECIAL,
            )
            if bought + want > dish.special_per_dish_limit:
                return False, f'「{dish.name}」特价限购 {dish.special_per_dish_limit} {unit}'

    # 使用中商品列表：按清单控制会员/特价展示与可售上限（不依赖饮食插件）。
    from .menu_helpers import get_menu_item_for_dish, menu_item_allows_tier
    from .product_shell_helpers import build_product_shell, catalog_controls_shop_display

    if catalog_controls_shop_display(seller_id):
        menu_item = get_menu_item_for_dish(seller_id, dish.dish_id)
        if not menu_item_allows_tier(menu_item, tier, seller_id):
            word = build_product_shell(seller_id).get('catalog_word', '商品列表')
            return False, f'「{dish.name}」当前{word}未开放{TIER_LABELS.get(tier, tier)}'
        if menu_item and menu_item.sales_cap is not None:
            if menu_item.sold_count + quantity > menu_item.sales_cap:
                remain = max(0, menu_item.sales_cap - menu_item.sold_count)
                return False, f'「{dish.name}」本列表仅剩 {remain} {unit}'

    return True, ''


def build_tier_purchase_hints(dish: Dish, tier: str, seller_id: str, menu_item=None) -> list[str]:
    """
    根据商品管理与全店规则，生成客人可见的购买条件说明（与下单校验一致，勿手写重复）。
    """
    hints: list[str] = []
    from .product_shell_helpers import product_unit_label

    unit = product_unit_label(seller_id)
    if tier == PRICE_TIER_GENERAL:
        return hints

    if tier in (PRICE_TIER_MEMBER, PRICE_TIER_SPECIAL):
        hints.append(shop_hint_label('login_required_buyer'))

    if tier == PRICE_TIER_MEMBER:
        if dish.member_daily_limit:
            hints.append(format_dish_limit_hint(
                'member_daily_limit', dish.member_daily_limit, unit,
            ))
        if dish.member_total_limit:
            hints.append(format_dish_limit_hint(
                'member_total_limit', dish.member_total_limit, unit,
            ))

    if tier == PRICE_TIER_SPECIAL:
        if dish.special_per_dish_limit:
            hints.append(format_dish_limit_hint(
                'special_per_dish_limit', dish.special_per_dish_limit, unit,
            ))
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


def get_tier_description(dish: Dish, tier: str) -> str:
    """按价格档位取商品描述；普通描述沿用原 description 字段。"""
    if tier == PRICE_TIER_MEMBER:
        return (dish.description_member or '').strip()
    if tier == PRICE_TIER_SPECIAL:
        return (dish.description_special or '').strip()
    return (dish.description or '').strip()


def build_dish_tier_options(
    dish: Dish, buyer, seller_id: str, cart: dict, menu_item=None,
) -> list[dict]:
    """点菜页：该菜有哪些档位可选"""
    from .menu_helpers import get_active_menu_profile, get_menu_item_for_dish, menu_item_allows_tier
    from .product_shell_helpers import build_product_shell

    options = []
    buyer_id = buyer.username if buyer and buyer.is_authenticated else ''
    special_exhausted = buyer_special_pool_exhausted(buyer_id, seller_id, cart)
    shell = build_product_shell(seller_id)
    use_catalog = bool(shell['show_menu_catalog'])
    active_profile = get_active_menu_profile(seller_id) if use_catalog else None
    if active_profile and menu_item is None:
        menu_item = get_menu_item_for_dish(seller_id, dish.dish_id)

    for tier in (PRICE_TIER_GENERAL, PRICE_TIER_MEMBER, PRICE_TIER_SPECIAL):
        if active_profile and not menu_item_allows_tier(menu_item, tier, seller_id):
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
            'description': get_tier_description(dish, tier),
            'price': price,
            'disabled': disabled,
            'reason': reason if disabled else '',
            'purchase_hints': build_tier_purchase_hints(dish, tier, seller_id, menu_item),
        })
    return options


def build_dish_shop_compact(dish: Dish, tier_options: list[dict], image_gallery: list[dict]) -> dict:
    """点菜页简化行：首图缩略、最低价、一行简介（展开后见完整档位与加购）。"""
    thumb_url = image_gallery[0]['url'] if image_gallery else ''
    cheapest = None
    for opt in tier_options:
        price = opt.get('price')
        if price is None:
            continue
        if cheapest is None or price < cheapest['price']:
            cheapest = opt
    summary = (dish.description or '').strip()
    summary = ' '.join(summary.split())
    dish_key = dish.dish_id.hex[:8]
    return {
        'name': dish.name,
        'thumb_url': thumb_url,
        'cheapest_price': cheapest['price'] if cheapest else None,
        'cheapest_tier': cheapest['tier'] if cheapest else '',
        'cheapest_tier_label': cheapest['label'] if cheapest else '',
        'summary': summary,
        'group_anchor': f'dish-group-{dish_key}',
    }


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
