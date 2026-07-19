# 店铺员工子账号：工牌用户名仅在本店唯一（库内用「店铺ID::工牌名」存储）

import socket
import csv
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from django.contrib.auth import authenticate
from django import forms
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone

from .models import StaffAttendanceLog, User

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
    'manager': '店长',
    'staff': '店铺员工',
}
STAFF_ROLE = 'staff'
LEGACY_STAFF_ROLES = ('waiter', 'kitchen', 'rider', 'manager')
ALL_STAFF_ROLES = (STAFF_ROLE,) + LEGACY_STAFF_ROLES

PERM_CANCEL_ORDER = 'orders.cancel'
PERM_ORDERS_VIEW = 'orders.view'
PERM_ORDERS_UPDATE_STATUS = 'orders.update_status'
PERM_ORDERS_CONFIRM_PAYMENT = 'orders.confirm_payment'
PERM_ORDERS_CONTACT = 'orders.contact'
PERM_DINING_WAITER = 'dining.waiter'
PERM_DINING_KITCHEN = 'dining.kitchen'
# 配送属于履约能力；由履约插件贡献权限与页签（编号不绑死饮食）。
PERM_DINING_RIDER = 'fulfillment.delivery'
PERM_FULFILLMENT_CASH_MANAGE = 'fulfillment.cash_manage'

# 主体通用订单台相关权限（促成交易闭环，不依赖业态插件）
CORE_ORDER_DESK_PERMISSIONS = (
    PERM_ORDERS_VIEW,
    PERM_ORDERS_UPDATE_STATUS,
    PERM_ORDERS_CONFIRM_PAYMENT,
    PERM_ORDERS_CONTACT,
)

CORE_STAFF_PERMISSION_DEFINITIONS = [
    {
        'code': PERM_ORDERS_VIEW,
        'label': '仅看订单',
        'help_text': '可打开「订单处理」查看本店基础订单，不能改状态或收款',
    },
    {
        'code': PERM_ORDERS_UPDATE_STATUS,
        'label': '可改订单状态',
        'help_text': '可推进基础订单：开始处理 → 可交付 → 完成',
    },
    {
        'code': PERM_ORDERS_CONFIRM_PAYMENT,
        'label': '可确认收款',
        'help_text': '可确认现金等到店收款；网上支付仍由系统自动到账',
    },
    {
        'code': PERM_ORDERS_CONTACT,
        'label': '可联系顾客',
        'help_text': '可查看联系信息，并在订单沟通里留言',
    },
    {
        'code': PERM_CANCEL_ORDER,
        'label': '允许取消订单',
        'help_text': '满足沟通门槛后，可在工作台取消本店订单',
    },
]


def shop_staff_query():
    """统一店铺子账号查询条件（兼容迁移前旧四岗位）。"""
    return Q(role__in=ALL_STAFF_ROLES)


def staff_permission_query(permission_code: str):
    """按稳定权限编号筛选账号；同时兼容迁移前旧岗位。"""
    legacy_roles = {
        PERM_DINING_WAITER: ('waiter', 'manager'),
        PERM_DINING_KITCHEN: ('kitchen',),
        PERM_DINING_RIDER: ('rider',),
        PERM_CANCEL_ORDER: (),
    }
    query = Q(role=STAFF_ROLE, staff_permissions__icontains=permission_code)
    old_roles = legacy_roles.get(permission_code, ())
    if old_roles:
        query |= Q(role__in=old_roles)
    if permission_code == PERM_CANCEL_ORDER:
        query |= Q(role__in=ALL_STAFF_ROLES, perm_cancel_order=True)
    return query


def is_shop_staff_account(user) -> bool:
    """是否店铺员工子账号（不含店主）。"""
    return bool(user and getattr(user, 'role', '') in ALL_STAFF_ROLES)


def staff_permission_codes(user) -> set[str]:
    """读取权限清单；旧账号在迁移前也能按原岗位正常工作。"""
    codes = set(getattr(user, 'staff_permissions', None) or [])
    role = getattr(user, 'role', '')
    # 旧四岗位：补饮食权限；同时给主体订单台基础能力，关插件后仍能干活。
    legacy = {
        'manager': {
            PERM_DINING_WAITER,
            PERM_CANCEL_ORDER,
            PERM_FULFILLMENT_CASH_MANAGE,
            *CORE_ORDER_DESK_PERMISSIONS,
        },
        'waiter': {
            PERM_DINING_WAITER,
            *CORE_ORDER_DESK_PERMISSIONS,
        },
        'kitchen': {
            PERM_DINING_KITCHEN,
            PERM_ORDERS_VIEW,
            PERM_ORDERS_UPDATE_STATUS,
        },
        'rider': {
            PERM_DINING_RIDER,
            PERM_ORDERS_VIEW,
            PERM_ORDERS_CONTACT,
        },
    }
    codes.update(legacy.get(role, set()))
    if getattr(user, 'perm_cancel_order', False):
        codes.add(PERM_CANCEL_ORDER)
    # 已有饮食前台权限的新壳账号：默认可做主体订单台（关插件后不空转）
    if PERM_DINING_WAITER in codes:
        codes.update(CORE_ORDER_DESK_PERMISSIONS)
    elif PERM_DINING_KITCHEN in codes:
        codes.update({PERM_ORDERS_VIEW, PERM_ORDERS_UPDATE_STATUS})
    elif PERM_DINING_RIDER in codes:
        codes.update({PERM_ORDERS_VIEW, PERM_ORDERS_CONTACT})
    return codes


def staff_has_permission(user, permission_code: str) -> bool:
    """店主拥有全部店务权限；员工按权限清单判断。"""
    if not user or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'role', '') == 'seller':
        return True
    return is_shop_staff_account(user) and permission_code in staff_permission_codes(user)


def staff_has_any_order_desk_permission(user) -> bool:
    """是否可看到主体「订单处理」台（任一细权限即可）。"""
    if not user or not getattr(user, 'is_active', False):
        return False
    if getattr(user, 'role', '') == 'seller':
        return True
    codes = staff_permission_codes(user)
    return any(code in codes for code in CORE_ORDER_DESK_PERMISSIONS)


def staff_job_title(user) -> str:
    """页面显示职务名；旧账号自动回落原岗位名。"""
    title = (getattr(user, 'staff_job_title', '') or '').strip()
    if title:
        return title
    return STAFF_ROLE_LABELS.get(getattr(user, 'role', ''), '员工')


def staff_account_type_label(user) -> str:
    """页面显示两大类子账号。"""
    value = (getattr(user, 'staff_account_type', '') or '').strip()
    if not value and getattr(user, 'role', '') == 'manager':
        value = 'management'
    return '管理职务' if value == 'management' else '普通员工'


def attendance_account_type_label(log) -> str:
    """考勤快照里的两大类中文名（兼容旧流水）。"""
    value = (getattr(log, 'account_type_snapshot', '') or '').strip()
    if not value and getattr(log, 'role_snapshot', '') == 'manager':
        value = 'management'
    return '管理职务' if value == 'management' else '普通员工'


def get_shop_staff_users(seller_id: str, *, active_only: bool = False):
    """本店全部子账号，不再按写死岗位拆查询。"""
    qs = User.objects.filter(shop_staff_query(), employer_seller_id=seller_id)
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by('staff_account_type', 'date_joined', 'username')


def get_staff_permission_definitions(seller_id: str) -> list[dict]:
    """主体权限 + 当前已启用插件提供的权限。"""
    definitions = list(CORE_STAFF_PERMISSION_DEFINITIONS)
    from .plugin_runtime.registry import is_plugin_enabled, list_plugins

    for plugin in list_plugins():
        if not is_plugin_enabled(plugin.id, seller_id):
            continue
        definitions.extend(plugin.staff_permission_definitions(seller_id) or [])
    seen = set()
    return [
        item for item in definitions
        if item.get('code') and not (item['code'] in seen or seen.add(item['code']))
    ]


def get_staff_account_presets(seller_id: str, account_type: str) -> list[dict]:
    """主体默认模板 + 当前已启用插件提供的模板。"""
    presets = []
    if account_type == 'management':
        presets.append({
            'code': 'core.manager',
            'label': '店长（可改名）',
            'account_type': 'management',
            'job_title': '店长',
            'permissions': [
                *CORE_ORDER_DESK_PERMISSIONS,
                PERM_CANCEL_ORDER,
            ],
        })
    elif account_type == 'employee':
        presets.append({
            'code': 'core.order_clerk',
            'label': '店员·通用接单（可改名）',
            'account_type': 'employee',
            'job_title': '店员',
            'permissions': list(CORE_ORDER_DESK_PERMISSIONS),
        })
    from .plugin_runtime.registry import is_plugin_enabled, list_plugins

    for plugin in list_plugins():
        if not is_plugin_enabled(plugin.id, seller_id):
            continue
        presets.extend(plugin.staff_account_presets(seller_id) or [])
    return [item for item in presets if item.get('account_type') == account_type]


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
    if user and user.is_active and is_shop_staff_account(user):
        if (user.employer_seller_id or '').strip() == seller_id:
            return user

    # 兼容尚未迁移的旧工牌账号（裸用户名）
    user = authenticate(request, username=login_name, password=password)
    if user and user.is_active and is_shop_staff_account(user):
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
    """考勤组合筛选：期间 + 职务 + 名字"""

    date_from = forms.DateField(required=False, label='开始日期', widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, label='结束日期', widget=forms.DateInput(attrs={'type': 'date'}))
    role = forms.ChoiceField(required=False, label='职务')
    name = forms.CharField(required=False, label='名字')

    def __init__(self, *args, seller_id: str = '', **kwargs):
        super().__init__(*args, **kwargs)
        titles = []
        if seller_id:
            titles = sorted({
                staff_job_title(user)
                for user in get_shop_staff_users(seller_id)
                if staff_job_title(user)
            })
        self.fields['role'].choices = [('', '全部职务')] + [
            (title, title) for title in titles
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
    if not is_shop_staff_account(user):
        return
    StaffAttendanceLog.objects.create(
        user=user,
        seller_id=(user.employer_seller_id or '').strip(),
        username_snapshot=user.username,
        display_name_snapshot=staff_display_username(user.username),
        role_snapshot=user.role,
        account_type_snapshot=(getattr(user, 'staff_account_type', '') or '').strip(),
        job_title_snapshot=staff_job_title(user),
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
    if not is_shop_staff_account(user):
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
    # 配送员一进入上班状态，就主动询问待派单池；自动派单关闭时不会领取。
    if target == STAFF_WORK_ON_DUTY:
        from .dispatch_helpers import maybe_refill_dispatch_after_rider_available

        maybe_refill_dispatch_after_rider_available(user)
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
    if not is_shop_staff_account(user):
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
        legacy_roles = [
            key for key, label in STAFF_ROLE_LABELS.items()
            if label == role
        ]
        qs = qs.filter(
            Q(job_title_snapshot=role)
            | Q(job_title_snapshot='', role_snapshot__in=legacy_roles)
        )
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
            'role_label': staff_job_title(user),
            'account_type_label': staff_account_type_label(user),
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
    writer.writerow(['时间', '员工姓名', '账号类别', '职务', '动作', '来源', '操作人账号', '备注'])
    for log in logs:
        writer.writerow([
            timezone.localtime(log.changed_at).strftime('%Y-%m-%d %H:%M:%S'),
            log.display_name_snapshot,
            attendance_account_type_label(log),
            log.job_title_snapshot or staff_role_label(log.role_snapshot),
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
        role__in=ALL_STAFF_ROLES,
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
    'manager': ('toggle_manager', 'manager_username', '店长'),
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


def handle_staff_cancel_perm_post(request, seller_id: str, *, section='workbench'):
    """店主勾选/取消员工的「允许取消订单」权限"""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    if 'set_staff_cancel_perm' not in request.POST:
        return None
    username = (request.POST.get('staff_username') or '').strip()
    user = get_object_or_404(
        User,
        username=username,
        employer_seller_id=seller_id,
        role__in=ALL_STAFF_ROLES,
    )
    enabled = request.POST.get('perm_cancel_order') == '1'
    user.perm_cancel_order = enabled
    user.save(update_fields=['perm_cancel_order'])
    display = staff_display_username(user.username)
    if enabled:
        messages.success(request, f'已授权 {display} 可取消订单')
    else:
        messages.success(request, f'已取消 {display} 的取消订单权限')
    from .audit_helpers import write_audit_log

    write_audit_log(
        action_code='other',
        action_label='店长权限变更',
        seller_id=seller_id,
        actor=request.user,
        target_type='staff',
        target_id=user.username,
        summary=f'{"授权" if enabled else "收回"}取消订单权限：{display}',
        request=request,
    )
    return redirect('seller_panel_section', section=section)


def handle_create_staff_account_post(request, seller_id: str, *, section='workbench'):
    """目标态：统一创建管理职务或普通员工子账号。"""
    if 'create_staff_account' not in request.POST:
        return None
    from django.contrib import messages
    from django.shortcuts import redirect

    from .forms import CreateStaffAccountForm

    account_type = (request.POST.get('account_type') or '').strip()
    form = CreateStaffAccountForm(
        request.POST,
        seller_id=seller_id,
        account_type=account_type,
    )
    if form.is_valid():
        user = form.save()
        messages.success(
            request,
            f'已创建{staff_account_type_label(user)}：{staff_job_title(user)}'
            f'（{staff_display_username(user.username)}）',
        )
        from .audit_helpers import write_audit_log

        write_audit_log(
            action_code='other',
            action_label='创建员工子账号',
            seller_id=seller_id,
            actor=request.user,
            target_type='staff',
            target_id=user.username,
            summary=f'创建{staff_account_type_label(user)}：{staff_job_title(user)}',
            request=request,
        )
    else:
        first_error = next(
            (str(error) for errors in form.errors.values() for error in errors),
            '请检查填写内容',
        )
        messages.error(request, f'创建失败：{first_error}')
    return redirect('seller_panel_section', section=section)


def handle_edit_staff_account_post(request, seller_id: str, *, section='workbench'):
    """目标态：修改子账号类别、职务名称与权限。"""
    if 'edit_staff_account' not in request.POST:
        return None
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    from .forms import EditStaffAccountForm

    username = (request.POST.get('staff_username') or '').strip()
    user = get_object_or_404(
        User,
        username=username,
        employer_seller_id=seller_id,
        role__in=ALL_STAFF_ROLES,
    )
    old_title = staff_job_title(user)
    form = EditStaffAccountForm(
        request.POST,
        seller_id=seller_id,
        user=user,
    )
    if form.is_valid():
        form.save()
        messages.success(request, f'已保存 {staff_display_username(user.username)} 的职务与权限')
        from .audit_helpers import write_audit_log

        write_audit_log(
            action_code='other',
            action_label='员工职务权限变更',
            seller_id=seller_id,
            actor=request.user,
            target_type='staff',
            target_id=user.username,
            summary=f'{old_title} → {staff_job_title(user)}；权限已更新',
            request=request,
        )
    else:
        messages.error(request, '保存失败，请检查职务名称与权限')
    return redirect('seller_panel_section', section=section)


def handle_toggle_staff_account_post(request, seller_id: str, *, section='workbench'):
    """目标态：统一启用或停用任意店铺子账号。"""
    if 'toggle_staff_account' not in request.POST:
        return None
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect

    username = (request.POST.get('staff_username') or '').strip()
    user = get_object_or_404(
        User,
        username=username,
        employer_seller_id=seller_id,
        role__in=ALL_STAFF_ROLES,
    )
    user.is_active = not user.is_active
    update_fields = ['is_active']
    if not user.is_active:
        user.staff_work_status = STAFF_WORK_OFF_DUTY
        user.staff_work_status_updated_at = timezone.now()
        update_fields.extend(['staff_work_status', 'staff_work_status_updated_at'])
    user.save(update_fields=update_fields)
    if not user.is_active:
        create_attendance_log(
            user,
            STAFF_WORK_OFF_DUTY,
            source=ATTENDANCE_SOURCE_MANAGER,
            operator_username=request.user.username,
            note='老板停用账号',
        )
    state_word = '启用' if user.is_active else '停用'
    messages.success(
        request,
        f'已{state_word}{staff_job_title(user)} {staff_display_username(user.username)}',
    )
    return redirect('seller_panel_section', section=section)
