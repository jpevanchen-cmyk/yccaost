# 主体订单壳：通用展示字段；饮食专属文案由已启用插件补充。

from __future__ import annotations


def _core_shell(order) -> dict:
    """主体默认展示（不含饮食业态话术）。"""
    label = order.get_fulfillment_display_short()
    if order.is_basic_order():
        return {
            'fulfillment_label': label,
            'cash_pending_banner': (
                '已选择<strong>下单 · 现金</strong>。订单已提交，店家将按商品说明或沟通约定处理。'
                '有事可在下方「订单沟通」留言。'
            ),
            'cash_payment_hint': (
                '基础下单：请按订单约定与店家完成现金付款。有事可在订单沟通里留言。'
            ),
            'estimated_ready_label': order.get_estimated_ready_label(),
            'show_table_label': False,
            'table_label_caption': '',
            'table_label': '',
            'location_kind': 'basic',
            'location_section_title': '📦 下单说明',
            'place_label': '履约说明',
            'show_distance': False,
            'list_place_prefix': '说明',
        }

    # 历史饮食/外卖单在插件关掉后仍要能核对，用中性事实文案
    has_table = bool((order.table_label or '').strip())
    if order.is_in_store():
        place = '就餐地点' if order.is_dine_in() else '取餐地点'
        return {
            'fulfillment_label': label,
            'cash_pending_banner': f'已选择<strong>{label} · 现金</strong>。订单已提交，请按店内约定付款。',
            'cash_payment_hint': order.get_cash_payment_hint(),
            'estimated_ready_label': order.get_estimated_ready_label(),
            'show_table_label': has_table,
            'table_label_caption': '现场标识',
            'table_label': order.table_label or '',
            'location_kind': 'in_store',
            'location_section_title': '🏪 到店信息',
            'place_label': place,
            'show_distance': False,
            'list_place_prefix': '地点',
        }

    return {
        'fulfillment_label': label,
        'cash_pending_banner': (
            f'已选择<strong>{label} · 现金</strong>。订单已提交，请按约定付款。'
        ),
        'cash_payment_hint': order.get_cash_payment_hint(),
        'estimated_ready_label': order.get_estimated_ready_label(),
        'show_table_label': has_table,
        'table_label_caption': '现场标识',
        'table_label': order.table_label or '',
        'location_kind': 'delivery',
        'location_section_title': '📍 配送信息',
        'place_label': '送达地址',
        'show_distance': True,
        'list_place_prefix': '地址',
    }


def build_order_shell(order) -> dict:
    """
    组装订单展示壳。
    主体先给通用字段；已启用插件可覆盖饮食专属文案。
    """
    shell = _core_shell(order)
    from .plugin_runtime.registry import list_plugins, is_plugin_enabled

    for plugin in list_plugins():
        if not is_plugin_enabled(plugin.id, order.seller_id):
            continue
        contribute = getattr(plugin, 'contribute_order_shell', None)
        if not callable(contribute):
            continue
        extra = contribute(order) or {}
        if extra:
            shell.update(extra)
    return shell


def order_search_placeholder(seller_id: str) -> str:
    """订单管理搜索框提示；饮食插件开启时才提桌号。"""
    from .plugin_runtime.registry import is_plugin_enabled

    if is_plugin_enabled('dining', seller_id):
        return '订单号、买家、桌号、地址、菜名、备注…'
    return '订单号、买家、地址、商品、备注…'


def fulfillment_filter_choices(seller_id: str):
    """
    筛选下拉：列出全部履约类型，便于核对历史单。
    （关饮食插件后仍可能有旧堂食/外卖单。）
    """
    from .models import BuyOrder

    return list(BuyOrder.FULFILLMENT_TYPE_CHOICES)
