# 新版新手体验：全站模板上下文（与旧 onboarding_boot 并行）

from __future__ import annotations

import json

from .boot import build_experience_boot_payload, should_inject_experience_boot
from .official_shop import OFFICIAL_SHOP_NAME, official_shop_ready


def experience_boot(request):
    """在 ?exp=1 或 /experience/ 下注入新版 boot；其它页面不注入"""
    if not should_inject_experience_boot(request):
        return {'experience_boot_json': ''}
    if not official_shop_ready():
        return {'experience_boot_json': ''}
    boot = build_experience_boot_payload()
    return {
        'experience_boot_json': json.dumps(boot, ensure_ascii=False),
        'experience_enabled': True,
        'experience_official_shop_name': boot['officialShopName'],
    }
