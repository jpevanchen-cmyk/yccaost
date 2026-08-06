# 删除订单历程表（进度展示已改为只读 BuyOrder / DeliveryOrder 真源字段）

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0046_idempotency_record'),
    ]

    operations = [
        migrations.DeleteModel(
            name='OrderTimelineEvent',
        ),
    ]
