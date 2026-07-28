# H4 新手体验：卖家开店线小步脚本（通用 + 插件可选）

from __future__ import annotations

from typing import Any

from .onboarding_tour_common import TOUR_PAGES, ms as _ms


def seller_tour_majors(
    *,
    official_seller_id: str,
    product_shell: dict[str, Any],
    dining_enabled: bool,
    fulfillment_enabled: bool,
) -> list[dict[str, Any]]:
    """组装卖家体验各大步；文案随 product_shell 与插件开关变化"""
    item = product_shell.get('item_label', '商品')
    catalog = product_shell.get('catalog_word', '商品列表')
    catalog_title = product_shell.get('catalog_panel_title', '商品列表')
    sales_title = product_shell.get('sales_title', '商品销量排行')
    dine_hint = '堂食/打包/外卖细分在「堂食营业」大步。' if dining_enabled else '细分通道可在启用相应插件后配置。'

    majors: list[dict[str, Any]] = [
        _seller_register(),
        {
            'id': 'seller-2',
            'title': '营业状态',
            'graduateTitle': '营业状态已观摩',
            'graduateSummary': f'您已了解全天营业时间与营业中/停止开关；下一步看{item}上架。',
            'microSteps': [
                _ms('preview_operating', selector='[data-yc-tour="operating-intro"]', title='营业状态管什么',
                    body='控制是否接单与全天营业时间；与细分通道分开。',
                    tips=(dine_hint,)),
                _ms('preview_operating', selector='[data-yc-tour="fold-operating-form"]', title='展开「营业时间和状态设定」',
                    open_fold='#status-form'),
                _ms('preview_operating', selector='[data-yc-tour="operating-open-time"]', title='开始营业时间',
                    body='新订单须落在设定时间段内。', demo_type='type', demo_text='09:00'),
                _ms('preview_operating', selector='[data-yc-tour="operating-close-time"]', title='结束营业时间',
                    demo_type='type', demo_text='22:00'),
                _ms('preview_operating', selector='[data-yc-tour="operating-save-hours"]', title='保存营业时间',
                    body='改时间后须点保存；体验模式不会真保存。'),
                _ms('preview_operating', selector='[data-yc-tour="operating-status-text"]', title='当前状态',
                    body='一眼查看营业中或停止营业。'),
                _ms('preview_operating', selector='[data-yc-tour="operating-toggle"]', title='营业中 / 停止营业',
                    body='临时打烊用此按钮；不必改时间表。',
                    warn='容易错：只改状态不改时间，夜间仍可能拒单。'),
                _ms('preview_operating', selector='[data-yc-tour="operating-intro"]', title='与店铺主页同步',
                    body='店铺主页上的营业状态会自动读取这里，不用重复填。'),
            ],
        },
        _seller_products(item, catalog, catalog_title, sales_title, official_seller_id),
        _seller_workbench_manage(dining_enabled, fulfillment_enabled),
        _seller_workbench_practice(dining_enabled, fulfillment_enabled),
        _seller_orders(),
        _seller_payment(fulfillment_enabled),
        _seller_homepage(),
    ]
    if dining_enabled:
        majors.append(_seller_dine())
    if fulfillment_enabled:
        majors.append(_seller_delivery())
    return majors


def _seller_register() -> dict[str, Any]:
    return {
        'id': 'seller-1',
        'title': '注册并开通店铺',
        'graduateTitle': '开通店铺流程已观摩',
        'graduateSummary': '您已了解开通页各字段；下一步看营业状态。',
        'microSteps': [
            _ms('home', selector='[data-yc-tour="nav-shop-register"]', title='找到「店铺开通」入口',
                body='开店从服务器主页菜单进入；手机请先点 ☰。', open_nav=True),
            _ms('home', selector='[data-yc-tour="block-onboarding"]', title='「新手体验」区',
                body='体验区可随时再开引导；真开店走「店铺开通」。'),
            _ms('shop_register', selector='[data-yc-tour="shop-register-title"]', title='开通页做什么',
                body='同时创建店主账号与店铺资料；体验不真提交。'),
            _ms('shop_register', selector='#id_username', title='店主用户名', demo_type='type',
                demo_text='demo_my_shop',
                body='即登录「管理店铺」用的账号。',
                tips=('150 字以内；字母数字与 @ . + - _ 。',),
                warn='容易错：含空格或中文无法提交。'),
            _ms('shop_register', selector='#id_password1', title='登录密码', demo_type='type', demo_text='DemoPass123'),
            _ms('shop_register', selector='#id_password2', title='确认密码',
                warn='容易错：两次不一致无法提交。'),
            _ms('shop_register', selector='#id_shop_name', title='店铺名称', demo_type='type', demo_text='演示小馆'),
            _ms('shop_register', selector='#id_shop_type', title='店铺类型',
                body='影响部分默认文案与后台分区。'),
            _ms('shop_register', selector='#id_address', title='店铺地址', demo_type='type',
                demo_text='示例市示例路 1 号'),
            _ms('shop_register', selector='[data-yc-tour="shop-register-submit"]', title='提交开通',
                body='真注册点此创建；体验不会保存。'),
        ],
    }


def _seller_products(
    item: str,
    catalog: str,
    catalog_title: str,
    sales_title: str,
    seller_id: str,
) -> dict[str, Any]:
    shop_preview = f'/shop/?seller_id={seller_id}'
    steps = [
        _ms('preview_products', selector='[data-yc-tour="fold-sales-ranking"]', title=f'卡片 1 · {sales_title}',
            open_fold='#sales-ranking', body='看哪些卖得好；只统计已完成订单。'),
        _ms('preview_products', selector='[data-yc-tour="sales-rank-tabs"]', title='日 / 周 / 月排行',
            body='点标签切换；演示用固定假数据。'),
        _ms('preview_products', selector='[data-yc-tour="sales-rank-day"]', title='日排行',
            demo_click='.sales-rank-tab[data-panel="sales-day"]'),
        _ms('preview_products', selector='[data-yc-tour="sales-rank-week"]', title='周排行',
            demo_click='.sales-rank-tab[data-panel="sales-week"]'),
        _ms('preview_products', selector='[data-yc-tour="sales-rank-month"]', title='月排行',
            demo_click='.sales-rank-tab[data-panel="sales-month"]'),
        _ms('preview_products', selector='[data-yc-tour="fold-menu-panel"]', title=f'卡片 2 · {catalog_title}',
            open_fold='#menu-panel', body=f'客人店铺页以「使用中」的{catalog}为准。'),
        _ms('preview_products', selector='[data-yc-tour="menu-intro"]', title=f'{catalog}做什么',
            tips=('切换前须无未结束订单。',)),
        _ms('preview_products', selector='[data-yc-tour="menu-create-form"]', title=f'新建{catalog}',
            body='填名称后点创建。'),
        _ms('preview_products', selector='[data-yc-tour="menu-copy-select"]', title='复制已有清单',
            body='选「清单 1」等复制后再改，有时更快捷。',
            demo_type='type', demo_text='清单 3'),
        _ms('preview_products', selector='[data-yc-tour="menu-copy-select"]', title='或选「全新」',
            body='纳入全部商品，从零配。'),
        _ms('preview_products', selector='[data-yc-tour="menu-profile-select"]', title=f'选择{catalog}',
            body='演示预设清单 1～5；切换后看下方详情。'),
        _ms('preview_products', selector='[data-yc-tour="menu-activate-btn"]', title='切换使用',
            body='只有「使用中」的清单才对客人生效。'),
        _ms('preview_products', selector='[data-yc-tour="menu-delete-btn"]', title='删除清单',
            warn='使用中的清单不能删除。'),
        _ms('preview_products', selector='[data-yc-tour="menu-item-table"]', title='上架 / 下架',
            body=f'下架后客人看不到、不能对该{item}下单。'),
        _ms('preview_products', selector='[data-yc-tour="menu-item-table"]', title='展示会员价 / 展示特价',
            body='须与「商品管理」里「是否允许」同时满足才展示。'),
        _ms('preview_products', selector='[data-yc-tour="menu-print-qr-link"]', title='批量打印本清单二维码',
            body='贴货架；小超市/便利店可让顾客扫码加购（须登录买家）。'),
        _ms('preview_print_qr', selector='[data-yc-tour="print-qr-intro"]', title='批量打印页',
            body='使用中清单内、已上架商品；每档位一张码。'),
        _ms('preview_print_qr', selector='[data-yc-tour="print-qr-g18-hint"]', title='规划 · 收银结账码',
            body='「扫货后至收银台出示结账码统一算账」见手册 G1-8，尚未上线。',
            tips=('当前 G1-6/7 已支持扫商品码加购。',)),
        _ms('preview_print_qr', selector='[data-yc-tour="print-qr-btn"]', title='打印本页',
            body='浏览器打印贴货架。'),
        _ms('preview_products', selector='[data-yc-tour="fold-product-add"]', title=f'卡片 3 · 添加新{item}',
            open_fold='#product-add'),
        _ms('preview_products', selector='[data-yc-tour="add-name"]', title=f'{item}名称',
            demo_type='type', demo_text='演示矿泉水'),
        _ms('preview_products', selector='[data-yc-tour="add-price"]', title='通用价格',
            demo_type='type', demo_text='3.50'),
        _ms('preview_products', selector='[data-yc-tour="add-sort"]', title='排序',
            body='数字越小越靠前。'),
        _ms('preview_products', selector='[data-yc-tour="add-desc"]', title='描述',
            body='普通/会员/特价可分档描述。'),
        _ms('preview_products', selector='[data-yc-tour="add-member"]', title='会员价',
            body='勾选后可在清单里控制是否展示。'),
        _ms('preview_products', selector='[data-yc-tour="add-special"]', title='特价',
            body='勾选后可在清单里控制是否展示。'),
        _ms('preview_products', selector='[data-yc-tour="add-image"]', title='商品图片',
            body='添加时可随「添加商品」一起上传；支持多张，系统会一张一张处理。',
            tips=('正式店也可稍后在「商品管理」里补传、调序。',)),
        _ms('preview_products', selector='[data-yc-tour="add-list-all"]', title='添加后全部清单上架',
            warn='勾选后客人可能立刻看到；须二次确认。'),
        _ms('preview_products', selector='[data-yc-tour="add-submit"]', title=f'添加{item}',
            body='体验不真提交。'),
        _ms('preview_products', selector='[data-yc-tour="fold-product-list"]', title=f'卡片 4 · {item}管理',
            open_fold='#product-list'),
        _ms('preview_products', selector='[data-yc-tour="product-sample-row"]', title='列表与徽章',
            body='可看上架/下架、会员价、特价等状态。'),
        _ms('preview_products', selector='[data-yc-tour="product-edit-btn"]', title='编辑商品',
            body='点「编辑」展开下方修改区。'),
        _ms('preview_products', selector='[data-yc-tour="product-edit-panel"]', title='修改名称与价格',
            body='可改通用价、会员价、特价与描述等（演示为只读）。'),
        _ms('preview_products', selector='[data-yc-tour="product-image-upload"]', title='上传新图片',
            body='编辑区可选图后点「开始上传」，系统逐张处理并自动编号。',
            tips=('单张大小与总数有上限，见页面说明。',)),
        _ms('preview_products', selector='[data-yc-tour="product-image-manage"]', title='已上传图片管理',
            body='可调顺序（↑↓）、删除；也可把文件放进编号文件夹后点「同步图片」。'),
        _ms('preview_products', selector='[data-yc-tour="preview-shop-order-link"]', title='预览店铺（下单页）',
            body='新窗口打开客人加购页；不是店铺主页。',
            tips=(f'地址：{shop_preview}',)),
    ]
    return {
        'id': 'seller-3',
        'title': f'{item}上架',
        'graduateTitle': f'{item}上架已观摩',
        'graduateSummary': '下一步：员工工作台 · 管理。',
        'microSteps': steps,
    }


def _seller_workbench_manage(dining_enabled: bool, fulfillment_enabled: bool) -> dict[str, Any]:
    extra = []
    if dining_enabled:
        extra.append('饮食插件开启后可建服务员/后厨模板。')
    if fulfillment_enabled:
        extra.append('履约插件开启后可建配送员模板。')
    tips_tail = tuple(extra) if extra else ('员工不用野草主页「登录」。',)
    return {
        'id': 'seller-4a',
        'title': '员工工作台 · 管理',
        'graduateTitle': '工作台管理已观摩',
        'graduateSummary': '下一步：工作台实操（扫码登录与各岗位）。',
        'microSteps': [
            _ms('preview_workbench_manage', selector='[data-yc-tour="workbench-intro"]', title='本页管什么',
                body='员工二维码、协作设置、考勤与子账号权限。', tips=tips_tail),
            _ms('preview_workbench_manage', selector='[data-yc-tour="fold-workbench-qr"]', title='工作台登录二维码',
                open_fold='#workbench-qr'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="workbench-qr-body"]', title='二维码贴哪里',
                body='员工扫此码上班，不要用野草生态登录页。'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="fold-workbench-settings"]', title='协作设置',
                open_fold='#workbench-settings-form'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="fold-workbench-attendance"]', title='员工状态与考勤',
                open_fold='#workbench-attendance'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="attendance-export"]', title='导出考勤 CSV'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="fold-mgmt-staff"]', title='新建管理职务',
                open_fold='#management-staff-create'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="mgmt-staff-intro"]', title='管理职务说明',
                body='店长、经理等名称由您填写；具体能做什么看下面勾选的权限。'),
            _ms('preview_workbench_manage', selector='#management-staff-create form', title='员工登录名',
                open_fold='#management-staff-create', demo_type='type', demo_text='小张'),
            _ms('preview_workbench_manage', selector='#management-staff-create form', title='设置密码',
                body='员工用此名和密码在工作台登录页上班。'),
            _ms('preview_workbench_manage', selector='#management-staff-create form', title='职务名称',
                demo_type='type', demo_text='值班经理'),
            _ms('preview_workbench_manage', selector='#management-staff-create form', title='勾选权限',
                body='勾什么就能做什么；不勾则看不到对应功能。',
                tips=('例如：只勾「仅看订单」= 只能看不能改。',)),
            _ms('preview_workbench_manage', selector='[data-yc-tour="mgmt-staff-submit"]', title='创建管理职务',
                body='体验不真提交；正式店点绿色按钮保存。'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="fold-emp-staff"]', title='新建普通员工',
                open_fold='#employee-staff-create'),
            _ms('preview_workbench_manage', selector='#employee-staff-create form', title='预置模板（可选）',
                open_fold='#employee-staff-create',
                body='饮食/履约插件开启后，会出现服务员、后厨、配送员等模板。',
                tips=tuple(extra) if extra else ('也可不套模板，自己填职务名与权限。',)),
            _ms('preview_workbench_manage', selector='#employee-staff-create form', title='普通员工职务名',
                demo_type='type', demo_text='收银员'),
            _ms('preview_workbench_manage', selector='#employee-staff-create form', title='普通员工登录名',
                demo_type='type', demo_text='小李'),
            _ms('preview_workbench_manage', selector='#employee-staff-create form', title='普通员工权限',
                body='通常比管理职务少；例如一般不给「取消订单」。'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="emp-staff-submit"]', title='创建普通员工',
                body='体验不真提交。'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="fold-staff-list"]', title='子账号列表',
                open_fold='#staff-account-list'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="staff-account-row"]', title='展开已有账号',
                body='点一行可展开，修改职务名与权限。'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="staff-edit-permissions"]', title='修改权限',
                body='随时可增删勾选；员工下次登录即按新权限显示 Tab。'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="staff-edit-save"]', title='保存修改'),
            _ms('preview_workbench_manage', selector='[data-yc-tour="staff-toggle-active"]', title='停用 / 启用账号',
                warn='离职或暂不用时可停用，不必删账号。'),
        ],
    }


def _seller_workbench_practice(dining_enabled: bool, fulfillment_enabled: bool) -> dict[str, Any]:
    steps = [
        _ms('preview_workbench_manage', selector='[data-yc-tour="workbench-open-login-link"]', title='打开工作台登录页',
            body='从后台链接进入；员工也可直接扫 QR。'),
        _ms('preview_work_login', selector='[data-yc-tour="work-login-intro"]', title='登录页说明',
            body='买家去点菜页，不要在此登录。'),
        _ms('preview_work_login', selector='[data-yc-tour="work-login-username"]', title='输入名字',
            demo_type='type', demo_text='小服务员'),
        _ms('preview_work_login', selector='[data-yc-tour="work-login-password"]', title='输入密码',
            demo_type='type', demo_text='******'),
        _ms('preview_work_login', selector='[data-yc-tour="work-login-remember"]', title='记住密码',
            warn='公共电脑请勿勾选。'),
        _ms('preview_work_login', selector='[data-yc-tour="work-login-demo-enter"]', title='进入演示工作台',
            body='体验用按钮，模拟已登录。'),
        _ms('preview_work_hub', selector='[data-yc-tour="work-status-bar"]', title='上班 / 休息 / 下班',
            path='/onboarding/preview/work/orders/'),
        _ms('preview_work_hub', selector='[data-yc-tour="work-view-tabs"]', title='岗位 Tab',
            body='不同权限看到不同 Tab。', path='/onboarding/preview/work/orders/'),
        _ms('preview_work_hub', selector='[data-yc-tour="work-panel-body"]', title='订单台操作',
            body='按件处理、交付；可确认现金。',
            path='/onboarding/preview/work/orders/'),
    ]
    if dining_enabled:
        steps.extend([
            _ms('preview_work_hub', selector='[data-yc-tour="work-waiter-action"]', title='服务员 Tab',
                body='接待、交付、协助收款与派单。',
                path='/onboarding/preview/work/waiter/'),
            _ms('preview_work_hub', selector='[data-yc-tour="work-kitchen-action"]', title='后厨 Tab',
                body='备货、标记备好。',
                path='/onboarding/preview/work/kitchen/'),
        ])
    if fulfillment_enabled:
        steps.extend([
            _ms('preview_work_hub', selector='[data-yc-tour="work-rider-action"]', title='配送员 Tab',
                body='取货、送达、货到收款。',
                path='/onboarding/preview/work/rider/'),
            _ms('preview_work_hub', selector='[data-yc-tour="work-rider-remit"]', title='骑手 · 现金交款申请',
                body='配送员在工作台发起交款；店主在「支付设置」里确认入金。',
                path='/onboarding/preview/work/rider/'),
        ])
    steps.append(
        _ms('preview_work_hub', selector='[data-yc-tour="work-audit-hint"]', title='与工作台分工',
            body='查历史订单在「订单管理」；现场干活在工作台。',
            path='/onboarding/preview/work/orders/'),
    )
    return {
        'id': 'seller-4b',
        'title': '员工工作台 · 实操',
        'graduateTitle': '工作台实操已观摩',
        'graduateSummary': '下一步：订单管理。',
        'microSteps': steps,
    }


def _seller_orders() -> dict[str, Any]:
    return {
        'id': 'seller-5',
        'title': '订单管理',
        'graduateTitle': '订单管理已观摩',
        'graduateSummary': '下一步：支付设置。',
        'microSteps': [
            _ms('preview_orders', selector='[data-yc-tour="fold-boss-notify"]', title='老板邮件通知',
                open_fold='#boss-order-notify',
                body='店主不在工作台时的新单邮件；与 SMTP/值班邮件分开。'),
            _ms('preview_orders', selector='[data-yc-tour="boss-notify-save"]', title='保存老板通知'),
            _ms('preview_orders', selector='[data-yc-tour="orders-intro"]', title='本页定位',
                body='查单、核对；备货收款去工作台。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-search-q"]', title='搜索',
                demo_type='type', demo_text='YC-DEMO'),
            _ms('preview_orders', selector='[data-yc-tour="orders-filters"]', title='筛选条件',
                body='可按订单状态、支付、履约方式、时间范围组合筛选。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-filter-status"]', title='订单状态',
                body='例如：只看「已完成」或「待处理」。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-filter-pay"]', title='支付状态',
                body='区分已支付、待支付、未收款等。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-filter-fulfillment"]', title='履约方式',
                body='打包、堂食、配送等按店型显示。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-search-hint"]', title='默认范围',
                body='默认近 1 个月、最多 100 条；关键词也匹配买家备注。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-sample-row"]', title='订单卡片',
                body='金额、支付与履约状态一目了然。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-sample-meta"]', title='买家与履约信息',
                body='可看买家名、桌号/地址、支付方式等。'),
            _ms('preview_orders', selector='[data-yc-tour="orders-detail-link"]', title='查看订单详情',
                body='点进去可看明细、沟通记录；有未读留言会显示红点。',
                tips=('现场备货收款请去「店铺工作台」，本页以查单核对为主。',)),
            _ms('preview_order_detail', selector='[data-yc-tour="order-detail-hero"]', title='订单详情总览',
                body='订单号、履约方式、合计金额与当前状态。'),
            _ms('preview_order_detail', selector='[data-yc-tour="order-detail-items"]', title='商品明细',
                body='每笔买了什么、数量与单价。'),
            _ms('preview_order_detail', selector='[data-yc-tour="order-detail-chat"]', title='订单沟通',
                body='与买家的留言记录；重要协商请写在这里留痕。'),
        ],
    }


def _seller_payment(fulfillment_enabled: bool) -> dict[str, Any]:
    steps = [
        _ms('preview_payment', selector='[data-yc-tour="payment-settings-box"]', title='支付设置',
            body='各支付方式可单独开关。'),
        _ms('preview_payment', selector='[data-yc-tour="payment-experience-hint"]', title='体验店说明'),
        _ms('preview_payment', selector='[data-yc-tour="payment-demo"]', title='演示支付',
            tips=('正式营业请关闭演示支付。',)),
        _ms('preview_payment', selector='[data-yc-tour="payment-wechat"]', title='微信支付',
            warn='体验店无法开通真微信。'),
        _ms('preview_payment', selector='[data-yc-tour="payment-cash"]', title='到店付'),
        _ms('preview_payment', selector='[data-yc-tour="payment-save"]', title='保存'),
    ]
    if fulfillment_enabled:
        steps.append(
            _ms('preview_payment', selector='[data-yc-tour="rider-cash-box"]', title='配送员现金入金',
                body='与配送员在工作台发起的交款申请配合。'),
        )
    steps.append(
        _ms('preview_payment', selector='[data-yc-tour="payment-settings-box"]', title='小结',
            body='下一步：展示主页（后台编辑客人门面）。'),
    )
    return {
        'id': 'seller-6',
        'title': '支付设置',
        'graduateTitle': '支付设置已观摩',
        'graduateSummary': '下一步：展示主页。',
        'microSteps': steps,
    }


def _seller_homepage() -> dict[str, Any]:
    return {
        'id': 'seller-7',
        'title': '展示主页',
        'graduateTitle': '通用开店体验完成',
        'graduateSummary': '通用大步已走完；若已开启插件，可选堂食/配送大步；购物请回主页点「体验野草购物」。',
        'microSteps': [
            _ms('preview_homepage', selector='[data-yc-tour="fold-home-settings"]', title='店铺主页总设置',
                open_fold='#home-page-settings',
                body='与服务器主页严格分开；这里只编辑本店门面。'),
            _ms('preview_homepage', selector='[data-yc-tour="home-auto-read"]', title='自动读取的资料',
                body='店名、营业状态、时间、地址不用重复填。'),
            _ms('preview_homepage', selector='[data-yc-tour="home-nav-mode-select"]', title='顶栏「下单」行为',
                body='直达下单页，或滚到「进入店铺」块。'),
            _ms('preview_homepage', selector='[data-yc-tour="home-preview-link"]', title='预览本店主页',
                body='新窗口看客人看到的店铺主页；不是下单加购页。',
                warn='勿与商品上架末尾的「预览店铺（下单页）」混淆。'),
            _ms('preview_homepage', selector='[data-yc-tour="fold-home-intro"]', title='简介积木',
                open_fold='#block-intro'),
            _ms('preview_homepage', selector='[data-yc-tour="fold-home-notice"]', title='公告积木',
                open_fold='#block-notice'),
            _ms('preview_homepage', selector='[data-yc-tour="fold-home-cta"]', title='进入店铺积木',
                open_fold='#block-order_cta'),
            _ms('preview_homepage', selector='[data-yc-tour="fold-home-custom"]', title='添加自定义积木',
                open_fold='#custom-blocks-toolbar', body='点「添加自定义积木」可新增一块自由编辑区域。'),
            _ms('preview_homepage', selector='[data-yc-tour="fold-home-custom-block"]', title='编辑第一块自定义积木',
                body='展开后可改标题与正文；体验模式不会真保存。'),
        ],
    }


def _seller_dine() -> dict[str, Any]:
    return {
        'id': 'seller-8',
        'title': '堂食营业',
        'graduateTitle': '堂食营业已观摩',
        'graduateSummary': '饮食插件相关设置已浏览；可选配送费规则或结束体验。',
        'microSteps': [
            _ms('preview_dine', selector='[data-yc-tour="fold-dine-rules"]', title='桌码主单硬规则',
                open_fold='#dine-rules', body='必读；每桌一份主单。'),
            _ms('preview_dine', selector='[data-yc-tour="fold-dining-settings"]', title='堂食接单细则',
                open_fold='#dining-settings'),
            _ms('preview_dine', selector='[data-yc-tour="dine-toggle"]', title='堂食 / 打包 / 外卖开关'),
            _ms('preview_dine', selector='[data-yc-tour="fold-lan-address"]', title='桌码局域网地址',
                open_fold='#lan-address-box'),
            _ms('preview_dine', selector='[data-yc-tour="fold-table-list"]', title='桌号列表',
                open_fold='#table-list'),
            _ms('preview_dine', selector='[data-yc-tour="fold-table-qr"]', title='批量生成桌贴',
                open_fold='#table-qr-export'),
        ],
    }


def _seller_delivery() -> dict[str, Any]:
    return {
        'id': 'seller-9',
        'title': '配送费规则',
        'graduateTitle': '卖家体验全部完成',
        'graduateSummary': '开店体验已全部走完；若要体验购物，请回主页点「体验野草购物」。',
        'microSteps': [
            _ms('preview_delivery', selector='[data-yc-tour="delivery-intro"]', title='配送费规则做什么',
                body='买家下单时自动计算配送费。'),
            _ms('preview_delivery', selector='[data-yc-tour="delivery-base"]', title='最远配送距离',
                body='超出此距离的订单无法配送。',
                demo_type='type', demo_text='5'),
            _ms('preview_delivery', selector='[data-yc-tour="delivery-fee"]', title='最低配送费',
                body='算出的配送费不会低于此金额。',
                demo_type='type', demo_text='3'),
            _ms('preview_delivery', selector='[data-yc-tour="delivery-free"]', title='满额免配'),
            _ms('preview_delivery', selector='[data-yc-tour="delivery-per-km"]', title='每公里加价'),
            _ms('preview_delivery', selector='[data-yc-tour="delivery-save"]', title='保存规则'),
            _ms('preview_delivery', selector='[data-yc-tour="delivery-workbench-hint"]', title='与工作台关系',
                body='配送员在店铺工作台操作；现金入金在支付设置。'),
        ],
    }
