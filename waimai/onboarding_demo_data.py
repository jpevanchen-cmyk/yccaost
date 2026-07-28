# H4 新手体验：只读演示用固定假数据（每次体验一致）

from __future__ import annotations

from decimal import Decimal

# 销量排行（日/周/月各 5 行）
SALES_RANK_DAY = [
    {'name': '演示可乐', 'qty': 28, 'amount': '84.00'},
    {'name': '演示面包', 'qty': 15, 'amount': '45.00'},
    {'name': '演示矿泉水', 'qty': 12, 'amount': '36.00'},
    {'name': '演示薯片', 'qty': 9, 'amount': '27.00'},
    {'name': '演示牛奶', 'qty': 6, 'amount': '24.00'},
]
SALES_RANK_WEEK = [
    {'name': '演示可乐', 'qty': 132, 'amount': '396.00'},
    {'name': '演示面包', 'qty': 88, 'amount': '264.00'},
    {'name': '演示矿泉水', 'qty': 76, 'amount': '228.00'},
    {'name': '演示薯片', 'qty': 54, 'amount': '162.00'},
    {'name': '演示牛奶', 'qty': 41, 'amount': '164.00'},
]
SALES_RANK_MONTH = [
    {'name': '演示可乐', 'qty': 520, 'amount': '1560.00'},
    {'name': '演示面包', 'qty': 410, 'amount': '1230.00'},
    {'name': '演示矿泉水', 'qty': 365, 'amount': '1095.00'},
    {'name': '演示薯片', 'qty': 290, 'amount': '870.00'},
    {'name': '演示牛奶', 'qty': 210, 'amount': '840.00'},
]

# 菜单/商品清单 1～5
DEMO_MENU_PROFILES = [
    {'id': 'p1', 'name': '清单 1', 'active': True},
    {'id': 'p2', 'name': '清单 2', 'active': False},
    {'id': 'p3', 'name': '清单 3', 'active': False},
    {'id': 'p4', 'name': '清单 4', 'active': False},
    {'id': 'p5', 'name': '清单 5', 'active': False},
]

DEMO_MENU_ITEMS = [
    {
        'name': '演示可乐',
        'listed': True,
        'member_show': True,
        'member_allowed': True,
        'special_show': False,
        'special_allowed': True,
        'cap': '',
        'sold': 3,
    },
    {
        'name': '演示面包',
        'listed': True,
        'member_show': False,
        'member_allowed': False,
        'special_show': True,
        'special_allowed': True,
        'cap': '50',
        'sold': 1,
    },
    {
        'name': '演示矿泉水',
        'listed': False,
        'member_show': False,
        'member_allowed': True,
        'special_show': False,
        'special_allowed': False,
        'cap': '',
        'sold': 0,
    },
]

DEMO_DISHES = [
    {
        'name': '演示可乐',
        'price': Decimal('3.00'),
        'active': True,
        'member': True,
        'special': False,
        'sort': 1,
        'code': 'A001',
    },
    {
        'name': '演示面包',
        'price': Decimal('3.00'),
        'active': True,
        'member': False,
        'special': True,
        'sort': 2,
        'code': 'A002',
    },
]

DEMO_QR_PRINT_CARDS = [
    {'code': 'A001', 'name': '演示可乐', 'tier': '通用价'},
    {'code': 'A001', 'name': '演示可乐', 'tier': '会员价'},
    {'code': 'A002', 'name': '演示面包', 'tier': '特价'},
]

# 演示用工位权限清单（与主体通用权限一致；插件权限在体验文案里另说明）
DEMO_STAFF_PERMISSIONS = [
    {'code': 'orders.view', 'label': '仅看订单', 'help': '可打开「订单处理」查看本店基础订单'},
    {'code': 'orders.update_status', 'label': '可改订单状态', 'help': '可推进：开始处理 → 可交付 → 完成'},
    {'code': 'orders.confirm_payment', 'label': '可确认收款', 'help': '可确认现金等到店收款'},
    {'code': 'orders.contact', 'label': '可联系顾客', 'help': '可查看联系信息并在订单沟通里留言'},
    {'code': 'orders.cancel', 'label': '允许取消订单', 'help': '满足沟通门槛后可取消本店订单'},
]

DEMO_STAFF_ACCOUNTS = [
    {
        'type': '管理职务',
        'title': '店长',
        'username': 'demo_mgr',
        'active': True,
        'permissions': ['orders.view', 'orders.update_status', 'orders.confirm_payment', 'orders.contact', 'orders.cancel'],
    },
    {
        'type': '普通员工',
        'title': '服务员',
        'username': 'demo_waiter',
        'active': True,
        'permissions': ['orders.view', 'orders.update_status', 'orders.confirm_payment', 'orders.contact'],
    },
]

DEMO_ATTENDANCE_ROWS = [
    {'role': '服务员', 'name': '小服务员', 'status': '上班', 'account': '启用'},
    {'role': '后厨', 'name': '小后厨', 'status': '休息', 'account': '启用'},
]

DEMO_ORDERS = [
    {
        'display_no': 'YC-DEMO-001',
        'time': '07-27 10:15',
        'amount': '28.50',
        'fulfillment': '打包',
        'pay': '已支付',
        'status': '已完成',
        'buyer': '演示买家',
        'address': '到店自取',
        'payment_method': '微信支付',
        'unread': 0,
    },
    {
        'display_no': 'YC-DEMO-002',
        'time': '07-27 09:40',
        'amount': '15.00',
        'fulfillment': '下单',
        'pay': '待支付',
        'status': '待处理',
        'buyer': '路人甲',
        'address': '001 号桌',
        'payment_method': '现金',
        'unread': 2,
    },
]

DEMO_TABLES = ['001', '002', '007']

DEMO_WORK_ORDER_ROW = {
    'display_no': 'YC-DEMO-003',
    'fulfillment': '打包',
    'amount': '18.00',
    'status': '待处理',
}
