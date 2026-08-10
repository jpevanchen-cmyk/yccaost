# 抽检最近若干份备份是否完整可用（JSON）

import json

from django.core.management.base import BaseCommand

from waimai.v1_backup_helpers import BACKUP_HEALTH_CHECK_COUNT, inspect_recent_backups


class Command(BaseCommand):
    help = '抽检最近备份文件完整性（供托盘启动后 / 日备后调用）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=BACKUP_HEALTH_CHECK_COUNT,
            help='抽检最近多少份（默认 10）',
        )

    def handle(self, *args, **options):
        limit = int(options.get('limit') or BACKUP_HEALTH_CHECK_COUNT)
        report = inspect_recent_backups(limit=limit)
        self.stdout.write(json.dumps(report.as_dict(), ensure_ascii=False))
