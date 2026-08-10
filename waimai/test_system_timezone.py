# 时间出口：系统时区探测与本地 ISO

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone

from waimai.time_helpers import format_local_iso, to_local, now_local_wall
from wuwei_system.system_timezone import detect_system_timezone_name


class SystemTimezoneExportTests(SimpleTestCase):
    def test_detect_returns_valid_name(self):
        name = detect_system_timezone_name()
        self.assertTrue(name)
        # settings 启动时应已写入同一套探测结果（可被 YECAO_TIME_ZONE 覆盖）
        self.assertTrue(getattr(settings, 'TIME_ZONE', None))

    def test_format_local_iso_not_utc_zero_offset_when_not_utc(self):
        text = format_local_iso()
        self.assertIn('T', text)
        # 系统非 UTC 时，不应再写出裸 +00:00 给人看（本机日本/中国常见为 +09/+08）
        if settings.TIME_ZONE != 'UTC':
            self.assertFalse(text.endswith('+00:00'), text)

    def test_to_local_is_system_aware(self):
        from waimai.time_helpers import ensure_local_aware

        now = now_local_wall()
        self.assertEqual(to_local(now), ensure_local_aware(now))
        self.assertIsNotNone(to_local(now).tzinfo)
