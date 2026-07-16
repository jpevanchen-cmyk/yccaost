# 店长子账号：创建 / 停用

from django.contrib import messages
from django.shortcuts import redirect


def get_shop_managers(seller_id: str, *, active_only: bool = False):
    from .models import User

    qs = User.objects.filter(role='manager', employer_seller_id=seller_id)
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by('date_joined', 'username')


def handle_seller_manager_post(request, seller_id: str, *, section='workbench'):
    """卖家管理店长子账号"""
    if 'create_manager' in request.POST:
        from .forms import CreateManagerForm

        form = CreateManagerForm(request.POST, seller_id=seller_id)
        if form.is_valid():
            form.save()
            messages.success(request, '店长账号已创建')
        else:
            messages.error(request, '创建失败，请检查用户名和密码')
        return redirect('seller_panel_section', section=section)

    if 'toggle_manager' in request.POST:
        from .staff_account_helpers import handle_seller_staff_toggle_post

        return handle_seller_staff_toggle_post(request, seller_id, 'manager', section=section)

    return None
