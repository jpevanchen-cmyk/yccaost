# 模板标签：页面上的时间一律按北京时间显示

from django import template
from django.utils.dateformat import format as django_date_format

from ..time_helpers import to_beijing

register = template.Library()


@register.filter(name='beijing')
def beijing_datetime(value, arg='m-d H:i'):
    """
    用法：{{ order.created_at|beijing:"m-d H:i" }}
    与 date 过滤器写法相同，但明确走北京时间转换，避免漏转时区。
    """
    if not value:
        return ''
    local_dt = to_beijing(value)
    if not local_dt:
        return ''
    return django_date_format(local_dt, arg)
