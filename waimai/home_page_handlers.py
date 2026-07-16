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
    MAX_SHOP_CUSTOM_BLOCKS,
    SHOP_EDITABLE_BLOCK_TYPES,
    add_shop_custom_block,
    block_dom_id,
    ensure_home_page_for_seller,
    get_shop_block_spec,
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
        messages.success(request, '店铺主页设置已保存')
        return redirect_with_anchor(
            reverse('seller_panel_section', kwargs={'section': 'homepage'}),
            'home-page-settings',
        )

    if 'add_custom_block' in request.POST:
        block = add_shop_custom_block(page)
        if block is None:
            messages.error(request, f'自定义积木最多 {MAX_SHOP_CUSTOM_BLOCKS} 块，无法再添加')
        else:
            messages.success(request, '已添加一块自定义积木，请填写内容后保存')
            return redirect_with_anchor(
                reverse('seller_panel_section', kwargs={'section': 'homepage'}),
                block_dom_id(block),
            )
        return redirect('seller_panel_section', section='homepage')

    if 'delete_home_block' in request.POST:
        block_id = (request.POST.get('block_id') or '').strip()
        block = page.blocks.filter(block_id=block_id).first()
        if not block:
            messages.error(request, '找不到该积木块')
        elif block.block_type != BLOCK_CUSTOM:
            messages.error(request, '预设积木不能删除，只能关闭显示')
        else:
            release_block_photo_quota(request.user, block, 'shop_home_block')
            block.delete()
            messages.success(request, '已删除该自定义积木')
        return redirect('seller_panel_section', section='homepage')

    if 'save_home_block' in request.POST:
        block_id = (request.POST.get('block_id') or '').strip()
        block = page.blocks.filter(block_id=block_id).first()
        if not block:
            messages.error(request, '找不到该积木块')
            return redirect('seller_panel_section', section='homepage')
        if block.block_type not in SHOP_EDITABLE_BLOCK_TYPES:
            messages.error(request, '该积木不能在此修改')
            return redirect('seller_panel_section', section='homepage')

        block.title = (request.POST.get('title') or '')[:120]
        block.body = request.POST.get('body') or ''
        # 去掉首尾空格，避免粘贴链接后「看起来像没保存」
        block.image_url = (request.POST.get('image_url') or '').strip()[:500]
        block.link_url = (request.POST.get('link_url') or '').strip()[:500]
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
            messages.error(request, err)
            return redirect_with_anchor(
                reverse('seller_panel_section', kwargs={'section': 'homepage'}),
                block_dom_id(block),
            )

        block.save()
        spec = get_shop_block_spec(block.block_type)
        label = spec.label if spec else block.block_type
        messages.success(request, f'已保存积木「{label}」')
        return redirect_with_anchor(
            reverse('seller_panel_section', kwargs={'section': 'homepage'}),
            block_dom_id(block),
        )

    return None
