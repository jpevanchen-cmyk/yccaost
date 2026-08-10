# V1 托盘整点：daily（0:00～0:10）或 hourly（满 1 小时）

import json

from django.core.management.base import BaseCommand, CommandError

from waimai.v1_backup_helpers import run_scheduled_backup


class Command(BaseCommand):
    help = 'V1 托盘整点备份：优先 daily，否则 hourly（日备成功后含抽检）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='忽略「今日已 daily / 不足 1 小时」跳过条件',
        )

    def handle(self, *args, **options):
        result = run_scheduled_backup(force=bool(options['force']))
        payload = {
            'ok': bool(result.ok),
            'skipped': bool(result.skipped),
            'message': result.message or '',
            'backup_path': result.backup_path or '',
            'health_ok': result.health_ok,
            'health_message': result.health_message or '',
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False))
        if not result.ok and not result.skipped:
            raise CommandError(result.message)
