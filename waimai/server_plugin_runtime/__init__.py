# 整机私人插件加载（公开仓保留薄插口；插件本体可不进 Git）

from .bootstrap import bootstrap_server_plugins, is_owner_toolkit_enabled
from .django_hooks import apply_server_plugins_to_django
from .registry import (
    enrich_server_home_context,
    get_server_middleware_classes,
    get_server_plugin_urls,
    server_manager_nav_items,
)

__all__ = [
    'apply_server_plugins_to_django',
    'bootstrap_server_plugins',
    'is_owner_toolkit_enabled',
    'enrich_server_home_context',
    'get_server_middleware_classes',
    'get_server_plugin_urls',
    'server_manager_nav_items',
]
