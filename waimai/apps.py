from django.apps import AppConfig

class WaimaiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'waimai'

    def ready(self):
        import waimai.models  # 应用启动时加载信号