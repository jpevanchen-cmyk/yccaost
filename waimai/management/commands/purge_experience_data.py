# 北京时间每日清空体验账号与体验店（官方小店与正式号保留）

from django.core.management.base import BaseCommand

from waimai.experience_helpers import purge_experience_data


class Command(BaseCommand):
    help = '清空体验机上的体验账号/体验店相关数据；不动官方小店与正式保留号'

    def handle(self, *args, **options):
        stats = purge_experience_data()
        self.stdout.write(self.style.SUCCESS(
            f'体验日清完成：店铺 {stats["shops"]}，用户 {stats["users"]}，订单 {stats["orders"]}'
        ))
