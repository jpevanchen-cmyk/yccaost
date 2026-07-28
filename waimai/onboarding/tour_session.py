# 新版新手体验：引导参数写入 session，防止 POST 刷新后丢步

from __future__ import annotations

from .constants import URL_FLAG, URL_MAJOR, URL_MICRO, URL_TRACK

_SESSION_PREFIX = 'yc_exp_'
SESSION_TOUR_ACTIVE = 'experience_tour_active'


def _session_key(url_key: str) -> str:
    return f'{_SESSION_PREFIX}{url_key}'


def load_tour_query(request) -> dict[str, str]:
    """合并 URL 与 session 中的 exp 引导参数（供模板 hidden 与 redirect）"""
    keys = (URL_FLAG, URL_TRACK, URL_MAJOR, URL_MICRO)
    out: dict[str, str] = {}
    for key in keys:
        val = (request.GET.get(key) or request.POST.get(key) or '').strip()
        if not val:
            val = (request.session.get(_session_key(key)) or '').strip()
        out[key] = val
    if not out[URL_FLAG] and request.path.startswith('/experience/'):
        if request.session.get(SESSION_TOUR_ACTIVE):
            out[URL_FLAG] = '1'
    return out


def touch_experience_tour_session(request) -> None:
    """每次进入/提交体验页时，把引导参数写入 session"""
    query = {
        URL_FLAG: (request.GET.get(URL_FLAG) or request.POST.get(URL_FLAG) or '').strip(),
        URL_TRACK: (request.GET.get(URL_TRACK) or request.POST.get(URL_TRACK) or '').strip(),
        URL_MAJOR: (request.GET.get(URL_MAJOR) or request.POST.get(URL_MAJOR) or '').strip(),
        URL_MICRO: (request.GET.get(URL_MICRO) or request.POST.get(URL_MICRO) or '').strip(),
    }
    touched = False
    for key, val in query.items():
        if val:
            request.session[_session_key(key)] = val
            touched = True
    if touched or request.path.startswith('/experience/'):
        request.session[SESSION_TOUR_ACTIVE] = True


def tour_query_for_redirect(request) -> list[str]:
    """拼 redirect 查询串；POST/GET 缺项时用 session 补全"""
    parts: list[str] = []
    q = load_tour_query(request)
    for key in (URL_FLAG, URL_TRACK, URL_MAJOR, URL_MICRO):
        val = q.get(key, '')
        if not val and key == URL_FLAG and request.session.get(SESSION_TOUR_ACTIVE):
            val = '1'
        if val:
            parts.append(f'{key}={val}')
    return parts
