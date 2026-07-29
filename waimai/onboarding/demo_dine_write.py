# 新版新手体验：堂食营业页可写演示（桌台批量操作）

from __future__ import annotations

from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse

from waimai.models import ShopTable
from waimai.plugins.dining.seller_handlers import handle_dine_post
from waimai.scroll_helpers import redirect_with_anchor

from .dine_demo_helpers import register_demo_tables_from_numbers
from .tour_session import load_tour_query, touch_experience_tour_session, tour_query_for_redirect


def is_experience_dine_post(request) -> bool:
    """是否为堂食体验页允许的 POST"""
    if request.method != 'POST':
        return False
    if request.POST.get('save_operating') == '1':
        return False
    allowed = (
        'add_table',
        'table_batch_action',
        'add_virtual_code',
        'virtual_batch_action',
        'open_share_order',
    )
    return any(request.POST.get(k) == '1' for k in allowed)


def _experience_dine_redirect(request, anchor: str | None = None):
    touch_experience_tour_session(request)
    base = reverse('experience_preview_dine')
    parts = tour_query_for_redirect(request)
    url = base
    if parts:
        url = f'{base}?{"&".join(parts)}'
    return redirect_with_anchor(url, anchor)


def _experience_table_stickers_redirect(request, table_ids: list[str]):
    touch_experience_tour_session(request)
    base = reverse('experience_preview_table_stickers')
    q = load_tour_query(request)
    q['tables'] = ','.join(table_ids)
    return redirect(f'{base}?{urlencode(q)}')


def handle_experience_dine_post(request, seller_id: str):
    """体验堂食页 POST：桌台可写；导出 PDF 改跳网页预览"""
    touch_experience_tour_session(request)

    if request.POST.get('add_table') == '1':
        t_min = (request.POST.get('table_min') or '').strip()
        t_max = (request.POST.get('table_max') or '').strip()
        resp = handle_dine_post(request, seller_id)
        if t_min.isdigit() and t_max.isdigit():
            lo, hi = int(t_min), int(t_max)
            if lo <= hi:
                nums = [str(n) for n in range(lo, hi + 1)]
                register_demo_tables_from_numbers(seller_id, nums)
        return _rewrite_dine_redirect(resp, request)

    if request.POST.get('table_batch_action') == '1':
        action = (request.POST.get('batch_action') or '').strip()
        ids = request.POST.getlist('selected_ids')
        if action == 'export_pdf' and ids:
            tables = list(ShopTable.objects.filter(seller_id=seller_id, table_id__in=ids))
            if tables:
                return _experience_table_stickers_redirect(
                    request,
                    [str(t.table_id) for t in tables],
                )
        resp = handle_dine_post(request, seller_id)
        return _rewrite_dine_redirect(resp, request)

    resp = handle_dine_post(request, seller_id)
    return _rewrite_dine_redirect(resp, request)


def _rewrite_dine_redirect(resp, request):
    """把正式卖家后台 redirect 换成体验堂食页，并保留引导参数"""
    if getattr(resp, 'status_code', None) not in (301, 302, 303, 307, 308):
        return resp
    location = resp.get('Location', '') or ''
    anchor = ''
    if '#' in location:
        location, anchor = location.split('#', 1)
    if 'seller-panel/dine' not in location and '/dine/' not in location:
        return resp
    touch_experience_tour_session(request)
    base = reverse('experience_preview_dine')
    parts = tour_query_for_redirect(request)
    url = base
    if parts:
        url = f'{base}?{"&".join(parts)}'
    return redirect_with_anchor(url, anchor or None)
