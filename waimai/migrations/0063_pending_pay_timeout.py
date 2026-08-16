# 待支付超时：店铺默认分钟 + 订单截止时间（一份真源）

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0062_community_page'),
    ]

    operations = [
        migrations.AddField(
            model_name='shoppaymentsettings',
            name='pending_pay_timeout_minutes',
            field=models.PositiveIntegerField(
                default=30,
                verbose_name='待支付超时（分钟）',
                help_text='仅微信/演示等先付单。默认 30；最少 5、最多 1440（24 小时）。只影响新单。',
            ),
        ),
        migrations.AddField(
            model_name='buyorder',
            name='pending_pay_deadline',
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name='待支付截止时间',
            ),
        ),
        migrations.AddField(
            model_name='buyorder',
            name='pending_pay_limit_minutes',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name='本单待支付时限（分钟）',
            ),
        ),
        migrations.AlterField(
            model_name='buyorder',
            name='cancel_side',
            field=models.CharField(
                blank=True,
                choices=[('buyer', '买家'), ('shop', '店家'), ('system', '系统')],
                default='',
                max_length=8,
                verbose_name='取消方',
            ),
        ),
    ]
