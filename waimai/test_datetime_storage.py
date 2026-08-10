# 库内存法：旧 UTC 墙钟 → 系统本地

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from waimai.datetime_storage_helpers import (
    STORAGE_MODE_LOCAL,
    convert_all_utc_naive_datetimes_to_local,
    utc_naive_to_local_naive,
)


class DatetimeStorageConvertTests(SimpleTestCase):
    def test_utc_naive_to_tokyo_local(self):
        # 01:00 UTC → 东京 10:00
        utc_wall = datetime(2026, 8, 9, 1, 0, 0)
        with override_settings(TIME_ZONE='Asia/Tokyo', USE_TZ=False):
            local = utc_naive_to_local_naive(utc_wall)
        self.assertEqual(local, datetime(2026, 8, 9, 10, 0, 0))

    def test_convert_skips_when_already_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / '.yecao_datetime_storage.json'
            marker.write_text(
                json.dumps({'mode': STORAGE_MODE_LOCAL}, ensure_ascii=False),
                encoding='utf-8',
            )
            with patch(
                'waimai.datetime_storage_helpers.storage_marker_path',
                return_value=marker,
            ):
                result = convert_all_utc_naive_datetimes_to_local(force=False)
        self.assertTrue(result.get('skipped'))
        self.assertEqual(result.get('updated_cells'), 0)
