# 主体商品壳：通用商品能力留在主体，业态插件补充目录/菜单等专属能力。

from __future__ import annotations


def build_product_shell(seller_id: str) -> dict:
    """组装店铺商品展示壳；插件只能补充，不删除主体商品能力。"""
    shell = {
        'item_label': '商品',
        'unit_label': '件',
        'sales_title': '商品销量排行',
        'show_menu_catalog': False,
        'shop_catalog_intro': '',
        'product_help': (
            '在此设定商品名称、通用价格、会员价、特价与上下架状态。'
            '已上架商品会在店铺页展示。'
        ),
        'sort_help': '排序（0为不排序，越小越靠前，是客人看到商品的顺序）',
        'empty_shop_text': '该店铺暂无商品',
    }

    from .plugin_runtime.registry import is_plugin_enabled, list_plugins

    for plugin in list_plugins():
        if not is_plugin_enabled(plugin.id, seller_id):
            continue
        contribute = getattr(plugin, 'contribute_product_shell', None)
        if not callable(contribute):
            continue
        extra = contribute(seller_id) or {}
        if extra:
            shell.update(extra)
    return shell


def get_shop_products_for_sale(seller_id: str):
    """
    买家店铺页商品来源。
    无业态目录插件时直接读主体上架商品；饮食插件开启时沿用菜单清单。
    """
    shell = build_product_shell(seller_id)
    if shell['show_menu_catalog']:
        from .menu_helpers import get_shop_dishes_for_sale

        return get_shop_dishes_for_sale(seller_id)

    from .models import Dish

    products = list(
        Dish.objects.filter(seller_id=seller_id, is_active=True)
        .order_by('sort_order', 'name')
    )
    return products, False


def product_unit_label(seller_id: str) -> str:
    """当前店铺商品数量单位；主体默认用「件」。"""
    return build_product_shell(seller_id)['unit_label']
