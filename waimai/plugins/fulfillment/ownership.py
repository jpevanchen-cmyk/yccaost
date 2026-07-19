# 履约包：数据归属说明与统一入口（表仍在主体库，逻辑归属履约）
#
# 归属本包（表暂仍定义在 waimai.models，避免本刀大迁移）：
# - ShopDeliverySettings  店铺配送费规则
# - DeliveryOrder         配送单（与买单一对一）
#
# 相关但暂留主体/饮食侧的字段（由履约开关门禁）：
# - ShopOperatingSettings.auto_dispatch_enabled / delivery_handoff_mode
# - ShopPaymentSettings.enable_cod（外卖货到付款）

from __future__ import annotations


def fulfillment_plugin_enabled(seller_id: str) -> bool:
    """本店是否启用履约配送插件。"""
    from waimai.plugin_runtime.registry import is_plugin_enabled

    return is_plugin_enabled('fulfillment', seller_id)


def get_delivery_order_model():
    """配送单模型（归属履约；表仍在主体）。"""
    from waimai.models import DeliveryOrder

    return DeliveryOrder


def get_shop_delivery_settings_model():
    """配送费配置模型（归属履约；表仍在主体）。"""
    from waimai.models import ShopDeliverySettings

    return ShopDeliverySettings
