# 留言邮件：收条、回复通知、管理者新留言

from __future__ import annotations

import logging

logger = logging.getLogger('waimai')

KIND_GUESTBOOK_RECEIPT = 'guestbook_receipt'
KIND_GUESTBOOK_REPLY = 'guestbook_reply'
KIND_OWNER_GUESTBOOK = 'owner_guestbook'


def _mail_footer(public_code: str = '') -> str:
    """收条 / 回复通知共用 footer（只维护这一处）"""
    from .guestbook_helpers import guestbook_public_site_url, guestbook_search_hint_text

    site = guestbook_public_site_url()
    lines = ['']
    code = (public_code or '').strip()
    if code:
        lines.append(f'您的留言编号：{code}')
    lines.append(guestbook_search_hint_text())
    lines.append(f'主页地址：{site}')
    return '\n'.join(lines) + '\n'


def notify_guest_receipt_email(thread) -> str:
    """
    提交成功后给访客发收条邮件（含编号）。
    返回：sent / rate_limited / failed / skipped
    """
    email = (thread.guest_email or '').strip()
    code = (thread.public_code or '').strip()
    if not email or not code:
        return 'skipped'

    from waimai.email_rate_limit_helpers import recipient_send_block_reason

    dedupe_key = f'guestbook_receipt:{thread.thread_id}'
    block = recipient_send_block_reason(
        email, kind=KIND_GUESTBOOK_RECEIPT, dedupe_key=dedupe_key,
    )
    if block:
        return 'rate_limited'

    try:
        from waimai.email_helpers import is_email_ready, send_yecao_mail
    except ImportError:
        return 'failed'
    if not is_email_ready():
        return 'failed'

    name = (thread.guest_display_name or '').strip()
    hello = f'您好{name}：' if name else '您好：'
    subject = f'野草 · 留言已收到 · {code}'
    body = (
        f'{hello}\n\n'
        '我们已收到您在服务器主页的留言。\n'
        '请妥善保存下面的留言编号，用于查看回复与继续沟通。\n'
        f'{_mail_footer(code)}'
    )
    if thread.has_view_password:
        body += '您设置了查看密码，打开留言记录时需要输入。\n'
    else:
        body += '建议为留言设置查看密码，以免编号被他人看到时内容泄露。\n'

    if send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=[email],
        kind=KIND_GUESTBOOK_RECEIPT,
        dedupe_key=dedupe_key,
    ):
        return 'sent'
    return 'failed'


def notify_guest_on_owner_reply(thread, message) -> None:
    email = (thread.guest_email or '').strip()
    code = (thread.public_code or '').strip()
    if not email or message.author_side != 'owner':
        return
    try:
        from waimai.email_helpers import is_email_ready, send_yecao_mail
    except ImportError:
        return
    if not is_email_ready():
        return

    subject = '您在野草的留言有新回复'
    body = (
        f'您好{("，" + thread.guest_display_name) if thread.guest_display_name else ""}：\n\n'
        f'管理者回复：\n{message.body}\n'
        f'{_mail_footer(code)}'
    )

    if send_yecao_mail(
        subject=subject,
        message=body,
        recipient_list=[email],
        kind=KIND_GUESTBOOK_REPLY,
        dedupe_key=f'guestbook:{thread.thread_id}:msg:{message.message_id}',
    ):
        message.guest_notified = True
        message.save(update_fields=['guest_notified'])


def notify_manager_new_guestbook(thread, message) -> None:
    """通知管理者有新留言（优先走 owner_toolkit 通知设置）"""
    if getattr(message, 'author_side', '') != 'guest':
        return
    try:
        from owner_toolkit.owner_notify_helpers import notify_owner_new_guestbook

        notify_owner_new_guestbook(thread, message)
        return
    except ImportError:
        pass

    logger.debug('owner_toolkit 未加载，跳过管理者留言通知邮件')
