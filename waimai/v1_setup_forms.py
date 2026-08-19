# V1 首次向导 · 各步表单

from django import forms
from django.contrib.auth.password_validation import validate_password

from .staff_account_helpers import validate_main_eco_username
from .v1_setup_helpers import (
    DEFAULT_LISTEN_PORT,
    default_backup_dir,
    default_lan_base_url,
    lan_base_url_rejection_message,
    normalize_backup_dir,
    normalize_lan_base_url,
)


class V1SetupShopForm(forms.Form):
    shop_name = forms.CharField(max_length=100, label='店铺名称')
    username = forms.CharField(max_length=150, label='老板登录名')
    password1 = forms.CharField(widget=forms.PasswordInput, label='登录密码')
    password2 = forms.CharField(widget=forms.PasswordInput, label='确认密码')
    address = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        label='店铺地址',
        required=False,
    )

    def clean_username(self):
        from django.contrib.auth import get_user_model

        username = validate_main_eco_username(self.cleaned_data.get('username'))
        if get_user_model().objects.filter(username=username).exists():
            raise forms.ValidationError('该登录名已被占用，请换一个。')
        return username

    def clean_shop_name(self):
        from .shop_name_helpers import validate_new_shop_name

        return validate_new_shop_name(self.cleaned_data.get('shop_name'))

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('password1') or ''
        p2 = cleaned.get('password2') or ''
        if p1 != p2:
            raise forms.ValidationError('两次输入的密码不一致。')
        if p1:
            validate_password(p1)
        return cleaned


class V1SetupNetworkForm(forms.Form):
    listen_port = forms.IntegerField(
        min_value=1024,
        max_value=65535,
        initial=DEFAULT_LISTEN_PORT,
        label='本机端口',
        help_text='店内设备用浏览器访问时，地址里的端口号（常见 8000）。',
    )
    lan_base_url = forms.CharField(
        max_length=255,
        required=False,
        label='本机局域网地址',
        help_text='能自动测到会预填。测不到则留空，请自行填写店内地址；不要填 127.0.0.1。',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 草稿若带空字符串，须覆盖写入，不能用 setdefault（空键已存在不会补）
        if not (self.initial.get('lan_base_url') or '').strip():
            port = int(self.initial.get('listen_port') or DEFAULT_LISTEN_PORT)
            self.initial['lan_base_url'] = default_lan_base_url(port)

    def clean_lan_base_url(self):
        port = int(self.cleaned_data.get('listen_port') or DEFAULT_LISTEN_PORT)
        url = normalize_lan_base_url(self.cleaned_data.get('lan_base_url') or '', port)
        msg = lan_base_url_rejection_message(url)
        if msg:
            raise forms.ValidationError(msg)
        return url


class V1SetupPluginsForm(forms.Form):
    enable_fulfillment = forms.BooleanField(
        required=False,
        initial=False,
        label='启用履约配送插件',
        help_text='本地堂食内测通常可不选；以后可在卖家后台「插件试验」里再开。',
    )


class V1SetupPaymentForm(forms.Form):
    enable_cash = forms.BooleanField(required=False, initial=True, label='现金支付')
    enable_wechat = forms.BooleanField(required=False, initial=False, label='商户微信支付')
    enable_simulate = forms.BooleanField(
        required=False,
        initial=True,
        label='演示/模拟支付（仅老板主账号可用）',
    )
    wechat_mch_id = forms.CharField(required=False, label='微信商户号')
    wechat_app_id = forms.CharField(required=False, label='微信 AppID')
    wechat_api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label='微信 APIv2 密钥',
    )
    public_site_url = forms.CharField(
        required=False,
        label='公网网址（可选）',
        help_text='无公网可留空，靠轮询查单。',
    )


class V1SetupBackupForm(forms.Form):
    backup_dir = forms.CharField(
        max_length=500,
        required=False,
        label='备份目录',
        help_text='已预填默认位置。可点「选择文件夹」改；留空则用默认。',
        widget=forms.TextInput(attrs={'id': 'id_backup_dir', 'style': 'width:100%;max-width:28rem;'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not (self.initial.get('backup_dir') or '').strip():
            self.initial['backup_dir'] = default_backup_dir()

    def clean_backup_dir(self):
        return normalize_backup_dir(self.cleaned_data.get('backup_dir') or '')
