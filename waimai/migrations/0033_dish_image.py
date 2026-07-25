# 批次 G · G1-2：商品多图表 + 压缩上传

import uuid

from django.db import migrations, models
import waimai.models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0032_dish_display_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='DishImage',
            fields=[
                ('image_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='图片ID')),
                ('seller_id', models.CharField(db_index=True, max_length=64, verbose_name='卖家ID')),
                ('display_code', models.CharField(max_length=5, verbose_name='展示编号')),
                ('sort_index', models.PositiveSmallIntegerField(verbose_name='展示序号')),
                ('image', models.ImageField(max_length=300, upload_to=waimai.models.dish_image_upload_to, verbose_name='图片文件')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='上传时间')),
                ('dish', models.ForeignKey(on_delete=models.CASCADE, related_name='product_images', to='waimai.dish', verbose_name='所属商品')),
            ],
            options={
                'verbose_name': '商品图片',
                'verbose_name_plural': '商品图片',
                'db_table': 'dish_image',
                'ordering': ['sort_index'],
            },
        ),
        migrations.AddConstraint(
            model_name='dishimage',
            constraint=models.UniqueConstraint(fields=('dish', 'sort_index'), name='uniq_dish_image_sort_per_dish'),
        ),
    ]
