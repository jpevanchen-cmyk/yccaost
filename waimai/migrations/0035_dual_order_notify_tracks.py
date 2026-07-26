# 批次 H3：老板邮件与值班防漏单分轨

from django.db import migrations, models


def copy_legacy_order_notify(apps, schema_editor):
    """旧「新订单邮件通知」迁入老板轨（原在员工工作台管理里配置）。"""
    ShopOperatingSettings = apps.get_model('waimai', 'ShopOperatingSettings')
    for row in ShopOperatingSettings.objects.all():
        if row.order_notify_enabled or (row.order_notify_email or '').strip():
            row.boss_order_notify_enabled = bool(row.order_notify_enabled)
            row.boss_order_notify_email = (row.order_notify_email or '').strip()
            row.save(
                update_fields=['boss_order_notify_enabled', 'boss_order_notify_email'],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0034_migrate_dish_image_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='boss_order_notify_enabled',
            field=models.BooleanField(default=False, verbose_name='开启老板新订单邮件'),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='boss_order_notify_email',
            field=models.CharField(
                blank=True, default='', max_length=255,
                verbose_name='老板新订单收件邮箱（多个用逗号分隔）',
            ),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='duty_order_notify_enabled',
            field=models.BooleanField(default=False, verbose_name='开启值班防漏单邮件'),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='duty_order_notify_email',
            field=models.CharField(
                blank=True, default='', max_length=255,
                verbose_name='值班防漏单收件邮箱（多个用逗号分隔）',
            ),
        ),
        migrations.RunPython(copy_legacy_order_notify, migrations.RunPython.noop),
    ]
