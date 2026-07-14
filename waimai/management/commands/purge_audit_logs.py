# 清理过期操作审计（A.12：默认保留半年）

from django.core.management.base import BaseCommand

from waimai.audit_helpers import AUDIT_RETENTION_DAYS, purge_expired_audit_logs


class Command(BaseCommand):
    help = '删除超过保留天数的操作审计记录（默认 180 天）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=AUDIT_RETENTION_DAYS,
            help=f'保留天数（默认 {AUDIT_RETENTION_DAYS}）',
        )

    def handle(self, *args, **options):
        days = options['days']
        deleted = purge_expired_audit_logs(days)
        self.stdout.write(self.style.SUCCESS(f'已清理 {deleted} 条超过 {days} 天的操作审计'))
