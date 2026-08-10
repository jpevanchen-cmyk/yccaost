# V1 执行一次数据库备份（稳定优先）

from django.core.management.base import BaseCommand, CommandError

from waimai.v1_backup_helpers import run_backup, run_backup_to_directory, write_cli_message


class Command(BaseCommand):
    help = 'V1 SQLite 稳定备份（manual / daily / exit；或立刻备份到指定文件夹）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reason',
            default='manual',
            choices=('manual', 'daily', 'hourly', 'exit', 'export'),
            help='备份原因标签',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='daily/hourly 时忽略跳过条件',
        )
        parser.add_argument(
            '--dest-dir',
            default='',
            help='立刻备份到指定文件夹（不改默认自动备份目录）',
        )

    def handle(self, *args, **options):
        dest_dir = (options.get('dest_dir') or '').strip()
        if dest_dir:
            result = run_backup_to_directory(dest_dir, reason=options.get('reason') or 'export')
        else:
            result = run_backup(options['reason'], force=bool(options.get('force')))
        if result.skipped:
            self.stdout.write(self.style.WARNING(result.message))
            return
        if not result.ok:
            raise CommandError(result.message)
        write_cli_message(self.stdout, self.style.SUCCESS, result.message, ok=True)
