# 店铺员工子账号：工牌用户名仅在本店唯一（库内用「店铺ID::工牌名」存储）

import socket
import csv
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from django.contrib.auth import authenticate
from django import forms
from django.http import HttpResponse
from django.utils import timezone

from .models import StaffAttendanceLog, User
from .shop_work_helpers import SHOP_STAFF_ROLES

STAFF_USERNAME_SEP = '::'
STAFF_WORK_ON_DUTY = 'on_duty'
STAFF_WORK_BREAK = 'break'
STAFF_WORK_OFF_DUTY = 'off_duty'
ATTENDANCE_SOURCE_SELF = 'self'
ATTENDANCE_SOURCE_MANAGER = 'manager'
ATTENDANCE_SOURCE_SYSTEM = 'system'
ATTENDANCE_RETENTION_FOREVER = 'forever'
ATTENDANCE_STATUS_LABELS = {
    STAFF_WORK_ON_DUTY: '上班',
    STAFF_WORK_BREAK: '休息',
    STAFF_WORK_OFF_DUTY: '下班',
    'active': '上班',
    'inactive': '下班',
}
ATTENDANCE_SOURCE_LABELS = {
    ATTENDANCE_SOURCE_SELF: '员工本人',
    ATTENDANCE_SOURCE_MANAGER: '老板补改',
    ATTENDANCE_SOURCE_SYSTEM: '系统自动',
}
STAFF_ROLE_LABELS = {
    'waiter': '服务员',
    'kitchen': '后厨',
    'rider': '骑手',
}


def staff_internal_username(seller_id: str, display_name: str) -> str:
    """数据库里的登录名（全局唯一，但按店加前缀）"""
    seller = (seller_id or '').strip()
    name = (display_name or '').strip()
    return f'{seller}{STAFF_USERNAME_SEP}{name}'


def staff_display_username(username: str) -> str:
    """页面上显示给店主/员工看的短用户名"""
    text = (username or '').strip()
    if STAFF_USERNAME_SEP in text:
        return text.split(STAFF_USERNAME_SEP, 1)[1]
    return text


def staff_username_taken(seller_id: str, display_name: str) -> bool:
    """本店是否已有该工牌用户名"""
    internal = staff_internal_username(seller_id, display_name)
    return User.objects.filter(username=internal).exists()


def authenticate_shop_work_user(request, seller_id: str, login_name: str, password: str):
    """
    店铺工作台登录：
    - 店主用生态用户名
    - 员工用工牌名（仅在本店查重）
    """
    login_name = (login_name or '').strip()
    seller_id = (seller_id or '').strip()
    if not login_name or not password:
        return None

    # 店主
    user = authenticate(request, username=login_name, password=password)
    if user and user.is_active and user.role == 'seller' and user.username == seller_id:
        return user

    # 员工（新规则：带店铺前缀）
    internal = staff_internal_username(seller_id, login_name)
    user = authenticate(request, username=internal, password=password)
    if user and user.is_active and user.role in SHOP_STAFF_ROLES:
        if (user.employer_seller_id or '').strip() == seller_id:
            return user

    # 兼容尚未迁移的旧工牌账号（裸用户名）
    user = authenticate(request, username=login_name, password=password)
    if user and user.is_active and user.role in SHOP_STAFF_ROLES:
        if (user.employer_seller_id or '').strip() == seller_id:
            return user

    return None


def shop_code_from_request(request) -> str:
    """从会话、表单或网址里取出店码（退出跳转用）"""
    from .shop_work_helpers import SESSION_SHOP_WORK_CODE

    code = (
        (request.POST.get('shop_work_code') or '').strip()
        or (request.GET.get('shop_work_code') or '').strip()
        or (request.session.get(SESSION_SHOP_WORK_CODE) or '').strip()
    )
    if code:
        return code
    path = (request.path or '').strip('/')
    parts = path.split('/')
    if len(parts) >= 2 and parts[0] == 's' and parts[1]:
        return parts[1]
    referer = (request.META.get('HTTP_REFERER') or '')
    if '/s/' in referer and '/work' in referer:
        try:
            seg = referer.split('/s/', 1)[1]
            return seg.split('/', 1)[0].strip()
        except (IndexError, ValueError):
            pass
    return ''


def staff_status_label(user) -> str:
    """员工当前在岗状态文案"""
    status = (getattr(user, 'staff_work_status', '') or '').strip()
    return ATTENDANCE_STATUS_LABELS.get(status, '下班')


def attendance_status_options():
    """考勤状态下拉选项"""
    return [
        (STAFF_WORK_ON_DUTY, '上班'),
        (STAFF_WORK_BREAK, '休息'),
        (STAFF_WORK_OFF_DUTY, '下班'),
    ]


class AttendanceFilterForm(forms.Form):
    """考勤组合筛选：期间 + 岗位 + 名字"""

    date_from = forms.DateField(required=False, label='开始日期', widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, label='结束日期', widget=forms.DateInput(attrs={'type': 'date'}))
    role = forms.ChoiceField(required=False, label='岗位')
    name = forms.CharField(required=False, label='名字')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [('', '全部岗位')] + [
            ('waiter', '服务员'),
            ('kitchen', '后厨'),
            ('rider', '骑手'),
        ]
        self.fields['name'].widget.attrs.update({'placeholder': '员工名字'})

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('date_from')
        end = cleaned.get('date_to')
        if start and end and start > end:
            self.add_error('date_to', '结束日期不能早于开始日期')
        return cleaned


def attendance_retention_days_value(raw_value) -> int | None:
    """把保留时长配置转成天数；长期保留返回 None"""
    value = (raw_value or '').strip()
    if value == ATTENDANCE_RETENTION_FOREVER:
        return None
    try:
        days = int(value or '90')
    except ValueError:
        return 90
    return max(days, 1)


def attendance_source_label(value: str) -> str:
    """操作来源中文文案"""
    return ATTENDANCE_SOURCE_LABELS.get((value or '').strip(), '未知')


def staff_role_label(value: str) -> str:
    """岗位中文名"""
    return STAFF_ROLE_LABELS.get((value or '').strip(), value or '')


def _normalize_staff_work_status(status: str) -> str:
    """兼容旧值并统一成三态"""
    text = (status or '').strip()
    if text in ('active', STAFF_WORK_ON_DUTY):
        return STAFF_WORK_ON_DUTY
    if text == STAFF_WORK_BREAK:
        return STAFF_WORK_BREAK
    return STAFF_WORK_OFF_DUTY


def create_attendance_log(user, action: str, *, source: str, operator_username: str = '', note: str = '') -> None:
    """写入一条员工考勤流水"""
    if not user or getattr(user, 'role', '') not in SHOP_STAFF_ROLES:
        return
    StaffAttendanceLog.objects.create(
        user=user,
        seller_id=(user.employer_seller_id or '').strip(),
        username_snapshot=user.username,
        display_name_snapshot=staff_display_username(user.username),
        role_snapshot=user.role,
        action=_normalize_staff_work_status(action),
        source=(source or ATTENDANCE_SOURCE_SYSTEM).strip(),
        operator_username=(operator_username or '').strip(),
        note=(note or '').strip(),
    )


def set_staff_work_status(user, status: str, *, source: str = ATTENDANCE_SOURCE_SYSTEM, operator_username: str = '', note: str = '', force_log: bool = False) -> bool:
    """
    统一切换员工在岗状态：
    - on_duty：上班，可接单
    - break：休息，不接单
    - off_duty：下班，不接单
    """
    role = getattr(user, 'role', '')
    if not user or role not in SHOP_STAFF_ROLES:
        return False
    target = _normalize_staff_work_status(status)
    changed = _normalize_staff_work_status(user.staff_work_status) != target
    user.staff_work_status = target
    user.staff_work_status_updated_at = timezone.now()
    user.save(update_fields=['staff_work_status', 'staff_work_status_updated_at'])
    if changed or force_log:
        create_attendance_log(
            user,
            target,
            source=source,
            operator_username=operator_username,
            note=note,
        )
    return changed


def activate_staff_on_login(user) -> None:
    """员工登录工作台后自动进入上班状态"""
    set_staff_work_status(user, STAFF_WORK_ON_DUTY, source=ATTENDANCE_SOURCE_SYSTEM, force_log=True)


def deactivate_staff_on_logout(user) -> None:
    """员工退出工作台后自动回到下班状态"""
    set_staff_work_status(user, STAFF_WORK_OFF_DUTY, source=ATTENDANCE_SOURCE_SYSTEM, force_log=True)


def handle_staff_work_status_post(request, user, *, redirect_to: str):
    """员工本人手动切换上班/休息/下班；卖家账号不处理"""
    from django.contrib import messages
    from django.shortcuts import redirect

    from .shop_work_auth import clear_shop_work_session

    role = getattr(user, 'role', '')
    if not user or role not in SHOP_STAFF_ROLES:
        return None
    action = (request.POST.get('staff_work_status_action') or '').strip()
    if not action:
        return None
    if action == 'start':
        set_staff_work_status(
            user,
            STAFF_WORK_ON_DUTY,
            source=ATTENDANCE_SOURCE_SELF,
            operator_username=user.username,
            force_log=True,
        )
        messages.success(request, '已切换为上班')
    elif action == 'break':
        set_staff_work_status(
            user,
            STAFF_WORK_BREAK,
            source=ATTENDANCE_SOURCE_SELF,
            operator_username=user.username,
            force_log=True,
        )
        messages.success(request, '已切换为休息')
    elif action == 'stop':
        set_staff_work_status(
            user,
            STAFF_WORK_OFF_DUTY,
            source=ATTENDANCE_SOURCE_SELF,
            operator_username=user.username,
            force_log=True,
        )
        clear_shop_work_session(request)
        messages.success(request, '已下班并退出工作台')
    else:
        messages.error(request, '无效的状态操作')
    return redirect(redirect_to)


def purge_old_attendance_logs(seller_id: str, retention_value: str) -> int:
    """按店铺设置清理超期考勤记录；长期保留则不删"""
    days = attendance_retention_days_value(retention_value)
    if days is None:
        return 0
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = StaffAttendanceLog.objects.filter(seller_id=seller_id, changed_at__lt=cutoff).delete()
    return deleted


def query_attendance_logs(seller_id: str, retention_value: str, filters: dict | None = None):
    """取店铺考勤流水（已按保留时长与组合条件过滤）"""
    qs = StaffAttendanceLog.objects.filter(seller_id=seller_id)
    days = attendance_retention_days_value(retention_value)
    if days is not None:
        cutoff = timezone.now() - timedelta(days=days)
        qs = qs.filter(changed_at__gte=cutoff)
    data = filters or {}
    start = data.get('date_from')
    if start:
        qs = qs.filter(changed_at__date__gte=start)
    end = data.get('date_to')
    if end:
        qs = qs.filter(changed_at__date__lte=end)
    role = (data.get('role') or '').strip()
    if role:
        qs = qs.filter(role_snapshot=role)
    name = (data.get('name') or '').strip()
    if name:
        qs = qs.filter(display_name_snapshot__icontains=name)
    return qs.select_related('user')


def build_staff_status_rows(staff_users, attendance_logs) -> list[dict]:
    """把当前员工状态整理成老板易看的表格行"""
    today = timezone.localdate()
    by_user: dict[str, list] = {}
    for log in attendance_logs:
        key = log.username_snapshot or ''
        by_user.setdefault(key, []).append(log)

    rows = []
    for user in staff_users:
        logs = by_user.get(user.username, [])
        today_logs = [log for log in logs if timezone.localtime(log.changed_at).date() == today]
        first_on_duty = next((log for log in reversed(today_logs) if log.action == STAFF_WORK_ON_DUTY), None)
        last_today = today_logs[0] if today_logs else None
        rows.append({
            'user': user,
            'role_label': user.get_role_display(),
            'display_name': staff_display_username(user.username),
            'status_label': staff_status_label(user),
            'first_on_duty_today': first_on_duty.changed_at if first_on_duty else None,
            'last_today': last_today,
            'status_updated_at': user.staff_work_status_updated_at,
        })
    return rows


def export_attendance_csv(logs, *, seller_id: str) -> HttpResponse:
    """导出考勤流水 CSV"""
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{seller_id}-staff-attendance.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['时间', '员工姓名', '岗位', '动作', '来源', '操作人账号', '备注'])
    for log in logs:
        writer.writerow([
            timezone.localtime(log.changed_at).strftime('%Y-%m-%d %H:%M:%S'),
            log.display_name_snapshot,
            staff_role_label(log.role_snapshot),
            ATTENDANCE_STATUS_LABELS.get(log.action, log.action),
            attendance_source_label(log.source),
            log.operator_username,
            log.note,
        ])
    return response


def handle_manager_staff_status_post(request, seller_id: str, *, section: str = 'workbench'):
    """老板在考勤表中兜底改状态"""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    if 'manager_set_staff_status' not in request.POST:
        return None
    username = (request.POST.get('attendance_username') or '').strip()
    status = (request.POST.get('attendance_status') or '').strip()
    note = (request.POST.get('attendance_note') or '').strip()
    user = get_object_or_404(
        User,
        username=username,
        employer_seller_id=seller_id,
        role__in=SHOP_STAFF_ROLES,
    )
    set_staff_work_status(
        user,
        status,
        source=ATTENDANCE_SOURCE_MANAGER,
        operator_username=request.user.username,
        note=note or '老板补改',
        force_log=True,
    )
    messages.success(request, f'已把 {staff_display_username(user.username)} 改为{staff_status_label(user)}')
    return redirect('seller_panel_section', section=section)


def get_local_network_ip() -> str:
    """取当前电脑在局域网里的常用 IP，给手机扫码用"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = ''
    finally:
        sock.close()
    if ip.startswith('127.'):
        return ''
    return ip


def build_mobile_share_url(page_url: str) -> str:
    """把本机链接改成手机可访问的局域网链接"""
    text = (page_url or '').strip()
    if not text:
        return ''
    lan_ip = get_local_network_ip()
    if not lan_ip:
        return ''
    parts = urlsplit(text)
    host = parts.hostname or ''
    if host not in ('127.0.0.1', 'localhost'):
        return text
    port = f':{parts.port}' if parts.port else ''
    new_netloc = f'{lan_ip}{port}'
    return urlunsplit((parts.scheme, new_netloc, parts.path, parts.query, parts.fragment))


# 三岗位停用/启用：表单字段名与岗位称谓
STAFF_TOGGLE_POST = {
    'waiter': ('toggle_waiter', 'waiter_username', '服务员'),
    'kitchen': ('toggle_kitchen', 'kitchen_username', '后厨'),
    'rider': ('toggle_rider', 'rider_username', '骑手'),
}


def handle_seller_staff_toggle_post(request, seller_id: str, role: str, *, section='workbench'):
    """
    卖家后台：切换本店员工子账号启用/停用。
    若本次提交不是该岗位的切换操作，返回 None。
    """
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    cfg = STAFF_TOGGLE_POST.get(role)
    if not cfg:
        return None
    flag_name, username_field, role_label = cfg
    if flag_name not in request.POST:
        return None
    username = request.POST.get(username_field, '').strip()
    user = get_object_or_404(
        User,
        username=username,
        role=role,
        employer_seller_id=seller_id,
    )
    user.is_active = not user.is_active
    if not user.is_active:
        user.staff_work_status = STAFF_WORK_OFF_DUTY
        user.staff_work_status_updated_at = timezone.now()
        user.save(update_fields=['is_active', 'staff_work_status', 'staff_work_status_updated_at'])
        create_attendance_log(
            user,
            STAFF_WORK_OFF_DUTY,
            source=ATTENDANCE_SOURCE_MANAGER,
            operator_username=request.user.username,
            note='老板停用账号',
        )
    else:
        user.save(update_fields=['is_active'])
    display = staff_display_username(user.username)
    state_word = '启用' if user.is_active else '停用'
    messages.success(request, f'已{state_word}{role_label} {display}')
    return redirect('seller_panel_section', section=section)
