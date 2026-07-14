# 展示主页积木：预设块注册表与组装（A.10 · 通用，不绑个体）

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction

# 预设块类型（插件日后可往注册表追加）
BLOCK_HERO = 'hero'
BLOCK_INTRO = 'intro'
BLOCK_HOURS = 'hours'
BLOCK_ADDRESS = 'address'
BLOCK_NOTICE = 'notice'
BLOCK_ORDER_CTA = 'order_cta'
BLOCK_DIRECTORY = 'directory'
BLOCK_YECAO_INTRO = 'yecao_intro'

# 「点餐」导航行为
ORDER_NAV_TO_SHOP = 'to_shop'
ORDER_NAV_TO_CTA = 'to_cta_block'


@dataclass(frozen=True)
class BlockTypeSpec:
    """一种预设块的说明书（给后台与前台用）"""
    code: str
    label: str
    default_nav_label: str
    default_enabled: bool
    default_show_in_nav: bool
    default_sort: int
    allows_body: bool
    description: str


# 系统预设块：默认启用店内介绍类；名录与野草介绍默认关闭（拥有者自选）
PRESET_BLOCK_SPECS: tuple[BlockTypeSpec, ...] = (
    BlockTypeSpec(
        BLOCK_HERO, '店名 / 头图', '首页', True, True, 10, True,
        '展示店名与一句口号；头图地址可填公开图片链接（可选）',
    ),
    BlockTypeSpec(
        BLOCK_INTRO, '简介', '简介', True, True, 20, True,
        '店铺或本服务器的公开介绍文字',
    ),
    BlockTypeSpec(
        BLOCK_HOURS, '营业时间', '时间', True, True, 30, True,
        '营业时段说明（可与后台营业设置文案互补）',
    ),
    BlockTypeSpec(
        BLOCK_ADDRESS, '地址', '地址', True, True, 40, True,
        '公开地址；地图链接可选',
    ),
    BlockTypeSpec(
        BLOCK_NOTICE, '公告', '公告', False, True, 50, True,
        '临时公告；默认关闭',
    ),
    BlockTypeSpec(
        BLOCK_ORDER_CTA, '开始点餐', '点餐', True, False, 60, True,
        '页内「开始点餐」按钮；导航「点餐」默认可直接进点菜页',
    ),
    BlockTypeSpec(
        BLOCK_DIRECTORY, '名录', '名录', False, True, 70, True,
        '可选：列出本服务器上已登记且允许展示的店铺；默认关闭',
    ),
    BlockTypeSpec(
        BLOCK_YECAO_INTRO, '野草介绍', '野草', False, True, 80, True,
        '可选：介绍野草系统是什么；默认关闭，绝不强制每台服务器启用',
    ),
)

_PRESET_BY_CODE = {s.code: s for s in PRESET_BLOCK_SPECS}


def get_block_spec(code: str) -> BlockTypeSpec | None:
    return _PRESET_BY_CODE.get(code)


def list_preset_specs() -> list[BlockTypeSpec]:
    return list(PRESET_BLOCK_SPECS)


def register_block_type(spec: BlockTypeSpec) -> None:
    """插件占位：运行时追加块类型（第一阶段仅预留调用口）"""
    global PRESET_BLOCK_SPECS, _PRESET_BY_CODE
    if spec.code in _PRESET_BY_CODE:
        return
    PRESET_BLOCK_SPECS = PRESET_BLOCK_SPECS + (spec,)
    _PRESET_BY_CODE = {s.code: s for s in PRESET_BLOCK_SPECS}


def ensure_home_page_for_seller(seller_id: str, shop_profile=None):
    """确保该店有主页配置与预设块行；已有则不覆盖内容"""
    from .models import ShopHomeBlock, ShopHomePage, ShopProfile

    seller_id = (seller_id or '').strip()
    if not seller_id:
        return None

    page, created = ShopHomePage.objects.get_or_create(
        seller_id=seller_id,
        defaults={
            'order_nav_mode': ORDER_NAV_TO_SHOP,
            'is_server_entry': False,
        },
    )
    if shop_profile is None:
        shop_profile = ShopProfile.objects.filter(seller_id=seller_id).first()

    existing = {b.block_type: b for b in page.blocks.all()}
    to_create = []
    for spec in PRESET_BLOCK_SPECS:
        if spec.code in existing:
            continue
        title, body = _default_content(spec.code, shop_profile)
        to_create.append(ShopHomeBlock(
            block_id=uuid.uuid4(),
            home_page=page,
            block_type=spec.code,
            title=title,
            body=body,
            is_enabled=spec.default_enabled,
            show_in_nav=spec.default_show_in_nav,
            sort_order=spec.default_sort,
            nav_label=spec.default_nav_label,
        ))
    if to_create:
        ShopHomeBlock.objects.bulk_create(to_create)
    return page


def _default_content(block_type: str, shop_profile) -> tuple[str, str]:
    """新块的默认标题与正文（公开信息；野草介绍用中性通用文案）"""
    name = (shop_profile.shop_name if shop_profile else '') or '本店'
    address = (shop_profile.address if shop_profile else '') or ''
    if block_type == BLOCK_HERO:
        return name, '欢迎光临'
    if block_type == BLOCK_INTRO:
        return '简介', f'{name}使用野草系统接待堂食与外卖订单。'
    if block_type == BLOCK_HOURS:
        return '营业时间', '请以店内实际营业与后台「堂食营业」设置为准。'
    if block_type == BLOCK_ADDRESS:
        return '地址', address or '地址待填写'
    if block_type == BLOCK_NOTICE:
        return '公告', ''
    if block_type == BLOCK_ORDER_CTA:
        return '开始点餐', '浏览菜单、加入购物车并下单'
    if block_type == BLOCK_DIRECTORY:
        return '店铺名录', '以下为本服务器上可展示的店铺（由拥有者决定是否启用本块）。'
    if block_type == BLOCK_YECAO_INTRO:
        return '关于野草', (
            '野草系统是一套去中心化的本地餐饮与配送网页工具：'
            '每台服务器属于其拥有者，店铺自管菜品、订单与收款，平台不抽佣。'
            '本块为可选介绍，服务器拥有者可随时关闭。'
        )
    return '', ''


def resolve_entry_home_page():
    """
    解析本服务器默认入口主页所属店铺：
    1) 标记为「本服务器入口」的主页；
    2) 否则若仅有一家已登记店，用该店；
    3) 否则取最早登记的一家（仍通用，不绑死某账号名）。
    """
    from .models import ShopHomePage, ShopProfile

    marked = (
        ShopHomePage.objects.filter(is_server_entry=True)
        .select_related()
        .first()
    )
    if marked:
        ensure_home_page_for_seller(marked.seller_id)
        return ShopHomePage.objects.filter(seller_id=marked.seller_id).first()

    shops = list(ShopProfile.objects.order_by('registered_at', 'seller_id')[:2])
    if not shops:
        return None
    seller_id = shops[0].seller_id
    return ensure_home_page_for_seller(seller_id, shops[0])


@transaction.atomic
def set_server_entry(seller_id: str) -> None:
    """将某店主页设为本服务器默认入口（同时清掉其它入口标记）"""
    from .models import ShopHomePage

    seller_id = (seller_id or '').strip()
    ensure_home_page_for_seller(seller_id)
    ShopHomePage.objects.exclude(seller_id=seller_id).update(is_server_entry=False)
    ShopHomePage.objects.filter(seller_id=seller_id).update(is_server_entry=True)


def build_home_view_context(page, request=None) -> dict:
    """组装前台展示用的块列表与导航"""
    from .models import ShopProfile

    ensure_home_page_for_seller(page.seller_id)
    page.refresh_from_db()
    blocks = list(
        page.blocks.filter(is_enabled=True).order_by('sort_order', 'block_type')
    )
    shop = ShopProfile.objects.filter(seller_id=page.seller_id).first()
    directory_shops = []
    if any(b.block_type == BLOCK_DIRECTORY for b in blocks):
        directory_shops = list(
            ShopProfile.objects.filter(is_listed=True).order_by('shop_name')
        )

    nav_items = []
    for b in blocks:
        if not b.show_in_nav:
            continue
        # 点餐块默认不进锚点导航；由顶栏「点餐」单独处理
        if b.block_type == BLOCK_ORDER_CTA:
            continue
        spec = get_block_spec(b.block_type)
        nav_items.append({
            'label': b.nav_label or b.title or (spec.default_nav_label if spec else b.block_type),
            'anchor': f'block-{b.block_type}',
        })

    order_url = f'/shop/?seller_id={page.seller_id}'
    order_nav_mode = page.order_nav_mode or ORDER_NAV_TO_SHOP
    order_nav_href = order_url if order_nav_mode == ORDER_NAV_TO_SHOP else '#block-order_cta'

    return {
        'home_page': page,
        'shop_profile': shop,
        'home_blocks': blocks,
        'home_nav_items': nav_items,
        'directory_shops': directory_shops,
        'order_url': order_url,
        'order_nav_href': order_nav_href,
        'order_nav_mode': order_nav_mode,
    }
