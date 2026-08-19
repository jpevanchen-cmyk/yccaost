# 整机公告表；旧服务器介绍/公告积木改为可增删自定义积木

import uuid

from django.db import migrations, models


def forwards_intro_notice_to_custom(apps, schema_editor):
    ServerHomeBlock = apps.get_model('waimai', 'ServerHomeBlock')
    ServerHomeBlock.objects.filter(block_type__in=('intro', 'notice')).update(block_type='custom')


def noop_reverse(apps, schema_editor):
    """不把自定义积木改回介绍/公告，避免误伤后来新加的块。"""
    return


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0064_late_pay_query_and_channel'),
    ]

    operations = [
        migrations.RunPython(forwards_intro_notice_to_custom, noop_reverse),
        migrations.CreateModel(
            name='ServerBulletin',
            fields=[
                ('singleton_id', models.PositiveSmallIntegerField(
                    default=1, editable=False, primary_key=True, serialize=False, verbose_name='固定编号',
                )),
                ('body', models.TextField(blank=True, default='', verbose_name='现行公告正文')),
                ('revision', models.PositiveIntegerField(default=0, verbose_name='现行版本号')),
                ('published_at', models.DateTimeField(blank=True, null=True, verbose_name='最近发布时刻')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '整机现行公告',
                'verbose_name_plural': '整机现行公告',
                'db_table': 'server_bulletin',
            },
        ),
        migrations.CreateModel(
            name='ServerBulletinHistory',
            fields=[
                ('history_id', models.UUIDField(
                    default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='记录ID',
                )),
                ('body', models.TextField(verbose_name='当时正文')),
                ('revision', models.PositiveIntegerField(default=0, verbose_name='当时版本号')),
                ('archived_at', models.DateTimeField(db_index=True, verbose_name='收入历史的时刻')),
                ('bulletin', models.ForeignKey(
                    on_delete=models.CASCADE,
                    related_name='history_rows',
                    to='waimai.serverbulletin',
                    verbose_name='现行公告',
                )),
            ],
            options={
                'verbose_name': '整机公告历史',
                'verbose_name_plural': '整机公告历史',
                'db_table': 'server_bulletin_history',
                'ordering': ['-archived_at'],
            },
        ),
    ]
