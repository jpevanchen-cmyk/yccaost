# 官方演示店：只读复用旧 helpers，不在本包重复实现

from __future__ import annotations

from waimai.onboarding_helpers import (
    OFFICIAL_SHOP_NAME,
    get_official_shop_profile,
    official_shop_ready,
)

__all__ = [
    'OFFICIAL_SHOP_NAME',
    'get_official_shop_profile',
    'official_shop_ready',
]
