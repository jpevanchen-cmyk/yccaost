# 主体基础交易通道：订单新增「下单」取餐/履约类型

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0019_plugin_dining_enabled'),
    ]

    operations = [
        migrations.AlterField(
            model_name='buyorder',
            name='fulfillment_type',
            field=models.CharField(
                choices=[
                    ('order', '下单'),
                    ('delivery', '外卖'),
                    ('dine_in', '堂食'),
                    ('takeaway', '打包'),
                ],
                db_index=True,
                default='order',
                max_length=16,
                verbose_name='取餐方式',
            ),
        ),
    ]
