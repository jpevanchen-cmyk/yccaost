# 新版新手体验：堂食营业演示数据准备与清理

from __future__ import annotations

from django.core.cache import cache

from waimai.models import ShopTable
from waimai.operating_helpers import get_operating_settings

_CACHE_KEY = 'yc_experience_demo_table_ids'
_CACHE_TTL = 86400


def _load_demo_table_ids() -> list[str]:
    raw = cache.get(_CACHE_KEY) or []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw]


def _save_demo_table_ids(ids: list[str]) -> None:
    cache.set(_CACHE_KEY, ids, _CACHE_TTL)


def register_demo_table(table_id) -> None:
    """记录体验引导新建的桌台，便于退出时清理"""
    ids = _load_demo_table_ids()
    tid = str(table_id)
    if tid not in ids:
        ids.append(tid)
        _save_demo_table_ids(ids)


def register_demo_tables_from_numbers(seller_id: str, numbers: list[str]) -> None:
    """按桌号登记演示桌台（批量添加后调用）"""
    for table in ShopTable.objects.filter(seller_id=seller_id, table_number__in=numbers):
        register_demo_table(table.table_id)


def ensure_dine_tour_prepared(seller_id: str) -> None:
    """
    第 8 大步进入前：清残留演示桌台，并预设拼桌模式 B 等，避免勾选/模式挡住观摩。
    """
    cleanup_experience_demo_tables(seller_id)
    settings = get_operating_settings(seller_id)
    settings.table_rules_acknowledged = True
    settings.share_rules_confirmed = True
    settings.share_table_enabled = True
    settings.share_table_mode = 'virtual'
    settings.save(update_fields=[
        'table_rules_acknowledged',
        'share_rules_confirmed',
        'share_table_enabled',
        'share_table_mode',
    ])


def cleanup_experience_demo_tables(seller_id: str) -> int:
    """删除体验引导创建的桌台；返回删除数量"""
    deleted = 0
    seen: set[str] = set()
    for tid in _load_demo_table_ids():
        if tid in seen:
            continue
        seen.add(tid)
        table = ShopTable.objects.filter(table_id=tid, seller_id=seller_id).first()
        if table:
            table.delete()
            deleted += 1
    # 兜底：演示常用 1～10 号桌一并清掉
    for table in ShopTable.objects.filter(
        seller_id=seller_id,
        table_number__in=[str(i) for i in range(1, 11)],
    ):
        if str(table.table_id) in seen:
            continue
        table.delete()
        deleted += 1
    _save_demo_table_ids([])
    return deleted
