# V1 本地营业内测：服务器站点设置增加安装模式字段

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0049_fund_ledger'),
    ]

    operations = [
        migrations.AddField(
            model_name='serversitesettings',
            name='install_mode',
            field=models.CharField(
                choices=[
                    ('standard', '标准（完整功能）'),
                    ('v1_local', '本地营业内测版 V1.0'),
                ],
                db_index=True,
                default='standard',
                max_length=16,
                verbose_name='安装模式',
            ),
        ),
    ]
