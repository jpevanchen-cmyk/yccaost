# 服务器主页「文件下载」积木：上传、记账、代发文件（含传输结果回填）

from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import HttpResponse, StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone

from .models import (
    ALLOWED_HOME_BLOCK_DOWNLOAD_EXT,
    HomeBlockDownloadHit,
    ServerHomeBlock,
    validate_home_block_download_size,
)

DEFAULT_DOWNLOAD_BUTTON_LABEL = '下载文件'
_STREAM_CHUNK = 64 * 1024


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


def record_home_block_download(request, block: ServerHomeBlock, *, file_size_bytes: int = 0):
    """写入下载真源（开始时）；返回记账行。私人包可用则再记访客点击。"""
    filename = ''
    if block.download_file and block.download_file.name:
        filename = Path(block.download_file.name).name
    hit = HomeBlockDownloadHit.objects.create(
        block_id=block.block_id,
        block_title=(block.title or '')[:120],
        original_filename=filename[:255],
        ip=client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:300],
        file_size_bytes=max(0, int(file_size_bytes or 0)),
        bytes_sent=0,
    )
    _try_record_visitor_click(request, block, filename)
    return hit


def finalize_download_hit(hit_id, *, bytes_sent: int, started_mono: float) -> None:
    """连接结束时回填发出量、时长、是否接近传完（幂等：已结束则不再改）。"""
    duration_ms = max(0, int((time.monotonic() - started_mono) * 1000))
    bytes_sent = max(0, int(bytes_sent or 0))
    hit = HomeBlockDownloadHit.objects.filter(pk=hit_id).only(
        'file_size_bytes', 'finished_at',
    ).first()
    if hit is None or hit.finished_at is not None:
        return
    file_size = int(hit.file_size_bytes or 0)
    if file_size > 0:
        threshold = max(file_size - 1024, int(file_size * 0.99))
        near = bytes_sent >= threshold
    else:
        near = bytes_sent > 0
    HomeBlockDownloadHit.objects.filter(pk=hit_id, finished_at__isnull=True).update(
        bytes_sent=bytes_sent,
        finished_at=timezone.now(),
        duration_ms=duration_ms,
        near_complete=near,
    )


def _stream_and_finalize(path: Path, hit_id, file_size: int):
    """边读边发；无论传完或中途断开，尽量在 finally 回填结果。"""
    sent = 0
    started = time.monotonic()
    try:
        with path.open('rb') as f:
            while True:
                chunk = f.read(_STREAM_CHUNK)
                if not chunk:
                    break
                sent += len(chunk)
                yield chunk
    finally:
        try:
            finalize_download_hit(hit_id, bytes_sent=sent, started_mono=started)
        except Exception:
            pass


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


def _format_bytes_mb(n: int) -> str:
    n = max(0, int(n or 0))
    return f'{n / (1024 * 1024):.2f}'


def _format_duration(ms: int) -> str:
    ms = max(0, int(ms or 0))
    if ms <= 0:
        return '—'
    sec = ms / 1000.0
    if sec < 60:
        return f'{sec:.1f} 秒'
    minutes = int(sec // 60)
    rem = sec - minutes * 60
    return f'{minutes} 分 {rem:.0f} 秒'


def _format_speed(bytes_sent: int, duration_ms: int) -> str:
    if duration_ms <= 0 or bytes_sent <= 0:
        return '—'
    bps = bytes_sent / (duration_ms / 1000.0)
    if bps >= 1024 * 1024:
        return f'{bps / (1024 * 1024):.2f} MB/s'
    if bps >= 1024:
        return f'{bps / 1024:.0f} KB/s'
    return f'{bps:.0f} B/s'


def _hit_result_label(hit) -> str:
    if not hit.finished_at:
        return '未回填（旧记录或传输中）'
    if hit.near_complete:
        return '接近传完'
    if (hit.bytes_sent or 0) <= 0:
        return '几乎未传出'
    return '只传一部分'


def summarize_home_block_downloads(*, days: int = 7) -> dict:
    """近 N 天：总次数 + 按 IP + 按积木 + 明细列表。"""
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
    recent = []
    for hit in qs.order_by('-clicked_at')[:80]:
        recent.append({
            'clicked_at': hit.clicked_at,
            'finished_at': hit.finished_at,
            'ip': hit.ip or '—',
            'title': hit.block_title or '（无标题）',
            'filename': hit.original_filename or '—',
            'file_mb': _format_bytes_mb(hit.file_size_bytes),
            'sent_mb': _format_bytes_mb(hit.bytes_sent) if hit.finished_at else '—',
            'duration': _format_duration(hit.duration_ms) if hit.finished_at else '—',
            'speed': _format_speed(hit.bytes_sent, hit.duration_ms) if hit.finished_at else '—',
            'result': _hit_result_label(hit),
        })
    return {
        'total': total,
        'by_ip': by_ip,
        'by_block': by_block,
        'recent': recent,
    }


def serve_home_block_download(request, block_id):
    """先记账再流式发文件；连接结束回填发出量与时长。"""
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

    file_size = path.stat().st_size
    hit = record_home_block_download(request, block, file_size_bytes=file_size)
    original = Path(block.download_file.name).name
    response = StreamingHttpResponse(
        _stream_and_finalize(path, hit.hit_id, file_size),
        content_type='application/octet-stream',
    )
    response['Content-Length'] = str(file_size)
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
