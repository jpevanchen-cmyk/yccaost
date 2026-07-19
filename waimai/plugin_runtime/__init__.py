# 插件运行时（同仓试验）：主体只认正式注册与开关，不认行业内部细节。
# 目标态可再拆成独立安装包；现阶段插件代码仍在本仓库 plugins/ 下。

from .registry import (
    collect_seller_nav_items,
    get_plugin,
    is_plugin_enabled,
    list_plugins,
    register_plugin,
    set_plugin_enabled,
)

__all__ = [
    'register_plugin',
    'get_plugin',
    'list_plugins',
    'is_plugin_enabled',
    'set_plugin_enabled',
    'collect_seller_nav_items',
]
