# 发信记录表：邮件防刷计数

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0028_server_email_and_buyer_notify'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailSendLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recipient', models.EmailField(db_index=True, verbose_name='收件邮箱')),
                ('kind', models.CharField(db_index=True, max_length=32, verbose_name='通知类型')),
                ('dedupe_key', models.CharField(
                    blank=True, db_index=True, default='', max_length=128, verbose_name='去重键',
                )),
                ('sent_at', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='发送时间')),
            ],
            options={
                'verbose_name': '发信记录',
                'verbose_name_plural': '发信记录',
                'db_table': 'email_send_log',
                'ordering': ['-sent_at'],
            },
        ),
    ]
