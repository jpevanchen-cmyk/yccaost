# 服务器管理者：与体验机「官方小店 / 正式保留」无关

from __future__ import annotations


def user_is_server_manager(user) -> bool:
    """是否可进「服务器设置」：标记为管理者，或超级管理员（救急）"""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_server_owner', False):
        return True
    if getattr(user, 'is_superuser', False):
        return True
    return False


# 兼容旧名
user_is_server_owner = user_is_server_manager


def any_server_manager_exists() -> bool:
    from .models import User

    return User.objects.filter(is_server_owner=True).exists()


any_server_owner_exists = any_server_manager_exists


def get_site_settings():
    from .models import ServerSiteSettings

    obj, _ = ServerSiteSettings.objects.get_or_create(
        singleton_id=1,
        defaults={
            'site_name': '野草系统',
            'nav_brand_label': '店铺名录',
            'show_powered_by': True,
        },
    )
    return obj


def get_compliance_settings():
    from .models import SiteComplianceSettings

    obj = SiteComplianceSettings.objects.first()
    if obj is None:
        obj = SiteComplianceSettings(singleton_id=1)
    return obj


def get_server_email_settings():
    from .models import ServerEmailSettings

    obj, _ = ServerEmailSettings.objects.get_or_create(singleton_id=1)
    return obj
