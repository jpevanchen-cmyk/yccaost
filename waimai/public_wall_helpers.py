# 公开留言壁：大厅展示、发帖、防刷（与联系我们私信分轨）

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Max

from .time_helpers import local_day_bounds_for_query, now_local_wall

# 对外列表每页条数（定案 50）
PUBLIC_WALL_PAGE_SIZE = 50
PUBLIC_WALL_MAX_BODY = 500
PUBLIC_WALL_MAX_NICKNAME = 80
PUBLIC_WALL_INTERVAL_MINUTES = 10
PUBLIC_WALL_DAILY_MAX = 15
DISPLAY_ANON_GUEST = '匿名游客'
DISPLAY_ANON_LOGIN = '匿名'


def public_wall_block_enabled() -> bool:
    """大厅这块是否在互动社区页显示。关掉则不允许发帖。"""
    from .home_page_helpers import BLOCK_PUBLIC_WALL
    from .home_page_tier_helpers import ensure_community_page

    page = ensure_community_page()
    return page.blocks.filter(block_type=BLOCK_PUBLIC_WALL, is_enabled=True).exists()


def resolve_public_wall_display_name(request, *, nickname: str, is_anonymous: bool) -> str:
    """
    对外显示名（定案）：
    游客无昵称 → 匿名游客；游客有昵称 → 该昵称；
    已登录勾选匿名 → 匿名；已登录填昵称 → 该昵称；否则账号名。
    """
    nick = (nickname or '').strip()[:PUBLIC_WALL_MAX_NICKNAME]
    user = getattr(request, 'user', None)
    logged_in = bool(user and getattr(user, 'is_authenticated', False))
    if logged_in:
        if is_anonymous:
            return DISPLAY_ANON_LOGIN
        if nick:
            return nick
        return ((getattr(user, 'username', '') or '').strip() or DISPLAY_ANON_LOGIN)[:PUBLIC_WALL_MAX_NICKNAME]
    if nick:
        return nick
    return DISPLAY_ANON_GUEST


def _client_ip(request) -> str | None:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    if forwarded:
        return forwarded[:45]
    raw = request.META.get('REMOTE_ADDR')
    return raw[:45] if raw else None


def check_public_wall_rate_limit(actor_key: str) -> tuple[bool, str]:
    """同一人 10 分钟 1 条、每天 15 条。计数看身份键，不看屏幕上的名字。"""
    from .public_wall_models import PublicWallPost

    key = (actor_key or '').strip()
    if not key:
        return True, ''

    now = now_local_wall()
    ten_min_ago = now - timedelta(minutes=PUBLIC_WALL_INTERVAL_MINUTES)
    day_start, _end = local_day_bounds_for_query()

    if PublicWallPost.objects.filter(actor_key=key, created_at__gte=ten_min_ago).exists():
        return False, f'您 {PUBLIC_WALL_INTERVAL_MINUTES} 分钟内已发过一条，请稍后再试'
    daily_count = PublicWallPost.objects.filter(actor_key=key, created_at__gte=day_start).count()
    if daily_count >= PUBLIC_WALL_DAILY_MAX:
        return False, f'您今天已发满 {PUBLIC_WALL_DAILY_MAX} 条，请明天再试'
    return True, ''


def _next_floor_no() -> int:
    from .public_wall_models import PublicWallPost

    agg = PublicWallPost.objects.aggregate(m=Max('floor_no'))
    return (agg['m'] or 0) + 1


def create_public_wall_post(request, *, body: str, nickname: str, is_anonymous: bool):
    """
    写一楼。成功返回 (True, 该条)；失败返回 (False, 人话原因)。
    须在幂等守卫内调用。
    """
    from .guestbook_rate_helpers import resolve_guestbook_actor
    from .public_wall_models import PublicWallPost

    if not public_wall_block_enabled():
        return False, '公开留言壁当前未开放'

    actor_key, new_cookie = resolve_guestbook_actor(request)
    if new_cookie:
        request._yc_new_guestbook_actor = new_cookie

    ok_limit, limit_msg = check_public_wall_rate_limit(actor_key)
    if not ok_limit:
        return False, limit_msg

    text = (body or '').strip()
    if not text:
        return False, '请填写留言内容'
    if len(text) > PUBLIC_WALL_MAX_BODY:
        return False, f'留言请控制在 {PUBLIC_WALL_MAX_BODY} 字以内'

    nick = (nickname or '').strip()[:PUBLIC_WALL_MAX_NICKNAME]
    user = getattr(request, 'user', None)
    logged_in = bool(user and getattr(user, 'is_authenticated', False))
    display_name = resolve_public_wall_display_name(
        request, nickname=nick, is_anonymous=bool(is_anonymous),
    )
    user_snap = (getattr(user, 'username', '') or '').strip()[:64] if logged_in else ''

    last_error = '发帖失败，请稍后再试'
    for _attempt in range(3):
        try:
            with transaction.atomic():
                PublicWallPost.objects.select_for_update().order_by('pk').first()
                post = PublicWallPost.objects.create(
                    floor_no=_next_floor_no(),
                    body=text,
                    display_name=display_name,
                    nickname_input=nick,
                    is_anonymous=bool(is_anonymous) if logged_in else False,
                    actor_key=actor_key,
                    author_user_id=user_snap,
                    author_ip=_client_ip(request),
                    created_at=now_local_wall(),
                )
            return True, post
        except IntegrityError:
            last_error = '发帖冲突，请再试一次'
    return False, last_error


def run_public_wall_post_idempotent(request, execute):
    """同一人同一幂等键只写一楼；与私信留言的作用域分开。"""
    from .guestbook_rate_helpers import resolve_guestbook_actor
    from .idempotency_helpers import idempotency_scope, run_idempotent

    actor_key, _ = resolve_guestbook_actor(request)
    actor = (actor_key or 'anon')[:32]
    scope = idempotency_scope('public_wall_post', actor)
    return run_idempotent(request, scope, execute)


def _public_wall_pager_urls(request, page_obj) -> dict:
    from .home_page_tier_helpers import community_page_public_path
    from .workbench_pagination_helpers import append_query_params

    preserved = {}
    if request is not None:
        preserved = {key: request.GET.get(key) for key in request.GET if key != 'wall'}
    base = community_page_public_path()

    def _link(page: int) -> str:
        params = dict(preserved)
        if page > 1:
            params['wall'] = str(page)
        else:
            params.pop('wall', None)
        return append_query_params(base, params) + '#block-public_wall'

    return {
        'has_other_pages': page_obj.has_other_pages(),
        'count': page_obj.paginator.count,
        'number': page_obj.number,
        'num_pages': page_obj.paginator.num_pages,
        'prev_url': _link(page_obj.previous_page_number()) if page_obj.has_previous() else '',
        'next_url': _link(page_obj.next_page_number()) if page_obj.has_next() else '',
    }


def build_public_wall_home_context(request=None) -> dict:
    """大厅积木用：最新楼在上；超过 50 条翻页。藏/删楼仍占原楼号。"""
    from .public_wall_models import PublicWallPost
    from .workbench_pagination_helpers import paginate_sequence

    page_raw = '1'
    if request is not None:
        page_raw = request.GET.get('wall') or '1'
    rows = list(
        PublicWallPost.objects.all()
        .prefetch_related('replies')
        .order_by('-floor_no')
    )
    page_obj = paginate_sequence(rows, page_raw, PUBLIC_WALL_PAGE_SIZE)
    return {
        'public_wall_posts': list(page_obj.object_list),
        'public_wall_pager': _public_wall_pager_urls(request, page_obj),
        'public_wall_max_body': PUBLIC_WALL_MAX_BODY,
        'public_wall_max_nickname': PUBLIC_WALL_MAX_NICKNAME,
    }


def list_public_wall_posts_for_home(request=None):
    """兼容旧调用：只返回当前页的楼。"""
    return build_public_wall_home_context(request)['public_wall_posts']


def posted_wall_action(request) -> str:
    """点了哪颗按钮。关按钮后可能只剩隐藏栏；多值时取最后一个非空。"""
    values = []
    if request is not None:
        values = list(request.POST.getlist('action'))
        if not values:
            values = [request.POST.get('action') or '']
    for raw in reversed(values):
        text = (raw or '').strip()
        if text:
            return text
    return ''


ACTION_HIDE = 'hide'
ACTION_DELETE = 'delete'
ACTION_RESTORE = 'restore'
ACTION_REPLY = 'reply'


def normalize_wall_signer(raw: str) -> str:
    """手填署名；空则管理员。"""
    from .public_wall_models import PublicWallReply

    text = (raw or '').strip()[:PublicWallReply.MAX_SIGNER]
    return text or PublicWallReply.DEFAULT_SIGNER


def resolve_wall_reply_kind(action: str, post) -> str:
    """藏/删 → 说明；正常回复 → 回复；已藏/已删楼再贴一句 → 说明。"""
    from .public_wall_models import PublicWallPost, PublicWallReply

    action = (action or '').strip()
    if action in (ACTION_HIDE, ACTION_DELETE):
        return PublicWallReply.KIND_NOTE
    if action == ACTION_RESTORE:
        return PublicWallReply.KIND_REPLY
    status = getattr(post, 'status', '') or ''
    if status in (PublicWallPost.STATUS_HIDDEN, PublicWallPost.STATUS_DELETED):
        return PublicWallReply.KIND_NOTE
    return PublicWallReply.KIND_REPLY


def add_public_wall_reply(
    post, body: str, *, signer_name: str = '', suffix_kind: str = '',
) -> tuple[bool, str]:
    """管理者楼下回：不占新楼号，不计入访客发帖限额。"""
    from .public_wall_models import PublicWallReply

    text = (body or '').strip()
    kind = (suffix_kind or '').strip() or PublicWallReply.KIND_NOTE
    label = '回复' if kind == PublicWallReply.KIND_REPLY else '说明'
    if not text:
        return False, f'请填写{label}'
    if len(text) > PUBLIC_WALL_MAX_BODY:
        return False, f'{label}请控制在 {PUBLIC_WALL_MAX_BODY} 字以内'
    PublicWallReply.objects.create(
        post=post,
        body=text,
        signer_name=normalize_wall_signer(signer_name),
        suffix_kind=kind,
        created_at=now_local_wall(),
    )
    return True, f'{label}已贴上'


def moderate_public_wall_post(
    post, *, action: str, note: str = '', signer_name: str = '',
) -> tuple[bool, str]:
    """隐藏 / 删除 / 恢复：只改状态，库内留条。可选同时写下说明或回复。"""
    from .public_wall_models import PublicWallPost, PublicWallReply

    action = (action or '').strip()
    note = (note or '').strip()
    kind = resolve_wall_reply_kind(action, post)
    if action == ACTION_REPLY:
        return add_public_wall_reply(
            post, note, signer_name=signer_name, suffix_kind=kind,
        )

    if action == ACTION_HIDE:
        post.status = PublicWallPost.STATUS_HIDDEN
        post.save(update_fields=['status'])
        msg = f'{post.floor_no} 楼已隐藏'
    elif action == ACTION_DELETE:
        post.status = PublicWallPost.STATUS_DELETED
        post.save(update_fields=['status'])
        msg = f'{post.floor_no} 楼已删除（库内仍保留，大厅上看不到原文）'
    elif action == ACTION_RESTORE:
        post.status = PublicWallPost.STATUS_VISIBLE
        post.save(update_fields=['status'])
        msg = f'{post.floor_no} 楼已恢复显示'
    else:
        return False, '请选择要做的操作'

    if note:
        ok, note_msg = add_public_wall_reply(
            post, note, signer_name=signer_name, suffix_kind=kind,
        )
        if not ok:
            return True, f'{msg}；{note_msg}'
        label = '回复' if kind == PublicWallReply.KIND_REPLY else '说明'
        return True, f'{msg}，并已写下{label}'
    return True, msg


def run_public_wall_mod_idempotent(request, execute):
    """管理者藏/删/说明：同一编号只做一次。"""
    from .idempotency_helpers import idempotency_scope, run_idempotent

    user = getattr(request, 'user', None)
    actor = ((getattr(user, 'username', '') or '') or 'manager')[:32]
    scope = idempotency_scope('public_wall_mod', actor)
    return run_idempotent(request, scope, execute)


def _admin_pager_urls(request, page_obj) -> dict:
    from django.urls import reverse

    from .workbench_pagination_helpers import append_query_params

    base = reverse('server_settings_public_wall')

    def _link(page: int) -> str:
        params = {}
        if page > 1:
            params['p'] = str(page)
        return append_query_params(base, params)

    return {
        'has_other_pages': page_obj.has_other_pages(),
        'count': page_obj.paginator.count,
        'number': page_obj.number,
        'num_pages': page_obj.paginator.num_pages,
        'prev_url': _link(page_obj.previous_page_number()) if page_obj.has_previous() else '',
        'next_url': _link(page_obj.next_page_number()) if page_obj.has_next() else '',
    }


def build_public_wall_admin_context(request) -> dict:
    """管理者后台：能看见原文；最新楼在上。"""
    from .public_wall_models import PublicWallPost, PublicWallReply
    from .workbench_pagination_helpers import paginate_sequence

    page_raw = '1'
    if request is not None:
        page_raw = request.GET.get('p') or '1'
    rows = list(
        PublicWallPost.objects.all()
        .prefetch_related('replies')
        .order_by('-floor_no')
    )
    page_obj = paginate_sequence(rows, page_raw, PUBLIC_WALL_PAGE_SIZE)
    return {
        'public_wall_posts': list(page_obj.object_list),
        'public_wall_pager': _admin_pager_urls(request, page_obj),
        'public_wall_max_body': PUBLIC_WALL_MAX_BODY,
        'public_wall_admin_page': page_obj.number,
        'public_wall_default_signer': PublicWallReply.DEFAULT_SIGNER,
        'public_wall_max_signer': PublicWallReply.MAX_SIGNER,
    }
