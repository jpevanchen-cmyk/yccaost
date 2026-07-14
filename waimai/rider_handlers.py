# 卖家管理本店专属骑手子账号

from django.contrib import messages
from django.shortcuts import redirect

from .forms import CreateRiderForm
from .staff_account_helpers import handle_seller_staff_toggle_post


def handle_seller_rider_post(request, seller_id: str, *, section='workbench'):
    """卖家后台：创建骑手、停用/启用骑手"""
    response = handle_seller_staff_toggle_post(request, seller_id, 'rider', section=section)
    if response:
        return response

    if 'create_rider' in request.POST:
        form = CreateRiderForm(request.POST, seller_id=seller_id)
        if form.is_valid():
            form.save()
            messages.success(request, '骑手账号已创建')
        else:
            messages.error(request, '创建失败，请检查用户名和密码')
        return redirect('seller_panel_section', section=section)

    return None
