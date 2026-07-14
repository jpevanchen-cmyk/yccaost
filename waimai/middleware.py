# 工作台会话装载 + 子账户不得占用野草生态登录身份

from django.contrib.auth import logout as ecosystem_logout
from django.shortcuts import redirect
from django.urls import reverse

from .shop_work_auth import (
    get_shop_work_user,
    is_shop_staff_role,
    path_is_shop_work,
    restore_shop_work_session,
    snapshot_shop_work_session,
)
from .shop_work_helpers import get_shop_code_for_user


class ShopWorkAuthMiddleware:
    """
    1. 把工作台独立登录用户挂到 request.shop_work_user
    2. 若野草生态会话里误留了子账户，立即清掉，避免串到名录等生态页
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .session_guard import force_logout_all_channels, idle_expired, touch_user_activity

        request.shop_work_user = get_shop_work_user(request)

        # 子账户绝不能作为野草生态已登录用户存在
        if is_shop_staff_role(request.user):
            shop_code = get_shop_code_for_user(request.user)
            # django logout 会清空整份 session，先备份工作台字段
            snap = snapshot_shop_work_session(request)
            ecosystem_logout(request)
            restore_shop_work_session(request, snap)
            request.shop_work_user = get_shop_work_user(request)
            path = request.path or ''
            if not path_is_shop_work(path):
                if request.shop_work_user and shop_code:
                    return redirect(reverse('shop_work', kwargs={'shop_code': shop_code}))
                if shop_code:
                    return redirect(reverse('shop_work', kwargs={'shop_code': shop_code}))
                return redirect('directory')

        # 服务端兜底：超过 15 分钟无操作则退出（心跳接口自行处理，避免循环）
        path = request.path or ''
        if not path.startswith('/accounts/session/'):
            has_session = (
                getattr(request.user, 'is_authenticated', False)
                or request.shop_work_user is not None
            )
            if has_session and idle_expired(request):
                force_logout_all_channels(request)
                request.shop_work_user = None
                if path_is_shop_work(path):
                    code = shop_code_from_request_safe(request)
                    if code:
                        return redirect(reverse('shop_work', kwargs={'shop_code': code}))
                return redirect('login')
            if has_session and request.method in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                # 普通页面访问算有操作；纯静态资源不经过这里
                touch_user_activity(request)

        return self.get_response(request)


def shop_code_from_request_safe(request) -> str:
    from .staff_account_helpers import shop_code_from_request
    return shop_code_from_request(request)


class ExperienceOnlineMiddleware:
    """体验机：同时在线名额；已在线可刷新，新占用超限则提示繁忙"""

    SKIP_PREFIXES = (
        '/static/',
        '/accounts/session/',
        '/pay/wechat/notify/',
        '/media/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect

        from .experience_helpers import (
            can_accept_online,
            experience_site_enabled,
            request_presence_user,
            touch_online_user,
        )

        path = request.path or ''
        if experience_site_enabled() and not any(path.startswith(p) for p in self.SKIP_PREFIXES):
            user = request_presence_user(request)
            if user is not None:
                ok, msg = can_accept_online(user)
                if not ok:
                    from .session_guard import force_logout_all_channels

                    force_logout_all_channels(request)
                    request.shop_work_user = None
                    messages.error(request, msg)
                    return redirect('login')
                touch_online_user(user)

        return self.get_response(request)
