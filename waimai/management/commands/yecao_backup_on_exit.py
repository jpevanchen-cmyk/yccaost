# 托盘「退出野草」时触发的正常退出备份

from django.core.management.base import BaseCommand, CommandError

from waimai.v1_backup_helpers import run_backup, write_cli_message


class Command(BaseCommand):
    help = 'V1 托盘完全退出时的稳定备份'

    def handle(self, *args, **options):
        result = run_backup('exit')
        if not result.ok:
            raise CommandError(result.message)
        write_cli_message(self.stdout, self.style.SUCCESS, result.message, ok=True)
