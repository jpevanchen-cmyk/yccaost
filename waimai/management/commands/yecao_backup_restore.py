# 从最近或指定备份恢复数据库（须先停网页服务）

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from waimai.v1_backup_helpers import find_latest_backup, restore_from_backup, restore_latest_backup, write_cli_message


class Command(BaseCommand):
    help = 'V1 从备份恢复 SQLite 数据库'

    def add_arguments(self, parser):
        parser.add_argument(
            '--latest',
            action='store_true',
            help='使用备份目录中最新一份',
        )
        parser.add_argument(
            '--file',
            default='',
            help='指定备份文件路径',
        )
        parser.add_argument(
            '--no-keep-corrupt',
            action='store_true',
            help='不保留损坏的当前库文件',
        )

    def handle(self, *args, **options):
        keep = not options['no_keep_corrupt']
        file_arg = (options['file'] or '').strip()
        if file_arg:
            result = restore_from_backup(Path(file_arg), keep_corrupt_copy=keep)
        elif options['latest']:
            result = restore_latest_backup(keep_corrupt_copy=keep)
        else:
            latest = find_latest_backup()
            if not latest:
                raise CommandError('备份目录里没有可恢复的副本。')
            result = restore_from_backup(latest, keep_corrupt_copy=keep)
        if not result.ok:
            raise CommandError(result.message)
        write_cli_message(self.stdout, self.style.SUCCESS, result.message, ok=True)
