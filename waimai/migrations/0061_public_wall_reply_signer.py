# 公开墙楼下回：署名 + 说明/回复（与正文同一条，展示时再拼）

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0060_public_wall'),
    ]

    operations = [
        migrations.AddField(
            model_name='publicwallreply',
            name='signer_name',
            field=models.CharField(
                blank=True,
                default='',
                help_text='手填，如管理员、外卖大叔；空则按管理员显示',
                max_length=40,
                verbose_name='对外署名',
            ),
        ),
        migrations.AddField(
            model_name='publicwallreply',
            name='suffix_kind',
            field=models.CharField(
                blank=True,
                choices=[('note', '说明'), ('reply', '回复')],
                default='',
                help_text='note=说明（藏/删）；reply=回复（正常回）；旧条为空则按说明',
                max_length=16,
                verbose_name='后缀种类',
            ),
        ),
    ]
