# 新版新手体验：独立大步入口时准备演示数据

from __future__ import annotations

from decimal import Decimal

from waimai.models import Dish
from waimai.menu_helpers import sync_new_dish_to_menu_profiles
from waimai.product_seller_handlers import _apply_new_dish_special_defaults

from .demo_cleanup import (
    DEMO_DISH_NAME,
    get_demo_dish_for_seller,
    register_demo_dish,
)
from .demo_product_image import attach_demo_preset_image

# 与 docs/新手引导流程.md 定稿文案一致
_SEED_DESCRIPTIONS = {
    'description': '普通价格所有用户都可以下单（包括未注册的游客帐户）',
    'description_member': '会员价格需要本店铺注册用户可以下单',
    'description_special': '特价需要本店注册用户，并且每个用户有限购数量',
}


def ensure_seller_major_prepared(seller_id: str, *, track: str, major_index: int) -> dict:
    """
    各大步脱钩独立进入时，按索引准备本步所需演示数据。
    major_index 与 boot 中 seller 大步下标一致（0=注册 … 5=编辑）。
    """
    if track != 'seller':
        return {}
    if major_index == 5:
        dish = _ensure_demo_dish_for_edit_major(seller_id)
        if dish:
            return {'edit_dish_id': dish.dish_id.hex[:8]}
    return {}


def _ensure_demo_dish_for_edit_major(seller_id: str):
    """第 6 大步：须有一只可编辑的演示商品（含图），与第 5 步是否做过无关"""
    dish = get_demo_dish_for_seller(seller_id)
    if dish:
        register_demo_dish(dish.dish_id)
        if not dish.product_images.exists():
            attach_demo_preset_image(dish)
        return dish

    dish = Dish(
        seller_id=seller_id,
        name=DEMO_DISH_NAME,
        price=Decimal('99'),
        sort_order=0,
        is_active=True,
        description=_SEED_DESCRIPTIONS['description'],
        description_member=_SEED_DESCRIPTIONS['description_member'],
        description_special=_SEED_DESCRIPTIONS['description_special'],
        member_price_enabled=True,
        special_price_enabled=True,
    )
    if not dish.member_price_mode:
        dish.member_price_mode = 'percent'
    if not dish.special_price_mode:
        dish.special_price_mode = 'percent'
    _apply_new_dish_special_defaults(dish)
    dish.save()
    sync_new_dish_to_menu_profiles(dish, list_on_all_menus=False)
    attach_demo_preset_image(dish)
    register_demo_dish(dish.dish_id)
    return dish
