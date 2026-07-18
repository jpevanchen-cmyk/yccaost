# 支付方式注册入口：对外仍用 build_buyer_pay_options
# 批次 D 起：通用在线通道在 core；饮食现金文案在 dining_bridge

from .dining_bridge import build_dining_buyer_pay_options


def build_buyer_pay_options(settings, order=None):
    """
    根据店铺配置与订单场景生成买家可选支付列表。
    当前接入方为饮食店；其它行业可另写 bridge，不必改 core。
    """
    return build_dining_buyer_pay_options(settings, order=order)
