# 店铺工作台：店码、权限、页面数据组装

from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from .models import ShopProfile
from .staff_account_helpers import ALL_STAFF_ROLES

# 兼容旧引用；员工角色只以 staff_account_helpers 的定义为准。
SHOP_STAFF_ROLES = ALL_STAFF_ROLES
# orders = 主体通用订单台；其余为业态插件 Tab
WORK_VIEWS = ('orders', 'waiter', 'kitchen', 'rider')
SESSION_SHOP_WORK_CODE = 'shop_work_code'


def current_seller_id_for_user(user) -> str:
    """统一取得账号所属店铺：店主用账号名，员工用所属店铺。"""
    if not getattr(user, 'is_authenticated', False):
        return ''
    if getattr(user, 'role', '') == 'seller':
        return (getattr(user, 'username', '') or '').strip()
    if getattr(user, 'role', '') in SHOP_STAFF_ROLES:
        return (getattr(user, 'employer_seller_id', '') or '').strip()
    return ''


def get_shop_profile_by_code(shop_code: str) -> ShopProfile | None:
    """按店码查店铺（不区分大小写）"""
    code = (shop_code or '').strip()
    if not code:
        return None
    return ShopProfile.objects.filter(shop_code__iexact=code).first()


def get_shop_code_for_user(user) -> str:
    """当前登录用户所属店铺店码；无则空字符串"""
    seller_id = current_seller_id_for_user(user)
    if not seller_id:
        return ''
    profile = ShopProfile.objects.filter(seller_id=seller_id).values_list('shop_code', flat=True).first()
    return (profile or '').strip()


def user_belongs_to_shop(user, seller_id: str) -> bool:
    """是否可使用本店工作台（店主或本店员工）"""
    if not user.is_authenticated or not user.is_active:
        return False
    return current_seller_id_for_user(user) == seller_id


def work_permissions(user) -> dict[str, bool]:
    """各业务面板是否可写入；通用订单台按细权限拆开后，有改状态或确认收款即视为可操作。"""
    from .staff_account_helpers import (
        PERM_DINING_KITCHEN,
        PERM_DINING_RIDER,
        PERM_DINING_WAITER,
        PERM_ORDERS_CONFIRM_PAYMENT,
        PERM_ORDERS_UPDATE_STATUS,
        staff_has_any_order_desk_permission,
        staff_has_permission,
    )

    if user.role == 'seller':
        return {'orders': True, 'waiter': True, 'kitchen': True, 'rider': True}
    can_orders_write = (
        staff_has_permission(user, PERM_ORDERS_UPDATE_STATUS)
        or staff_has_permission(user, PERM_ORDERS_CONFIRM_PAYMENT)
    )
    return {
        # 能打开订单台：任一细权限；写入由面板内按钮再判
        'orders': staff_has_any_order_desk_permission(user) and can_orders_write,
        'waiter': staff_has_permission(user, PERM_DINING_WAITER),
        'kitchen': staff_has_permission(user, PERM_DINING_KITCHEN),
        'rider': staff_has_permission(user, PERM_DINING_RIDER),
    }


def default_work_view(user) -> str:
    """登录后打开第一个有操作权（或至少可看订单台）的业务 Tab。"""
    from .staff_account_helpers import staff_has_any_order_desk_permission

    permissions = work_permissions(user)
    for view in WORK_VIEWS:
        if permissions.get(view):
            return view
    if staff_has_any_order_desk_permission(user):
        return 'orders'
    return 'orders'


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
    from .dispatch_helpers import get_delivery_handoff_mode

    return get_delivery_handoff_mode(seller_id)


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
    from .staff_account_helpers import (
        PERM_DINING_KITCHEN,
        PERM_DINING_RIDER,
        PERM_DINING_WAITER,
        staff_has_permission,
    )

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
    show_kitchen = staff_has_permission(user, PERM_DINING_KITCHEN)
    show_waiter = staff_has_permission(user, PERM_DINING_WAITER)
    show_rider = staff_has_permission(user, PERM_DINING_RIDER)
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


def build_waiter_board_context(
    seller_id: str, *, allow_dispatch: bool = False, sort_mode: str = 'newest',
) -> dict:
    """服务员 Tab 数据"""
    from .dispatch_helpers import get_shop_riders
    from .order_workflow_rules import order_can_dispatch
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
    )

    raw_orders = list(query_waiter_active_orders(seller_id, sort_mode=sort_mode))
    dispatch_riders = list(get_shop_riders(seller_id))
    from .order_message_helpers import unread_map_for_orders
    from .wait_time_helpers import can_adjust_order_wait_time

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
            'can_adjust_wait_time': can_adjust_order_wait_time(order),
            'can_complete_in_store': waiter_can_complete_in_store(order),
            'can_close_uncollected': waiter_can_close_uncollected(order),
            'unread_msg_count': unread_map.get(order.order_id, 0),
            'can_dispatch': bool(
                allow_dispatch
                and order_can_dispatch(order)
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


def build_kitchen_board_context(
    seller_id: str, *, allow_dispatch: bool = False, sort_mode: str = 'newest',
) -> dict:
    """后厨 Tab 数据"""
    from .dispatch_helpers import get_shop_riders
    from .order_workflow_rules import order_can_dispatch
    from .kitchen_helpers import (
        build_kitchen_dish_groups,
        build_kitchen_dish_rows,
        build_kitchen_phase_label,
        build_kitchen_summary,
        kitchen_order_can_start,
        latest_kitchen_new_order_ts,
        query_kitchen_board_orders,
        recent_kitchen_activity_logs,
    )

    from .workbench_sort_helpers import order_queryset_by_created

    raw_orders = list(order_queryset_by_created(
        query_kitchen_board_orders(seller_id),
        sort_mode,
    ))
    dispatch_riders = list(get_shop_riders(seller_id))
    from .wait_time_helpers import can_adjust_order_wait_time

    rows = []
    for order in raw_orders:
        delivery = getattr(order, 'delivery_order', None)
        rows.append({
            'order': order,
            'phase_label': build_kitchen_phase_label(order),
            'dish_rows': build_kitchen_dish_rows(order),
            'dish_groups': build_kitchen_dish_groups(order),
            'log_lines': recent_kitchen_activity_logs(order),
            'can_adjust_wait_time': can_adjust_order_wait_time(order),
            'can_start_preparing': kitchen_order_can_start(order),
            'can_dispatch': bool(
                allow_dispatch
                and order_can_dispatch(order)
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


def build_rider_board_context(user, seller_id: str, *, sort_mode: str = 'newest') -> dict:
    """骑手 Tab 数据（店主预览本店全部进行中配送）"""
    from .dispatch_helpers import query_pending_dispatch_orders, validate_shop_rider
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

    from .workbench_sort_helpers import order_queryset_by_created

    active_list = list(order_queryset_by_created(active_orders, sort_mode))
    for order in active_list:
        order.handoff_ready = delivery_handoff_ready(order.buy_order)

    rider_cash = None
    if not seller_mode:
        from .rider_cash_helpers import rider_remittance_context

        rider_cash = rider_remittance_context(seller_id, rider_id)

    return {
        'active_orders': active_list,
        'pending_dispatch_orders': list(query_pending_dispatch_orders(seller_id)[:30]),
        'rider_can_claim': (not seller_mode and validate_shop_rider(seller_id, rider_id)),
        'rider_id': rider_id,
        'rider_cash_remittance': rider_cash,
    }
