# 幂等第 9 步：商品图 Ajax 单张上传防重复

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from waimai.product_image_helpers import delete_all_images_for_dish
from waimai.test_shop_helpers import create_logged_in_seller_client, create_test_shop_bundle


def _make_png_upload(name='test.png'):
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', (40, 40), color=(200, 100, 50)).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=Path(settings.BASE_DIR) / 'test_media_img_idem')
class ProductImageUploadIdempotencyTests(TestCase):
    def setUp(self):
        self.media_root = Path(settings.MEDIA_ROOT)
        self.media_root.mkdir(parents=True, exist_ok=True)
        bundle = create_test_shop_bundle(with_dish=True, dish_name='幂等图试验商品')
        self.seller = bundle.seller
        self.dish = bundle.dish
        self.client = create_logged_in_seller_client(bundle)
        self.upload_url = reverse('seller_panel_section', kwargs={'section': 'products'})

    def tearDown(self):
        if self.dish.pk:
            delete_all_images_for_dish(self.dish)
        if self.media_root.exists():
            for p in sorted(self.media_root.rglob('*'), reverse=True):
                if p.is_file():
                    p.unlink(missing_ok=True)
                elif p.is_dir():
                    p.rmdir()
            self.media_root.rmdir()

    def _upload_payload(self, key: str = '', name='a.png'):
        data = {
            'upload_dish_image': '1',
            'dish_id': str(self.dish.dish_id),
        }
        if key:
            data['idempotency_key'] = key
        return data, _make_png_upload(name)

    def _post_upload(self, data, upload):
        """Django 5 测试客户端须把文件放进 data，不能单独传 files=。"""
        payload = {**data, 'dish_image': upload}
        return self.client.post(self.upload_url, payload)

    @patch('waimai.product_image_helpers._schedule_dish_image_compress')
    def test_same_key_upload_creates_one_image(self, _mock_compress):
        key = 'img-upload-key-00000001'
        data, upload = self._upload_payload(key)

        resp1 = self._post_upload(data, upload)
        upload2 = _make_png_upload('retry.png')
        resp2 = self._post_upload(data, upload2)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        body1 = resp1.json()
        body2 = resp2.json()
        self.assertTrue(body1.get('ok'))
        self.assertTrue(body2.get('ok'))
        self.assertEqual(body1.get('image_id'), body2.get('image_id'))
        self.assertEqual(self.dish.product_images.count(), 1)

    @patch('waimai.product_image_helpers._schedule_dish_image_compress')
    def test_without_key_double_upload_creates_two(self, _mock_compress):
        data, upload1 = self._upload_payload()
        resp1 = self._post_upload(data, upload1)
        data2, upload2 = self._upload_payload()
        resp2 = self._post_upload(data2, upload2)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp1.json().get('ok'))
        self.assertTrue(resp2.json().get('ok'))
        self.assertEqual(self.dish.product_images.count(), 2)
