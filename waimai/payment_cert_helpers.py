# 微信退款证书：上传保存与校验（V1 · 存本机私有目录，不对外提供下载）

from __future__ import annotations

from pathlib import Path

from django.conf import settings

from .models import ShopPaymentSettings

CERT_FILENAME = 'apiclient_cert.pem'
KEY_FILENAME = 'apiclient_key.pem'
MAX_PEM_BYTES = 256 * 1024


def wechat_cert_storage_dir(seller_id: str) -> Path:
    """本店证书存放目录（自动创建）。"""
    base = Path(settings.BASE_DIR) / 'private' / 'wechat_certs' / (seller_id or '').strip()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _path_readable(path_text: str) -> bool:
    path = (path_text or '').strip()
    if not path:
        return False
    try:
        return Path(path).is_file()
    except OSError:
        return False


def build_wechat_cert_display(pay: ShopPaymentSettings) -> dict:
    """支付设置页：证书上传与可读状态（供人眼核对路径）。"""
    cert_path = (pay.wechat_apiclient_cert_path or '').strip()
    key_path = (pay.wechat_apiclient_key_path or '').strip()
    cert_ok = _path_readable(cert_path)
    key_ok = _path_readable(key_path)
    files_ready = cert_ok and key_ok
    wechat_ready = pay.wechat_config_ready()
    refund_ready = pay.wechat_refund_config_ready()

    if refund_ready:
        summary = '证书已上传且系统可读；微信退款已就绪'
    elif files_ready and not wechat_ready:
        summary = '证书已上传且系统可读；还须勾选「开启微信支付」并填齐商户号/AppID/密钥'
    elif cert_path or key_path:
        if not cert_ok and not key_ok:
            summary = '数据库有记录，但找不到证书文件，请重新上传'
        elif cert_ok and not key_ok:
            summary = '证书文件可读；私钥缺失或未上传，请补传 apiclient_key.pem'
        elif key_ok and not cert_ok:
            summary = '私钥文件可读；证书缺失或未上传，请补传 apiclient_cert.pem'
        else:
            summary = '请重新上传两个证书文件'
    else:
        summary = '尚未上传（取消已微信收款订单时需要）'

    return {
        'summary': summary,
        'cert_path': cert_path,
        'key_path': key_path,
        'cert_readable': cert_ok,
        'key_readable': key_ok,
        'files_ready': files_ready,
        'wechat_params_ready': wechat_ready,
        'refund_ready': refund_ready,
        'has_any_record': bool(cert_path or key_path or files_ready),
        'can_clear': bool(cert_path or key_path or cert_ok or key_ok),
    }


def wechat_cert_status_label(pay: ShopPaymentSettings) -> str:
    """兼容旧模板字段：返回摘要一句。"""
    return build_wechat_cert_display(pay)['summary']


def _read_upload_limited(uploaded_file) -> bytes:
    """读取上传文件并限制大小。"""
    chunks: list[bytes] = []
    total = 0
    for chunk in uploaded_file.chunks():
        total += len(chunk)
        if total > MAX_PEM_BYTES:
            raise ValueError('文件过大，请选择正确的 apiclient 证书文件（一般几十 KB）')
        chunks.append(chunk)
    return b''.join(chunks)


def _validate_pem_bytes(content: bytes, *, kind: str) -> None:
    """简单校验 PEM 内容，避免传错文件。"""
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('证书文件编码异常，请重新从微信商户平台下载原文件') from exc
    if '-----BEGIN' not in text or '-----END' not in text:
        raise ValueError('不是有效的 PEM 证书文件，请确认选对了 apiclient 证书包里的文件')
    if kind == 'cert' and 'CERTIFICATE' not in text:
        raise ValueError('这不是 apiclient_cert.pem，请选证书文件（不是私钥）')
    if kind == 'key' and 'PRIVATE KEY' not in text:
        raise ValueError('这不是 apiclient_key.pem，请选私钥文件（不是证书）')


def _validate_upload_name(filename: str, expected: str) -> None:
    name = (filename or '').lower()
    if not name.endswith('.pem'):
        raise ValueError(f'请上传 .pem 文件：{expected}')


def apply_wechat_cert_uploads(
    pay: ShopPaymentSettings,
    *,
    cert_file=None,
    key_file=None,
) -> list[str]:
    """
    保存店主上传的退款证书/私钥，并写回 ShopPaymentSettings 路径字段。
    返回错误文案列表；空列表表示成功或无新上传。
    """
    errors: list[str] = []
    if not cert_file and not key_file:
        return errors

    seller_id = (pay.seller_id or '').strip()
    if not seller_id:
        return ['店铺信息异常，无法保存证书']

    cert_dir = wechat_cert_storage_dir(seller_id)
    update_fields: list[str] = []

    if cert_file:
        try:
            _validate_upload_name(cert_file.name, CERT_FILENAME)
            content = _read_upload_limited(cert_file)
            _validate_pem_bytes(content, kind='cert')
            target = cert_dir / CERT_FILENAME
            target.write_bytes(content)
            pay.wechat_apiclient_cert_path = str(target.resolve())
            update_fields.append('wechat_apiclient_cert_path')
        except ValueError as exc:
            errors.append(str(exc))
        except OSError:
            errors.append('证书保存失败，请检查磁盘权限后重试')

    if key_file:
        try:
            _validate_upload_name(key_file.name, KEY_FILENAME)
            content = _read_upload_limited(key_file)
            _validate_pem_bytes(content, kind='key')
            target = cert_dir / KEY_FILENAME
            target.write_bytes(content)
            pay.wechat_apiclient_key_path = str(target.resolve())
            update_fields.append('wechat_apiclient_key_path')
        except ValueError as exc:
            errors.append(str(exc))
        except OSError:
            errors.append('私钥保存失败，请检查磁盘权限后重试')

    if update_fields and not errors:
        pay.save(update_fields=update_fields)

    return errors


def clear_wechat_cert_files(pay: ShopPaymentSettings) -> tuple[bool, str]:
    """删除本店已上传的退款证书文件并清空数据库路径。"""
    seller_id = (pay.seller_id or '').strip()
    if not seller_id:
        return False, '店铺信息异常，无法删除证书'

    for path_text in (
        (pay.wechat_apiclient_cert_path or '').strip(),
        (pay.wechat_apiclient_key_path or '').strip(),
    ):
        if not path_text:
            continue
        try:
            path = Path(path_text)
            if path.is_file():
                path.unlink()
        except OSError:
            return False, '删除证书文件失败，请检查文件是否被占用'

    pay.wechat_apiclient_cert_path = ''
    pay.wechat_apiclient_key_path = ''
    pay.save(update_fields=['wechat_apiclient_cert_path', 'wechat_apiclient_key_path'])

    cert_dir = wechat_cert_storage_dir(seller_id)
    try:
        if cert_dir.is_dir() and not any(cert_dir.iterdir()):
            cert_dir.rmdir()
    except OSError:
        pass

    return True, '已删除本店上传的微信退款证书'
