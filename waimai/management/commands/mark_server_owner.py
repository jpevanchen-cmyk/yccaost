# 指定服务器管理者：python manage.py mark_server_owner --username=用户名
# 与体验机「官方小店 / 正式保留」无关

from django.core.management.base import BaseCommand, CommandError

from waimai.models import User


class Command(BaseCommand):
    help = '将某用户设为服务器管理者（可进「服务器设置」）'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True, help='用户名')
        parser.add_argument(
            '--exclusive',
            action='store_true',
            help='同时取消其他账号的管理者标记',
        )

    def handle(self, *args, **options):
        username = (options['username'] or '').strip()
        user = User.objects.filter(username=username).first()
        if not user:
            raise CommandError(f'找不到用户：{username}')
        if options['exclusive']:
            User.objects.exclude(pk=user.pk).update(is_server_owner=False)
        user.is_server_owner = True
        user.save(update_fields=['is_server_owner'])
        self.stdout.write(self.style.SUCCESS(f'已设为服务器管理者：{username}'))
