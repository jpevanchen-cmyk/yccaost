# 卖家面板：营业状态（主体）POST 处理
# 只管全天营业时间 + 营业中/停止营业；通道接单开关在饮食插件

from django.contrib import messages
from django.urls import reverse

from .audit_helpers import write_audit_log
from .forms import ShopStatusSettingsForm
from .operating_helpers import get_operating_settings
from .scroll_helpers import redirect_with_anchor


def _seller_redirect(section, anchor=None):
    url = reverse('seller_panel_section', kwargs={'section': section})
    return redirect_with_anchor(url, anchor)


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
        currently_open = (not settings.closed_for_today) and (not settings.pause_new_orders)
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
        messages.success(request, f'已切换为：{label}')
        return _seller_redirect('operating', 'status-form')

    return None
