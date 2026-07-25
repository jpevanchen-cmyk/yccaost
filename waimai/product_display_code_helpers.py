# 商品展示编号：分配、占用记录（A.11.11 · 批次 G · G1-1）

import string

from django.db import transaction

# 第一层：a001～z999；第二层：aa001～zz999
_LAYER1_LETTERS = string.ascii_lowercase


def _iter_layer1_codes():
    """按手册顺序生成第一层编号"""
    for letter in _LAYER1_LETTERS:
        for num in range(1, 1000):
            yield f'{letter}{num:03d}'


def _iter_layer2_codes():
    """第一层用尽后生成第二层编号"""
    for l1 in _LAYER1_LETTERS:
        for l2 in _LAYER1_LETTERS:
            for num in range(1, 1000):
                yield f'{l1}{l2}{num:03d}'


def normalize_display_code(code: str) -> str:
    """库内统一小写"""
    return (code or '').strip().lower()


def collect_taken_display_codes(seller_id: str) -> set[str]:
    """本店已占用编号：在架商品 + 删商品后保留的占用记录"""
    from .models import Dish, DishDisplayCodeOccupied

    taken = set(
        Dish.objects.filter(seller_id=seller_id)
        .exclude(display_code='')
        .values_list('display_code', flat=True)
    )
    taken |= set(
        DishDisplayCodeOccupied.objects.filter(seller_id=seller_id)
        .values_list('display_code', flat=True)
    )
    return {normalize_display_code(c) for c in taken if c}


def allocate_next_display_code(seller_id: str) -> str:
    """为本店取下一条可用展示编号"""
    taken = collect_taken_display_codes(seller_id)
    for code in _iter_layer1_codes():
        if code not in taken:
            return code
    for code in _iter_layer2_codes():
        if code not in taken:
            return code
    raise RuntimeError('本店商品展示编号已用尽，请联系管理员')


@transaction.atomic
def assign_display_code_to_dish(dish) -> str:
    """新建商品时写入展示编号（已有编号则原样保留）"""
    existing = normalize_display_code(dish.display_code)
    if existing:
        dish.display_code = existing
        return existing
    code = allocate_next_display_code(dish.seller_id)
    dish.display_code = code
    return code


@transaction.atomic
def release_display_code_for_dish(dish) -> None:
    """删商品前把编号记入占用表，此后永不复用"""
    from .models import DishDisplayCodeOccupied

    code = normalize_display_code(dish.display_code)
    if not code:
        return
    DishDisplayCodeOccupied.objects.get_or_create(
        seller_id=dish.seller_id,
        display_code=code,
    )
