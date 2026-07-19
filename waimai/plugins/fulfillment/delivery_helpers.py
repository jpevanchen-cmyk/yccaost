# 履约包：店铺配送费计算（读取店铺配置，统一入口）

from decimal import Decimal

from waimai.models import ShopDeliverySettings


def get_delivery_settings(seller_id):
    """获取店铺配送费配置，没有则创建默认配置"""
    settings, _ = ShopDeliverySettings.objects.get_or_create(seller_id=seller_id)
    return settings


def calc_distance_fee(settings, distance_km, subtotal):
    """按店铺配置的距离规则计算应收配送费（不含满额免运等减免）"""
    distance = Decimal(str(distance_km))
    max_km = Decimal(str(settings.max_distance_km))
    if distance > max_km:
        return None

    # 新建默认配置时，模型默认值在首次读出前可能仍是普通小数；统一转成精确金额小数。
    rate = Decimal(str(settings.per_km_rate_0_3))
    multiplier_3_6 = Decimal(str(settings.multiplier_3_6))
    multiplier_6_9 = Decimal(str(settings.multiplier_6_9))
    min_fee = Decimal(str(settings.min_delivery_fee))
    if distance <= 3:
        fee = distance * rate
        segment = f'{distance} 公里 × {rate} 元/公里'
    elif distance <= 6:
        fee = Decimal('3') * rate + (distance - Decimal('3')) * rate * multiplier_3_6
        segment = (
            f'前3公里 {Decimal("3") * rate} 元 + 超出 {distance - Decimal("3")} 公里 × '
            f'{rate}×{multiplier_3_6} 元/公里'
        )
    else:
        fee = (
            Decimal('3') * rate
            + Decimal('3') * rate * multiplier_3_6
            + (distance - Decimal('6')) * rate * multiplier_6_9
        )
        segment = (
            f'前3公里 {Decimal("3") * rate} 元 + 3～6公里段 + 超出 {distance - Decimal("6")} 公里 × '
            f'{rate}×{multiplier_6_9} 元/公里'
        )

    fee = max(fee, min_fee)
    return fee.quantize(Decimal('0.01')), segment


def build_delivery_fee_breakdown(seller_id, distance_km, subtotal):
    """
    生成配送费计算清单（下单时保存，买家卖家详情页展示）。
    返回 (final_fee, detail_dict)；超距时 final_fee 为 None。
    """
    settings = get_delivery_settings(seller_id)
    subtotal = Decimal(str(subtotal))
    lines = []

    distance_fee, segment_desc = calc_distance_fee(settings, distance_km, subtotal)
    if distance_fee is None:
        return None, {
            'lines': [f'配送距离 {distance_km} 公里，超过店铺最远配送 {settings.max_distance_km} 公里，无法配送'],
            'final_fee': None,
        }

    lines.append(f'① 按距离计算：{segment_desc} → ¥{distance_fee}')
    fee = distance_fee

    if fee < settings.min_delivery_fee:
        lines.append(f'② 不低于最低配送费 ¥{settings.min_delivery_fee}')
        fee = settings.min_delivery_fee
    else:
        lines.append(f'② 已满足最低配送费 ¥{settings.min_delivery_fee}')

    if settings.discount_percent and settings.discount_percent > 0:
        cap = (subtotal * settings.discount_percent / Decimal('100')).quantize(Decimal('0.01'))
        before = fee
        fee = max(Decimal('0.00'), fee - cap)
        lines.append(
            f'③ 按商品金额 {settings.discount_percent}% 减免：'
            f'¥{subtotal} × {settings.discount_percent}% = 最多减 ¥{cap} → ¥{before} − ¥{cap} = ¥{fee}'
        )

    if settings.free_delivery_threshold and subtotal >= settings.free_delivery_threshold:
        lines.append(
            f'④ 满 ¥{settings.free_delivery_threshold} 免配送费：商品 ¥{subtotal} 已达标 → 配送费 ¥0'
        )
        fee = Decimal('0.00')
    else:
        if settings.free_delivery_threshold:
            lines.append(
                f'④ 满 ¥{settings.free_delivery_threshold} 免运未达标（商品 ¥{subtotal}）'
            )
        fee = max(fee, settings.min_delivery_fee) if fee > 0 else fee

    if fee > 0 and fee < settings.min_delivery_fee:
        fee = settings.min_delivery_fee

    fee = fee.quantize(Decimal('0.01'))
    lines.append(f'⑤ 买家应付配送费：¥{fee}')

    return fee, {
        'distance_km': float(distance_km),
        'subtotal': str(subtotal),
        'lines': lines,
        'final_fee': str(fee),
    }


def calc_order_delivery_fee(seller_id, distance_km, subtotal):
    """统一计算买家应付配送费（含 breakdown）"""
    fee, _ = build_delivery_fee_breakdown(seller_id, distance_km, subtotal)
    return fee
