# 店铺工作台：店码、权限、页面数据组装

from datetime import datetime, time, timedelta

from django.urls import reverse
from django.utils import timezone

from .models import ShopProfile
from .staff_account_helpers import ALL_STAFF_ROLES

# 兼容旧引用；员工角色只以 staff_account_helpers 的定义为准。
SHOP_STAFF_ROLES = ALL_STAFF_ROLES
# orders = 主体通用订单台；cashier = 实体收银台；其余为业态插件 Tab
WORK_VIEWS = ('orders', 'cashier', 'cash_manage', 'waiter', 'kitchen', 'rider')
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
        PERM_FULFILLMENT_CASH_MANAGE,
        PERM_ORDERS_CASHIER,
        PERM_ORDERS_CONFIRM_PAYMENT,
        PERM_ORDERS_UPDATE_STATUS,
        staff_has_any_order_desk_permission,
        staff_has_permission,
    )

    if user.role == 'seller':
        return {
            'orders': True,
            'cashier': True,
            'cash_manage': True,
            'waiter': True,
            'kitchen': True,
            'rider': True,
        }
    can_orders_write = (
        staff_has_permission(user, PERM_ORDERS_UPDATE_STATUS)
        or staff_has_permission(user, PERM_ORDERS_CONFIRM_PAYMENT)
    )
    return {
        # 能打开订单台：任一细权限；写入由面板内按钮再判
        'orders': staff_has_any_order_desk_permission(user) and can_orders_write,
        'cashier': staff_has_permission(user, PERM_ORDERS_CASHIER),
        'cash_manage': staff_has_permission(user, PERM_FULFILLMENT_CASH_MANAGE),
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


def build_shop_work_daily_history(
    seller_id: str,
    user=None,
    *,
    request=None,
    list_base_url: str = '',
) -> dict:
    """
    店铺工作台底部：今日订单历史 + 今日动作记录（分卡 + 分页）。
    老板看全店动作；员工只看自己账号相关的动作。
    """
    from .models import BuyOrder, DeliveryOrder, OrderKitchenDishPrepLog, OrderWaiterDishServeLog, OrderWaiterStatusLog
    from .workbench_pagination_helpers import (
        paginate_sequence,
        resolve_work_list_page_size,
        work_list_pagination_context,
    )

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
        .order_by('-created_at')
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
    show_shop_events = is_owner

    if show_kitchen:
        kitchen_qs = OrderKitchenDishPrepLog.objects.filter(
            order__seller_id=seller_id,
            changed_at__gte=start,
            changed_at__lt=end,
        ).select_related('order')
        if not is_owner and username:
            kitchen_qs = kitchen_qs.filter(changed_by=username)
        for log in kitchen_qs.order_by('-changed_at'):
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
        for log in serve_qs.order_by('-changed_at'):
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
        for log in status_qs.order_by('-changed_at'):
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
        ).order_by('-payment_time'):
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
        ).order_by('-preparing_at'):
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
        ).order_by('-ready_at'):
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

        for delivery in delivery_orders.filter(accepted_at__gte=start, accepted_at__lt=end).order_by('-accepted_at'):
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
        for delivery in delivery_orders.filter(picked_up_at__gte=start, picked_up_at__lt=end).order_by('-picked_up_at'):
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
        for delivery in delivery_orders.filter(completed_at__gte=start, completed_at__lt=end).order_by('-completed_at'):
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

    hist_per_page = resolve_work_list_page_size(
        request.GET.get('hist_per_page') if request else None,
    )
    act_per_page = resolve_work_list_page_size(
        request.GET.get('act_per_page') if request else None,
    )
    hist_page_obj = paginate_sequence(
        order_rows,
        request.GET.get('hist_page') if request else 1,
        hist_per_page,
    )
    act_page_obj = paginate_sequence(
        activity_items,
        request.GET.get('act_page') if request else 1,
        act_per_page,
    )

    ctx = {
        'today_order_page': hist_page_obj,
        'today_activity_page': act_page_obj,
        'today_activity_is_owner_view': is_owner,
        'work_hist_fold_open': hist_page_obj.paginator.count > 0 or act_page_obj.paginator.count == 0,
        'work_act_fold_open': act_page_obj.paginator.count > 0 and hist_page_obj.paginator.count == 0,
        'work_act_fold_title': '📝 全店今日动作记录' if is_owner else '📝 我的今日动作记录',
        'work_act_fold_hint': (
            '老板可查看今天所有岗位、所有账号的操作。'
            if is_owner else
            '只显示当前账号自己做过的事，方便快速核对前面做过什么。'
        ),
        'work_act_empty_hint': (
            '今天暂时还没有动作记录。'
            if is_owner else
            '今天您还没有可核对的个人动作记录。'
        ),
    }
    if request and list_base_url:
        ctx['hist_pagination'] = work_list_pagination_context(
            list_base_url,
            request,
            page_param='hist_page',
            per_page_param='hist_per_page',
            per_page=hist_per_page,
            page_obj=hist_page_obj,
        )
        ctx['act_pagination'] = work_list_pagination_context(
            list_base_url,
            request,
            page_param='act_page',
            per_page_param='act_per_page',
            per_page=act_per_page,
            page_obj=act_page_obj,
        )
    return ctx


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
        waiter_can_mark_all_served,
    )

    raw_orders = list(query_waiter_active_orders(seller_id))
    dispatch_riders = list(get_shop_riders(seller_id))
    from .order_message_helpers import unread_map_for_orders
    from .wait_time_helpers import can_adjust_order_wait_time
    from .workbench_sort_helpers import group_board_rows_by_fulfillment, sort_waiter_board_rows

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
            'can_mark_all_served': waiter_can_mark_all_served(order),
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
    orders = sort_waiter_board_rows(orders)
    order_groups = group_board_rows_by_fulfillment(orders, fold_id_prefix='waiter')
    return {'orders': orders, 'order_groups': order_groups, 'dispatch_riders': dispatch_riders}


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
        kitchen_can_mark_all_prepared,
        latest_kitchen_new_order_ts,
        query_kitchen_board_orders,
        recent_kitchen_activity_logs,
    )

    from .workbench_shell_helpers import build_workbench_shell
    from .workbench_sort_helpers import group_board_rows_by_fulfillment, sort_kitchen_board_rows

    shell = build_workbench_shell(seller_id)
    raw_orders = list(query_kitchen_board_orders(seller_id))
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
            'can_mark_all_prepared': kitchen_can_mark_all_prepared(order),
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
    summary_rows = build_kitchen_summary(raw_orders)
    rows = sort_kitchen_board_rows(rows)
    order_groups = group_board_rows_by_fulfillment(rows, fold_id_prefix='kitchen')
    return {
        'orders': rows,
        'order_groups': order_groups,
        'summary_rows': summary_rows,
        'kitchen_summary_fold_open': bool(summary_rows),
        'kitchen_summary_fold_title': f'📦 {shell["kitchen_summary_title"]}',
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

    pending_list = list(query_pending_dispatch_orders(seller_id)[:30])
    active_list = list(order_queryset_by_created(active_orders, sort_mode))

    from waimai.dispatch_display_helpers import enrich_pending_dispatch_order
    from waimai.models import ShopProfile

    shop_pickup_raw = '店铺取货点'
    try:
        shop_pickup_raw = ShopProfile.objects.get(seller_id=seller_id).address or shop_pickup_raw
    except ShopProfile.DoesNotExist:
        pass
    for order in pending_list:
        enrich_pending_dispatch_order(order, shop_address=shop_pickup_raw)

    from waimai.order_timeline_helpers import (
        build_rider_delivery_wait_display,
        build_rider_pickup_wait_display,
    )
    from waimai.plugins.fulfillment.delivery_workflow_helpers import sync_delivery_overtime

    for order in active_list:
        order.handoff_ready = delivery_handoff_ready(order.buy_order)
        sync_delivery_overtime(order)
        order.rider_pickup_wait = build_rider_pickup_wait_display(order)
        order.rider_delivery_wait = build_rider_delivery_wait_display(order)
        short_id = str(order.delivery_id.hex)[:8]
        addr = (order.delivery_address or '').strip()
        if len(addr) > 18:
            addr = addr[:18] + '…'
        order.rider_fold_id = f'delivery-{short_id}'
        order.rider_fold_title = (
            f'配送 #{short_id} · {order.get_delivery_status_display()} · {addr}'
        )

    rider_cash = None
    if not seller_mode:
        from .rider_cash_helpers import rider_remittance_context

        rider_cash = rider_remittance_context(seller_id, rider_id)

    has_delivery = bool(active_list) or bool(pending_list)
    has_cash = False
    if rider_cash:
        has_cash = bool(rider_cash.get('available_count') or rider_cash.get('requests'))

    return {
        'active_orders': active_list,
        'pending_dispatch_orders': pending_list,
        'rider_can_claim': (not seller_mode and validate_shop_rider(seller_id, rider_id)),
        'rider_id': rider_id,
        'rider_cash_remittance': rider_cash,
        'rider_fold_delivery_open': has_delivery or not has_cash,
        'rider_fold_cash_open': has_cash and not has_delivery,
        # 真实工作台无演示入金数据；给 None 让模板 default: 可安全求值（演示预览仍有该变量）
        'onboarding_demo_rider_cash': None,
    }
