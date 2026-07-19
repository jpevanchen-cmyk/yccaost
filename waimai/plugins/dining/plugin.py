# 饮食插件：导航「堂食营业」；桌台代码在本包；营业状态（全天/打烊）已拆到主体。
# 配送页签与配送权限由履约插件提供，本插件不再代挂。

from waimai.plugin_runtime.base import Plugin, SellerNavItem


class DiningPlugin(Plugin):
    id = 'dining'
    name = '饮食插件'
    description = (
        '堂食/打包/外卖接单开关与下单通道、分时段、等待、拼桌、桌台桌码、桌贴、'
        '扫桌码入口与游客堂食、饮食支付接入、堂食超时提示与桌台点选脚本等。'
        '停用后买家回落到主体「下单」通道；订单壳、商品壳、工作台饮食文案由本插件挂载。'
        '本店配送（配送费、配送页签）改由「履约配送插件」提供。'
        '全天营业时间与营业中/停止在主体「营业状态」。'
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

    def contribute_order_shell(self, order) -> dict:
        from .order_shell import contribute_dining_order_shell

        return contribute_dining_order_shell(order)

    def contribute_product_shell(self, seller_id: str) -> dict:
        """饮食插件把菜单清单与菜品用语挂到主体商品壳。"""
        return {
            'item_label': '菜品',
            'unit_label': '份',
            'sales_title': '菜品销量排行',
            'show_menu_catalog': True,
            'shop_catalog_intro': (
                '本店当前按「今日菜单清单」展示菜品与价格档位'
                '（会员价/特价以清单设置为准）。'
            ),
            'product_help': (
                '在此设定商品名称、通用价，以及是否允许会员价、特价。'
                '是否在客人菜单里展示，由「今日菜单清单」控制。'
            ),
            'sort_help': (
                '排序（0为不排序，越小越靠前，是客人看到菜单的排序）'
            ),
            'empty_shop_text': '该店铺暂无菜品',
        }

    def contribute_workbench_shell(self, seller_id: str) -> dict:
        """饮食插件把服务员/后厨用语挂到主体工作台壳。"""
        from .workbench_shell import contribute_dining_workbench_shell

        return contribute_dining_workbench_shell(seller_id)

    def staff_permission_definitions(self, seller_id: str) -> list[dict]:
        """饮食插件提供服务员/后厨业务权限（配送权由履约插件提供）。"""
        return [
            {
                'code': 'dining.waiter',
                'label': '服务员业务',
                'help_text': '可操作服务员 Tab：接待、交付、协助收款与派单等',
            },
            {
                'code': 'dining.kitchen',
                'label': '后厨业务',
                'help_text': '可操作后厨 Tab：备货、标记备好与派单等',
            },
        ]

    def staff_account_presets(self, seller_id: str) -> list[dict]:
        """饮食插件提供服务员/后厨预置；配送员模板改由履约插件提供。"""
        return [
            {
                'code': 'dining.waiter',
                'label': '服务员',
                'account_type': 'employee',
                'job_title': '服务员',
                'permissions': [
                    'dining.waiter',
                    'orders.view',
                    'orders.update_status',
                    'orders.confirm_payment',
                    'orders.contact',
                ],
            },
            {
                'code': 'dining.kitchen',
                'label': '后厨',
                'account_type': 'employee',
                'job_title': '后厨',
                'permissions': [
                    'dining.kitchen',
                    'orders.view',
                    'orders.update_status',
                ],
            },
        ]
