# 托盘启动器读取：端口、本机打开后台、店内地址对比

import json

from django.core.management.base import BaseCommand

from waimai.lan_base_helpers import compare_saved_and_detected, local_open_backend_url
from waimai.owner_helpers import get_site_settings
from waimai.v1_local_helpers import v1_local_mode_enabled


class Command(BaseCommand):
    help = '输出 JSON 供 V1 托盘读取端口、本机打开后台与店内地址对比'

    def handle(self, *args, **options):
        site = get_site_settings()
        snapshot = compare_saved_and_detected()
        port = snapshot.get('listen_port') or site.v1_listen_port or 8000
        payload = {
            'listen_port': int(port),
            'open_url': local_open_backend_url(int(port)),
            'lan_base_url': snapshot.get('saved_lan') or '',
            'detected_lan': snapshot.get('detected_lan') or '',
            'match': bool(snapshot.get('match')),
            'detect_failed': bool(snapshot.get('detect_failed')),
            'lan_message': snapshot.get('message') or '',
            'setup_completed': bool(site.v1_setup_completed),
            'v1_local_mode': v1_local_mode_enabled(),
            'backup_dir': (site.v1_backup_dir or '').strip(),
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False))
