from django.db import migrations, models


LEGACY_STAFF_MAP = {
    'manager': ('management', '店长', ['dining.waiter']),
    'waiter': ('employee', '服务员', ['dining.waiter']),
    'kitchen': ('employee', '后厨', ['dining.kitchen']),
    'rider': ('employee', '骑手', ['fulfillment.delivery']),
}


def migrate_legacy_staff_accounts(apps, schema_editor):
    """把旧四类岗位账号无损归入统一店铺员工壳。"""
    User = apps.get_model('waimai', 'User')
    StaffAttendanceLog = apps.get_model('waimai', 'StaffAttendanceLog')
    for old_role, (account_type, title, default_permissions) in LEGACY_STAFF_MAP.items():
        for user in User.objects.filter(role=old_role).iterator():
            permissions = list(default_permissions)
            if user.perm_cancel_order and 'orders.cancel' not in permissions:
                permissions.append('orders.cancel')
            user.role = 'staff'
            user.staff_account_type = account_type
            user.staff_job_title = title
            user.staff_permissions = permissions
            user.save(update_fields=[
                'role',
                'staff_account_type',
                'staff_job_title',
                'staff_permissions',
            ])
        StaffAttendanceLog.objects.filter(
            role_snapshot=old_role,
            job_title_snapshot='',
        ).update(
            account_type_snapshot=account_type,
            job_title_snapshot=title,
        )


def restore_legacy_staff_roles(apps, schema_editor):
    """仅供迁移回退：按已保存权限尽量还原旧岗位。"""
    User = apps.get_model('waimai', 'User')
    for user in User.objects.filter(role='staff').iterator():
        permissions = set(user.staff_permissions or [])
        if 'fulfillment.delivery' in permissions:
            role = 'rider'
        elif 'dining.kitchen' in permissions:
            role = 'kitchen'
        elif 'dining.waiter' in permissions:
            role = 'manager' if user.staff_account_type == 'management' else 'waiter'
        else:
            role = 'manager' if user.staff_account_type == 'management' else 'waiter'
        user.role = role
        user.save(update_fields=['role'])


class Migration(migrations.Migration):

    dependencies = [
        ('waimai', '0020_buyorder_basic_order_channel'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffattendancelog',
            name='account_type_snapshot',
            field=models.CharField(blank=True, default='', max_length=16, verbose_name='子账号类别快照'),
        ),
        migrations.AddField(
            model_name='staffattendancelog',
            name='job_title_snapshot',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='职务名称快照'),
        ),
        migrations.AddField(
            model_name='user',
            name='staff_account_type',
            field=models.CharField(
                blank=True,
                choices=[('management', '管理职务'), ('employee', '普通员工')],
                default='',
                max_length=16,
                verbose_name='子账号类别',
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='staff_job_title',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='职务名称'),
        ),
        migrations.AddField(
            model_name='user',
            name='staff_permissions',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='保存主体或插件提供的稳定权限编号',
                verbose_name='员工权限清单',
            ),
        ),
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('buyer', '买家'),
                    ('seller', '卖家'),
                    ('staff', '店铺员工'),
                ],
                default='buyer',
                max_length=10,
                verbose_name='用户身份',
            ),
        ),
        migrations.RunPython(migrate_legacy_staff_accounts, restore_legacy_staff_roles),
    ]
