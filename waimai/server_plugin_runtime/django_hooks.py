# 整机私人插件：在 settings 阶段挂入 Django（INSTALLED_APPS / MIDDLEWARE）
# 主程序只认「服务器插件运行时」，不在 settings 里写死私人包中间件类名。

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Sequence

logger = logging.getLogger('waimai')


def apply_server_plugins_to_django(
    installed_apps: Sequence[str],
    middleware: Sequence[str],
    *,
    enabled: bool,
    toolkit_path: str | Path,
) -> tuple[list[str], list[str]]:
    """
    把已启用的整机私人插件挂进 Django 应用与中间件列表。
    须在 settings 里 INSTALLED_APPS / MIDDLEWARE 定稿前调用；
    开关与路径由 settings 显式传入，避免加载 settings 时循环读 conf。
    """
    apps = list(installed_apps)
    mws = list(middleware)

    if not enabled:
        return apps, mws

    path = Path(toolkit_path)
    if not path.is_dir():
        logger.warning('已开启私人工具包插件，但目录不存在：%s', path)
        return apps, mws

    root = str(path.parent)
    if root not in sys.path:
        sys.path.insert(0, root)

    app_label = 'owner_toolkit.apps.OwnerToolkitConfig'
    if app_label not in apps and 'owner_toolkit' not in apps:
        apps.append(app_label)

    mw_paths: list[str] = []
    try:
        from owner_toolkit.plugin import OwnerToolkitPlugin

        plugin = OwnerToolkitPlugin()
        raw = plugin.middleware_classes()
        mw_paths = list(raw or [])
    except Exception as exc:
        logger.warning('读取私人工具包中间件声明失败：%s', exc)

    for mw in mw_paths:
        if mw and mw not in mws:
            if 'django.middleware.clickjacking.XFrameOptionsMiddleware' in mws:
                idx = mws.index('django.middleware.clickjacking.XFrameOptionsMiddleware')
                mws.insert(idx, mw)
            else:
                mws.append(mw)

    return apps, mws
