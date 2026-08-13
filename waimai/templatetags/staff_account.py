from django import template

from waimai.staff_account_helpers import (
    attendance_account_type_label,
    staff_display_username,
    staff_job_title,
    staff_permission_lock_payload,
    staff_role_label,
)

register = template.Library()


@register.filter
def staff_display(username):
    """员工列表里显示工牌短名"""
    return staff_display_username(username)


@register.filter
def staff_role(value):
    """岗位代码转中文"""
    return staff_role_label(value)


@register.filter
def staff_title(user):
    """店铺员工显示店主自填职务名。"""
    return staff_job_title(user)


@register.filter
def staff_account_type(value):
    """考勤快照显示管理职务 / 普通员工。"""
    return attendance_account_type_label(value)


@register.simple_tag
def staff_perm_lock_data(seller_id):
    """勾选页锁定规则（业务权限连带订单台项）。"""
    return staff_permission_lock_payload(seller_id)
