# 留言对外编号：YC-MMDD-8位（数字+大小写字母，当天唯一）

from __future__ import annotations

import secrets
import string

from django.utils import timezone
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo('Asia/Shanghai')
_CODE_CHARS = string.ascii_letters + string.digits
_CODE_SUFFIX_LEN = 8
_CODE_PREFIX = 'YC-'


def _today_mmdd() -> str:
    return timezone.now().astimezone(BEIJING).strftime('%m%d')


def generate_public_code() -> str:
    """生成当天唯一的留言编号"""
    from .guestbook_models import GuestbookThread

    mmdd = _today_mmdd()
    prefix = f'{_CODE_PREFIX}{mmdd}-'
    for _ in range(80):
        suffix = ''.join(secrets.choice(_CODE_CHARS) for _ in range(_CODE_SUFFIX_LEN))
        code = f'{prefix}{suffix}'
        if not GuestbookThread.objects.filter(public_code=code).exists():
            return code
    raise RuntimeError('今日留言编号已用尽，请稍后再试')


def normalize_public_code(raw: str) -> str:
    """去掉首尾空格，统一大写前缀部分的可读性（编号区分大小写）"""
    return (raw or '').strip()


def is_valid_public_code_format(code: str) -> bool:
    text = normalize_public_code(code)
    if len(text) != len(_CODE_PREFIX) + 4 + 1 + _CODE_SUFFIX_LEN:
        return False
    if not text.startswith(_CODE_PREFIX):
        return False
    mmdd = text[len(_CODE_PREFIX):len(_CODE_PREFIX) + 4]
    if not mmdd.isdigit():
        return False
    if text[len(_CODE_PREFIX) + 4] != '-':
        return False
    suffix = text[len(_CODE_PREFIX) + 5:]
    if len(suffix) != _CODE_SUFFIX_LEN:
        return False
    return all(c in _CODE_CHARS for c in suffix)
