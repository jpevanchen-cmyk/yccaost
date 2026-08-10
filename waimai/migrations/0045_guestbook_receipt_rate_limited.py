# 留言板：收条邮件防刷上限字段（主程序正式功能）
# 可幂等：无表则先建齐（照顾 0044 已记 applied 但未建表的试装库）；有列则跳过。

from django.db import migrations, models


def _column_names(schema_editor, table):
    with schema_editor.connection.cursor() as cursor:
        return {
            col.name for col in schema_editor.connection.introspection.get_table_description(
                cursor, table,
            )
        }


def _noop_reverse(apps, schema_editor):
    pass


def _ensure_receipt_rate_limited(apps, schema_editor):
    """保证主题表存在并拥有 receipt_email_rate_limited 列。"""
    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())

    # 试装若卡在 0044「已登记未建表」，这里补建
    if 'owner_guestbook_thread' not in tables:
        GuestbookSettings = apps.get_model('waimai', 'GuestbookSettings')
        GuestbookThread = apps.get_model('waimai', 'GuestbookThread')
        GuestbookMessage = apps.get_model('waimai', 'GuestbookMessage')
        schema_editor.create_model(GuestbookSettings)
        schema_editor.create_model(GuestbookThread)
        schema_editor.create_model(GuestbookMessage)
        tables = set(connection.introspection.table_names())

    if 'owner_guestbook_thread' not in tables:
        return

    table = 'owner_guestbook_thread'
    existing = _column_names(schema_editor, table)
    if 'receipt_email_rate_limited' in existing:
        return

    if connection.vendor == 'postgresql':
        schema_editor.execute(
            f'ALTER TABLE {table} ADD COLUMN receipt_email_rate_limited boolean NOT NULL DEFAULT false',
        )
    else:
        schema_editor.execute(
            f'ALTER TABLE {table} ADD COLUMN receipt_email_rate_limited bool NOT NULL DEFAULT 0',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0044_guestbook_formal'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='guestbookthread',
                    name='receipt_email_rate_limited',
                    field=models.BooleanField(
                        default=False,
                        verbose_name='收条邮件因防刷上限未发',
                    ),
                ),
            ],
            database_operations=[
                migrations.RunPython(_ensure_receipt_rate_limited, _noop_reverse),
            ],
        ),
    ]
