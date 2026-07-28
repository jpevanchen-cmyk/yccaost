# 新版新手体验：卖家开店线（第 1～6 大步）

from __future__ import annotations

from typing import Any

from .demo_cleanup import DEMO_DISH_NAME, DEMO_MENU_PROFILE_NAME
from .tour_common import ms as _ms

# 第 5 大步 · 三分档演示描述（正本 docs/新手引导流程.md）
_DEMO_DESC_NORMAL = '普通价格所有用户都可以下单（包括未注册的游客帐户）'
_DEMO_DESC_MEMBER = '会员价格需要本店铺注册用户可以下单'
_DEMO_DESC_SPECIAL = '特价需要本店注册用户，并且每个用户有限购数量'


def seller_tour_majors(*, dining_enabled: bool = False, seller_id: str = '') -> list[dict[str, Any]]:
    """v2 卖家体验大步"""
    from waimai.product_shell_helpers import build_product_shell

    shell = build_product_shell(seller_id) if seller_id else {}
    item = shell.get('item_word', '商品')
    catalog = shell.get('catalog_word', '菜单清单')
    catalog_title = (shell.get('catalog_panel_title') or catalog).lstrip('📋 ').strip()
    sales_title = shell.get('sales_title', '商品销量排行')
    dine_hint = '堂食/打包/外卖细分在「堂食营业」大步。' if dining_enabled else '细分通道可在启用相应插件后配置。'
    return [
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
    ]


def _seller_operating(dine_hint: str) -> dict[str, Any]:
    return {
        'id': 'seller-2',
        'title': '营业状态',
        'graduateTitle': '营业状态已观摩',
        'graduateSummary': '您已了解全天营业时间与营业中/停止开关；下一步体验菜单清单。',
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
            _ms('preview_products', selector='[data-yc-tour="menu-profile-name"]', title=f'新建{catalog}名称',
                demo_type='type', demo_text=DEMO_MENU_PROFILE_NAME,
                body=f'本演示预设输入「{DEMO_MENU_PROFILE_NAME}」。'),
            _ms('preview_products', selector='[data-yc-tour="menu-copy-select"]', title='展开「复制自」',
                body='可选「全新」或复制已有清单；下面两步分别说明。'),
            _ms('preview_products', selector='[data-yc-tour="menu-copy-new-option"]', title='「全新（纳入全部商品）」',
                body=f'把所有已添加的{item}全部纳入新清单，展示设定从零配。'),
            _ms('preview_products', selector='[data-yc-tour="menu-copy-select"]', title='复制「通用清单」',
                body=(
                    '复制通用清单里的内容，含上下架、会员价/特价是否展示等设定，可节约时间；'
                    '本演示选此项。'
                ),
                demo_type='select', demo_text_key='demoCopyProfileId'),
            _ms('preview_products', selector='[data-yc-tour="menu-create-submit"]', title=f'创建「{DEMO_MENU_PROFILE_NAME}」',
                body='请在高亮处点「创建」真实建立；体验结束后系统会自动清理演示数据。' + action_hint,
                demo_type='action',
                warn='演示会写入官方演示店；退出或本步完成后会清理。'),
            _ms('preview_products', selector='[data-yc-tour="menu-active-state"]', title='当前使用中清单',
                body='上方应显示「通用清单」为使用中；若下拉框不在通用清单，请先切到通用清单再看下方详情。'),
            _ms('preview_products', selector='[data-yc-tour="menu-delete-btn"]', title='删除清单',
                body='使用中的清单不能删除；删除按钮应为灰色且无法点击。',
                warn='容易错：未先切换使用就删清单会失败。'),
            _ms('preview_products', selector='[data-yc-tour="menu-profile-select"]', title=f'选中「{DEMO_MENU_PROFILE_NAME}」',
                body='在下拉框选中演示清单；选好后下方显示该清单详情。' + action_hint,
                demo_type='select_name', demo_text=DEMO_MENU_PROFILE_NAME),
            _ms('preview_products', selector='[data-yc-tour="menu-activate-btn"]', title='切换使用',
                body='请点「切换使用」，把演示清单设为客人可见；切换后上方「当前使用中」应变。' + action_hint,
                demo_type='action'),
            _ms('preview_products', selector='[data-yc-tour="menu-active-state"]', title='确认已切换',
                body=f'应显示「{DEMO_MENU_PROFILE_NAME}」为使用中。'),
            _ms('preview_products', selector='[data-yc-tour="menu-profile-select"]', title='切回通用清单',
                body='在下拉框选回通用清单，准备把使用中清单改回去。' + action_hint,
                demo_type='select_name', demo_text='通用'),
            _ms('preview_products', selector='[data-yc-tour="menu-activate-btn"]', title='切换回通用清单',
                body='请点「切换使用」，让通用清单重新对客人生效。' + action_hint,
                demo_type='action'),
            _ms('preview_products', selector='[data-yc-tour="menu-profile-select"]', title=f'再选「{DEMO_MENU_PROFILE_NAME}」',
                body='选中演示清单后，可演示删除非使用中的清单。' + action_hint,
                demo_type='select_name', demo_text=DEMO_MENU_PROFILE_NAME),
            _ms('preview_products', selector='[data-yc-tour="menu-delete-btn"]', title='删除演示清单',
                body='请点「删除」真实删除演示清单；后续上下架演示在通用清单里进行。' + action_hint,
                demo_type='action',
                warn='删除后无法恢复；体验结束也会自动清理残留。'),
            _ms('preview_products', selector='[data-yc-tour="menu-item-listed-toggle"]', title='上架 → 下架',
                body=f'请点「上架中」，把该{item}在本清单改为下架；客人将看不到、不能下单。' + action_hint,
                demo_type='action'),
            _ms('preview_products', selector='[data-yc-tour="menu-item-listed-toggle"]', title='下架 → 上架',
                body='再点一次，恢复上架状态。' + action_hint,
                demo_type='action'),
            _ms('preview_products', selector='[data-yc-tour="menu-item-member-toggle"]', title='会员价展示 ↔ 不展示',
                body=f'须「商品管理」里已允许会员价，且本{catalog}勾选展示，客人才看得到会员价按钮。' + action_hint,
                demo_type='action',
                tips=(f'本演示{item}已预设允许会员价。',)),
            _ms('preview_products', selector='[data-yc-tour="menu-item-special-toggle"]', title='特价展示 ↔ 不展示',
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
            _ms('preview_products', selector='[data-yc-tour="menu-print-qr-link"]', title='批量打印入口',
                open_fold='#menu-panel',
                body='请点蓝色链接「批量打印本清单商品二维码」进入打印页；贴货架供顾客扫码加购（须登录买家）。'),
            _ms('preview_print_qr', selector='[data-yc-tour="print-qr-intro"]', title='打印页说明',
                body='以下为使用中清单内、已上架且可扫码的商品；每个可用档位各一张码。'),
            _ms('preview_print_qr', selector='[data-yc-tour="print-qr-g18-hint"]', title='预告 · 收银结账码',
                body='「扫货后至收银台出示结账码统一算账」见手册 G1-8，尚未上线。',
                tips=('当前 G1-6/7 已支持扫商品码加购。',)),
            _ms('preview_print_qr', selector='[data-yc-tour="print-qr-btn"]', title='打印本页',
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
            _ms('preview_products', selector='[data-yc-tour="add-name"]', title=f'{item}名称',
                open_fold='#product-add',
                demo_type='type', demo_text=DEMO_DISH_NAME,
                body=f'演示输入「{DEMO_DISH_NAME}」。'),
            _ms('preview_products', selector='[data-yc-tour="add-price"]', title='通用价格',
                demo_type='type', demo_text='99',
                body='演示输入价格，例如 99 元。'),
            _ms('preview_products', selector='[data-yc-tour="add-sort"]', title='排序',
                body=(
                    '0 = 不排序，按商品添加顺序排列；'
                    '1 = 商品置顶；数字越大，位置越靠后。'
                )),
            _ms('preview_products', selector='[data-yc-tour="add-desc-block"]', title='普通 / 会员 / 特价描述',
                demo_type='type_multi',
                demo_fields=[
                    {'selector': '[data-yc-tour="add-desc-normal"] textarea', 'text': _DEMO_DESC_NORMAL},
                    {'selector': '[data-yc-tour="add-desc-member"] textarea', 'text': _DEMO_DESC_MEMBER},
                    {'selector': '[data-yc-tour="add-desc-special"] textarea', 'text': _DEMO_DESC_SPECIAL},
                ],
                body='此处为示例，各价格档位，可以分别设置不同描述。'),
            _ms('preview_products', selector='[data-yc-tour="add-member-enable"]', title='启用会员价',
                demo_type='check', demo_checked=True,
                body='勾选后下方会员价选项才会展开。'),
            _ms('preview_products', selector='[data-yc-tour="add-member-limits"]', title='单日限购 + 累计限购',
                body=(
                    '单日限购会每日重置；'
                    '累计限购设定后，顾客购买到达上限后不能再购买本商品的会员价。'
                ),
                warn='容易错：两种限购含义不同，请按需填写或留空表示不限。'),
            _ms('preview_products', selector='[data-yc-tour="add-special-enable"]', title='启用特价',
                demo_type='check', demo_checked=True,
                body='勾选后下方特价选项才会展开。'),
            _ms('preview_products', selector='[data-yc-tour="add-special-limit"]', title='本特价商品每人限购',
                body='顾客购买到达上限后，不能再购买本商品的特价。',
                tips=('演示可保持默认 1。',)),
            _ms('preview_products', selector='[data-yc-tour="add-image"]', title='添加商品图片',
                body='此处可以选择商品图片。'),
            _ms('preview_products', selector='[data-yc-tour="add-list-all"]', title='添加后全部清单上架',
                body=(
                    '勾选后添加成功会立即展示在店铺'
                    '（注意，勾选后，添加成功，顾客就马上可以下单，若未准备好销售的商品，切勿勾选）'
                )),
            _ms('preview_products', selector='[data-yc-tour="add-submit"]', title=f'添加{item}',
                body='请点「添加商品」真实建立；第 6 大步结束或体验退出时自动清理。' + action_hint,
                demo_type='action',
                warn='演示会写入官方演示店。'),
            _ms('preview_products', selector='[data-yc-tour="demo-s5-step12-shot"]', title=f'已添加「{DEMO_DISH_NAME}」',
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
            '卖家开店线六大步已全部体验；演示商品将自动清理。'
        ),
        'cleanupOnComplete': True,
        'microSteps': [
            _ms('preview_products', selector='[data-yc-tour="demo-s6-shot-1"]',
                title=f'「{DEMO_DISH_NAME}」基本资料',
                open_fold='#experience-s6-demo',
                body='这里可以确认商品的基本资料，详情在下方，可以在体验后自行查看。'),
            _ms('preview_products', selector='[data-yc-tour="demo-s6-shot-2"]',
                title='分档扫码加购二维码',
                open_fold='#experience-s6-demo',
                body=(
                    '此处自动生成二维码，适合货架商品，顾客可以直接扫码取货，'
                    '直接到收银处出示订单码结算，或者自行结算（功能规划中，近期会更新）'
                )),
            _ms('preview_products', selector='[data-yc-tour="demo-s6-shot-3"]',
                title='添加商品图片',
                open_fold='#experience-s6-demo',
                body='这里可以上传添加新图片'),
            _ms('preview_products', selector='[data-yc-tour="demo-s6-shot-4"]',
                title='已上传图片管理',
                open_fold='#experience-s6-demo',
                body=(
                    '点上下箭头可以更改图片显示位置，点删可以删除不需要的图片，'
                    '点同步/刷新商品图片才会同步到服务器（注意，由于浏览器缓存的关系，'
                    '可能造成更改不成功的假象，可以按Ctrl+F5强制刷新浏览器查看）'
                )),
            _ms('preview_products', selector='[data-yc-tour="demo-s6-shot-5"]',
                title='预览店铺',
                open_fold='#experience-s6-demo',
                body='点此处可以预览您的店铺'),
            _ms('preview_products', selector='[data-yc-tour="demo-s6-shot-6"]',
                title='店铺预览',
                open_fold='#experience-s6-demo',
                body='恭喜你成功装修好了自己的店铺'),
        ],
    }


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
                body='旧版体验区供对照；本引导为新版试运行。'),
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
