# 店铺码生成与合并去重（A.13 · 本机唯一短码）

import re
import secrets

# 长度 5（手册建议 4～6）；去掉易混字符 0/O、1/I
_SHOP_CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
_SHOP_CODE_LENGTH = 5
_MAX_GENERATE_ATTEMPTS = 50

# 合并后缀：原码-A01、原码-A02…（联盟码/服务器码/店铺码共用算法，合并登记时调用）
_MERGE_SUFFIX_RE = re.compile(r'^(.+)-A(\d+)$')


def _random_shop_code(length: int = _SHOP_CODE_LENGTH) -> str:
    """随机生成一段候选店铺码"""
    return ''.join(secrets.choice(_SHOP_CODE_ALPHABET) for _ in range(length))


def generate_unique_shop_code(*, exclude: set[str] | None = None) -> str:
    """
    在本服务器名册内生成唯一店铺码。
    exclude：本次批量分配时已占用的码（合并去重时传入）。
    """
    from .models import ShopProfile

    taken = exclude or set()
    taken |= set(
        ShopProfile.objects.exclude(shop_code='').values_list('shop_code', flat=True)
    )
    for _ in range(_MAX_GENERATE_ATTEMPTS):
        code = _random_shop_code()
        if code not in taken:
            return code
    raise RuntimeError('无法生成唯一店铺码，请稍后重试')


def assign_shop_code_on_create(shop_profile) -> str:
    """开店时写入店铺码；已有码则原样返回（防重复调用）"""
    existing = (shop_profile.shop_code or '').strip()
    if existing:
        return existing
    code = generate_unique_shop_code()
    shop_profile.shop_code = code
    shop_profile.save(update_fields=['shop_code'])
    return code


def _parse_merge_suffix(code: str) -> tuple[str, int | None]:
    """解析 原码-A01 → (原根, 1)；无后缀则序号为 None"""
    m = _MERGE_SUFFIX_RE.match((code or '').strip())
    if not m:
        return (code or '').strip(), None
    return m.group(1), int(m.group(2))


def _max_merge_suffix_index(codes: list[str], root: str) -> int:
    """已占用合并后缀的最大序号（无后缀的裸 root 不计入序号）"""
    max_idx = 0
    root = (root or '').strip()
    for raw in codes:
        code = (raw or '').strip()
        if not code:
            continue
        base, idx = _parse_merge_suffix(code)
        if base != root:
            continue
        if idx is not None:
            max_idx = max(max_idx, idx)
    return max_idx


def allocate_merge_suffix_codes(root: str, count: int, occupied: list[str]) -> list[str]:
    """
    合并撞车时分配 原码-A01、A02…；若已有 A02，新分配从 A03 起顺延。
    供第二阶段联盟/服务器/店铺合并登记复用。
    """
    root = (root or '').strip()
    if not root or count < 1:
        return []
    start = _max_merge_suffix_index(occupied, root) + 1
    return [f'{root}-A{start + i:02d}' for i in range(count)]


def plan_merge_rename(existing_codes: list[str], incoming_codes: list[str]) -> dict[str, str]:
    """
    给定名册已有码与即将并入的码，返回需要改名的 {旧码: 新码}。
    无撞车的不出现在结果里；撞车涉及多方时统一分配 -A01、-A02…
    """
    existing = [(c or '').strip() for c in existing_codes if (c or '').strip()]
    incoming = [(c or '').strip() for c in incoming_codes if (c or '').strip()]
    occupied = list(dict.fromkeys(existing + incoming))
    renames: dict[str, str] = {}

    # 按原根分组统计「裸码」出现次数（含已带 -A 的也算在同一原根下）
    roots_incoming: dict[str, list[str]] = {}
    for code in incoming:
        root, _ = _parse_merge_suffix(code)
        roots_incoming.setdefault(root, []).append(code)

    existing_roots = set()
    for code in existing:
        root, _ = _parse_merge_suffix(code)
        existing_roots.add(root)

    for root, codes in roots_incoming.items():
        # 并入方有裸 root，且名册里已有同 root → 需要对本批冲突各方改名
        bare_incoming = [c for c in codes if _parse_merge_suffix(c)[1] is None]
        conflict = root in existing_roots or len(bare_incoming) > 1 or any(
            c in existing for c in codes
        )
        if not conflict:
            continue
        pool = [c for c in codes if c not in renames.values()]
        # 已有名册里同 root 的也要一起改（除已分配新名的）
        for c in existing:
            base, _ = _parse_merge_suffix(c)
            if base == root and c not in pool:
                pool.append(c)
        need = len(pool)
        if need < 2 and not (root in existing_roots and bare_incoming):
            continue
        if need < 1:
            continue
        new_codes = allocate_merge_suffix_codes(root, need, occupied)
        for old, new in zip(pool, new_codes):
            if old != new:
                renames[old] = new
                occupied.append(new)
    return renames
