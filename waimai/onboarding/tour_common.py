# 新版新手体验：小步脚本公共定义

from __future__ import annotations

from typing import Any

from .constants import AUTO_ADVANCE_SECONDS, AUTO_ADVANCE_SECONDS_TYPE_DEMO

TOUR_PAGES: dict[str, str] = {
    'home': '/',
    'shop_register': '/shop-register/',
    'preview_operating': '/experience/preview/seller/operating/',
    'preview_products': '/experience/preview/seller/products/',
    'preview_print_qr': '/experience/preview/seller/print-qr/',
    'preview_workbench_manage': '/experience/preview/seller/workbench/',
}


def ms(
    page: str,
    *,
    selector: str = '',
    title: str,
    body: str = '',
    tips: tuple[str, ...] = (),
    warn: str = '',
    demo_type: str = '',
    demo_text: str = '',
    demo_text_key: str = '',
    open_nav: bool = False,
    open_fold: str = '',
    fold_layout: list[str] | None = None,
    demo_click: str = '',
    path: str = '',
    auto_seconds: int | None = None,
    demo_fields: list[dict[str, str]] | None = None,
    demo_checked: bool = False,
) -> dict[str, Any]:
    """组装一个小步"""
    if auto_seconds is None:
        if demo_type in ('type', 'select', 'select_name', 'action', 'check', 'type_multi'):
            auto_seconds = AUTO_ADVANCE_SECONDS_TYPE_DEMO
        else:
            auto_seconds = AUTO_ADVANCE_SECONDS
    step: dict[str, Any] = {
        'page': page,
        'path': path or TOUR_PAGES.get(page, '/'),
        'selector': selector,
        'title': title,
        'body': body,
        'tips': list(tips),
        'warn': warn,
        'demoType': demo_type,
        'demoText': demo_text,
        'demoTextKey': demo_text_key,
        'openNav': open_nav,
        'openFold': open_fold,
        'demoClick': demo_click,
        'autoSeconds': auto_seconds,
    }
    if fold_layout is not None:
        step['foldLayout'] = list(fold_layout)
    if demo_fields:
        step['demoFields'] = demo_fields
    if demo_checked:
        step['demoChecked'] = True
    return step
