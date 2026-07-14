# 支付插头基类：每种支付方式实现同一套动作

from dataclasses import dataclass
from typing import Optional


@dataclass
class PayMethodOption:
    """买家支付页上的一种支付方式"""

    code: str
    label: str
    description: str = ''
    enabled: bool = False
    coming_soon: bool = False
    hint: str = ''


@dataclass
class PaymentInitResult:
    """发起支付后的结果"""

    ok: bool
    message: str = ''
    redirect_url: Optional[str] = None
    template_name: Optional[str] = None
    extra_context: Optional[dict] = None
