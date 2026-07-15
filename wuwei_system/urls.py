from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from waimai import views

urlpatterns = [
    path('', views.home, name='home'),
    path('admin/', admin.site.urls),
    path('directory/', views.directory, name='directory'),
    path('s/<str:shop_code>/home/', views.shop_showcase, name='shop_showcase'),
    path('showcase/', views.shop_showcase, name='shop_showcase_by_query'),
    path('rider-home/', views.rider_home, name='rider_home'),
    path('kitchen-home/', views.kitchen_home, name='kitchen_home'),
    path('s/<str:shop_code>/work/', views.shop_work, name='shop_work'),
    path('s/<str:shop_code>/work/logout/', views.shop_work_logout, name='shop_work_logout'),
    path('owner-hub/', views.owner_hub, name='owner_hub'),
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
    path('accounts/session/heartbeat/', views.session_heartbeat, name='session_heartbeat'),
    path('accounts/session/beacon-logout/', views.session_beacon_logout, name='session_beacon_logout'),
    path('seller-panel/', views.seller_panel, name='seller_panel'),
    path('seller-panel/<str:section>/', views.seller_panel_section, name='seller_panel_section'),
    path('place-order/', views.place_order, name='place_order'),
    path('pay/<uuid:order_id>/', views.pay_order, name='pay_order'),
    path('pay/<uuid:order_id>/status/', views.pay_order_status, name='pay_order_status'),
    path('pay/wechat/notify/', views.wechat_pay_notify, name='wechat_pay_notify'),
    path('order-history/', views.order_history, name='order_history'),
    path('order/<uuid:order_id>/', views.order_detail, name='order_detail'),
]

# 本地开发时由 Django 提供上传图片；正式服务器由 Nginx 提供 /media/。
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
