# 微信退款证书上传

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from pathlib import Path

from django.conf import settings

from waimai.forms import ShopPaymentSettingsForm
from waimai.models import ShopProfile, User
from waimai.payment_cert_helpers import apply_wechat_cert_uploads, wechat_cert_status_label
from waimai.payments.service import get_payment_settings


SAMPLE_CERT = b"""-----BEGIN CERTIFICATE-----
MIIC-test-cert-for-yecaost
-----END CERTIFICATE-----
"""

SAMPLE_KEY = b"""-----BEGIN PRIVATE KEY-----
MIIE-test-key-for-yecaost
-----END PRIVATE KEY-----
"""


@override_settings(BASE_DIR=Path(settings.BASE_DIR))
class PaymentCertUploadTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='cert_upload_seller',
            password='pass12345',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller.username,
            shop_name='证书上传测试店',
            shop_code='certshop',
            address='测试地址',
        )
        self.pay = get_payment_settings(self.seller.username)
        self.pay.enable_wechat = True
        self.pay.wechat_mch_id = '1900000109'
        self.pay.wechat_app_id = 'wx8888888888888888'
        self.pay.wechat_api_key = '8934e7d15453e97507ef794cf7b0519d'
        self.pay.save()

    def test_apply_uploads_writes_files_and_paths(self):
        cert = SimpleUploadedFile('apiclient_cert.pem', SAMPLE_CERT, content_type='application/x-pem-file')
        key = SimpleUploadedFile('apiclient_key.pem', SAMPLE_KEY, content_type='application/x-pem-file')
        errors = apply_wechat_cert_uploads(self.pay, cert_file=cert, key_file=key)
        self.assertEqual(errors, [])
        self.pay.refresh_from_db()
        self.assertTrue(self.pay.wechat_refund_config_ready())
        self.assertIn('已上传', wechat_cert_status_label(self.pay))

    def test_form_rejects_wrong_extension(self):
        bad = SimpleUploadedFile('wrong.txt', SAMPLE_CERT, content_type='text/plain')
        form = ShopPaymentSettingsForm(
            {},
            {'wechat_apiclient_cert_upload': bad},
            instance=self.pay,
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(any('pem' in str(e).lower() for e in form.errors.get('wechat_apiclient_cert_upload', [])))

    def test_partial_upload_keeps_other_file(self):
        cert = SimpleUploadedFile('apiclient_cert.pem', SAMPLE_CERT, content_type='application/x-pem-file')
        apply_wechat_cert_uploads(self.pay, cert_file=cert, key_file=None)
        self.pay.refresh_from_db()
        cert_path = self.pay.wechat_apiclient_cert_path
        key = SimpleUploadedFile('apiclient_key.pem', SAMPLE_KEY, content_type='application/x-pem-file')
        apply_wechat_cert_uploads(self.pay, cert_file=None, key_file=key)
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.wechat_apiclient_cert_path, cert_path)
        self.assertTrue(self.pay.wechat_refund_config_ready())

    def test_display_shows_paths_when_readable(self):
        cert = SimpleUploadedFile('apiclient_cert.pem', SAMPLE_CERT, content_type='application/x-pem-file')
        key = SimpleUploadedFile('apiclient_key.pem', SAMPLE_KEY, content_type='application/x-pem-file')
        apply_wechat_cert_uploads(self.pay, cert_file=cert, key_file=key)
        self.pay.refresh_from_db()
        from waimai.payment_cert_helpers import build_wechat_cert_display

        display = build_wechat_cert_display(self.pay)
        self.assertTrue(display['files_ready'])
        self.assertTrue(display['cert_path'])
        self.assertIn('证书已上传', display['summary'])

    def test_clear_removes_files_and_paths(self):
        cert = SimpleUploadedFile('apiclient_cert.pem', SAMPLE_CERT, content_type='application/x-pem-file')
        key = SimpleUploadedFile('apiclient_key.pem', SAMPLE_KEY, content_type='application/x-pem-file')
        apply_wechat_cert_uploads(self.pay, cert_file=cert, key_file=key)
        self.pay.refresh_from_db()
        from waimai.payment_cert_helpers import clear_wechat_cert_files

        ok, _ = clear_wechat_cert_files(self.pay)
        self.assertTrue(ok)
        self.pay.refresh_from_db()
        self.assertEqual(self.pay.wechat_apiclient_cert_path, '')
        self.assertFalse(self.pay.wechat_refund_config_ready())
