# Generated manually for JB-EM / J-A+

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0027_alter_buyorder_cash_shortfall_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServerEmailSettings',
            fields=[
                ('singleton_id', models.PositiveSmallIntegerField(
                    default=1, editable=False, primary_key=True, serialize=False, verbose_name='固定编号',
                )),
                ('smtp_host', models.CharField(blank=True, default='', max_length=200, verbose_name='SMTP 地址')),
                ('smtp_port', models.PositiveIntegerField(default=465, verbose_name='SMTP 端口')),
                ('smtp_user', models.CharField(blank=True, default='', max_length=200, verbose_name='SMTP 账号')),
                ('smtp_password', models.CharField(blank=True, default='', max_length=200, verbose_name='SMTP 密码')),
                ('from_email', models.CharField(
                    blank=True, default='', help_text='留空则使用 SMTP 账号作为发件地址',
                    max_length=254, verbose_name='发件人邮箱',
                )),
                ('use_tls', models.BooleanField(default=False, verbose_name='使用 STARTTLS（常见端口 587）')),
                ('use_ssl', models.BooleanField(default=True, verbose_name='使用 SSL（常见端口 465）')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '服务器发信设置',
                'verbose_name_plural': '服务器发信设置',
                'db_table': 'server_email_settings',
            },
        ),
        migrations.AddField(
            model_name='user',
            name='buyer_notify_enabled',
            field=models.BooleanField(default=False, verbose_name='开启订单邮件通知'),
        ),
        migrations.AddField(
            model_name='user',
            name='buyer_notify_email',
            field=models.CharField(blank=True, default='', max_length=254, verbose_name='订单通知收件邮箱'),
        ),
    ]
