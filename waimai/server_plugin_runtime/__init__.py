# 服务器级私人插件加载（公开仓仅保留薄插口；插件本体不进 Git）

from .bootstrap import bootstrap_server_plugins, is_owner_toolkit_enabled
from .registry import (
    enrich_server_home_context,
    get_server_plugin_urls,
    server_manager_nav_items,
)

__all__ = [
    'bootstrap_server_plugins',
    'is_owner_toolkit_enabled',
    'enrich_server_home_context',
    'get_server_plugin_urls',
    'server_manager_nav_items',
]
