# V1 首次向导：站点级安装完成标记与网络/备份配置

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0050_server_site_install_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='serversitesettings',
            name='v1_setup_completed',
            field=models.BooleanField(
                default=False,
                db_index=True,
                verbose_name='V1 首次向导已完成',
            ),
        ),
        migrations.AddField(
            model_name='serversitesettings',
            name='v1_listen_port',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name='V1 监听端口',
            ),
        ),
        migrations.AddField(
            model_name='serversitesettings',
            name='v1_lan_base_url',
            field=models.CharField(
                blank=True,
                default='',
                max_length=255,
                verbose_name='V1 本机局域网访问地址',
            ),
        ),
        migrations.AddField(
            model_name='serversitesettings',
            name='v1_backup_dir',
            field=models.CharField(
                blank=True,
                default='',
                max_length=500,
                verbose_name='V1 备份目录',
            ),
        ),
    ]
