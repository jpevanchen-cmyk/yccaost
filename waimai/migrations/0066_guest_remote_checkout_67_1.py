# 进度 67-①：游客打包/外卖未登录下单（店铺开关 + 本单联系信息）

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0065_server_bulletin_and_custom_intro'),
    ]

    operations = [
        migrations.AddField(
            model_name='buyorder',
            name='guest_contact_email',
            field=models.CharField(blank=True, default='', max_length=254, verbose_name='游客本单邮箱'),
        ),
        migrations.AddField(
            model_name='buyorder',
            name='guest_contact_name',
            field=models.CharField(blank=True, default='', max_length=40, verbose_name='游客本单姓名'),
        ),
        migrations.AddField(
            model_name='buyorder',
            name='guest_contact_phone',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='游客本单电话'),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='guest_delivery_cod_enabled',
            field=models.BooleanField(default=False, verbose_name='允许未登录顾客外卖货到付款'),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='guest_delivery_online_enabled',
            field=models.BooleanField(default=False, verbose_name='允许未登录顾客外卖在线支付'),
        ),
        migrations.AddField(
            model_name='shopoperatingsettings',
            name='guest_takeaway_enabled',
            field=models.BooleanField(default=False, verbose_name='允许未登录顾客打包自取'),
        ),
    ]
