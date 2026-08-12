# 服务器主页「文件下载」积木：上传、记账、代发文件

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import FileResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone

from .models import (
    ALLOWED_HOME_BLOCK_DOWNLOAD_EXT,
    HomeBlockDownloadHit,
    ServerHomeBlock,
    validate_home_block_download_size,
)

DEFAULT_DOWNLOAD_BUTTON_LABEL = '下载文件'


def block_has_download_file(block) -> bool:
    f = getattr(block, 'download_file', None)
    return bool(f and getattr(f, 'name', None))


def block_download_button_label(block) -> str:
    label = (getattr(block, 'link_label', None) or '').strip()
    return label or DEFAULT_DOWNLOAD_BUTTON_LABEL


def block_download_url(block) -> str:
    return reverse('home_block_download', kwargs={'block_id': str(block.block_id)})


def download_content_disposition(original_name: str) -> str:
    """ASCII 兜底 + UTF-8 中文名（避免浏览器保存成「下载」且无扩展名）"""
    raw = (original_name or 'download.bin').replace('\\', '/').rsplit('/', 1)[-1]
    ext = raw.rsplit('.', 1)[-1].lower() if '.' in raw else 'bin'
    if ext not in ALLOWED_HOME_BLOCK_DOWNLOAD_EXT:
        ext = 'bin'
    ascii_stem = re.sub(r'[^A-Za-z0-9._-]+', '_', raw.rsplit('.', 1)[0])[:60].strip('._') or 'download'
    if not re.search(r'[A-Za-z0-9]', ascii_stem):
        ascii_stem = 'YecaoST_Download'
    ascii_name = f'{ascii_stem}.{ext}'
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(raw)}"
    )


def apply_home_block_download_from_post(block, request) -> str | None:
    """
    处理上传/清除下载附件。成功返回 None；失败返回白话错误。
    """
    clear = request.POST.get('clear_block_download') == '1'
    uploaded = request.FILES.get('block_download')

    if clear and not uploaded:
        _clear_download_file(block)
        return None

    if not uploaded:
        return None

    name = (getattr(uploaded, 'name', '') or '').lower()
    ext = name.rsplit('.', 1)[-1] if '.' in name else ''
    if ext not in ALLOWED_HOME_BLOCK_DOWNLOAD_EXT:
        return '下载文件只支持：exe、zip、pdf、msi、7z、rar。'
    try:
        validate_home_block_download_size(uploaded)
    except ValidationError as exc:
        return '; '.join(exc.messages) if hasattr(exc, 'messages') else str(exc)

    if block.download_file:
        try:
            block.download_file.delete(save=False)
        except Exception:
            pass
    block.download_file = uploaded
    return None


def _clear_download_file(block) -> None:
    if block.download_file:
        try:
            block.download_file.delete(save=False)
        except Exception:
            pass
    block.download_file = None


def client_ip(request) -> str | None:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    if forwarded:
        return forwarded[:45]
    raw = request.META.get('REMOTE_ADDR')
    return raw[:45] if raw else None


def record_home_block_download(request, block: ServerHomeBlock) -> None:
    """写入下载真源；若私人包可用则再记一条访客点击（计入真人）。"""
    filename = ''
    if block.download_file and block.download_file.name:
        filename = Path(block.download_file.name).name
    HomeBlockDownloadHit.objects.create(
        block_id=block.block_id,
        block_title=(block.title or '')[:120],
        original_filename=filename[:255],
        ip=client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:300],
    )
    _try_record_visitor_click(request, block, filename)


def _try_record_visitor_click(request, block, filename: str) -> None:
    try:
        from django.conf import settings
        if not getattr(settings, 'YECAO_OWNER_TOOLKIT_ENABLED', False):
            return
        from owner_toolkit.analytics_helpers import (
            ensure_visitor_session_for_download,
        )
        from owner_toolkit.models import VisitorClickEvent, VisitorSession

        session = ensure_visitor_session_for_download(request)
        if session is None:
            return
        label = f'下载:{(block.title or filename or "文件")[:180]}'
        VisitorClickEvent.objects.create(
            session=session,
            page_view=None,
            path=(request.path or '')[:500],
            element_label=label[:200],
        )
        VisitorSession.objects.filter(pk=session.pk).update(last_seen_at=timezone.now())
    except Exception:
        return


def summarize_home_block_downloads(*, days: int = 7) -> dict:
    """近 N 天：总次数 + 按 IP；供私人包访客统计页展示。"""
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=days)
    qs = HomeBlockDownloadHit.objects.filter(clicked_at__gte=cutoff)
    total = qs.count()
    by_ip_rows = list(
        qs.values('ip').annotate(times=Count('hit_id')).order_by('-times', 'ip')[:100]
    )
    by_ip = [{'ip': row['ip'] or '—', 'times': row['times']} for row in by_ip_rows]
    by_block_rows = list(
        qs.values('block_title', 'original_filename')
        .annotate(times=Count('hit_id'))
        .order_by('-times')[:50]
    )
    by_block = [
        {
            'title': row['block_title'] or '（无标题）',
            'filename': row['original_filename'] or '—',
            'times': row['times'],
        }
        for row in by_block_rows
    ]
    return {'total': total, 'by_ip': by_ip, 'by_block': by_block}


def serve_home_block_download(request, block_id):
    """先记账再发文件。"""
    block = ServerHomeBlock.objects.filter(
        block_id=block_id,
        block_type='file_download',
        is_enabled=True,
    ).first()
    if not block or not block_has_download_file(block):
        return HttpResponse(
            '该下载暂不可用（未启用或未上传文件）。',
            status=404,
            content_type='text/plain; charset=utf-8',
        )

    path = Path(block.download_file.path)
    if not path.is_file():
        return HttpResponse(
            '文件已丢失，请服务器管理者重新上传。',
            status=404,
            content_type='text/plain; charset=utf-8',
        )

    record_home_block_download(request, block)
    original = Path(block.download_file.name).name
    response = FileResponse(path.open('rb'), as_attachment=False)
    response['Content-Type'] = 'application/octet-stream'
    response['Content-Disposition'] = download_content_disposition(original)

    new_key = getattr(request, '_yc_new_visitor_cookie', None)
    if new_key:
        response.set_cookie(
            'yc_va_sid',
            new_key,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite='Lax',
            secure=request.is_secure(),
        )
    return response
