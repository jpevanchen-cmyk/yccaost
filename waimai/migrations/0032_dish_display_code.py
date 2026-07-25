# 批次 G · G1-1：商品展示编号 + 删后占用不复用

import string

from django.db import migrations, models


def _iter_layer1_codes():
    letters = string.ascii_lowercase
    for letter in letters:
        for num in range(1, 1000):
            yield f'{letter}{num:03d}'


def _iter_layer2_codes():
    letters = string.ascii_lowercase
    for l1 in letters:
        for l2 in letters:
            for num in range(1, 1000):
                yield f'{l1}{l2}{num:03d}'


def _next_code(taken: set[str]) -> str:
    for code in _iter_layer1_codes():
        if code not in taken:
            return code
    for code in _iter_layer2_codes():
        if code not in taken:
            return code
    raise RuntimeError('本店商品展示编号已用尽')


def backfill_dish_display_codes(apps, schema_editor):
    """为已有商品按创建顺序补分配展示编号"""
    Dish = apps.get_model('waimai', 'Dish')
    seller_ids = (
        Dish.objects.order_by()
        .values_list('seller_id', flat=True)
        .distinct()
    )
    for seller_id in seller_ids:
        taken: set[str] = set()
        dishes = Dish.objects.filter(seller_id=seller_id).order_by('created_at', 'dish_id')
        for dish in dishes.iterator():
            existing = (dish.display_code or '').strip().lower()
            if existing:
                taken.add(existing)
                continue
            code = _next_code(taken)
            taken.add(code)
            Dish.objects.filter(pk=dish.pk).update(display_code=code)


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0031_dish_tier_descriptions'),
    ]

    operations = [
        migrations.CreateModel(
            name='DishDisplayCodeOccupied',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('seller_id', models.CharField(db_index=True, max_length=64, verbose_name='卖家ID')),
                ('display_code', models.CharField(max_length=5, verbose_name='展示编号')),
                ('released_at', models.DateTimeField(auto_now_add=True, verbose_name='释放时间')),
            ],
            options={
                'verbose_name': '商品展示编号占用',
                'verbose_name_plural': '商品展示编号占用',
                'db_table': 'dish_display_code_occupied',
            },
        ),
        migrations.AddField(
            model_name='dish',
            name='display_code',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='系统自动分配（小写存库）；删商品后编号不复用',
                max_length=5,
                verbose_name='展示编号',
            ),
        ),
        migrations.AddConstraint(
            model_name='dishdisplaycodeoccupied',
            constraint=models.UniqueConstraint(
                fields=('seller_id', 'display_code'),
                name='uniq_dish_display_code_occupied_per_seller',
            ),
        ),
        migrations.AddConstraint(
            model_name='dish',
            constraint=models.UniqueConstraint(
                condition=models.Q(('display_code', ''), _negated=True),
                fields=('seller_id', 'display_code'),
                name='uniq_dish_display_code_per_seller',
            ),
        ),
        migrations.RunPython(backfill_dish_display_codes, migrations.RunPython.noop),
    ]
