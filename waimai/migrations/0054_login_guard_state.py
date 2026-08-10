# V1 第 8 项：登录防试密码状态表

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0053_table_session_addon_token'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginGuardState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scope', models.CharField(db_index=True, max_length=32, verbose_name='登录口')),
                ('guard_key', models.CharField(max_length=128, verbose_name='锁定键')),
                ('fail_count', models.PositiveIntegerField(default=0, verbose_name='连续失败次数')),
                ('locked_until', models.DateTimeField(blank=True, db_index=True, null=True, verbose_name='暂锁至')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '登录防试状态',
                'verbose_name_plural': '登录防试状态',
                'db_table': 'login_guard_state',
            },
        ),
        migrations.AddConstraint(
            model_name='loginguardstate',
            constraint=models.UniqueConstraint(fields=('scope', 'guard_key'), name='login_guard_scope_key_uniq'),
        ),
    ]
