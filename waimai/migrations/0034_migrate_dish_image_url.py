# 批次 G · G1-5：旧 image_url 外链迁移落盘 + 字段废止

from django.db import migrations, models


def migrate_legacy_dish_image_urls_forward(apps, schema_editor):
    """部署 migrate 时自动把仍有价值的外链下载到本地并清空字段。"""
    from waimai.product_image_helpers import migrate_all_legacy_dish_image_urls

    migrate_all_legacy_dish_image_urls()


def normalize_null_image_urls(apps, schema_editor):
    """URLField 改 CharField 前，把 null 统一成空串。"""
    Dish = apps.get_model('waimai', 'Dish')
    Dish.objects.filter(image_url__isnull=True).update(image_url='')


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0033_dish_image'),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_dish_image_urls_forward, migrations.RunPython.noop),
        migrations.RunPython(normalize_null_image_urls, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='dish',
            name='image_url',
            field=models.CharField(
                blank=True,
                default='',
                help_text='历史外链迁移后留空；运行时只认本地商品图文件夹。',
                max_length=500,
                verbose_name='菜品图片链接（已废止）',
            ),
        ),
    ]
