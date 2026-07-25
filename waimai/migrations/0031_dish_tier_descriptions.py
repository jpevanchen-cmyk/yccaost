# 批次 H1：商品普通/会员/特价三描述框；原 description 即为普通描述，无需迁数据。

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0030_email_backup_sender'),
    ]

    operations = [
        migrations.AlterField(
            model_name='dish',
            name='description',
            field=models.TextField(blank=True, verbose_name='普通描述'),
        ),
        migrations.AddField(
            model_name='dish',
            name='description_member',
            field=models.TextField(blank=True, verbose_name='会员描述'),
        ),
        migrations.AddField(
            model_name='dish',
            name='description_special',
            field=models.TextField(blank=True, verbose_name='特价描述'),
        ),
    ]
