# 托盘启动前：数据库完整性 + 异常退出提示（JSON）

import json
import logging
import traceback
from pathlib import Path

from django.core.management.base import BaseCommand

from waimai.v1_backup_helpers import (
    find_latest_backup,
    startup_database_report,
    user_facing_db_check_message,
)
from waimai.v1_setup_helpers import default_backup_dir

logger = logging.getLogger('waimai')


class Command(BaseCommand):
    help = 'V1 启动前数据库自检（输出 JSON 供托盘读取）'

    def handle(self, *args, **options):
        try:
            report = startup_database_report()
        except Exception as Exc:
            # 任何未捕获异常：仍输出 JSON，堆栈进日志，不把 Traceback 塞给托盘弹窗
            logger.exception('yecao_startup_db_check 失败')
            tech = traceback.format_exc()
            backup_dir = Path(default_backup_dir())
            latest = find_latest_backup(backup_dir)
            detail = user_facing_db_check_message(str(Exc)) or '营业数据检查未通过。'
            report = {
                'ok': False,
                'detail': detail,
                'tech_detail': tech,
                'user_message': detail,
                'database': '',
                'backup_dir': str(backup_dir),
                'latest_backup': str(latest) if latest else '',
                'abnormal_shutdown_suspected': False,
                'meta': {},
            }
            # 技术细节写到 stderr 仅供日志；stdout 仍是干净 JSON
            self.stderr.write(tech)
        self.stdout.write(json.dumps(report, ensure_ascii=False))
