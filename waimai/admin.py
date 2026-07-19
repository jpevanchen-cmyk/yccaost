from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.contrib.auth.models import Group
from django.utils.html import format_html

from .models import (
    BuyOrder,
    DeliveryOrder,
    Dish,
    OperationAuditLog,
    OrderMessage,
    PaymentRecord,
    ServerHomePage,
    ServerSiteSettings,
    ShopDeliverySettings,
    ShopPaymentSettings,
    ShopProfile,
    SiteComplianceSettings,
    User,
)

admin.site.unregister(Group)


@admin.register(User)
class CustomUserAdmin(DefaultUserAdmin):
    list_display = [
        'username', 'role', 'staff_account_type', 'staff_job_title',
        'employer_seller_id', 'is_experience', 'is_permanent',
        'is_server_owner', 'is_active', 'date_joined',
    ]
    list_filter = [
        'role', 'staff_account_type', 'is_active',
        'is_experience', 'is_permanent', 'is_server_owner',
    ]
    fieldsets = DefaultUserAdmin.fieldsets + (
        ('用户身份', {
            'fields': (
                'role', 'employer_seller_id', 'staff_account_type',
                'staff_job_title', 'staff_permissions', 'perm_cancel_order',
                'is_experience', 'is_permanent', 'is_server_owner',
            ),
            'description': (
                '店铺子账号统一使用“店铺员工”，再填写管理职务/普通员工、'
                '职务名称与权限清单。“允许取消订单”旧字段仅作兼容同步。'
            ),
        }),
    )


@admin.register(SiteComplianceSettings)
class SiteComplianceSettingsAdmin(admin.ModelAdmin):
    """服务器级备案设置：只给 Django 超级管理员维护，普通店主无权进入。"""

    fields = [
        'icp_record_number',
        'icp_link_preview',
        'police_record_number',
        'police_record_icon',
        'police_icon_preview',
        'police_link_preview',
        'updated_at',
    ]
    readonly_fields = ['icp_link_preview', 'police_icon_preview', 'police_link_preview', 'updated_at']

    @admin.display(description='工信部查询链接（系统自动）')
    def icp_link_preview(self, obj):
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
            'https://beian.miit.gov.cn/',
            '打开工信部备案管理系统',
        )

    @admin.display(description='公安备案查询链接（系统自动）')
    def police_link_preview(self, obj):
        if not obj or not obj.police_query_url:
            return '填写公安联网备案号后，系统会从数字编号生成官方查询链接。'
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
            obj.police_query_url,
            '打开公安联网备案查询',
        )

    @admin.display(description='公安备案图标预览')
    def police_icon_preview(self, obj):
        if not obj or not obj.police_record_icon:
            return '请上传公安备案审核平台为本网站提供的图标。'
        return format_html(
            '<img src="{}" alt="公安备案图标" style="max-width:40px;max-height:40px;">',
            obj.police_record_icon.url,
        )

    def has_add_permission(self, request):
        return request.user.is_superuser and not SiteComplianceSettings.objects.exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        # 清空输入框即可停止展示，禁止删除唯一设置行。
        return False


@admin.register(ShopProfile)
class ShopProfileAdmin(admin.ModelAdmin):
    list_display = ['shop_name', 'shop_code', 'seller_id', 'shop_type', 'address', 'is_listed', 'is_official']
    list_filter = ['shop_type', 'is_listed', 'is_official']

    def get_readonly_fields(self, request, obj=None):
        """已有店铺：店铺码只读（仅合并登记可改，见 A.13）"""
        if obj:
            return ['shop_code', 'seller_id', 'registered_at']
        return ['registered_at']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from .shop_code_helpers import assign_shop_code_on_create
        assign_shop_code_on_create(obj)


@admin.register(ShopDeliverySettings)
class ShopDeliverySettingsAdmin(admin.ModelAdmin):
    list_display = ['seller_id', 'min_delivery_fee', 'free_delivery_threshold', 'max_distance_km']


@admin.register(ShopPaymentSettings)
class ShopPaymentSettingsAdmin(admin.ModelAdmin):
    list_display = [
        'seller_id', 'enable_simulate', 'enable_wechat', 'enable_cash',
        'wechat_mch_id',
    ]
    list_filter = ['enable_simulate', 'enable_wechat', 'enable_cash']


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = [
        'out_trade_no', 'buy_order', 'payment_method', 'amount', 'status', 'created_at',
    ]
    list_filter = ['payment_method', 'status']
    readonly_fields = ['record_id', 'created_at', 'updated_at', 'paid_at']


@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'seller_id', 'is_active', 'created_at']
    list_filter = ['is_active', 'seller_id']


@admin.register(BuyOrder)
class BuyOrderAdmin(admin.ModelAdmin):
    list_display = [
        'display_order_no', 'buyer_id', 'seller_id', 'total_amount',
        'payment_status', 'order_status', 'payment_method', 'created_at',
        'fulfillment_type',
    ]
    list_filter = ['payment_status', 'order_status', 'payment_method']
    readonly_fields = ['order_id', 'created_at', 'updated_at', 'preparing_at', 'ready_at']

    @admin.display(description='订单号')
    def display_order_no(self, obj):
        return obj.get_display_order_no()


@admin.register(OrderMessage)
class OrderMessageAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'order', 'author_side', 'author_username', 'body']
    list_filter = ['author_side']
    search_fields = ['author_username', 'body', 'order__buyer_id', 'order__seller_id']
    readonly_fields = ['message_id', 'created_at']


@admin.register(DeliveryOrder)
class DeliveryOrderAdmin(admin.ModelAdmin):
    list_display = ['delivery_id_truncated', 'rider_id', 'delivery_fee', 'delivery_status', 'created_at']
    list_filter = ['delivery_status']

    @admin.display(description='配送单ID(短)')
    def delivery_id_truncated(self, obj):
        return obj.delivery_id.hex[:8]


@admin.register(OperationAuditLog)
class OperationAuditLogAdmin(admin.ModelAdmin):
    list_display = [
        'created_at', 'seller_id', 'actor_username', 'action_code', 'result', 'summary',
    ]
    list_filter = ['action_code', 'result', 'actor_role']
    search_fields = ['actor_username', 'seller_id', 'summary', 'target_id']
    readonly_fields = [
        'log_id', 'seller_id', 'actor', 'actor_username', 'actor_role',
        'action_code', 'action_label', 'target_type', 'target_id',
        'summary', 'result', 'ip_address', 'created_at',
    ]


@admin.register(ServerSiteSettings)
class ServerSiteSettingsAdmin(admin.ModelAdmin):
    list_display = ['site_name', 'nav_brand_label', 'show_powered_by', 'updated_at']


@admin.register(ServerHomePage)
class ServerHomePageAdmin(admin.ModelAdmin):
    list_display = ['singleton_id', 'updated_at']
