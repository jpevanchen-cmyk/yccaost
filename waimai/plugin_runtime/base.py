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

    def contribute_order_shell(self, order) -> dict:
        """
        向主体订单壳补充业态展示字段（文案、桌台等）。
        未实现则返回空字典；仅覆盖本业态相关订单。
        """
        return {}

    def contribute_product_shell(self, seller_id: str) -> dict:
        """向主体商品壳补充业态目录、名称与帮助文案。"""
        return {}

    def contribute_workbench_shell(self, seller_id: str) -> dict:
        """向主体工作台壳补充业态岗名、桌台与服务用语。"""
        return {}

    def staff_permission_definitions(self, seller_id: str) -> list[dict]:
        """向子账号管理页贡献可勾选的业态权限。"""
        return []

    def staff_account_presets(self, seller_id: str) -> list[dict]:
        """向子账号管理页贡献可选的职务预置模板。"""
        return []
