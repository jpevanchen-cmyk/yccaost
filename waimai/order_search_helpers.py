# 卖家订单列表：搜索与筛选（公共逻辑，订单页与其它入口共用）

from datetime import timedelta
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from .models import BuyOrder

# 列表最多返回条数（防止一次拉太多）
ORDER_LIST_LIMIT = 100

# 时间范围选项（表单与说明共用）
ORDER_DATE_RANGE_CHOICES = (
    ('month', '近 1 个月'),
    ('week', '近 7 天'),
    ('today', '今天'),
    ('all', '全部时间'),
)

ORDER_SEARCH_PARAM_KEYS = (
    'q', 'order_status', 'payment_status', 'fulfillment_type', 'cash_issue', 'date_range',
)


def default_order_date_range() -> str:
    """默认只查近 1 个月"""
    return 'month'


def parse_seller_order_search(get_params) -> dict:
    """从网址参数解析订单搜索条件"""
    date_range = (get_params.get('date_range') or default_order_date_range()).strip()
    if date_range not in dict(ORDER_DATE_RANGE_CHOICES):
        date_range = default_order_date_range()
    return {
        'q': (get_params.get('q') or '').strip(),
        'order_status': (get_params.get('order_status') or '').strip(),
        'payment_status': (get_params.get('payment_status') or '').strip(),
        'fulfillment_type': (get_params.get('fulfillment_type') or '').strip(),
        'cash_issue': (get_params.get('cash_issue') or '').strip(),
        'date_range': date_range,
    }


def build_order_search_querystring(get_params) -> str:
    """把搜索条件拼回网址（操作订单后跳回列表时保留筛选）"""
    from urllib.parse import urlencode

    search = parse_seller_order_search(get_params)
    data = {'date_range': search['date_range']}
    if search['q']:
        data['q'] = search['q']
    if search['order_status']:
        data['order_status'] = search['order_status']
    if search['payment_status']:
        data['payment_status'] = search['payment_status']
    if search['fulfillment_type']:
        data['fulfillment_type'] = search['fulfillment_type']
    if search['cash_issue']:
        data['cash_issue'] = search['cash_issue']
    return urlencode(data)


def _apply_date_range(qs, date_range: str):
    """按时间范围过滤"""
    if date_range == 'all':
        return qs
    now = timezone.now()
    if date_range == 'today':
        start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        return qs.filter(created_at__gte=start)
    if date_range == 'week':
        return qs.filter(created_at__gte=now - timedelta(days=7))
    # 默认 month
    return qs.filter(created_at__gte=now - timedelta(days=30))


def _apply_keyword_filter(qs, keyword: str):
    """关键词：订单号、买家、桌号、地址、备注、菜名、骑手；兼容 订单号-店铺码-YYYYMMDD。"""
    if not keyword:
        return qs
    raw = str(keyword).strip().replace('#', '')
    q_compact = raw.replace('-', '').replace(' ', '').lower()
    parts = [p.strip() for p in raw.split('-') if p.strip()]

    date_token = ''
    short_token = ''
    for part in parts or [raw]:
        if len(part) == 8 and part.isdigit():
            date_token = part
        elif part:
            short_token = part.replace(' ', '')

    if short_token or date_token:
        filtered = qs
    else:
        q_obj = (
            Q(buyer_id__icontains=raw)
            | Q(table_label__icontains=raw)
            | Q(delivery_address__icontains=raw)
            | Q(buyer_note__icontains=raw)
            | Q(dish_items__icontains=raw)
            | Q(delivery_order__rider_id__icontains=raw)
        )
        if q_compact:
            q_obj = q_obj | Q(order_id__icontains=q_compact)
        filtered = qs.filter(q_obj).distinct()

    if short_token:
        filtered = filtered.filter(order_id__icontains=short_token.lower())
    if date_token:
        try:
            day = datetime.strptime(date_token, '%Y%m%d').date()
            filtered = filtered.filter(created_at__date=day)
        except ValueError:
            pass
    return filtered


def query_seller_orders(seller_id: str, search: dict):
    """按条件查询本店订单列表"""
    valid_order_status = {c[0] for c in BuyOrder.ORDER_STATUS_CHOICES}
    valid_payment_status = {c[0] for c in BuyOrder.PAYMENT_STATUS_CHOICES}
    valid_fulfillment = {c[0] for c in BuyOrder.FULFILLMENT_TYPE_CHOICES}

    qs = BuyOrder.objects.filter(seller_id=seller_id).select_related(
        'delivery_order', 'table_session',
    )
    qs = _apply_date_range(qs, search.get('date_range') or default_order_date_range())

    if search.get('order_status') in valid_order_status:
        qs = qs.filter(order_status=search['order_status'])
    if search.get('payment_status') in valid_payment_status:
        qs = qs.filter(payment_status=search['payment_status'])
    if search.get('fulfillment_type') in valid_fulfillment:
        qs = qs.filter(fulfillment_type=search['fulfillment_type'])
    if search.get('cash_issue') == 'abnormal':
        qs = qs.exclude(cash_shortfall_status='')

    qs = _apply_keyword_filter(qs, search.get('q', ''))
    return list(qs.order_by('-created_at')[:ORDER_LIST_LIMIT])
