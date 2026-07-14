# 卖家后台：菜品销量统计（从已完成订单的菜品明细汇总）

from datetime import timedelta

from django.utils import timezone

from .models import BuyOrder


def _aggregate_dish_sales(orders) -> list[dict]:
    """把订单里的菜品明细汇总成销量列表"""
    totals = {}
    for order in orders:
        for item in order.dish_items or []:
            dish_id = str(item.get('dish_id', '')).replace('-', '')
            name = (item.get('name') or '未知菜品').strip()
            qty = int(item.get('quantity', 0) or 0)
            if qty <= 0:
                continue
            key = dish_id or name
            if key not in totals:
                totals[key] = {'dish_id': dish_id, 'name': name, 'quantity': 0}
            totals[key]['quantity'] += qty

    rows = sorted(totals.values(), key=lambda r: (-r['quantity'], r['name']))
    for i, row in enumerate(rows, start=1):
        row['rank'] = i
    return rows


def get_dish_sales_rankings(seller_id: str) -> dict:
    """
    返回日 / 周 / 月销量排行。
    日 = 今天 0 点起；周 = 近 7 天；月 = 近 30 天。
    只统计已完成订单。
    """
    now = timezone.now()
    local_now = timezone.localtime(now)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    base = BuyOrder.objects.filter(
        seller_id=seller_id,
        order_status='completed',
    ).only('dish_items', 'created_at')

    return {
        'day': _aggregate_dish_sales(base.filter(created_at__gte=today_start)),
        'week': _aggregate_dish_sales(base.filter(created_at__gte=week_start)),
        'month': _aggregate_dish_sales(base.filter(created_at__gte=month_start)),
        'day_label': f'今日（{local_now.strftime("%m月%d日")}）',
        'week_label': '近 7 天',
        'month_label': '近 30 天',
    }
