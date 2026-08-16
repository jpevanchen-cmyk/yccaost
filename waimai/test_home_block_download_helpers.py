# 文件下载积木：投放盒点选复制到本块隔间

from __future__ import annotations

import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from waimai.home_block_download_helpers import (
    apply_home_block_download_from_post,
    list_download_library_files,
    resolve_download_library_file,
)
from waimai.home_page_helpers import BLOCK_FILE_DOWNLOAD, ensure_server_home_page
from waimai.models import ServerHomeBlock


class DownloadLibraryPickTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.media = Path(self._tmp.name)

    def _make_block(self) -> ServerHomeBlock:
        page = ensure_server_home_page()
        return ServerHomeBlock.objects.create(
            home_page=page,
            block_type=BLOCK_FILE_DOWNLOAD,
            title='测试下载',
            sort_order=90,
            is_enabled=True,
        )

    def test_list_and_copy_from_library(self):
        with override_settings(MEDIA_ROOT=str(self.media)):
            lib = self.media / 'downloads'
            lib.mkdir(parents=True)
            src = lib / '野草本地营业_V1.01_安装包.exe'
            src.write_bytes(b'MZ-fake-installer')
            self.assertIn('野草本地营业_V1.01_安装包.exe', list_download_library_files())
            self.assertIsNone(resolve_download_library_file('../secret.exe'))
            self.assertIsNone(resolve_download_library_file('..\\secret.exe'))

            block = self._make_block()
            req = RequestFactory().post(
                '/x/', {'pick_server_download': '野草本地营业_V1.01_安装包.exe'},
            )
            err = apply_home_block_download_from_post(block, req)
            self.assertIsNone(err)
            block.save()
            block.refresh_from_db()
            self.assertTrue(block.download_file)
            copied = Path(block.download_file.path)
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.read_bytes(), b'MZ-fake-installer')
            self.assertTrue(src.is_file())
            self.assertIn('home_downloads', copied.as_posix())

            err2 = apply_home_block_download_from_post(block, req)
            self.assertIsNone(err2)

            up = SimpleUploadedFile(
                'from_pc.zip', b'PK-from-pc', content_type='application/zip',
            )
            class _Req:
                POST = {'pick_server_download': '野草本地营业_V1.01_安装包.exe'}
                FILES = {'block_download': up}

            err3 = apply_home_block_download_from_post(block, _Req())
            self.assertIsNone(err3)
            block.save()
            block.refresh_from_db()
            self.assertTrue(Path(block.download_file.path).read_bytes().startswith(b'PK'))
