from django.apps import AppConfig


class WaimaiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'waimai'

    def ready(self):
        import waimai.models  # 应用启动时加载信号
        from django.contrib import admin
        from django.db.models.signals import post_save

        from .models import BuyOrder
        from .order_notify_helpers import on_buy_order_created

        # 新订单邮件通知：新建订单后触发（dispatch_uid 防止重复注册）
        post_save.connect(
            on_buy_order_created, sender=BuyOrder,
            dispatch_uid='yc_new_order_email_notify',
        )

        # 总后台文案：提醒仅技术维护使用（详情见服务器部署手册）
        admin.site.site_header = '野草系统 · 技术总后台（高风险）'
        admin.site.site_title = '野草技术总后台'
        admin.site.index_title = '请确认您是有经验的维护人员后再操作'
