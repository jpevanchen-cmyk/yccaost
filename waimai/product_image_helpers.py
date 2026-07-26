# 商品多图：文件夹、压缩、上传（A.11.11 · 批次 G · G1-2～G1-5 · 试跑补丁 H：逐张上传 + 事后压缩）

from __future__ import annotations

import logging
import re
import shutil
import threading
from io import BytesIO
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from .product_display_code_helpers import normalize_display_code
# 与手册一致：单商品最多 10 张；单张原图上传上限 5MB（压缩后落盘）
MAX_DISH_IMAGES_PER_PRODUCT = 10
MAX_DISH_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DISH_IMAGE_LONG_EDGE = 1920
DISH_IMAGE_JPEG_QUALITY = 85
ALLOWED_DISH_IMAGE_EXT = frozenset({'png', 'jpg', 'jpeg', 'webp', 'gif'})

# 磁盘目录：商品图片/<展示编号>/ → 实现为 dish_images/<code>/
DISH_IMAGE_MEDIA_PREFIX = 'dish_images'

logger = logging.getLogger('waimai')


def dish_image_upload_to(instance, filename) -> str:
    """按展示编号与序号落盘：dish_images/a001/a001-1.jpg"""
    code = normalize_display_code(getattr(instance, 'display_code', '')) or 'unknown'
    idx = getattr(instance, 'sort_index', None) or 1
    return f'{DISH_IMAGE_MEDIA_PREFIX}/{code}/{code}-{idx}.jpg'


def dish_image_folder_relpath(display_code: str) -> str:
    code = normalize_display_code(display_code)
    return f'{DISH_IMAGE_MEDIA_PREFIX}/{code}'


def count_dish_images(dish) -> int:
    return dish.product_images.count()


def list_dish_images(dish):
    return dish.product_images.order_by('sort_index')


def _media_root() -> Path:
    return Path(settings.MEDIA_ROOT)


def _normalize_relpath(path: str) -> str:
    return (path or '').replace('\\', '/')


def _rel_path_for(code: str, sort_index: int, ext: str) -> str:
    ext = (ext or 'jpg').lower().lstrip('.') or 'jpg'
    return f'{DISH_IMAGE_MEDIA_PREFIX}/{code}/{code}-{sort_index}.{ext}'


def _guess_ext(uploaded) -> str:
    name = (getattr(uploaded, 'name', '') or '').lower()
    ext = name.rsplit('.', 1)[-1] if '.' in name else 'jpg'
    if ext not in ALLOWED_DISH_IMAGE_EXT:
        return 'jpg'
    return 'jpg' if ext == 'jpeg' else ext


def _rename_image_record_to_index(record, new_index: int) -> None:
    """把一条图片记录改序号，并在磁盘上同步文件名。"""
    code = normalize_display_code(record.display_code)
    old_rel = _normalize_relpath(record.image.name)
    ext = Path(old_rel).suffix.lstrip('.').lower() or 'jpg'
    new_rel = _rel_path_for(code, new_index, ext)
    if old_rel != new_rel:
        old_abs = _media_root() / old_rel
        new_abs = _media_root() / new_rel
        new_abs.parent.mkdir(parents=True, exist_ok=True)
        if old_abs.is_file():
            if new_abs.is_file() and old_abs.resolve() != new_abs.resolve():
                new_abs.unlink()
            shutil.move(str(old_abs), str(new_abs))
        record.image.name = new_rel
    if record.sort_index != new_index:
        record.sort_index = new_index
    record.save(update_fields=['sort_index', 'image'])


def _compact_dish_image_sort_indices(dish) -> None:
    """删图后把剩余图片序号收成 1、2、3…"""
    for new_idx, record in enumerate(dish.product_images.order_by('sort_index'), start=1):
        if record.sort_index != new_idx:
            _rename_image_record_to_index(record, new_idx)


def _validate_upload_file(uploaded) -> str | None:
    """校验扩展名与原始大小；失败返回白话错误。"""
    name = (getattr(uploaded, 'name', '') or '').lower()
    ext = name.rsplit('.', 1)[-1] if '.' in name else ''
    if ext not in ALLOWED_DISH_IMAGE_EXT:
        return '只支持 PNG、JPG、JPEG、WEBP、GIF 图片。'
    size = getattr(uploaded, 'size', 0) or 0
    if size > MAX_DISH_IMAGE_UPLOAD_BYTES:
        return f'单张图片不能超过 {MAX_DISH_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB，请先压缩后再上传。'
    return None


def compress_image_to_jpeg_bytes(uploaded) -> bytes:
    """上传时压缩为 JPEG，过长边缩至 MAX_DISH_IMAGE_LONG_EDGE。"""
    from PIL import Image

    uploaded.seek(0)
    img = Image.open(uploaded)
    img.load()
    if img.mode in ('RGBA', 'LA', 'P'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        if img.mode in ('RGBA', 'LA'):
            background.paste(img, mask=img.split()[-1])
        else:
            background.paste(img)
        img = background
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    width, height = img.size
    longest = max(width, height)
    if longest > MAX_DISH_IMAGE_LONG_EDGE:
        scale = MAX_DISH_IMAGE_LONG_EDGE / longest
        img = img.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )

    buf = BytesIO()
    img.save(buf, format='JPEG', quality=DISH_IMAGE_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _next_sort_indices(dish, count: int) -> list[int] | str:
    """为本批上传分配连续序号；不足则返回错误文案。"""
    existing = set(dish.product_images.values_list('sort_index', flat=True))
    slots: list[int] = []
    for idx in range(1, MAX_DISH_IMAGES_PER_PRODUCT + 1):
        if idx not in existing:
            slots.append(idx)
        if len(slots) >= count:
            break
    if len(slots) < count:
        remain = MAX_DISH_IMAGES_PER_PRODUCT - len(existing)
        return (
            f'本商品最多 {MAX_DISH_IMAGES_PER_PRODUCT} 张图，'
            f'还可上传 {max(0, remain)} 张，请先删除旧图或减少本次选择。'
        )
    return slots


@transaction.atomic
def apply_dish_image_uploads(dish, uploaded_files) -> str | None:
    """
    批量上传商品图（兼容旧表单）：逐张上传，部分成功部分失败时返回汇总错误。
    新页面应走 upload_single_dish_image + Ajax。
    """
    files = [f for f in (uploaded_files or []) if f]
    if not files:
        return None

    errors: list[str] = []
    ok_count = 0
    for uploaded in files:
        _, err = upload_single_dish_image(dish, uploaded)
        if err:
            name = getattr(uploaded, 'name', '未知')
            errors.append(f'「{name}」：{err}')
        else:
            ok_count += 1
    if errors and ok_count == 0:
        return errors[0]
    if errors:
        return f'成功 {ok_count} 张，失败 {len(errors)} 张：' + '；'.join(errors)
    return None


def upload_single_dish_image(dish, uploaded_file) -> tuple[dict | None, str | None]:
    """
    单张上传：先快速保存原图并写库，再在后台线程压缩为 JPEG。
    返回 ({image_id, sort_index, url}, None) 或 (None, 错误文案)。
    """
    from .models import DishImage

    if not uploaded_file:
        return None, '未收到图片文件'

    code = normalize_display_code(dish.display_code)
    if not code:
        return None, '商品尚未分配展示编号，请先保存商品后再上传图片。'

    slots = _next_sort_indices(dish, 1)
    if isinstance(slots, str):
        return None, slots

    err = _validate_upload_file(uploaded_file)
    if err:
        return None, err

    sort_index = slots[0]
    ext = _guess_ext(uploaded_file)
    rel_path = _rel_path_for(code, sort_index, ext)
    abs_path = _media_root() / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        uploaded_file.seek(0)
        data = uploaded_file.read()
        if not data:
            return None, '图片文件为空'
        abs_path.write_bytes(data)
    except Exception:
        return None, f'图片「{getattr(uploaded_file, "name", "未知")}」保存失败，请重试。'

    record = DishImage(
        dish=dish,
        seller_id=dish.seller_id,
        display_code=code,
        sort_index=sort_index,
    )
    record.image.name = rel_path
    record.save()

    _schedule_dish_image_compress(record.image_id)
    try:
        url = record.image.url
    except (ValueError, AttributeError):
        url = ''
    return {
        'image_id': str(record.image_id),
        'sort_index': sort_index,
        'url': url,
    }, None


def _schedule_dish_image_compress(image_id) -> None:
    """后台线程压缩，不阻塞上传响应；跑测试时同步压缩避免竞态。"""

    def _job():
        try:
            compress_dish_image_by_id(image_id)
        except Exception:
            logger.exception('商品图压缩失败 image_id=%s', image_id)

    import sys

    if any(arg == 'test' for arg in sys.argv):
        _job()
        return
    threading.Thread(target=_job, daemon=True, name=f'yc-dish-img-{image_id}').start()


def compress_dish_image_by_id(image_id) -> bool:
    """将已落盘的原图压缩为 JPEG；失败时保留原图并写日志。返回是否压缩成功。"""
    from .models import DishImage

    record = DishImage.objects.filter(image_id=image_id).select_related('dish').first()
    if not record or not record.image:
        return False
    return compress_dish_image_record(record)


def compress_dish_image_record(record) -> bool:
    """压缩单条商品图记录；成功则替换为 .jpg 并更新库。"""
    code = normalize_display_code(record.display_code)
    sort_index = record.sort_index
    old_rel = _normalize_relpath(record.image.name)
    old_abs = _media_root() / old_rel
    if not old_abs.is_file():
        return False

    try:
        with old_abs.open('rb') as fh:
            jpeg_bytes = compress_image_to_jpeg_bytes(fh)
    except Exception:
        logger.warning('商品图无法压缩，保留原图：%s', old_rel, exc_info=True)
        return False

    new_rel = _rel_path_for(code, sort_index, 'jpg')
    new_abs = _media_root() / new_rel
    new_abs.parent.mkdir(parents=True, exist_ok=True)
    new_abs.write_bytes(jpeg_bytes)
    if old_abs.resolve() != new_abs.resolve() and old_abs.is_file():
        old_abs.unlink(missing_ok=True)

    if record.image.name != new_rel:
        record.image.name = new_rel
        record.save(update_fields=['image'])
    return True


def delete_all_images_for_dish(dish) -> None:
    """删商品时连磁盘文件夹与库内记录一并清除。"""
    for record in list(dish.product_images.all()):
        if record.image:
            record.image.delete(save=False)
        record.delete()

    folder = _media_root() / dish_image_folder_relpath(dish.display_code)
    if folder.is_dir():
        for child in folder.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass


def dish_image_quota_hint(dish) -> dict:
    used = count_dish_images(dish)
    return {
        'dish_image_used': used,
        'dish_image_max': MAX_DISH_IMAGES_PER_PRODUCT,
        'dish_image_remaining': max(0, MAX_DISH_IMAGES_PER_PRODUCT - used),
        'dish_image_max_mb': MAX_DISH_IMAGE_UPLOAD_BYTES // (1024 * 1024),
    }


def parse_dish_image_filename(name: str) -> tuple[str, int] | None:
    """
    解析 a001-1.jpg 或 a001-1-说明.jpg（G1-3 同步用）。
    返回 (display_code, sort_index) 或 None。
    """
    base = Path(name).name
    m = re.match(r'^([a-z]{1,2})(\d{3})-(\d+)(?:-.*)?\.(jpg|jpeg|png|webp|gif)$', base.lower())
    if not m:
        return None
    code = f'{m.group(1)}{m.group(2)}'
    return code, int(m.group(3))


def build_dish_image_gallery(dish) -> list[dict]:
    """买家点菜页：按序号返回可展示的多图列表。"""
    code = normalize_display_code(getattr(dish, 'display_code', ''))
    gallery: list[dict] = []
    for record in list_dish_images(dish):
        if not record.image:
            continue
        try:
            url = record.image.url
        except (ValueError, AttributeError):
            continue
        if not url:
            continue
        label = f'{code.upper()}-{record.sort_index}' if code else str(record.sort_index)
        gallery.append({
            'url': url,
            'sort_index': record.sort_index,
            'label': label,
        })
    return gallery


@transaction.atomic
def delete_dish_image(dish, image_id) -> str | None:
    """删除单张商品图，并把剩余图片序号重新排紧。"""
    from .models import DishImage

    try:
        parsed_id = UUID(str(image_id))
    except (TypeError, ValueError):
        return '找不到该图片'

    record = DishImage.objects.filter(image_id=parsed_id, dish=dish).first()
    if not record:
        return '找不到该图片'

    if record.image:
        record.image.delete(save=False)
    record.delete()
    _compact_dish_image_sort_indices(dish)
    return None


@transaction.atomic
def move_dish_image(dish, image_id, direction: str) -> str | None:
    """上移 / 下移一张图片的展示顺序。"""
    from .models import DishImage

    if direction not in ('up', 'down'):
        return '无效操作'

    try:
        parsed_id = UUID(str(image_id))
    except (TypeError, ValueError):
        return '找不到该图片'

    records = list(dish.product_images.order_by('sort_index'))
    pos = next((i for i, row in enumerate(records) if row.image_id == parsed_id), None)
    if pos is None:
        return '找不到该图片'
    if direction == 'up' and pos == 0:
        return '已在最前'
    if direction == 'down' and pos == len(records) - 1:
        return '已在最后'

    swap_with = pos - 1 if direction == 'up' else pos + 1
    current = records[pos]
    neighbor = records[swap_with]
    current_idx = current.sort_index
    neighbor_idx = neighbor.sort_index

    # 用临时序号避免唯一约束冲突
    temp_idx = 99
    _rename_image_record_to_index(current, temp_idx)
    _rename_image_record_to_index(neighbor, current_idx)
    _rename_image_record_to_index(current, neighbor_idx)
    return None


@transaction.atomic
def sync_dish_images_from_folder(dish) -> tuple[str | None, int]:
    """
    扫描编号文件夹，把符合命名规则的图片挂载进库。
    返回 (错误文案, 新挂载张数)。
    """
    from .models import DishImage

    code = normalize_display_code(dish.display_code)
    if not code:
        return '商品尚无展示编号', 0

    folder = _media_root() / dish_image_folder_relpath(code)
    if not folder.is_dir():
        return None, 0

    desired: dict[int, str] = {}
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        parsed = parse_dish_image_filename(path.name)
        if not parsed:
            continue
        file_code, idx = parsed
        if file_code != code:
            continue
        if idx < 1 or idx > MAX_DISH_IMAGES_PER_PRODUCT:
            continue
        if idx in desired:
            return f'文件夹里序号 {idx} 有多张图，请只保留一张', 0
        desired[idx] = f'{DISH_IMAGE_MEDIA_PREFIX}/{code}/{path.name}'

    if len(desired) > MAX_DISH_IMAGES_PER_PRODUCT:
        return f'文件夹内有效图片超过 {MAX_DISH_IMAGES_PER_PRODUCT} 张', 0

    desired_values = set(desired.values())
    mounted = 0

    for record in list(dish.product_images.order_by('sort_index')):
        rel = _normalize_relpath(record.image.name)
        if record.sort_index in desired and desired[record.sort_index] == rel:
            continue
        if rel not in desired_values and record.image:
            record.image.delete(save=False)
        record.delete()

    for idx, rel in sorted(desired.items()):
        record = dish.product_images.filter(sort_index=idx).first()
        if record:
            if _normalize_relpath(record.image.name) != rel:
                record.image.name = rel
                record.save(update_fields=['image'])
            continue
        record = DishImage(
            dish=dish,
            seller_id=dish.seller_id,
            display_code=code,
            sort_index=idx,
        )
        record.image.name = rel
        record.save()
        mounted += 1

    return None, mounted


# ---------- G1-5：旧 image_url 外链迁移落盘并清空字段 ----------

LEGACY_MIGRATION_UA = 'YecaoST/1.0 (dish-image-migration)'


def _legacy_image_url_value(dish) -> str:
    """读取商品上尚未清空的旧外链（空则返回空串）。"""
    raw = getattr(dish, 'image_url', None)
    if raw is None:
        return ''
    return str(raw).strip()


def _clear_dish_image_url(dish, *, dry_run: bool = False) -> None:
    """迁移后一律清空旧外链字段。"""
    if dry_run:
        return
    dish.image_url = ''
    dish.save(update_fields=['image_url'])


def _download_legacy_image_bytes(url: str) -> bytes | None:
    """从旧外链下载原图字节；失败或过大则返回 None。"""
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={'User-Agent': LEGACY_MIGRATION_UA},
        method='GET',
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(MAX_DISH_IMAGE_UPLOAD_BYTES + 1)
            if len(data) > MAX_DISH_IMAGE_UPLOAD_BYTES or not data:
                return None
            return data
    except Exception:
        return None


def _legacy_bytes_to_jpeg(raw_bytes: bytes) -> bytes | None:
    """把下载到的任意图片字节压成 JPEG；无法识别则 None。"""
    from django.core.files.uploadedfile import SimpleUploadedFile

    try:
        uploaded = SimpleUploadedFile(
            'legacy.bin',
            raw_bytes,
            content_type='application/octet-stream',
        )
        return compress_image_to_jpeg_bytes(uploaded)
    except Exception:
        return None


@transaction.atomic
def migrate_legacy_dish_image_url(dish, *, dry_run: bool = False) -> str:
    """
    单商品旧外链迁移：有效则落本地第 1 张（或补空位），无论成败都清空 image_url。
    返回：downloaded / dead / cleared_only / full / skipped
    """
    url = _legacy_image_url_value(dish)
    if not url:
        return 'skipped'

    if count_dish_images(dish) > 0:
        _clear_dish_image_url(dish, dry_run=dry_run)
        return 'cleared_only'

    slots = _next_sort_indices(dish, 1)
    if isinstance(slots, str):
        _clear_dish_image_url(dish, dry_run=dry_run)
        return 'full'

    sort_index = slots[0]
    raw = _download_legacy_image_bytes(url)
    if not raw:
        _clear_dish_image_url(dish, dry_run=dry_run)
        return 'dead'

    jpeg_bytes = _legacy_bytes_to_jpeg(raw)
    if not jpeg_bytes:
        _clear_dish_image_url(dish, dry_run=dry_run)
        return 'dead'

    if dry_run:
        return 'downloaded'

    code = normalize_display_code(dish.display_code)
    if not code:
        from .product_display_code_helpers import assign_display_code_to_dish

        assign_display_code_to_dish(dish)
        dish.save(update_fields=['display_code'])
        code = normalize_display_code(dish.display_code)
        if not code:
            _clear_dish_image_url(dish)
            return 'dead'

    from .models import DishImage

    record = DishImage(
        dish=dish,
        seller_id=dish.seller_id,
        display_code=code,
        sort_index=sort_index,
    )
    filename = f'{code}-{sort_index}.jpg'
    record.image.save(filename, ContentFile(jpeg_bytes), save=True)
    _clear_dish_image_url(dish)
    return 'downloaded'


def migrate_all_legacy_dish_image_urls(queryset=None, *, dry_run: bool = False) -> dict[str, int]:
    """批量迁移旧外链；返回各结果计数。"""
    from django.db.models import Q

    from .models import Dish

    stats: dict[str, int] = {
        'downloaded': 0,
        'dead': 0,
        'cleared_only': 0,
        'full': 0,
        'skipped': 0,
    }
    qs = queryset if queryset is not None else Dish.objects.all()
    qs = qs.filter(Q(image_url__isnull=False) & ~Q(image_url=''))
    for dish in qs.iterator():
        if not _legacy_image_url_value(dish):
            stats['skipped'] += 1
            continue
        result = migrate_legacy_dish_image_url(dish, dry_run=dry_run)
        stats[result] = stats.get(result, 0) + 1
    return stats
