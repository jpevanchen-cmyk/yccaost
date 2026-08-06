# 删除商品旧外链字段（G1-5 已完成；真源仅为本地 DishImage）

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0047_drop_order_timeline_event'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='dish',
            name='image_url',
        ),
    ]
