# 管理命令：查看当前 SQLite 是否满足 Django 要求
from django.core.management.base import BaseCommand

from wuwei_system.sqlite_compat import _MIN_SQLITE, _version_tuple


class Command(BaseCommand):
    help = '检查 SQLite 版本是否满足 Django 5.2（部署自检）'

    def handle(self, *args, **options):
        import sqlite3

        current = _version_tuple(sqlite3)
        need = '.'.join(str(x) for x in _MIN_SQLITE)
        cur = '.'.join(str(x) for x in current)
        # 版本号用英文输出，避免部分 Windows 终端中文乱码中断
        self.stdout.write(f'SQLite in use: {cur}')
        self.stdout.write(f'Django 5.2 requires: {need}+')
        if current >= _MIN_SQLITE:
            self.stdout.write(self.style.SUCCESS('OK: version is enough for migrate/run.'))
        else:
            self.stdout.write(
                self.style.ERROR(
                    'FAIL: too old. Run: pip install -r requirements-sqlite-compat.txt\n'
                    'Then retry. See docs for SQLite section.'
                )
            )
