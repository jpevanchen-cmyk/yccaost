# 服务器主页「文件下载」积木 + 下载记账表

import django.core.validators
import uuid
import waimai.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0056_fund_status_pending_arrival'),
    ]

    operations = [
        migrations.CreateModel(
            name='HomeBlockDownloadHit',
            fields=[
                ('hit_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='记录ID')),
                ('block_id', models.UUIDField(db_index=True, verbose_name='积木块ID')),
                ('block_title', models.CharField(blank=True, default='', max_length=120, verbose_name='标题快照')),
                ('original_filename', models.CharField(blank=True, default='', max_length=255, verbose_name='文件名快照')),
                ('ip', models.GenericIPAddressField(blank=True, db_index=True, null=True, verbose_name='IP')),
                ('user_agent', models.CharField(blank=True, default='', max_length=300, verbose_name='浏览器标识')),
                ('clicked_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='点击时间')),
            ],
            options={
                'verbose_name': '主页下载点击',
                'verbose_name_plural': '主页下载点击',
                'db_table': 'home_block_download_hit',
                'ordering': ['-clicked_at'],
            },
        ),
        migrations.RemoveConstraint(
            model_name='serverhomeblock',
            name='uniq_server_home_block_type_non_custom',
        ),
        migrations.AddField(
            model_name='serverhomeblock',
            name='download_file',
            field=models.FileField(
                blank=True,
                upload_to=waimai.models.home_block_download_upload_to,
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=['7z', 'exe', 'msi', 'pdf', 'rar', 'zip'],
                    ),
                    waimai.models.validate_home_block_download_size,
                ],
                verbose_name='下载附件',
            ),
        ),
        migrations.AddConstraint(
            model_name='serverhomeblock',
            constraint=models.UniqueConstraint(
                condition=models.Q(('block_type__in', ['custom', 'file_download']), _negated=True),
                fields=('home_page', 'block_type'),
                name='uniq_server_home_block_type_non_custom',
            ),
        ),
    ]
