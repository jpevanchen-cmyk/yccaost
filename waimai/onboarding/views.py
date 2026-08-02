# 新版新手体验：页面视图



from __future__ import annotations



from django.http import JsonResponse

from django.shortcuts import redirect, render

from django.views.decorators.http import require_POST



from .boot import build_experience_boot_json, experience_shop_ready

from .demo_cleanup import cleanup_experience_demo_data

from .demo_product_write import handle_experience_product_post, is_experience_product_post
from .demo_write import handle_experience_menu_post

from .official_shop import get_official_shop_profile

from .demo_dine_write import handle_experience_dine_post, is_experience_dine_post
from .preview_helpers import (
    build_experience_dine_context,
    build_experience_delivery_context,
    build_experience_homepage_context,
    build_experience_homepage_showcase_context,
    build_experience_operating_context,
    build_experience_order_detail_context,
    build_experience_orders_context,
    build_experience_payment_context,
    build_experience_print_qr_context,
    build_experience_products_context,
    build_experience_table_stickers_context,
    build_experience_workbench_context,
    build_experience_work_hub_context,
    build_experience_work_login_context,
    experience_menu_panel_json,
)
from .tour_session import touch_experience_tour_session





def _shop_or_redirect():

    if not experience_shop_ready():

        return redirect('home')

    return None





def experience_home(request):

    """新版体验入口（试运行）"""

    shop = get_official_shop_profile()

    if not shop:

        return redirect('home')

    return render(request, 'waimai/onboarding/experience/home.html', {

        'experience_enabled': True,

        'experience_boot_json': build_experience_boot_json(),

        'official_shop_name': shop.shop_name,

        # 禁用旧版 boot，避免双引导

        'onboarding_boot_json': '',

    })





def experience_preview_operating(request):

    redir = _shop_or_redirect()

    if redir:

        return redir

    ctx = build_experience_operating_context(request)

    if not ctx:

        return redirect('experience_home')

    ctx['experience_boot_json'] = build_experience_boot_json()

    ctx['onboarding_boot_json'] = ''

    return render(request, 'waimai/seller/operating.html', ctx)





def experience_preview_products(request):

    """新版商品演示页：菜单清单可写"""

    redir = _shop_or_redirect()

    if redir:

        return redir

    shop = get_official_shop_profile()

    if not shop:

        return redirect('experience_home')

    seller_id = shop.seller_id
    touch_experience_tour_session(request)
    if request.method == 'POST':
        if is_experience_product_post(request):
            return handle_experience_product_post(request, seller_id)
        return handle_experience_menu_post(request, seller_id)
    if request.headers.get('X-Experience-Menu-Pick') == '1':
        return experience_menu_panel_json(request, seller_id)
    ctx = build_experience_products_context(request)

    if not ctx:

        return redirect('experience_home')

    ctx['experience_boot_json'] = build_experience_boot_json()

    ctx['onboarding_boot_json'] = ''

    return render(request, 'waimai/seller/products.html', ctx)


def experience_preview_print_qr(request):
    """新版批量打印二维码演示页（只读观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_print_qr_context(request)
    if not ctx:
        return redirect('experience_home')
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/product_qr_print.html', ctx)


def experience_preview_workbench(request):
    """新版员工工作台管理演示页（只读观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_workbench_context(request)
    if not ctx:
        return redirect('experience_home')
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/workbench.html', ctx)


def experience_preview_dine(request):
    """新版堂食营业演示页（桌台可写）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    shop = get_official_shop_profile()
    if not shop:
        return redirect('experience_home')
    seller_id = shop.seller_id
    touch_experience_tour_session(request)
    if request.method == 'POST':
        if is_experience_dine_post(request):
            return handle_experience_dine_post(request, seller_id)
        touch_experience_tour_session(request)
        ctx = build_experience_dine_context(request)
        if not ctx:
            return redirect('experience_home')
        if ctx.get('_redirect'):
            return redirect(ctx['_redirect'])
        ctx['experience_boot_json'] = build_experience_boot_json()
        ctx['onboarding_boot_json'] = ''
        return render(request, 'waimai/seller/dine.html', ctx)
    ctx = build_experience_dine_context(request)
    if not ctx:
        return redirect('experience_home')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/dine.html', ctx)


def experience_preview_table_stickers(request):
    """桌贴二维码网页预览（体验引导）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_table_stickers_context(request)
    if not ctx:
        return redirect('experience_home')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/table_sticker_print.html', ctx)


def experience_preview_delivery(request):
    """新版配送费规则演示页（只读观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_delivery_context(request)
    if not ctx:
        return redirect('experience_home')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/delivery.html', ctx)


def experience_preview_payment(request):
    """新版支付设置演示页（只读观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_payment_context(request)
    if not ctx:
        return redirect('experience_home')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/payment.html', ctx)


def experience_preview_orders(request):
    """新版订单管理演示页（只读观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_orders_context(request)
    if not ctx:
        return redirect('experience_home')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/orders.html', ctx)


def experience_preview_order_detail(request, order_id):
    """新版订单详情演示页（只读观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_order_detail_context(request, order_id)
    if not ctx:
        return redirect('experience_preview_orders')
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/order_detail.html', ctx)


def experience_preview_homepage(request):
    """新版展示主页演示页（只读观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_homepage_context(request)
    if not ctx:
        return redirect('experience_home')
    if ctx.get('_redirect'):
        return redirect(ctx['_redirect'])
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/seller/homepage.html', ctx)


def experience_preview_homepage_showcase(request):
    """新版店铺主页预览演示（假 UI）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_homepage_showcase_context(request)
    if not ctx:
        return redirect('experience_home')
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/onboarding/experience/homepage_showcase_demo.html', ctx)


def experience_preview_work_login(request):
    """演示工作台登录页（只观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    ctx = build_experience_work_login_context(request)
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/shop_work_login.html', ctx)


def experience_preview_work_hub(request, view: str = 'orders'):
    """演示店铺工作台（只观摩）"""
    redir = _shop_or_redirect()
    if redir:
        return redir
    valid = {'orders', 'waiter', 'kitchen', 'rider'}
    if view not in valid:
        view = 'orders'
    ctx = build_experience_work_hub_context(request, view)
    if not ctx:
        return redirect('experience_home')
    touch_experience_tour_session(request)
    ctx['experience_boot_json'] = build_experience_boot_json()
    ctx['onboarding_boot_json'] = ''
    return render(request, 'waimai/shop_work_hub.html', ctx)


@require_POST
def experience_cleanup(request):
    """退出体验或演示大步完成时清理演示数据"""

    shop = get_official_shop_profile()

    if not shop:

        return JsonResponse({'ok': False, 'error': 'no_shop'}, status=400)

    result = cleanup_experience_demo_data(shop.seller_id)

    return JsonResponse({'ok': True, **result})

