# 页面操作后跳回时带上锚点，配合前端 mobile.js 保持滚动位置

import uuid

from django.shortcuts import redirect


def dish_scroll_anchor(dish_id_str, price_tier=None):
    """菜品卡片锚点 id，与店铺页模板 id=\"dish-xxxxxxxx-档位\" 一致。"""
    try:
        dish_uuid = uuid.UUID(str(dish_id_str))
        anchor = f'dish-{dish_uuid.hex[:8]}'
        tier = (price_tier or '').strip()
        if tier:
            anchor = f'{anchor}-{tier}'
        return anchor
    except (ValueError, AttributeError, TypeError):
        return None


def redirect_with_anchor(url, anchor=None):
    """重定向到 url，可选 #锚点"""
    if anchor:
        return redirect(f'{url}#{anchor}')
    return redirect(url)
