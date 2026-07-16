# 店铺工作台：店码、权限、页面数据组装

from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from .models import ShopProfile

SHOP_STAFF_ROLES = ('waiter', 'kitchen', 'rider', 'manager')
WORK_VIEWS = ('waiter', 'kitchen', 'rider')
SESSION_SHOP_WORK_CODE = 'shop_work_code'


def get_shop_profile_by_code(shop_code: str) -> ShopProfile | None:
    """按店码查店铺（不区分大小写）"""
    code = (shop_code or '').strip()
    if not code:
        return None
    return ShopProfile.objects.filter(shop_code__iexact=code).first()


def get_shop_code_for_user(user) -> str:
    """当前登录用户所属店铺店码；无则空字符串"""
    if not user.is_authenticated:
        return ''
    if user.role == 'seller':
        seller_id = user.username
    elif user.role in SHOP_STAFF_ROLES:
        seller_id = (user.employer_seller_id or '').strip()
    else:
        return ''
    if not seller_id:
        return ''
    profile = ShopProfile.objects.filter(seller_id=seller_id).values_list('shop_code', flat=True).first()
    return (profile or '').strip()


def user_belongs_to_shop(user, seller_id: str) -> bool:
    """是否可使用本店工作台（店主或本店员工）"""
    if not user.is_authenticated or not user.is_active:
        return False
    if user.role == 'seller':
        return user.username == seller_id
    if user.role in SHOP_STAFF_ROLES:
        return (user.employer_seller_id or '').strip() == seller_id
    return False


def work_permissions(user) -> dict[str, bool]:
    """各岗位是否可操作（店主三岗全开；店长可操作服务员视角以便处理订单）"""
    if user.role == 'seller':
        return {'waiter': True, 'kitchen': True, 'rider': True}
    if user.role == 'manager':
        return {'waiter': True, 'kitchen': False, 'rider': False}
    return {
        'waiter': user.role == 'waiter',
        'kitchen': user.role == 'kitchen',
        'rider': user.role == 'rider',
    }


def default_work_view(user) -> str:
    """登录后默认打开的 Tab"""
    mapping = {
        'waiter': 'waiter',
        'kitchen': 'kitchen',
        'rider': 'rider',
        'manager': 'waiter',
        'seller': 'waiter',
    }
    return mapping.get(user.role, 'waiter')


def build_shop_work_path(shop_code: str, *, view: str = '') -> str:
    """店铺工作台路径（相对）"""
    base = reverse('shop_work', kwargs={'shop_code': shop_code})
    view = (view or '').strip()
    if view in WORK_VIEWS:
        return f'{base}?view={view}'
    return base


def build_shop_work_order_path(shop_code: str, order_id) -> str:
    """工作台订单中转页（员工联系/沟通/取消，不进卖家后台）"""
    return reverse('shop_work_order', kwargs={'shop_code': shop_code, 'order_id': order_id})


def build_shop_work_redirect(shop_code: str, view: str, *, anchor: str = '') -> str:
    """操作完成后跳回工作台某视角"""
    url = build_shop_work_path(shop_code, view=view)
    if anchor:
        url = f'{url}#{anchor}'
    return url


def remember_shop_work_session(request, shop_code: str) -> None:
    """登录成功后记住当前店码，便于收款等跳回"""
    request.session[SESSION_SHOP_WORK_CODE] = (shop_code or '').strip()
    request.session.modified = True


def resolve_waiter_return_url(request) -> str:
    """服务员收款完成后返回地址"""
    code = (request.session.get(SESSION_SHOP_WORK_CODE) or '').strip() or get_shop_code_for_user(request.user)
    if code:
        return build_shop_work_path(code, view='waiter')
    return reverse('waiter_home')


def get_delivery_dispatch_role(seller_id: str) -> str:
    """手动派单归谁操作：跟随外卖交接方式"""
    from .operating_helpers import get_operating_settings

    settings = get_operating_settings(seller_id)
    mode = (getattr(settings, 'delivery_handoff_mode', '') or 'waiter').strip()
    return mode if mode in ('waiter', 'kitchen') else 'waiter'


def _today_range():
    """返回今天的起止时间（按项目时区）"""
    tz = timezone.get_current_timezone()
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, time.min), tz)
    return start, start + timedelta(days=1)


def build_shop_work_daily_history(seller_id: str, user=None) -> dict:
    """
    店铺工作台底部：今日订单历史 + 今日动作记录。
    老板看全店动作；员工只看自己账号相关的动作，方便核对「我刚才做过什么」。
    """
    from .models import BuyOrder, DeliveryOrder, OrderKitchenDishPrepLog, OrderWaiterDishServeLog, OrderWaiterStatusLog

    start, end = _today_range()
    is_owner = bool(user and getattr(user, 'role', '') == 'seller')
    username = (getattr(user, 'username', '') or '').strip() if user else ''
    role = (getattr(user, 'role', '') or '').strip() if user else ''

    today_orders = (
        BuyOrder.objects.filter(
            seller_id=seller_id,
            created_at__gte=start,
            created_at__lt=end,
        )
        .select_related('delivery_order')
        .order_by('-created_at')[:30]
    )
    order_rows = []
    for order in today_orders:
        delivery = getattr(order, 'delivery_order', None)
        order_rows.append({
            'order': order,
            'delivery': delivery,
            'status_label': order.get_order_status_display(),
            'delivery_label': delivery.get_delivery_status_display() if delivery else '',
        })

    activity_items: list[dict] = []
    show_kitchen = is_owner or role == 'kitchen'
    show_waiter = is_owner or role in ('waiter', 'manager')
    show_rider = is_owner or role == 'rider'
    show_shop_events = is_owner  # 收款/备齐等无操作人字段的事件，仅老板看全店汇总

    if show_kitchen:
        kitchen_qs = OrderKitchenDishPrepLog.objects.filter(
            order__seller_id=seller_id,
            changed_at__gte=start,
            changed_at__lt=end,
        ).select_related('order')
        if not is_owner and username:
            kitchen_qs = kitchen_qs.filter(changed_by=username)
        for log in kitchen_qs[:80]:
            action_label = '备好' if log.action == OrderKitchenDishPrepLog.ACTION_MARK else '撤回备好'
            who = log.changed_by if is_owner else '我'
            activity_items.append({
                'at': log.changed_at,
                'kind': '后厨',
                'text': f'{who} {action_label}「{log.dish_name}」({log.prepared_after}/{log.total_qty})',
                'order': log.order,
            })

    if show_waiter:
        serve_qs = OrderWaiterDishServeLog.objects.filter(
            order__seller_id=seller_id,
            changed_at__gte=start,
            changed_at__lt=end,
        ).select_related('order')
        if not is_owner and username:
            serve_qs = serve_qs.filter(changed_by=username)
        for log in serve_qs[:80]:
            action_label = '交付' if log.action == OrderWaiterDishServeLog.ACTION_MARK else '撤回交付'
            who = log.changed_by if is_owner else '我'
            activity_items.append({
                'at': log.changed_at,
                'kind': '服务员',
                'text': f'{who} {action_label}「{log.dish_name}」({log.served_after}/{log.total_qty})',
                'order': log.order,
            })

        labels = {
            'pending_serve': '服务中',
            'served': '已全部送达',
            'settled': '已结账',
        }
        status_qs = OrderWaiterStatusLog.objects.filter(
            order__seller_id=seller_id,
            changed_at__gte=start,
            changed_at__lt=end,
        ).select_related('order')
        if not is_owner and username:
            status_qs = status_qs.filter(changed_by=username)
        for log in status_qs[:50]:
            old_label = labels.get(log.from_status, '—') if log.from_status else '—'
            new_label = labels.get(log.to_status, log.to_status)
            who = log.changed_by if is_owner else '我'
            activity_items.append({
                'at': log.changed_at,
                'kind': '服务员',
                'text': f'{who} 将前台状态从「{old_label}」改为「{new_label}」',
                'order': log.order,
            })

    if show_shop_events:
        for order in BuyOrder.objects.filter(
            seller_id=seller_id,
            payment_time__gte=start,
            payment_time__lt=end,
        ).order_by('-payment_time')[:50]:
            activity_items.append({
                'at': order.payment_time,
                'kind': '订单',
                'text': f'订单已收款（{order.get_payment_method_display() or "未注明方式"}）',
                'order': order,
            })

        for order in BuyOrder.objects.filter(
            seller_id=seller_id,
            preparing_at__gte=start,
            preparing_at__lt=end,
        ).order_by('-preparing_at')[:50]:
            activity_items.append({
                'at': order.preparing_at,
                'kind': '后厨',
                'text': '开始备货',
                'order': order,
            })

        for order in BuyOrder.objects.filter(
            seller_id=seller_id,
            ready_at__gte=start,
            ready_at__lt=end,
        ).order_by('-ready_at')[:50]:
            ready_text = '餐品已全部备齐'
            if order.is_dine_in():
                ready_text = '餐品已全部备齐，等待上桌'
            elif order.is_takeaway():
                ready_text = '餐品已全部备齐，等待客人自取'
            elif order.fulfillment_type == 'delivery':
                ready_text = '餐品已全部备齐，等待骑手取餐'
            activity_items.append({
                'at': order.ready_at,
                'kind': '订单',
                'text': ready_text,
                'order': order,
            })

    if show_rider:
        delivery_orders = DeliveryOrder.objects.filter(
            buy_order__seller_id=seller_id,
        ).select_related('buy_order')
        if not is_owner and username:
            delivery_orders = delivery_orders.filter(rider_id=username)

        for delivery in delivery_orders.filter(accepted_at__gte=start, accepted_at__lt=end).order_by('-accepted_at')[:50]:
            if is_owner:
                text = f'已派给骑手 {delivery.rider_id}'
            else:
                text = '店铺已派单给我'
            activity_items.append({
                'at': delivery.accepted_at,
                'kind': '骑手',
                'text': text,
                'order': delivery.buy_order,
            })
        for delivery in delivery_orders.filter(picked_up_at__gte=start, picked_up_at__lt=end).order_by('-picked_up_at')[:50]:
            if is_owner:
                text = f'骑手 {delivery.rider_id} 已取餐'
            else:
                text = '我已取餐'
            activity_items.append({
                'at': delivery.picked_up_at,
                'kind': '骑手',
                'text': text,
                'order': delivery.buy_order,
            })
        for delivery in delivery_orders.filter(completed_at__gte=start, completed_at__lt=end).order_by('-completed_at')[:50]:
            if is_owner:
                text = f'骑手 {delivery.rider_id} 已送达'
            else:
                text = '我已送达'
            activity_items.append({
                'at': delivery.completed_at,
                'kind': '骑手',
                'text': text,
                'order': delivery.buy_order,
            })

    activity_items.sort(key=lambda item: item['at'] or start, reverse=True)
    return {
        'today_order_rows': order_rows,
        'today_activity_rows': activity_items[:40],
        'today_activity_is_owner_view': is_owner,
    }


def build_waiter_board_context(seller_id: str, *, allow_dispatch: bool = False) -> dict:
    """服务员 Tab 数据"""
    from .dispatch_helpers import get_shop_riders
    from .waiter_helpers import (
        build_dish_groups,
        get_serve_unit_label,
        get_waiter_phase_label,
        persist_dish_items_if_needed,
        query_waiter_active_orders,
        recent_waiter_activity_logs,
        waiter_can_close_uncollected,
        waiter_can_collect_payment,
        waiter_can_complete_in_store,
        waiter_can_confirm_cash,
        waiter_can_confirm_in_store_order,
    )

    raw_orders = list(query_waiter_active_orders(seller_id))
    dispatch_riders = list(get_shop_riders(seller_id))
    from .order_message_helpers import unread_map_for_orders

    unread_map = unread_map_for_orders(raw_orders, side='shop')
    orders = []
    for order in raw_orders:
        persist_dish_items_if_needed(order)
        delivery = getattr(order, 'delivery_order', None)
        orders.append({
            'order': order,
            'phase_label': get_waiter_phase_label(order),
            'dish_groups': build_dish_groups(order.dish_items),
            'serve_label': get_serve_unit_label(order),
            'log_lines': recent_waiter_activity_logs(order),
            'can_collect': waiter_can_collect_payment(order),
            'can_confirm_cash': waiter_can_confirm_cash(order),
            'can_confirm_in_store_order': waiter_can_confirm_in_store_order(order),
            'can_complete_in_store': waiter_can_complete_in_store(order),
            'can_close_uncollected': waiter_can_close_uncollected(order),
            'unread_msg_count': unread_map.get(order.order_id, 0),
            'can_dispatch': bool(
                allow_dispatch
                and order.fulfillment_type == 'delivery'
                and order.payment_status == 'paid'
                and not delivery
                and order.order_status in ('awaiting_prep', 'preparing', 'ready_pickup')
            ),
            'can_reassign': bool(
                allow_dispatch
                and delivery
                and delivery.delivery_status == 'accepted'
            ),
            'rider_id': delivery.rider_id if delivery else '',
            'delivery_status': delivery.get_delivery_status_display() if delivery else '',
        })
    return {'orders': orders, 'dispatch_riders': dispatch_riders}


def build_kitchen_board_context(seller_id: str, *, allow_dispatch: bool = False) -> dict:
    """后厨 Tab 数据"""
    from .dispatch_helpers import get_shop_riders
    from .kitchen_helpers import (
        build_kitchen_dish_groups,
        build_kitchen_dish_rows,
        build_kitchen_phase_label,
        build_kitchen_summary,
        latest_kitchen_new_order_ts,
        query_kitchen_board_orders,
        recent_kitchen_activity_logs,
    )

    raw_orders = list(query_kitchen_board_orders(seller_id))
    dispatch_riders = list(get_shop_riders(seller_id))
    rows = []
    for order in raw_orders:
        delivery = getattr(order, 'delivery_order', None)
        rows.append({
            'order': order,
            'phase_label': build_kitchen_phase_label(order),
            'dish_rows': build_kitchen_dish_rows(order),
            'dish_groups': build_kitchen_dish_groups(order),
            'log_lines': recent_kitchen_activity_logs(order),
            'can_dispatch': bool(
                allow_dispatch
                and order.fulfillment_type == 'delivery'
                and order.payment_status == 'paid'
                and not delivery
                and order.order_status in ('awaiting_prep', 'preparing', 'ready_pickup')
            ),
            'can_reassign': bool(
                allow_dispatch
                and delivery
                and delivery.delivery_status == 'accepted'
            ),
            'rider_id': delivery.rider_id if delivery else '',
        })
    return {
        'orders': rows,
        'summary_rows': build_kitchen_summary(raw_orders),
        'new_order_ts': latest_kitchen_new_order_ts(raw_orders),
        'dispatch_riders': dispatch_riders,
    }


def build_rider_board_context(user, seller_id: str) -> dict:
    """骑手 Tab 数据（店主预览本店全部进行中配送）"""
    from .models import DeliveryOrder
    from .waiter_helpers import delivery_handoff_ready

    rider_id = user.username
    seller_mode = user.role == 'seller'
    active_orders = DeliveryOrder.objects.exclude(
        delivery_status__in=['waiting', 'completed', 'cancelled']
    ).select_related('buy_order')
    if seller_mode:
        active_orders = active_orders.filter(buy_order__seller_id=seller_id)
    else:
        active_orders = active_orders.filter(rider_id=rider_id)

    active_list = list(active_orders.order_by('-created_at'))
    for order in active_list:
        order.handoff_ready = delivery_handoff_ready(order.buy_order)

    return {
        'active_orders': active_list,
        'rider_id': rider_id,
    }
