# 卖家管理面板：各分区 POST 处理（公共逻辑）

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .delivery_helpers import get_delivery_settings
from .forms import ShopDeliverySettingsForm, ShopPaymentSettingsForm
from .payments import get_payment_settings
from .scroll_helpers import redirect_with_anchor


def _seller_panel_redirect(section, anchor=None, request=None):
    """操作后回到同一分区，并带上锚点；订单页保留当前搜索条件"""
    from .order_search_helpers import build_order_search_querystring

    url = reverse('seller_panel_section', kwargs={'section': section})
    if section == 'orders' and request is not None:
        qs = build_order_search_querystring(request.GET)
        if qs:
            url = f'{url}?{qs}'
    return redirect_with_anchor(url, anchor)


def handle_seller_post(request, seller_id, section):
    """
    处理卖家面板表单提交。
    成功或失败后 redirect 回同一分区，并定位到刚操作的条目附近。
  """
    from .plugins.fulfillment.ownership import fulfillment_plugin_enabled

    if 'save_delivery_settings' in request.POST and section == 'delivery':
        if not fulfillment_plugin_enabled(seller_id):
            messages.error(request, '履约配送插件未启用，无法保存配送费规则')
            return _seller_panel_redirect('plugins', request=request)
        settings = get_delivery_settings(seller_id)
        form = ShopDeliverySettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, '配送费规则已保存')
        else:
            messages.error(request, '配置无效，请检查输入')
        return _seller_panel_redirect('delivery', 'delivery-settings-form')

    if 'save_payment_settings' in request.POST and section == 'payment':
        settings = get_payment_settings(seller_id)
        form = ShopPaymentSettingsForm(request.POST, request.FILES, instance=settings)
        # 履约关闭时不允许改货到付款开关（字段不在表单里也应挡住 POST 篡改）
        if not fulfillment_plugin_enabled(seller_id) and 'enable_cod' in form.fields:
            del form.fields['enable_cod']
        if form.is_valid():
            form.save()
            from .payment_cert_helpers import apply_wechat_cert_uploads

            cert = form.cleaned_data.get('wechat_apiclient_cert_upload')
            key = form.cleaned_data.get('wechat_apiclient_key_upload')
            cert_errors: list[str] = []
            if cert or key:
                cert_errors = apply_wechat_cert_uploads(
                    get_payment_settings(seller_id),
                    cert_file=cert,
                    key_file=key,
                )
            from .audit_helpers import write_audit_log
            write_audit_log(
                action_code='payment_settings',
                summary='保存支付设置',
                seller_id=seller_id,
                actor=request.user,
                request=request,
            )
            if cert_errors:
                for msg in cert_errors:
                    messages.error(request, msg)
            elif cert or key:
                pay = get_payment_settings(seller_id)
                from .payment_cert_helpers import build_wechat_cert_display

                display = build_wechat_cert_display(pay)
                if display['files_ready']:
                    messages.success(
                        request,
                        '支付设置与退款证书已保存。'
                        f'证书：{display["cert_path"]}；私钥：{display["key_path"]}',
                    )
                else:
                    messages.success(request, '支付设置已保存；证书尚未完整，请查看下方路径与状态')
            else:
                messages.success(request, '支付设置已保存')
        else:
            err = next(iter(form.non_field_errors()), None) or '配置无效，请检查输入'
            messages.error(request, err)
        return _seller_panel_redirect('payment', 'payment-settings-form')

    if 'clear_wechat_certs' in request.POST and section == 'payment':
        from .payment_cert_helpers import clear_wechat_cert_files

        pay = get_payment_settings(seller_id)
        ok, msg = clear_wechat_cert_files(pay)
        if ok:
            from .audit_helpers import write_audit_log

            write_audit_log(
                action_code='payment_settings',
                action_label='删除微信退款证书',
                summary='删除本店上传的微信退款证书',
                seller_id=seller_id,
                actor=request.user,
                request=request,
            )
            messages.success(request, msg)
        else:
            messages.error(request, msg)
        return _seller_panel_redirect('payment', 'payment-wechat-refund-cert')

    if 'confirm_rider_remit' in request.POST and section == 'payment':
        messages.info(request, '配送员入金确认已移至「外卖现金管理」分区，请在那里操作。')
        return _seller_panel_redirect('cash_manage', 'cash-manage-card', request=request)

    if section == 'cash_manage':
        if 'save_boss_remittance_notify' in request.POST:
            from .forms import ShopBossRemittanceNotifyForm
            from .operating_helpers import get_operating_settings

            operating = get_operating_settings(seller_id)
            form = ShopBossRemittanceNotifyForm(request.POST, instance=operating)
            if form.is_valid():
                form.save()
                messages.success(request, '老板入金申请邮件已保存')
            else:
                messages.error(request, '老板入金申请邮件无效，请检查邮箱格式')
            return _seller_panel_redirect('cash_manage', 'boss-remittance-notify', request=request)

        if 'cash_manage_action' in request.POST:
            from .plugins.fulfillment.ownership import fulfillment_plugin_enabled
            from .cash_manage_handlers import handle_cash_management_post
            from .cash_manage_panel_helpers import (
                attach_seller_cash_manage_panel_ctx,
                detect_cash_manage_panel_action,
                run_cash_manage_idempotent,
            )

            if not fulfillment_plugin_enabled(seller_id):
                messages.error(request, '履约配送插件未启用，无法处理外卖现金管理')
                return _seller_panel_redirect('cash_manage', request=request)
            redirect_to = reverse('seller_panel_section', kwargs={'section': 'cash_manage'})
            cash_action = detect_cash_manage_panel_action(request)

            def _execute_seller_cash_manage():
                attach_seller_cash_manage_panel_ctx(
                    request, seller_id, redirect_to=redirect_to,
                )
                return handle_cash_management_post(
                    request, seller_id, operator=request.user, redirect_to=redirect_to,
                )

            if cash_action:
                return run_cash_manage_idempotent(
                    request,
                    seller_id,
                    request.user,
                    cash_action,
                    _execute_seller_cash_manage,
                )
            return _execute_seller_cash_manage()

    if 'save_boss_remittance_notify' in request.POST and section == 'payment':
        messages.info(request, '入金申请邮件设置已移至「外卖现金管理」分区。')
        return _seller_panel_redirect('cash_manage', 'boss-remittance-notify', request=request)

    if 'save_boss_order_notify' in request.POST and section == 'orders':
        from .forms import ShopBossOrderNotifyForm
        from .operating_helpers import get_operating_settings

        operating = get_operating_settings(seller_id)
        form = ShopBossOrderNotifyForm(request.POST, instance=operating)
        if form.is_valid():
            form.save()
            messages.success(request, '老板邮件通知已保存')
        else:
            messages.error(request, '老板邮件通知无效，请检查邮箱格式')
        return _seller_panel_redirect('orders', 'boss-order-notify', request=request)

    if section == 'orders' and request.method == 'POST':
        messages.error(request, '订单管理仅用于查询历史，请到店铺工作台处理现场操作')
        return _seller_panel_redirect('orders', request=request)

    return None
