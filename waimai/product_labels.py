# 商品与店铺规则：卖家表单与客人页共用的中文标签（正本，改一处两边同步）

DISH_LIMIT_LABELS = {
    'member_daily_limit': '单日限购',
    'member_total_limit': '累计限购',
    'special_per_dish_limit': '本特价商品每人限购',
}

SHOP_SPECIAL_LABELS = {
    'special_max_per_user': '每人特价合计上限',
    'special_pool_code': '特价活动代码',
}

SHOP_HINT_LABELS = {
    'login_required_buyer': '须登录本店买家账号购买',
    'menu_sales_cap': '今日菜单可售',
    'menu_sales_cap_shared': '（各价格档共享）',
    'activity_prefix': '活动',
}


def dish_limit_label(field_key: str) -> str:
    """商品限购字段在表单/客人页上的名称"""
    return DISH_LIMIT_LABELS[field_key]


def shop_special_label(field_key: str) -> str:
    """全店特价规则字段名称"""
    return SHOP_SPECIAL_LABELS[field_key]


def shop_hint_label(key: str) -> str:
    """客人页固定说明用语"""
    return SHOP_HINT_LABELS[key]


def format_quantity_hint(label: str, quantity: int, unit: str = '份') -> str:
    """标签 + 数量 + 单位，供店铺页购买说明使用"""
    return f'{label} {quantity} {unit}'


def format_dish_limit_hint(field_key: str, quantity: int, unit: str = '份') -> str:
    """用商品管理同款标签拼限购说明"""
    return format_quantity_hint(dish_limit_label(field_key), quantity, unit)


def format_shop_special_limit_hint(field_key: str, quantity: int) -> str:
    """用全店特价规则同款标签拼上限说明"""
    return format_quantity_hint(shop_special_label(field_key), quantity)
