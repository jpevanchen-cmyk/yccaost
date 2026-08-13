# 下载记账：传输字节 / 时长 / 是否接近传完

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0058_server_home_tier_pages'),
    ]

    operations = [
        migrations.AddField(
            model_name='homeblockdownloadhit',
            name='file_size_bytes',
            field=models.BigIntegerField(default=0, verbose_name='文件标称大小（字节）'),
        ),
        migrations.AddField(
            model_name='homeblockdownloadhit',
            name='bytes_sent',
            field=models.BigIntegerField(default=0, verbose_name='实际发出字节'),
        ),
        migrations.AddField(
            model_name='homeblockdownloadhit',
            name='finished_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='连接结束时间'),
        ),
        migrations.AddField(
            model_name='homeblockdownloadhit',
            name='duration_ms',
            field=models.PositiveIntegerField(default=0, verbose_name='持续毫秒'),
        ),
        migrations.AddField(
            model_name='homeblockdownloadhit',
            name='near_complete',
            field=models.BooleanField(
                default=False,
                help_text='发出量接近文件大小；不等于对方一定存盘成功',
                verbose_name='接近传完',
            ),
        ),
    ]
