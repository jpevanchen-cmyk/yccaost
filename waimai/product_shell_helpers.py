# 主体商品壳：通用商品能力留在主体，业态插件补充目录/菜单等专属能力。

from __future__ import annotations


def build_product_shell(seller_id: str) -> dict:
    """组装店铺商品展示壳；插件只能补充，不删除主体商品能力。"""
    shell = {
        'item_label': '商品',
        'unit_label': '件',
        'sales_title': '商品销量排行',
        # 批次 H2：主体通用商品列表（关饮食插件仍可用）
        'show_menu_catalog': True,
        'catalog_panel_title': '商品列表',
        'catalog_word': '商品列表',
        'catalog_create_placeholder': '商品列表 1',
        'catalog_all_phrase': '所有商品列表',
        'shop_catalog_intro': (
            '本店当前按「使用中商品列表」展示商品与价格档位'
            '（会员价/特价以列表设置为准）。'
        ),
        'product_help': (
            '在此设定商品名称、通用价格、会员价、特价与上下架状态。'
            '是否在客人店铺页展示，由「商品列表」控制。'
        ),
        'sort_help': '排序（0为不排序，按添加顺序；1为置顶；数字越大越靠后）',
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
    启用商品列表时按使用中列表过滤；否则读主体上架商品。
    """
    shell = build_product_shell(seller_id)
    if shell['show_menu_catalog']:
        from .menu_helpers import get_shop_dishes_for_sale

        return get_shop_dishes_for_sale(seller_id)

    from .models import Dish

    products = list(
        Dish.objects.filter(seller_id=seller_id, is_active=True)
        .prefetch_related('product_images')
        .order_by('sort_order', 'name')
    )
    return products, False


def product_unit_label(seller_id: str) -> str:
    """当前店铺商品数量单位；主体默认用「件」。"""
    return build_product_shell(seller_id)['unit_label']


def catalog_controls_shop_display(seller_id: str) -> bool:
    """是否有「使用中」列表在控制店铺页展示（须已启用列表且已切换使用）。"""
    if not build_product_shell(seller_id)['show_menu_catalog']:
        return False
    from .menu_helpers import get_active_menu_profile

    return get_active_menu_profile(seller_id) is not None
