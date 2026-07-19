# 饮食插件：向主体工作台壳补充服务员/后厨用语（配送页签已迁履约插件）

from __future__ import annotations


def contribute_dining_workbench_shell(seller_id: str) -> dict:
    """饮食业态开启时的工作台展示字段（不含配送页签；配送页签由履约插件挂）。"""
    return {
        'enabled_views': ['waiter', 'kitchen'],
        'tab_waiter': '服务员',
        'tab_kitchen': '后厨',
        'view_waiter_title': '服务员视角',
        'view_kitchen_title': '后厨视角',
        'item_label': '菜品',
        'unit_label': '份',
        'show_table_on_board': True,
        'table_caption': '桌台',
        'kitchen_summary_title': '待备菜品汇总',
        'kitchen_summary_empty': '当前没有待备菜品。',
        'kitchen_empty_orders': '当前没有需要后厨处理的订单。',
        'kitchen_log_title': '后厨记录',
        'waiter_readonly_hint': (
            '👀 当前为<strong>只读预览</strong>：您可查看服务员视角订单概况，'
            '操作请使用本岗位账号登录。'
        ),
        'kitchen_readonly_hint': (
            '👀 当前为<strong>只读预览</strong>：您可查看后厨待备概况，'
            '操作请使用后厨账号登录。'
        ),
        # 饮食叫法：履约插件若同时开启，会先写中性词，再被下面覆盖为骑手话术
        'tab_rider': '骑手',
        'view_rider_title': '骑手视角',
        'rider_readonly_hint': (
            '👀 当前为<strong>只读预览</strong>：您可查看本店配送概况，'
            '操作请使用骑手账号登录。'
        ),
        'pickup_label': '取餐',
        'pickup_button': '我已取餐',
        'pickup_disabled_title': '请先取餐',
        'handoff_wait_text': '餐品尚未完成交接，请等店内先交给骑手。',
        'serve_dine_in': '上桌',
        'serve_takeaway': '交付',
        'serve_delivery': '交给骑手',
        'serve_basic': '交付',
        'complete_dine_in': '用餐完成',
        'complete_takeaway': '客人已取走',
        'rider_role_word': '骑手',
        'kitchen_role_word': '后厨',
        'prep_word': '备餐',
        'pickup_word': '取餐',
        'rider_alert_item': '个外卖单待接单，请及时处理！',
    }
