# 工作台列表分页（今日订单历史 / 动作记录等共用）

from __future__ import annotations

from django.core.paginator import EmptyPage, Paginator

WORK_LIST_PAGE_SIZES = (10, 15, 20)


def resolve_work_list_page_size(raw_value, *, default: int = 10) -> int:
    """每页条数：10 / 15 / 20。"""
    try:
        size = int(raw_value or default)
    except (TypeError, ValueError):
        return default
    return size if size in WORK_LIST_PAGE_SIZES else default


def paginate_sequence(items, page_number, per_page: int):
    """内存列表分页，返回 Django Page 对象。"""
    paginator = Paginator(list(items), per_page)
    try:
        page_num = int(page_number or 1)
    except (TypeError, ValueError):
        page_num = 1
    if page_num < 1:
        page_num = 1
    try:
        return paginator.page(page_num)
    except EmptyPage:
        if paginator.num_pages:
            return paginator.page(paginator.num_pages)
        return paginator.page(1)


def work_list_pagination_context(
    base_url: str,
    request,
    *,
    page_param: str,
    per_page_param: str,
    per_page: int,
    page_obj,
) -> dict:
    """供 _workbench_list_pagination.html 使用的链接字典。"""
    preserved = {
        key: request.GET.get(key)
        for key in request.GET
        if key not in (page_param, per_page_param)
    }

    def _link(*, page: int | None = None, size: int | None = None) -> str:
        params = dict(preserved)
        params[per_page_param] = size if size is not None else per_page
        params[page_param] = page if page is not None else page_obj.number
        return append_query_params(base_url, params)

    return {
        'list_page': page_obj,
        'list_per_page': per_page,
        'list_page_sizes': WORK_LIST_PAGE_SIZES,
        'list_per_page_links': [
            {'size': size, 'url': _link(page=1, size=size)}
            for size in WORK_LIST_PAGE_SIZES
        ],
        'list_prev_url': _link(page=page_obj.previous_page_number()) if page_obj.has_previous() else '',
        'list_next_url': _link(page=page_obj.next_page_number()) if page_obj.has_next() else '',
    }


def append_query_params(base_url: str, params: dict) -> str:
    """在已有 query 的 URL 上追加参数。"""
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(base_url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None or value == '':
            existing.pop(key, None)
        else:
            existing[key] = str(value)
    query = urlencode(existing)
    return urlunparse(parsed._replace(query=query))
