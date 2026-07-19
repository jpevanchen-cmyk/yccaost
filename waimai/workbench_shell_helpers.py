# 主体工作台壳：通用 Tab / 用语；饮食专属文案由已启用插件补充。

from __future__ import annotations


def _core_shell() -> dict:
    """主体默认展示：始终提供通用订单台；饮食岗名由插件补充。"""
    return {
        # 主体促成交易：通用「订单处理」始终可用
        'enabled_views': ['orders'],
        'tab_orders': '订单处理',
        'view_orders_title': '订单处理',
        'orders_empty': '当前没有需要处理的基础订单。',
        'orders_readonly_hint': (
            '👀 当前为<strong>只读</strong>：您可查看订单，'
            '改状态或确认收款需由店主勾选对应权限。'
        ),
        'tab_waiter': '前台',
        'tab_kitchen': '备货',
        'tab_rider': '配送',
        'view_waiter_title': '前台视角',
        'view_kitchen_title': '备货视角',
        'view_rider_title': '配送视角',
        'item_label': '商品',
        'unit_label': '件',
        'show_table_on_board': False,
        'table_caption': '现场标识',
        'kitchen_summary_title': '待备商品汇总',
        'kitchen_summary_empty': '当前没有待备商品。',
        'kitchen_empty_orders': '当前没有需要备货处理的订单。',
        'kitchen_log_title': '备货记录',
        'waiter_readonly_hint': (
            '👀 当前为<strong>只读预览</strong>：您可查看前台视角订单概况，'
            '操作请使用本岗位账号登录。'
        ),
        'kitchen_readonly_hint': (
            '👀 当前为<strong>只读预览</strong>：您可查看备货概况，'
            '操作请使用备货岗位账号登录。'
        ),
        'rider_readonly_hint': (
            '👀 当前为<strong>只读预览</strong>：您可查看本店配送概况，'
            '操作请使用配送岗位账号登录。'
        ),
        'pickup_label': '取货',
        'pickup_button': '我已取货',
        'pickup_disabled_title': '请先取货',
        'handoff_wait_text': '商品尚未完成交接，请等店内先交给配送员。',
        'serve_dine_in': '交付',
        'serve_takeaway': '交付',
        'serve_delivery': '交付',
        'serve_basic': '交付',
        'complete_dine_in': '订单完成',
        'complete_takeaway': '客人已取走',
        'rider_role_word': '配送员',
        'kitchen_role_word': '备货岗',
        'prep_word': '备货',
        'pickup_word': '取货',
        'rider_alert_item': '个配送单待接单，请及时处理！',
    }


def build_workbench_shell(seller_id: str) -> dict:
    """
    组装工作台展示壳。
    主体先给通用订单台；已启用插件可追加业态 Tab 与用语。
    """
    shell = _core_shell()
    from .plugin_runtime.registry import list_plugins, is_plugin_enabled

    for plugin in list_plugins():
        if not is_plugin_enabled(plugin.id, seller_id):
            continue
        contribute = getattr(plugin, 'contribute_workbench_shell', None)
        if not callable(contribute):
            continue
        extra = contribute(seller_id) or {}
        if not extra:
            continue
        # 插件追加业态 Tab
        if 'enabled_views' in extra:
            merged = list(dict.fromkeys(
                list(shell.get('enabled_views') or [])
                + list(extra.get('enabled_views') or [])
            ))
            extra = {**extra, 'enabled_views': merged}
        shell.update(extra)

    # 仅当饮食业态前台/备货面板出现时，收起主体「订单处理」
    # （仅开履约配送时仍保留订单台，方便干洗自送等业态）
    views = list(shell.get('enabled_views') or [])
    if any(v in ('waiter', 'kitchen') for v in views):
        views = [v for v in views if v != 'orders']
    shell['enabled_views'] = views
    return shell


def serve_unit_label_for_order(order) -> str:
    """按订单履约方式取「每件/每份」动作文案（读工作台壳）。"""
    shell = build_workbench_shell(order.seller_id)
    if getattr(order, 'is_basic_order', None) and order.is_basic_order():
        return shell['serve_basic']
    if order.is_dine_in():
        return shell['serve_dine_in']
    if order.is_takeaway():
        return shell['serve_takeaway']
    if getattr(order, 'fulfillment_type', '') == 'order':
        return shell['serve_basic']
    return shell['serve_delivery']
