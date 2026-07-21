# 服务器级插件注册表（饮食/履约插件在 plugin_runtime，这里是整机私人扩展）

from __future__ import annotations

from typing import Any

_PLUGINS: list[Any] = []
_SERVER_BLOCK_SPECS: dict[str, Any] = {}


def register_server_plugin(plugin) -> None:
    """登记一个服务器级私人插件实例"""
    _PLUGINS.append(plugin)


def register_server_block_spec(spec) -> None:
    """登记服务器主页积木类型（如「联系我们」）"""
    _SERVER_BLOCK_SPECS[spec.code] = spec


def list_server_plugins() -> list:
    return list(_PLUGINS)


def get_server_block_spec(code: str):
    return _SERVER_BLOCK_SPECS.get(code)


def server_manager_nav_items() -> list[dict]:
    """服务器设置顶栏额外入口（仅私人插件贡献）"""
    items: list[dict] = []
    for plugin in _PLUGINS:
        fn = getattr(plugin, 'server_settings_nav_items', None)
        if callable(fn):
            items.extend(fn())
    return items


def get_server_plugin_urls() -> list:
    """合并私人插件 URL（挂到 urlpatterns 末尾）"""
    patterns = []
    for plugin in _PLUGINS:
        fn = getattr(plugin, 'urlpatterns', None)
        if callable(fn):
            patterns.extend(fn())
        elif fn:
            patterns.extend(fn)
    return patterns


def enrich_server_home_context(context: dict) -> dict:
    """渲染服务器主页前，让私人插件补充上下文（如联系我们积木数据）"""
    for plugin in _PLUGINS:
        fn = getattr(plugin, 'enrich_server_home_context', None)
        if callable(fn):
            context = fn(context) or context
    return context


def get_server_middleware_classes() -> list[str]:
    """私人插件声明的中间件类路径"""
    paths: list[str] = []
    for plugin in _PLUGINS:
        fn = getattr(plugin, 'middleware_classes', None)
        if callable(fn):
            paths.extend(fn())
        elif fn:
            paths.extend(fn)
    return paths
