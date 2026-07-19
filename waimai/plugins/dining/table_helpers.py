# A.11.2 桌台、桌码主单会话（饮食插件包内）

from django.utils import timezone

from waimai.models import BuyOrder, ShopTable, TableSession, VirtualTableCode
from waimai.operating_helpers import check_order_admission


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


def get_open_session_for_virtual(code: VirtualTableCode) -> TableSession | None:
    return TableSession.objects.filter(
        virtual_code=code,
        session_type='virtual',
        status='open',
    ).first()


def virtual_code_is_busy(code: VirtualTableCode) -> bool:
    return TableSession.objects.filter(virtual_code=code, status='open').exists()


def open_table_main_session(
    shop_table: ShopTable, device_key: str = '',
) -> tuple[TableSession | None, str]:
    """打开或恢复实体桌主单会话"""
    ok, msg = check_order_admission(shop_table.seller_id, 'dine_in')
    if not ok:
        return None, msg

    existing = get_open_main_session_for_table(shop_table)
    if existing:
        return existing, ''

    session = TableSession.objects.create(
        seller_id=shop_table.seller_id,
        shop_table=shop_table,
        session_type='main',
        device_key=device_key or '',
    )
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


def get_open_order_for_session(session: TableSession) -> BuyOrder | None:
    """会话关联的进行中主订单"""
    return BuyOrder.objects.filter(
        table_session=session,
    ).exclude(order_status__in=('completed', 'cancelled')).order_by('-created_at').first()


def close_table_session(session: TableSession):
    session.status = 'closed'
    session.closed_at = timezone.now()
    session.save(update_fields=['status', 'closed_at'])


def build_table_scan_path(seller_id: str, token: str) -> str:
    return f'/dine/?seller_id={seller_id}&t={token}'


def build_virtual_scan_path(seller_id: str, token: str) -> str:
    return f'/dine/?seller_id={seller_id}&v={token}'
