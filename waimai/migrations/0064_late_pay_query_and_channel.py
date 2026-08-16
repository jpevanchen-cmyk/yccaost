# 取消后追问支付机构：记下最近一次查单时间（间隔用，不是第二份到账事实）

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0063_pending_pay_timeout'),
    ]

    operations = [
        migrations.AddField(
            model_name='buyorder',
            name='late_pay_last_query_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='取消后最近一次向支付机构查单时间',
            ),
        ),
    ]
