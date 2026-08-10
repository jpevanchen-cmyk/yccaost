# V1 第 11 项：本机忘记密码重置（命令行）

from django.core.management.base import BaseCommand, CommandError

from waimai.v1_password_reset_helpers import (
    CONFIRM_PHRASE,
    clear_operation_lock_pin_local,
    clear_tray_startup_exit_password,
    confirm_phrase_ok,
    list_owner_accounts,
    reset_owner_login_password,
)


class Command(BaseCommand):
    help = '本机忘记密码重置：老板登录 / 托盘密码 / 操作锁（须在本机执行）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--owner',
            default='',
            help='要重置的老板登录名（不填则列出可选账号）',
        )
        parser.add_argument(
            '--new-password',
            default='',
            help='老板登录的新密码',
        )
        parser.add_argument(
            '--clear-tray',
            action='store_true',
            help='清除托盘启动/退出密码',
        )
        parser.add_argument(
            '--clear-operation-lock',
            action='store_true',
            help='清除操作锁 PIN',
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help=f'跳过交互确认（仍建议先看清参数；正式确认词为「{CONFIRM_PHRASE}」）',
        )
        parser.add_argument(
            '--confirm',
            default='',
            help=f'确认词，须为「{CONFIRM_PHRASE}」（与 --yes 二选一亦可）',
        )

    def handle(self, *args, **options):
        do_owner = bool((options.get('owner') or '').strip() or (options.get('new_password') or '').strip())
        do_tray = bool(options.get('clear_tray'))
        do_lock = bool(options.get('clear_operation_lock'))

        if not do_owner and not do_tray and not do_lock:
            owners = list_owner_accounts()
            self.stdout.write('本机忘记密码重置工具')
            self.stdout.write('可做：重置老板登录密码、清除托盘密码、清除操作锁。')
            self.stdout.write(f'确认词：{CONFIRM_PHRASE}')
            if owners:
                self.stdout.write('老板账号：' + '、'.join(u.username for u in owners))
            else:
                self.stdout.write('当前库里没有标记为服务器管理者的老板账号。')
            self.stdout.write('')
            self.stdout.write('示例：')
            self.stdout.write(
                f'  python manage.py yecao_reset_local_password --owner 登录名 '
                f'--new-password 新密码 --confirm {CONFIRM_PHRASE}'
            )
            self.stdout.write(
                f'  python manage.py yecao_reset_local_password --clear-tray --confirm {CONFIRM_PHRASE}'
            )
            self.stdout.write(
                f'  python manage.py yecao_reset_local_password --clear-operation-lock '
                f'--confirm {CONFIRM_PHRASE}'
            )
            self.stdout.write('也可双击：本机忘记密码重置.bat')
            return

        confirmed = bool(options.get('yes')) or confirm_phrase_ok(options.get('confirm') or '')
        if not confirmed:
            raise CommandError(f'未确认。请加 --confirm {CONFIRM_PHRASE} 或 --yes')

        messages: list[str] = []
        if do_tray:
            ok, msg = clear_tray_startup_exit_password()
            if not ok:
                raise CommandError(msg)
            messages.append(msg)

        if do_lock:
            ok, msg = clear_operation_lock_pin_local()
            if not ok:
                raise CommandError(msg)
            messages.append(msg)

        if do_owner:
            owner = (options.get('owner') or '').strip()
            password = options.get('new_password') or ''
            if not owner:
                owners = list_owner_accounts()
                if len(owners) == 1:
                    owner = owners[0].username
                else:
                    raise CommandError('请用 --owner 指定老板登录名。')
            ok, msg = reset_owner_login_password(owner, password)
            if not ok:
                raise CommandError(msg)
            messages.append(msg)

        for line in messages:
            self.stdout.write(self.style.SUCCESS(line))
