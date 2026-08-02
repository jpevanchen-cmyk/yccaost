# 进度 79：清单可售名额 · 付款后占用

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0042_menu_general_price_listed'),
    ]

    operations = [
        migrations.AddField(
            model_name='buyorder',
            name='catalog_sales_applied',
            field=models.BooleanField(default=False, verbose_name='清单可售名额已占用'),
        ),
        migrations.AddField(
            model_name='buyorder',
            name='catalog_sales_detail',
            field=models.JSONField(blank=True, default=dict, verbose_name='清单已占用明细（按菜品件数）'),
        ),
    ]
