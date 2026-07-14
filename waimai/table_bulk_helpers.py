# 桌号与虚拟桌码：批量创建与编号校验

import re

from .models import ShopTable, VirtualTableCode

# 虚拟码统一前缀（须英文字母开头，与纯数字桌号区分）
VIRTUAL_CODE_PREFIX = 'V'

TABLE_DIGITS_RE = re.compile(r'^\d+$')
VIRTUAL_LABEL_RE = re.compile(r'^[A-Za-z][A-Za-z0-9]*$')


def get_table_number_set(seller_id: str) -> set[str]:
    return set(
        ShopTable.objects.filter(seller_id=seller_id).values_list('table_number', flat=True)
    )


def get_virtual_label_set(seller_id: str) -> set[str]:
    return set(
        VirtualTableCode.objects.filter(seller_id=seller_id).values_list('code_label', flat=True)
    )


def validate_table_number(num: str) -> tuple[bool, str]:
    """桌号只能是数字"""
    num = (num or '').strip()
    if not num:
        return False, '桌号不能为空'
    if not TABLE_DIGITS_RE.match(num):
        return False, f'桌号「{num}」只能填数字'
    return True, num


def virtual_label_for_number(n: int, width: int) -> str:
    """按序号生成虚拟码编号，如 V01、V12"""
    if width > 1:
        return f'{VIRTUAL_CODE_PREFIX}{n:0{width}d}'
    return f'{VIRTUAL_CODE_PREFIX}{n}'


def virtual_conflicts_table(label: str, table_numbers: set[str]) -> bool:
    """虚拟码是否与某实体桌号冲突（如桌号 7 与 V7）"""
    if label in table_numbers:
        return True
    if label.startswith(VIRTUAL_CODE_PREFIX):
        suffix = label[len(VIRTUAL_CODE_PREFIX):]
        if suffix.isdigit() and suffix in table_numbers:
            return True
        # 去掉前导零再比，如 V07 与桌号 7
        if suffix.isdigit():
            normalized = str(int(suffix))
            if normalized in table_numbers:
                return True
    return False


def validate_virtual_label(label: str, seller_id: str) -> tuple[bool, str]:
    label = (label or '').strip()
    if not label:
        return False, '虚拟码编号不能为空'
    if not VIRTUAL_LABEL_RE.match(label):
        return False, f'虚拟码「{label}」须以英文字母开头，只能含字母和数字'
    tables = get_table_number_set(seller_id)
    if virtual_conflicts_table(label, tables):
        return False, f'虚拟码「{label}」与已有桌号重复，请换编号'
    return True, label


def virtual_label_sort_key(label: str) -> tuple:
    """虚拟码按数字大小排序（V2 在 V10 前面）"""
    label = (label or '').strip()
    if label.upper().startswith(VIRTUAL_CODE_PREFIX):
        suffix = label[len(VIRTUAL_CODE_PREFIX):]
        if suffix.isdigit():
            return (0, int(suffix), label)
    return (1, 0, label.lower())


def table_number_sort_key(num: str) -> tuple:
    """桌号按数字大小排序"""
    num = (num or '').strip()
    if num.isdigit():
        return (0, int(num), num)
    return (1, 0, num)


def sort_shop_tables(tables) -> list:
    """桌台列表：按桌号数字从小到大"""
    return sorted(tables, key=lambda t: table_number_sort_key(t.table_number))


def sort_virtual_codes(codes) -> list:
    """虚拟码列表：按编号数字从小到大"""
    return sorted(codes, key=lambda c: virtual_label_sort_key(c.code_label))


def bulk_create_tables(seller_id: str, min_num: int, max_num: int) -> tuple[int, int, list[str]]:
    """
    批量建桌：返回 (新建数, 跳过数, 提示行列表)
    """
    if min_num > max_num:
        min_num, max_num = max_num, min_num
    if min_num < 1:
        return 0, 0, ['最小桌号须大于 0']
    if max_num - min_num > 500:
        return 0, 0, ['单次最多批量创建 500 个桌号']

    existing = get_table_number_set(seller_id)
    created = 0
    skipped = 0
    notes = []

    for n in range(min_num, max_num + 1):
        num = str(n)
        if num in existing:
            skipped += 1
            continue
        ShopTable.objects.create(seller_id=seller_id, table_number=num)
        existing.add(num)
        created += 1

    return created, skipped, notes


def bulk_create_virtual_codes(seller_id: str, min_num: int, max_num: int) -> tuple[int, int, list[str]]:
    """批量建虚拟码：编号为 V+序号，不与桌号冲突"""
    if min_num > max_num:
        min_num, max_num = max_num, min_num
    if min_num < 1:
        return 0, 0, ['最小编号须大于 0']
    if max_num - min_num > 500:
        return 0, 0, ['单次最多批量创建 500 个虚拟码']

    existing_virtual = get_virtual_label_set(seller_id)
    table_numbers = get_table_number_set(seller_id)
    created = 0
    skipped = 0
    blocked = 0
    notes = []
    width = max(2, len(str(max_num)))

    for n in range(min_num, max_num + 1):
        label = virtual_label_for_number(n, width)
        if label in existing_virtual:
            skipped += 1
            continue
        if virtual_conflicts_table(label, table_numbers):
            blocked += 1
            notes.append(f'「{label}」与桌号冲突，已跳过')
            continue
        VirtualTableCode.objects.create(seller_id=seller_id, code_label=label)
        existing_virtual.add(label)
        created += 1

    return created, skipped + blocked, notes
