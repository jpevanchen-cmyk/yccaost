# 野草互动社区：唯一二级页；留言板/公开墙从大厅搬走

import uuid

from django.db import migrations, models
from django.db.models import Max


def forwards_seed_community(apps, schema_editor):
    """建唯一互动社区页，并把大厅上的留言板/公开墙改挂过去。"""
    ServerHomePage = apps.get_model('waimai', 'ServerHomePage')
    ServerHomeBlock = apps.get_model('waimai', 'ServerHomeBlock')

    hall = ServerHomePage.objects.filter(page_role='hall').first()
    if hall is None:
        return

    page = ServerHomePage.objects.filter(page_role='community').first()
    if page is None:
        agg = ServerHomePage.objects.aggregate(m=Max('singleton_id'))
        page_id = max(2, (agg['m'] or 1) + 1)
        slug = f'p{page_id}'
        suffix = 2
        while ServerHomePage.objects.filter(slug=slug).exists():
            slug = f'p{page_id}-{suffix}'
            suffix += 1
        page = ServerHomePage.objects.create(
            singleton_id=page_id,
            page_role='community',
            slug=slug,
            title='野草互动社区',
            welcome_body='',
            welcome_enabled=True,
        )

    defaults = {
        'contact_us': ('联系我们', '', '联系', 50),
        'public_wall': ('野草公开留言壁', '', '留言壁', 52),
    }
    for code, (title, body, nav, sort) in defaults.items():
        comm = ServerHomeBlock.objects.filter(home_page=page, block_type=code).first()
        hall_rows = list(ServerHomeBlock.objects.filter(home_page=hall, block_type=code))
        for hall_block in hall_rows:
            if comm is None:
                hall_block.home_page = page
                hall_block.save(update_fields=['home_page'])
                comm = hall_block
            elif hall_block.pk != comm.pk:
                hall_block.delete()
        if comm is None:
            ServerHomeBlock.objects.create(
                block_id=uuid.uuid4(),
                home_page=page,
                block_type=code,
                title=title,
                body=body,
                nav_label=nav,
                is_enabled=True,
                show_in_nav=True,
                sort_order=sort,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0061_public_wall_reply_signer'),
    ]

    operations = [
        migrations.AlterField(
            model_name='serverhomepage',
            name='page_role',
            field=models.CharField(
                choices=[
                    ('hall', '一级大厅'),
                    ('topic', '二级专题页'),
                    ('community', '野草互动社区'),
                ],
                db_index=True,
                default='hall',
                max_length=16,
                verbose_name='页角色',
            ),
        ),
        migrations.AddConstraint(
            model_name='serverhomepage',
            constraint=models.UniqueConstraint(
                condition=models.Q(('page_role', 'community')),
                fields=('page_role',),
                name='uniq_server_home_page_community',
            ),
        ),
        migrations.RunPython(forwards_seed_community, migrations.RunPython.noop),
    ]
