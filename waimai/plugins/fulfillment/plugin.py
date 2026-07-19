# 履约 / 配送插件：本店配送费、配送页签与配送权限（不绑死饮食）

from waimai.plugin_runtime.base import Plugin, SellerNavItem


class FulfillmentPlugin(Plugin):
    id = 'fulfillment'
    name = '履约配送插件'
    description = (
        '本店配送履约：配送费规则与计算、派单、工作台配送页签、取货送达、'
        '货到收款统计。停用后隐藏配送费与配送页签，且不再自动/手动派单；'
        '已有配送单与账号权限保留。饮食插件只管点餐通道，'
        '「怎么送」由本插件提供。'
    )

    def seller_nav_items(self) -> list[SellerNavItem]:
        return [
            SellerNavItem(
                section='delivery',
                label='配送费规则',
                icon='🚚',
                mobile_label='配送费',
                order=60,
            ),
        ]

    def contribute_workbench_shell(self, seller_id: str) -> dict:
        """贡献配送页签与中性配送用语。"""
        from .workbench_shell import contribute_fulfillment_workbench_shell

        return contribute_fulfillment_workbench_shell(seller_id)

    def staff_permission_definitions(self, seller_id: str) -> list[dict]:
        """配送业务权限（稳定编号 fulfillment.delivery）。"""
        return [
            {
                'code': 'fulfillment.delivery',
                'label': '本店配送业务',
                'help_text': '可操作配送 Tab：取货、送达与货到付款收款等',
            },
            {
                'code': 'fulfillment.cash_manage',
                'label': '现金异常与入金处理',
                'help_text': '可兜底处理货到付款异常，并确认或退回配送员交款申请',
            },
        ]

    def staff_account_presets(self, seller_id: str) -> list[dict]:
        """本店专属配送员预置模板。"""
        return [
            {
                'code': 'fulfillment.cash_manager',
                'label': '配送现金管理（可改名）',
                'account_type': 'management',
                'job_title': '配送主管',
                'permissions': [
                    'orders.view',
                    'orders.contact',
                    'orders.cancel',
                    'fulfillment.cash_manage',
                ],
            },
            {
                'code': 'fulfillment.rider',
                'label': '本店专属配送员',
                'account_type': 'employee',
                'job_title': '配送员',
                'permissions': [
                    'fulfillment.delivery',
                    'orders.view',
                    'orders.contact',
                ],
            },
        ]
