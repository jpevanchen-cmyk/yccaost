from django.contrib import admin
from django.urls import path, include

from waimai import views
from waimai import owner_views as views_owner
from waimai import public_wall_views as views_public_wall
from waimai import v1_setup_views as views_v1
from waimai import v1_tray_lan_views as views_v1_tray
from waimai import operation_lock_views as views_op_lock

urlpatterns = [
    path('', views.home, name='home'),
    path('p/<slug:slug>/', views.server_topic_page, name='server_topic_page'),
    path('admin/', admin.site.urls),
    path('directory/', views.directory, name='directory'),
    path('s/<str:shop_code>/home/', views.shop_showcase, name='shop_showcase'),
    path('showcase/', views.shop_showcase, name='shop_showcase_by_query'),
    path('rider-home/', views.rider_home, name='rider_home'),
    path('kitchen-home/', views.kitchen_home, name='kitchen_home'),
    path('s/<str:shop_code>/work/', views.shop_work, name='shop_work'),
    path('s/<str:shop_code>/work/new-orders.json', views.shop_work_new_orders_json, name='shop_work_new_orders_json'),
    path('s/<str:shop_code>/work/remittances-pending.json', views.shop_work_pending_remittances_json, name='shop_work_pending_remittances_json'),
    path('s/<str:shop_code>/work/logout/', views.shop_work_logout, name='shop_work_logout'),
    path(
        's/<str:shop_code>/work/table/<uuid:table_id>/order/',
        views.shop_work_waiter_table_order,
        name='shop_work_waiter_table_order',
    ),
    path(
        's/<str:shop_code>/work/order/<uuid:order_id>/',
        views.shop_work_order,
        name='shop_work_order',
    ),
    path(
        's/<str:shop_code>/work/cashier/wechat/<uuid:order_id>/',
        views.shop_work_cashier_wechat,
        name='shop_work_cashier_wechat',
    ),
    path(
        's/<str:shop_code>/work/cashier/wechat/<uuid:order_id>/status/',
        views.shop_work_cashier_wechat_status,
        name='shop_work_cashier_wechat_status',
    ),
    path(
        's/<str:shop_code>/work/cashier/print/<uuid:order_id>/',
        views.shop_work_cashier_order_print,
        name='shop_work_cashier_order_print',
    ),
    path('owner-hub/', views.owner_hub, name='owner_hub'),
    # 服务器设置（通用）；旧 /owner/ 路径兼容跳转
    path('server-settings/', views_owner.server_settings_home, name='server_settings'),
    path('server-settings/branding/', views_owner.server_settings_branding, name='server_settings_branding'),
    path('server-settings/bulletin/', views_owner.server_settings_bulletin, name='server_settings_bulletin'),
    path('bulletin/', views.server_bulletin_history, name='server_bulletin_history'),
    path('server-settings/compliance/', views_owner.server_settings_compliance, name='server_settings_compliance'),
    path('server-settings/email/', views_owner.server_settings_email, name='server_settings_email'),
    path('server-settings/tech-logs/', views_owner.server_settings_tech_logs, name='server_settings_tech_logs'),
    path(
        'server-settings/operation-lock/',
        views_owner.server_settings_operation_lock,
        name='server_settings_operation_lock',
    ),
    path('server-settings/home/', views_owner.server_settings_home_page, name='server_settings_home_page'),
    path(
        'home-download/<uuid:block_id>/',
        views.home_block_download,
        name='home_block_download',
    ),
    path('server-settings/guestbook/', views_owner.server_settings_guestbook, name='server_settings_guestbook'),
    path(
        'server-settings/guestbook/<str:public_code>/',
        views_owner.server_settings_guestbook_thread,
        name='server_settings_guestbook_thread',
    ),
    path(
        'server-settings/public-wall/',
        views_public_wall.server_settings_public_wall,
        name='server_settings_public_wall',
    ),
    path('guestbook/post/', views_owner.guestbook_post, name='guestbook_post'),
    path('public-wall/post/', views_public_wall.public_wall_post, name='public_wall_post'),
    path('guestbook/open/', views_owner.guestbook_open_search, name='guestbook_open_search'),
    path(
        'guestbook/t/<str:public_code>/',
        views_owner.guestbook_thread_public,
        name='guestbook_thread_public',
    ),
    path('owner/', views_owner.server_settings_home, name='owner_console'),
    path('owner/branding/', views_owner.server_settings_branding, name='owner_branding'),
    path('owner/compliance/', views_owner.server_settings_compliance, name='owner_compliance'),
    path('owner/server-home/', views_owner.server_settings_home_page, name='owner_server_home'),
    path('waiter-home/', views.waiter_home, name='waiter_home'),
    path('waiter-home/pay/<uuid:order_id>/', views.waiter_pay_order, name='waiter_pay_order'),
    path('waiter-home/pay/<uuid:order_id>/status/', views.waiter_pay_order_status, name='waiter_pay_order_status'),
    path('knight-hall/', views.knight_hall_redirect, name='knight_hall'),
    path('shop/', views.shop_page, name='shop'),
    path(
        'shop/scan/<str:display_code>/<str:tier>/',
        views.product_scan_add,
        name='product_scan_add',
    ),
    path('dine/', views.dine_table_entry, name='dine_table'),
    path('my-deliveries/', views.my_deliveries, name='my_deliveries'),
    path('rider-history/', views.rider_delivery_history, name='rider_delivery_history'),
    path('register/', views.register, name='register'),
    path('privacy/', views.privacy_policy, name='privacy_policy'),
    path('shop-register/', views.shop_register, name='shop_register'),
    path('accounts/login/', views.CustomLoginView.as_view(), name='login'),
    path('accounts/logout/', views.EcosystemLogoutView.as_view(), name='logout'),
    path('account/', views.buyer_center, name='buyer_center'),
    path('account/cancel/', views.account_cancel, name='account_cancel'),
    path('seller-panel/shop-cancel/', views.shop_cancel, name='shop_cancel'),
    path('account/password/', views.account_password_change, name='account_password_change'),
    path('accounts/session/heartbeat/', views.session_heartbeat, name='session_heartbeat'),
    path('accounts/session/beacon-logout/', views.session_beacon_logout, name='session_beacon_logout'),
    path('operation-lock/unlock/', views_op_lock.operation_lock_unlock, name='operation_lock_unlock'),
    path('operation-lock/lock/', views_op_lock.operation_lock_manual, name='operation_lock_manual'),
    path('operation-lock/touch/', views_op_lock.operation_lock_touch, name='operation_lock_touch'),
    path('seller-panel/', views.seller_panel, name='seller_panel'),
    path('seller-panel/products/print-qr/', views.seller_product_qr_print, name='seller_product_qr_print'),
    path('seller-panel/workbench/attendance-logs/', views.seller_panel_attendance_logs, name='seller_panel_attendance_logs'),
    path('seller-panel/orders/pending.json', views.seller_pending_orders_json, name='seller_pending_orders_json'),
    path('seller-panel/payment/remittances-pending.json', views.seller_pending_remittances_json, name='seller_pending_remittances_json'),
    path(
        'seller-panel/fund-ledger/entry/<uuid:ledger_id>/drawer.json',
        views.seller_fund_ledger_entry_drawer,
        name='seller_fund_ledger_entry_drawer',
    ),
    path(
        'seller-panel/fund-ledger/order/<uuid:order_id>/drawer.json',
        views.seller_fund_ledger_order_drawer,
        name='seller_fund_ledger_order_drawer',
    ),
    path('seller-panel/<str:section>/', views.seller_panel_section, name='seller_panel_section'),
    path('place-order/', views.place_order, name='place_order'),
    path('pay/<uuid:order_id>/', views.pay_order, name='pay_order'),
    path('pay/<uuid:order_id>/status/', views.pay_order_status, name='pay_order_status'),
    path('pay/wechat/notify/', views.wechat_pay_notify, name='wechat_pay_notify'),
    path('order-history/', views.order_history, name='order_history'),
    path('order/<uuid:order_id>/cash-code/', views.order_cash_code, name='order_cash_code'),
    path('order/<uuid:order_id>/cash-code/print/', views.order_cash_code_print, name='order_cash_code_print'),
    path('order/<uuid:order_id>/voucher/', views.guest_order_voucher, name='guest_order_voucher'),
    path('order/<uuid:order_id>/', views.order_detail, name='order_detail'),
    path(
        'seller-panel/orders/cashier-qr/<uuid:order_id>/',
        views.seller_order_cashier_qr_print,
        name='seller_order_cashier_qr_print',
    ),
    path('experience/', include('waimai.onboarding.urls')),
    path('v1-local/tray/lan/', views_v1_tray.v1_tray_lan, name='v1_tray_lan'),
    path('v1-local/setup/', views_v1.v1_setup_entry, name='v1_setup_entry'),
    path(
        'v1-local/setup/pick-backup-dir/',
        views_v1.v1_setup_pick_backup_dir,
        name='v1_setup_pick_backup_dir',
    ),
    path(
        'v1-local/setup/<slug:step_slug>/',
        views_v1.v1_setup_step,
        name='v1_setup_step',
    ),
]

# 服务器拥有者私人工具包 URL（未开启时不注册）
try:
    from waimai.server_plugin_runtime import get_server_plugin_urls

    urlpatterns += get_server_plugin_urls()
except Exception:
    pass

# 调试或 V1 本机无 Nginx：由程序提供上传图（显式挂路由；勿用 static()——关调试时它故意返回空）。
# 云上正式站关调试且非 V1 时由 Nginx 提供。
from waimai.v1_local_helpers import uploaded_media_urlpatterns

urlpatterns += uploaded_media_urlpatterns()
