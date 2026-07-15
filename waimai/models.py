import re
import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .time_helpers import format_beijing_time
from .time_helpers import to_beijing


# ============================================
# 自定义用户模型（方向C：注册登录与权限）
# ============================================
class User(AbstractUser):
    ROLE_CHOICES = [
        ('buyer', '买家'),
        ('seller', '卖家'),
        ('rider', '骑手'),
        ('waiter', '服务员'),
        ('kitchen', '后厨'),
    ]
    STAFF_WORK_STATUS_CHOICES = [
        ('on_duty', '上班'),
        ('break', '休息'),
        ('off_duty', '下班'),
    ]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='buyer', verbose_name='用户身份')
    # 专属骑手所属店铺（卖家用户名）
    employer_seller_id = models.CharField(
        max_length=64, blank=True, null=True, db_index=True, verbose_name='所属店铺ID'
    )
    staff_work_status = models.CharField(
        max_length=16,
        default='off_duty',
        db_index=True,
        verbose_name='员工在岗状态',
        choices=STAFF_WORK_STATUS_CHOICES,
    )
    staff_work_status_updated_at = models.DateTimeField(
        blank=True, null=True, verbose_name='员工在岗状态更新时间'
    )
    # 体验机：体验账号每日清空；正式/官方相关账号保留
    is_experience = models.BooleanField(default=False, db_index=True, verbose_name='体验账号')
    is_permanent = models.BooleanField(default=False, db_index=True, verbose_name='正式保留账号')

    class Meta:
        db_table = 'user'
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class SiteComplianceSettings(models.Model):
    """整台服务器共用的备案展示设置；只允许服务器拥有者在管理后台维护。"""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False, verbose_name='固定编号'
    )
    icp_record_number = models.CharField(
        max_length=80,
        blank=True,
        default='',
        verbose_name='ICP备案号',
        help_text='请照工信部/备案服务商下发的完整号码填写，例如：闽ICP备XXXXXXXX号。',
    )
    police_record_number = models.CharField(
        max_length=80,
        blank=True,
        default='',
        verbose_name='公安联网备案号',
        help_text='审核通过后填写完整号码，例如：闽公网安备 XXXXXXXXXXXXXX号；未取得时留空。',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='最后更新时间')

    class Meta:
        db_table = 'site_compliance_settings'
        verbose_name = '网站合规信息'
        verbose_name_plural = '网站合规信息'

    def clean(self):
        self.icp_record_number = (self.icp_record_number or '').strip()
        self.police_record_number = (self.police_record_number or '').strip()
        if self.icp_record_number and 'ICP' not in self.icp_record_number.upper():
            raise ValidationError({'icp_record_number': '请填写完整的 ICP 备案号（号码中应包含“ICP”）。'})
        if self.police_record_number and not self.police_record_code:
            raise ValidationError({'police_record_number': '公安备案号中应包含平台下发的数字编号。'})

    def save(self, *args, **kwargs):
        # 整台服务器只保留一份；防止后台误建多份造成页脚显示不确定。
        self.singleton_id = 1
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def icp_query_url(self):
        return 'https://beian.miit.gov.cn/'

    @property
    def police_record_code(self):
        groups = re.findall(r'\d{6,20}', self.police_record_number or '')
        return max(groups, key=len) if groups else ''

    @property
    def police_query_url(self):
        code = self.police_record_code
        if not code:
            return ''
        return f'https://beian.mps.gov.cn/#/query/webSearch?code={code}'

    def __str__(self):
        return '本服务器网站合规信息'


class StaffAttendanceLog(models.Model):
    """员工状态变更流水：作为考勤基础留痕"""

    ACTION_CHOICES = [
        ('on_duty', '上班'),
        ('break', '休息'),
        ('off_duty', '下班'),
    ]
    SOURCE_CHOICES = [
        ('self', '员工本人'),
        ('manager', '老板补改'),
        ('system', '系统自动'),
    ]

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='记录ID')
    user = models.ForeignKey(
        'User', on_delete=models.SET_NULL, blank=True, null=True,
        related_name='attendance_logs', verbose_name='员工账号',
    )
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='店铺ID')
    username_snapshot = models.CharField(max_length=128, verbose_name='员工账号快照')
    display_name_snapshot = models.CharField(max_length=64, verbose_name='员工姓名快照')
    role_snapshot = models.CharField(max_length=16, verbose_name='岗位快照')
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, db_index=True, verbose_name='状态动作')
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default='self', verbose_name='操作来源')
    operator_username = models.CharField(max_length=128, blank=True, default='', verbose_name='操作人账号')
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发生时间')

    class Meta:
        db_table = 'staff_attendance_log'
        ordering = ['-changed_at']
        verbose_name = '员工考勤流水'
        verbose_name_plural = '员工考勤流水'

    def __str__(self):
        return f'{self.display_name_snapshot} {self.action}'


# ============================================
# 店铺注册信息（公共名录）
# ============================================
class ShopProfile(models.Model):
    SHOP_TYPE_CHOICES = [
        ('restaurant', '餐饮'),
        ('market', '超市'),
        ('other', '其他'),
    ]

    seller_id = models.CharField(max_length=64, primary_key=True, verbose_name='店铺账号ID')
    shop_name = models.CharField(max_length=100, verbose_name='店铺名称')
    shop_code = models.CharField(
        max_length=32, blank=True, default='', unique=True, db_index=True,
        verbose_name='店铺码（开店自动生成，仅合并登记可改）',
    )
    shop_type = models.CharField(max_length=20, choices=SHOP_TYPE_CHOICES, default='restaurant', verbose_name='店铺类型')
    address = models.TextField(verbose_name='店铺地址')
    is_listed = models.BooleanField(default=True, db_index=True, verbose_name='在名录中展示')
    registered_at = models.DateTimeField(auto_now_add=True, verbose_name='注册时间')
    # 体验机：官方小店不占体验额度、不日清、可真支付
    is_official = models.BooleanField(default=False, db_index=True, verbose_name='官方小店')

    class Meta:
        db_table = 'shop_profile'
        verbose_name = '店铺注册信息'
        verbose_name_plural = '店铺注册信息'

    def __str__(self):
        return self.shop_name


class ShopHomePage(models.Model):
    """服务器拥有者入口展示主页配置（一店一份；可标为整机默认入口）"""

    ORDER_NAV_CHOICES = [
        ('to_shop', '导航「点餐」直接进点菜页'),
        ('to_cta_block', '导航「点餐」滚到页内开始点餐块'),
    ]

    seller_id = models.CharField(max_length=64, primary_key=True, verbose_name='店铺账号ID')
    is_server_entry = models.BooleanField(
        default=False, db_index=True,
        verbose_name='是否本服务器默认入口主页',
    )
    order_nav_mode = models.CharField(
        max_length=16, choices=ORDER_NAV_CHOICES, default='to_shop',
        verbose_name='顶栏点餐行为',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'shop_home_page'
        verbose_name = '展示主页'
        verbose_name_plural = '展示主页'

    def __str__(self):
        return f'主页:{self.seller_id}'


class ShopHomeBlock(models.Model):
    """展示主页上的一个积木块（预设类型 + 拥有者填写的内容）"""

    block_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='块ID')
    home_page = models.ForeignKey(
        ShopHomePage, on_delete=models.CASCADE, related_name='blocks', verbose_name='所属主页',
    )
    block_type = models.CharField(max_length=32, db_index=True, verbose_name='块类型')
    title = models.CharField(max_length=120, blank=True, default='', verbose_name='标题')
    body = models.TextField(blank=True, default='', verbose_name='正文')
    image_url = models.CharField(max_length=500, blank=True, default='', verbose_name='图片链接')
    link_url = models.CharField(max_length=500, blank=True, default='', verbose_name='附加链接')
    nav_label = models.CharField(max_length=32, blank=True, default='', verbose_name='导航短名')
    is_enabled = models.BooleanField(default=False, db_index=True, verbose_name='是否启用')
    show_in_nav = models.BooleanField(default=True, verbose_name='是否出现在吸顶导航')
    sort_order = models.PositiveIntegerField(default=100, db_index=True, verbose_name='排序')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'shop_home_block'
        ordering = ['sort_order', 'block_type']
        verbose_name = '展示主页积木块'
        verbose_name_plural = '展示主页积木块'
        constraints = [
            models.UniqueConstraint(fields=['home_page', 'block_type'], name='uniq_home_block_type'),
        ]

    def __str__(self):
        return f'{self.block_type}:{self.title}'


# ============================================
# 店铺配送费配置
# ============================================
class ShopDeliverySettings(models.Model):
    seller_id = models.CharField(max_length=64, primary_key=True, verbose_name='店铺账号ID')
    min_delivery_fee = models.DecimalField(
        max_digits=6, decimal_places=2, default=3.00, verbose_name='最低配送费（元）'
    )
    per_km_rate_0_3 = models.DecimalField(
        max_digits=6, decimal_places=2, default=2.00, verbose_name='3公里内基础单价（元/公里）'
    )
    multiplier_3_6 = models.DecimalField(
        max_digits=4, decimal_places=2, default=1.50, verbose_name='3～6公里倍数'
    )
    multiplier_6_9 = models.DecimalField(
        max_digits=4, decimal_places=2, default=2.00, verbose_name='6～9公里倍数'
    )
    max_distance_km = models.DecimalField(
        max_digits=4, decimal_places=1, default=9.0, verbose_name='最远配送距离（公里）'
    )
    free_delivery_threshold = models.DecimalField(
        max_digits=8, decimal_places=2, default=30.00, blank=True, null=True,
        verbose_name='满额免运门槛（元，留空表示不启用）'
    )
    discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        verbose_name='按订单金额比例减免上限（%）'
    )

    class Meta:
        db_table = 'shop_delivery_settings'
        verbose_name = '店铺配送费配置'
        verbose_name_plural = '店铺配送费配置'

    def __str__(self):
        return f"{self.seller_id} 配送费配置"


# ============================================
# 菜品表
# ============================================
class Dish(models.Model):
    """商品（菜品）：通用价 + 可选会员价、特价"""

    PRICE_MODE_CHOICES = [
        ('percent', '按通用价百分比'),
        ('fixed', '直接填价格'),
    ]
    PRICE_TIER_GENERAL = 'general'
    PRICE_TIER_MEMBER = 'member'
    PRICE_TIER_SPECIAL = 'special'

    dish_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='菜品ID')
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='卖家ID')
    name = models.CharField(max_length=100, db_index=True, verbose_name='菜品名称')
    price = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(0.01)],
        verbose_name='通用价格（元）',
    )
    image_url = models.URLField(max_length=500, blank=True, null=True, verbose_name='菜品图片链接')
    description = models.TextField(blank=True, verbose_name='菜品描述')
    stock = models.PositiveIntegerField(default=999, verbose_name='库存数量')
    is_active = models.BooleanField(default=True, db_index=True, verbose_name='上架状态')
    sort_order = models.IntegerField(default=0, verbose_name='排序')
    # 会员价
    member_price_enabled = models.BooleanField(default=False, verbose_name='启用会员价')
    member_price_mode = models.CharField(
        max_length=16, choices=PRICE_MODE_CHOICES, default='percent', verbose_name='会员价计算方式',
    )
    member_price_fixed = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True, verbose_name='会员价（直接填）',
    )
    member_price_percent = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True, verbose_name='会员价（通用价百分比）',
    )
    member_daily_limit = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='会员价单日限购（空=不限）',
    )
    member_total_limit = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='会员价累计限购（空=不限）',
    )
    # 特价
    special_price_enabled = models.BooleanField(default=False, verbose_name='启用特价')
    special_price_mode = models.CharField(
        max_length=16, choices=PRICE_MODE_CHOICES, default='percent', verbose_name='特价计算方式',
    )
    special_price_fixed = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True, verbose_name='特价（直接填）',
    )
    special_price_percent = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True, verbose_name='特价（通用价百分比）',
    )
    special_per_dish_limit = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='本菜特价每人限购（空=不限）',
    )
    # 旧字段保留兼容，新逻辑不再使用
    require_registered = models.BooleanField(default=False, verbose_name='仅注册用户可买')
    new_member_only = models.BooleanField(default=False, verbose_name='仅新会员可买')
    max_per_user = models.PositiveIntegerField(
        blank=True, null=True, verbose_name='每人限购（空=不限）',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'dish'
        ordering = ['-created_at']
        verbose_name = '菜品'
        verbose_name_plural = '菜品'

    def __str__(self):
        return f"{self.name} - ¥{self.price}"


# ============================================
# 购买订单表
# ============================================
class BuyOrder(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('pending_payment', '待支付'),
        ('paid', '已支付'),
        ('uncollected', '未收款结案'),
        ('cancelled', '已取消'),
    ]
    ORDER_STATUS_CHOICES = [
        ('awaiting_payment', '待支付'),
        ('awaiting_shop_confirm', '待店家接单'),
        ('awaiting_prep', '待备货'),
        ('preparing', '商家备货中'),
        ('ready_pickup', '待取货'),
        ('delivering', '配送中'),
        ('completed', '已完成'),
        ('cancelled', '已取消'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('wechat_simulate', '微信扫码支付（模拟）'),
        ('wechat', '微信支付'),
        ('cash', '现金'),
        ('card', '信用卡/借记卡'),
    ]
    FULFILLMENT_TYPE_CHOICES = [
        ('delivery', '外卖'),
        ('dine_in', '堂食'),
        ('takeaway', '打包'),
    ]

    ORDER_KIND_CHOICES = [
        ('normal', '普通单'),
        ('table_main', '桌码主单'),
        ('share_waiter', '服务员拼桌单'),
        ('virtual', '虚拟拼桌单'),
    ]

    order_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='订单ID')
    buyer_id = models.CharField(max_length=64, db_index=True, verbose_name='买家ID')
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='卖家ID')
    total_amount = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0.01)], verbose_name='订单总金额（元）')
    subtotal_amount = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True, verbose_name='商品小计（元）'
    )
    delivery_fee = models.DecimalField(
        max_digits=6, decimal_places=2, blank=True, null=True, verbose_name='配送费（元）'
    )
    delivery_fee_detail = models.JSONField(blank=True, null=True, verbose_name='配送费计算明细')
    dish_items = models.JSONField(verbose_name='菜品明细')
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending_payment',
        db_index=True, verbose_name='支付状态'
    )
    order_status = models.CharField(
        max_length=24, choices=ORDER_STATUS_CHOICES, default='awaiting_payment',
        db_index=True, verbose_name='订单状态'
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True,
        verbose_name='支付渠道'
    )
    payment_time = models.DateTimeField(blank=True, null=True, verbose_name='支付时间')
    preparing_at = models.DateTimeField(blank=True, null=True, verbose_name='开始备货时间')
    estimated_ready_at = models.DateTimeField(blank=True, null=True, verbose_name='预计出餐/取餐时间')
    ready_at = models.DateTimeField(blank=True, null=True, verbose_name='出餐可配送时间')
    buyer_note = models.TextField(blank=True, verbose_name='买家备注')
    cash_uncollected_reason = models.TextField(blank=True, verbose_name='未收款结案原因')
    table_session = models.ForeignKey(
        'TableSession', on_delete=models.SET_NULL, blank=True, null=True,
        related_name='orders', verbose_name='桌台会话',
    )
    table_label = models.CharField(max_length=64, blank=True, default='', verbose_name='桌号/拼桌标识')
    order_kind = models.CharField(
        max_length=16, choices=ORDER_KIND_CHOICES, default='normal', verbose_name='订单类型',
    )
    delivery_address = models.TextField(verbose_name='配送地址')
    fulfillment_type = models.CharField(
        max_length=16,
        choices=FULFILLMENT_TYPE_CHOICES,
        default='delivery',
        db_index=True,
        verbose_name='取餐方式',
    )
    distance_km = models.DecimalField(max_digits=4, decimal_places=1, default=2.5, verbose_name='配送距离（公里）')
    vip_service = models.CharField(max_length=20, blank=True, null=True, choices=[('priority','优选推送'),('assigned','指定配送'),('urgent','加急配送')], verbose_name='增值服务类型')
    vip_service_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name='增值服务费（元）')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='下单时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    waiter_service_status = models.CharField(
        max_length=20,
        choices=[
            ('pending_serve', '待出餐'),
            ('served', '已上桌'),
            ('settled', '已结账'),
        ],
        blank=True,
        default='',
        db_index=True,
        verbose_name='前台服务状态',
    )

    class Meta:
        db_table = 'buy_order'
        ordering = ['-created_at']
        verbose_name = '购买订单'
        verbose_name_plural = '购买订单'

    def __str__(self):
        return f"订单{self.get_display_order_no()} - ¥{self.total_amount}"

    @staticmethod
    def _shop_code(seller_id: str) -> str:
        """取店铺资料中的店铺码（订单展示现查，见 A.13）"""
        return (
            ShopProfile.objects.filter(seller_id=seller_id)
            .values_list('shop_code', flat=True)
            .first() or ''
        )

    def get_order_short_code(self) -> str:
        """给人看的订单主体：沿用 UUID 前 8 位，便于短读短报。"""
        return self.order_id.hex[:8]

    def get_order_date_code(self) -> str:
        """给人看的日期码：北京时间 YYYYMMDD。"""
        local_dt = to_beijing(self.created_at)
        if not local_dt:
            return ''
        return local_dt.strftime('%Y%m%d')

    def get_display_order_no(self) -> str:
        """展示/搜索用订单号：短号-店铺码-日期；店铺码未启用时省略中段。"""
        parts = [self.get_order_short_code()]
        shop_code = self._shop_code(self.seller_id).strip()
        if shop_code:
            parts.append(shop_code)
        date_code = self.get_order_date_code()
        if date_code:
            parts.append(date_code)
        return '-'.join(parts)

    def get_subtotal(self):
        """商品小计（优先读下单时保存的值）"""
        if self.subtotal_amount is not None:
            return self.subtotal_amount
        from .order_helpers import subtotal_from_dish_items
        return subtotal_from_dish_items(self.dish_items)

    def get_delivery_fee_amount(self):
        """配送费（优先读下单时保存的值）"""
        if self.delivery_fee is not None:
            return self.delivery_fee
        return self.total_amount - self.get_subtotal()

    def is_cash_awaiting_confirm(self):
        """外卖货到付款：等待卖家确认收款后才备货"""
        return (
            self.fulfillment_type == 'delivery'
            and self.payment_status == 'pending_payment'
            and self.payment_method == 'cash'
        )

    def is_awaiting_in_store_order_confirm(self):
        """堂食/打包到店付：等待店家确认接单并开始备餐"""
        return (
            self.is_in_store()
            and self.payment_method == 'cash'
            and self.payment_status == 'pending_payment'
            and self.order_status in ('awaiting_payment', 'awaiting_shop_confirm')
        )

    def is_cash_receipt_pending(self):
        """堂食/打包到店付：备餐中但尚未确认已收款"""
        return (
            self.is_in_store()
            and self.payment_method == 'cash'
            and self.payment_status == 'pending_payment'
            and self.order_status in ('preparing', 'ready_pickup')
        )

    def can_complete_in_store_order(self):
        """到店单是否允许正常结束（须已收款）"""
        return (
            self.is_in_store()
            and self.order_status == 'ready_pickup'
            and self.payment_status == 'paid'
        )

    def can_close_as_uncollected(self):
        """是否可走「无法收款结单」例外流程"""
        return self.is_cash_receipt_pending() and self.order_status == 'ready_pickup'

    def is_in_store_cash_order(self):
        """是否堂食/打包且选择到店付现金"""
        return self.is_in_store() and self.payment_method == 'cash'

    def is_in_store(self):
        """是否到店服务（堂食或打包，不收配送费、不派骑手）"""
        return self.fulfillment_type in ('dine_in', 'takeaway')

    def is_dine_in(self):
        """是否堂食（在店内用餐）"""
        return self.fulfillment_type == 'dine_in'

    def is_takeaway(self):
        """是否打包（自取带走）"""
        return self.fulfillment_type == 'takeaway'

    def is_pickup(self):
        """兼容旧称：到店自取（堂食或打包）"""
        return self.is_in_store()

    def get_fulfillment_display_short(self):
        """取餐方式短文案"""
        return dict(self.FULFILLMENT_TYPE_CHOICES).get(self.fulfillment_type, self.fulfillment_type)

    def get_cash_payment_hint(self):
        """现金单给买家看的说明"""
        if self.is_awaiting_in_store_order_confirm():
            if self.is_dine_in():
                return '堂食订单已提交，等待店家确认接单。接单后将告知预计出餐时间，用餐时到店付现金即可。'
            return '打包订单已提交，等待店家确认接单。接单后将告知预计可取餐时间，取餐时到店付现金即可。'
        if self.is_cash_receipt_pending():
            if self.estimated_ready_at:
                t = format_beijing_time(self.estimated_ready_at)
                if self.is_dine_in():
                    return f'店家已接单，预计 {t} 可出餐。用餐时请付现金，店家确认收款后订单完结。'
                return f'店家已接单，预计 {t} 可取餐。取餐时请付现金，店家确认收款后订单完结。'
            if self.is_dine_in():
                return '店家已接单备餐中。用餐时请付现金。'
            return '店家已接单备货中。取餐时请付现金。'
        if self.is_dine_in():
            return '堂食订单：请在店内付款。'
        if self.is_takeaway():
            return '打包自取：请到店取餐并付款。'
        return '外卖货到付款：送达时付现金，店家确认收款后备货并派单。'

    def get_estimated_ready_label(self):
        """预计出餐/取餐时间的展示文案（北京时间）"""
        if not self.estimated_ready_at:
            return ''
        t = format_beijing_time(self.estimated_ready_at)
        if self.is_dine_in():
            return f'预计 {t} 可出餐'
        if self.is_takeaway():
            return f'预计 {t} 可取餐'
        return f'预计 {t} 可出餐'


# ============================================
# 店铺支付配置（各支付方式开关与微信参数）
# ============================================
class ShopPaymentSettings(models.Model):
    seller_id = models.CharField(max_length=64, primary_key=True, verbose_name='店铺账号ID')
    enable_simulate = models.BooleanField(default=True, verbose_name='开启模拟支付（演示用）')
    enable_wechat = models.BooleanField(default=False, verbose_name='开启微信支付')
    enable_cash = models.BooleanField(default=True, verbose_name='开启现金支付')
    is_showcase_shop = models.BooleanField(
        default=False, verbose_name='示范店模式',
        help_text='勾选后可在店铺说明中提示：可同时提供模拟与真微信供体验',
    )
    wechat_mch_id = models.CharField(max_length=32, blank=True, default='', verbose_name='微信商户号')
    wechat_app_id = models.CharField(max_length=32, blank=True, default='', verbose_name='微信 AppID')
    wechat_api_key = models.CharField(max_length=64, blank=True, default='', verbose_name='微信 APIv2 密钥')
    public_site_url = models.CharField(
        max_length=255, blank=True, default='',
        verbose_name='店铺公网网址',
        help_text='如 https://你的域名.com ，用于拼微信异步通知地址；无公网时可先留空，用轮询查单',
    )

    class Meta:
        db_table = 'shop_payment_settings'
        verbose_name = '店铺支付配置'
        verbose_name_plural = '店铺支付配置'

    def __str__(self):
        return f"{self.seller_id} 支付配置"

    def wechat_config_ready(self):
        """微信商户参数是否已填齐（可发起真支付）"""
        return bool(
            self.enable_wechat
            and self.wechat_mch_id.strip()
            and self.wechat_app_id.strip()
            and self.wechat_api_key.strip()
        )


# ============================================
# 支付流水（微信等在线支付的单笔记录）
# ============================================
class PaymentRecord(models.Model):
    STATUS_CHOICES = [
        ('pending', '待支付'),
        ('success', '支付成功'),
        ('failed', '失败'),
        ('closed', '已关闭'),
    ]

    record_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='流水ID')
    buy_order = models.ForeignKey(
        BuyOrder, on_delete=models.CASCADE, related_name='payment_records', verbose_name='关联订单',
    )
    payment_method = models.CharField(max_length=32, verbose_name='支付渠道')
    out_trade_no = models.CharField(max_length=32, unique=True, db_index=True, verbose_name='商户订单号')
    amount = models.DecimalField(max_digits=8, decimal_places=2, verbose_name='金额（元）')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default='pending', db_index=True, verbose_name='流水状态',
    )
    code_url = models.TextField(blank=True, default='', verbose_name='微信扫码链接')
    provider_trade_no = models.CharField(
        max_length=64, blank=True, default='', verbose_name='支付平台交易号',
    )
    notify_payload = models.JSONField(blank=True, null=True, verbose_name='回调原始数据')
    paid_at = models.DateTimeField(blank=True, null=True, verbose_name='支付成功时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'payment_record'
        ordering = ['-created_at']
        verbose_name = '支付流水'
        verbose_name_plural = '支付流水'

    def __str__(self):
        return f"{self.out_trade_no} ({self.get_status_display()})"


class DeliveryOrder(models.Model):
    STATUS_CHOICES = [
        ('waiting', '待派单'),
        ('accepted', '待取餐'),
        ('picked_up', '已取餐'),
        ('in_transit', '配送中'),
        ('completed', '已送达'),
        ('overtime', '超时未送达'),
        ('cancelled', '已取消'),
    ]

    delivery_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='配送单ID')
    buy_order = models.OneToOneField(BuyOrder, on_delete=models.CASCADE, related_name='delivery_order', verbose_name='关联购买订单')
    rider_id = models.CharField(max_length=64, blank=True, null=True, db_index=True, verbose_name='接单骑手ID')
    delivery_fee = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(0)], verbose_name='配送费（元）')
    distance_km = models.DecimalField(max_digits=4, decimal_places=1, verbose_name='配送距离（公里）')
    pickup_address = models.TextField(verbose_name='取餐地址')
    delivery_address = models.TextField(verbose_name='送达地址')
    delivery_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting', db_index=True, verbose_name='配送状态')
    accepted_at = models.DateTimeField(blank=True, null=True, verbose_name='接单时间')
    picked_up_at = models.DateTimeField(blank=True, null=True, verbose_name='取餐时间')
    completed_at = models.DateTimeField(blank=True, null=True, verbose_name='送达时间')
    estimated_delivery_time = models.DateTimeField(blank=True, null=True, verbose_name='预计送达时间')
    is_on_time = models.BooleanField(default=None, blank=True, null=True, verbose_name='是否准时送达')
    is_payout_triggered = models.BooleanField(default=False, verbose_name='是否已触发分账')
    has_vip_service = models.CharField(max_length=20, blank=True, null=True, choices=[('priority','优选推送'),('assigned','指定配送'),('urgent','加急配送')], verbose_name='增值服务类型')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'delivery_order'
        ordering = ['-created_at']
        verbose_name = '配送订单'
        verbose_name_plural = '配送订单'

    def __str__(self):
        return f"配送单{self.delivery_id.hex[:8]} - 状态:{self.get_delivery_status_display()}"

    def trigger_payout(self):
        pass


class OrderWaiterStatusLog(models.Model):
    """服务员前台状态变更留痕（A.11.8）"""

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='记录ID')
    order = models.ForeignKey(
        BuyOrder,
        on_delete=models.CASCADE,
        related_name='waiter_status_logs',
        verbose_name='关联订单',
    )
    from_status = models.CharField(max_length=20, blank=True, default='', verbose_name='原状态')
    to_status = models.CharField(max_length=20, verbose_name='新状态')
    changed_by = models.CharField(max_length=64, verbose_name='操作人')
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='变更时间')
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')

    class Meta:
        db_table = 'order_waiter_status_log'
        ordering = ['-changed_at']
        verbose_name = '前台服务状态变更记录'
        verbose_name_plural = '前台服务状态变更记录'

    def __str__(self):
        return f'{self.order_id} {self.from_status}->{self.to_status}'


class OrderWaiterDishServeLog(models.Model):
    """服务员按份标记菜品留痕"""

    ACTION_MARK = 'mark'
    ACTION_UNDO = 'undo'
    ACTION_CHOICES = (
        (ACTION_MARK, '标记一份'),
        (ACTION_UNDO, '撤回一份'),
    )

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='记录ID')
    order = models.ForeignKey(
        BuyOrder,
        on_delete=models.CASCADE,
        related_name='waiter_dish_serve_logs',
        verbose_name='关联订单',
    )
    dish_id = models.CharField(max_length=64, verbose_name='菜品ID')
    dish_name = models.CharField(max_length=128, verbose_name='菜品名称')
    line_id = models.CharField(max_length=64, blank=True, default='', verbose_name='明细行ID')
    action = models.CharField(max_length=8, choices=ACTION_CHOICES, verbose_name='操作')
    served_after = models.PositiveIntegerField(verbose_name='操作后已服务份数')
    total_qty = models.PositiveIntegerField(verbose_name='该菜合计份数')
    changed_by = models.CharField(max_length=64, verbose_name='操作人')
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='操作时间')
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')

    class Meta:
        db_table = 'order_waiter_dish_serve_log'
        ordering = ['-changed_at']
        verbose_name = '服务员按份服务记录'
        verbose_name_plural = '服务员按份服务记录'

    def __str__(self):
        return f'{self.dish_name} {self.action}'


class OrderKitchenDishPrepLog(models.Model):
    """后厨按份备好记录"""

    ACTION_MARK = 'mark'
    ACTION_UNDO = 'undo'
    ACTION_CHOICES = (
        (ACTION_MARK, '标记一份'),
        (ACTION_UNDO, '撤回一份'),
    )

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='记录ID')
    order = models.ForeignKey(
        BuyOrder,
        on_delete=models.CASCADE,
        related_name='kitchen_dish_prep_logs',
        verbose_name='关联订单',
    )
    dish_id = models.CharField(max_length=64, verbose_name='菜品ID')
    dish_name = models.CharField(max_length=128, verbose_name='菜品名称')
    line_id = models.CharField(max_length=64, blank=True, default='', verbose_name='明细行ID')
    action = models.CharField(max_length=8, choices=ACTION_CHOICES, verbose_name='操作')
    prepared_after = models.PositiveIntegerField(verbose_name='操作后已备好份数')
    total_qty = models.PositiveIntegerField(verbose_name='该菜合计份数')
    changed_by = models.CharField(max_length=64, verbose_name='操作人')
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='操作时间')
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')

    class Meta:
        db_table = 'order_kitchen_dish_prep_log'
        ordering = ['-changed_at']
        verbose_name = '后厨按份备好记录'
        verbose_name_plural = '后厨按份备好记录'

    def __str__(self):
        return f'{self.dish_name} {self.action}'


class OperationAuditLog(models.Model):
    """操作审计日志（A.12）：谁、何时、对何对象、做了什么"""

    ACTION_CHOICES = [
        ('login', '登录'),
        ('logout', '退出'),
        ('login_failed', '登录失败'),
        ('order_place', '下单'),
        ('order_status', '订单状态变更'),
        ('operating', '营业/渠道设置'),
        ('menu_switch', '切换菜单清单'),
        ('payment_settings', '支付设置'),
        ('view_audit', '查看操作审计'),
        ('view_tech_log', '查看技术日志'),
        ('other', '其他'),
    ]
    RESULT_CHOICES = [
        ('ok', '成功'),
        ('fail', '失败'),
    ]

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='记录ID')
    seller_id = models.CharField(max_length=64, blank=True, default='', db_index=True, verbose_name='店铺ID')
    actor = models.ForeignKey(
        'User', on_delete=models.SET_NULL, blank=True, null=True,
        related_name='operation_audit_logs', verbose_name='操作人',
    )
    actor_username = models.CharField(max_length=128, blank=True, default='', verbose_name='操作人账号快照')
    actor_role = models.CharField(max_length=16, blank=True, default='', verbose_name='操作人角色快照')
    action_code = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True, verbose_name='动作类型')
    action_label = models.CharField(max_length=64, blank=True, default='', verbose_name='动作说明')
    target_type = models.CharField(max_length=32, blank=True, default='', verbose_name='对象类型')
    target_id = models.CharField(max_length=64, blank=True, default='', verbose_name='对象ID')
    summary = models.CharField(max_length=500, blank=True, default='', verbose_name='结果摘要')
    result = models.CharField(max_length=8, choices=RESULT_CHOICES, default='ok', verbose_name='结果')
    ip_address = models.CharField(max_length=64, blank=True, default='', verbose_name='来源IP')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发生时间')

    class Meta:
        db_table = 'operation_audit_log'
        ordering = ['-created_at']
        verbose_name = '操作审计日志'
        verbose_name_plural = '操作审计日志'
        indexes = [
            models.Index(fields=['seller_id', '-created_at'], name='audit_seller_created_idx'),
            models.Index(fields=['actor_username', '-created_at'], name='audit_actor_created_idx'),
        ]

    def __str__(self):
        return f'{self.actor_username} {self.action_label or self.action_code}'


# A.11 堂食相关模型（营业、桌台、菜单清单）
from .dine_models import (  # noqa: E402
    MenuProfile,
    MenuProfileItem,
    ShopOperatingSettings,
    ShopTable,
    TableSession,
    VirtualTableCode,
)
