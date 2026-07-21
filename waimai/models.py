import re
import uuid

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models

from .time_helpers import format_beijing_time
from .time_helpers import to_beijing


def validate_compliance_icon_size(uploaded_file):
    """公安备案图标应是小图片，避免误传过大的文件。"""
    if uploaded_file.size > 1024 * 1024:
        raise ValidationError('公安备案图标不能超过 1 MB。')


# 主页积木配图：单张上限与每账号张数（第一阶段）
MAX_HOME_BLOCK_IMAGE_BYTES = 5 * 1024 * 1024
MAX_USER_UPLOADED_PHOTOS = 100


def validate_home_block_image_size(uploaded_file):
    """积木配图单张不超过 5 MB。"""
    if uploaded_file.size > MAX_HOME_BLOCK_IMAGE_BYTES:
        raise ValidationError('图片不能超过 5 MB，请压缩后再上传。')


def home_block_image_upload_to(instance, filename):
    """按积木 ID 存图，同块再次上传会覆盖旧文件名。"""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    if ext not in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
        ext = 'jpg'
    return f'home_blocks/{instance.block_id}.{ext}'


# ============================================
# 自定义用户模型（方向C：注册登录与权限）
# ============================================
class User(AbstractUser):
    ROLE_CHOICES = [
        ('buyer', '买家'),
        ('seller', '卖家'),
        ('staff', '店铺员工'),
    ]
    STAFF_ACCOUNT_TYPE_CHOICES = [
        ('management', '管理职务'),
        ('employee', '普通员工'),
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
    staff_account_type = models.CharField(
        max_length=16,
        blank=True,
        default='',
        choices=STAFF_ACCOUNT_TYPE_CHOICES,
        verbose_name='子账号类别',
    )
    staff_job_title = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='职务名称',
    )
    staff_permissions = models.JSONField(
        blank=True,
        default=list,
        verbose_name='员工权限清单',
        help_text='保存主体或插件提供的稳定权限编号',
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
    # 店长权限勾选项（第一版仅「允许取消订单」；店主账号无需此字段）
    perm_cancel_order = models.BooleanField(
        default=False, verbose_name='允许取消订单',
        help_text='店主授权后，该员工可在满足沟通门槛时取消订单',
    )
    # 体验机：体验账号每日清空；正式/官方相关账号保留
    is_experience = models.BooleanField(default=False, db_index=True, verbose_name='体验账号')
    is_permanent = models.BooleanField(default=False, db_index=True, verbose_name='正式保留账号')
    # 服务器管理者：可进「服务器设置」（由超级管理员或命令指定；与体验机官方小店无关）
    is_server_owner = models.BooleanField(default=False, db_index=True, verbose_name='服务器管理者')
    # 同账号只允许一处在线：新登录写入当前会话编号，旧设备下次请求时退出。
    active_session_key = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        verbose_name='当前有效登录会话',
    )
    # 买家邮件通知（自愿开启；注册时不要求填邮箱）
    buyer_notify_enabled = models.BooleanField(
        default=False,
        verbose_name='开启订单邮件通知',
    )
    buyer_notify_email = models.CharField(
        max_length=254,
        blank=True,
        default='',
        verbose_name='订单通知收件邮箱',
    )

    class Meta:
        db_table = 'user'
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def __str__(self):
        if self.role == 'staff':
            title = (self.staff_job_title or '').strip() or '店铺员工'
            return f"{self.username} ({title})"
        return f"{self.username} ({self.get_role_display()})"


class SiteComplianceSettings(models.Model):
    """整台服务器共用的备案展示设置；由服务器管理者在「服务器设置」维护（总后台亦可救急）。"""

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
    police_record_icon = models.ImageField(
        upload_to='site_compliance/police/',
        blank=True,
        verbose_name='公安备案图标',
        help_text='请上传公安备案审核平台为本网站提供的图标；支持 PNG、JPG、JPEG，最大 1 MB。',
        validators=[
            FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg']),
            validate_compliance_icon_size,
        ],
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
        if self.police_record_number and not self.police_record_icon:
            raise ValidationError({'police_record_icon': '填写公安备案号时，必须上传审核平台提供的备案图标。'})
        if self.police_record_icon and not self.police_record_number:
            raise ValidationError({'police_record_number': '上传公安备案图标时，也必须填写对应的公安备案号。'})

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


class ServerSiteSettings(models.Model):
    """整台服务器站点品牌设置（「服务器设置」维护；与单店无关）"""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False, verbose_name='固定编号'
    )
    site_name = models.CharField(
        max_length=80, blank=True, default='野草系统', verbose_name='网站顶部名称',
    )
    brand_image_url = models.CharField(
        max_length=500, blank=True, default='', verbose_name='标识图片链接（可选）',
    )
    nav_brand_label = models.CharField(
        max_length=40, blank=True, default='店铺名录', verbose_name='导航「名录」显示名',
    )
    show_powered_by = models.BooleanField(
        default=True, verbose_name='页脚显示「由野草系统提供支持」',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'server_site_settings'
        verbose_name = '服务器站点设置'
        verbose_name_plural = '服务器站点设置'

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        self.site_name = (self.site_name or '').strip() or '野草系统'
        self.nav_brand_label = (self.nav_brand_label or '').strip() or '店铺名录'
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'站点设置:{self.site_name}'


class ServerEmailSettings(models.Model):
    """整台服务器发信邮箱；由服务器管理者在「服务器设置」维护（优先于 .env）。"""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False, verbose_name='固定编号',
    )
    smtp_host = models.CharField(max_length=200, blank=True, default='', verbose_name='SMTP 地址')
    smtp_port = models.PositiveIntegerField(default=465, verbose_name='SMTP 端口')
    smtp_user = models.CharField(max_length=200, blank=True, default='', verbose_name='SMTP 账号')
    smtp_password = models.CharField(max_length=200, blank=True, default='', verbose_name='SMTP 密码')
    from_email = models.CharField(
        max_length=254, blank=True, default='', verbose_name='发件人邮箱',
        help_text='留空则使用 SMTP 账号作为发件地址',
    )
    use_tls = models.BooleanField(default=False, verbose_name='使用 STARTTLS（常见端口 587）')
    use_ssl = models.BooleanField(default=True, verbose_name='使用 SSL（常见端口 465）')
    # 备用发信：主邮箱 SMTP 失败时自动再试
    backup_smtp_host = models.CharField(max_length=200, blank=True, default='', verbose_name='备用 SMTP 地址')
    backup_smtp_port = models.PositiveIntegerField(default=465, verbose_name='备用 SMTP 端口')
    backup_smtp_user = models.CharField(max_length=200, blank=True, default='', verbose_name='备用 SMTP 账号')
    backup_smtp_password = models.CharField(max_length=200, blank=True, default='', verbose_name='备用 SMTP 密码')
    backup_from_email = models.CharField(
        max_length=254, blank=True, default='', verbose_name='备用发件人邮箱',
    )
    backup_use_tls = models.BooleanField(default=False, verbose_name='备用使用 STARTTLS')
    backup_use_ssl = models.BooleanField(default=True, verbose_name='备用使用 SSL')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'server_email_settings'
        verbose_name = '服务器发信设置'
        verbose_name_plural = '服务器发信设置'

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        return super().save(*args, **kwargs)

    def is_configured(self) -> bool:
        return bool(
            (self.smtp_host or '').strip()
            and (self.smtp_user or '').strip()
            and (self.smtp_password or '').strip()
        )

    def is_backup_configured(self) -> bool:
        return bool(
            (self.backup_smtp_host or '').strip()
            and (self.backup_smtp_user or '').strip()
            and (self.backup_smtp_password or '').strip()
        )

    def __str__(self):
        return '服务器发信设置'


class EmailSendLog(models.Model):
    """发信记录（仅用于防刷计数，不存邮件正文）"""

    recipient = models.EmailField(db_index=True, verbose_name='收件邮箱')
    kind = models.CharField(max_length=32, db_index=True, verbose_name='通知类型')
    dedupe_key = models.CharField(
        max_length=128, blank=True, default='', db_index=True, verbose_name='去重键',
    )
    sender_route = models.CharField(
        max_length=16, blank=True, default='', verbose_name='发信通道',
        help_text='primary 主邮箱；backup 备用邮箱',
    )
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发送时间')

    class Meta:
        db_table = 'email_send_log'
        ordering = ['-sent_at']
        verbose_name = '发信记录'
        verbose_name_plural = '发信记录'

    def __str__(self):
        return f'{self.recipient}:{self.kind}'


class ServerHomePage(models.Model):
    """服务器主页（整机一份；与店铺主页严格分开）"""

    singleton_id = models.PositiveSmallIntegerField(
        primary_key=True, default=1, editable=False, verbose_name='固定编号'
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'server_home_page'
        verbose_name = '服务器主页'
        verbose_name_plural = '服务器主页'

    def save(self, *args, **kwargs):
        self.singleton_id = 1
        return super().save(*args, **kwargs)

    def __str__(self):
        return '本服务器主页'


class ServerHomeBlock(models.Model):
    """服务器主页积木块（名录、野草介绍、公告等）"""

    block_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='块ID')
    home_page = models.ForeignKey(
        ServerHomePage, on_delete=models.CASCADE, related_name='blocks', verbose_name='所属服务器主页',
    )
    block_type = models.CharField(max_length=32, db_index=True, verbose_name='块类型')
    title = models.CharField(max_length=120, blank=True, default='', verbose_name='标题')
    body = models.TextField(blank=True, default='', verbose_name='正文')
    image = models.ImageField(
        upload_to=home_block_image_upload_to,
        blank=True,
        verbose_name='上传配图',
        validators=[
            FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'webp', 'gif']),
            validate_home_block_image_size,
        ],
    )
    image_url = models.CharField(max_length=500, blank=True, default='', verbose_name='图片公开链接')
    link_url = models.CharField(max_length=500, blank=True, default='', verbose_name='附加链接')
    nav_label = models.CharField(max_length=32, blank=True, default='', verbose_name='导航短名')
    is_enabled = models.BooleanField(default=False, db_index=True, verbose_name='是否启用')
    show_in_nav = models.BooleanField(default=True, verbose_name='是否出现在吸顶导航')
    sort_order = models.PositiveIntegerField(default=100, db_index=True, verbose_name='排序')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'server_home_block'
        ordering = ['sort_order', 'block_type']
        verbose_name = '服务器主页积木块'
        verbose_name_plural = '服务器主页积木块'
        constraints = [
            models.UniqueConstraint(
                fields=['home_page', 'block_type'],
                condition=~models.Q(block_type='custom'),
                name='uniq_server_home_block_type_non_custom',
            ),
        ]

    def __str__(self):
        return f'server:{self.block_type}:{self.title}'


class UserUploadedPhoto(models.Model):
    """用户上传配图台账：用于每账号最多 100 张的限额（当前持有张数）。"""

    SCOPE_CHOICES = [
        ('shop_home_block', '店铺主页积木'),
        ('server_home_block', '服务器主页积木'),
    ]

    photo_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='记录ID')
    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='uploaded_photos', verbose_name='上传人',
    )
    scope = models.CharField(max_length=32, choices=SCOPE_CHOICES, db_index=True, verbose_name='用途')
    block_id = models.UUIDField(db_index=True, verbose_name='积木块ID')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='首次上传时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='最后更新时间')

    class Meta:
        db_table = 'user_uploaded_photo'
        verbose_name = '用户上传配图'
        verbose_name_plural = '用户上传配图'
        constraints = [
            models.UniqueConstraint(fields=['owner', 'scope', 'block_id'], name='uniq_owner_block_photo'),
        ]

    def __str__(self):
        return f'{self.owner_id}:{self.scope}:{self.block_id}'


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
    account_type_snapshot = models.CharField(
        max_length=16, blank=True, default='', verbose_name='子账号类别快照'
    )
    job_title_snapshot = models.CharField(
        max_length=64, blank=True, default='', verbose_name='职务名称快照'
    )
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
    """单店店铺主页配置（一店一份；不再充当整机入口）"""

    ORDER_NAV_CHOICES = [
        ('to_shop', '导航「下单」直接进下单页'),
        ('to_cta_block', '导航「下单」滚到页内「进入店铺」块'),
    ]

    seller_id = models.CharField(max_length=64, primary_key=True, verbose_name='店铺账号ID')
    # 旧字段：整机入口已迁到 ServerHomePage，本字段仅兼容旧数据，不再驱动 /
    is_server_entry = models.BooleanField(
        default=False, db_index=True,
        verbose_name='（已弃用）曾作本服务器默认入口',
    )
    order_nav_mode = models.CharField(
        max_length=16, choices=ORDER_NAV_CHOICES, default='to_shop',
        verbose_name='顶栏下单行为',
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'shop_home_page'
        verbose_name = '店铺主页'
        verbose_name_plural = '店铺主页'

    def __str__(self):
        return f'店铺主页:{self.seller_id}'


class ShopHomeBlock(models.Model):
    """店铺主页上的一个积木块（简介、公告等；营业/地址由经营设置自动带出）"""

    block_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='块ID')
    home_page = models.ForeignKey(
        ShopHomePage, on_delete=models.CASCADE, related_name='blocks', verbose_name='所属主页',
    )
    block_type = models.CharField(max_length=32, db_index=True, verbose_name='块类型')
    title = models.CharField(max_length=120, blank=True, default='', verbose_name='标题')
    body = models.TextField(blank=True, default='', verbose_name='正文')
    image = models.ImageField(
        upload_to=home_block_image_upload_to,
        blank=True,
        verbose_name='上传配图',
        validators=[
            FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'webp', 'gif']),
            validate_home_block_image_size,
        ],
    )
    image_url = models.CharField(max_length=500, blank=True, default='', verbose_name='图片公开链接')
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
            # 预设块每种只能一块；custom 可有多块（见 home_page_helpers）
            models.UniqueConstraint(
                fields=['home_page', 'block_type'],
                condition=~models.Q(block_type='custom'),
                name='uniq_shop_home_block_type_non_custom',
            ),
        ]

    def __str__(self):
        return f'{self.block_type}:{self.title}'


# ============================================
# 店铺配送费配置（逻辑归属履约插件；表暂留主体）
# 见 waimai.plugins.fulfillment.ownership
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
        ('awaiting_shop_confirm', '待店家备货'),
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
        ('order', '下单'),
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
    # 游客堂食单可为空：归属靠桌台会话，不挂买家账号
    buyer_id = models.CharField(max_length=64, blank=True, default='', db_index=True, verbose_name='买家ID')
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
    cancelled_at = models.DateTimeField(blank=True, null=True, verbose_name='取消时间')
    cancel_side = models.CharField(
        max_length=8,
        blank=True,
        default='',
        choices=[('buyer', '买家'), ('shop', '店家')],
        verbose_name='取消方',
    )
    cancel_note = models.CharField(max_length=500, blank=True, default='', verbose_name='取消说明')
    table_session = models.ForeignKey(
        'TableSession', on_delete=models.SET_NULL, blank=True, null=True,
        related_name='orders', verbose_name='桌台会话',
    )
    table_label = models.CharField(max_length=64, blank=True, default='', verbose_name='桌号/拼桌标识')
    # 可选称呼：方便店员叫人；不填则展示时用桌号
    guest_nickname = models.CharField(max_length=20, blank=True, default='', verbose_name='称呼（可选）')
    order_kind = models.CharField(
        max_length=16, choices=ORDER_KIND_CHOICES, default='normal', verbose_name='订单类型',
    )
    delivery_address = models.TextField(verbose_name='配送地址')
    fulfillment_type = models.CharField(
        max_length=16,
        choices=FULFILLMENT_TYPE_CHOICES,
        default='order',
        db_index=True,
        verbose_name='取餐方式',
    )
    distance_km = models.DecimalField(max_digits=4, decimal_places=1, default=2.5, verbose_name='配送距离（公里）')
    vip_service = models.CharField(max_length=20, blank=True, null=True, choices=[('priority','优选推送'),('assigned','指定配送'),('urgent','加急配送')], verbose_name='增值服务类型')
    vip_service_fee = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name='增值服务费（元）')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='下单时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    # 订单沟通：各方上次看过留言的时间（用于未读红点）
    buyer_msg_read_at = models.DateTimeField(blank=True, null=True, verbose_name='买家已读沟通时间')
    seller_msg_read_at = models.DateTimeField(blank=True, null=True, verbose_name='店家已读沟通时间')
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
    # 外卖货到付款：骑手送达时收取的现金记录
    cash_collected_amount = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True, null=True, verbose_name='骑手实收现金（元）'
    )
    cash_collected_by = models.CharField(
        max_length=64, blank=True, default='', verbose_name='收款骑手'
    )
    cash_collected_at = models.DateTimeField(blank=True, null=True, verbose_name='骑手收款时间')
    # 骑手入金：把收到的现金交回店里，由店主/店长确认
    cash_remitted_at = models.DateTimeField(blank=True, null=True, verbose_name='入金确认时间')
    cash_remitted_by = models.CharField(
        max_length=64, blank=True, default='', verbose_name='入金确认人'
    )
    CASH_SHORTFALL_STATUS_CHOICES = [
        ('', '无异常'),
        ('buyer_pending', '待买家确认少付'),
        ('buyer_confirmed', '买家已确认少付'),
        ('buyer_rejected', '买家拒绝确认'),
        ('exception', '已电话上报异常'),
        ('resolved_full', '已补足现金'),
        ('manager_approved', '管理人员已兜底结单'),
    ]
    cash_shortfall_status = models.CharField(
        max_length=24,
        choices=CASH_SHORTFALL_STATUS_CHOICES,
        blank=True,
        default='',
        db_index=True,
        verbose_name='货到付款少收状态',
    )
    cash_shortfall_reason = models.CharField(
        max_length=500, blank=True, default='', verbose_name='货到付款少收原因'
    )
    cash_shortfall_buyer_responded_at = models.DateTimeField(
        blank=True, null=True, verbose_name='买家确认少收时间'
    )
    cash_exception_note = models.CharField(
        max_length=500, blank=True, default='', verbose_name='现金异常电话沟通备注'
    )
    cash_exception_marked_by = models.CharField(
        max_length=64, blank=True, default='', verbose_name='现金异常标记人'
    )
    cash_exception_marked_at = models.DateTimeField(
        blank=True, null=True, verbose_name='现金异常标记时间'
    )
    cash_exception_resolved_by = models.CharField(
        max_length=64, blank=True, default='', verbose_name='现金异常处理人'
    )
    cash_exception_resolved_at = models.DateTimeField(
        blank=True, null=True, verbose_name='现金异常处理时间'
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

    def is_guest_order(self) -> bool:
        """没有买家账号的订单（堂食游客）。"""
        return not (self.buyer_id or '').strip()

    def get_buyer_display_name(self) -> str:
        """给人看的称呼：优先可选称呼 → 桌号 → 买家账号 →「游客」。"""
        nick = (self.guest_nickname or '').strip()
        if nick:
            return nick
        label = (self.table_label or '').strip()
        if self.is_guest_order() and label:
            return label
        if (self.buyer_id or '').strip():
            return self.buyer_id
        if label:
            return label
        return '游客'

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
        """兼容旧调用；统一使用“货到付款等待配送员收款”的判断。"""
        return self.is_cod_awaiting_collection()

    def is_delivery_cod(self):
        """是否外卖 · 现金货到付款单"""
        return self.fulfillment_type == 'delivery' and self.payment_method == 'cash'

    def is_cod_awaiting_collection(self):
        """外卖货到付款：尚未收款（骑手送达时收）"""
        return self.is_delivery_cod() and self.payment_status == 'pending_payment'

    def cash_remit_pending(self):
        """骑手已收现金、但尚未交回店里入金"""
        return bool(
            self.payment_method == 'cash'
            and self.cash_collected_at is not None
            and self.cash_remitted_at is None
        )

    def cash_shortfall_amount(self):
        """货到付款少收金额；没有少收时为 0。"""
        if self.cash_collected_amount is None:
            return None
        diff = self.total_amount - self.cash_collected_amount
        return diff if diff > 0 else 0

    def cash_shortfall_waiting_buyer(self):
        """是否正在等买家当面确认少付。"""
        return self.cash_shortfall_status == 'buyer_pending'

    def cash_exception_unresolved(self):
        """是否为尚未正常结清的现金异常。"""
        return self.cash_shortfall_status in (
            'buyer_pending', 'buyer_rejected', 'exception',
        )

    def is_awaiting_in_store_order_confirm(self):
        """堂食/打包到店付：已默认接单，待店家开始备货并告知预计时间"""
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
            and self.order_status in ('awaiting_prep', 'preparing', 'ready_pickup')
        )

    def can_complete_in_store_order(self):
        """手动完成到店单：须已备好且已收款。

        按份交付全部完成时可由服务流程自动结单，这是另一条有意保留的便捷路径。
        """
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

    def is_basic_order(self):
        """是否主体提供的基础「下单」通道。"""
        return self.fulfillment_type == 'order'

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
        if self.is_basic_order():
            if self.payment_status == 'pending_payment' and self.payment_method == 'cash':
                return '基础下单：请按订单约定与店家完成现金付款。有事可在订单沟通里留言。'
            return '基础下单：请按订单约定付款。'
        if self.is_awaiting_in_store_order_confirm():
            if self.is_dine_in():
                return '堂食订单已提交，店家将为您备餐并告知预计出餐时间；用餐时到店付现金即可。有事可在订单沟通里留言。'
            return '打包订单已提交，店家将为您备货并告知预计可取餐时间；取餐时到店付现金即可。有事可在订单沟通里留言。'
        if self.is_cash_receipt_pending():
            if self.estimated_ready_at:
                t = format_beijing_time(self.estimated_ready_at)
                if self.order_status == 'awaiting_prep':
                    if self.is_dine_in():
                        return f'订单已进入备餐队列，预计 {t} 可出餐。请在店内付款。'
                    return f'订单已进入备货队列，预计 {t} 可取餐。请在取餐时付款。'
                if self.is_dine_in():
                    return f'店家备餐中，预计 {t} 可出餐。用餐时请付现金，店家确认收款后订单完结。'
                return f'店家备货中，预计 {t} 可取餐。取餐时请付现金，店家确认收款后订单完结。'
            if self.is_dine_in():
                return '店家备餐中。用餐时请付现金。'
            return '店家备货中。取餐时请付现金。'
        if self.is_dine_in():
            return '堂食订单：请在店内付款。'
        if self.is_takeaway():
            return '打包自取：请到店取餐并付款。'
        return '外卖货到付款：店家会先备货并派骑手，骑手送达时向您收现金（也可当面扫码付）。'

    def get_estimated_ready_label(self):
        """预计完成/出餐/取餐时间的展示文案（北京时间）"""
        if not self.estimated_ready_at:
            return ''
        t = format_beijing_time(self.estimated_ready_at)
        if self.is_basic_order():
            return f'预计 {t} 可完成'
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
    enable_cod = models.BooleanField(default=True, verbose_name='允许外卖现金货到付款')
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
    """配送单（逻辑归属履约插件；表暂留主体）。见 plugins.fulfillment.ownership"""
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


class CashRemittanceRequest(models.Model):
    """配送员交回货到付款现金的申请单。"""

    STATUS_CHOICES = [
        ('pending', '待确认'),
        ('confirmed', '已确认'),
        ('rejected', '已退回'),
    ]

    request_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, verbose_name='交款申请ID'
    )
    seller_id = models.CharField(max_length=64, db_index=True, verbose_name='店铺ID')
    rider_id = models.CharField(max_length=64, db_index=True, verbose_name='配送员ID')
    total_amount = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name='申请交款金额（元）'
    )
    order_count = models.PositiveIntegerField(default=0, verbose_name='包含订单数')
    note = models.CharField(max_length=500, blank=True, default='', verbose_name='配送员交款备注')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default='pending',
        db_index=True, verbose_name='交款申请状态',
    )
    reviewed_by = models.CharField(
        max_length=64, blank=True, default='', verbose_name='确认/退回人'
    )
    review_note = models.CharField(
        max_length=500, blank=True, default='', verbose_name='确认/退回说明'
    )
    reviewed_at = models.DateTimeField(blank=True, null=True, verbose_name='处理时间')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='申请时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'cash_remittance_request'
        ordering = ['-created_at']
        verbose_name = '配送员现金交款申请'
        verbose_name_plural = '配送员现金交款申请'


class CashRemittanceItem(models.Model):
    """交款申请内的订单明细；保留历史，退回后可重新申请。"""

    item_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, verbose_name='交款明细ID'
    )
    request = models.ForeignKey(
        CashRemittanceRequest,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='交款申请',
    )
    order = models.ForeignKey(
        BuyOrder,
        on_delete=models.PROTECT,
        related_name='cash_remittance_items',
        verbose_name='现金订单',
    )
    amount = models.DecimalField(max_digits=8, decimal_places=2, verbose_name='本单实收（元）')

    class Meta:
        db_table = 'cash_remittance_item'
        verbose_name = '配送员现金交款明细'
        verbose_name_plural = '配送员现金交款明细'
        constraints = [
            models.UniqueConstraint(
                fields=['request', 'order'], name='uniq_cash_remittance_request_order'
            ),
        ]


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
    ShopWaitTimeRule,
    TableSession,
    VirtualTableCode,
)


class OrderMessage(models.Model):
    """订单双方沟通留言（非即时聊天；打开详情可看到更新）"""

    SIDE_CHOICES = [
        ('buyer', '买家'),
        ('shop', '店家'),
    ]

    message_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, verbose_name='留言ID')
    order = models.ForeignKey(
        BuyOrder, on_delete=models.CASCADE, related_name='messages', verbose_name='所属订单',
    )
    author_side = models.CharField(max_length=8, choices=SIDE_CHOICES, db_index=True, verbose_name='发言方')
    author_username = models.CharField(max_length=128, verbose_name='发言账号')
    body = models.CharField(max_length=300, verbose_name='留言内容')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发送时间')

    class Meta:
        db_table = 'order_message'
        ordering = ['created_at']
        verbose_name = '订单沟通留言'
        verbose_name_plural = '订单沟通留言'

    def __str__(self):
        return f'{self.order_id}:{self.author_side}:{self.body[:20]}'
