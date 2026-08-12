# 主页编辑 · Panel 局部刷新（复用进度 80 panel_refresh）

from __future__ import annotations

from django.http import HttpRequest
from django.template.loader import render_to_string

from .home_block_media import block_display_image_src, photo_quota_hint
from .home_page_helpers import (
    BLOCK_CUSTOM,
    BLOCK_DIRECTORY,
    BLOCK_FILE_DOWNLOAD,
    BLOCK_ORDER_CTA,
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

# 与模板、panel_refresh.js 一致
SHOP_HOME_SETTINGS_PANEL_ID = 'home-page-settings-panel'
SHOP_HOME_BLOCKS_PANEL_ID = 'home-page-blocks-panel'
SERVER_HOME_BLOCKS_PANEL_ID = 'server-home-blocks-panel'


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
        BLOCK_ORDER_CTA, BLOCK_DIRECTORY, BLOCK_FILE_DOWNLOAD,
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


def build_server_home_blocks() -> list:
    page = ensure_server_home_page()
    blocks = list(page.blocks.order_by('sort_order', 'block_type'))
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
    }
    ctx.update(photo_quota_hint(request.user))
    return ctx


def _server_home_common_context(request: HttpRequest) -> dict:
    page = ensure_server_home_page()
    blocks = build_server_home_blocks()
    custom_count = count_server_custom_blocks(page)
    download_count = count_server_download_blocks(page)
    ctx = {
        'home_page': page,
        'home_blocks': blocks,
        'preset_specs': list_server_preset_specs(),
        'custom_block_count': custom_count,
        'max_custom_blocks': MAX_SERVER_CUSTOM_BLOCKS,
        'can_add_custom_block': custom_count < MAX_SERVER_CUSTOM_BLOCKS,
        'download_block_count': download_count,
        'max_download_blocks': MAX_SERVER_DOWNLOAD_BLOCKS,
        'can_add_download_block': download_count < MAX_SERVER_DOWNLOAD_BLOCKS,
        'section': 'server_home',
        'preview_url': '/',
        'save_block_action_name': 'save_server_home_block',
        'delete_block_action_name': 'delete_server_home_block',
        'home_blocks_panel_id': SERVER_HOME_BLOCKS_PANEL_ID,
    }
    ctx.update(photo_quota_hint(request.user))
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


def render_server_home_blocks_panel_html(request: HttpRequest) -> str:
    ctx = _server_home_common_context(request)
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
