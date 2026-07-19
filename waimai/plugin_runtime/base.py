# 插件接口约定（试验版）：先够用，再逐步加挂载点

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SellerNavItem:
    """卖家后台导航一项（由核心或插件声明）"""

    section: str
    label: str
    icon: str = ''
    mobile_label: str = ''
    # 越小越靠前；核心段常用 10～90，插件从 100 起
    order: int = 100


class Plugin:
    """业态 / 能力插件基类"""

    # 稳定编号，勿随意改（以后独立成包仍用此 id）
    id: str = ''
    name: str = ''
    description: str = ''

    def seller_nav_items(self) -> list[SellerNavItem]:
        """本插件向卖家后台贡献的导航（未启用时不会出现）"""
        return []

    def is_enabled_for_shop(self, seller_id: str) -> bool:
        """该店是否启用本插件；子类可覆盖（例如读店铺开关）"""
        from .registry import is_plugin_enabled

        return is_plugin_enabled(self.id, seller_id)
