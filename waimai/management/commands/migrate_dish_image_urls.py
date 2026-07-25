# 批次 G · G1-5：把商品旧 image_url 外链下载到本地并清空字段

from django.core.management.base import BaseCommand

from waimai.models import Dish
from waimai.product_image_helpers import migrate_all_legacy_dish_image_urls


class Command(BaseCommand):
    help = '迁移商品旧 image_url 外链：有效则落本地图，然后一律清空外链字段'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='只预演，不写库、不落盘',
        )
        parser.add_argument(
            '--seller',
            type=str,
            help='只处理指定卖家账号',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        seller = (options.get('seller') or '').strip()

        qs = Dish.objects.all()
        if seller:
            qs = qs.filter(seller_id=seller)

        stats = migrate_all_legacy_dish_image_urls(qs, dry_run=dry_run)
        mode = '预演' if dry_run else '完成'
        self.stdout.write(
            self.style.SUCCESS(
                f'旧外链迁移{mode}：'
                f'落盘 {stats.get("downloaded", 0)}，'
                f'失效 {stats.get("dead", 0)}，'
                f'已有本地图仅清链 {stats.get("cleared_only", 0)}，'
                f'图满仅清链 {stats.get("full", 0)}，'
                f'跳过 {stats.get("skipped", 0)}'
            )
        )
