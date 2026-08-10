# A.11.2 桌台、桌码主单会话（饮食插件包内）+ V1 专属加点码 / 禁止双开

import secrets

from django.db import transaction
from django.utils import timezone
from waimai.time_helpers import now_local_wall

from waimai.models import BuyOrder, ShopTable, TableSession, VirtualTableCode
from waimai.operating_helpers import check_order_admission

# 陌生人扫物理桌码、桌已启用中时展示
PHYSICAL_TABLE_BUSY_MSG = '该桌正在使用中，请联系服务员获取加点码'
ADDON_TOKEN_INVALID_MSG = '加点码无效或已过期，请联系服务员'


def _new_addon_token() -> str:
    return secrets.token_urlsafe(16)


def get_table_by_token(seller_id: str, token: str) -> ShopTable | None:
    return ShopTable.objects.filter(
        seller_id=seller_id, qr_token=token, is_active=True,
    ).first()


def get_virtual_by_token(seller_id: str, token: str) -> VirtualTableCode | None:
    return VirtualTableCode.objects.filter(
        seller_id=seller_id, qr_token=token, is_active=True,
    ).first()


def get_open_main_session_for_table(shop_table: ShopTable) -> TableSession | None:
    """实体桌进行中的主单会话（一桌一单）"""
    return TableSession.objects.filter(
        shop_table=shop_table,
        session_type='main',
        status='open',
    ).first()


def table_main_session_is_active(shop_table: ShopTable) -> bool:
    return get_open_main_session_for_table(shop_table) is not None


def get_session_by_addon_token(seller_id: str, token: str) -> TableSession | None:
    if not (token or '').strip():
        return None
    return TableSession.objects.filter(
        seller_id=seller_id,
        addon_token=token.strip(),
        session_type='main',
        status='open',
    ).select_related('shop_table').first()


def ensure_addon_token(session: TableSession) -> str:
    """主单会话须有点加码；旧数据开台时补发。"""
    if session.session_type != 'main' or session.status != 'open':
        return session.addon_token or ''
    if session.addon_token:
        return session.addon_token
    token = _new_addon_token()
    TableSession.objects.filter(
        session_id=session.session_id,
        addon_token__isnull=True,
    ).update(addon_token=token)
    session.addon_token = token
    return token


def open_table_main_session(
    shop_table: ShopTable, device_key: str = '',
) -> tuple[TableSession | None, str]:
    """
    实体桌首次开台（仅空闲时可开）。
    禁止双开：已有进行中主单则拒绝（须用专属加点码加入）。
    """
    ok, msg = check_order_admission(shop_table.seller_id, 'dine_in')
    if not ok:
        return None, msg

    with transaction.atomic():
        ShopTable.objects.select_for_update().get(pk=shop_table.table_id)
        if get_open_main_session_for_table(shop_table):
            return None, PHYSICAL_TABLE_BUSY_MSG

        session = TableSession.objects.create(
            seller_id=shop_table.seller_id,
            shop_table=shop_table,
            session_type='main',
            device_key=device_key or '',
            addon_token=_new_addon_token(),
        )
    return session, ''


def bind_addon_session(
    seller_id: str, addon_token: str, device_key: str = '',
) -> tuple[TableSession | None, str]:
    """扫专属加点码：绑定本桌进行中主单，可继续加点。"""
    ok, msg = check_order_admission(seller_id, 'dine_in')
    if not ok:
        return None, msg

    session = get_session_by_addon_token(seller_id, addon_token)
    if not session:
        return None, ADDON_TOKEN_INVALID_MSG

    if device_key and not session.device_key:
        session.device_key = device_key
        session.save(update_fields=['device_key'])
    return session, ''


def open_virtual_session(
    code: VirtualTableCode, device_key: str = '',
) -> tuple[TableSession | None, str]:
    ok, msg = check_order_admission(code.seller_id, 'dine_in')
    if not ok:
        return None, msg
    if virtual_code_is_busy(code):
        return None, '该虚拟桌码使用中，请换码或等待结账'

    session = TableSession.objects.create(
        seller_id=code.seller_id,
        virtual_code=code,
        session_type='virtual',
        device_key=device_key or '',
    )
    return session, ''


def get_open_session_for_virtual(code: VirtualTableCode) -> TableSession | None:
    return TableSession.objects.filter(
        virtual_code=code,
        session_type='virtual',
        status='open',
    ).first()


def virtual_code_is_busy(code: VirtualTableCode) -> bool:
    return TableSession.objects.filter(virtual_code=code, status='open').exists()


def get_open_order_for_session(session: TableSession) -> BuyOrder | None:
    """会话关联的进行中主订单"""
    return BuyOrder.objects.filter(
        table_session=session,
    ).exclude(order_status__in=('completed', 'cancelled')).order_by('-created_at').first()


def close_table_session(session: TableSession):
    session.status = 'closed'
    session.closed_at = now_local_wall()
    session.save(update_fields=['status', 'closed_at'])


def build_table_scan_path(seller_id: str, token: str) -> str:
    return f'/dine/?seller_id={seller_id}&t={token}'


def build_addon_scan_path(seller_id: str, addon_token: str) -> str:
    return f'/dine/?seller_id={seller_id}&s={addon_token}'


def build_virtual_scan_path(seller_id: str, token: str) -> str:
    return f'/dine/?seller_id={seller_id}&v={token}'
