from django import template

from waimai.staff_account_helpers import staff_display_username, staff_role_label

register = template.Library()


@register.filter
def staff_display(username):
    """员工列表里显示工牌短名"""
    return staff_display_username(username)


@register.filter
def staff_role(value):
    """岗位代码转中文"""
    return staff_role_label(value)
