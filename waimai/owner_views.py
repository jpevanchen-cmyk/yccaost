# 服务器设置（整机日常设置；原「拥有者控制台」）

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse

from .owner_helpers import user_is_server_manager

# 留言板（正式功能）
from .guestbook_views import (  # noqa: E402
    guestbook_open_search,
    guestbook_post,
    guestbook_thread_public,
    server_settings_guestbook,
    server_settings_guestbook_thread,
)


def _manager_required(view_fn):
    @login_required
    @wraps(view_fn)
    def _wrapped(request, *args, **kwargs):
        if user_is_server_manager(request.user):
            return view_fn(request, *args, **kwargs)
        messages.error(
            request,
            '需要服务器管理者权限。请由超级管理员在总后台指定，或使用命令 mark_server_owner。',
        )
        return redirect('home')
    return _wrapped


@_manager_required
def server_settings_home(request):
    """服务器设置 · 总览"""
    from .owner_helpers import get_compliance_settings, get_site_settings

    site = get_site_settings()
    compliance = get_compliance_settings()
    return render(request, 'waimai/owner/index.html', {
        'site_settings': site,
        'compliance': compliance,
        'section': 'index',
    })


# 兼容旧视图名
owner_console = server_settings_home


@_manager_required
def server_settings_branding(request):
    """站点品牌"""
    from .owner_helpers import get_site_settings

    site = get_site_settings()
    if request.method == 'POST':
        site.site_name = (request.POST.get('site_name') or '')[:80]
        site.brand_image_url = (request.POST.get('brand_image_url') or '')[:500]
        site.nav_brand_label = (request.POST.get('nav_brand_label') or '')[:40]
        site.show_powered_by = request.POST.get('show_powered_by') == '1'
        site.save()
        messages.success(request, '站点品牌设置已保存')
        return redirect('server_settings_branding')
    return render(request, 'waimai/owner/branding.html', {
        'site_settings': site,
        'section': 'branding',
    })


owner_branding = server_settings_branding


@_manager_required
def server_settings_compliance(request):
    """备案信息"""
    from .models import SiteComplianceSettings

    compliance, _ = SiteComplianceSettings.objects.get_or_create(singleton_id=1)
    if request.method == 'POST':
        compliance.icp_record_number = request.POST.get('icp_record_number') or ''
        compliance.police_record_number = request.POST.get('police_record_number') or ''
        if request.FILES.get('police_record_icon'):
            compliance.police_record_icon = request.FILES['police_record_icon']
        if request.POST.get('clear_police_icon') == '1':
            compliance.police_record_icon.delete(save=False)
            compliance.police_record_icon = None
        try:
            compliance.save()
            messages.success(request, '备案信息已保存')
            return redirect('server_settings_compliance')
        except ValidationError as exc:
            for _field, errs in exc.message_dict.items():
                for err in errs:
                    messages.error(request, err)
    return render(request, 'waimai/owner/compliance.html', {
        'compliance': compliance,
        'section': 'compliance',
    })


owner_compliance = server_settings_compliance


@_manager_required
def server_settings_home_page(request):
    """编辑服务器主页积木"""
    from .home_page_handlers import handle_server_home_page_post
    from .home_page_panel_helpers import _server_home_common_context

    if request.method == 'POST':
        response = handle_server_home_page_post(request)
        if response is not None:
            return response

    ctx = _server_home_common_context(request)
    return render(request, 'waimai/owner/server_home.html', ctx)


owner_server_home = server_settings_home_page


@_manager_required
def server_settings_email(request):
    """服务器统一发信邮箱（网页配置，优先于 .env；主失败自动试备用）"""
    from .email_helpers import ROUTE_BACKUP, ROUTE_PRIMARY, email_rate_limit_status, is_email_ready, send_yecao_mail
    from .email_rate_limit_helpers import KIND_TEST
    from .owner_helpers import get_server_email_settings

    email_settings = get_server_email_settings()
    if request.method == 'POST':
        if 'save_email_settings' in request.POST:
            email_settings.smtp_host = (request.POST.get('smtp_host') or '').strip()[:200]
            try:
                email_settings.smtp_port = max(1, min(65535, int(request.POST.get('smtp_port') or 465)))
            except (TypeError, ValueError):
                email_settings.smtp_port = 465
            email_settings.smtp_user = (request.POST.get('smtp_user') or '').strip()[:200]
            new_password = request.POST.get('smtp_password') or ''
            if new_password.strip():
                email_settings.smtp_password = new_password
            email_settings.from_email = (request.POST.get('from_email') or '').strip()[:254]
            email_settings.use_tls = request.POST.get('use_tls') == '1'
            email_settings.use_ssl = request.POST.get('use_ssl') == '1'

            email_settings.backup_smtp_host = (request.POST.get('backup_smtp_host') or '').strip()[:200]
            try:
                email_settings.backup_smtp_port = max(
                    1, min(65535, int(request.POST.get('backup_smtp_port') or 465)),
                )
            except (TypeError, ValueError):
                email_settings.backup_smtp_port = 465
            email_settings.backup_smtp_user = (request.POST.get('backup_smtp_user') or '').strip()[:200]
            backup_password = request.POST.get('backup_smtp_password') or ''
            if backup_password.strip():
                email_settings.backup_smtp_password = backup_password
            email_settings.backup_from_email = (request.POST.get('backup_from_email') or '').strip()[:254]
            email_settings.backup_use_tls = request.POST.get('backup_use_tls') == '1'
            email_settings.backup_use_ssl = request.POST.get('backup_use_ssl') == '1'

            email_settings.save()
            messages.success(request, '发信邮箱设置已保存（含备用邮箱）')
            return redirect('server_settings_email')

        test_route = (request.POST.get('send_test_email') or '').strip().lower()
        if test_route in (ROUTE_PRIMARY, ROUTE_BACKUP):
            test_to = (request.POST.get('test_recipient') or '').strip()
            label = '主邮箱' if test_route == ROUTE_PRIMARY else '备用邮箱'
            if not test_to:
                messages.error(request, '请填写测试收件邮箱')
            elif test_route == ROUTE_BACKUP and not email_settings.is_backup_configured():
                messages.error(request, '备用邮箱未配齐，请先保存备用 SMTP 信息')
            elif test_route == ROUTE_PRIMARY and not email_settings.is_configured():
                messages.error(request, '主邮箱未配齐，请先保存主 SMTP 信息')
            elif send_yecao_mail(
                subject=f'野草系统 · {label}发信测试',
                message=f'这是一封{label}测试邮件。若您收到，说明该通道可用。',
                recipient_list=[test_to],
                kind=KIND_TEST,
                dedupe_key=f'test:{test_route}',
                force_route=test_route,
            ):
                messages.success(request, f'{label}测试邮件已发送到 {test_to}')
            else:
                messages.error(request, f'{label}测试邮件发送失败，请检查 SMTP 或是否触发防刷上限')
            return redirect('server_settings_email')

    return render(request, 'waimai/owner/email.html', {
        'email_settings': email_settings,
        'email_ready': is_email_ready(),
        'backup_ready': email_settings.is_backup_configured(),
        'rate_stats': email_rate_limit_status(),
        'section': 'email',
    })


@_manager_required
def server_settings_operation_lock(request):
    """操作锁设置已迁至店铺管理；旧链接兼容跳转。"""
    return redirect('seller_panel_section', section='operation_lock')


@_manager_required
def server_settings_tech_logs(request):
    """系统排错日志：仅供服务器维护人员，不在卖家后台展示。"""
    from .audit_helpers import (
        AUDIT_VIEW_TECH_ERROR,
        AUDIT_VIEW_TECH_RUNTIME,
        build_tech_log_querystring,
        parse_tech_log_view_params,
        read_tech_log_filtered,
    )

    params = parse_tech_log_view_params(request.GET)
    view = params['view']
    keyword = params['q']
    ctx = {
        'section': 'tech_logs',
        'tech_view': view,
        'tech_q': keyword,
        'tech_query_runtime': build_tech_log_querystring(
            view=AUDIT_VIEW_TECH_RUNTIME, q=keyword,
        ),
        'tech_query_error': build_tech_log_querystring(
            view=AUDIT_VIEW_TECH_ERROR, q=keyword,
        ),
        'runtime_log_lines': [],
        'error_payment_log_lines': [],
    }
    if view == AUDIT_VIEW_TECH_RUNTIME:
        ctx['runtime_log_lines'] = read_tech_log_filtered(
            'runtime.log', keyword, 300,
        )
    else:
        ctx['error_payment_log_lines'] = read_tech_log_filtered(
            'error_payment.log', keyword, 300,
        )
    return render(request, 'waimai/owner/tech_logs.html', ctx)

