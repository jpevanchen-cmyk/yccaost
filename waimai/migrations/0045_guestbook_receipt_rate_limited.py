# 留言板：收条邮件防刷上限字段

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0044_guestbook_formal'),
    ]

    operations = [
        migrations.AddField(
            model_name='guestbookthread',
            name='receipt_email_rate_limited',
            field=models.BooleanField(
                default=False,
                verbose_name='收条邮件因防刷上限未发',
            ),
        ),
    ]
