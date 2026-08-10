# 资金流水：新增「待到账」状态（微信扫码等待阶段）

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0055_wechat_refund_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='fundledgerentry',
            name='fund_status',
            field=models.CharField(
                blank=True,
                choices=[
                    ('not_applicable', '不涉及真钱'),
                    ('pending_arrival', '待到账'),
                    ('customer_paid', '客人侧已付'),
                    ('in_transit', '在途'),
                    ('at_shop', '已到店铺'),
                    ('written_off', '未收款结案'),
                ],
                default='',
                max_length=32,
                verbose_name='资金状态',
            ),
        ),
    ]
