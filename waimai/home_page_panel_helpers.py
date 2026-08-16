# 主页编辑 · Panel 局部刷新（复用进度 80 panel_refresh）

from __future__ import annotations

from django.http import HttpRequest
from django.template.loader import render_to_string

from .home_block_download_helpers import list_download_library_files
from .home_block_media import block_display_image_src, photo_quota_hint
from .home_page_helpers import (
    BLOCK_CUSTOM,
    BLOCK_DIRECTORY,
    BLOCK_FILE_DOWNLOAD,
    BLOCK_ORDER_CTA,
    BLOCK_PUBLIC_WALL,
    COMMUNITY_ONLY_BLOCK_TYPES,
    MAX_SERVER_CUSTOM_BLOCKS,
    MAX_SERVER_DOWNLOAD_BLOCKS,
    MAX_SHOP_CUSTOM_BLOCKS,
    SERVER_ONLY_BLOCK_TYPES,
    SHOP_LEGACY_BLOCK_TYPES,
    block_dom_id,
    count_server_custom_blocks,
    count_server_download_blocks,
    count_shop_custom_blocks,
    ensure_home_page_for_seller,
    ensure_server_home_page,
    get_server_block_spec,
    get_shop_block_spec,
    list_server_preset_specs,
)
from .home_page_tier_helpers import (
    MAX_SERVER_TOPIC_PAGES,
    list_server_pages,
    list_topic_pages,
    resolve_editing_server_page,
    server_page_edit_url,
    server_page_public_path,
)

# 与模板、panel_refresh.js 一致
SHOP_HOME_SETTINGS_PANEL_ID = 'home-page-settings-panel'
SHOP_HOME_BLOCKS_PANEL_ID = 'home-page-blocks-panel'
SERVER_HOME_BLOCKS_PANEL_ID = 'server-home-blocks-panel'


def _server_preset_specs_for_page(page) -> list:
    """大厅不展示留言板/公开墙说明书；互动社区只展示这两块。"""
    specs = list(list_server_preset_specs())
    if page is None or page.is_hall:
        return [s for s in specs if s.code not in COMMUNITY_ONLY_BLOCK_TYPES]
    if page.is_community:
        return [s for s in specs if s.code in COMMUNITY_ONLY_BLOCK_TYPES]
    return []


def _enrich_shop_block(block) -> None:
    block.spec = get_shop_block_spec(block.block_type)
    block.dom_id = block_dom_id(block)
    block.is_custom = block.block_type == BLOCK_CUSTOM
    block.is_download_block = False
    if block.is_custom:
        block.fold_title = (block.title or '').strip() or '自定义积木'
    else:
        block.fold_title = block.spec.label if block.spec else block.block_type
    block.display_image_src = block_display_image_src(block)
    block.shows_rich_media = block.block_type not in (BLOCK_ORDER_CTA, BLOCK_DIRECTORY)


def _enrich_server_block(block) -> None:
    from .home_block_download_helpers import (
        block_download_button_label,
        block_download_url,
        block_has_download_file,
    )

    block.spec = get_server_block_spec(block.block_type)
    block.dom_id = block_dom_id(block)
    block.is_custom = block.block_type == BLOCK_CUSTOM
    block.is_download_block = block.block_type == BLOCK_FILE_DOWNLOAD
    block.display_image_src = block_display_image_src(block)
    block.shows_rich_media = block.block_type not in (
        BLOCK_ORDER_CTA, BLOCK_DIRECTORY, BLOCK_FILE_DOWNLOAD, BLOCK_PUBLIC_WALL,
    )
    if block.is_custom:
        block.fold_title = (block.title or '').strip() or '自定义积木'
    elif block.is_download_block:
        block.fold_title = (block.title or '').strip() or '文件下载'
        block.has_download_file = block_has_download_file(block)
        block.download_url = block_download_url(block) if block.has_download_file else ''
        block.download_button_label = block_download_button_label(block)
    else:
        block.fold_title = block.spec.label if block.spec else block.block_type
        block.has_download_file = False
        block.download_url = ''
        block.download_button_label = ''


def build_shop_home_blocks(request: HttpRequest, seller_id: str, shop_profile=None) -> list:
    page = ensure_home_page_for_seller(seller_id, shop_profile)
    blocks = list(
        page.blocks.exclude(block_type__in=SERVER_ONLY_BLOCK_TYPES | SHOP_LEGACY_BLOCK_TYPES)
        .order_by('sort_order', 'block_type')
    )
    for b in blocks:
        _enrich_shop_block(b)
    return blocks


def build_server_home_blocks(page=None) -> list:
    page = page or ensure_server_home_page()
    blocks = list(page.blocks.order_by('sort_order', 'block_type'))
    # 二级页后台不展示不允许的类型（若历史误挂则隐藏）
    from .home_page_tier_helpers import allowed_server_block_types

    allowed = allowed_server_block_types(page)
    if page.is_hall:
        blocks = [b for b in blocks if b.block_type not in COMMUNITY_ONLY_BLOCK_TYPES]
    elif allowed is not None:
        blocks = [b for b in blocks if b.block_type in allowed]
    for b in blocks:
        _enrich_server_block(b)
    return blocks


def _shop_home_common_context(request: HttpRequest, seller_id: str, shop_profile=None) -> dict:
    page = ensure_home_page_for_seller(seller_id, shop_profile)
    blocks = build_shop_home_blocks(request, seller_id, shop_profile)
    custom_count = count_shop_custom_blocks(page)
    ctx = {
        'home_page': page,
        'home_blocks': blocks,
        'custom_block_count': custom_count,
        'max_custom_blocks': MAX_SHOP_CUSTOM_BLOCKS,
        'can_add_custom_block': custom_count < MAX_SHOP_CUSTOM_BLOCKS,
        'save_block_action_name': 'save_home_block',
        'delete_block_action_name': 'delete_home_block',
        'home_blocks_panel_id': SHOP_HOME_BLOCKS_PANEL_ID,
        'topic_link_choices': [],
        'editing_page_id': '',
    }
    ctx.update(photo_quota_hint(request.user))
    ctx['server_download_library_files'] = []
    return ctx


def _server_home_common_context(request: HttpRequest, page=None) -> dict:
    page = page or resolve_editing_server_page(request)
    blocks = build_server_home_blocks(page)
    custom_count = count_server_custom_blocks(page)
    download_count = count_server_download_blocks(page)
    all_pages = list_server_pages()
    topics = list_topic_pages()
    # 选页入口：大厅可链到各二级；二级也可链回大厅或其它二级
    link_choices = []
    for p in all_pages:
        if p.pk == page.pk:
            continue
        path = server_page_public_path(p)
        label = (p.title or '').strip() or (p.slug if p.is_topic else '一级大厅')
        if p.is_topic:
            label = f'{label}（{path}）'
        else:
            label = f'一级大厅（/）'
        link_choices.append({'id': str(p.pk), 'label': label, 'path': path})

    ctx = {
        'home_page': page,
        'home_blocks': blocks,
        'preset_specs': _server_preset_specs_for_page(page),
        'custom_block_count': custom_count,
        'max_custom_blocks': MAX_SERVER_CUSTOM_BLOCKS,
        'can_add_custom_block': custom_count < MAX_SERVER_CUSTOM_BLOCKS,
        'download_block_count': download_count,
        'max_download_blocks': MAX_SERVER_DOWNLOAD_BLOCKS,
        'can_add_download_block': download_count < MAX_SERVER_DOWNLOAD_BLOCKS,
        'section': 'server_home',
        'preview_url': server_page_public_path(page),
        'save_block_action_name': 'save_server_home_block',
        'delete_block_action_name': 'delete_server_home_block',
        'home_blocks_panel_id': SERVER_HOME_BLOCKS_PANEL_ID,
        'server_pages': all_pages,
        'topic_pages': topics,
        'topic_count': len(topics),
        'max_topic_pages': MAX_SERVER_TOPIC_PAGES,
        'can_add_topic_page': len(topics) < MAX_SERVER_TOPIC_PAGES,
        'is_editing_hall': page.is_hall,
        'is_editing_topic': page.is_topic,
        'is_editing_community': page.is_community,
        'editing_page_id': str(page.pk),
        'topic_link_choices': link_choices,
        'page_edit_url': server_page_edit_url(page),
    }
    ctx.update(photo_quota_hint(request.user))
    ctx['server_download_library_files'] = list_download_library_files()
    return ctx


def render_shop_home_settings_panel_html(
    request: HttpRequest, seller_id: str, shop_profile=None,
) -> str:
    ctx = _shop_home_common_context(request, seller_id, shop_profile)
    return render_to_string(
        'waimai/seller/_shop_home_settings_panel.html', ctx, request=request,
    )


def render_shop_home_blocks_panel_html(
    request: HttpRequest, seller_id: str, shop_profile=None,
) -> str:
    ctx = _shop_home_common_context(request, seller_id, shop_profile)
    return render_to_string(
        'waimai/seller/_shop_home_blocks_panel.html', ctx, request=request,
    )


def render_server_home_blocks_panel_html(request: HttpRequest, page=None) -> str:
    ctx = _server_home_common_context(request, page=page)
    return render_to_string(
        'waimai/owner/_server_home_blocks_panel.html', ctx, request=request,
    )


def respond_home_panel(
    request,
    *,
    panel_id: str,
    ok: bool,
    message: str,
    html: str = '',
    scroll_to: str = '',
):
    """主页 Panel 统一响应：Ajax 返回 JSON；普通 POST 仍 messages + None（由调用方 redirect）。"""
    from django.contrib import messages

    from .panel_refresh_helpers import is_panel_refresh, panel_refresh_fail, panel_refresh_ok

    if is_panel_refresh(request):
        if not ok:
            return panel_refresh_fail(message)
        extra = {'scroll_to': scroll_to} if scroll_to else None
        return panel_refresh_ok(
            html=html, message=message, panel_id=panel_id, extra=extra,
        )
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return None
