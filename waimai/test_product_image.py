# 批次 G · G1-2：商品多图上传、压缩与文件夹

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from waimai.models import Dish, DishImage, User
from waimai.product_image_helpers import (
    MAX_DISH_IMAGES_PER_PRODUCT,
    apply_dish_image_uploads,
    delete_all_images_for_dish,
    delete_dish_image,
    migrate_legacy_dish_image_url,
    move_dish_image,
    sync_dish_images_from_folder,
)


def _make_png_upload(name='test.png', size=(800, 600)):
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', size, color=(200, 100, 50)).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=Path(settings.BASE_DIR) / 'test_media_g12')
class ProductImageUploadTests(TestCase):
    def setUp(self):
        self.media_root = Path(settings.MEDIA_ROOT)
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.seller = User.objects.create_user(
            username='img_seller',
            password='test-pass',
            role='seller',
        )
        self.client = Client()
        self.client.login(username='img_seller', password='test-pass')
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='测试商品',
            price='12.00',
        )

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

    def test_upload_saves_compressed_jpeg_with_numbered_filename(self):
        err = apply_dish_image_uploads(self.dish, [_make_png_upload()])
        self.assertIsNone(err)
        self.assertEqual(self.dish.product_images.count(), 1)
        record = self.dish.product_images.get()
        self.assertEqual(record.sort_index, 1)
        self.assertEqual(record.display_code, 'a001')
        self.assertTrue(record.image.name.endswith('a001/a001-1.jpg'))
        self.assertTrue(Path(settings.MEDIA_ROOT / record.image.name).is_file())

    def test_upload_respects_ten_image_limit(self):
        files = [_make_png_upload(f't{i}.png', size=(40, 40)) for i in range(MAX_DISH_IMAGES_PER_PRODUCT + 1)]
        err = apply_dish_image_uploads(self.dish, files)
        self.assertIsNotNone(err)
        self.assertEqual(self.dish.product_images.count(), 0)

    def test_delete_dish_removes_image_files(self):
        apply_dish_image_uploads(self.dish, [_make_png_upload()])
        path = self.dish.product_images.get().image.name
        self.dish.delete()
        self.assertFalse(DishImage.objects.filter(dish_id=self.dish.dish_id).exists())
        self.assertFalse((Path(settings.MEDIA_ROOT) / path).is_file())

    def test_delete_single_image_compacts_sort_indices(self):
        apply_dish_image_uploads(
            self.dish,
            [_make_png_upload('a.png'), _make_png_upload('b.png')],
        )
        first_id = self.dish.product_images.get(sort_index=1).image_id
        self.assertIsNone(delete_dish_image(self.dish, first_id))
        self.assertEqual(self.dish.product_images.count(), 1)
        remaining = self.dish.product_images.get()
        self.assertEqual(remaining.sort_index, 1)
        self.assertTrue(remaining.image.name.endswith('a001-1.jpg'))

    def test_move_dish_image_swaps_order(self):
        apply_dish_image_uploads(
            self.dish,
            [_make_png_upload('a.png'), _make_png_upload('b.png')],
        )
        second = self.dish.product_images.get(sort_index=2)
        self.assertIsNone(move_dish_image(self.dish, second.image_id, 'up'))
        self.assertEqual(
            list(self.dish.product_images.order_by('sort_index').values_list('image_id', flat=True)),
            [second.image_id, self.dish.product_images.exclude(image_id=second.image_id).get().image_id],
        )

    def test_sync_mounts_manual_folder_file(self):
        folder = Path(settings.MEDIA_ROOT) / 'dish_images' / 'a001'
        folder.mkdir(parents=True, exist_ok=True)
        manual = folder / 'a001-1-手工图.png'
        _make_png_upload('manual.png').seek(0)
        from PIL import Image
        buf = BytesIO()
        Image.new('RGB', (120, 80), color=(10, 20, 30)).save(buf, format='PNG')
        manual.write_bytes(buf.getvalue())

        err, mounted = sync_dish_images_from_folder(self.dish)
        self.assertIsNone(err)
        self.assertEqual(mounted, 1)
        record = self.dish.product_images.get()
        self.assertEqual(record.sort_index, 1)
        self.assertIn('a001-1-手工图.png', record.image.name)

    def test_build_dish_image_gallery_orders_by_sort_index(self):
        apply_dish_image_uploads(
            self.dish,
            [_make_png_upload('a.png'), _make_png_upload('b.png')],
        )
        from waimai.product_image_helpers import build_dish_image_gallery

        gallery = build_dish_image_gallery(self.dish)
        self.assertEqual(len(gallery), 2)
        self.assertEqual([g['sort_index'] for g in gallery], [1, 2])
        self.assertTrue(all(g['url'] for g in gallery))

    def test_shop_gallery_template_renders(self):
        from django.template.loader import render_to_string
        from waimai.product_image_helpers import build_dish_image_gallery

        apply_dish_image_uploads(
            self.dish,
            [_make_png_upload('a.png'), _make_png_upload('b.png')],
        )
        html = render_to_string(
            'waimai/_dish_image_gallery.html',
            {'gallery': build_dish_image_gallery(self.dish), 'dish': self.dish},
        )
        self.assertIn('dish-gallery', html)
        self.assertIn('dish-gallery-thumbs', html)
        self.assertNotIn('dish-gallery-main', html)
        self.assertEqual(html.count('data-dish-gallery-thumb'), 2)
        self.assertIn('dish-gallery-json', html)

    def test_product_image_manage_forms_have_csrf_on_seller_page(self):
        """子模板含独立 POST 表单时，include 不可用 only，否则 csrf_token 渲染为空。"""
        apply_dish_image_uploads(self.dish, [_make_png_upload('a.png')])
        edit_id = self.dish.dish_id.hex[:8]
        resp = self.client.get(f'/seller-panel/products/?edit={edit_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        idx = html.find('product-image-manage-block')
        self.assertGreater(idx, -1)
        seg = html[idx:idx + 1500]
        self.assertIn('csrfmiddlewaretoken', seg)
        self.assertIn('sync_dish_images', html[idx:])


def _make_png_bytes(size=(800, 600)):
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', size, color=(200, 100, 50)).save(buf, format='PNG')
    return buf.getvalue()


@override_settings(MEDIA_ROOT=Path(settings.BASE_DIR) / 'test_media_g15')
class ProductImageLegacyUrlMigrationTests(TestCase):
    def setUp(self):
        self.media_root = Path(settings.MEDIA_ROOT)
        self.media_root.mkdir(parents=True, exist_ok=True)
        self.seller = User.objects.create_user(
            username='legacy_img_seller',
            password='test-pass',
            role='seller',
        )
        self.dish = Dish.objects.create(
            seller_id=self.seller.username,
            name='旧外链商品',
            price='9.00',
            image_url='https://example.com/old.png',
        )

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

    @patch('waimai.product_image_helpers._download_legacy_image_bytes')
    def test_migrate_downloads_url_and_clears_field(self, mock_download):
        mock_download.return_value = _make_png_bytes()
        result = migrate_legacy_dish_image_url(self.dish)
        self.assertEqual(result, 'downloaded')
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.image_url, '')
        self.assertEqual(self.dish.product_images.count(), 1)
        record = self.dish.product_images.get()
        self.assertEqual(record.sort_index, 1)
        self.assertTrue(Path(settings.MEDIA_ROOT / record.image.name).is_file())

    @patch('waimai.product_image_helpers._download_legacy_image_bytes')
    def test_migrate_dead_url_clears_field_only(self, mock_download):
        mock_download.return_value = None
        result = migrate_legacy_dish_image_url(self.dish)
        self.assertEqual(result, 'dead')
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.image_url, '')
        self.assertEqual(self.dish.product_images.count(), 0)

    @patch('waimai.product_image_helpers._download_legacy_image_bytes')
    def test_migrate_skips_download_when_local_images_exist(self, mock_download):
        apply_dish_image_uploads(self.dish, [_make_png_upload()])
        Dish.objects.filter(pk=self.dish.pk).update(image_url='https://example.com/old.png')
        self.dish.refresh_from_db()
        result = migrate_legacy_dish_image_url(self.dish)
        self.assertEqual(result, 'cleared_only')
        mock_download.assert_not_called()
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.image_url, '')
        self.assertEqual(self.dish.product_images.count(), 1)

    @patch('waimai.product_image_helpers._download_legacy_image_bytes')
    def test_migrate_dry_run_does_not_change_database(self, mock_download):
        mock_download.return_value = _make_png_bytes()
        result = migrate_legacy_dish_image_url(self.dish, dry_run=True)
        self.assertEqual(result, 'downloaded')
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.image_url, 'https://example.com/old.png')
        self.assertEqual(self.dish.product_images.count(), 0)
        mock_download.assert_called_once()
