# 0055 · V1 微信退款最小版：流水退款字段 + 商户证书路径

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0054_login_guard_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='shoppaymentsettings',
            name='wechat_apiclient_cert_path',
            field=models.CharField(
                blank=True, default='', max_length=512, verbose_name='微信退款证书路径',
            ),
        ),
        migrations.AddField(
            model_name='shoppaymentsettings',
            name='wechat_apiclient_key_path',
            field=models.CharField(
                blank=True, default='', max_length=512, verbose_name='微信退款私钥路径',
            ),
        ),
        migrations.AddField(
            model_name='paymentrecord',
            name='out_refund_no',
            field=models.CharField(
                blank=True, default='', max_length=64, db_index=True, verbose_name='商户退款单号',
            ),
        ),
        migrations.AddField(
            model_name='paymentrecord',
            name='refund_id',
            field=models.CharField(
                blank=True, default='', max_length=64, verbose_name='微信退款单号',
            ),
        ),
        migrations.AddField(
            model_name='paymentrecord',
            name='refund_status',
            field=models.CharField(
                blank=True, default='', max_length=16, db_index=True, verbose_name='退款状态',
            ),
        ),
        migrations.AddField(
            model_name='paymentrecord',
            name='refunded_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='退款完成时间'),
        ),
        migrations.AddField(
            model_name='paymentrecord',
            name='refund_payload',
            field=models.JSONField(blank=True, null=True, verbose_name='退款查询/回调原始数据'),
        ),
        migrations.AlterField(
            model_name='buyorder',
            name='payment_status',
            field=models.CharField(
                choices=[
                    ('pending_payment', '待支付'),
                    ('paid', '已支付'),
                    ('refunded', '已退款'),
                    ('uncollected', '未收款结案'),
                    ('cancelled', '已取消'),
                ],
                db_index=True,
                default='pending_payment',
                max_length=20,
                verbose_name='支付状态',
            ),
        ),
    ]
