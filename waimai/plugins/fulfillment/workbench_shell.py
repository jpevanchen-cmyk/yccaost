# 履约插件：只挂「配送」页签；中性用语已在主体壳，饮食可另盖「骑手」话术

from __future__ import annotations


def contribute_fulfillment_workbench_shell(seller_id: str) -> dict:
    """履约开启时挂上配送页签（不覆盖饮食的骑手话术）。"""
    return {
        'enabled_views': ['rider'],
    }
