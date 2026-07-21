# 备用发信字段 + 发信记录通道标记

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0029_email_send_log'),
    ]

    operations = [
        migrations.AddField(
            model_name='serveremailsettings',
            name='backup_from_email',
            field=models.CharField(blank=True, default='', max_length=254, verbose_name='备用发件人邮箱'),
        ),
        migrations.AddField(
            model_name='serveremailsettings',
            name='backup_smtp_host',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='备用 SMTP 地址'),
        ),
        migrations.AddField(
            model_name='serveremailsettings',
            name='backup_smtp_password',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='备用 SMTP 密码'),
        ),
        migrations.AddField(
            model_name='serveremailsettings',
            name='backup_smtp_port',
            field=models.PositiveIntegerField(default=465, verbose_name='备用 SMTP 端口'),
        ),
        migrations.AddField(
            model_name='serveremailsettings',
            name='backup_smtp_user',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='备用 SMTP 账号'),
        ),
        migrations.AddField(
            model_name='serveremailsettings',
            name='backup_use_ssl',
            field=models.BooleanField(default=True, verbose_name='备用使用 SSL'),
        ),
        migrations.AddField(
            model_name='serveremailsettings',
            name='backup_use_tls',
            field=models.BooleanField(default=False, verbose_name='备用使用 STARTTLS'),
        ),
        migrations.AddField(
            model_name='emailsendlog',
            name='sender_route',
            field=models.CharField(
                blank=True, default='', help_text='primary 主邮箱；backup 备用邮箱',
                max_length=16, verbose_name='发信通道',
            ),
        ),
    ]
