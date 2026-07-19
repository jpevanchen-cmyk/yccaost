from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0024_plugin_fulfillment_help_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='active_session_key',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                max_length=64,
                verbose_name='当前有效登录会话',
            ),
        ),
    ]
