# 展示主页积木：服务器主页与店铺主页严格分层（A.10 完善）

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max, Q


# 预设块类型（插件日后可往注册表追加）
BLOCK_HERO = 'hero'  # 已弃用：店头改由固定自动区展示
BLOCK_INTRO = 'intro'
BLOCK_HOURS = 'hours'  # 已弃用：自动店头展示
BLOCK_ADDRESS = 'address'  # 已弃用：自动店头展示
BLOCK_NOTICE = 'notice'
BLOCK_ORDER_CTA = 'order_cta'
BLOCK_DIRECTORY = 'directory'
BLOCK_YECAO_INTRO = 'yecao_intro'
BLOCK_CONTACT_US = 'contact_us'
BLOCK_PUBLIC_WALL = 'public_wall'
BLOCK_FILE_DOWNLOAD = 'file_download'
BLOCK_CUSTOM = 'custom'

ORDER_NAV_TO_SHOP = 'to_shop'
ORDER_NAV_TO_CTA = 'to_cta_block'

# 第一版：自定义积木数量上限（防乱折腾）
MAX_SHOP_CUSTOM_BLOCKS = 20
MAX_SERVER_CUSTOM_BLOCKS = 20
MAX_SERVER_DOWNLOAD_BLOCKS = 5

# 店铺主页：店主后台可编辑的预设块（仅三块）
SHOP_EDITOR_PRESET_TYPES = frozenset({BLOCK_INTRO, BLOCK_NOTICE, BLOCK_ORDER_CTA})
# 兼容旧名
SHOP_EDITABLE_BLOCK_TYPES = frozenset(SHOP_EDITOR_PRESET_TYPES | {BLOCK_CUSTOM})
# 历史遗留块：不再创建、不在前台与后台展示
SHOP_LEGACY_BLOCK_TYPES = frozenset({BLOCK_HERO, BLOCK_HOURS, BLOCK_ADDRESS})
SHOP_AUTO_BLOCK_TYPES = SHOP_LEGACY_BLOCK_TYPES
# 服务器主页专用（店主后台不出现）
SERVER_ONLY_BLOCK_TYPES = frozenset({
    BLOCK_DIRECTORY, BLOCK_YECAO_INTRO, BLOCK_FILE_DOWNLOAD, BLOCK_PUBLIC_WALL,
    BLOCK_CONTACT_US,
})
# 只挂唯一二级页「野草互动社区」，不挂大厅、不挂其它专题页
COMMUNITY_ONLY_BLOCK_TYPES = frozenset({BLOCK_CONTACT_US, BLOCK_PUBLIC_WALL})


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
    scope: str  # 'shop' | 'server' | 'both'


# 新店开店时只创建这三块预设
SHOP_PRESET_SPECS: tuple[BlockTypeSpec, ...] = (
    BlockTypeSpec(
        BLOCK_INTRO, '简介', '简介', True, True, 20, True,
        '本店公开介绍（仅本店主页）', 'shop',
    ),
    BlockTypeSpec(
        BLOCK_NOTICE, '公告', '公告', False, True, 50, True,
        '临时公告；默认关闭', 'shop',
    ),
    BlockTypeSpec(
        BLOCK_ORDER_CTA, '进入店铺', '店铺', True, False, 60, True,
        '页内「进入店铺」按钮；顶栏「下单」默认可直接进下单页。勾选「进吸顶导航」后，导航会多出本块短名', 'shop',
    ),
)

CUSTOM_BLOCK_SPEC = BlockTypeSpec(
    BLOCK_CUSTOM, '自定义积木', '更多', True, True, 200, True,
    '可自由填写标题、正文、图片与链接；每页最多 20 块', 'both',
)

FILE_DOWNLOAD_BLOCK_SPEC = BlockTypeSpec(
    BLOCK_FILE_DOWNLOAD, '文件下载', '下载', True, False, 55, True,
    '标题+介绍+上传一个文件；未上传文件时主页不显示下载按钮。可添加多块。', 'server',
)

SERVER_PRESET_SPECS: tuple[BlockTypeSpec, ...] = (
    BlockTypeSpec(
        BLOCK_DIRECTORY, '店铺名录', '名录', True, True, 20, True,
        '列出本服务器允许公开的店铺，支持按店名搜索', 'server',
    ),
    BlockTypeSpec(
        BLOCK_YECAO_INTRO, '野草介绍', '野草', False, True, 40, True,
        '可选：介绍野草系统是什么；默认关闭，绝不强制', 'server',
    ),
    BlockTypeSpec(
        BLOCK_CONTACT_US, '联系我们', '联系', True, True, 50, True,
        '展示对外联系方式并接收访客留言；名称与邮箱在「留言管理」中填写', 'server',
    ),
    BlockTypeSpec(
        BLOCK_PUBLIC_WALL, '野草公开留言壁', '留言壁', True, True, 52, True,
        '人人可见的公开墙；与「联系我们」私信分开，不共用一张表', 'server',
    ),
)

_SHOP_BY_CODE = {s.code: s for s in SHOP_PRESET_SPECS}
_SERVER_BY_CODE = {s.code: s for s in SERVER_PRESET_SPECS}


def get_shop_block_spec(code: str) -> BlockTypeSpec | None:
    if code == BLOCK_CUSTOM:
        return CUSTOM_BLOCK_SPEC
    return _SHOP_BY_CODE.get(code)


def get_server_block_spec(code: str) -> BlockTypeSpec | None:
    if code == BLOCK_CUSTOM:
        return CUSTOM_BLOCK_SPEC
    if code == BLOCK_FILE_DOWNLOAD:
        return FILE_DOWNLOAD_BLOCK_SPEC
    from waimai.server_plugin_runtime.registry import get_server_block_spec as _plugin_spec

    plugin = _plugin_spec(code)
    if plugin:
        return plugin
    return _SERVER_BY_CODE.get(code)


def get_block_spec(code: str) -> BlockTypeSpec | None:
    """兼容旧调用：优先店铺说明书"""
    return get_shop_block_spec(code) or get_server_block_spec(code)


def list_shop_preset_specs() -> list[BlockTypeSpec]:
    return list(SHOP_PRESET_SPECS)


def list_server_preset_specs() -> list[BlockTypeSpec]:
    return list(SERVER_PRESET_SPECS)


def list_preset_specs() -> list[BlockTypeSpec]:
    """兼容：返回店铺预设（旧卖家后台）"""
    return list_shop_preset_specs()


def block_dom_id(block) -> str:
    """前台锚点与卡片 id（自定义块、下载块用 UUID，其它预设块用类型名）"""
    if block.block_type in (BLOCK_CUSTOM, BLOCK_FILE_DOWNLOAD):
        return f'block-{block.block_id}'
    return f'block-{block.block_type}'


def count_shop_custom_blocks(page) -> int:
    return page.blocks.filter(block_type=BLOCK_CUSTOM).count()


def count_server_custom_blocks(page) -> int:
    return page.blocks.filter(block_type=BLOCK_CUSTOM).count()


def count_server_download_blocks(page) -> int:
    return page.blocks.filter(block_type=BLOCK_FILE_DOWNLOAD).count()


def _next_custom_sort_order(page) -> int:
    """新自定义块默认排在现有块之后（可再在后台改小数字插到前面）"""
    agg = page.blocks.aggregate(m=Max('sort_order'))
    return max(900, (agg['m'] or 0) + 10)


@transaction.atomic
def add_shop_custom_block(page):
    """新增一块店铺自定义积木；达上限返回 None"""
    if count_shop_custom_blocks(page) >= MAX_SHOP_CUSTOM_BLOCKS:
        return None
    n = count_shop_custom_blocks(page) + 1
    return page.blocks.create(
        block_id=uuid.uuid4(),
        block_type=BLOCK_CUSTOM,
        title=f'自定义内容 {n}',
        body='',
        is_enabled=True,
        show_in_nav=False,
        sort_order=_next_custom_sort_order(page),
        nav_label='更多',
    )


@transaction.atomic
def add_server_custom_block(page):
    """新增一块服务器自定义积木；达上限返回 None"""
    if count_server_custom_blocks(page) >= MAX_SERVER_CUSTOM_BLOCKS:
        return None
    n = count_server_custom_blocks(page) + 1
    return page.blocks.create(
        block_id=uuid.uuid4(),
        block_type=BLOCK_CUSTOM,
        title=f'自定义内容 {n}',
        body='',
        is_enabled=True,
        show_in_nav=False,
        sort_order=_next_custom_sort_order(page),
        nav_label='更多',
    )


@transaction.atomic
def add_server_download_block(page):
    """新增一块服务器「文件下载」积木；达上限返回 None"""
    if count_server_download_blocks(page) >= MAX_SERVER_DOWNLOAD_BLOCKS:
        return None
    n = count_server_download_blocks(page) + 1
    return page.blocks.create(
        block_id=uuid.uuid4(),
        block_type=BLOCK_FILE_DOWNLOAD,
        title=f'下载文件 {n}',
        body='点击下方按钮下载。',
        is_enabled=True,
        show_in_nav=False,
        sort_order=_next_custom_sort_order(page),
        nav_label='下载',
        link_label='下载文件',
    )


def ensure_home_page_for_seller(seller_id: str, shop_profile=None):
    """确保该店有店铺主页与店铺预设块；不含服务器专用块"""
    from .models import ShopHomeBlock, ShopHomePage, ShopProfile

    seller_id = (seller_id or '').strip()
    if not seller_id:
        return None

    page, _created = ShopHomePage.objects.get_or_create(
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
    for spec in SHOP_PRESET_SPECS:
        if spec.code in existing:
            continue
        title, body = _default_shop_content(spec.code, shop_profile)
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

    # 关掉已有服务器专用块与历史店头/时间/地址块
    page.blocks.filter(
        block_type__in=SERVER_ONLY_BLOCK_TYPES | SHOP_LEGACY_BLOCK_TYPES
    ).update(is_enabled=False)

    # 旧默认文案 → 新默认（仅仍为旧字样时改，店主已改过的不动）
    page.blocks.filter(block_type=BLOCK_ORDER_CTA, title='开始点餐').update(title='进入店铺')
    page.blocks.filter(block_type=BLOCK_ORDER_CTA, nav_label='点餐').update(nav_label='店铺')
    page.blocks.filter(
        block_type=BLOCK_ORDER_CTA,
        body='浏览菜单、加入购物车并下单',
    ).update(body='浏览商品、加入购物车并下单')
    return page


def convert_server_intro_notice_to_custom() -> int:
    """把旧的服务器介绍/公告专用块改成可增删的自定义积木。"""
    from .models import ServerHomeBlock

    return ServerHomeBlock.objects.filter(
        block_type__in=(BLOCK_INTRO, BLOCK_NOTICE),
    ).update(block_type=BLOCK_CUSTOM)


def ensure_server_home_page():
    """确保一级大厅与预设块存在（大厅固定页编号 1）"""
    from .models import ServerHomeBlock, ServerHomePage

    page, _created = ServerHomePage.objects.get_or_create(
        singleton_id=1,
        defaults={
            'page_role': ServerHomePage.PAGE_HALL,
            'slug': '',
            'title': '一级大厅',
            'welcome_body': '',
            'welcome_enabled': True,
        },
    )
    if page.page_role != ServerHomePage.PAGE_HALL or page.slug:
        page.page_role = ServerHomePage.PAGE_HALL
        page.slug = ''
        if not (page.title or '').strip():
            page.title = '一级大厅'
        page.save(update_fields=['page_role', 'slug', 'title', 'updated_at'])

    convert_server_intro_notice_to_custom()

    existing = {b.block_type: b for b in page.blocks.all()}
    to_create = []
    for spec in SERVER_PRESET_SPECS:
        if spec.code in COMMUNITY_ONLY_BLOCK_TYPES:
            continue
        if spec.code in existing:
            continue
        title, body = _default_server_content(spec.code)
        to_create.append(ServerHomeBlock(
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
        ServerHomeBlock.objects.bulk_create(to_create)
    return page


def _default_shop_content(block_type: str, shop_profile) -> tuple[str, str]:
    name = (shop_profile.shop_name if shop_profile else '') or '本店'
    if block_type == BLOCK_INTRO:
        return '简介', f'{name}欢迎您。'
    if block_type == BLOCK_NOTICE:
        return '公告', ''
    if block_type == BLOCK_ORDER_CTA:
        return '进入店铺', '浏览商品、加入购物车并下单'
    return '', ''


def _default_server_content(block_type: str) -> tuple[str, str]:
    if block_type == BLOCK_INTRO:
        return '本服务器', '欢迎访问本服务器。以下为可公开浏览的店铺。'
    if block_type == BLOCK_DIRECTORY:
        return '店铺名录', '点击店铺可进入该店主页；也可按店名搜索。'
    if block_type == BLOCK_NOTICE:
        return '公告', ''
    if block_type == BLOCK_YECAO_INTRO:
        return '关于野草', (
            '野草系统是一套去中心化的本地餐饮与配送网页工具：'
            '每台服务器属于其拥有者，店铺自管菜品、订单与收款，平台不抽佣。'
            '本块为可选介绍，服务器拥有者可随时关闭。'
        )
    if block_type == BLOCK_CONTACT_US:
        return '联系我们', ''
    if block_type == BLOCK_PUBLIC_WALL:
        return '野草公开留言壁', ''
    return '', ''


def format_shop_hours_text(seller_id: str) -> str:
    """从营业设置拼出可读营业时间"""
    from .models import ShopOperatingSettings

    op = ShopOperatingSettings.objects.filter(seller_id=seller_id).first()
    if not op:
        return '营业时间待店主在「堂食营业」中设置。'
    lines = []
    if op.closed_for_today:
        lines.append('本日打烊')
    if op.pause_new_orders:
        lines.append('当前暂停接新单')
    bo = op.business_open.strftime('%H:%M') if op.business_open else ''
    bc = op.business_close.strftime('%H:%M') if op.business_close else ''
    if bo and bc:
        lines.append(f'全天营业：{bo} – {bc}')
    dine_on = '开' if op.dine_channel_enabled else '关'
    take_on = '开' if getattr(op, 'takeaway_channel_enabled', True) else '关'
    del_on = '开' if op.delivery_channel_enabled else '关'
    lines.append(f'堂食通道：{dine_on}；打包通道：{take_on}；外卖通道：{del_on}')
    return '\n'.join(lines) if lines else '请以店内实际营业为准。'


def format_shop_status_text(seller_id: str) -> str:
    from .models import ShopOperatingSettings

    op = ShopOperatingSettings.objects.filter(seller_id=seller_id).first()
    if not op:
        return '营业状态未知'
    if op.closed_for_today:
        return '本日打烊'
    if op.pause_new_orders:
        return '暂停接单'
    return '营业中'


@transaction.atomic
def set_server_entry(seller_id: str) -> None:
    """兼容旧调用：不再把某店设为整机入口；仅确保店铺主页存在"""
    ensure_home_page_for_seller(seller_id)


def resolve_entry_home_page():
    """兼容旧名：现返回一级大厅"""
    return ensure_server_home_page()


def _attach_block_meta(blocks, get_spec_fn):
    """给块挂上说明书、前台锚点与展示用图片地址"""
    from .home_block_download_helpers import (
        block_download_button_label,
        block_download_url,
        block_has_download_file,
    )
    from .home_block_media import block_display_image_src, block_display_link_label

    for b in blocks:
        b.spec = get_spec_fn(b.block_type)
        b.dom_id = block_dom_id(b)
        b.display_image_src = block_display_image_src(b)
        b.display_link_label = block_display_link_label(b)
        # 与前台 showcase 一致：进入店铺/名录/下载块不用配图与附加链接那套
        b.shows_rich_media = b.block_type not in (
            BLOCK_ORDER_CTA, BLOCK_DIRECTORY, BLOCK_FILE_DOWNLOAD, BLOCK_PUBLIC_WALL,
        )
        # 站内路径用本页打开；外链仍新标签
        link = (b.link_url or '').strip()
        b.link_is_internal = bool(link.startswith('/'))
        if b.block_type == BLOCK_FILE_DOWNLOAD:
            b.has_download_file = block_has_download_file(b)
            b.download_url = block_download_url(b) if b.has_download_file else ''
            b.download_button_label = block_download_button_label(b)
        else:
            b.has_download_file = False
            b.download_url = ''
            b.download_button_label = ''


def build_shop_home_view_context(page, request=None) -> dict:
    """组装店铺主页前台上下文"""
    from .models import ShopProfile

    ensure_home_page_for_seller(page.seller_id)
    page.refresh_from_db()
    shop = ShopProfile.objects.filter(seller_id=page.seller_id).first()
    blocks = list(
        page.blocks.filter(is_enabled=True)
        .exclude(block_type__in=SERVER_ONLY_BLOCK_TYPES | SHOP_LEGACY_BLOCK_TYPES)
        .order_by('sort_order', 'block_type')
    )
    # 所有积木（含自定义）统一按排序数字比大小；数字越小越靠前
    blocks.sort(key=lambda b: (b.sort_order, str(b.block_type)))
    _attach_block_meta(blocks, get_shop_block_spec)

    # 凡勾选「进吸顶导航」的启用块都进导航（含自定义；进入店铺块默认不勾，避免与顶栏「下单」重复）
    nav_items = []
    for b in blocks:
        if not b.show_in_nav:
            continue
        spec = b.spec
        nav_items.append({
            'label': (b.nav_label or b.title or (spec.default_nav_label if spec else b.block_type)).strip() or '导航',
            'anchor': b.dom_id,
        })

    order_url = f'/shop/?seller_id={page.seller_id}'
    order_nav_mode = page.order_nav_mode or ORDER_NAV_TO_SHOP
    order_nav_href = order_url if order_nav_mode == ORDER_NAV_TO_SHOP else '#block-order_cta'

    return {
        'home_kind': 'shop',
        'home_page': page,
        'shop_profile': shop,
        'shop_status_text': format_shop_status_text(page.seller_id) if shop else '',
        'shop_hours_text': format_shop_hours_text(page.seller_id) if shop else '',
        'home_blocks': blocks,
        'home_nav_items': nav_items,
        'directory_shops': [],
        'directory_query': '',
        'order_url': order_url,
        'order_nav_href': order_nav_href,
        'order_nav_mode': order_nav_mode,
        'brand_title': (shop.shop_name if shop else '店铺主页'),
        'page_public_path': f'/s/{shop.shop_code}/home/' if shop and shop.shop_code else '/',
        'show_topic_welcome': False,
        'topic_welcome_body': '',
        'topic_welcome_storage_key': '',
        'is_server_topic': False,
    }


def build_server_home_view_context(request=None, page=None) -> dict:
    """组装服务器主页前台上下文（大厅或二级专题页）"""
    from .models import ShopProfile, ServerHomePage
    from .home_page_tier_helpers import (
        allowed_server_block_types,
        ensure_community_page,
        server_page_public_path,
        topic_welcome_should_show,
    )

    if page is None:
        page = ensure_server_home_page()
    elif page.page_role == ServerHomePage.PAGE_HALL:
        page = ensure_server_home_page()

    ensure_community_page()

    allowed = allowed_server_block_types(page)
    qs = page.blocks.filter(is_enabled=True)
    if page.is_hall:
        qs = qs.exclude(block_type__in=COMMUNITY_ONLY_BLOCK_TYPES)
    elif allowed is not None:
        qs = qs.filter(block_type__in=allowed)
    blocks = list(qs.order_by('sort_order', 'block_type'))
    blocks.sort(key=lambda b: (b.sort_order, str(b.block_type)))
    _attach_block_meta(blocks, get_server_block_spec)

    q = ''
    if request is not None:
        q = (request.GET.get('q') or request.GET.get('search') or '').strip()

    directory_shops = []
    if page.is_hall and any(b.block_type == BLOCK_DIRECTORY for b in blocks):
        qs = ShopProfile.objects.filter(is_listed=True).order_by('shop_name')
        if q:
            qs = qs.filter(Q(shop_name__icontains=q) | Q(address__icontains=q))
        directory_shops = list(qs)

    nav_items = []
    for b in blocks:
        if not b.show_in_nav:
            continue
        spec = b.spec
        nav_items.append({
            'label': b.nav_label or b.title or (spec.default_nav_label if spec else b.block_type),
            'anchor': b.dom_id,
        })

    from .owner_helpers import get_site_settings
    from waimai.server_plugin_runtime import enrich_server_home_context

    site = get_site_settings()
    public_path = server_page_public_path(page)
    brand = (page.title or '').strip() if page.is_topic else (site.site_name or '本服务器')
    if page.is_topic and not brand:
        brand = page.slug or '专题页'

    ctx = {
        'home_kind': 'server',
        'home_page': page,
        'shop_profile': None,
        'shop_status_text': '',
        'shop_hours_text': '',
        'home_blocks': blocks,
        'home_nav_items': nav_items,
        'directory_shops': directory_shops,
        'directory_query': q,
        'order_url': '',
        'order_nav_href': '#block-directory',
        'order_nav_mode': '',
        'brand_title': brand,
        'page_public_path': public_path,
        'is_server_topic': page.is_topic,
        'show_topic_welcome': topic_welcome_should_show(page),
        'topic_welcome_body': (page.welcome_body or '') if topic_welcome_should_show(page) else '',
        'topic_welcome_storage_key': f'yecao_topic_welcome_{page.pk}' if page.is_topic else '',
    }
    if page.is_community:
        from .guestbook_helpers import get_guestbook_settings
        from .public_wall_helpers import build_public_wall_home_context

        ctx['guestbook_settings'] = get_guestbook_settings()
        ctx.update(build_public_wall_home_context(request))
        return ctx

    if page.is_hall:
        ctx['guestbook_settings'] = None
        ctx['public_wall_posts'] = []
        ctx['public_wall_pager'] = None
        from .bulletin_helpers import bulletin_public_state

        st = bulletin_public_state()
        ctx['show_hall_bulletin_popup'] = bool(st['popup_body'])
        ctx['hall_bulletin_body'] = st['popup_body']
        ctx['hall_bulletin_revision'] = st['popup_revision']
        ctx = enrich_server_home_context(ctx)
        from .onboarding.context import enrich_server_home_onboarding
        return enrich_server_home_onboarding(ctx)

    ctx['guestbook_settings'] = None
    ctx['public_wall_posts'] = []
    ctx['public_wall_pager'] = None
    return ctx


def build_home_view_context(page, request=None) -> dict:
    """兼容旧调用：若是店铺主页则按店铺组装"""
    from .models import ShopHomePage, ServerHomePage

    if isinstance(page, ShopHomePage):
        return build_shop_home_view_context(page, request)
    if isinstance(page, ServerHomePage):
        return build_server_home_view_context(request, page=page)
    return build_server_home_view_context(request)
