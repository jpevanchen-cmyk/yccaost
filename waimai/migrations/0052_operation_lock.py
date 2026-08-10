# V1 操作锁：服务器站点字段

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0051_v1_setup_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='serversitesettings',
            name='operation_lock_enabled',
            field=models.BooleanField(
                default=False,
                verbose_name='启用操作锁（店主后台+服务器设置）',
            ),
        ),
        migrations.AddField(
            model_name='serversitesettings',
            name='operation_lock_idle_seconds',
            field=models.PositiveIntegerField(
                default=300,
                verbose_name='操作锁空闲自动锁定时长（秒）',
            ),
        ),
        migrations.AddField(
            model_name='serversitesettings',
            name='operation_lock_pin_salt',
            field=models.CharField(
                blank=True,
                default='',
                max_length=64,
                verbose_name='操作锁 PIN 盐',
            ),
        ),
        migrations.AddField(
            model_name='serversitesettings',
            name='operation_lock_pin_hash',
            field=models.CharField(
                blank=True,
                default='',
                max_length=128,
                verbose_name='操作锁 PIN 哈希',
            ),
        ),
    ]
