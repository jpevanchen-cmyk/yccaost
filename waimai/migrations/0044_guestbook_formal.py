# Generated manually · 留言板迁入 waimai 正式功能

import uuid

from django.db import migrations, models


def _column_names(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        return {
            col.name for col in schema_editor.connection.introspection.get_table_description(
                cursor, table,
            )
        }


def _add_guestbook_columns(apps, schema_editor):
    """在已有 owner_toolkit 表上补字段；新库则跳过（由 owner_toolkit 迁移建表）"""
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())
    if 'owner_guestbook_thread' not in tables:
        return

    Thread = apps.get_model('waimai', 'GuestbookThread')
    table = Thread._meta.db_table
    existing = _column_names(schema_editor, table)

    additions = [
        ('public_code', 'varchar(20) NOT NULL DEFAULT \'\'' ),
        ('guest_password_hash', 'varchar(128) NOT NULL DEFAULT \'\'' ),
        ('receipt_email_failed', 'bool NOT NULL DEFAULT 0'),
        ('email_delivery_suspect', 'bool NOT NULL DEFAULT 0'),
    ]
    if connection.vendor == 'postgresql':
        for col, typedef in additions:
            if col not in existing:
                schema_editor.execute(
                    f'ALTER TABLE {table} ADD COLUMN {col} {typedef.replace("bool", "boolean")}',
                )
    else:
        # SQLite
        for col, typedef in additions:
            if col not in existing:
                schema_editor.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typedef}')

    # 为旧数据补编号
    import secrets
    import string

    from django.utils import timezone
    from zoneinfo import ZoneInfo

    chars = string.ascii_letters + string.digits
    mmdd = timezone.now().astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m%d')
    prefix = f'YC-{mmdd}-'

    for thread in Thread.objects.filter(public_code=''):
        for _ in range(80):
            suffix = ''.join(secrets.choice(chars) for _ in range(8))
            code = f'{prefix}{suffix}'
            if not Thread.objects.filter(public_code=code).exists():
                thread.public_code = code
                thread.save(update_fields=['public_code'])
                break


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0043_order_catalog_sales'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='GuestbookSettings',
                    fields=[
                        ('singleton_id', models.PositiveSmallIntegerField(
                            default=1, editable=False, primary_key=True, serialize=False,
                            verbose_name='固定编号',
                        )),
                        ('public_display_name', models.CharField(
                            blank=True, default='', max_length=80, verbose_name='对外名称',
                        )),
                        ('public_contact_email', models.CharField(
                            blank=True, default='', max_length=254, verbose_name='联系邮箱',
                        )),
                        ('block_intro', models.TextField(
                            blank=True, default='', help_text='显示在服务器主页「联系我们」积木中',
                            verbose_name='联系我们说明',
                        )),
                        ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                    ],
                    options={
                        'verbose_name': '联系我们设置',
                        'verbose_name_plural': '联系我们设置',
                        'db_table': 'owner_guestbook_settings',
                    },
                ),
                migrations.CreateModel(
                    name='GuestbookThread',
                    fields=[
                        ('thread_id', models.UUIDField(
                            default=uuid.uuid4, editable=False, primary_key=True,
                            serialize=False, verbose_name='主题ID',
                        )),
                        ('public_code', models.CharField(
                            blank=True, db_index=True, default='', max_length=20, unique=True,
                            verbose_name='对外留言编号',
                        )),
                        ('guest_display_name', models.CharField(
                            blank=True, default='', max_length=80, verbose_name='访客称呼',
                        )),
                        ('guest_email', models.CharField(
                            blank=True, default='', max_length=254, verbose_name='访客邮箱',
                        )),
                        ('guest_user_id', models.CharField(
                            blank=True, default='', max_length=64, verbose_name='登录账号快照',
                        )),
                        ('guest_actor_key', models.CharField(
                            blank=True, db_index=True, default='', max_length=80,
                            verbose_name='留言身份键',
                        )),
                        ('guest_password_hash', models.CharField(
                            blank=True, default='', max_length=128, verbose_name='查看密码（加密）',
                        )),
                        ('author_ip', models.GenericIPAddressField(
                            blank=True, null=True, verbose_name='首次留言IP',
                        )),
                        ('receipt_email_failed', models.BooleanField(
                            default=False, verbose_name='收条邮件当场发送失败',
                        )),
                        ('email_delivery_suspect', models.BooleanField(
                            default=False, verbose_name='邮箱可能无法收信',
                        )),
                        ('created_at', models.DateTimeField(
                            auto_now_add=True, db_index=True, verbose_name='创建时间',
                        )),
                        ('last_activity_at', models.DateTimeField(
                            auto_now=True, db_index=True, verbose_name='最后活动时间',
                        )),
                        ('owner_read_at', models.DateTimeField(
                            blank=True, null=True, verbose_name='管理者已读时间',
                        )),
                    ],
                    options={
                        'verbose_name': '留言主题',
                        'verbose_name_plural': '留言主题',
                        'db_table': 'owner_guestbook_thread',
                        'ordering': ['-last_activity_at'],
                    },
                ),
                migrations.CreateModel(
                    name='GuestbookMessage',
                    fields=[
                        ('message_id', models.UUIDField(
                            default=uuid.uuid4, editable=False, primary_key=True,
                            serialize=False, verbose_name='消息ID',
                        )),
                        ('author_side', models.CharField(
                            choices=[('guest', '访客'), ('owner', '管理者')],
                            db_index=True, max_length=8, verbose_name='发言方',
                        )),
                        ('author_label', models.CharField(
                            blank=True, default='', max_length=80, verbose_name='显示名快照',
                        )),
                        ('body', models.CharField(max_length=1000, verbose_name='内容')),
                        ('created_at', models.DateTimeField(
                            auto_now_add=True, db_index=True, verbose_name='发送时间',
                        )),
                        ('guest_notified', models.BooleanField(
                            default=False, verbose_name='已邮件通知访客',
                        )),
                        ('thread', models.ForeignKey(
                            on_delete=models.deletion.CASCADE, related_name='messages',
                            to='waimai.guestbookthread', verbose_name='所属主题',
                        )),
                    ],
                    options={
                        'verbose_name': '留言消息',
                        'verbose_name_plural': '留言消息',
                        'db_table': 'owner_guestbook_message',
                        'ordering': ['created_at'],
                    },
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(_add_guestbook_columns, _noop_reverse),
    ]
