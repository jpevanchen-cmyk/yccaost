# 托盘 / 维护：V1 SQLite WAL 等 PRAGMA 自检（JSON）

import json

from django.core.management.base import BaseCommand

from waimai.v1_sqlite_helpers import read_sqlite_pragma_report


class Command(BaseCommand):
    help = 'V1 SQLite 数据保护自检（WAL / busy_timeout 等，输出 JSON）'

    def handle(self, *args, **options):
        report = read_sqlite_pragma_report()
        self.stdout.write(json.dumps(report, ensure_ascii=True))
