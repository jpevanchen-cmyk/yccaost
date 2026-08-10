# 托盘启动器读取：端口、营业入口网址、V1 状态

import json

from django.core.management.base import BaseCommand

from waimai.owner_helpers import get_site_settings
from waimai.v1_local_helpers import v1_local_mode_enabled


class Command(BaseCommand):
    help = '输出 JSON 供 V1 托盘读取端口与营业地址'

    def handle(self, *args, **options):
        site = get_site_settings()
        port = site.v1_listen_port or 8000
        open_url = (site.v1_lan_base_url or '').strip()
        if open_url:
            open_url = open_url.rstrip('/') + '/accounts/login/'
        else:
            open_url = f'http://127.0.0.1:{port}/accounts/login/'
        payload = {
            'listen_port': port,
            'open_url': open_url,
            'setup_completed': bool(site.v1_setup_completed),
            'v1_local_mode': v1_local_mode_enabled(),
            'backup_dir': (site.v1_backup_dir or '').strip(),
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False))
