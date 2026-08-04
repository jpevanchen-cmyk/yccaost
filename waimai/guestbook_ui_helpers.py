# 留言板：提交结果与页面提示文案（全站共用这一处，避免前后端各写一套）

from __future__ import annotations

# 提交 / 弹窗结果类型
RESULT_OK = 'ok'
RESULT_OK_NO_EMAIL = 'ok_no_email'
RESULT_DUPLICATE = 'duplicate'
RESULT_RATE_LIMITED = 'rate_limited'
RESULT_EMAIL_FAILED = 'email_failed'


def _hourly_max_text() -> str:
    from .email_rate_limit_helpers import _recipient_hourly_max

    return str(_recipient_hourly_max())


def guestbook_rate_limit_detail() -> str:
    """防刷上限说明（含每小时上限数字）"""
    return (
        f'同一邮箱每小时最多收 {_hourly_max_text()} 封通知。'
        '留言板可正常使用（凭编号查看与继续留言）；邮件通知通常约 1 小时内恢复。'
    )


def guestbook_submit_result_ui(result_type: str, *, duplicate: bool = False) -> dict:
    """Ajax 提交成功弹窗：标题 + 说明"""
    if duplicate or result_type == RESULT_DUPLICATE:
        return {
            'title': '您已提交过',
            'message': '相同内容刚才已提交，请使用下方编号查看，无需重复提交。',
            'level': 'ok',
        }
    mapping = {
        RESULT_OK: (
            '留言已提交',
            '收条邮件已发送到您的邮箱，请同时复制保存留言编号。',
            'ok',
        ),
        RESULT_OK_NO_EMAIL: (
            '留言已提交',
            '请复制保存留言编号，以便日后查看回复。',
            'ok',
        ),
        RESULT_RATE_LIMITED: (
            '留言已保存',
            '您的留言或邮件通知较频繁，暂时无法向该邮箱发送通知。'
            + guestbook_rate_limit_detail(),
            'warn',
        ),
        RESULT_EMAIL_FAILED: (
            '留言已保存，邮件未发出',
            '收条邮件未能发出，可能是邮箱地址有误。'
            '请用下方编号打开留言记录，在页面中更新邮箱。留言板可正常使用。',
            'warn',
        ),
    }
    title, message, level = mapping.get(
        result_type,
        mapping[RESULT_OK_NO_EMAIL],
    )
    return {'title': title, 'message': message, 'level': level}


def thread_email_result_type(thread) -> str:
    """根据主题上的邮件状态字段，推断提交结果类型"""
    if getattr(thread, 'receipt_email_rate_limited', False):
        return RESULT_RATE_LIMITED
    if thread.receipt_email_failed or thread.email_delivery_suspect:
        return RESULT_EMAIL_FAILED
    if (thread.guest_email or '').strip():
        return RESULT_OK
    return RESULT_OK_NO_EMAIL


def guestbook_thread_page_ui(thread) -> dict:
    """
    编号打开页：顶部提示与是否显示改邮箱表单。
    防刷上限 ≠ 邮箱错误，文案与表单分开处理。
    """
    result_type = thread_email_result_type(thread)
    show_email_update = result_type == RESULT_EMAIL_FAILED
    notice = ''
    notice_level = ''

    if result_type == RESULT_RATE_LIMITED:
        notice = (
            '⚠ 您的留言或邮件通知较频繁，暂时无法向该邮箱发送邮件通知。'
            + guestbook_rate_limit_detail()
        )
        notice_level = 'warn'
    elif show_email_update:
        notice = (
            '⚠ 收条邮件可能未能送达该邮箱。'
            '请在下方更新联系邮箱或核对地址是否正确；留言板可正常使用。'
        )
        notice_level = 'warn'

    return {
        'notice': notice,
        'notice_level': notice_level,
        'show_email_update': show_email_update,
        'result_type': result_type,
    }


def guestbook_owner_thread_email_label(thread) -> str:
    """管理者列表/详情：邮件状态短标签"""
    if getattr(thread, 'receipt_email_rate_limited', False):
        return '邮件防刷上限'
    if thread.receipt_email_failed or thread.email_delivery_suspect:
        return '邮箱可疑'
    return ''
