# 服务器主页分级分流：大厅 + 二级专题页字段

import django.db.models.deletion
from django.db import migrations, models


def forwards_seed_hall(apps, schema_editor):
    ServerHomePage = apps.get_model('waimai', 'ServerHomePage')
    hall = ServerHomePage.objects.filter(pk=1).first()
    if hall is None:
        ServerHomePage.objects.create(
            singleton_id=1,
            page_role='hall',
            slug='',
            title='一级大厅',
            welcome_body='',
            welcome_enabled=True,
        )
    else:
        ServerHomePage.objects.filter(pk=1).update(
            page_role='hall',
            slug='',
            title=(hall.title or '').strip() or '一级大厅',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0057_server_home_file_download_block'),
    ]

    operations = [
        migrations.AlterField(
            model_name='serverhomepage',
            name='singleton_id',
            field=models.PositiveIntegerField(primary_key=True, serialize=False, verbose_name='页编号'),
        ),
        migrations.AddField(
            model_name='serverhomepage',
            name='page_role',
            field=models.CharField(
                choices=[('hall', '一级大厅'), ('topic', '二级专题页')],
                db_index=True,
                default='hall',
                max_length=16,
                verbose_name='页角色',
            ),
        ),
        migrations.AddField(
            model_name='serverhomepage',
            name='slug',
            field=models.SlugField(blank=True, default='', help_text='二级页网址用；大厅留空', max_length=48, verbose_name='短名'),
        ),
        migrations.AddField(
            model_name='serverhomepage',
            name='title',
            field=models.CharField(blank=True, default='', max_length=80, verbose_name='页标题'),
        ),
        migrations.AddField(
            model_name='serverhomepage',
            name='welcome_body',
            field=models.TextField(blank=True, default='', verbose_name='欢迎弹窗正文'),
        ),
        migrations.AddField(
            model_name='serverhomepage',
            name='welcome_enabled',
            field=models.BooleanField(default=True, verbose_name='启用欢迎弹窗'),
        ),
        migrations.RunPython(forwards_seed_hall, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='serverhomepage',
            constraint=models.UniqueConstraint(
                condition=models.Q(('page_role', 'hall')),
                fields=('page_role',),
                name='uniq_server_home_page_hall',
            ),
        ),
        migrations.AddConstraint(
            model_name='serverhomepage',
            constraint=models.UniqueConstraint(
                condition=models.Q(('slug', ''), _negated=True),
                fields=('slug',),
                name='uniq_server_home_page_slug',
            ),
        ),
        migrations.AlterField(
            model_name='serverhomeblock',
            name='home_page',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='blocks',
                to='waimai.serverhomepage',
                verbose_name='所属服务器主页',
            ),
        ),
    ]
