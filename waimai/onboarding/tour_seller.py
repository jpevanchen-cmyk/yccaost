# 新版新手体验：卖家开店线（第 1～7 大步）

from __future__ import annotations

from typing import Any

from .demo_cleanup import DEMO_DISH_NAME, DEMO_MENU_PROFILE_NAME
from .tour_common import ms as _ms

# 第 5 大步 · 三分档演示描述（正本 docs/新手引导流程.md）
_DEMO_DESC_NORMAL = '普通价格所有用户都可以下单（包括未注册的游客帐户）'
_DEMO_DESC_MEMBER = '会员价格需要本店铺注册用户可以下单'
_DEMO_DESC_SPECIAL = '特价需要本店注册用户，并且每个用户有限购数量'

# 第 2 大步 · 营业状态：每小步固定折叠布局
_OPERATING_FOLD_LAYOUTS: dict[str, list[str]] = {
    'none': [],
    'form': ['status-form'],
}


def _operating_ms(fold_key: str, **kwargs) -> dict[str, Any]:
    """营业状态演示小步：同步 foldLayout"""
    layout = _OPERATING_FOLD_LAYOUTS.get(fold_key)
    if layout is None:
        raise ValueError(f'未知营业状态折叠布局: {fold_key}')
    kwargs.pop('open_fold', None)
    return _ms('preview_operating', fold_layout=layout, **kwargs)


# 第 3～6 大步 · 商品上架页：每小步固定折叠布局
_PRODUCTS_FOLD_LAYOUTS: dict[str, list[str]] = {
    'none': [],
    'sales': ['sales-ranking'],
    'menu': ['menu-panel'],
    'add': ['product-add'],
}


def _products_ms(fold_key: str, **kwargs) -> dict[str, Any]:
    """商品上架页演示小步：同步 foldLayout"""
    layout = _PRODUCTS_FOLD_LAYOUTS.get(fold_key)
    if layout is None:
        raise ValueError(f'未知商品页折叠布局: {fold_key}')
    kwargs.pop('open_fold', None)
    return _ms('preview_products', fold_layout=layout, **kwargs)


def _print_qr_ms(**kwargs) -> dict[str, Any]:
    """打印页无折叠区，固定全关"""
    kwargs.pop('open_fold', None)
    return _ms('preview_print_qr', fold_layout=[], **kwargs)


# 第 7 大步 · 员工工作台：每小步固定折叠布局
_WB_FOLD_LAYOUTS: dict[str, list[str]] = {
    'none': [],
    'qr': ['workbench-qr'],
    'settings': ['workbench-settings-form'],
    'attendance': ['workbench-attendance'],
    'mgmt': ['management-staff-create'],
    'emp': ['employee-staff-create'],
    'list': ['staff-account-list'],
}


def _wb_ms(fold_key: str, **kwargs) -> dict[str, Any]:
    """工作台演示小步：同步 foldLayout，避免上一步折叠区残留"""
    layout = _WB_FOLD_LAYOUTS.get(fold_key)
    if layout is None:
        raise ValueError(f'未知工作台折叠布局: {fold_key}')
    kwargs.pop('open_fold', None)
    return _ms('preview_workbench_manage', fold_layout=layout, **kwargs)


def seller_tour_majors(
    *,
    dining_enabled: bool = False,
    fulfillment_enabled: bool = False,
    seller_id: str = '',
) -> list[dict[str, Any]]:
    """v2 卖家体验大步"""
    from waimai.product_shell_helpers import build_product_shell

    shell = build_product_shell(seller_id) if seller_id else {}
    item = shell.get('item_word', '商品')
    catalog = shell.get('catalog_word', '菜单清单')
    catalog_title = (shell.get('catalog_panel_title') or catalog).lstrip('📋 ').strip()
    sales_title = shell.get('sales_title', '商品销量排行')
    dine_hint = '堂食/打包/外卖细分在「堂食营业」大步。' if dining_enabled else '细分通道可在启用相应插件后配置。'
    majors = [
        _seller_register(),
        _seller_operating(dine_hint),
        _seller_menu_catalog(
            item=item,
            catalog=catalog,
            catalog_title=catalog_title,
            sales_title=sales_title,
        ),
        _seller_print_qr(item=item, catalog=catalog),
        _seller_add_product(item=item),
        _seller_edit_product(item=item),
        _seller_workbench_manage(fulfillment_enabled=fulfillment_enabled),
    ]
    if dining_enabled:
        majors.append(_seller_dine())
    if fulfillment_enabled:
        majors.append(_seller_delivery())
    majors.append(_seller_payment(fulfillment_enabled=fulfillment_enabled))
    majors.append(_seller_orders())
    majors.append(_seller_homepage())
    return majors


def _seller_operating(dine_hint: str) -> dict[str, Any]:
    return {
        'id': 'seller-2',
        'title': '营业状态',
        'graduateTitle': '营业状态已观摩',
        'graduateSummary': '您已了解全天营业时间与营业中/停止开关；下一步体验菜单清单。',
        'microSteps': [
            _operating_ms('none', selector='[data-yc-tour="operating-intro"]', title='营业状态管什么',
                body='控制是否接单与全天营业时间；与细分通道分开。',
                tips=(dine_hint,)),
            _operating_ms('form', selector='[data-yc-tour="operating-form-head"]', title='展开「营业时间和状态设定」',
                body='点标题可展开或收起；本步起保持展开以便观摩各字段。'),
            _operating_ms('form', selector='[data-yc-tour="operating-open-time"]', title='开始营业时间',
                body='新订单须落在设定时间段内。', demo_type='type', demo_text='09:00'),
            _operating_ms('form', selector='[data-yc-tour="operating-close-time"]', title='结束营业时间',
                demo_type='type', demo_text='22:00'),
            _operating_ms('form', selector='[data-yc-tour="operating-save-hours"]', title='保存营业时间',
                body='改时间后须点保存；体验模式不会真保存。'),
            _operating_ms('form', selector='[data-yc-tour="operating-status-text"]', title='当前状态',
                body='一眼查看营业中或停止营业。'),
            _operating_ms('form', selector='[data-yc-tour="operating-toggle"]', title='营业中 / 停止营业',
                body='临时打烊用此按钮；不必改时间表。',
                warn='容易错：只改状态不改时间，夜间仍可能拒单。'),
            _operating_ms('none', selector='[data-yc-tour="operating-intro"]', title='与店铺主页同步',
                body='店铺主页上的营业状态会自动读取这里，不用重复填。'),
        ],
    }


def _seller_menu_catalog(
    *,
    item: str,
    catalog: str,
    catalog_title: str,
    sales_title: str,
) -> dict[str, Any]:
    """第 3 大步：菜单清单（1～7 沿用旧逻辑；8 起重写为可写演示）"""
    action_hint = '请在高亮处点击；若未操作，倒计时结束后将自动执行。'
    return {
        'id': 'seller-3',
        'title': catalog_title,
        'graduateTitle': f'{catalog_title}已体验',
        'graduateSummary': (
            f'您已走完{catalog}新建、切换、删除与清单内上下架/会员价/特价展示；'
            '下一步体验批量打印二维码。'
        ),
        'cleanupOnComplete': True,
        'microSteps': [
            _products_ms('sales', selector='[data-yc-tour="sales-ranking-head"]', title=f'卡片 1 · {sales_title}',
                body='看哪些卖得好；只统计已完成订单。'),
            _products_ms('sales', selector='[data-yc-tour="sales-rank-tabs"]', title='日 / 周 / 月排行',
                body='点标签切换；演示用固定假数据。'),
            _products_ms('sales', selector='[data-yc-tour="sales-rank-day"]', title='日排行',
                demo_click='.sales-rank-tab[data-panel="sales-day"]'),
            _products_ms('sales', selector='[data-yc-tour="sales-rank-week"]', title='周排行',
                demo_click='.sales-rank-tab[data-panel="sales-week"]'),
            _products_ms('sales', selector='[data-yc-tour="sales-rank-month"]', title='月排行',
                demo_click='.sales-rank-tab[data-panel="sales-month"]'),
            _products_ms('menu', selector='[data-yc-tour="menu-panel-head"]', title=f'卡片 2 · {catalog_title}',
                body=f'客人店铺页以「使用中」的{catalog}为准。'),
            _products_ms('menu', selector='[data-yc-tour="menu-intro"]', title=f'{catalog}做什么',
                tips=('切换前须无未结束订单。',)),
            _products_ms('menu', selector='[data-yc-tour="menu-profile-name"]', title=f'新建{catalog}名称',
                demo_type='type', demo_text=DEMO_MENU_PROFILE_NAME,
                body=f'本演示预设输入「{DEMO_MENU_PROFILE_NAME}」。'),
            _products_ms('menu', selector='[data-yc-tour="menu-copy-select"]', title='展开「复制自」',
                body='可选「全新」或复制已有清单；下面两步分别说明。'),
            _products_ms('menu', selector='[data-yc-tour="menu-copy-select"]', title='「全新（纳入全部商品）」',
                body=f'把所有已添加的{item}全部纳入新清单，展示设定从零配。'),
            _products_ms('menu', selector='[data-yc-tour="menu-copy-select"]', title='复制「通用清单」',
                body=(
                    '复制通用清单里的内容，含上下架、会员价/特价是否展示等设定，可节约时间；'
                    '本演示选此项。'
                ),
                demo_type='select', demo_text_key='demoCopyProfileId'),
            _products_ms('menu', selector='[data-yc-tour="menu-create-submit"]', title=f'创建「{DEMO_MENU_PROFILE_NAME}」',
                body='请在高亮处点「创建」真实建立；体验结束后系统会自动清理演示数据。' + action_hint,
                demo_type='action',
                warn='演示会写入官方演示店；退出或本步完成后会清理。'),
            _products_ms('menu', selector='[data-yc-tour="menu-active-state"]', title='当前使用中清单',
                body='上方应显示「通用清单」为使用中；若下拉框不在通用清单，请先切到通用清单再看下方详情。'),
            _products_ms('menu', selector='[data-yc-tour="menu-delete-btn"]', title='删除清单',
                body='使用中的清单不能删除；删除按钮应为灰色且无法点击。',
                warn='容易错：未先切换使用就删清单会失败。'),
            _products_ms('menu', selector='[data-yc-tour="menu-profile-select"]', title=f'选中「{DEMO_MENU_PROFILE_NAME}」',
                body='在下拉框选中演示清单；选好后下方显示该清单详情。' + action_hint,
                demo_type='select_name', demo_text=DEMO_MENU_PROFILE_NAME),
            _products_ms('menu', selector='[data-yc-tour="menu-activate-btn"]', title='切换使用',
                body='请点「切换使用」，把演示清单设为客人可见；切换后上方「当前使用中」应变。' + action_hint,
                demo_type='action'),
            _products_ms('menu', selector='[data-yc-tour="menu-active-state"]', title='确认已切换',
                body=f'应显示「{DEMO_MENU_PROFILE_NAME}」为使用中。'),
            _products_ms('menu', selector='[data-yc-tour="menu-profile-select"]', title='切回通用清单',
                body='在下拉框选回通用清单，准备把使用中清单改回去。' + action_hint,
                demo_type='select_name', demo_text='通用'),
            _products_ms('menu', selector='[data-yc-tour="menu-activate-btn"]', title='切换回通用清单',
                body='请点「切换使用」，让通用清单重新对客人生效。' + action_hint,
                demo_type='action'),
            _products_ms('menu', selector='[data-yc-tour="menu-profile-select"]', title=f'再选「{DEMO_MENU_PROFILE_NAME}」',
                body='选中演示清单后，可演示删除非使用中的清单。' + action_hint,
                demo_type='select_name', demo_text=DEMO_MENU_PROFILE_NAME),
            _products_ms('menu', selector='[data-yc-tour="menu-delete-btn"]', title='删除演示清单',
                body='请点「删除」真实删除演示清单；后续上下架演示在通用清单里进行。' + action_hint,
                demo_type='action',
                warn='删除后无法恢复；体验结束也会自动清理残留。'),
            _products_ms('menu', selector='[data-yc-tour="menu-item-listed-toggle"]', title='上架 → 下架',
                body=f'请点「上架中」，把该{item}在本清单改为下架；客人将看不到、不能下单。' + action_hint,
                demo_type='action'),
            _products_ms('menu', selector='[data-yc-tour="menu-item-listed-toggle"]', title='下架 → 上架',
                body='再点一次，恢复上架状态。' + action_hint,
                demo_type='action'),
            _products_ms('menu', selector='[data-yc-tour="menu-item-member-toggle"]', title='会员价展示 ↔ 不展示',
                body=f'须「商品管理」里已允许会员价，且本{catalog}勾选展示，客人才看得到会员价按钮。' + action_hint,
                demo_type='action',
                tips=(f'本演示{item}已预设允许会员价。',)),
            _products_ms('menu', selector='[data-yc-tour="menu-item-special-toggle"]', title='特价展示 ↔ 不展示',
                body=f'逻辑同会员价：商品允许 + 本{catalog}展示 + 已切换使用，客人才看得到特价。' + action_hint,
                demo_type='action',
                tips=(f'本演示{item}已预设允许特价。',)),
        ],
    }


def _seller_print_qr(*, item: str, catalog: str) -> dict[str, Any]:
    """第 4 大步：批量打印二维码（只观摩）"""
    return {
        'id': 'seller-4',
        'title': '批量打印二维码',
        'graduateTitle': '批量打印已观摩',
        'graduateSummary': (
            f'您已了解如何从{catalog}进入打印页、各档位二维码含义；'
            f'下一步体验添加新{item}。'
        ),
        'microSteps': [
            _products_ms('menu', selector='[data-yc-tour="menu-print-qr-link"]', title='批量打印入口',
                body='请点蓝色链接「批量打印本清单商品二维码」进入打印页；贴货架供顾客扫码加购（须登录买家）。'),
            _print_qr_ms(selector='[data-yc-tour="print-qr-intro"]', title='打印页说明',
                body='以下为使用中清单内、已上架且可扫码的商品；每个可用档位各一张码。'),
            _print_qr_ms(selector='[data-yc-tour="print-qr-g18-hint"]', title='预告 · 收银结账码',
                body='「扫货后至收银台出示结账码统一算账」见手册 G1-8，尚未上线。',
                tips=('当前 G1-6/7 已支持扫商品码加购。',)),
            _print_qr_ms(selector='[data-yc-tour="print-qr-btn"]', title='打印本页',
                body='本步只观摩；正式店可点「打印本页」用浏览器打印贴货架。'),
        ],
    }


def _seller_add_product(*, item: str) -> dict[str, Any]:
    """第 5 大步：添加新商品（可写演示 · 正本 docs/新手引导流程.md）"""
    action_hint = '请在高亮处点击；若未操作，倒计时结束后将自动执行。'
    return {
        'id': 'seller-5',
        'title': f'添加新{item}',
        'graduateTitle': f'添加{item}已体验',
        'graduateSummary': (
            f'您已真实添加「{DEMO_DISH_NAME}」；下一步学习编辑该商品并预览店铺。'
        ),
        'microSteps': [
            _products_ms('add', selector='[data-yc-tour="add-name"]', title=f'{item}名称',
                demo_type='type', demo_text=DEMO_DISH_NAME,
                body=f'演示输入「{DEMO_DISH_NAME}」。'),
            _products_ms('add', selector='[data-yc-tour="add-price"]', title='通用价格',
                demo_type='type', demo_text='99',
                body='演示输入价格，例如 99 元。'),
            _products_ms('add', selector='[data-yc-tour="add-sort"]', title='排序',
                body=(
                    '0 = 不排序，按商品添加顺序排列；'
                    '1 = 商品置顶；数字越大，位置越靠后。'
                )),
            _products_ms('add', selector='[data-yc-tour="add-desc-block"]', title='普通 / 会员 / 特价描述',
                demo_type='type_multi',
                demo_fields=[
                    {'selector': '[data-yc-tour="add-desc-normal"] textarea', 'text': _DEMO_DESC_NORMAL},
                    {'selector': '[data-yc-tour="add-desc-member"] textarea', 'text': _DEMO_DESC_MEMBER},
                    {'selector': '[data-yc-tour="add-desc-special"] textarea', 'text': _DEMO_DESC_SPECIAL},
                ],
                body='此处为示例，各价格档位，可以分别设置不同描述。'),
            _products_ms('add', selector='[data-yc-tour="add-member-enable"]', title='启用会员价',
                demo_type='check', demo_checked=True,
                body='勾选后下方会员价选项才会展开。'),
            _products_ms('add', selector='[data-yc-tour="add-member-limits"]', title='单日限购 + 累计限购',
                body=(
                    '单日限购会每日重置；'
                    '累计限购设定后，顾客购买到达上限后不能再购买本商品的会员价。'
                ),
                warn='容易错：两种限购含义不同，请按需填写或留空表示不限。'),
            _products_ms('add', selector='[data-yc-tour="add-special-enable"]', title='启用特价',
                demo_type='check', demo_checked=True,
                body='勾选后下方特价选项才会展开。'),
            _products_ms('add', selector='[data-yc-tour="add-special-limit"]', title='本特价商品每人限购',
                body='顾客购买到达上限后，不能再购买本商品的特价。',
                tips=('演示可保持默认 1。',)),
            _products_ms('add', selector='[data-yc-tour="add-image"]', title='添加商品图片',
                body='此处可以选择商品图片。'),
            _products_ms('add', selector='[data-yc-tour="add-list-all"]', title='添加后全部清单上架',
                body=(
                    '勾选后添加成功会立即展示在店铺'
                    '（注意，勾选后，添加成功，顾客就马上可以下单，若未准备好销售的商品，切勿勾选）'
                )),
            _products_ms('add', selector='[data-yc-tour="add-submit"]', title=f'添加{item}',
                body='请点「添加商品」真实建立；第 6 大步结束或体验退出时自动清理。' + action_hint,
                demo_type='action',
                warn='演示会写入官方演示店。'),
            _products_ms('none', selector='[data-yc-tour="demo-s5-step12-shot"]', title=f'已添加「{DEMO_DISH_NAME}」',
                body='添加商品后，可以进入商品管理进行编辑管理'),
        ],
    }


def _seller_edit_product(*, item: str) -> dict[str, Any]:
    """第 6 大步：编辑商品 + 预览店铺（观摩；假 UI 外观与真 UI 一致）"""
    return {
        'id': 'seller-6',
        'title': f'编辑{item}',
        'graduateTitle': f'编辑{item}已体验',
        'graduateSummary': (
            '您已了解编辑商品与预览店铺；下一步学习员工工作台管理。'
        ),
        'cleanupOnComplete': True,
        'microSteps': [
            _products_ms('none', selector='[data-yc-tour="demo-s6-shot-1"]',
                title=f'「{DEMO_DISH_NAME}」基本资料',
                body='这里可以确认商品的基本资料，详情在下方，可以在体验后自行查看。'),
            _products_ms('none', selector='[data-yc-tour="demo-s6-shot-2"]',
                title='分档扫码加购二维码',
                body=(
                    '此处自动生成二维码，适合货架商品，顾客可以直接扫码取货，'
                    '直接到收银处出示订单码结算，或者自行结算（功能规划中，近期会更新）'
                )),
            _products_ms('none', selector='[data-yc-tour="demo-s6-shot-3"]',
                title='添加商品图片',
                body='这里可以上传添加新图片'),
            _products_ms('none', selector='[data-yc-tour="demo-s6-shot-4"]',
                title='已上传图片管理',
                body=(
                    '点上下箭头可以更改图片显示位置，点删可以删除不需要的图片，'
                    '点同步/刷新商品图片才会同步到服务器（注意，由于浏览器缓存的关系，'
                    '可能造成更改不成功的假象，可以按Ctrl+F5强制刷新浏览器查看）'
                )),
            _products_ms('none', selector='[data-yc-tour="demo-s6-shot-5"]',
                title='预览店铺',
                body='点此处可以预览您的店铺'),
            _products_ms('none', selector='[data-yc-tour="demo-s6-shot-6"]',
                title='店铺预览',
                body='恭喜你成功装修好了自己的店铺'),
        ],
    }


def _seller_workbench_manage(*, fulfillment_enabled: bool) -> dict[str, Any]:
    """第 7 大步：员工工作台 · 管理（只观摩）"""
    plugin_tips = []
    if fulfillment_enabled:
        plugin_tips.append('本演示店已开启履约插件，可看到外卖交接与自动派单选项。')
    else:
        plugin_tips.append('未开启履约插件时，外卖交接与自动派单不会显示。')
    steps: list[dict[str, Any]] = [
        _wb_ms('none', selector='[data-yc-tour="workbench-intro"]', title='本页管什么',
            body='员工登录二维码、协作设置、考勤与子账号权限，都在这一页维护。',
            tips=tuple(plugin_tips) + ('员工不用野草主页「登录」。',)),
        _wb_ms('qr', selector='[data-yc-tour="fold-workbench-qr"]', title='工作台登录二维码',
            body='贴在员工方便扫码的位置；扫码后输入名字和密码开始上班。'),
        _wb_ms('qr', selector='[data-yc-tour="workbench-qr-body"]', title='链接与二维码',
            body='上面是链接，下面是二维码；员工扫此码上班，不要用野草生态登录页。'),
        _wb_ms('qr', selector='[data-yc-tour="workbench-qr-link"]', title='点开链接看一看',
            body='可点开链接，在新标签页预览工作台登录页长什么样；本步只观摩，不必真登录。',
            demo_click='[data-yc-tour="workbench-qr-link"]'),
        _wb_ms('settings', selector='[data-yc-tour="workbench-settings-head"]', title='协作设置',
            body='配送交接、新单提醒、考勤保留时长等，都在这里配置。'),
    ]
    if fulfillment_enabled:
        steps.extend([
            _wb_ms('settings', selector='[data-yc-tour="workbench-delivery-handoff"]', title='外卖交接方式',
                body='外卖备好后由谁交给骑手：默认服务员交接；也可选后厨直交骑手。'),
            _wb_ms('settings', selector='[data-yc-tour="workbench-auto-dispatch"]', title='开启自动派单',
                body='开启后，有可派单订单时会自动分给当前上班的本店骑手；关闭则需人工派单。'),
        ])
    steps.extend([
        _wb_ms('settings', selector='[data-yc-tour="workbench-attendance-retention"]', title='考勤记录保留时长',
            body='超过保留期的旧考勤记录可后续清理；当前先按这个规则展示与导出。'),
        _wb_ms('settings', selector='[data-yc-tour="workbench-alert-volume"]', title='新单提醒音量',
            demo_type='type', demo_text='80',
            body='工作台/后厨页面开着时，新单提醒响铃的音量；演示预设 80。'),
        _wb_ms('settings', selector='[data-yc-tour="workbench-alert-interval"]', title='提醒重复间隔',
            body='有新单未处理时，每隔多少秒再响一次（最少 3 秒）。'),
        _wb_ms('settings', selector='[data-yc-tour="workbench-alert-sound"]', title='自定义提醒音频',
            body='可上传自己的提示音；留空则用系统默认提示音。'),
        _wb_ms('settings', selector='[data-yc-tour="workbench-settings-save"]', title='保存协作设置',
            body='改完后须点保存；体验模式不会真保存。'),
        _wb_ms('attendance', selector='[data-yc-tour="workbench-attendance-head"]', title='员工状态与考勤',
            body=(
                '可看当前状态、今日上班情况与最近考勤流水；老板也可在此兜底补改。'
                '考勤流水默认只显示今天；需要查更早记录可筛选，或正式店点「打开全部考勤」。'
            )),
        _wb_ms('attendance', selector='[data-yc-tour="attendance-filter"]', title='筛选考勤',
            body='可按开始/结束日期、职务、名字筛选；演示默认已填今天。'),
        _wb_ms('attendance', selector='[data-yc-tour="attendance-status-table"]', title='员工状态表',
            body='一行一名员工：当前上班/休息/下班、今日首次上班、今日最后状态；右侧可老板补改。'),
        _wb_ms('attendance', selector='[data-yc-tour="attendance-export"]', title='导出考勤 CSV',
            body='按当前筛选条件导出表格，方便存档或对账。'),
        _wb_ms('attendance', selector='[data-yc-tour="attendance-manager-form"]', title='老板补改',
            body='上班/下班须填一个时间点；休息须填开始与结束两个时间；体验不真提交。',
            warn='容易错：补改休息只填一个时间不够，须填开始+结束。'),
        _wb_ms('attendance', selector='[data-yc-tour="attendance-demo-log-table"]', title='演示员工考勤流水',
            body='下方表格为「演示员工」今日 5 条示意流水，便于对照上方状态表理解。',
            tips=('均为演示示意数据，只供观摩。',)),
        _wb_ms('attendance', selector='[data-yc-tour="attendance-log-stream"]', title='最近考勤流水',
            body=(
                '按时间倒序显示；默认只看今天。'
                '正式店可点「打开全部考勤」在新窗口查看全部历史；体验页仅说明，按钮在正式店才出现。'
            )),
        _wb_ms('attendance', selector='[data-yc-tour="attendance-log-pagination"]', title='流水分页',
            body='可切换每页 10 / 15 / 20 条。'),
        _wb_ms('mgmt', selector='[data-yc-tour="mgmt-staff-head"]', title='新建管理职务',
            body=(
                '「店长、经理、大堂经理」都属于管理职务；职务名称由您填写，'
                '能做什么以勾选权限为准，不再由“店长”二字自动决定。'
            )),
        _wb_ms('mgmt', selector='[data-yc-tour="mgmt-staff-username"]', title='员工登录名',
            demo_type='type', demo_text='小张',
            body='员工用此名和密码在工作台登录页上班。'),
        _wb_ms('mgmt', selector='[data-yc-tour="mgmt-staff-password"]', title='设置密码',
            body='须告知员工；公共设备请勿勾选「记住密码」。'),
        _wb_ms('mgmt', selector='[data-yc-tour="mgmt-staff-job-title"]', title='职务名称',
            demo_type='type', demo_text='值班经理'),
        _wb_ms('mgmt', selector='[data-yc-tour="mgmt-staff-permissions"]', title='勾选权限',
            body='勾什么就能做什么；不勾则看不到对应功能。',
            tips=('例如：只勾「仅看订单」= 只能看不能改。',)),
        _wb_ms('mgmt', selector='[data-yc-tour="mgmt-staff-submit"]', title='创建管理职务',
            body='体验不真提交；正式店点绿色按钮保存。'),
        _wb_ms('emp', selector='[data-yc-tour="emp-staff-head"]', title='新建普通员工',
            body='普通员工职务名与权限可自行填写；插件可提供常用模板。'),
        _wb_ms('emp', selector='[data-yc-tour="emp-staff-preset"]', title='预置模板（可选）',
            body='饮食/履约插件开启后，会出现服务员、后厨、配送员等模板；也可不套模板自己填。',
            tips=tuple(
                ['本演示店若已开插件，下拉框里会有对应模板。']
                if fulfillment_enabled
                else ['未开插件时也可不选模板，自己填职务名与权限。']
            )),
        _wb_ms('emp', selector='[data-yc-tour="emp-staff-job-title"]', title='普通员工职务名',
            demo_type='type', demo_text='收银员'),
        _wb_ms('emp', selector='[data-yc-tour="emp-staff-username"]', title='普通员工登录名',
            demo_type='type', demo_text='小李'),
        _wb_ms('emp', selector='[data-yc-tour="emp-staff-permissions"]', title='普通员工权限',
            body='通常比管理职务少；例如一般不给「取消订单」。'),
        _wb_ms('emp', selector='[data-yc-tour="emp-staff-submit"]', title='创建普通员工',
            body='体验不真提交。'),
        _wb_ms('list', selector='[data-yc-tour="staff-list-head"]', title='子账号列表',
            body='这里统一维护账号类别、职务名称与权限；停用插件不会删账号。'),
        _wb_ms('list', selector='[data-yc-tour="staff-account-row"]', title='展开已有账号',
            body='点一行可展开，修改职务名与权限；演示已展开「演示经理」。'),
        _wb_ms('list', selector='[data-yc-tour="staff-edit-permissions"]', title='修改权限',
            body='勾选「允许做什么」决定员工能看哪些 Tab；员工下次登录即按新权限显示。',
            tips=('本步只框权限勾选区，不含保存按钮。',)),
        _wb_ms('list', selector='[data-yc-tour="staff-edit-save"]', title='保存修改',
            body='体验不真提交。'),
        _wb_ms('list', selector='[data-yc-tour="staff-toggle-active"]', title='停用 / 启用账号',
            warn='离职或暂不用时可停用，不必删账号。'),
        _wb_ms('list', selector='[data-yc-tour="fold-staff-list"]', title='本大步结束',
            body='员工工作台管理已观摩完毕；下一步学习堂食营业。'),
    ])
    return {
        'id': 'seller-7',
        'title': '员工工作台 · 管理',
        'graduateTitle': '工作台管理已观摩',
        'graduateSummary': '您已了解员工登录、协作设置、考勤与子账号；后续大步待上线。',
        'microSteps': steps,
    }


# 第 8 大步 · 堂食营业：每小步固定折叠布局
_DINE_FOLD_LAYOUTS: dict[str, list[str]] = {
    'none': [],
    'rules': ['dine-rules'],
    'settings': ['dining-settings'],
    'tables': ['table-list'],
    'virtual': ['virtual-list'],
}


def _dine_ms(fold_key: str, **kwargs) -> dict[str, Any]:
    """堂食营业演示小步：同步 foldLayout"""
    layout = _DINE_FOLD_LAYOUTS.get(fold_key)
    if layout is None:
        raise ValueError(f'未知堂食折叠布局: {fold_key}')
    kwargs.pop('open_fold', None)
    return _ms('preview_dine', fold_layout=layout, **kwargs)


def _dine_sticker_ms(**kwargs) -> dict[str, Any]:
    """桌贴预览页小步"""
    kwargs.pop('open_fold', None)
    return _ms('preview_table_stickers', fold_layout=[], **kwargs)


def _seller_dine() -> dict[str, Any]:
    """第 8 大步：堂食营业（接单细则观摩 + 桌台可写演示）"""
    action_hint = '请在高亮处点击；若未操作，倒计时结束后将自动执行。'
    return {
        'id': 'seller-8',
        'title': '堂食营业',
        'graduateTitle': '堂食营业已体验',
        'graduateSummary': '您已了解堂食硬规则、接单细则、实体桌码与虚拟桌码池；下一步可学配送费规则（须启用履约插件）。',
        'cleanupOnComplete': True,
        'microSteps': [
            _dine_ms('none', selector='[data-yc-tour="nav-dine"]', title='进入「堂食营业」',
                body='点顶部菜单进入堂食设置页；饮食插件开启后才有此入口。'),
            _dine_ms('rules', selector='[data-yc-tour="dine-rules-head"]', title='展开「桌码主单硬规则」',
                body='做堂食营业必看，切勿偷懒！先展开这张卡片阅读规则。'),
            _dine_ms('rules', selector='[data-yc-tour="dine-rules-content"]', title='桌码主单硬规则',
                body='做堂食营业必看，切勿偷懒！每桌一份主单、可多次加点；须营业中且堂食通道开启才能开单。',
                warn='容易错：不看规则就营业，客人扫桌码可能无法下单。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-settings-head"]', title='展开「堂食接单细则与拼桌」',
                body='堂食/打包/外卖是否接单、等待时间、拼桌与桌码局域网，都在这里设置；点标题展开。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-channel"]', title='允许堂食接单',
                body='控制客人能否扫实体桌码在现场点餐。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-takeaway"]', title='允许打包接单',
                body='控制客人能否选「打包」通道下单。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-delivery"]', title='允许外卖接单',
                body='控制客人能否选「外卖」通道下单。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-hours"]', title='堂食接单时段',
                body='堂食与打包共用此时段；留空表示不额外限制（仍受「营业状态」全天时间约束）。'),
            _dine_ms('settings', selector='[data-yc-tour="delivery-hours"]', title='外卖接单时段',
                body='只限制外卖通道；与堂食时段分开配置。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-wait-default"]', title='堂食默认等待时间',
                body='没有匹配到下方「分时段规则」时使用。'),
            _dine_ms('settings', selector='[data-yc-tour="takeaway-wait-default"]', title='打包默认等待时间',
                body='逻辑同堂食；无匹配分时段时用此值。'),
            _dine_ms('settings', selector='[data-yc-tour="delivery-wait-default"]', title='外卖默认等待时间',
                body='逻辑同堂食；无匹配分时段时用此值。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-share-enable"]', title='开启拼桌功能',
                body='同一物理桌有多批客人须分开买单时才需要开启。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-share-mode"]', title='拼桌模式 · 模式 A',
                body='模式 A · 服务员拼桌单：第二位及以后客人须由服务员开单，客人不能自助扫码开拼桌单。',
                demo_type='select', demo_text='waiter'),
            _dine_ms('settings', selector='[data-yc-tour="dine-share-mode"]', title='拼桌模式 · 模式 B',
                body='模式 B · 虚拟桌码自助拼桌：把空闲虚拟码交给客人扫码，客人可自助开拼桌单；结账后码可复用。',
                demo_type='select', demo_text='virtual'),
            _dine_ms('settings', selector='[data-yc-tour="dine-share-mode"]', title='A 与 B 的主要区别',
                body='A 靠服务员全程操作，适合管得严的店；B 靠虚拟码池，客人可自助，但须先配好虚拟码。本演示预设为模式 B。',
                tips=('上方硬规则卡片会随所选模式显示 2A 或 2B。',)),
            _dine_ms('settings', selector='[data-yc-tour="dine-restrict-device"]', title='同桌仅允许同一台手机',
                body='防止有居心不良者，偷偷刷码，乱给其它人点单！'),
            _dine_ms('settings', selector='[data-yc-tour="fold-lan-address"]', title='桌码局域网固定地址',
                body=(
                    '难点：桌贴二维码须填客人连上店内 WiFi 后能打开的地址；'
                    '填错或填成宽带公网 IP，客人扫了打不开。推荐用四段数字，例 192 168 3 120。'
                ),
                warn='容易错：勿填宽带公网 IP；桌贴会印「先连店内访客 WiFi → 再扫此码点餐」。'),
            _dine_ms('settings', selector='[data-yc-tour="dine-wait-time-rules"]', title='按时间段自动调整等待时间（可选）',
                body=(
                    '难点：可按「堂食/打包/外卖 + 下单时段」自动给出预计等待分钟数；'
                    '没有匹配行时才用上面的普通默认时间。服务员和后厨仍可临时改单个订单。'
                ),
                tips=('同一种订单类型的时间段不能重叠。',)),
            _dine_ms('settings', selector='[data-yc-tour="dine-save-btn"]', title='保存堂食设置',
                body='改完后须点保存；体验模式不会真保存。'),
            _dine_ms('tables', selector='[data-yc-tour="table-list-head"]', title='展开「实体桌台与桌码」',
                body='在这里批量建桌号、停用/启用、删除，以及导出桌贴。'),
            _dine_ms('tables', selector='[data-yc-tour="table-min-max"]', title='最小桌号 / 最大桌号',
                demo_type='type_multi',
                demo_fields=[
                    {'selector': '[data-yc-tour="table-min"] input', 'text': '1'},
                    {'selector': '[data-yc-tour="table-max"] input', 'text': '10'},
                ],
                body='演示输入 1 和 10，可一次建好 1～10 号桌。'),
            _dine_ms('tables', selector='[data-yc-tour="table-batch-add"]', title='批量添加桌台',
                body='请点「批量添加桌台」真实建立；体验结束后系统会自动清理。' + action_hint,
                demo_type='action',
                warn='演示会写入官方演示店。'),
            _dine_ms('tables', selector='[data-yc-tour="table-chip-1"]', title='点选 1 号桌',
                demo_chip_labels=['1'],
                body='先点选桌号，再用下方按钮批量操作。'),
            _dine_ms('tables', selector='[data-yc-tour="table-batch-disable"]', title='停用 1 号桌',
                demo_chip_labels=['1'],
                body='演示停用；停用后客人扫该桌码无法开新主单。' + action_hint,
                demo_type='action'),
            _dine_ms('tables', selector='[data-yc-tour="table-batch-enable"]', title='再启用 1 号桌',
                demo_chip_labels=['1'],
                body='恢复启用后，客人又可扫该桌码开单。' + action_hint,
                demo_type='action'),
            _dine_ms('tables', selector='[data-yc-tour="table-chip-10"]', title='点选 10 号桌',
                demo_chip_labels=['10'],
                body='单独选中 10 号桌，演示删除。'),
            _dine_ms('tables', selector='[data-yc-tour="table-batch-delete"]', title='删除 10 号桌',
                body='删除须二次确认；体验模式会自动确认。' + action_hint,
                demo_type='action',
                warn='删除后不可恢复；体验结束也会自动清理。'),
            _dine_ms('tables', selector='[data-yc-tour="table-chip-grid"]', title='点选 1～5 号桌',
                demo_chip_labels=['1', '2', '3', '4', '5'],
                body='可一次选多张桌，用于批量导出桌贴 PDF。'),
            _dine_ms('tables', selector='[data-yc-tour="table-batch-export"]', title='导出桌贴 PDF',
                body='请点「导出桌贴 PDF」；体验模式会打开网页预览（正式店为下载 PDF）。' + action_hint,
                demo_type='action'),
            _dine_sticker_ms(selector='[data-yc-tour="table-sticker-grid"]', title='桌贴预览',
                body='打印出来剪下来，贴在桌子上，就可以让客人扫码点单了！',
                tips=('每页正式 PDF 可排 12 张；此处为演示所选 5 张。',)),
            _dine_ms('virtual', selector='[data-yc-tour="virtual-list-head"]', title='展开「虚拟桌码池」',
                body='除了虚拟桌码编号和实体桌码不一样，其余操作方法完全相同。',
                path='/experience/preview/seller/dine/'),
            _dine_ms('virtual', selector='[data-yc-tour="virtual-list-intro"]', title='虚拟桌码池说明',
                body='虚拟码以 V 开头；须先开启拼桌模式 B 才显示本卡片。体验预设已开启模式 B。',
                tips=('批量添加、停用、导出 PDF 与实体桌台操作相同。',)),
            _dine_ms('none', selector='[data-yc-tour="fold-virtual-list"]', title='堂食营业体验结束',
                body='堂食营业大步已走完；下一步可学习配送费规则（须启用履约插件）；工作台实操等后续上线。'),
        ],
    }


def _delivery_ms(**kwargs) -> dict[str, Any]:
    """配送费规则演示小步（只观摩，无折叠卡片）"""
    kwargs.pop('open_fold', None)
    return _ms('preview_delivery', fold_layout=[], **kwargs)


def _seller_delivery() -> dict[str, Any]:
    """第 10 大步：配送费规则（只观摩；依赖履约插件）"""
    return {
        'id': 'seller-10',
        'title': '配送费规则',
        'graduateTitle': '配送费规则已观摩',
        'graduateSummary': '您已了解配送费各字段含义；下一步观摩支付设置。',
        'microSteps': [
            _delivery_ms(selector='[data-yc-tour="nav-delivery"]', title='进入「配送费规则」',
                body='点顶部菜单进入；须启用履约配送插件才有此入口。'),
            _delivery_ms(selector='[data-yc-tour="delivery-intro"]', title='配送费规则做什么',
                body='买家下单时按此处规则自动计算配送费。'),
            _delivery_ms(selector='[data-yc-tour="delivery-fee"]', title='最低配送费（元）',
                body='算出的配送费不会低于此金额。',
                demo_type='type', demo_text='3'),
            _delivery_ms(selector='[data-yc-tour="delivery-per-km"]', title='3公里内单价（元/公里）',
                body='配送距离在 3 公里以内时，按此单价乘以公里数计费。',
                demo_type='type', demo_text='2'),
            _delivery_ms(selector='[data-yc-tour="delivery-multiplier-3-6"]', title='3～6公里倍数',
                body='距离在 3～6 公里段时，在 3 公里内单价基础上乘以该倍数。',
                demo_type='type', demo_text='1.5'),
            _delivery_ms(selector='[data-yc-tour="delivery-multiplier-6-9"]', title='6～9公里倍数',
                body='距离在 6～9 公里段时，继续按倍数加价。',
                demo_type='type', demo_text='2'),
            _delivery_ms(selector='[data-yc-tour="delivery-base"]', title='最远配送距离（公里）',
                body='超出此距离的订单无法配送。',
                demo_type='type', demo_text='5'),
            _delivery_ms(selector='[data-yc-tour="delivery-free"]', title='满额免运门槛（元）',
                body='商品金额达到此门槛时配送费为零；可留空表示不设免配。'),
            _delivery_ms(selector='[data-yc-tour="delivery-discount"]', title='按订单金额减免上限（%）',
                body='在最低配送费之上，还可按商品金额百分比再减免一部分配送费。'),
            _delivery_ms(selector='[data-yc-tour="delivery-save"]', title='保存配送费规则',
                body='改完后须点保存；体验模式不会真保存。'),
            _delivery_ms(selector='[data-yc-tour="delivery-workbench-hint"]', title='与工作台关系',
                body='配送员取货送达在「店铺工作台 · 配送员」；现金入金在「支付设置」。'),
            _delivery_ms(selector='[data-yc-tour="delivery-intro"]', title='配送费规则体验结束',
                body='本大步已走完；下一步观摩支付设置。'),
        ],
    }


def _payment_ms(**kwargs) -> dict[str, Any]:
    """支付设置演示小步（只观摩，无折叠卡片）"""
    kwargs.pop('open_fold', None)
    return _ms('preview_payment', fold_layout=[], **kwargs)


def _seller_payment(*, fulfillment_enabled: bool) -> dict[str, Any]:
    """第 11 大步：支付设置（只观摩；不依赖插件，配送员入金小步依赖履约插件）"""
    steps: list[dict[str, Any]] = [
        _payment_ms(selector='[data-yc-tour="nav-payment"]', title='进入「支付设置」',
            body='点顶部菜单进入本页。'),
        _payment_ms(selector='[data-yc-tour="payment-settings-box"]', title='支付设置管什么',
            body='各支付方式可单独开关，互不影响。'),
        _payment_ms(selector='[data-yc-tour="payment-intro"]', title='怎么用本页',
            body='先决定开哪些支付方式，再按需填写微信商户资料。'),
        _payment_ms(selector='[data-yc-tour="payment-experience-hint"]', title='体验店说明',
            body='体验店不能开真微信；请用「演示支付」走完整流程。',
            warn='若需要测试真实支付，请到野草官方小店购买0.01元测试专用商品。'),
        _payment_ms(selector='[data-yc-tour="payment-demo"]', title='开启模拟支付',
            body='演示用，不扣真钱；正式营业请关闭。',
            tips=('可与真微信同时开着做对比测试；上线前务必关掉。',)),
        _payment_ms(selector='[data-yc-tour="payment-wechat"]', title='开启微信支付',
            body='顾客扫码真付款；须填写下方微信商户信息。',
            warn='体验店无法开通真微信。'),
        _payment_ms(selector='[data-yc-tour="payment-cash"]', title='开启现金支付',
            body='到店付、堂食等场景可用。'),
    ]
    if fulfillment_enabled:
        steps.append(
            _payment_ms(selector='[data-yc-tour="payment-cod"]', title='外卖现金货到付款',
                body='外卖可选「送达时付现金」；关闭则外卖不显示现金。'),
        )
    steps.extend([
        _payment_ms(selector='[data-yc-tour="payment-cashier"]', title='启用实体收银台',
            body='开启后，工作台多一个「收银台」页，现场收当天待付单。'),
        _payment_ms(selector='[data-yc-tour="payment-cashier-page-size"]', title='收银台每页条数',
            body='只影响工作台收银台列表分页，与订单管理无关。'),
        _payment_ms(selector='[data-yc-tour="payment-wechat-mch-id"]', title='微信商户号',
            body='在微信商户平台申请后填写。'),
        _payment_ms(selector='[data-yc-tour="payment-wechat-app-id"]', title='微信 AppID',
            body='与商户号配套，用于对接微信支付。'),
        _payment_ms(selector='[data-yc-tour="payment-wechat-api-key"]', title='微信 APIv2 密钥',
            body='商户平台里设置，系统用来验签、查单。'),
        _payment_ms(selector='[data-yc-tour="payment-public-site-url"]', title='店铺公网网址',
            body='填好后才能用微信自动通知；没公网时可留空，靠轮询查单。'),
        _payment_ms(selector='[data-yc-tour="payment-notify-url"]', title='微信异步通知地址',
            body='填好公网网址后自动生成；复制到微信商户后台即可。'),
        _payment_ms(selector='[data-yc-tour="payment-save"]', title='保存支付设置',
            body='改完后须点保存；体验模式不会真保存。'),
    ])
    if fulfillment_enabled:
        steps.append(
            _payment_ms(selector='[data-yc-tour="rider-cash-box"]', title='配送员现金入金',
                body='配送员在工作台申请交款；店主在这里核对后确认入金。'),
        )
    steps.append(
        _payment_ms(selector='[data-yc-tour="payment-settings-box"]', title='支付设置体验结束',
            body='本大步已走完；下一步观摩订单管理。'),
    )
    return {
        'id': 'seller-11',
        'title': '支付设置',
        'graduateTitle': '支付设置已观摩',
        'graduateSummary': '您已了解各支付方式开关与微信配置；下一步观摩订单管理。',
        'microSteps': steps,
    }


# 第 12 大步 · 订单管理：折叠布局（老板邮件通知区）
_ORDERS_FOLD_LAYOUTS: dict[str, list[str]] = {
    'none': [],
    'boss': ['boss-order-notify'],
}


def _orders_ms(fold_key: str = 'none', *, page: str = 'preview_orders', **kwargs) -> dict[str, Any]:
    """订单管理演示小步（列表 + 详情页）"""
    layout = _ORDERS_FOLD_LAYOUTS.get(fold_key)
    if layout is None:
        raise ValueError(f'未知订单页折叠布局: {fold_key}')
    kwargs.pop('open_fold', None)
    return _ms(page, fold_layout=layout, **kwargs)


def _order_detail_ms(**kwargs) -> dict[str, Any]:
    """订单详情演示小步"""
    kwargs.pop('open_fold', None)
    return _ms('preview_order_detail', fold_layout=[], **kwargs)


def _seller_orders() -> dict[str, Any]:
    """第 12 大步：订单管理（只观摩；列表 + 详情）"""
    steps: list[dict[str, Any]] = [
        _orders_ms('none', selector='[data-yc-tour="nav-orders"]', title='进入「订单管理」',
            body='点顶部菜单进入本页。'),
        _orders_ms('boss', selector='[data-yc-tour="fold-boss-notify"]', title='老板邮件通知',
            body='店主不在工作台时的新单邮件；与 SMTP/值班邮件分开配置。'),
        _orders_ms('boss', selector='[data-yc-tour="boss-notify-save"]', title='保存老板通知',
            body='填写收件邮箱后点保存；体验模式不会真保存。'),
        _orders_ms('none', selector='[data-yc-tour="orders-intro"]', title='本页定位',
            body='查单、核对历史订单；备货收款等现场操作请到店铺工作台。'),
        _orders_ms('none', selector='[data-yc-tour="orders-search-q"]', title='搜索',
            demo_type='type', demo_text='YC-DEMO',
            body='可搜订单号、买家名或备注关键词。'),
        _orders_ms('none', selector='[data-yc-tour="orders-filters"]', title='筛选条件',
            body='可按订单状态、支付、履约方式、时间范围组合筛选。'),
        _orders_ms('none', selector='[data-yc-tour="orders-filter-status"]', title='订单状态',
            body='例如：只看「已完成」或「待处理」。'),
        _orders_ms('none', selector='[data-yc-tour="orders-filter-pay"]', title='支付状态',
            body='区分已支付、待支付、未收款等。'),
        _orders_ms('none', selector='[data-yc-tour="orders-filter-fulfillment"]', title='履约方式',
            body='打包、堂食、配送等按店型显示。'),
        _orders_ms('none', selector='[data-yc-tour="orders-search-hint"]', title='默认范围',
            body='默认近 1 个月；列表分页展示，每页 10 / 15 / 20 条可选；关键词也匹配买家备注。'),
        _orders_ms('none', selector='[data-yc-tour="orders-pagination"]', title='分页与每页条数',
            body='订单多时可翻页；可切换每页显示条数。'),
        _orders_ms('none', selector='[data-yc-tour="orders-sample-row"]', title='订单卡片',
            body='两行紧凑布局：订单号与状态标签、金额与详情入口。'),
        _orders_ms('none', selector='[data-yc-tour="orders-sample-meta"]', title='时间与买家',
            body='第二行显示下单时间与买家名称；游客单会标注。'),
        _orders_ms('none', selector='[data-yc-tour="orders-detail-link"]', title='查看订单详情',
            body='点进去可看完整明细与各分区；有未读留言会显示红点。',
            tips=('也可点「下一步」进入详情页继续观摩。', '现场备货收款请去「店铺工作台」，本页以查单核对为主。')),
        _order_detail_ms(selector='[data-yc-tour="preview-banner"]', title='订单详情（演示）',
            body='本页只读观摩，不会真改订单或发留言。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-hero"]', title='顶栏总览',
            body='当前订单状态、订单号、履约方式与合计金额，一眼看清这单处于什么阶段。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-contact"]', title='联系客人',
            body='有问题先电话或微信沟通；这里可复制买家账号，桌号单会显示桌位信息。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-buyer"]', title='买家与履约信息',
            body='买家账号、打包/堂食/外卖方式、地址或桌号；外卖单还可看配送距离。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-chat"]', title='订单沟通',
            body='与买家的留言记录；重要协商请写在这里留痕。打开本页即视为已看过新留言。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-items"]', title='订单内容',
            body='每笔买了什么菜、数量多少、该行小计多少。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-fee-total"]', title='费用合计',
            body='商品小计、配送费（如有）与订单应付总额。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-payment"]', title='支付情况',
            body='支付状态、支付渠道与支付时间；未收款单会显示原因。'),
        _order_detail_ms(selector='[data-yc-tour="order-detail-timeline"]', title='订单进度',
            body='当前处理状态、配送骑手（如有）与各节点时间线，便于追溯这单怎么走过来的。'),
        _orders_ms('none', selector='[data-yc-tour="orders-intro"]', title='订单管理体验结束',
            body='本大步已走完；下一步观摩展示主页。'),
    ]
    return {
        'id': 'seller-12',
        'title': '订单管理',
        'graduateTitle': '订单管理已观摩',
        'graduateSummary': '您已了解订单查询、筛选与详情沟通；下一步观摩展示主页。',
        'microSteps': steps,
    }


# 第 13 大步 · 展示主页：折叠布局（假 UI 积木 id）
_HOMEPAGE_FOLD_LAYOUTS: dict[str, list[str]] = {
    'none': [],
    'fake_intro': ['demo-home-intro'],
    'fake_add': ['demo-home-add-toolbar'],
    'custom_demo': ['experience-home-custom-demo'],
    'fake_settings': ['experience-home-fake-settings'],
}


def _homepage_ms(fold_key: str = 'none', *, page: str = 'preview_homepage', **kwargs) -> dict[str, Any]:
    layout = _HOMEPAGE_FOLD_LAYOUTS.get(fold_key)
    if layout is None:
        raise ValueError(f'未知展示主页折叠布局: {fold_key}')
    kwargs.pop('open_fold', None)
    return _ms(page, fold_layout=layout, **kwargs)


def _homepage_showcase_ms(**kwargs) -> dict[str, Any]:
    kwargs.pop('open_fold', None)
    return _ms('preview_homepage_showcase', fold_layout=[], **kwargs)


_DEMO_HOME_BODY = (
    '野草是开源免费的店铺管理系统，配合自部署服务器后，'
    '可以实现线上经营和自配送外卖管理'
)


def _seller_homepage() -> dict[str, Any]:
    """第 13 大步：展示主页（假 UI + 只读演示；卖家开店线收尾）"""
    steps: list[dict[str, Any]] = [
        _homepage_ms('none', selector='[data-yc-tour="nav-homepage"]', title='进入「展示主页」',
            body='点顶部菜单进入本页；这里编辑客人看到的店铺门面。'),
        _homepage_ms('none', selector='[data-yc-tour="demo-home-preset-labels"]', title='预设积木',
            body='简介、公告、进入店铺是系统预设的三块；开店时自动创建，可按需改内容。'),
        _homepage_ms('none', selector='[data-yc-tour="demo-home-add-row"]', title='添加自定义积木',
            body='点「+ 自定义积木（添加）」可新增自由编辑的模块，例如活动介绍或「野草系统是什么」。'),
        _homepage_ms('fake_intro', selector='[data-yc-tour="demo-home-fold-intro"]', title='简介积木',
            body='简介、公告、进入店铺都可以在这里展开后编辑标题与正文等内容。'),
        _homepage_ms('fake_add', selector='[data-yc-tour="fold-home-custom"]', title='添加自定义积木',
            body='新加的块会出现在列表最下面；本演示接下来编辑一块示例积木。'),
        _homepage_ms('fake_add', selector='[data-yc-tour="home-add-custom"]', title='添加按钮',
            body='点这里新增一块；体验模式不会真写入数据库。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-enabled"]', title='在主页显示',
            body='勾选后客人在店铺主页能看到本块；不勾选则隐藏。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-show-nav"]', title='进吸顶导航',
            body='勾选后顶栏导航会出现本块的短名；方便客人一键跳到本模块。', demo_type='check', demo_checked=True),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-sort"]', title='排序',
            demo_type='type', demo_text='70',
            body='这里输入的数字是排序用的，越小越靠前。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-nav-label"]', title='导航短名',
            demo_type='type', demo_text='关于野草',
            body='勾选进吸顶导航后，在导航栏会显示关于野草的按钮，点击后直达本模块。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-title"]', title='标题',
            demo_type='type', demo_text='野草系统是什么',
            body='本模块在主页展示时候的标题名称。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-upload"]', title='上传配图',
            body='可选：从手机或电脑上传一张图；单张不超过账号配额。体验不会真上传。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-body"]', title='正文',
            demo_type='type', demo_text=_DEMO_HOME_BODY,
            body='在店铺主页展示的内容。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-link-url"]', title='附加链接',
            body='可选：在标题旁加外链按钮，例如活动页或说明文档。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-link-label"]', title='链接文字',
            body='外链按钮上显示的文字；留空则用「了解更多」。'),
        _homepage_ms('custom_demo', selector='[data-yc-tour="home-block-save"]', title='保存本块',
            body='改完后须点保存；保存后列表会多出新的一块「野草系统是什么」。体验模式不会真保存。'),
        _homepage_ms('fake_settings', selector='[data-yc-tour="fold-home-settings"]', title='店铺主页总设置',
            body='顶栏「下单」跳哪里、预览门面等在这里配置。'),
        _homepage_ms('fake_settings', selector='[data-yc-tour="home-auto-read"]', title='自动读取的资料',
            body='店名、营业状态、时间、地址从其它页面自动同步，不用重复填。'),
        _homepage_ms('fake_settings', selector='[data-yc-tour="home-photo-quota"]', title='配图名额',
            body='全店上传配图共享此名额；超出需先清除旧图。'),
        _homepage_ms('fake_settings', selector='[data-yc-tour="home-preview-link"]', title='预览本店主页',
            body='点这里可在新窗口预览；下一步会演示点击进入预览页。'),
        _homepage_ms('fake_settings', selector='[data-yc-tour="home-nav-mode-select"]', title='顶栏「下单」行为',
            body='可直达下单页，或滚到页内「进入店铺」按钮。'),
        _homepage_ms('fake_settings', selector='[data-yc-tour="home-save-settings"]', title='保存主页设置',
            body='改完顶栏行为后须点保存；体验不会真保存。'),
        _homepage_ms('fake_settings', selector='[data-yc-tour="home-preview-link"]', title='点击进入预览',
            body='请点「预览本店主页」或点下方「下一步」，进入客人看到的店铺主页演示。',
            tips=('进入后将继续介绍顶栏导航与刚编辑的模块。',)),
        _homepage_showcase_ms(selector='[data-yc-tour="shop-home-header"]', title='店铺主页预览',
            body='顶栏下方自动显示店名、营业状态、营业时间与地址。'),
        _homepage_showcase_ms(selector='[data-yc-tour="shop-home-nav-about"]', title='顶栏导航',
            body='勾选「进吸顶导航」的积木会出现在这里；演示点击「关于野草」。', demo_click='[data-yc-tour="shop-home-nav-about"]'),
        _homepage_showcase_ms(selector='[data-yc-tour="shop-home-custom-module"]', title='自定义模块',
            body='这就是刚才自定义编辑好的模块：标题「野草系统是什么」与正文会展示在这里。'),
        _homepage_ms('none', selector='[data-yc-tour="fold-home-settings"]', title='展示主页体验结束',
            body='卖家开店线通用大步已走完；若已开启饮食/履约插件，还可选其它专项体验。'),
    ]
    return {
        'id': 'seller-13',
        'title': '展示主页',
        'graduateTitle': '展示主页已观摩',
        'graduateSummary': '您已了解店铺门面积木与预览；通用开店体验线至此结束。',
        'microSteps': steps,
    }


def _seller_register() -> dict[str, Any]:
    return {
        'id': 'seller-1',
        'title': '注册并开通店铺',
        'graduateTitle': '开通店铺流程已观摩',
        'graduateSummary': '您已了解开通页各字段；下一步看营业状态。',
        'microSteps': [
            _ms('home', selector='[data-yc-tour="nav-buyer-register"]', title='找到「注册」入口',
                body='先注册一个野草账户，默认是买家；开店在登录后的「我的」里。手机请先点 ☰。', open_nav=True),
            _ms('register', selector='.page-title', title='注册做什么',
                body='只注册一次。请先点开隐私条款并勾选同意；年龄两项只选一项。默认能逛店下单。'),
            _ms('shop_register', selector='[data-yc-tour="shop-register-title"]', title='开店从哪进',
                body='登录后到「我的 → 我要开店」填写店名地址。体验不真提交。'),
        ],
    }
