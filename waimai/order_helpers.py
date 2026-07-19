# 订单与购物车相关的共用计算逻辑（避免多处各算各的）

from decimal import Decimal

from .product_helpers import (
    PRICE_TIER_GENERAL,
    cart_line_key,
    parse_cart_line_key,
    resolve_tier_price,
)


def get_shop_cart(session, seller_id):
    """读取某家店铺的购物车；兼容旧版整站共用一个 cart 的格式"""
    carts = session.get('carts')
    if carts is None and 'cart' in session:
        legacy = session.get('cart', {})
        session['carts'] = {'seller_001': legacy}
        del session['cart']
        session.modified = True
        carts = session['carts']
    return session.get('carts', {}).get(seller_id, {})


def set_shop_cart(session, seller_id, cart):
    """保存某家店铺的购物车"""
    carts = session.get('carts', {})
    if cart:
        carts[seller_id] = cart
    else:
        carts.pop(seller_id, None)
    session['carts'] = carts
    session.modified = True


def normalize_cart_keys(cart):
    """把旧版仅 dish_id 的键转为 general 档位（内存中不强制改 session）"""
    normalized = {}
    for key, qty in cart.items():
        did, tier = parse_cart_line_key(key)
        nk = cart_line_key(did, tier)
        normalized[nk] = normalized.get(nk, 0) + int(qty or 0)
    return normalized


def build_cart_items(cart, seller_id, for_checkout=False):
    """
    根据购物车内容构建明细（含价格档位）。
    for_checkout=False 时含数量为 0 的行；for_checkout=True 时只统计数量>0。
    返回 (cart_items, subtotal)。
    """
    from .models import Dish

    cart = normalize_cart_keys(cart)
    cart_items = []
    subtotal = Decimal('0.00')
    for line_key, qty in cart.items():
        dish_id, tier = parse_cart_line_key(line_key)
        try:
            dish = Dish.objects.get(dish_id=dish_id, seller_id=seller_id, is_active=True)
        except Dish.DoesNotExist:
            continue
        unit_price = resolve_tier_price(dish, tier)
        if unit_price is None:
            continue
        qty = int(qty)
        if qty <= 0 and for_checkout:
            continue
        if qty < 0:
            qty = 0
        item_total = (unit_price * qty) if qty > 0 else Decimal('0.00')
        if qty > 0:
            subtotal += item_total
        cart_items.append({
            'dish': dish,
            'quantity': qty,
            'item_total': item_total,
            'unit_price': unit_price,
            'price_tier': tier,
            'line_key': line_key,
        })
    return cart_items, subtotal


def cart_count_positive(cart):
    """购物车里有几件（只计数量大于 0）"""
    cart = normalize_cart_keys(cart)
    return sum(int(q) for q in cart.values() if int(q) > 0)


def cart_has_lines(cart):
    """购物车里是否还有菜品行（含数量为 0 未删除的）"""
    return bool(cart)


def parse_distance_km(value, default=2.5):
    """解析配送距离（公里）"""
    try:
        distance = float(value)
        if distance <= 0:
            return default
        return distance
    except (TypeError, ValueError):
        return default


def subtotal_from_dish_items(dish_items):
    """从订单 JSON 明细还原商品小计"""
    total = Decimal('0.00')
    for item in dish_items:
        total += Decimal(str(item['price'])) * int(item['quantity'])
    return total


def parse_fulfillment_type(value):
    """解析履约方式：主体下单 + 饮食三通道（兼容旧值 pickup → 打包）"""
    if value == 'pickup':
        return 'takeaway'
    if value in ('delivery', 'dine_in', 'takeaway'):
        return value
    return 'order'


def build_order_pricing(seller_id, subtotal, distance_km, fulfillment_type):
    """
    按取餐方式计算配送费与合计。
    堂食、打包：配送费为 0；外卖：走店铺配送费规则。
    返回 (delivery_fee, fee_detail) ；超配送范围时 delivery_fee 为 None。
    """
    from decimal import Decimal
    from .delivery_helpers import build_delivery_fee_breakdown

    if fulfillment_type == 'order':
        return Decimal('0.00'), {
            'lines': ['基础下单通道，不收配送费'],
            'fulfillment': 'order',
        }
    if fulfillment_type in ('dine_in', 'takeaway'):
        label = '堂食' if fulfillment_type == 'dine_in' else '打包'
        return Decimal('0.00'), {
            'lines': [f'{label}，不收配送费'],
            'fulfillment': fulfillment_type,
        }

    delivery_fee, fee_detail = build_delivery_fee_breakdown(seller_id, distance_km, subtotal)
    if fee_detail is not None:
        fee_detail = {**fee_detail, 'fulfillment': 'delivery'}
    return delivery_fee, fee_detail


def store_delivery_address(shop_profile, fulfillment_type):
    """堂食 / 打包订单写入的地址说明（含店铺地址）"""
    if fulfillment_type == 'order':
        return '【下单】由店家按商品说明或沟通约定处理'
    label = '堂食' if fulfillment_type == 'dine_in' else '打包'
    if shop_profile and shop_profile.address:
        return f'【{label}】{shop_profile.address}'
    return f'【{label}】请到店铺'


def pickup_delivery_address(shop_profile):
    """兼容旧调用：默认按打包"""
    return store_delivery_address(shop_profile, 'takeaway')


def build_order_timeline(order):
    """组装订单时间线，供详情页展示"""
    if order.is_basic_order():
        ready_label = '已备货'
    elif order.is_dine_in():
        ready_label = '已出餐'
    elif order.is_takeaway():
        ready_label = '已备好待取'
    else:
        ready_label = '出餐可配送'
    rows = [
        ('下单时间', order.created_at),
        ('支付时间', order.payment_time),
        ('开始备货', order.preparing_at),
    ]
    if order.estimated_ready_at:
        if order.is_basic_order():
            rows.append(('预计完成', order.estimated_ready_at))
        elif order.is_dine_in():
            rows.append(('预计出餐', order.estimated_ready_at))
        elif order.is_takeaway():
            rows.append(('预计可取餐', order.estimated_ready_at))
        else:
            rows.append(('预计出餐', order.estimated_ready_at))
    rows.append((ready_label, order.ready_at))
    delivery = getattr(order, 'delivery_order', None)
    if delivery:
        rows.extend([
            ('骑手接单', delivery.accepted_at),
            ('取餐时间', delivery.picked_up_at),
            ('送达时间', delivery.completed_at),
        ])
    if order.cancelled_at or order.order_status == 'cancelled':
        side = ''
        if order.cancel_side == 'buyer':
            side = '（买家）'
        elif order.cancel_side == 'shop':
            side = '（店家）'
        rows.append((f'取消时间{side}', order.cancelled_at))
    return rows


def dish_items_with_line_totals(dish_items):
    """订单明细加上每行小计"""
    lines = []
    for item in dish_items:
        qty = int(item['quantity'])
        price = Decimal(str(item['price']))
        lines.append({
            **item,
            'line_total': (price * qty).quantize(Decimal('0.01')),
        })
    return lines
