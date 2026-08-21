# 店铺注销第一刀：店铺资料增加注销时间

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0066_guest_remote_checkout_67_1'),
    ]

    operations = [
        migrations.AddField(
            model_name='shopprofile',
            name='cancelled_at',
            field=models.DateTimeField(
                blank=True, db_index=True, null=True, verbose_name='店铺注销时间',
            ),
        ),
    ]
