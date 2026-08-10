# V1 首次安装向导 · 视图（7 步）

from django.contrib import messages
from django.contrib.auth import login
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .single_login_helpers import claim_single_login
from .v1_setup_forms import (
    V1SetupBackupForm,
    V1SetupNetworkForm,
    V1SetupPaymentForm,
    V1SetupPluginsForm,
    V1SetupShopForm,
)
from .v1_setup_helpers import (
    V1_SETUP_STEP_SLUGS,
    V1_SETUP_STEPS,
    clear_setup_draft,
    finalize_v1_setup,
    get_setup_draft,
    save_setup_draft,
    setup_step_index,
    setup_step_url,
    v1_setup_allowed_manual,
    v1_setup_completed,
)


def _guard_setup_access(request, step_slug=None):
    """未完成且允许时方可进入；否则带提示跳转登录。"""
    if v1_setup_completed():
        if step_slug == 'done' and getattr(request.user, 'is_authenticated', False):
            return None
        messages.info(request, '首次向导已完成，请登录。')
        return redirect('login')
    ok, msg = v1_setup_allowed_manual()
    if not ok:
        messages.info(request, msg)
        return redirect('login')
    return None


def _render_step(request, step_slug, *, form=None, extra=None):
    idx = setup_step_index(step_slug)
    ctx = {
        'setup_steps': V1_SETUP_STEPS,
        'current_step': step_slug,
        'current_index': idx,
        'step_total': len(V1_SETUP_STEPS),
        'draft': get_setup_draft(request),
    }
    if form is not None:
        ctx['form'] = form
    if extra:
        ctx.update(extra)
    return render(request, f'waimai/v1_setup/{step_slug}.html', ctx)


@never_cache
def v1_setup_entry(request):
    blocked = _guard_setup_access(request)
    if blocked:
        return blocked
    return redirect('v1_setup_step', step_slug='welcome')


@never_cache
@require_http_methods(['GET', 'POST'])
def v1_setup_step(request, step_slug):
    blocked = _guard_setup_access(request, step_slug)
    if blocked:
        return blocked
    if step_slug not in V1_SETUP_STEP_SLUGS:
        return redirect('v1_setup_step', step_slug='welcome')

    draft = get_setup_draft(request)

    if step_slug == 'welcome':
        if request.method == 'POST':
            return redirect('v1_setup_step', step_slug='shop')
        return _render_step(request, 'welcome')

    if step_slug == 'shop':
        if request.method == 'POST':
            form = V1SetupShopForm(request.POST)
            if form.is_valid():
                save_setup_draft(
                    request,
                    shop_name=form.cleaned_data['shop_name'],
                    username=form.cleaned_data['username'],
                    password=form.cleaned_data['password1'],
                    address=form.cleaned_data.get('address') or '',
                )
                return redirect('v1_setup_step', step_slug='network')
        else:
            form = V1SetupShopForm(
                initial={
                    'shop_name': draft.get('shop_name', ''),
                    'username': draft.get('username', ''),
                    'address': draft.get('address', ''),
                },
            )
        return _render_step(request, 'shop', form=form)

    if step_slug == 'network':
        if not draft.get('username'):
            return redirect('v1_setup_step', step_slug='shop')
        if request.method == 'POST':
            form = V1SetupNetworkForm(request.POST)
            if form.is_valid():
                save_setup_draft(
                    request,
                    listen_port=form.cleaned_data['listen_port'],
                    lan_base_url=form.cleaned_data['lan_base_url'],
                )
                return redirect('v1_setup_step', step_slug='plugins')
        else:
            form = V1SetupNetworkForm(
                initial={
                    'listen_port': draft.get('listen_port') or 8000,
                    'lan_base_url': draft.get('lan_base_url') or '',
                },
            )
        return _render_step(request, 'network', form=form)

    if step_slug == 'plugins':
        if 'listen_port' not in draft:
            return redirect('v1_setup_step', step_slug='network')
        if request.method == 'POST':
            form = V1SetupPluginsForm(request.POST)
            if form.is_valid():
                save_setup_draft(
                    request,
                    fulfillment_enabled=form.cleaned_data.get('enable_fulfillment', False),
                )
                return redirect('v1_setup_step', step_slug='payment')
        else:
            form = V1SetupPluginsForm(
                initial={
                    'enable_fulfillment': draft.get('fulfillment_enabled', False),
                },
            )
        return _render_step(request, 'plugins', form=form)

    if step_slug == 'payment':
        if 'fulfillment_enabled' not in draft:
            return redirect('v1_setup_step', step_slug='plugins')
        if request.method == 'POST':
            form = V1SetupPaymentForm(request.POST)
            if form.is_valid():
                save_setup_draft(
                    request,
                    enable_cash=form.cleaned_data.get('enable_cash', True),
                    enable_wechat=form.cleaned_data.get('enable_wechat', False),
                    enable_simulate=form.cleaned_data.get('enable_simulate', True),
                    wechat_mch_id=form.cleaned_data.get('wechat_mch_id') or '',
                    wechat_app_id=form.cleaned_data.get('wechat_app_id') or '',
                    wechat_api_key=form.cleaned_data.get('wechat_api_key') or '',
                    public_site_url=form.cleaned_data.get('public_site_url') or '',
                    payment_configured=True,
                )
                return redirect('v1_setup_step', step_slug='backup')
        else:
            form = V1SetupPaymentForm(
                initial={
                    'enable_cash': draft.get('enable_cash', True),
                    'enable_wechat': draft.get('enable_wechat', False),
                    'enable_simulate': draft.get('enable_simulate', True),
                    'wechat_mch_id': draft.get('wechat_mch_id', ''),
                    'wechat_app_id': draft.get('wechat_app_id', ''),
                    'wechat_api_key': draft.get('wechat_api_key', ''),
                    'public_site_url': draft.get('public_site_url', ''),
                },
            )
        return _render_step(request, 'payment', form=form)

    if step_slug == 'backup':
        if not draft.get('payment_configured'):
            return redirect('v1_setup_step', step_slug='payment')
        if request.method == 'POST':
            form = V1SetupBackupForm(request.POST)
            if form.is_valid():
                save_setup_draft(
                    request,
                    backup_dir=form.cleaned_data['backup_dir'],
                )
                return redirect('v1_setup_step', step_slug='done')
        else:
            form = V1SetupBackupForm(
                initial={'backup_dir': draft.get('backup_dir') or ''},
            )
        return _render_step(request, 'backup', form=form)

    if step_slug == 'done':
        if not draft.get('backup_dir'):
            return redirect('v1_setup_step', step_slug='backup')
        if request.method == 'POST':
            try:
                user, summary = finalize_v1_setup(draft)
            except ValueError as exc:
                messages.error(request, str(exc))
                return redirect('v1_setup_step', step_slug='shop')
            except Exception:
                messages.error(request, '保存失败，请从第 2 步检查填写后重试。')
                return redirect('v1_setup_step', step_slug='shop')
            clear_setup_draft(request)
            login(request, user)
            claim_single_login(request, user)
            return _render_step(request, 'done', extra={'summary': summary})
        summary = request.session.get('v1_setup_summary')
        if summary:
            return _render_step(request, 'done', extra={'summary': summary})
        return _render_step(request, 'done')

    return redirect('v1_setup_entry')


@never_cache
@require_POST
def v1_setup_pick_backup_dir(request):
    """向导第 6 步：本机弹出选文件夹，返回绝对路径（须带 CSRF）。"""
    blocked = _guard_setup_access(request)
    if blocked:
        return JsonResponse({'ok': False, 'error': '向导不可用或已完成。'}, status=403)
    from .v1_setup_folder_helpers import pick_backup_directory

    draft = get_setup_draft(request)
    initial = (request.POST.get('initial_dir') or draft.get('backup_dir') or '').strip()
    chosen = pick_backup_directory(initial_dir=initial)
    if not chosen:
        return JsonResponse({'ok': False, 'cancelled': True, 'error': '未选择文件夹。'})
    return JsonResponse({'ok': True, 'path': chosen})
