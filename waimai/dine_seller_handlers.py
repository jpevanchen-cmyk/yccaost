# 卖家面板：堂食营业 + 桌台 + 菜单清单 POST 处理

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone

from .forms import ShopOperatingSettingsForm
from .models import (
    BuyOrder,
    Dish,
    MenuProfile,
    MenuProfileItem,
    ShopOperatingSettings,
    ShopTable,
    TableSession,
    VirtualTableCode,
)
from .operating_helpers import get_operating_settings, has_open_orders
from .scroll_helpers import redirect_with_anchor
from .table_bulk_helpers import (
    bulk_create_tables,
    bulk_create_virtual_codes,
    sort_shop_tables,
    sort_virtual_codes,
    validate_table_number,
    validate_virtual_label,
)
from .table_helpers import build_table_scan_path, build_virtual_scan_path


def _seller_redirect(section, anchor=None, query=None):
    url = reverse('seller_panel_section', kwargs={'section': section})
    if query:
        url = f'{url}?{query}'
    return redirect_with_anchor(url, anchor)


def _parse_int(val, default=None):
    val = (val or '').strip()
    if not val.isdigit():
        return default
    return int(val)


def _flash_bulk_result(request, created, skipped, action_name, extra_notes=None):
    """批量操作结果写入弹窗提示"""
    parts = []
    if created:
        parts.append(f'成功新建 {created} 个{action_name}')
    if skipped:
        parts.append(f'跳过 {skipped} 个（已存在或冲突）')
    if extra_notes:
        parts.extend(extra_notes[:5])
        if len(extra_notes) > 5:
            parts.append(f'…另有 {len(extra_notes) - 5} 条提示')
    if not parts:
        messages.error(request, f'没有新建任何{action_name}，请检查范围或是否已全部存在')
    elif created:
        messages.success(request, '；'.join(parts))
    else:
        messages.error(request, '；'.join(parts))


def _parse_id_list(request, field_name='selected_ids'):
    """解析批量操作选中的 ID 列表"""
    raw = request.POST.getlist(field_name) or request.POST.get(field_name, '')
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(',') if x.strip()]
    return [x for x in raw if x]


def _table_has_open_session(table) -> bool:
    return TableSession.objects.filter(shop_table=table, status='open').exists()


def _virtual_has_open_session(code) -> bool:
    return TableSession.objects.filter(virtual_code=code, status='open').exists()


def handle_dine_post(request, seller_id):
    """堂食营业 + 桌台分区 POST"""
    if 'save_operating' in request.POST:
        settings = get_operating_settings(seller_id)
        form = ShopOperatingSettingsForm(request.POST, instance=settings)
        if not form.is_valid():
            err = next(iter(form.errors.values()), None)
            msg = err[0] if err else '营业设置无效，请检查输入'
            messages.error(request, msg)
            return _seller_redirect('dine', 'operating-form')
        from .wait_time_helpers import parse_wait_time_rules, replace_wait_time_rules

        wait_time_rules, wait_error = parse_wait_time_rules(request.POST)
        if wait_error:
            messages.error(request, wait_error)
            return _seller_redirect('dine', 'operating-form')

        data = form.cleaned_data

        # 首次保存须确认桌码硬规则
        if not settings.table_rules_acknowledged:
            if not data.get('acknowledge_table_rules'):
                messages.error(request, '首次保存须勾选「已阅读桌码主单硬规则」')
                return _seller_redirect('dine', 'operating-form')
            settings.table_rules_acknowledged = True

        if data.get('share_table_enabled') and not data.get('share_table_mode'):
            messages.error(request, '开启拼桌须选择模式 A 或模式 B')
            return _seller_redirect('dine', 'operating-form')

        # 开启拼桌时须确认拼桌硬规则（首次开启或尚未确认过）
        if data.get('share_table_enabled'):
            if not data.get('confirm_share_rules') and not settings.share_rules_confirmed:
                messages.error(request, '开启拼桌须勾选「已阅读拼桌硬规则」')
                return _seller_redirect('dine', 'operating-form')
            if data.get('confirm_share_rules'):
                settings.share_rules_confirmed = True

        with transaction.atomic():
            for field in form.Meta.fields:
                setattr(settings, field, data[field])
            settings.save()
            replace_wait_time_rules(settings, wait_time_rules)
        from .audit_helpers import write_audit_log
        write_audit_log(
            action_code='operating',
            summary='保存营业与堂食设置',
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        messages.success(request, '营业与堂食设置已保存')
        return _seller_redirect('dine', 'operating-form')

    if 'toggle_closed' in request.POST:
        settings = get_operating_settings(seller_id)
        settings.closed_for_today = not settings.closed_for_today
        settings.save(update_fields=['closed_for_today'])
        label = '本日打烊' if settings.closed_for_today else '恢复营业'
        from .audit_helpers import write_audit_log
        write_audit_log(
            action_code='operating',
            summary=f'切换：{label}',
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        messages.success(request, f'已切换：{label}')
        return _seller_redirect('dine')

    if 'toggle_pause' in request.POST:
        settings = get_operating_settings(seller_id)
        settings.pause_new_orders = not settings.pause_new_orders
        settings.save(update_fields=['pause_new_orders'])
        label = '暂停接单' if settings.pause_new_orders else '恢复接单'
        from .audit_helpers import write_audit_log
        write_audit_log(
            action_code='operating',
            summary=f'切换：{label}',
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        messages.success(request, f'已切换：{label}')
        return _seller_redirect('dine')

    if 'add_table' in request.POST:
        t_min = _parse_int(request.POST.get('table_min'))
        t_max = _parse_int(request.POST.get('table_max'))
        if t_min is None or t_max is None:
            messages.error(request, '请填写最小桌号和最大桌号（纯数字）')
            return _seller_redirect('dine', 'table-list')

        created, skipped, notes = bulk_create_tables(seller_id, t_min, t_max)
        _flash_bulk_result(request, created, skipped, '桌台', notes)
        return _seller_redirect('dine', 'table-list')

    if 'add_single_table' in request.POST:
        num = (request.POST.get('table_number') or '').strip()
        ok, result = validate_table_number(num)
        if not ok:
            messages.error(request, result)
        elif ShopTable.objects.filter(seller_id=seller_id, table_number=result).exists():
            messages.error(request, f'桌号「{result}」已存在，未重复创建')
        else:
            ShopTable.objects.create(seller_id=seller_id, table_number=result)
            messages.success(request, f'已添加桌号 {result}')
        return _seller_redirect('dine', 'table-list')

    if 'table_batch_action' in request.POST:
        action = (request.POST.get('batch_action') or '').strip()
        ids = _parse_id_list(request)
        if not ids:
            messages.error(request, '请先点选要操作的桌号')
            return _seller_redirect('dine', 'table-list')

        tables = list(ShopTable.objects.filter(seller_id=seller_id, table_id__in=ids))
        if not tables:
            messages.error(request, '未找到所选桌号')
            return _seller_redirect('dine', 'table-list')

        labels = [t.table_number for t in sort_shop_tables(tables)]

        if action == 'enable':
            ShopTable.objects.filter(seller_id=seller_id, table_id__in=ids).update(is_active=True)
            messages.success(request, f'已启用桌号：{", ".join(labels)}')
        elif action == 'disable':
            ShopTable.objects.filter(seller_id=seller_id, table_id__in=ids).update(is_active=False)
            messages.success(request, f'已停用桌号：{", ".join(labels)}')
        elif action == 'delete':
            deleted, blocked = [], []
            for table in tables:
                if _table_has_open_session(table):
                    blocked.append(table.table_number)
                    continue
                deleted.append(table.table_number)
                table.delete()
            if deleted:
                messages.success(request, f'已删除桌号：{", ".join(deleted)}')
            if blocked:
                messages.error(request, f'以下桌号有进行中的会话，无法删除：{", ".join(blocked)}')
            if not deleted and not blocked:
                messages.error(request, '删除失败')
        elif action == 'export_pdf':
            from django.http import HttpResponse

            from .models import ShopProfile
            from .table_sticker_pdf import build_table_stickers_pdf, sticker_pdf_filename

            profile = ShopProfile.objects.filter(seller_id=seller_id).first()
            pdf_bytes = build_table_stickers_pdf(
                request=request,
                seller_id=seller_id,
                tables=sort_shop_tables(tables),
                shop_profile=profile,
            )
            resp = HttpResponse(pdf_bytes, content_type='application/pdf')
            resp['Content-Disposition'] = f'attachment; filename="{sticker_pdf_filename(seller_id)}"'
            return resp
        else:
            messages.error(request, '未知操作')
        return _seller_redirect('dine', 'table-list')

    if 'add_virtual_code' in request.POST:
        settings = get_operating_settings(seller_id)
        if not settings.share_table_enabled or settings.share_table_mode != 'virtual':
            messages.error(request, '须先开启拼桌模式 B 才能添加虚拟桌码')
            return _seller_redirect('dine', 'virtual-list')

        v_min = _parse_int(request.POST.get('virtual_min'))
        v_max = _parse_int(request.POST.get('virtual_max'))
        if v_min is not None and v_max is not None:
            created, skipped, notes = bulk_create_virtual_codes(seller_id, v_min, v_max)
            _flash_bulk_result(request, created, skipped, '虚拟桌码', notes)
            return _seller_redirect('dine', 'virtual-list')

        label = (request.POST.get('code_label') or '').strip()
        ok, result = validate_virtual_label(label, seller_id)
        if not ok:
            messages.error(request, result)
        elif VirtualTableCode.objects.filter(seller_id=seller_id, code_label=result).exists():
            messages.error(request, f'虚拟码「{result}」已存在，未重复创建')
        else:
            VirtualTableCode.objects.create(seller_id=seller_id, code_label=result)
            messages.success(request, f'已添加虚拟桌码 {result}')
        return _seller_redirect('dine', 'virtual-list')

    if 'virtual_batch_action' in request.POST:
        settings = get_operating_settings(seller_id)
        if not settings.share_table_enabled or settings.share_table_mode != 'virtual':
            messages.error(request, '须先开启拼桌模式 B')
            return _seller_redirect('dine', 'virtual-list')

        action = (request.POST.get('batch_action') or '').strip()
        ids = _parse_id_list(request)
        if not ids:
            messages.error(request, '请先点选要操作的虚拟码')
            return _seller_redirect('dine', 'virtual-list')

        codes = list(VirtualTableCode.objects.filter(seller_id=seller_id, code_id__in=ids))
        if not codes:
            messages.error(request, '未找到所选虚拟码')
            return _seller_redirect('dine', 'virtual-list')

        labels = [c.code_label for c in sort_virtual_codes(codes)]

        if action == 'enable':
            VirtualTableCode.objects.filter(seller_id=seller_id, code_id__in=ids).update(is_active=True)
            messages.success(request, f'已启用虚拟码：{", ".join(labels)}')
        elif action == 'disable':
            VirtualTableCode.objects.filter(seller_id=seller_id, code_id__in=ids).update(is_active=False)
            messages.success(request, f'已停用虚拟码：{", ".join(labels)}')
        elif action == 'delete':
            deleted, blocked = [], []
            for code in codes:
                if _virtual_has_open_session(code):
                    blocked.append(code.code_label)
                    continue
                deleted.append(code.code_label)
                code.delete()
            if deleted:
                messages.success(request, f'已删除虚拟码：{", ".join(deleted)}')
            if blocked:
                messages.error(request, f'以下虚拟码使用中，无法删除：{", ".join(blocked)}')
            if not deleted and not blocked:
                messages.error(request, '删除失败')
        else:
            messages.error(request, '未知操作')
        return _seller_redirect('dine', 'virtual-list')

    if 'open_share_order' in request.POST:
        settings = get_operating_settings(seller_id)
        if not settings.share_table_enabled or settings.share_table_mode != 'waiter':
            messages.error(request, '须先开启拼桌模式 A')
            return _seller_redirect('dine', 'share-waiter')
        table_num = (request.POST.get('table_number') or '').strip()
        ok, num = validate_table_number(table_num)
        if not ok:
            messages.error(request, num)
            return _seller_redirect('dine', 'share-waiter')
        table = ShopTable.objects.filter(seller_id=seller_id, table_number=num, is_active=True).first()
        if not table:
            messages.error(request, f'桌号「{num}」不存在或未启用')
            return _seller_redirect('dine', 'share-waiter')
        seq = TableSession.objects.filter(
            seller_id=seller_id, shop_table=table, session_type='share_waiter',
        ).count() + 1
        share_label = f'{num}-A{seq:03d}'
        TableSession.objects.create(
            seller_id=seller_id,
            shop_table=table,
            session_type='share_waiter',
            share_label=share_label,
        )
        messages.success(request, f'已开拼桌单 {share_label}（须由服务员全程操作）')
        return _seller_redirect('dine', 'share-waiter')

    return None


def _menus_query(profile_id=None):
    if profile_id:
        return f'profile={profile_id}'
    return ''


def handle_menus_post(request, seller_id):
    """菜单清单分区 POST"""
    profile_q = request.POST.get('profile_id', '')

    if 'create_menu_profile' in request.POST:
        name = (request.POST.get('profile_name') or '').strip()
        if not name:
            messages.error(request, '请填写清单名称')
        else:
            profile = MenuProfile.objects.create(seller_id=seller_id, name=name)
            messages.success(request, f'已创建菜单清单「{name}」')
            profile_q = str(profile.profile_id)
        return _seller_redirect('menus', 'menu-panel', _menus_query(profile_q))

    if 'add_dish_to_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        dish_id = request.POST.get('dish_id')
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        dish = get_object_or_404(Dish, dish_id=dish_id, seller_id=seller_id)
        cap = request.POST.get('sales_cap', '').strip()
        sales_cap = int(cap) if cap.isdigit() else None
        item, created = MenuProfileItem.objects.get_or_create(
            profile=profile, dish=dish,
            defaults={'sales_cap': sales_cap, 'is_listed': True},
        )
        if not created:
            item.sales_cap = sales_cap
            item.is_listed = True
            item.save()
        messages.success(request, f'已将「{dish.name}」加入清单「{profile.name}」')
        return _seller_redirect('menus', 'menu-panel', _menus_query(profile_id))

    if 'activate_menu_profile' in request.POST:
        if has_open_orders(seller_id):
            messages.error(request, '尚有未结束订单，不能切换菜单清单')
            return _seller_redirect('menus', 'menu-panel', _menus_query(profile_q))
        profile_id = request.POST.get('profile_id')
        profile = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        settings = get_operating_settings(seller_id)
        settings.active_menu_profile = profile
        settings.save(update_fields=['active_menu_profile'])
        MenuProfileItem.objects.filter(profile=profile).update(sold_count=0)
        from .audit_helpers import write_audit_log
        write_audit_log(
            action_code='menu_switch',
            summary=f'切换菜单清单为「{profile.name}」',
            seller_id=seller_id,
            actor=request.user,
            target_type='menu_profile',
            target_id=str(profile.profile_id),
            request=request,
        )
        messages.success(request, f'已切换为菜单清单「{profile.name}」')
        return _seller_redirect('menus', 'menu-panel', _menus_query(profile_id))

    if 'copy_menu_profile' in request.POST:
        profile_id = request.POST.get('profile_id')
        source = get_object_or_404(MenuProfile, profile_id=profile_id, seller_id=seller_id)
        new_name = (request.POST.get('new_name') or '').strip() or f'{source.name} 副本'
        new_profile = MenuProfile.objects.create(seller_id=seller_id, name=new_name)
        for item in source.items.all():
            MenuProfileItem.objects.create(
                profile=new_profile,
                dish=item.dish,
                sort_order=item.sort_order,
                is_listed=item.is_listed,
                sales_cap=item.sales_cap,
                sold_count=0,
            )
        messages.success(request, f'已复制为「{new_name}」')
        return _seller_redirect('menus', 'menu-panel', _menus_query(new_profile.profile_id))

    if 'update_dish_limits' in request.POST:
        dish_id = request.POST.get('dish_id')
        dish = get_object_or_404(Dish, dish_id=dish_id, seller_id=seller_id)
        dish.require_registered = bool(request.POST.get('require_registered'))
        dish.new_member_only = bool(request.POST.get('new_member_only'))
        max_val = request.POST.get('max_per_user', '').strip()
        dish.max_per_user = int(max_val) if max_val.isdigit() and int(max_val) > 0 else None
        sort_val = request.POST.get('sort_order', '0').strip()
        dish.sort_order = int(sort_val) if sort_val.lstrip('-').isdigit() else 0
        dish.save()
        messages.success(request, f'已更新「{dish.name}」限购与排序')
        return _seller_redirect('menus', 'dish-limits')

    return None
