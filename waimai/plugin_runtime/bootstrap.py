# 启动时装入同仓内置插件（以后可改为扫描独立包）


def bootstrap_builtin_plugins() -> None:
    """装入官方内置插件；重复调用安全（后注册覆盖）。"""
    from waimai.plugins.dining.plugin import DiningPlugin
    from waimai.plugins.fulfillment.plugin import FulfillmentPlugin

    from .registry import register_plugin

    register_plugin(DiningPlugin())
    register_plugin(FulfillmentPlugin())
