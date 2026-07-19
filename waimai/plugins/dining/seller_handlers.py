# 饮食插件：卖家「堂食营业」页 POST（分时段/等待/拼桌/桌台）
# 全天营业时间与营业中/停止在主体 operating；菜单清单不在本文件

from django.contrib import messages
from django.db import transaction
from django.urls import reverse

from waimai.forms import ShopOperatingSettingsForm
from waimai.models import ShopProfile, ShopTable, TableSession, VirtualTableCode
from waimai.operating_helpers import get_operating_settings
from waimai.scroll_helpers import redirect_with_anchor

from .table_bulk_helpers import (
    bulk_create_tables,
    bulk_create_virtual_codes,
    sort_shop_tables,
    sort_virtual_codes,
    validate_table_number,
    validate_virtual_label,
)
from .wait_time_helpers import parse_wait_time_rules, replace_wait_time_rules


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
    """饮食插件堂食页 POST（分时段 / 等待 / 拼桌 / 桌台）"""
    if 'save_operating' in request.POST:
        settings = get_operating_settings(seller_id)
        form = ShopOperatingSettingsForm(request.POST, instance=settings)
        if not form.is_valid():
            err = next(iter(form.errors.values()), None)
            msg = err[0] if err else '堂食设置无效，请检查输入'
            messages.error(request, msg)
            return _seller_redirect('dine', 'dining-settings')

        wait_time_rules, wait_error = parse_wait_time_rules(request.POST)
        if wait_error:
            messages.error(request, wait_error)
            return _seller_redirect('dine', 'dining-settings')

        data = form.cleaned_data

        # 首次保存须确认桌码硬规则
        if not settings.table_rules_acknowledged:
            if not data.get('acknowledge_table_rules'):
                messages.error(request, '首次保存须勾选「已阅读桌码主单硬规则」')
                return _seller_redirect('dine', 'dining-settings')
            settings.table_rules_acknowledged = True

        if data.get('share_table_enabled') and not data.get('share_table_mode'):
            messages.error(request, '开启拼桌须选择模式 A 或模式 B')
            return _seller_redirect('dine', 'dining-settings')

        # 开启拼桌时须确认拼桌硬规则（首次开启或尚未确认过）
        if data.get('share_table_enabled'):
            if not data.get('confirm_share_rules') and not settings.share_rules_confirmed:
                messages.error(request, '开启拼桌须勾选「已阅读拼桌硬规则」')
                return _seller_redirect('dine', 'dining-settings')
            if data.get('confirm_share_rules'):
                settings.share_rules_confirmed = True

        update_fields = list(form.Meta.fields) + [
            'table_rules_acknowledged', 'share_rules_confirmed',
        ]
        with transaction.atomic():
            for field in form.Meta.fields:
                setattr(settings, field, data[field])
            settings.save(update_fields=update_fields)
            replace_wait_time_rules(settings, wait_time_rules)
        from waimai.audit_helpers import write_audit_log
        write_audit_log(
            action_code='operating',
            summary='保存堂食接单与拼桌设置',
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        messages.success(request, '堂食接单与拼桌设置已保存')
        return _seller_redirect('dine', 'dining-settings')

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

            from .table_sticker_pdf import (
                build_table_stickers_pdf,
                sticker_pdf_filename,
            )

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
        elif action == 'export_pdf':
            from django.http import HttpResponse

            from .table_sticker_pdf import (
                build_virtual_stickers_pdf,
                virtual_sticker_pdf_filename,
            )

            profile = ShopProfile.objects.filter(seller_id=seller_id).first()
            pdf_bytes = build_virtual_stickers_pdf(
                request=request,
                seller_id=seller_id,
                codes=sort_virtual_codes(codes),
                shop_profile=profile,
            )
            resp = HttpResponse(pdf_bytes, content_type='application/pdf')
            resp['Content-Disposition'] = (
                f'attachment; filename="{virtual_sticker_pdf_filename(seller_id)}"'
            )
            return resp
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
