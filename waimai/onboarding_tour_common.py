# H4 新手体验：小步脚本公共定义

from __future__ import annotations

from typing import Any

# 小步自动前进默认秒数（有假输入演示的步用较长值）
AUTO_ADVANCE_SECONDS = 8
AUTO_ADVANCE_SECONDS_TYPE_DEMO = 12

TOUR_PAGES: dict[str, str] = {
    'home': '/',
    'shop_register': '/shop-register/',
    'register': '/register/',
    'shop': '/shop/',
    'preview_operating': '/onboarding/preview/seller/operating/',
    'preview_products': '/onboarding/preview/seller/products/',
    'preview_print_qr': '/onboarding/preview/seller/print-qr/',
    'preview_workbench_manage': '/onboarding/preview/seller/workbench/',
    'preview_work_login': '/onboarding/preview/work/login/',
    'preview_work_hub': '/onboarding/preview/work/orders/',
    'preview_orders': '/onboarding/preview/seller/orders/',
    'preview_order_detail': '/onboarding/preview/seller/orders/demo/',
    'preview_payment': '/onboarding/preview/seller/payment/',
    'preview_homepage': '/onboarding/preview/seller/homepage/',
    'preview_dine': '/onboarding/preview/seller/dine/',
    'preview_delivery': '/onboarding/preview/seller/delivery/',
    'preview_buyer_orders': '/onboarding/preview/buyer/orders/',
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
    open_nav: bool = False,
    open_fold: str = '',
    demo_click: str = '',
    path: str = '',
    auto_seconds: int | None = None,
) -> dict[str, Any]:
    """组装一个小步"""
    if auto_seconds is None:
        auto_seconds = (
            AUTO_ADVANCE_SECONDS_TYPE_DEMO if demo_type == 'type' else AUTO_ADVANCE_SECONDS
        )
    return {
        'page': page,
        'path': path or TOUR_PAGES.get(page, '/'),
        'selector': selector,
        'title': title,
        'body': body,
        'tips': list(tips),
        'warn': warn,
        'demoType': demo_type,
        'demoText': demo_text,
        'openNav': open_nav,
        'openFold': open_fold,
        'demoClick': demo_click,
        'autoSeconds': auto_seconds,
    }
