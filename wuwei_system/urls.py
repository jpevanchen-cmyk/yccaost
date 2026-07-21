from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from waimai import views
from waimai import owner_views as views_owner

urlpatterns = [
    path('', views.home, name='home'),
    path('admin/', admin.site.urls),
    path('directory/', views.directory, name='directory'),
    path('s/<str:shop_code>/home/', views.shop_showcase, name='shop_showcase'),
    path('showcase/', views.shop_showcase, name='shop_showcase_by_query'),
    path('rider-home/', views.rider_home, name='rider_home'),
    path('kitchen-home/', views.kitchen_home, name='kitchen_home'),
    path('s/<str:shop_code>/work/', views.shop_work, name='shop_work'),
    path('s/<str:shop_code>/work/new-orders.json', views.shop_work_new_orders_json, name='shop_work_new_orders_json'),
    path('s/<str:shop_code>/work/logout/', views.shop_work_logout, name='shop_work_logout'),
    path(
        's/<str:shop_code>/work/order/<uuid:order_id>/',
        views.shop_work_order,
        name='shop_work_order',
    ),
    path('owner-hub/', views.owner_hub, name='owner_hub'),
    # 服务器设置（通用）；旧 /owner/ 路径兼容跳转
    path('server-settings/', views_owner.server_settings_home, name='server_settings'),
    path('server-settings/branding/', views_owner.server_settings_branding, name='server_settings_branding'),
    path('server-settings/compliance/', views_owner.server_settings_compliance, name='server_settings_compliance'),
    path('server-settings/email/', views_owner.server_settings_email, name='server_settings_email'),
    path('server-settings/home/', views_owner.server_settings_home_page, name='server_settings_home_page'),
    path('owner/', views_owner.server_settings_home, name='owner_console'),
    path('owner/branding/', views_owner.server_settings_branding, name='owner_branding'),
    path('owner/compliance/', views_owner.server_settings_compliance, name='owner_compliance'),
    path('owner/server-home/', views_owner.server_settings_home_page, name='owner_server_home'),
    path('waiter-home/', views.waiter_home, name='waiter_home'),
    path('waiter-home/pay/<uuid:order_id>/', views.waiter_pay_order, name='waiter_pay_order'),
    path('waiter-home/pay/<uuid:order_id>/status/', views.waiter_pay_order_status, name='waiter_pay_order_status'),
    path('knight-hall/', views.knight_hall_redirect, name='knight_hall'),
    path('shop/', views.shop_page, name='shop'),
    path('dine/', views.dine_table_entry, name='dine_table'),
    path('my-deliveries/', views.my_deliveries, name='my_deliveries'),
    path('rider-history/', views.rider_delivery_history, name='rider_delivery_history'),
    path('register/', views.register, name='register'),
    path('shop-register/', views.shop_register, name='shop_register'),
    path('accounts/login/', views.CustomLoginView.as_view(), name='login'),
    path('accounts/logout/', views.EcosystemLogoutView.as_view(), name='logout'),
    path('account/', views.buyer_center, name='buyer_center'),
    path('account/password/', views.account_password_change, name='account_password_change'),
    path('accounts/session/heartbeat/', views.session_heartbeat, name='session_heartbeat'),
    path('accounts/session/beacon-logout/', views.session_beacon_logout, name='session_beacon_logout'),
    path('seller-panel/', views.seller_panel, name='seller_panel'),
    path('seller-panel/orders/pending.json', views.seller_pending_orders_json, name='seller_pending_orders_json'),
    path('seller-panel/<str:section>/', views.seller_panel_section, name='seller_panel_section'),
    path('place-order/', views.place_order, name='place_order'),
    path('pay/<uuid:order_id>/', views.pay_order, name='pay_order'),
    path('pay/<uuid:order_id>/status/', views.pay_order_status, name='pay_order_status'),
    path('pay/wechat/notify/', views.wechat_pay_notify, name='wechat_pay_notify'),
    path('order-history/', views.order_history, name='order_history'),
    path('order/<uuid:order_id>/', views.order_detail, name='order_detail'),
]

# 服务器拥有者私人工具包 URL（未开启时不注册）
try:
    from waimai.server_plugin_runtime import get_server_plugin_urls

    urlpatterns += get_server_plugin_urls()
except Exception:
    pass

# 本地开发时由 Django 提供上传图片；正式服务器由 Nginx 提供 /media/。
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
