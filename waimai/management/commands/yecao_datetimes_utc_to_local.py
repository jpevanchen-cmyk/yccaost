# 旧库时间：世界标准时墙钟 → 系统本地墙钟（配合 USE_TZ=False）

from django.core.management.base import BaseCommand

from waimai.datetime_storage_helpers import (
    apply_work_copy_to_live,
    convert_all_utc_naive_datetimes_to_local,
)


class Command(BaseCommand):
    help = '把库内旧 UTC 墙钟时间一次性改成系统本地（防重复；须在 USE_TZ=False 后执行）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='无视已转换标记强制再转（危险，一般不要用）',
        )
        parser.add_argument(
            '--apply-work-copy',
            action='store_true',
            help='把已转好的工作副本盖回正式库（先停 runserver/托盘）',
        )

    def handle(self, *args, **options):
        if options.get('apply_work_copy'):
            result = apply_work_copy_to_live()
        else:
            result = convert_all_utc_naive_datetimes_to_local(force=bool(options.get('force')))
        msg = result.get('message') or ''
        if result.get('ok'):
            self.stdout.write(self.style.SUCCESS(msg))
        else:
            self.stdout.write(self.style.ERROR(msg))
        if result.get('updated_cells') is not None:
            self.stdout.write(self.style.NOTICE(f"updated_cells={result.get('updated_cells')}"))
