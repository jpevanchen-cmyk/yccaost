# 饮食插件：导航「堂食营业」；桌台代码在本包；营业状态（全天/打烊）已拆到主体。

from waimai.plugin_runtime.base import Plugin, SellerNavItem


class DiningPlugin(Plugin):
    id = 'dining'
    name = '饮食插件'
    description = (
        '堂食/打包/外卖接单开关与下单通道、分时段、等待、拼桌、桌台桌码、桌贴、'
        '扫桌码入口与游客堂食、饮食支付接入、堂食超时提示与桌台点选脚本等。'
        '停用后买家回落到主体「下单」通道；全天营业时间与营业中/停止在主体「营业状态」。'
    )

    def seller_nav_items(self) -> list[SellerNavItem]:
        return [
            SellerNavItem(
                section='dine',
                label='堂食营业',
                icon='🪑',
                mobile_label='堂食',
                order=40,
            ),
        ]
