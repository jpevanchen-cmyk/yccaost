from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from .forms import CreateKitchenForm
from .models import BuyOrder
from .dispatch_helpers import dispatch_buy_order, maybe_auto_dispatch_order, validate_shop_rider
from .kitchen_helpers import (
    get_delivery_handoff_mode,
    kitchen_order_can_start,
    mark_kitchen_dish_unit_prepared,
    undo_kitchen_dish_unit_prepared,
)


def handle_seller_kitchen_post(request, seller_id: str, *, section='kitchen'):
    """卖家管理后厨子账号"""
    if 'create_kitchen' in request.POST:
        form = CreateKitchenForm(request.POST, seller_id=seller_id)
        if form.is_valid():
            form.save()
            messages.success(request, '后厨账号已创建')
        else:
            messages.error(request, '创建失败，请检查用户名和密码')
        return redirect('seller_panel_section', section=section)

    if 'toggle_kitchen' in request.POST:
        from .staff_account_helpers import handle_seller_staff_toggle_post

        return handle_seller_staff_toggle_post(request, seller_id, 'kitchen', section=section)

    return None


def handle_kitchen_board_post(request, seller_id: str, *, redirect_to=None):
    """后厨看板：按份备好/撤回，并负责开始备货"""
    from django.urls import reverse

    operator = getattr(request, 'shop_work_user', None) or request.user
    target = redirect_to or reverse('kitchen_home')
    can_dispatch = operator.role == 'seller' or get_delivery_handoff_mode(seller_id) == 'kitchen'
    order_id = request.POST.get('order_id', '').strip()
    if not order_id:
        return None
    order = get_object_or_404(BuyOrder, order_id=order_id, seller_id=seller_id)

    if 'adjust_wait_time' in request.POST:
        from .audit_helpers import audit_order_status
        from .wait_time_helpers import adjust_order_wait_time

        ok, msg, minutes = adjust_order_wait_time(order, request.POST.get('wait_minutes'))
        if ok:
            audit_order_status(
                order=order,
                actor=operator,
                summary=f'调整预计时间 {order.get_display_order_no()}（从现在起约 {minutes} 分钟）',
                request=request,
            )
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'mark_prepared_unit' in request.POST:
        dish_id = request.POST.get('dish_id', '').strip()
        ok, msg = mark_kitchen_dish_unit_prepared(order, dish_id, operator_username=operator.username)
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'undo_prepared_unit' in request.POST:
        dish_id = request.POST.get('dish_id', '').strip()
        ok, msg = undo_kitchen_dish_unit_prepared(order, dish_id, operator_username=operator.username)
        if ok:
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return redirect(target)

    if 'start_preparing' in request.POST:
        if kitchen_order_can_start(order):
            order.order_status = 'preparing'
            order.preparing_at = timezone.now()
            update_fields = ['order_status', 'preparing_at', 'updated_at']
            if not order.estimated_ready_at:
                from .wait_time_helpers import assign_default_wait_time

                assign_default_wait_time(order, at=order.preparing_at, save=False)
                update_fields.append('estimated_ready_at')
            order.save(update_fields=update_fields)
            from .audit_helpers import audit_order_status
            audit_order_status(
                order=order,
                actor=operator,
                summary=f'开始备货 {order.get_display_order_no()}',
                request=request,
            )
            messages.success(request, '后厨已开始备货')
            delivery, err = maybe_auto_dispatch_order(order)
            if delivery:
                messages.success(request, f'已自动派单给骑手 {delivery.rider_id}')
            elif err:
                messages.error(request, err)
        else:
            messages.error(request, '当前订单不能开始备货')
        return redirect(target)

    if 'dispatch_order' in request.POST:
        if not can_dispatch:
            messages.error(request, '当前店铺设置下，后厨没有手动派单权限')
            return redirect(target)
        rider_id = request.POST.get('rider_id', '').strip() or None
        if order.payment_status == 'paid' and order.order_status in ('awaiting_prep', 'preparing', 'ready_pickup'):
            delivery, err = dispatch_buy_order(order, rider_id=rider_id)
            if delivery:
                messages.success(request, f'已派单给骑手 {delivery.rider_id}')
            else:
                messages.error(request, err or '派单失败')
        else:
            messages.error(request, '当前订单状态不能派单')
        return redirect(target)

    if 'reassign_rider' in request.POST:
        if not can_dispatch:
            messages.error(request, '当前店铺设置下，后厨没有手动派单权限')
            return redirect(target)
        rider_id = request.POST.get('rider_id', '').strip()
        if hasattr(order, 'delivery_order') and rider_id:
            if not validate_shop_rider(seller_id, rider_id):
                messages.error(request, '只能改派给本店当前上班中的骑手')
            else:
                delivery = order.delivery_order
                if delivery.delivery_status == 'accepted':
                    delivery.rider_id = rider_id
                    delivery.save(update_fields=['rider_id', 'updated_at'])
                    messages.success(request, f'已改派给骑手 {rider_id}')
                else:
                    messages.error(request, '配送已开始，无法改派')
        return redirect(target)

    return None
