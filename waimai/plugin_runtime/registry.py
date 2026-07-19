# 插件注册表：谁装了、谁开着、导航怎么拼

from __future__ import annotations

from .base import Plugin, SellerNavItem

# 已注册插件（进程内；启动时由 bootstrap 装入）
_REGISTRY: dict[str, Plugin] = {}

# 核心卖家导航（不属于任何业态插件）
_CORE_SELLER_NAV: list[SellerNavItem] = [
    SellerNavItem('homepage', '店铺主页', '🏠', '主页', order=10),
    SellerNavItem('orders', '订单管理', '📋', '订单', order=20),
    SellerNavItem('products', '商品上架', '🛍', '商品', order=30),
    # 营业状态属店铺经营基础（A.15.10）；堂食由饮食插件提供（order=40）
    SellerNavItem('operating', '营业状态', '🕐', '营业', order=35),
    SellerNavItem('workbench', '员工工作台', '👥', '工作台', order=50),
    # 配送费规则暂仍挂核心（以后迁履约插件）；试验阶段保持可见
    SellerNavItem('delivery', '配送费规则', '🚚', '配送费', order=60),
    SellerNavItem('payment', '支付设置', '💳', '支付', order=70),
    SellerNavItem('audit', '操作留痕', '📝', '留痕', order=80),
    # 插件试验面板：看得到、关得掉
    SellerNavItem('plugins', '插件试验', '🧩', '插件', order=200),
]


def register_plugin(plugin: Plugin) -> None:
    """注册插件；同 id 后注册覆盖先注册（便于试验热替换）"""
    if not getattr(plugin, 'id', None):
        raise ValueError('插件必须有稳定 id')
    _REGISTRY[plugin.id] = plugin


def get_plugin(plugin_id: str) -> Plugin | None:
    return _REGISTRY.get(plugin_id)


def list_plugins() -> list[Plugin]:
    return sorted(_REGISTRY.values(), key=lambda p: p.id)


def is_plugin_enabled(plugin_id: str, seller_id: str) -> bool:
    """
    读店铺开关。饮食插件默认开（兼容现店）；其它未知名默认关。
    """
    if plugin_id == 'dining':
        from ..operating_helpers import get_operating_settings

        settings = get_operating_settings(seller_id)
        return bool(getattr(settings, 'plugin_dining_enabled', True))
    # 尚未做店铺级开关的插件：有注册即视为开（试验）
    return plugin_id in _REGISTRY


def set_plugin_enabled(plugin_id: str, seller_id: str, enabled: bool) -> tuple[bool, str]:
    """改店铺插件开关；目前仅支持饮食插件。"""
    if plugin_id != 'dining':
        return False, '该插件尚不支持在本页开关'
    from ..operating_helpers import get_operating_settings

    settings = get_operating_settings(seller_id)
    settings.plugin_dining_enabled = bool(enabled)
    settings.save(update_fields=['plugin_dining_enabled'])
    state = '已启用' if enabled else '已停用'
    return True, f'饮食插件{state}'


def collect_seller_nav_items(seller_id: str) -> list[SellerNavItem]:
    """核心导航 + 已启用插件贡献的导航，按 order 排序。"""
    items = list(_CORE_SELLER_NAV)
    for plugin in list_plugins():
        if not is_plugin_enabled(plugin.id, seller_id):
            continue
        items.extend(plugin.seller_nav_items())
    items.sort(key=lambda x: (x.order, x.section))
    return items


def plugin_owns_seller_section(section: str) -> str | None:
    """若某分区由插件声明，返回插件 id；否则 None（属核心）。"""
    for plugin in list_plugins():
        for item in plugin.seller_nav_items():
            if item.section == section:
                return plugin.id
    return None
