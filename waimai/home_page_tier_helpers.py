# 服务器主页分级分流（A.10.12）：大厅 + 二级专题页

from __future__ import annotations

import os
import re
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from django.urls import reverse

from .home_page_helpers import (
    BLOCK_CUSTOM,
    BLOCK_FILE_DOWNLOAD,
    MAX_SERVER_CUSTOM_BLOCKS,
    MAX_SERVER_DOWNLOAD_BLOCKS,
    ensure_server_home_page,
)

# 二级页数量上限（防乱建）
MAX_SERVER_TOPIC_PAGES = 20

# 短名：小写字母数字与连字符；禁止首尾连字符
_SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,46}[a-z0-9])?$')

# 短名保留字（避免与现有网址冲突）
_RESERVED_SLUGS = frozenset({
    'admin', 'static', 'media', 'shop', 'seller', 'owner', 'server-settings',
    'guestbook', 'directory', 'showcase', 'home', 'p', 's', 'api', 'accounts',
    'experience', 'onboarding', 'v1', 'login', 'logout', 'rider-home', 'kitchen-home',
})


def server_page_public_path(page) -> str:
    """前台公开路径：大厅 / ，二级 /p/短名/"""
    if page is None or getattr(page, 'is_hall', False) or page.page_role == 'hall':
        return '/'
    slug = (page.slug or '').strip()
    if not slug:
        return '/'
    return reverse('server_topic_page', kwargs={'slug': slug})


def server_page_edit_url(page) -> str:
    """后台编辑某页的地址"""
    base = reverse('server_settings_home_page')
    if page is None or getattr(page, 'is_hall', True):
        return base
    return f'{base}?page={page.pk}'


def normalize_topic_slug(raw: str) -> str:
    """规范化短名：去空格、转小写"""
    return (raw or '').strip().lower()


def validate_topic_slug(slug: str, *, exclude_page_id=None) -> str:
    """校验短名；通过返回空串，失败返回人话原因"""
    from .models import ServerHomePage

    slug = normalize_topic_slug(slug)
    if not slug:
        return '请填写短名（用于网址）'
    if not _SLUG_RE.match(slug):
        return '短名只能用小写字母、数字和中间的连字符，长度 1～48'
    if slug in _RESERVED_SLUGS:
        return f'短名「{slug}」已被系统保留，请换一个'
    qs = ServerHomePage.objects.filter(slug=slug)
    if exclude_page_id is not None:
        qs = qs.exclude(pk=exclude_page_id)
    if qs.exists():
        return f'短名「{slug}」已被其它页占用'
    return ''


def list_server_pages():
    """大厅在前，其后按编号排列二级页"""
    ensure_server_home_page()
    from .models import ServerHomePage

    hall = ServerHomePage.objects.filter(page_role=ServerHomePage.PAGE_HALL).first()
    topics = list(
        ServerHomePage.objects.filter(page_role=ServerHomePage.PAGE_TOPIC).order_by('singleton_id')
    )
    pages = []
    if hall:
        pages.append(hall)
    pages.extend(topics)
    return pages


def list_topic_pages():
    from .models import ServerHomePage

    ensure_server_home_page()
    return list(
        ServerHomePage.objects.filter(page_role=ServerHomePage.PAGE_TOPIC).order_by('singleton_id')
    )


def get_server_page_by_id(page_id):
    from .models import ServerHomePage

    ensure_server_home_page()
    try:
        pk = int(page_id)
    except (TypeError, ValueError):
        return ensure_server_home_page()
    page = ServerHomePage.objects.filter(pk=pk).first()
    return page or ensure_server_home_page()


def get_topic_page_by_slug(slug: str):
    from .models import ServerHomePage

    slug = normalize_topic_slug(slug)
    if not slug:
        return None
    return ServerHomePage.objects.filter(
        page_role=ServerHomePage.PAGE_TOPIC, slug=slug,
    ).first()


def resolve_editing_server_page(request):
    """从 POST/GET 解析当前正在编辑的服务器页；默认大厅"""
    raw = (request.POST.get('page_id') or request.GET.get('page') or '').strip()
    if raw:
        return get_server_page_by_id(raw)
    return ensure_server_home_page()


def allowed_server_block_types(page) -> frozenset | None:
    """该页允许的积木类型；大厅返回 None 表示不额外限制（含插件积木）"""
    if page is None or getattr(page, 'is_hall', True) or page.page_role == 'hall':
        return None
    return frozenset({BLOCK_CUSTOM, BLOCK_FILE_DOWNLOAD})


def _next_page_id() -> int:
    from .models import ServerHomePage

    agg = ServerHomePage.objects.aggregate(m=Max('singleton_id'))
    return max(2, (agg['m'] or 1) + 1)


def allocate_unique_topic_slug(page_id: int) -> str:
    """按页编号生成短名（如 p2）；若已占用则加后缀，保证本机不重复。"""
    from .models import ServerHomePage

    base = f'p{int(page_id)}'
    if base not in _RESERVED_SLUGS and not ServerHomePage.objects.filter(slug=base).exists():
        return base
    for n in range(2, 1000):
        cand = f'{base}-{n}'
        if cand in _RESERVED_SLUGS:
            continue
        if not ServerHomePage.objects.filter(slug=cand).exists():
            return cand
    return f'p{page_id}-{uuid.uuid4().hex[:8]}'


def _copy_file_field(src_field, dest_instance, attr_name: str) -> None:
    """把源文件字段内容复制到目标实例（新文件名）"""
    if not src_field:
        return
    try:
        src_field.open('rb')
        data = src_field.read()
    except Exception:
        return
    finally:
        try:
            src_field.close()
        except Exception:
            pass
    base = os.path.basename(src_field.name) or 'file.bin'
    getattr(dest_instance, attr_name).save(base, ContentFile(data), save=False)


@transaction.atomic
def create_topic_page_blank(*, title: str) -> tuple[object | None, str]:
    """空白新建二级页；短名由程序生成。成功返回 (page, '')，失败返回 (None, 原因)"""
    from .models import ServerHomePage

    ensure_server_home_page()
    if ServerHomePage.objects.filter(page_role=ServerHomePage.PAGE_TOPIC).count() >= MAX_SERVER_TOPIC_PAGES:
        return None, f'二级页最多 {MAX_SERVER_TOPIC_PAGES} 个，无法再新建'

    page_id = _next_page_id()
    slug = allocate_unique_topic_slug(page_id)
    err = validate_topic_slug(slug)
    if err:
        return None, err

    title = (title or '').strip()[:80] or f'专题页 {page_id}'
    page = ServerHomePage(
        singleton_id=page_id,
        page_role=ServerHomePage.PAGE_TOPIC,
        slug=slug,
        title=title,
        welcome_body='',
        welcome_enabled=True,
    )
    page.save()
    return page, ''


@transaction.atomic
def create_topic_page_from_hall(*, title: str) -> tuple[object | None, str]:
    """从一级大厅复制「新增积木」（自定义 / 文件下载）；不复制名录/留言等预设"""
    from .models import ServerHomeBlock

    page, err = create_topic_page_blank(title=title)
    if page is None:
        return None, err

    hall = ensure_server_home_page()
    sources = list(
        hall.blocks.filter(block_type__in=(BLOCK_CUSTOM, BLOCK_FILE_DOWNLOAD))
        .order_by('sort_order', 'block_type')
    )
    custom_n = 0
    download_n = 0
    for src in sources:
        if src.block_type == BLOCK_CUSTOM:
            if custom_n >= MAX_SERVER_CUSTOM_BLOCKS:
                continue
            custom_n += 1
        elif src.block_type == BLOCK_FILE_DOWNLOAD:
            if download_n >= MAX_SERVER_DOWNLOAD_BLOCKS:
                continue
            download_n += 1
        else:
            continue

        dest = ServerHomeBlock(
            block_id=uuid.uuid4(),
            home_page=page,
            block_type=src.block_type,
            title=src.title,
            body=src.body,
            image_url='',
            link_url=src.link_url,
            link_label=src.link_label,
            nav_label=src.nav_label,
            is_enabled=src.is_enabled,
            show_in_nav=src.show_in_nav,
            sort_order=src.sort_order,
        )
        if src.block_type == BLOCK_CUSTOM and src.image:
            _copy_file_field(src.image, dest, 'image')
        if src.block_type == BLOCK_FILE_DOWNLOAD and src.download_file:
            _copy_file_field(src.download_file, dest, 'download_file')
        dest.save()

    return page, ''


@transaction.atomic
def delete_topic_page(page) -> str:
    """删除二级页；大厅不可删。成功返回空串"""
    from .models import ServerHomePage

    if page is None or page.page_role != ServerHomePage.PAGE_TOPIC:
        return '只能删除二级专题页'
    # 先清文件字段，再删行
    for block in page.blocks.all():
        if block.image:
            try:
                block.image.delete(save=False)
            except Exception:
                pass
        if block.download_file:
            try:
                block.download_file.delete(save=False)
            except Exception:
                pass
    page.delete()
    return ''


@transaction.atomic
def save_topic_page_settings(page, *, title: str, welcome_body: str, welcome_enabled: bool) -> str:
    """保存二级页设置（短名只读，不接受手改）；失败返回人话"""
    from .models import ServerHomePage

    if page is None or page.page_role != ServerHomePage.PAGE_TOPIC:
        return '只能改二级专题页设置'

    page.title = (title or '').strip()[:80] or (page.title or page.slug or '专题页')
    page.welcome_body = welcome_body or ''
    page.welcome_enabled = bool(welcome_enabled)
    page.save(update_fields=['title', 'welcome_body', 'welcome_enabled', 'updated_at'])
    return ''


def topic_welcome_should_show(page) -> bool:
    """后台配置层面：是否具备弹出欢迎的条件（前台再用本机记住过滤）"""
    if page is None or not getattr(page, 'is_topic', False):
        return False
    if not page.welcome_enabled:
        return False
    return bool((page.welcome_body or '').strip())
