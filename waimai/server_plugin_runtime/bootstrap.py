# 启动时装入服务器拥有者私人插件（默认关闭；本体目录可不进公开 Git）

from __future__ import annotations

import logging
import sys
from pathlib import Path

from django.conf import settings

logger = logging.getLogger('waimai')


def is_owner_toolkit_enabled() -> bool:
    return bool(getattr(settings, 'YECAO_OWNER_TOOLKIT_ENABLED', False))


def bootstrap_server_plugins() -> None:
    """
    若开启 YECAO_OWNER_TOOLKIT_ENABLED 且目录存在，则加载 owner_toolkit。
    重复调用安全。
    """
    if not is_owner_toolkit_enabled():
        return
    toolkit_path = Path(getattr(settings, 'YECAO_OWNER_TOOLKIT_PATH', ''))
    if not toolkit_path.is_dir():
        logger.warning('已开启私人工具包，但目录不存在：%s', toolkit_path)
        return

    root = str(toolkit_path.parent)
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from owner_toolkit.plugin import register_owner_toolkit
    except ImportError as exc:
        logger.warning('无法加载 owner_toolkit：%s', exc)
        return

    register_owner_toolkit()
