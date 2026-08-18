# 北京时间每日拆掉体验店（账号与客人资格保留；官方小店与正式号不动）

from django.core.management.base import BaseCommand

from waimai.experience_helpers import purge_experience_data


class Command(BaseCommand):
    help = '拆掉体验店并摘掉店主帽子，保留体验账号；不动官方小店与正式保留号'

    def handle(self, *args, **options):
        stats = purge_experience_data()
        self.stdout.write(self.style.SUCCESS(
            f'体验日清完成：店铺 {stats["shops"]}，工牌 {stats["staff"]}，'
            f'摘掉店主帽子 {stats["hats"]}，该店订单 {stats["orders"]}；'
            f'体验账号保留 {stats["users"]}'
        ))
