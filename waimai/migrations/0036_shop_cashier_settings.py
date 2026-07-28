# 实体收银台第一期：支付设置开关、分页、渠道记忆

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0035_dual_order_notify_tracks'),
    ]

    operations = [
        migrations.AddField(
            model_name='shoppaymentsettings',
            name='enable_cashier',
            field=models.BooleanField(default=False, verbose_name='启用实体收银台'),
        ),
        migrations.AddField(
            model_name='shoppaymentsettings',
            name='cashier_page_size',
            field=models.PositiveSmallIntegerField(default=10, verbose_name='收银台每页条数'),
        ),
        migrations.AddField(
            model_name='shoppaymentsettings',
            name='cashier_channel_memory',
            field=models.JSONField(blank=True, default=list, verbose_name='收银台渠道记忆'),
        ),
    ]
