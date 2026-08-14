# 公开留言壁：独立两张表（与联系我们私信分轨）

import django.db.models.deletion
import uuid
import waimai.time_helpers
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0059_home_block_download_transfer_stats'),
    ]

    operations = [
        migrations.CreateModel(
            name='PublicWallPost',
            fields=[
                ('post_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='留言ID')),
                ('floor_no', models.PositiveIntegerField(db_index=True, help_text='先发的是 1 楼；不因最新在上而重排', unique=True, verbose_name='楼号')),
                ('body', models.CharField(max_length=500, verbose_name='正文')),
                ('display_name', models.CharField(max_length=80, verbose_name='对外显示名')),
                ('nickname_input', models.CharField(blank=True, default='', max_length=80, verbose_name='当时填写的昵称')),
                ('is_anonymous', models.BooleanField(default=False, verbose_name='当时勾选匿名')),
                ('actor_key', models.CharField(blank=True, db_index=True, default='', help_text='已登录用账号；未登录用浏览器访客编号，用于按人限流', max_length=80, verbose_name='发言身份键')),
                ('author_user_id', models.CharField(blank=True, default='', max_length=64, verbose_name='登录账号快照')),
                ('author_ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='发言IP')),
                ('status', models.CharField(choices=[('visible', '正常'), ('hidden', '已隐藏'), ('deleted', '已删除')], db_index=True, default='visible', max_length=16, verbose_name='状态')),
                ('created_at', models.DateTimeField(db_index=True, default=waimai.time_helpers.now_local_wall, verbose_name='发言时间')),
            ],
            options={
                'verbose_name': '公开留言壁楼',
                'verbose_name_plural': '公开留言壁楼',
                'db_table': 'public_wall_post',
                'ordering': ['-floor_no'],
            },
        ),
        migrations.CreateModel(
            name='PublicWallReply',
            fields=[
                ('reply_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='回复ID')),
                ('body', models.CharField(max_length=500, verbose_name='说明正文')),
                ('created_at', models.DateTimeField(db_index=True, default=waimai.time_helpers.now_local_wall, verbose_name='说明时间')),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='replies', to='waimai.publicwallpost', verbose_name='所属楼')),
            ],
            options={
                'verbose_name': '公开留言壁管理者说明',
                'verbose_name_plural': '公开留言壁管理者说明',
                'db_table': 'public_wall_reply',
                'ordering': ['created_at'],
            },
        ),
    ]
