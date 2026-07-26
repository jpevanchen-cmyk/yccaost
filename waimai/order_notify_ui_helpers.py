# H3：双轨邮件通知 · 界面共用提示

from __future__ import annotations


def smtp_not_ready_message(*enabled_flags: bool) -> str:
    """任一轨已开但服务器未配 SMTP 时，返回醒目白话提示。"""
    if not any(enabled_flags):
        return ''
    from .email_helpers import is_email_ready

    if is_email_ready():
        return ''
    return (
        '已开启邮件通知，但本服务器尚未配置发信邮箱，邮件暂时发不出去。'
        '请联系服务器管理者在「服务器设置 → 发信邮箱」里配置。'
    )
