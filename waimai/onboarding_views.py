# H4 新手体验：只读演示页（必须复用真实卖家/工作台模板）

from __future__ import annotations

from django.shortcuts import redirect, render

from .onboarding_helpers import get_official_shop_profile
from .onboarding_preview_helpers import (
    build_onboarding_order_detail_context,
    build_onboarding_print_qr_context,
    build_onboarding_seller_section_context,
    build_onboarding_work_hub_context,
    build_onboarding_work_login_context,
    seller_template_for_section,
)


def _official_shop_or_redirect():
    shop = get_official_shop_profile()
    if not shop:
        return None, redirect('home')
    return shop, None


def _render_seller_section(request, section: str):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    ctx = build_onboarding_seller_section_context(request, section)
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    return render(request, seller_template_for_section(section), ctx)


def onboarding_preview_seller_operating(request):
    return _render_seller_section(request, 'operating')


def onboarding_preview_seller_products(request):
    return _render_seller_section(request, 'products')


def onboarding_preview_seller_print_qr(request):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    ctx = build_onboarding_print_qr_context(request)
    return render(request, 'waimai/seller/product_qr_print.html', ctx)


def onboarding_preview_seller_workbench_manage(request):
    return _render_seller_section(request, 'workbench')


def onboarding_preview_work_login(request):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    return render(request, 'waimai/shop_work_login.html', build_onboarding_work_login_context(request))


def onboarding_preview_work_hub(request, view: str = 'orders'):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    valid = {'orders', 'waiter', 'kitchen', 'rider'}
    if view not in valid:
        view = 'orders'
    ctx = build_onboarding_work_hub_context(request, view)
    if not ctx:
        return redirect('home')
    return render(request, 'waimai/shop_work_hub.html', ctx)


def onboarding_preview_seller_orders(request):
    return _render_seller_section(request, 'orders')


def onboarding_preview_seller_order_detail(request, order_id):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    ctx = build_onboarding_order_detail_context(request, order_id)
    if not ctx:
        return redirect('onboarding_seller_orders')
    return render(request, 'waimai/order_detail.html', ctx)


def onboarding_preview_seller_payment(request):
    return _render_seller_section(request, 'payment')


def onboarding_preview_seller_homepage(request):
    return _render_seller_section(request, 'homepage')


def onboarding_preview_seller_dine(request):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    ctx = build_onboarding_seller_section_context(request, 'dine')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    if not ctx.get('dining_enabled'):
        return redirect('onboarding_seller_operating')
    return render(request, seller_template_for_section('dine'), ctx)


def onboarding_preview_seller_delivery(request):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    ctx = build_onboarding_seller_section_context(request, 'delivery')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    if not ctx.get('fulfillment_enabled'):
        return redirect('onboarding_seller_payment')
    return render(request, seller_template_for_section('delivery'), ctx)


def onboarding_preview_buyer_orders(request):
    shop, redir = _official_shop_or_redirect()
    if redir:
        return redir
    from .models import BuyOrder

    seller_id = shop.seller_id
    orders = list(BuyOrder.objects.filter(seller_id=seller_id).order_by('-created_at')[:8])
    ctx = {
        'onboarding_preview': True,
        'onboarding_page_title': '我的订单（演示）',
        'official_shop': shop,
        'home_url': '/',
        'orders': orders,
        'shop_name': shop.shop_name,
    }
    return render(request, 'waimai/onboarding/buyer_orders.html', ctx)
