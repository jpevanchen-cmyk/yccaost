# 新版新手体验：演示数据清理（官方演示店）

from __future__ import annotations

import uuid

from django.core.cache import cache

DEMO_MENU_PROFILE_NAME = '演示清单1'
DEMO_DISH_NAME = '演示商品'

_CACHE_KEY = 'yc_experience_demo_menu_ids'
_DISH_CACHE_KEY = 'yc_experience_demo_dish_ids'
_CACHE_TTL = 86400


def register_demo_menu_profile(profile_id) -> None:
    """记录本引导创建的演示清单，便于退出时清理"""
    ids = _load_demo_menu_ids()
    pid = str(profile_id)
    if pid not in ids:
        ids.append(pid)
        cache.set(_CACHE_KEY, ids, _CACHE_TTL)


def _load_demo_menu_ids() -> list[str]:
    raw = cache.get(_CACHE_KEY) or []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _save_demo_menu_ids(ids: list[str]) -> None:
    cache.set(_CACHE_KEY, ids, _CACHE_TTL)


def register_demo_dish(dish_id) -> None:
    """记录本引导创建的演示商品，便于改名后仍能清理"""
    ids = _load_demo_dish_ids()
    did = str(dish_id)
    if did not in ids:
        ids.append(did)
        cache.set(_DISH_CACHE_KEY, ids, _CACHE_TTL)


def _load_demo_dish_ids() -> list[str]:
    raw = cache.get(_DISH_CACHE_KEY) or []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _save_demo_dish_ids(ids: list[str]) -> None:
    cache.set(_DISH_CACHE_KEY, ids, _CACHE_TTL)


def is_demo_dish(dish) -> bool:
    """是否为体验引导创建的演示商品"""
    if dish.name == DEMO_DISH_NAME:
        return True
    return str(dish.dish_id) in _load_demo_dish_ids()


def get_demo_dish_for_seller(seller_id: str):
    """取当前演示商品（含第 6 步改名后）"""
    from waimai.models import Dish

    dish = Dish.objects.filter(seller_id=seller_id, name=DEMO_DISH_NAME).first()
    if dish:
        return dish
    for did in _load_demo_dish_ids():
        dish = Dish.objects.filter(dish_id=did, seller_id=seller_id).first()
        if dish:
            return dish
    return None


def cleanup_experience_demo_data(seller_id: str) -> dict[str, int]:
    """删除演示清单/演示商品/演示桌台，并尽量恢复「通用清单」为使用中"""
    from waimai.menu_helpers import get_active_menu_profile
    from waimai.models import Dish, MenuProfile
    from waimai.operating_helpers import get_operating_settings

    from .dine_demo_helpers import cleanup_experience_demo_tables

    deleted_menus = 0
    deleted_dishes = 0
    settings = get_operating_settings(seller_id)
    active = get_active_menu_profile(seller_id)

    # 按名称清理演示清单（含用户已在本步内手动删过的残留）
    demo_names = {DEMO_MENU_PROFILE_NAME}
    for profile in MenuProfile.objects.filter(seller_id=seller_id, name__in=demo_names):
        if settings.active_menu_profile_id == profile.profile_id:
            fallback = MenuProfile.objects.filter(
                seller_id=seller_id,
            ).exclude(profile_id=profile.profile_id).order_by('updated_at').first()
            if fallback:
                settings.active_menu_profile = fallback
                settings.save(update_fields=['active_menu_profile'])
        profile.delete()
        deleted_menus += 1

    for pid in _load_demo_menu_ids():
        try:
            uuid.UUID(pid)
        except ValueError:
            continue
        profile = MenuProfile.objects.filter(profile_id=pid, seller_id=seller_id).first()
        if not profile:
            continue
        if settings.active_menu_profile_id == profile.profile_id:
            fallback = MenuProfile.objects.filter(seller_id=seller_id).exclude(
                profile_id=profile.profile_id,
            ).first()
            if fallback:
                settings.active_menu_profile = fallback
                settings.save(update_fields=['active_menu_profile'])
        profile.delete()
        deleted_menus += 1

    deleted_dish_ids: set[str] = set()
    for dish in Dish.objects.filter(seller_id=seller_id, name=DEMO_DISH_NAME):
        deleted_dish_ids.add(str(dish.dish_id))
        dish.delete()
        deleted_dishes += 1

    for did in _load_demo_dish_ids():
        if did in deleted_dish_ids:
            continue
        try:
            uuid.UUID(did)
        except ValueError:
            continue
        dish = Dish.objects.filter(dish_id=did, seller_id=seller_id).first()
        if dish:
            dish.delete()
            deleted_dishes += 1

    # 若无使用中清单，尽量恢复名称含「通用」的清单
    settings.refresh_from_db()
    if not settings.active_menu_profile_id:
        generic = MenuProfile.objects.filter(
            seller_id=seller_id,
            name__icontains='通用',
        ).first() or MenuProfile.objects.filter(seller_id=seller_id).first()
        if generic:
            settings.active_menu_profile = generic
            settings.save(update_fields=['active_menu_profile'])

    deleted_tables = cleanup_experience_demo_tables(seller_id)

    _save_demo_menu_ids([])
    _save_demo_dish_ids([])
    return {
        'deleted_menus': deleted_menus,
        'deleted_dishes': deleted_dishes,
        'deleted_tables': deleted_tables,
    }
