# 将某店标记为官方小店（正式保留，不占体验额度、不日清、可真付）

from django.core.management.base import BaseCommand, CommandError

from waimai.experience_helpers import mark_shop_official
from waimai.models import ShopProfile


class Command(BaseCommand):
    help = '标记官方小店：python manage.py mark_official_shop --seller_id=店主用户名'

    def add_arguments(self, parser):
        parser.add_argument('--seller_id', required=True, help='店主用户名（店铺账号ID）')

    def handle(self, *args, **options):
        seller_id = (options['seller_id'] or '').strip()
        if not ShopProfile.objects.filter(seller_id=seller_id).exists():
            raise CommandError(f'找不到店铺：{seller_id}')
        mark_shop_official(seller_id)
        self.stdout.write(self.style.SUCCESS(f'已标记官方小店：{seller_id}（店主与员工为正式保留号）'))
