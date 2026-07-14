from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.contrib.auth.models import Group

from .models import BuyOrder, DeliveryOrder, Dish, OperationAuditLog, PaymentRecord, ShopDeliverySettings, ShopPaymentSettings, ShopProfile, User

admin.site.unregister(Group)


@admin.register(User)
class CustomUserAdmin(DefaultUserAdmin):
    list_display = ['username', 'role', 'employer_seller_id', 'is_experience', 'is_permanent', 'is_active', 'date_joined']
    list_filter = ['role', 'is_active', 'is_experience', 'is_permanent']
    fieldsets = DefaultUserAdmin.fieldsets + (
        ('用户身份', {'fields': ('role', 'employer_seller_id', 'is_experience', 'is_permanent')}),
    )


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
        'is_showcase_shop', 'wechat_mch_id',
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
