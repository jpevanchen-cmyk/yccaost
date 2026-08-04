# 待派单池展示：地址隐私模糊 + 预计可取餐/送达（预估）
# 接单前只展示大概信息；完整地址在生成配送单后可见。

from __future__ import annotations

import re
from datetime import datetime, timedelta

from django.utils import timezone

from .order_timeline_helpers import compute_wait_display

# 手机号（11 位）
_PHONE_RE = re.compile(r'1\d{10}')
# 常见门牌/楼栋/单元
_DETAIL_PATTERNS = (
    (re.compile(r'\d+号'), '***号'),
    (re.compile(r'\d+栋'), '***栋'),
    (re.compile(r'\d+单元'), '***单元'),
    (re.compile(r'\d+室'), '***室'),
    (re.compile(r'\d+层'), '***层'),
    (re.compile(r'\d+楼'), '***楼'),
    (re.compile(r'\d+-\d+'), '***'),
)
# 小区/社区名标记（保留前若干字 + 标记）
_COMMUNITY_MARKERS = ('小区', '花园', '苑', '公寓', '里', '村', '大厦', '广场')


def blur_address_for_dispatch_preview(raw: str) -> str:
    """
    待派单池/接单前：保留区街或小区大概，模糊门牌、单元、手机号等。
    """
    text = (raw or '').strip()
    if not text:
        return '（地址未填写）'
    if text in ('默认地址',):
        return '默认地址（详情接单后可见）'

    text = _PHONE_RE.sub('***', text)
    for pattern, repl in _DETAIL_PATTERNS:
        text = pattern.sub(repl, text)

    for marker in _COMMUNITY_MARKERS:
        idx = text.find(marker)
        if idx > 2:
            keep = min(4, idx)
            text = text[:keep] + '…' + text[idx:]
            break

    if len(text) > 28:
        text = text[:28] + '…'
    return text


def build_pending_ready_wait_display(order, *, now=None) -> dict | None:
    """待派单池 · 预计可取餐（订单 estimated_ready_at）。"""
    if not order.estimated_ready_at:
        return None
    display = compute_wait_display(order.estimated_ready_at, now=now)
    if not display:
        return None
    display = dict(display)
    display['label'] = '预计可取餐'
    return display


def estimate_pending_delivery_deadline(order, *, now=None) -> datetime | None:
    """待派单池 · 预计送达预估 = 预计可取餐 + 店铺外卖默认等待分钟。"""
    if not order.estimated_ready_at:
        return None
    from waimai.plugins.dining.wait_time_helpers import resolve_wait_minutes

    at = order.estimated_ready_at
    minutes = resolve_wait_minutes(order.seller_id, 'delivery', at=at)
    return at + timedelta(minutes=minutes)


def build_pending_delivery_wait_display(order, *, now=None) -> dict | None:
    """待派单池 · 预计送达（预估，开始送餐后以系统精确计时为准）。"""
    deadline = estimate_pending_delivery_deadline(order, now=now)
    if not deadline:
        return None
    display = compute_wait_display(deadline, now=now)
    if not display:
        return None
    display = dict(display)
    display['label'] = '预计送达（预估）'
    return display


def enrich_pending_dispatch_order(order, *, shop_address: str = '') -> None:
    """给待派单池订单挂上展示用字段（模板直接读）。"""
    order.pending_pickup_address = blur_address_for_dispatch_preview(shop_address or '店铺取货点')
    order.pending_delivery_address = blur_address_for_dispatch_preview(order.delivery_address)
    order.pending_pickup_wait = build_pending_ready_wait_display(order)
    order.pending_delivery_wait = build_pending_delivery_wait_display(order)
