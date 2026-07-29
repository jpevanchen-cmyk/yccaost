# 新版新手体验：URL（前缀 /experience/，与旧 /onboarding/ 并行）

from django.urls import path

from . import views

urlpatterns = [
    path('', views.experience_home, name='experience_home'),
    path(
        'preview/seller/operating/',
        views.experience_preview_operating,
        name='experience_preview_operating',
    ),
    path(
        'preview/seller/products/',
        views.experience_preview_products,
        name='experience_preview_products',
    ),
    path(
        'preview/seller/print-qr/',
        views.experience_preview_print_qr,
        name='experience_preview_print_qr',
    ),
    path(
        'preview/seller/workbench/',
        views.experience_preview_workbench,
        name='experience_preview_workbench',
    ),
    path('cleanup/', views.experience_cleanup, name='experience_cleanup'),
]
