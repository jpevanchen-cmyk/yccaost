import uuid


def norm_dish_id(dish_id: str) -> str:
    return (dish_id or '').replace('-', '').strip().lower()


def normalize_dish_items(dish_items: list | None, progress_fields: tuple[str, ...]) -> tuple[list[dict], bool]:
    """补齐行 ID 与多个按份进度字段"""
    changed = False
    rows: list[dict] = []
    for raw in dish_items or []:
        row = dict(raw)
        if not row.get('line_id'):
            row['line_id'] = uuid.uuid4().hex
            changed = True
        row['quantity'] = int(row.get('quantity') or 0)
        for field in progress_fields:
            if row.get(field) is None:
                row[field] = 0
                changed = True
            row[field] = int(row.get(field) or 0)
        rows.append(row)
    return rows, changed


def count_progress_units(dish_items: list | None, progress_field: str) -> tuple[int, int]:
    items, _ = normalize_dish_items(dish_items, (progress_field,))
    total = sum(int(i['quantity']) for i in items)
    done = sum(int(i.get(progress_field) or 0) for i in items)
    return total, done


def build_progress_groups(dish_items: list | None, progress_field: str, output_key: str) -> list[dict]:
    """按菜品 ID 合并展示统计"""
    items, _ = normalize_dish_items(dish_items, (progress_field,))
    groups: dict[str, dict] = {}
    for line in items:
        did = norm_dish_id(str(line.get('dish_id', '')))
        if not did:
            continue
        if did not in groups:
            groups[did] = {
                'dish_id': did,
                'name': line.get('name') or '菜品',
                'total_qty': 0,
                output_key: 0,
            }
        groups[did]['total_qty'] += int(line['quantity'])
        groups[did][output_key] += int(line.get(progress_field) or 0)
    return list(groups.values())


def find_markable_line(items: list[dict], dish_id: str, progress_field: str) -> dict | None:
    target = norm_dish_id(dish_id)
    for line in items:
        if norm_dish_id(str(line.get('dish_id', ''))) != target:
            continue
        if int(line.get(progress_field) or 0) < int(line['quantity']):
            return line
    return None


def find_undo_line(items: list[dict], dish_id: str, progress_field: str) -> dict | None:
    target = norm_dish_id(dish_id)
    for line in reversed(items):
        if norm_dish_id(str(line.get('dish_id', ''))) != target:
            continue
        if int(line.get(progress_field) or 0) > 0:
            return line
    return None
