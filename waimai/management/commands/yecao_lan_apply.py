# 托盘「一键更新」：把当前探测到的店内地址写入堂食真源并放行

import json

from django.core.management.base import BaseCommand

from waimai.lan_base_helpers import apply_detected_lan_base_url


class Command(BaseCommand):
    help = '探测当前店内地址并写入堂食真源（须托盘先确认；禁止静默调用）'

    def handle(self, *args, **options):
        ok, msg, payload = apply_detected_lan_base_url()
        payload['ok'] = ok
        payload['message'] = msg
        self.stdout.write(json.dumps(payload, ensure_ascii=False))
