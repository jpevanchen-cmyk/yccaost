# 模板标签：页面上的时间一律按系统本地时区显示（跟 settings.TIME_ZONE）

from django import template
from django.utils.dateformat import format as django_date_format

from ..time_helpers import to_local

register = template.Library()


@register.filter(name='local')
def local_datetime(value, arg='m-d H:i'):
    """
    用法：{{ order.created_at|local:"m-d H:i" }}
    转为系统本地时间后再按格式显示。
    """
    if not value:
        return ''
    local_dt = to_local(value)
    if not local_dt:
        return ''
    return django_date_format(local_dt, arg)
