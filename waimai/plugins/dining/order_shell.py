# 饮食插件：向主体订单壳补充堂食/打包/外卖展示文案

from __future__ import annotations


def contribute_dining_order_shell(order) -> dict:
    """仅处理饮食三通道；主体「下单」不介入。"""
    if getattr(order, 'fulfillment_type', '') == 'order':
        return {}

    label = order.get_fulfillment_display_short()
    has_table = bool((order.table_label or '').strip())

    if order.is_dine_in():
        return {
            'fulfillment_label': label,
            'cash_pending_banner': (
                '已选择<strong>堂食 · 到店付现金</strong>。订单已提交，店家将为您备餐并告知预计出餐时间。'
                '有事可在下方「订单沟通」留言。'
            ),
            'cash_payment_hint': order.get_cash_payment_hint(),
            'estimated_ready_label': order.get_estimated_ready_label(),
            'show_table_label': has_table,
            'table_label_caption': '桌台',
            'table_label': order.table_label or '',
            'location_kind': 'in_store',
            'location_section_title': '🏪 到店信息',
            'place_label': '就餐地点',
            'show_distance': False,
            'list_place_prefix': '地点',
        }

    if order.is_takeaway():
        return {
            'fulfillment_label': label,
            'cash_pending_banner': (
                '已选择<strong>打包 · 到店付现金</strong>。订单已提交，店家将为您备货并告知预计可取餐时间。'
                '有事可在下方「订单沟通」留言。'
            ),
            'cash_payment_hint': order.get_cash_payment_hint(),
            'estimated_ready_label': order.get_estimated_ready_label(),
            'show_table_label': has_table,
            'table_label_caption': '桌台',
            'table_label': order.table_label or '',
            'location_kind': 'in_store',
            'location_section_title': '🏪 到店信息',
            'place_label': '取餐地点',
            'show_distance': False,
            'list_place_prefix': '地点',
        }

    # 外卖
    return {
        'fulfillment_label': label,
        'cash_pending_banner': (
            '已选择<strong>外卖 · 货到付款</strong>。送达时请付现金；'
            '店家会先备货并派单，骑手送达时收款。'
        ),
        'cash_payment_hint': order.get_cash_payment_hint(),
        'estimated_ready_label': order.get_estimated_ready_label(),
        'show_table_label': False,
        'table_label_caption': '',
        'table_label': '',
        'location_kind': 'delivery',
        'location_section_title': '📍 配送信息',
        'place_label': '送达地址',
        'show_distance': True,
        'list_place_prefix': '地址',
    }
