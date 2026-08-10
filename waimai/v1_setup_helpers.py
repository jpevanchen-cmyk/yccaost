# V1 本地营业内测 · 首次安装向导（§5.16.4）
# 仅在「待安装」标记或手动打开向导时引导；开发机已有店铺不受影响。

from __future__ import annotations

import re
import secrets
import socket
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from .v1_local_helpers import INSTALL_MODE_V1_LOCAL, set_db_install_mode

User = get_user_model()

V1_SETUP_SESSION_KEY = 'v1_setup_draft'
V1_SETUP_PATH_PREFIX = '/v1-local/setup'
# 仅首次向导期间加长会话（秒）；不改 settings 里全站约 5 分钟
V1_SETUP_SESSION_SECONDS = 15 * 60
V1_SETUP_STEPS = (
    ('welcome', '欢迎'),
    ('shop', '店名与老板账号'),
    ('network', '端口与本机地址'),
    ('plugins', '插件'),
    ('payment', '支付'),
    ('backup', '备份目录'),
    ('done', '完成'),
)
V1_SETUP_STEP_SLUGS = [row[0] for row in V1_SETUP_STEPS]
DEFAULT_LISTEN_PORT = 8000


def v1_install_pending_from_settings() -> bool:
    """安装程序或维护者显式标记：首次打开浏览器应进向导。"""
    return bool(getattr(settings, 'YECAO_V1_INSTALL_PENDING', False))


def path_is_v1_setup(path: str) -> bool:
    path = (path or '').split('?', 1)[0]
    return path.startswith(V1_SETUP_PATH_PREFIX)


def touch_v1_setup_session(request) -> None:
    """
    向导页访问时把本会话寿命设为 15 分钟，并标记已改以便写出 Cookie。
    不修改全站 SESSION_COOKIE_AGE。
    """
    request.session.set_expiry(V1_SETUP_SESSION_SECONDS)
    request.session.modified = True


def v1_setup_completed() -> bool:
    from .owner_helpers import get_site_settings

    return bool(get_site_settings().v1_setup_completed)


def any_v1_shop_exists() -> bool:
    """是否已有卖家主账号（含服务器管理者）。"""
    from .models import ShopProfile

    if User.objects.filter(role='seller', is_server_owner=True).exists():
        return True
    return ShopProfile.objects.exists()


def should_auto_redirect_to_v1_setup() -> bool:
    """
    仅「待安装 + 未完成 + 尚无店铺」时自动跳向导。
    开发机已有店：不跳。
    """
    if not v1_install_pending_from_settings():
        return False
    if v1_setup_completed():
        return False
    if any_v1_shop_exists():
        return False
    return True


def v1_setup_allowed_manual() -> tuple[bool, str]:
    """手动打开向导是否允许（未完成且无既有主店）。"""
    if v1_setup_completed():
        return False, '首次向导已完成，请直接登录。'
    if any_v1_shop_exists():
        return False, '本机已有店铺数据，不能重复跑首次向导；请照常登录使用。'
    return True, ''


def detect_lan_ip() -> str | None:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return None


def default_lan_base_url(port: int = DEFAULT_LISTEN_PORT) -> str:
    """探测成功则返回 http://局域网IP:端口；失败返回空串（禁止退回 127.0.0.1）。"""
    from .operating_helpers import http_base_is_loopback

    ip = detect_lan_ip()
    if not ip:
        return ''
    candidate = f'http://{ip}:{port}'
    if http_base_is_loopback(candidate):
        return ''
    return candidate


def default_backup_dir() -> str:
    return str(Path(getattr(settings, 'BASE_DIR', Path('.'))) / 'backup')


def get_setup_draft(request) -> dict[str, Any]:
    draft = request.session.get(V1_SETUP_SESSION_KEY)
    if not isinstance(draft, dict):
        draft = {}
    return draft


def save_setup_draft(request, **updates) -> dict[str, Any]:
    draft = get_setup_draft(request)
    draft.update(updates)
    request.session[V1_SETUP_SESSION_KEY] = draft
    request.session.modified = True
    return draft


def clear_setup_draft(request) -> None:
    request.session.pop(V1_SETUP_SESSION_KEY, None)
    request.session.modified = True


def setup_step_index(slug: str) -> int:
    try:
        return V1_SETUP_STEP_SLUGS.index(slug)
    except ValueError:
        return 0


def setup_step_url(slug: str) -> str:
    from django.urls import reverse

    return reverse('v1_setup_step', kwargs={'step_slug': slug})


def normalize_lan_base_url(raw: str, port: int) -> str:
    text = (raw or '').strip()
    if not text:
        return default_lan_base_url(port)
    if not re.match(r'^https?://', text, re.I):
        text = 'http://' + text
    return text.rstrip('/')


def lan_base_url_rejection_message(url: str) -> str:
    """若地址不可给店内手机用，返回白话原因；可用则返回空串。"""
    from .operating_helpers import http_base_is_loopback

    text = (url or '').strip()
    if not text:
        return ''
    if http_base_is_loopback(text):
        return (
            '不能使用 127.0.0.1 或 localhost：只能本机打开，店内手机无法访问。'
            '请填写真实局域网地址，或暂时留空稍后在堂食营业里补填。'
        )
    return ''


def normalize_backup_dir(raw: str) -> str:
    text = (raw or '').strip() or default_backup_dir()
    return str(Path(text))


def generate_production_secret_key() -> str:
    return secrets.token_urlsafe(48)


def write_v1_env_hint_file(secret_key: str) -> Path:
    """写入本机提示文件（已在 .gitignore）；供正式营业前合并到 .env。"""
    base = Path(getattr(settings, 'BASE_DIR', Path('.')))
    target = base / '.env.v1.generated'
    content = (
        '# 由 V1 首次向导生成；请核对后合并进 .env（勿提交 Git）\n'
        f'YECAO_DEBUG=0\n'
        f'YECAO_SECRET_KEY={secret_key}\n'
        '# 可选：关闭安装待完成标记（若安装程序写过 YECAO_V1_INSTALL_PENDING=1）\n'
        '# YECAO_V1_INSTALL_PENDING=0\n'
        '# 本地营业建议：YECAO_V1_LOCAL_MODE=1\n'
    )
    target.write_text(content, encoding='utf-8')
    return target


@transaction.atomic
def finalize_v1_setup(draft: dict[str, Any]) -> tuple[User, dict[str, Any]]:
    """
    根据会话草稿创建老板+店铺，写入 V1 模式并完成站点设置。
    返回 (老板用户, 完成页摘要)。
    """
    from .home_page_helpers import ensure_home_page_for_seller, ensure_server_home_page
    from .menu_helpers import ensure_active_menu_catalog
    from .models import ShopDeliverySettings, ShopPaymentSettings, ShopProfile
    from .operating_helpers import get_operating_settings
    from .owner_helpers import get_site_settings
    from .shop_code_helpers import assign_shop_code_on_create
    from .staff_account_helpers import create_owner_workbench_staff

    username = (draft.get('username') or '').strip()
    password = draft.get('password') or ''
    shop_name = (draft.get('shop_name') or '').strip()
    address = (draft.get('address') or '').strip() or '本店地址待补充'
    listen_port = int(draft.get('listen_port') or DEFAULT_LISTEN_PORT)
    lan_base_url = normalize_lan_base_url(draft.get('lan_base_url') or '', listen_port)
    backup_dir = normalize_backup_dir(draft.get('backup_dir') or '')
    fulfillment_enabled = bool(draft.get('fulfillment_enabled'))

    if not username or not password or not shop_name:
        raise ValueError('向导数据不完整，请从第 2 步重新填写。')
    if User.objects.filter(username=username).exists():
        raise ValueError(f'登录名「{username}」已被占用，请返回第 2 步更换。')

    user = User.objects.create_user(
        username=username,
        password=password,
        role='seller',
    )
    user.is_server_owner = True
    user.save(update_fields=['is_server_owner'])

    profile = ShopProfile.objects.create(
        seller_id=user.username,
        shop_name=shop_name,
        shop_type='restaurant',
        address=address,
        is_listed=True,
        is_official=False,
    )
    assign_shop_code_on_create(profile)
    ShopDeliverySettings.objects.create(seller_id=user.username)
    pay = ShopPaymentSettings.objects.create(seller_id=user.username)
    pay.enable_cash = bool(draft.get('enable_cash', True))
    pay.enable_wechat = bool(draft.get('enable_wechat', False))
    pay.enable_simulate = bool(draft.get('enable_simulate', True))
    pay.wechat_mch_id = (draft.get('wechat_mch_id') or '').strip()
    pay.wechat_app_id = (draft.get('wechat_app_id') or '').strip()
    pay.wechat_api_key = (draft.get('wechat_api_key') or '').strip()
    pay.public_site_url = (draft.get('public_site_url') or '').strip()
    pay.save()

    operating = get_operating_settings(user.username)
    operating.plugin_dining_enabled = True
    operating.plugin_fulfillment_enabled = fulfillment_enabled
    operating.table_lan_base_url = lan_base_url
    operating.save(
        update_fields=[
            'plugin_dining_enabled',
            'plugin_fulfillment_enabled',
            'table_lan_base_url',
        ],
    )

    ensure_home_page_for_seller(user.username, profile)
    ensure_active_menu_catalog(user.username)
    ensure_server_home_page()
    create_owner_workbench_staff(user, password)

    secret_key = generate_production_secret_key()
    env_hint_path = write_v1_env_hint_file(secret_key)
    # 放行向导填写的局域网主机，避免手机/电脑用该 IP 访问时 400
    from .v1_allowed_hosts_helpers import apply_lan_url_to_allowed_hosts

    apply_lan_url_to_allowed_hosts(lan_base_url)

    site = get_site_settings()
    site.site_name = shop_name
    site.v1_setup_completed = True
    site.v1_listen_port = listen_port
    site.v1_lan_base_url = lan_base_url
    site.v1_backup_dir = backup_dir
    site.install_mode = INSTALL_MODE_V1_LOCAL
    site.save(
        update_fields=[
            'site_name',
            'v1_setup_completed',
            'v1_listen_port',
            'v1_lan_base_url',
            'v1_backup_dir',
            'install_mode',
            'updated_at',
        ],
    )
    set_db_install_mode(INSTALL_MODE_V1_LOCAL)

    summary = {
        'shop_name': shop_name,
        'username': username,
        'shop_code': profile.shop_code,
        'listen_port': listen_port,
        'lan_base_url': lan_base_url,
        'backup_dir': backup_dir,
        'dining_enabled': True,
        'fulfillment_enabled': fulfillment_enabled,
        'env_hint_file': str(env_hint_path),
        'login_path': '/accounts/login/',
        'seller_panel_path': '/seller-panel/',
        'workbench_hint': f'/s/{profile.shop_code}/work/',
    }
    return user, summary
