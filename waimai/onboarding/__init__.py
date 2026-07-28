# 新版新手体验（独立模块 v2）
# 与 waimai/onboarding_*.py 旧版并行；旧版逻辑不删不改，本包逐步替换。

from .boot import build_experience_boot_payload, experience_shop_ready

__all__ = [
    'build_experience_boot_payload',
    'experience_shop_ready',
]
