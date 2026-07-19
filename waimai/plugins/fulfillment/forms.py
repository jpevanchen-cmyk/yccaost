# 履约包：卖家表单

from django import forms

from waimai.models import ShopDeliverySettings


class ShopDeliverySettingsForm(forms.ModelForm):
    """店铺配送费配置表单（归属履约插件）"""

    class Meta:
        model = ShopDeliverySettings
        fields = [
            'min_delivery_fee',
            'per_km_rate_0_3',
            'multiplier_3_6',
            'multiplier_6_9',
            'max_distance_km',
            'free_delivery_threshold',
            'discount_percent',
        ]
        labels = {
            'min_delivery_fee': '最低配送费（元）',
            'per_km_rate_0_3': '3公里内单价（元/公里）',
            'multiplier_3_6': '3～6公里倍数',
            'multiplier_6_9': '6～9公里倍数',
            'max_distance_km': '最远配送距离（公里）',
            'free_delivery_threshold': '满额免运门槛（元，可留空）',
            'discount_percent': '按订单金额减免上限（%）',
        }
