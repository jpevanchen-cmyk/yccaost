# 卖家面板：营业状态（主体）POST 处理
# 只管全天营业时间 + 营业中/停止营业；通道接单开关在饮食插件

from django.contrib import messages
from django.template.loader import render_to_string
from django.urls import reverse

from .audit_helpers import write_audit_log
from .forms import ShopStatusSettingsForm
from .operating_helpers import get_operating_settings
from .scroll_helpers import redirect_with_anchor

OPERATING_STATUS_PANEL_ID = 'operating-status-panel'
OPERATING_PANEL_IDEMPOTENT_KEYS = ('toggle_open',)


def _seller_redirect(section, anchor=None):
    url = reverse('seller_panel_section', kwargs={'section': section})
    return redirect_with_anchor(url, anchor)


def _is_shop_open(settings) -> bool:
    return (not settings.closed_for_today) and (not settings.pause_new_orders)


def render_operating_status_panel_html(request, settings) -> str:
    """渲染营业开关局部片段。"""
    return render_to_string(
        'waimai/seller/_operating_status_panel.html',
        {'is_shop_open': _is_shop_open(settings)},
        request=request,
    )


def detect_operating_panel_action(request) -> str | None:
    for key in OPERATING_PANEL_IDEMPOTENT_KEYS:
        if key in request.POST:
            return key
    return None


def run_operating_panel_idempotent(request, seller_id: str, action: str, execute):
    """营业开关 Panel 写操作幂等（可重试）。"""
    from .idempotency_helpers import idempotency_scope, run_idempotent

    actor = (
        str(request.user.pk)
        if getattr(request.user, 'is_authenticated', False)
        else (request.session.session_key or 'anon')[:32]
    )
    scope = idempotency_scope('operating', action, seller_id, actor)
    return run_idempotent(request, scope, execute)


def _respond_operating_toggle(request, seller_id, settings, *, label: str):
    from .panel_refresh_helpers import is_panel_refresh, panel_refresh_ok

    message = f'已切换为：{label}'
    if is_panel_refresh(request):
        html = render_operating_status_panel_html(request, settings)
        return panel_refresh_ok(
            html=html,
            message=message,
            panel_id=OPERATING_STATUS_PANEL_ID,
        )
    messages.success(request, message)
    return _seller_redirect('operating', 'status-form')


def handle_operating_post(request, seller_id):
    """营业状态分区 POST"""
    if 'save_status' in request.POST:
        settings = get_operating_settings(seller_id)
        form = ShopStatusSettingsForm(request.POST, instance=settings)
        if not form.is_valid():
            err = next(iter(form.errors.values()), None)
            msg = err[0] if err else '营业时间无效，请检查输入'
            messages.error(request, msg)
            return _seller_redirect('operating', 'status-form')
        data = form.cleaned_data
        for field in form.Meta.fields:
            setattr(settings, field, data[field])
        settings.save(update_fields=list(form.Meta.fields))
        write_audit_log(
            action_code='operating',
            summary='保存营业时间',
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        messages.success(request, '营业时间已保存')
        return _seller_redirect('operating', 'status-form')

    if 'toggle_open' in request.POST:
        settings = get_operating_settings(seller_id)
        # 营业中 = 未打烊且未暂停；停止营业 = 打烊（并清掉暂停，避免状态打架）
        currently_open = _is_shop_open(settings)
        if currently_open:
            settings.closed_for_today = True
            settings.pause_new_orders = False
            label = '停止营业'
        else:
            settings.closed_for_today = False
            settings.pause_new_orders = False
            label = '营业中'
        settings.save(update_fields=['closed_for_today', 'pause_new_orders'])
        write_audit_log(
            action_code='operating',
            summary=f'切换营业状态：{label}',
            seller_id=seller_id,
            actor=request.user,
            request=request,
        )
        return _respond_operating_toggle(request, seller_id, settings, label=label)

    return None
