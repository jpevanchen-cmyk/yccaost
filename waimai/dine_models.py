# A.11 堂食：营业、桌台、菜单清单（数据模型）

import secrets
import uuid

from django.db import models


def _new_qr_token():
    """桌码/虚拟码 URL 用短令牌"""
    return secrets.token_urlsafe(12)


class ShopOperatingSettings(models.Model):
    """店铺营业与堂食设置（A.11.1 + A.11.2 拼桌开关）"""

    SHARE_MODE_CHOICES = [
        ('', '未开启拼桌'),
        ('waiter', '模式 A · 服务员拼桌单'),
        ('virtual', '模式 B · 虚拟桌码自助'),
    ]
    DELIVERY_HANDOFF_CHOICES = [
        ('waiter', '服务员交给骑手'),
        ('kitchen', '后厨直接交给骑手'),
    ]
    ATTENDANCE_RETENTION_CHOICES = [
        ('30', '保留 30 天'),
        ('90', '保留 90 天'),
        ('180', '保留 180 天'),
        ('365', '保留 1 年'),
        ('forever', '长期保留'),
    ]

    seller_id = models.CharField(max_length=64, primary_key=True, verbose_name='店铺账号ID')
    business_open = models.TimeField(default='09:00', verbose_name='全天营业开始')
    business_close = models.TimeField(default='22:00', verbose_name='全天营业结束')
    dine_open = models.TimeField(blank=True, null=True, verbose_name='堂食接单开始（空=同全天）')
    dine_close = models.TimeField(blank=True, null=True, verbose_name='堂食接单结束')
    delivery_open = models.TimeField(blank=True, null=True, verbose_name='外卖接单开始')
    delivery_close = models.TimeField(blank=True, null=True, verbose_name='外卖接单结束')
    dine_channel_enabled = models.BooleanField(default=True, verbose_name='当前堂食接单开')
    delivery_channel_enabled = models.BooleanField(default=True, verbose_name='当前外卖接单开')
    delivery_handoff_mode = models.CharField(
        max_length=16,
        choices=DELIVERY_HANDOFF_CHOICES,
        default='waiter',
        verbose_name='外卖交接方式',
    )
    auto_dispatch_enabled = models.BooleanField(default=True, verbose_name='开启自动派单')
    attendance_retention_days = models.CharField(
        max_length=16,
        choices=ATTENDANCE_RETENTION_CHOICES,
        default='90',
        verbose_name='考勤记录保留时长',
    )
    closed_for_today = models.BooleanField(default=False, verbose_name='本日打烊')
    pause_new_orders = models.BooleanField(default=False, verbose_name='暂停接单')
    share_table_enabled = models.BooleanField(default=False, verbose_name='开启拼桌')
    share_table_mode = models.CharField(
        max_length=16, choices=SHARE_MODE_CHOICES, blank=True, default='',
        verbose_name='拼桌模式',
    )
    table_rules_acknowledged = models.BooleanField(default=False, verbose_name='已确认桌码硬规则')
    share_rules_confirmed = models.BooleanField(default=False, verbose_name='已确认拼桌硬规则')
    restrict_same_device = models.BooleanField(default=False, verbose_name='同桌仅允许同一设备下单')
    active_menu_profile = models.ForeignKey(
        'MenuProfile', on_delete=models.SET_NULL,
        blank=True, null=True, related_name='+', verbose_name='当前菜单清单',
    )
    special_pool_code = models.CharField(
        max_length=32, blank=True, default='', verbose_name='特价活动代码',
    )
    special_max_per_user = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='每用户特价合计上限（全店）',
    )
    special_pool_code = models.CharField(
        max_length=32, blank=True, default='', verbose_name='特价活动代码（本店识别用）',
    )
    special_max_per_user = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='每人特价合计上限（全店所有特价菜）',
    )

    class Meta:
        db_table = 'shop_operating_settings'
        verbose_name = '店铺营业设置'
        verbose_name_plural = '店铺营业设置'

    def __str__(self):
        return f'{self.seller_id} 营业设置'


class ShopTable(models.Model):
    """实体桌台与桌码（A.11.2）"""

    table_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='店铺ID')
    table_number = models.CharField(max_length=32, verbose_name='桌号')
    qr_token = models.CharField(max_length=32, unique=True, default=_new_qr_token, verbose_name='桌码令牌')
    is_active = models.BooleanField(default=True, verbose_name='启用')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'shop_table'
        unique_together = [('seller_id', 'table_number')]
        ordering = ['table_number']
        verbose_name = '餐桌'
        verbose_name_plural = '餐桌'

    def __str__(self):
        return f'桌 {self.table_number}'


class VirtualTableCode(models.Model):
    """虚拟桌码池（拼桌模式 B）"""

    code_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='店铺ID')
    code_label = models.CharField(max_length=32, verbose_name='虚拟码编号')
    qr_token = models.CharField(max_length=32, unique=True, default=_new_qr_token, verbose_name='扫码令牌')
    is_active = models.BooleanField(default=True, verbose_name='启用')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'virtual_table_code'
        unique_together = [('seller_id', 'code_label')]
        ordering = ['code_label']
        verbose_name = '虚拟桌码'
        verbose_name_plural = '虚拟桌码'

    def __str__(self):
        return self.code_label


class TableSession(models.Model):
    """桌台扫码会话：一桌一主单（A.11.2 硬规则 1）"""

    SESSION_TYPE_CHOICES = [
        ('main', '桌码主单'),
        ('share_waiter', '服务员拼桌单'),
        ('virtual', '虚拟拼桌'),
    ]
    STATUS_CHOICES = [
        ('open', '进行中'),
        ('closed', '已结束'),
    ]

    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='店铺ID')
    shop_table = models.ForeignKey(
        ShopTable, on_delete=models.SET_NULL, blank=True, null=True,
        related_name='sessions', verbose_name='实体桌',
    )
    virtual_code = models.ForeignKey(
        VirtualTableCode, on_delete=models.SET_NULL, blank=True, null=True,
        related_name='sessions', verbose_name='虚拟桌码',
    )
    session_type = models.CharField(max_length=16, choices=SESSION_TYPE_CHOICES, verbose_name='会话类型')
    share_label = models.CharField(max_length=64, blank=True, default='', verbose_name='拼桌单号')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='open', db_index=True)
    device_key = models.CharField(max_length=64, blank=True, default='', verbose_name='设备标识')
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'table_session'
        ordering = ['-opened_at']
        verbose_name = '桌台会话'
        verbose_name_plural = '桌台会话'

    def display_label(self):
        if self.share_label:
            return self.share_label
        if self.shop_table:
            return f'桌{self.shop_table.table_number}'
        if self.virtual_code:
            return f'虚拟{self.virtual_code.code_label}'
        return '堂食'


class MenuProfile(models.Model):
    """每日菜单清单（A.11.4）"""

    profile_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='店铺ID')
    name = models.CharField(max_length=100, verbose_name='清单名称')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'menu_profile'
        ordering = ['-updated_at']
        verbose_name = '菜单清单'
        verbose_name_plural = '菜单清单'
        constraints = [
            models.UniqueConstraint(
                fields=['seller_id', 'name'],
                name='uniq_menu_profile_name_per_seller',
            ),
        ]

    def __str__(self):
        return self.name


class MenuProfileItem(models.Model):
    """菜单清单内的一条商品（含本清单可售上限）"""

    item_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(MenuProfile, on_delete=models.CASCADE, related_name='items')
    dish = models.ForeignKey('Dish', on_delete=models.CASCADE, related_name='menu_items')
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    is_listed = models.BooleanField(default=True, verbose_name='本清单上架')
    member_price_listed = models.BooleanField(
        default=False, verbose_name='本清单展示会员价',
    )
    special_price_listed = models.BooleanField(
        default=False, verbose_name='本清单展示特价',
    )
    sales_cap = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='本清单可售上限（空=不限）',
    )
    sold_count = models.PositiveIntegerField(default=0, verbose_name='本清单已售数量')

    class Meta:
        db_table = 'menu_profile_item'
        unique_together = [('profile', 'dish')]
        ordering = ['sort_order', 'dish__name']
        verbose_name = '菜单清单条目'
        verbose_name_plural = '菜单清单条目'
