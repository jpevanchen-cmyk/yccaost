# V1 桌台会话：专属加点码字段

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0052_operation_lock'),
    ]

    operations = [
        migrations.AddField(
            model_name='tablesession',
            name='addon_token',
            field=models.CharField(
                blank=True,
                default=None,
                max_length=32,
                null=True,
                unique=True,
                verbose_name='专属加点码令牌',
            ),
        ),
    ]
