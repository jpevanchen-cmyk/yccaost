# 卖家后台：展示主页积木编辑

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .home_page_helpers import (
    ensure_home_page_for_seller,
    get_block_spec,
    set_server_entry,
)
from .scroll_helpers import redirect_with_anchor


def handle_home_page_post(request, seller_id: str):
    """保存主页总设置或单个积木块"""
    page = ensure_home_page_for_seller(seller_id)
    if page is None:
        messages.error(request, '无法创建主页配置')
        return redirect('seller_panel_section', section='homepage')

    if 'save_home_page_settings' in request.POST:
        mode = (request.POST.get('order_nav_mode') or 'to_shop').strip()
        if mode not in ('to_shop', 'to_cta_block'):
            mode = 'to_shop'
        page.order_nav_mode = mode
        page.save(update_fields=['order_nav_mode', 'updated_at'])
        if request.POST.get('set_as_server_entry') == '1':
            set_server_entry(seller_id)
            messages.success(request, '已保存，并设为本服务器默认入口主页')
        else:
            if page.is_server_entry:
                page.is_server_entry = False
                page.save(update_fields=['is_server_entry', 'updated_at'])
            messages.success(request, '主页设置已保存')
        return redirect_with_anchor(
            reverse('seller_panel_section', kwargs={'section': 'homepage'}),
            'home-page-settings',
        )

    if 'save_home_block' in request.POST:
        block_id = (request.POST.get('block_id') or '').strip()
        block = page.blocks.filter(block_id=block_id).first()
        if not block:
            messages.error(request, '找不到该积木块')
            return redirect('seller_panel_section', section='homepage')

        block.title = (request.POST.get('title') or '')[:120]
        block.body = request.POST.get('body') or ''
        block.image_url = (request.POST.get('image_url') or '')[:500]
        block.link_url = (request.POST.get('link_url') or '')[:500]
        block.nav_label = (request.POST.get('nav_label') or '')[:32]
        block.is_enabled = request.POST.get('is_enabled') == '1'
        block.show_in_nav = request.POST.get('show_in_nav') == '1'
        try:
            block.sort_order = max(0, int(request.POST.get('sort_order') or block.sort_order))
        except (TypeError, ValueError):
            pass
        block.save()
        spec = get_block_spec(block.block_type)
        label = spec.label if spec else block.block_type
        messages.success(request, f'已保存积木「{label}」')
        return redirect_with_anchor(
            reverse('seller_panel_section', kwargs={'section': 'homepage'}),
            f'block-{block.block_type}',
        )

    return None
