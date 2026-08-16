from django.apps import AppConfig


class WaimaiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'waimai'

    def ready(self):
        import waimai.models  # 应用启动时加载信号
        from django.contrib import admin
        from django.db.backends.signals import connection_created
        from django.db.models.signals import post_save

        from .models import BuyOrder
        from .order_notify_helpers import on_buy_order_created
        from .plugin_runtime.bootstrap import bootstrap_builtin_plugins
        from .server_plugin_runtime.bootstrap import bootstrap_server_plugins
        from .v1_sqlite_helpers import on_connection_created

        # 同仓内置插件（饮食等）装入注册表
        bootstrap_builtin_plugins()
        # 服务器拥有者私人工具包（可选；默认关闭）
        bootstrap_server_plugins()
        # V1：首次请求时再补允许主机（避免 ready 阶段查库告警）
        from django.core.signals import request_started

        def _load_lan_hosts_once(**kwargs):
            from django.conf import settings as dj_settings

            if getattr(dj_settings, '_yc_lan_hosts_loaded', False):
                return
            dj_settings._yc_lan_hosts_loaded = True
            try:
                from .v1_allowed_hosts_helpers import load_saved_lan_hosts_into_allowed

                load_saved_lan_hosts_into_allowed()
            except Exception:
                pass

        request_started.connect(
            _load_lan_hosts_once,
            dispatch_uid='yc_load_lan_hosts_once',
        )

        def _start_pending_pay_scanner_once(**kwargs):
            from django.conf import settings as dj_settings

            if getattr(dj_settings, '_yc_pending_pay_scanner_started', False):
                return
            dj_settings._yc_pending_pay_scanner_started = True
            try:
                from .pending_payment_timeout_helpers import maybe_start_pending_pay_scanner

                maybe_start_pending_pay_scanner()
            except Exception:
                pass

        request_started.connect(
            _start_pending_pay_scanner_once,
            dispatch_uid='yc_pending_pay_scanner_once',
        )

        # V1 文件库：连库后自动 WAL + busy_timeout（仅 v1_local_mode 生效）
        connection_created.connect(
            on_connection_created,
            dispatch_uid='yc_v1_sqlite_pragmas',
        )

        # 新订单邮件通知：新建订单后触发（dispatch_uid 防止重复注册）
        post_save.connect(
            on_buy_order_created, sender=BuyOrder,
            dispatch_uid='yc_new_order_email_notify',
        )

        # 总后台文案：提醒仅技术维护使用（详情见服务器部署手册）
        admin.site.site_header = '野草系统 · 技术总后台（高风险）'
        admin.site.site_title = '野草技术总后台'
        admin.site.index_title = '请确认您是有经验的维护人员后再操作'
