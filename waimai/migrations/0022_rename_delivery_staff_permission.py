from django.db import migrations


def rename_delivery_permission(apps, schema_editor):
    """配送权限使用履约层稳定编号，不继续绑在饮食插件名下。"""
    User = apps.get_model('waimai', 'User')
    for user in User.objects.filter(role='staff').iterator():
        permissions = list(user.staff_permissions or [])
        if 'dining.rider' not in permissions:
            continue
        permissions = [
            'fulfillment.delivery' if code == 'dining.rider' else code
            for code in permissions
        ]
        user.staff_permissions = sorted(set(permissions))
        user.save(update_fields=['staff_permissions'])


def restore_old_delivery_permission(apps, schema_editor):
    User = apps.get_model('waimai', 'User')
    for user in User.objects.filter(role='staff').iterator():
        permissions = list(user.staff_permissions or [])
        if 'fulfillment.delivery' not in permissions:
            continue
        permissions = [
            'dining.rider' if code == 'fulfillment.delivery' else code
            for code in permissions
        ]
        user.staff_permissions = sorted(set(permissions))
        user.save(update_fields=['staff_permissions'])


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0021_staff_account_target_model'),
    ]

    operations = [
        migrations.RunPython(rename_delivery_permission, restore_old_delivery_permission),
    ]
