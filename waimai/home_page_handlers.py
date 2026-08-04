# 卖家后台：店铺主页
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .home_block_media import (
    apply_home_block_image_from_post,
    release_block_photo_quota,
)
from .home_page_helpers import (
    BLOCK_CUSTOM,
    MAX_SERVER_CUSTOM_BLOCKS,
    MAX_SHOP_CUSTOM_BLOCKS,
    SHOP_EDITABLE_BLOCK_TYPES,
    add_server_custom_block,
    add_shop_custom_block,
    block_dom_id,
    ensure_home_page_for_seller,
    ensure_server_home_page,
    get_server_block_spec,
    get_shop_block_spec,
)
from .home_page_panel_helpers import (
    SERVER_HOME_BLOCKS_PANEL_ID,
    SHOP_HOME_BLOCKS_PANEL_ID,
    SHOP_HOME_SETTINGS_PANEL_ID,
    render_server_home_blocks_panel_html,
    render_shop_home_blocks_panel_html,
    render_shop_home_settings_panel_html,
    respond_home_panel,
)
from .scroll_helpers import redirect_with_anchor


def handle_home_page_post(request, seller_id: str):
    """保存店铺主页总设置、预设积木或自定义积木"""
    page = ensure_home_page_for_seller(seller_id)
    if page is None:
        messages.error(request, '无法创建店铺主页配置')
        return redirect('seller_panel_section', section='homepage')

    if 'save_home_page_settings' in request.POST:
        mode = (request.POST.get('order_nav_mode') or 'to_shop').strip()
        if mode not in ('to_shop', 'to_cta_block'):
            mode = 'to_shop'
        page.order_nav_mode = mode
        if page.is_server_entry:
            page.is_server_entry = False
            page.save(update_fields=['order_nav_mode', 'is_server_entry', 'updated_at'])
        else:
            page.save(update_fields=['order_nav_mode', 'updated_at'])
        msg = '店铺主页设置已保存'
        panel_resp = respond_home_panel(
            request,
            panel_id=SHOP_HOME_SETTINGS_PANEL_ID,
            ok=True,
            message=msg,
            html=render_shop_home_settings_panel_html(request, seller_id),
        )
        if panel_resp is not None:
            return panel_resp
        return redirect_with_anchor(
            reverse('seller_panel_section', kwargs={'section': 'homepage'}),
            'home-page-settings',
        )

    if 'add_custom_block' in request.POST:
        block = add_shop_custom_block(page)
        if block is None:
            msg = f'自定义积木最多 {MAX_SHOP_CUSTOM_BLOCKS} 块，无法再添加'
            panel_resp = respond_home_panel(
                request,
                panel_id=SHOP_HOME_BLOCKS_PANEL_ID,
                ok=False,
                message=msg,
            )
            if panel_resp is not None:
                return panel_resp
            messages.error(request, msg)
            return redirect('seller_panel_section', section='homepage')
        msg = '已添加一块自定义积木，请填写内容后保存'
        scroll = block_dom_id(block)
        panel_resp = respond_home_panel(
            request,
            panel_id=SHOP_HOME_BLOCKS_PANEL_ID,
            ok=True,
            message=msg,
            html=render_shop_home_blocks_panel_html(request, seller_id),
            scroll_to=scroll,
        )
        if panel_resp is not None:
            return panel_resp
        return redirect_with_anchor(
            reverse('seller_panel_section', kwargs={'section': 'homepage'}),
            scroll,
        )

    if 'delete_home_block' in request.POST:
        block_id = (request.POST.get('block_id') or '').strip()
        block = page.blocks.filter(block_id=block_id).first()
        if not block:
            msg = '找不到该积木块'
            ok = False
        elif block.block_type != BLOCK_CUSTOM:
            msg = '预设积木不能删除，只能关闭显示'
            ok = False
        else:
            release_block_photo_quota(request.user, block, 'shop_home_block')
            block.delete()
            msg = '已删除该自定义积木'
            ok = True
        panel_resp = respond_home_panel(
            request,
            panel_id=SHOP_HOME_BLOCKS_PANEL_ID,
            ok=ok,
            message=msg,
            html=render_shop_home_blocks_panel_html(request, seller_id) if ok else '',
        )
        if panel_resp is not None:
            return panel_resp
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('seller_panel_section', section='homepage')

    if 'save_home_block' in request.POST:
        block_id = (request.POST.get('block_id') or '').strip()
        block = page.blocks.filter(block_id=block_id).first()
        if not block:
            msg = '找不到该积木块'
            panel_resp = respond_home_panel(
                request, panel_id=SHOP_HOME_BLOCKS_PANEL_ID, ok=False, message=msg,
            )
            if panel_resp is not None:
                return panel_resp
            messages.error(request, msg)
            return redirect('seller_panel_section', section='homepage')
        if block.block_type not in SHOP_EDITABLE_BLOCK_TYPES:
            msg = '该积木不能在此修改'
            panel_resp = respond_home_panel(
                request, panel_id=SHOP_HOME_BLOCKS_PANEL_ID, ok=False, message=msg,
            )
            if panel_resp is not None:
                return panel_resp
            messages.error(request, msg)
            return redirect('seller_panel_section', section='homepage')

        block.title = (request.POST.get('title') or '')[:120]
        block.body = request.POST.get('body') or ''
        block.image_url = ''
        block.link_url = (request.POST.get('link_url') or '').strip()[:500]
        block.link_label = (request.POST.get('link_label') or '').strip()[:32]
        block.nav_label = (request.POST.get('nav_label') or '')[:32]
        block.is_enabled = request.POST.get('is_enabled') == '1'
        block.show_in_nav = request.POST.get('show_in_nav') == '1'
        try:
            block.sort_order = max(0, int(request.POST.get('sort_order') or block.sort_order))
        except (TypeError, ValueError):
            pass

        err = apply_home_block_image_from_post(
            request.user, block, request, scope='shop_home_block',
        )
        if err:
            panel_resp = respond_home_panel(
                request, panel_id=SHOP_HOME_BLOCKS_PANEL_ID, ok=False, message=err,
            )
            if panel_resp is not None:
                return panel_resp
            messages.error(request, err)
            return redirect_with_anchor(
                reverse('seller_panel_section', kwargs={'section': 'homepage'}),
                block_dom_id(block),
            )

        block.save()
        spec = get_shop_block_spec(block.block_type)
        label = spec.label if spec else block.block_type
        msg = f'已保存积木「{label}」'
        scroll = block_dom_id(block)
        panel_resp = respond_home_panel(
            request,
            panel_id=SHOP_HOME_BLOCKS_PANEL_ID,
            ok=True,
            message=msg,
            html=render_shop_home_blocks_panel_html(request, seller_id),
            scroll_to=scroll,
        )
        if panel_resp is not None:
            return panel_resp
        return redirect_with_anchor(
            reverse('seller_panel_section', kwargs={'section': 'homepage'}),
            scroll,
        )

    return None


def handle_server_home_page_post(request):
    """服务器设置 · 保存服务器主页积木"""
    page = ensure_server_home_page()

    if 'add_server_custom_block' in request.POST:
        block = add_server_custom_block(page)
        if block is None:
            msg = f'自定义积木最多 {MAX_SERVER_CUSTOM_BLOCKS} 块，无法再添加'
            panel_resp = respond_home_panel(
                request, panel_id=SERVER_HOME_BLOCKS_PANEL_ID, ok=False, message=msg,
            )
            if panel_resp is not None:
                return panel_resp
            messages.error(request, msg)
            return redirect('server_settings_home_page')
        msg = '已添加一块自定义积木，请填写内容后保存'
        scroll = block_dom_id(block)
        panel_resp = respond_home_panel(
            request,
            panel_id=SERVER_HOME_BLOCKS_PANEL_ID,
            ok=True,
            message=msg,
            html=render_server_home_blocks_panel_html(request),
            scroll_to=scroll,
        )
        if panel_resp is not None:
            return panel_resp
        return redirect_with_anchor(reverse('server_settings_home_page'), scroll)

    if 'delete_server_home_block' in request.POST:
        block_id = (request.POST.get('block_id') or '').strip()
        block = page.blocks.filter(block_id=block_id).first()
        if not block:
            msg, ok = '找不到该积木块', False
        elif block.block_type != BLOCK_CUSTOM:
            msg, ok = '预设积木不能删除，只能关闭显示', False
        else:
            release_block_photo_quota(request.user, block, 'server_home_block')
            block.delete()
            msg, ok = '已删除该自定义积木', True
        panel_resp = respond_home_panel(
            request,
            panel_id=SERVER_HOME_BLOCKS_PANEL_ID,
            ok=ok,
            message=msg,
            html=render_server_home_blocks_panel_html(request) if ok else '',
        )
        if panel_resp is not None:
            return panel_resp
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect('server_settings_home_page')

    if 'save_server_home_block' in request.POST:
        block_id = (request.POST.get('block_id') or '').strip()
        block = page.blocks.filter(block_id=block_id).first()
        if not block:
            msg = '找不到该积木块'
            panel_resp = respond_home_panel(
                request, panel_id=SERVER_HOME_BLOCKS_PANEL_ID, ok=False, message=msg,
            )
            if panel_resp is not None:
                return panel_resp
            messages.error(request, msg)
            return redirect('server_settings_home_page')

        block.title = (request.POST.get('title') or '')[:120]
        block.body = request.POST.get('body') or ''
        block.image_url = ''
        block.link_url = (request.POST.get('link_url') or '').strip()[:500]
        block.link_label = (request.POST.get('link_label') or '').strip()[:32]
        block.nav_label = (request.POST.get('nav_label') or '')[:32]
        block.is_enabled = request.POST.get('is_enabled') == '1'
        block.show_in_nav = request.POST.get('show_in_nav') == '1'
        try:
            block.sort_order = max(0, int(request.POST.get('sort_order') or block.sort_order))
        except (TypeError, ValueError):
            pass
        err = apply_home_block_image_from_post(
            request.user, block, request, scope='server_home_block',
        )
        if err:
            panel_resp = respond_home_panel(
                request, panel_id=SERVER_HOME_BLOCKS_PANEL_ID, ok=False, message=err,
            )
            if panel_resp is not None:
                return panel_resp
            messages.error(request, err)
            return redirect_with_anchor(reverse('server_settings_home_page'), block_dom_id(block))
        block.save()
        spec = get_server_block_spec(block.block_type)
        label = spec.label if spec else block.block_type
        msg = f'已保存服务器积木「{label}」'
        scroll = block_dom_id(block)
        panel_resp = respond_home_panel(
            request,
            panel_id=SERVER_HOME_BLOCKS_PANEL_ID,
            ok=True,
            message=msg,
            html=render_server_home_blocks_panel_html(request),
            scroll_to=scroll,
        )
        if panel_resp is not None:
            return panel_resp
        return redirect_with_anchor(reverse('server_settings_home_page'), scroll)

    return None
