# 卖家商品图管理区 Panel（进度 80-3：删 / 调序 / 同步）

from __future__ import annotations

from django.http import HttpRequest
from django.template.loader import render_to_string

from .product_image_helpers import dish_image_quota_hint

# 与模板、panel_refresh.js 一致：product-image-manage-<dish_pick>
PRODUCT_IMAGE_PANEL_PREFIX = 'product-image-manage-'

PRODUCT_IMAGE_PANEL_IDEMPOTENT_KEYS = (
    'delete_dish_image',
    'move_dish_image',
    'sync_dish_images',
)


def product_image_manage_panel_id(dish) -> str:
    """单个商品编辑区的图片管理 Panel 容器 id。"""
    pick = getattr(dish, 'dish_id', None)
    if pick is None:
        return f'{PRODUCT_IMAGE_PANEL_PREFIX}unknown'
    return f'{PRODUCT_IMAGE_PANEL_PREFIX}{pick.hex[:8]}'


def is_product_image_manage_panel_id(panel_id: str) -> bool:
    return (panel_id or '').startswith(PRODUCT_IMAGE_PANEL_PREFIX)


def render_product_image_manage_html(request: HttpRequest, dish) -> str:
    """渲染商品图管理区片段（含删/调序/同步表单）。"""
    quota = dish_image_quota_hint(dish)
    return render_to_string(
        'waimai/seller/_product_image_manage.html',
        {
            'dish': dish,
            'dish_image_max': quota['dish_image_max'],
            'dish_image_used': quota['dish_image_used'],
            'product_image_panel_id': product_image_manage_panel_id(dish),
        },
        request=request,
    )


def detect_product_image_panel_action(request) -> str | None:
    """识别商品图 Panel 写操作；非此类返回 None。"""
    for key in PRODUCT_IMAGE_PANEL_IDEMPOTENT_KEYS:
        if key in request.POST:
            return key
    return None


def run_product_image_panel_idempotent(request, seller_id: str, action: str, execute):
    """商品图 Panel 写操作幂等（可重试）。"""
    from .idempotency_helpers import idempotency_scope, run_idempotent

    actor = (
        str(request.user.pk)
        if getattr(request.user, 'is_authenticated', False)
        else (request.session.session_key or 'anon')[:32]
    )
    dish_id = (request.POST.get('dish_id') or '').strip()[:64]
    scope = idempotency_scope('product_image', action, seller_id, dish_id, actor)
    return run_idempotent(request, scope, execute)
