# 进度 83：订单历程表 + 交付/完成/开始送餐时间戳

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0039_home_block_link_label'),
    ]

    operations = [
        migrations.AddField(
            model_name='buyorder',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='订单完成时间'),
        ),
        migrations.AddField(
            model_name='buyorder',
            name='goods_delivered_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='商品全部交付时间'),
        ),
        migrations.AddField(
            model_name='deliveryorder',
            name='in_transit_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='开始送餐时间'),
        ),
        migrations.CreateModel(
            name='OrderTimelineEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_code', models.CharField(db_index=True, max_length=48, verbose_name='事件代码')),
                ('label', models.CharField(max_length=64, verbose_name='展示文案')),
                ('occurred_at', models.DateTimeField(db_index=True, verbose_name='发生时间')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='写入时间')),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='timeline_events', to='waimai.buyorder', verbose_name='订单')),
            ],
            options={
                'verbose_name': '订单历程',
                'verbose_name_plural': '订单历程',
                'db_table': 'order_timeline_event',
                'ordering': ['occurred_at', 'pk'],
            },
        ),
    ]
