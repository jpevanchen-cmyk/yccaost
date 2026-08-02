# 入金申请邮件双轨：老板轨 + 值班轨

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0040_order_timeline_and_progress83'),
    ]

    operations = [
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='boss_remittance_notify_enabled',
            field=models.BooleanField(default=False, verbose_name='开启老板入金申请邮件'),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='boss_remittance_notify_email',
            field=models.CharField(
                blank=True, default='', max_length=255,
                verbose_name='老板入金申请收件邮箱（多个用逗号分隔）',
            ),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='duty_remittance_notify_enabled',
            field=models.BooleanField(default=False, verbose_name='开启值班入金申请邮件'),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='duty_remittance_notify_email',
            field=models.CharField(
                blank=True, default='', max_length=255,
                verbose_name='值班入金申请收件邮箱（多个用逗号分隔）',
            ),
        ),
    ]
