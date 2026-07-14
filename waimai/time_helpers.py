# 全站时间展示：统一转为北京时间（Asia/Shanghai）后再格式化

from django.utils import timezone


def to_beijing(dt):
    """把数据库里的时间转成北京时间（settings.TIME_ZONE = Asia/Shanghai）"""
    if not dt:
        return None
    return timezone.localtime(dt)


def format_beijing_time(dt, time_fmt='%H:%M', show_date_when_not_today=True):
    """
    格式化为北京时间字符串。
    默认只显示「时:分」；若时间不是今天，则带上「月-日」避免跨天误解。
    """
    local_dt = to_beijing(dt)
    if not local_dt:
        return ''
    if show_date_when_not_today:
        now_local = timezone.localtime(timezone.now())
        if local_dt.date() != now_local.date():
            return local_dt.strftime(f'%m-%d {time_fmt}')
    return local_dt.strftime(time_fmt)
