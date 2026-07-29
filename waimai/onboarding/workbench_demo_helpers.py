# 新版新手体验：员工工作台管理页演示数据（不写库）

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from django.http import QueryDict
from django.utils import timezone

from waimai.models import StaffAttendanceLog, User
from waimai.staff_account_helpers import (
    ATTENDANCE_LOG_PAGE_SIZES,
    ATTENDANCE_SOURCE_MANAGER,
    ATTENDANCE_SOURCE_SELF,
    AttendanceFilterForm,
    STAFF_WORK_BREAK,
    STAFF_WORK_OFF_DUTY,
    STAFF_WORK_ON_DUTY,
    build_staff_status_rows,
    datetime_local_input_value,
    paginate_attendance_logs,
)


def _demo_changed_at(hour: int, minute: int):
    """把今天的某时刻转成本机时区的发生时间"""
    today = timezone.localdate()
    naive = datetime.combine(today, time(hour, minute))
    tz = timezone.get_current_timezone()
    return timezone.make_aware(naive, tz)


def build_experience_workbench_demo_staff(seller_id: str) -> list[User]:
    """演示用子账号（内存对象，不写入数据库）"""
    now = timezone.now()
    manager = User(
        username=f'{seller_id}::演示经理',
        role='manager',
        employer_seller_id=seller_id,
        staff_account_type='management',
        staff_job_title='值班经理',
        staff_work_status=STAFF_WORK_OFF_DUTY,
        is_active=True,
    )
    manager.staff_work_status_updated_at = _demo_changed_at(18, 0)
    employee = User(
        username=f'{seller_id}::演示员工',
        role='waiter',
        employer_seller_id=seller_id,
        staff_account_type='employee',
        staff_job_title='演示员工',
        staff_work_status=STAFF_WORK_ON_DUTY,
        is_active=True,
    )
    employee.staff_work_status_updated_at = _demo_changed_at(17, 5)
    employee.date_joined = now - timedelta(days=30)
    manager.date_joined = now - timedelta(days=60)
    return [manager, employee]


def build_experience_workbench_demo_logs(seller_id: str) -> list[StaffAttendanceLog]:
    """演示员工今日 5 条考勤流水（内存对象）"""
    username = f'{seller_id}::演示员工'
    rows = [
        (8, 30, STAFF_WORK_ON_DUTY, ATTENDANCE_SOURCE_SELF, '', '到岗'),
        (12, 0, STAFF_WORK_BREAK, ATTENDANCE_SOURCE_SELF, '', '午饭'),
        (12, 30, STAFF_WORK_ON_DUTY, ATTENDANCE_SOURCE_SELF, '', '回岗'),
        (17, 0, STAFF_WORK_OFF_DUTY, ATTENDANCE_SOURCE_SELF, '', '下班'),
        (17, 5, STAFF_WORK_ON_DUTY, ATTENDANCE_SOURCE_MANAGER, '店主', '老板补改'),
    ]
    logs: list[StaffAttendanceLog] = []
    for hour, minute, action, source, operator, note in rows:
        logs.append(StaffAttendanceLog(
            seller_id=seller_id,
            username_snapshot=username,
            display_name_snapshot='演示员工',
            role_snapshot='waiter',
            account_type_snapshot='employee',
            job_title_snapshot='演示员工',
            action=action,
            source=source,
            operator_username=operator,
            note=note,
            changed_at=_demo_changed_at(hour, minute),
        ))
    logs.sort(key=lambda item: item.changed_at, reverse=True)
    return logs


def build_experience_workbench_attendance_context(
    request,
    seller_id: str,
    *,
    staff_users: list[User],
    demo_logs: list[StaffAttendanceLog],
) -> dict[str, Any]:
    """体验页考勤区：默认筛今天 + 演示流水"""
    today = timezone.localdate().isoformat()
    get_params = request.GET.copy() if request.GET else QueryDict(mutable=True)
    if not request.GET.get('date_from') and not request.GET.get('date_to'):
        get_params['date_from'] = today
        get_params['date_to'] = today
    attendance_filter_form = AttendanceFilterForm(get_params, seller_id=seller_id)
    filters = attendance_filter_form.cleaned_data if attendance_filter_form.is_valid() else {}
    per_page = 10
    raw_size = request.GET.get('log_per_page')
    try:
        size = int(raw_size or 10)
        if size in ATTENDANCE_LOG_PAGE_SIZES:
            per_page = size
    except (TypeError, ValueError):
        pass
    page_obj = paginate_attendance_logs(demo_logs, request.GET.get('log_page'), per_page)
    status_logs = sorted(demo_logs, key=lambda item: item.changed_at, reverse=True)
    return {
        'attendance_filter_form': attendance_filter_form,
        'attendance_filters': filters,
        'staff_status_rows': build_staff_status_rows(staff_users, status_logs),
        'attendance_logs_page': page_obj,
        'attendance_log_per_page': per_page,
        'attendance_log_page_sizes': ATTENDANCE_LOG_PAGE_SIZES,
        'attendance_datetime_default': datetime_local_input_value(),
    }
