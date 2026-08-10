# 托盘启动成功后标记「本次运行已开始」

from django.core.management.base import BaseCommand

from waimai.v1_backup_helpers import mark_startup_seen


class Command(BaseCommand):
    help = 'V1 托盘启动服务后写入运行标记'

    def handle(self, *args, **options):
        mark_startup_seen()
        self.stdout.write('ok')
