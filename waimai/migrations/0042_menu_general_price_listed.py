# 进度 78：清单三档展示开关 · 补通用价展示控制

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0041_remittance_notify'),
    ]

    operations = [
        migrations.AddField(
            model_name='menuprofileitem',
            name='general_price_listed',
            field=models.BooleanField(default=True, verbose_name='本清单展示通用价'),
        ),
    ]
