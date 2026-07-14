# 模板标签：商品/店铺共用中文标签（与 product_labels.py 正本一致）

from django import template

from ..product_labels import dish_limit_label as _dish_limit_label
from ..product_labels import shop_hint_label as _shop_hint_label
from ..product_labels import shop_special_label as _shop_special_label

register = template.Library()


@register.simple_tag
def dish_limit_label(field_key):
    """用法：{% dish_limit_label 'special_per_dish_limit' %}"""
    return _dish_limit_label(field_key)


@register.simple_tag
def shop_special_label(field_key):
    """用法：{% shop_special_label 'special_max_per_user' %}"""
    return _shop_special_label(field_key)


@register.simple_tag
def shop_hint_label(key):
    """用法：{% shop_hint_label 'login_required_buyer' %}"""
    return _shop_hint_label(key)
