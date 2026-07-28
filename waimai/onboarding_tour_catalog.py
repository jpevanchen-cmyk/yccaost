# H4 新手体验：买家线脚本

from __future__ import annotations

from typing import Any

from .onboarding_tour_common import TOUR_PAGES, ms as _ms

# 兼容旧 import
__all__ = ['TOUR_PAGES', 'buyer_tour_majors']


def buyer_tour_majors(*, official_seller_id: str, has_demo_orders: bool) -> list[dict[str, Any]]:
    majors = [
        {
            'id': 'buyer-1',
            'title': '进店下单到支付',
            'graduateTitle': '下单流程已观摩',
            'graduateSummary': '您已了解选商品与加购；下一步看「我的」。',
            'microSteps': [
                _ms('shop', selector='.page-title', title='进入演示店',
                    body='客人看到的下单页；上方是店名与地址。',
                    tips=('与「展示主页」不是同一页。',)),
                _ms('shop', selector='[data-yc-tour="shop-dish-area"]', title='浏览商品',
                    body='点加购进入购物车；须登录的价格档会提示登录。'),
                _ms('shop', selector='[data-yc-tour="shop-cart-bar"]', title='购物车与下单',
                    body='加购后底部出现购物车栏，点进去确认并支付。',
                    warn='未选通道时须先选堂食/打包/外卖等（视店铺配置）。'),
            ],
        },
        {
            'id': 'buyer-2',
            'title': '「我的」',
            'graduateTitle': '「我的」已了解',
            'graduateSummary': '下一步看订单列表。',
            'microSteps': [
                _ms('home', selector='[data-yc-tour="nav-buyer-register"]', title='注册买家账号',
                    open_nav=True),
                _ms('register', selector='[data-yc-tour="buyer-register-form"]', title='买家注册页'),
                _ms('home', selector='[data-yc-tour="nav-login"]', title='登录后进「我的」',
                    open_nav=True),
            ],
        },
    ]
    buyer3_micro = [
        _ms('preview_buyer_orders', selector='[data-yc-tour="preview-banner"]', title='我的订单页'),
        _ms('preview_buyer_orders', selector='[data-yc-tour="buyer-order-sample"]', title='单笔订单卡片'),
    ] if has_demo_orders else [
        _ms('home', selector='', title='「我的订单」入口',
            body='登录买家后，菜单里会出现「我的订单」。'),
    ]
    majors.append({
        'id': 'buyer-3',
        'title': '我的订单',
        'graduateTitle': '买家体验完成',
        'graduateSummary': '若要体验开店，请回主页点「体验野草开店」。',
        'microSteps': buyer3_micro,
    })
    majors[0]['shopSellerId'] = official_seller_id
    return majors
