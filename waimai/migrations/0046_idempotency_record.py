# 写操作幂等记录表（进度 80 · 幂等第 1 步）

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0045_guestbook_receipt_rate_limited'),
    ]

    operations = [
        migrations.CreateModel(
            name='IdempotencyRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scope', models.CharField(
                    db_index=True, default='', help_text='区分不同业务，如 shop_cart、seller_menu',
                    max_length=128, verbose_name='作用域',
                )),
                ('idempotency_key', models.CharField(db_index=True, max_length=128, verbose_name='幂等键')),
                ('state', models.CharField(
                    choices=[('pending', '处理中'), ('completed', '已完成')],
                    db_index=True, default='pending', max_length=16,
                )),
                ('response_status', models.PositiveSmallIntegerField(default=200, verbose_name='HTTP 状态码')),
                ('response_body', models.TextField(blank=True, default='', verbose_name='响应正文')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='创建时间')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='完成时间')),
                ('expires_at', models.DateTimeField(db_index=True, verbose_name='过期时间')),
            ],
            options={
                'verbose_name': '幂等记录',
                'verbose_name_plural': '幂等记录',
                'db_table': 'idempotency_record',
            },
        ),
        migrations.AddConstraint(
            model_name='idempotencyrecord',
            constraint=models.UniqueConstraint(
                fields=('scope', 'idempotency_key'),
                name='uniq_idempotency_scope_key',
            ),
        ),
    ]
