from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import (
    MenuProfile,
    ShopDeliverySettings,
    ShopOperatingSettings,
    ShopPaymentSettings,
    ShopProfile,
    User,
)
from .shop_code_helpers import assign_shop_code_on_create


class BuyerRegistrationForm(UserCreationForm):
    """买家注册：仅允许注册买家身份"""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields

    def clean(self):
        cleaned = super().clean()
        from .experience_helpers import can_register_experience_account

        ok, msg = can_register_experience_account()
        if not ok:
            raise forms.ValidationError(msg)
        return cleaned

    def save(self, commit=True):
        from .experience_helpers import apply_experience_flags_for_new_user

        user = super().save(commit=False)
        user.role = 'buyer'
        if commit:
            user.save()
            apply_experience_flags_for_new_user(user)
        return user


class ShopRegistrationForm(UserCreationForm):
    """店铺注册服务器：创建卖家账号 + 店铺信息"""

    shop_name = forms.CharField(max_length=100, label='店铺名称')
    shop_type = forms.ChoiceField(choices=ShopProfile.SHOP_TYPE_CHOICES, label='店铺类型')
    address = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), label='店铺地址')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields

    def clean(self):
        cleaned = super().clean()
        from .experience_helpers import can_register_experience_shop

        ok, msg = can_register_experience_shop()
        if not ok:
            raise forms.ValidationError(msg)
        return cleaned

    def save(self, commit=True):
        from .experience_helpers import apply_experience_flags_for_new_user, experience_site_enabled

        user = super().save(commit=False)
        user.role = 'seller'
        if commit:
            user.save()
            apply_experience_flags_for_new_user(user, is_shop=True)
            profile = ShopProfile.objects.create(
                seller_id=user.username,
                shop_name=self.cleaned_data['shop_name'],
                shop_type=self.cleaned_data['shop_type'],
                address=self.cleaned_data['address'],
                is_listed=True,
                is_official=False,  # 公网开通默认体验店；官方店用管理命令标记
            )
            assign_shop_code_on_create(profile)
            ShopDeliverySettings.objects.create(seller_id=user.username)
            pay = ShopPaymentSettings.objects.create(seller_id=user.username)
            if experience_site_enabled():
                # 体验店默认只开模拟支付，禁止真微信
                pay.enable_wechat = False
                pay.enable_simulate = True
                pay.save(update_fields=['enable_wechat', 'enable_simulate'])
            ShopOperatingSettings.objects.create(seller_id=user.username)
            from .home_page_helpers import ensure_home_page_for_seller, ensure_server_home_page
            ensure_home_page_for_seller(user.username, profile)
            ensure_server_home_page()
        return user


class CreateRiderForm(UserCreationForm):
    """卖家为本店创建专属骑手账号（工牌名仅本店唯一）"""

    perm_cancel_order = forms.BooleanField(
        required=False, initial=False, label='允许取消订单（店长权限）',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, seller_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seller_id = seller_id
        self.fields['username'].label = '员工用户名'
        self.fields['username'].help_text = '只在本店不能重复；别的店可以用同名'

    def clean_username(self):
        from .staff_account_helpers import STAFF_USERNAME_SEP, staff_username_taken

        name = (self.cleaned_data.get('username') or '').strip()
        if not name:
            raise forms.ValidationError('请输入用户名')
        if STAFF_USERNAME_SEP in name:
            raise forms.ValidationError('用户名不能包含 ::')
        if not self.seller_id:
            raise forms.ValidationError('店铺信息无效')
        if staff_username_taken(self.seller_id, name):
            raise forms.ValidationError('本店已有该员工用户名')
        return name

    def save(self, commit=True):
        from .staff_account_helpers import staff_internal_username

        user = super().save(commit=False)
        user.username = staff_internal_username(self.seller_id, self.cleaned_data['username'])
        user.role = 'rider'
        user.employer_seller_id = self.seller_id
        user.perm_cancel_order = bool(self.cleaned_data.get('perm_cancel_order'))
        if commit:
            user.save()
            from .experience_helpers import inherit_experience_from_employer
            inherit_experience_from_employer(user, self.seller_id)
        return user


class CreateWaiterForm(UserCreationForm):
    """卖家为本店创建服务员子账号（工牌名仅本店唯一）"""

    perm_cancel_order = forms.BooleanField(
        required=False, initial=False, label='允许取消订单（店长权限）',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, seller_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seller_id = seller_id
        self.fields['username'].label = '员工用户名'
        self.fields['username'].help_text = '只在本店不能重复；别的店可以用同名'

    def clean_username(self):
        from .staff_account_helpers import STAFF_USERNAME_SEP, staff_username_taken

        name = (self.cleaned_data.get('username') or '').strip()
        if not name:
            raise forms.ValidationError('请输入用户名')
        if STAFF_USERNAME_SEP in name:
            raise forms.ValidationError('用户名不能包含 ::')
        if not self.seller_id:
            raise forms.ValidationError('店铺信息无效')
        if staff_username_taken(self.seller_id, name):
            raise forms.ValidationError('本店已有该员工用户名')
        return name

    def save(self, commit=True):
        from .staff_account_helpers import staff_internal_username

        user = super().save(commit=False)
        user.username = staff_internal_username(self.seller_id, self.cleaned_data['username'])
        user.role = 'waiter'
        user.employer_seller_id = self.seller_id
        user.perm_cancel_order = bool(self.cleaned_data.get('perm_cancel_order'))
        if commit:
            user.save()
            from .experience_helpers import inherit_experience_from_employer
            inherit_experience_from_employer(user, self.seller_id)
        return user


class CreateKitchenForm(UserCreationForm):
    """卖家为本店创建后厨子账号（工牌名仅本店唯一）"""

    perm_cancel_order = forms.BooleanField(
        required=False, initial=False, label='允许取消订单（店长权限）',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, seller_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seller_id = seller_id
        self.fields['username'].label = '员工用户名'
        self.fields['username'].help_text = '只在本店不能重复；别的店可以用同名'

    def clean_username(self):
        from .staff_account_helpers import STAFF_USERNAME_SEP, staff_username_taken

        name = (self.cleaned_data.get('username') or '').strip()
        if not name:
            raise forms.ValidationError('请输入用户名')
        if STAFF_USERNAME_SEP in name:
            raise forms.ValidationError('用户名不能包含 ::')
        if not self.seller_id:
            raise forms.ValidationError('店铺信息无效')
        if staff_username_taken(self.seller_id, name):
            raise forms.ValidationError('本店已有该员工用户名')
        return name

    def save(self, commit=True):
        from .staff_account_helpers import staff_internal_username

        user = super().save(commit=False)
        user.username = staff_internal_username(self.seller_id, self.cleaned_data['username'])
        user.role = 'kitchen'
        user.employer_seller_id = self.seller_id
        user.perm_cancel_order = bool(self.cleaned_data.get('perm_cancel_order'))
        if commit:
            user.save()
            from .experience_helpers import inherit_experience_from_employer
            inherit_experience_from_employer(user, self.seller_id)
        return user


class CreateManagerForm(UserCreationForm):
    """卖家为本店创建店长子账号（工牌名仅本店唯一）"""

    perm_cancel_order = forms.BooleanField(
        required=False, initial=True, label='允许取消订单（店长权限）',
        help_text='店长默认勾选；也可事后在列表里改',
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'password1', 'password2')

    def __init__(self, *args, seller_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.seller_id = seller_id
        self.fields['username'].label = '员工用户名'
        self.fields['username'].help_text = '只在本店不能重复；别的店可以用同名'

    def clean_username(self):
        from .staff_account_helpers import STAFF_USERNAME_SEP, staff_username_taken

        name = (self.cleaned_data.get('username') or '').strip()
        if not name:
            raise forms.ValidationError('请输入用户名')
        if STAFF_USERNAME_SEP in name:
            raise forms.ValidationError('用户名不能包含 ::')
        if not self.seller_id:
            raise forms.ValidationError('店铺信息无效')
        if staff_username_taken(self.seller_id, name):
            raise forms.ValidationError('本店已有该员工用户名')
        return name

    def save(self, commit=True):
        from .staff_account_helpers import staff_internal_username

        user = super().save(commit=False)
        user.username = staff_internal_username(self.seller_id, self.cleaned_data['username'])
        user.role = 'manager'
        user.employer_seller_id = self.seller_id
        user.perm_cancel_order = bool(self.cleaned_data.get('perm_cancel_order'))
        if commit:
            user.save()
            from .experience_helpers import inherit_experience_from_employer
            inherit_experience_from_employer(user, self.seller_id)
        return user


class ShopDeliverySettingsForm(forms.ModelForm):
    """店铺配送费配置表单"""

    class Meta:
        model = ShopDeliverySettings
        fields = [
            'min_delivery_fee',
            'per_km_rate_0_3',
            'multiplier_3_6',
            'multiplier_6_9',
            'max_distance_km',
            'free_delivery_threshold',
            'discount_percent',
        ]
        labels = {
            'min_delivery_fee': '最低配送费（元）',
            'per_km_rate_0_3': '3公里内单价（元/公里）',
            'multiplier_3_6': '3～6公里倍数',
            'multiplier_6_9': '6～9公里倍数',
            'max_distance_km': '最远配送距离（公里）',
            'free_delivery_threshold': '满额免运门槛（元，可留空）',
            'discount_percent': '按订单金额减免上限（%）',
        }


class ShopPaymentSettingsForm(forms.ModelForm):
    """店铺支付配置表单"""

    class Meta:
        model = ShopPaymentSettings
        fields = [
            'enable_simulate',
            'enable_wechat',
            'enable_cash',
            'enable_cod',
            'wechat_mch_id',
            'wechat_app_id',
            'wechat_api_key',
            'public_site_url',
        ]
        labels = {
            'enable_simulate': '开启模拟支付（演示，不扣真钱）',
            'enable_wechat': '开启微信支付（真扣款）',
            'enable_cash': '开启现金支付',
            'enable_cod': '允许外卖现金货到付款',
            'wechat_mch_id': '微信商户号',
            'wechat_app_id': '微信 AppID',
            'wechat_api_key': '微信 APIv2 密钥',
            'public_site_url': '店铺公网网址（如 https://你的域名.com）',
        }
        widgets = {
            'wechat_api_key': forms.PasswordInput(render_value=True),
            'public_site_url': forms.URLInput(attrs={'placeholder': 'https://'}),
        }
        help_texts = {
            'public_site_url': '用于微信自动通知；未部署公网时可留空，买家扫码页将自动轮询查单。',
            'enable_simulate': '正式上线前请关闭，避免顾客误用演示支付。',
            'enable_cod': '开启后，外卖顾客可选「现金货到付款」：店家先备货派单，骑手送达时收现金。关闭则外卖不显示现金。',
        }

    def clean(self):
        cleaned = super().clean()
        from .experience_helpers import seller_blocked_from_real_wechat

        seller_id = getattr(self.instance, 'seller_id', '') or ''
        if cleaned.get('enable_wechat') and seller_blocked_from_real_wechat(seller_id):
            raise forms.ValidationError(
                '体验店铺无法开通真实微信支付。请使用模拟支付体验流程；真付请到官方小店。'
            )
        return cleaned


class ShopStatusSettingsForm(forms.ModelForm):
    """营业状态（主体）：只设全天营业时间；营业中/停止用页面按钮切换。"""

    class Meta:
        model = ShopOperatingSettings
        fields = [
            'business_open', 'business_close',
        ]
        widgets = {
            'business_open': forms.TimeInput(attrs={'type': 'time'}),
            'business_close': forms.TimeInput(attrs={'type': 'time'}),
        }
        labels = {
            'business_open': '全天营业开始',
            'business_close': '全天营业结束',
        }
        help_texts = {
            'business_open': '各业态通用的全天营业窗。',
            'business_close': '到点后按规则不再接新单（仍可用下方按钮停止营业）。',
        }


class ShopOperatingSettingsForm(forms.ModelForm):
    """饮食插件：通道开关、分时段、等待、拼桌、桌码局域网等"""

    acknowledge_table_rules = forms.BooleanField(
        required=False, label='已阅读并理解「桌码主单」硬规则',
    )
    confirm_share_rules = forms.BooleanField(
        required=False, label='已阅读并理解拼桌硬规则（开启拼桌时必填）',
    )
    # 桌码局域网地址：界面拆成四段数字 / 固定名字，最终写入 table_lan_base_url
    lan_mode = forms.ChoiceField(
        required=False,
        choices=[
            ('ip', '四段数字地址（推荐）'),
            ('name', '店内固定名字（高级）'),
        ],
        initial='ip',
        label='桌码局域网地址填写方式',
    )
    lan_ip1 = forms.CharField(required=False, max_length=3, label='地址第1段')
    lan_ip2 = forms.CharField(required=False, max_length=3, label='地址第2段')
    lan_ip3 = forms.CharField(required=False, max_length=3, label='地址第3段')
    lan_ip4 = forms.CharField(required=False, max_length=3, label='地址第4段')
    lan_port = forms.CharField(required=False, max_length=5, label='端口', initial='8000')
    lan_hostname = forms.CharField(required=False, max_length=200, label='店内固定名字')

    class Meta:
        model = ShopOperatingSettings
        fields = [
            'dine_channel_enabled', 'takeaway_channel_enabled', 'delivery_channel_enabled',
            'dine_open', 'dine_close',
            'delivery_open', 'delivery_close',
            'dine_default_wait_minutes', 'takeaway_default_wait_minutes',
            'delivery_default_wait_minutes',
            'share_table_enabled', 'share_table_mode',
            'restrict_same_device',
            'table_lan_base_url',
        ]
        widgets = {
            'dine_open': forms.TimeInput(attrs={'type': 'time'}),
            'dine_close': forms.TimeInput(attrs={'type': 'time'}),
            'delivery_open': forms.TimeInput(attrs={'type': 'time'}),
            'delivery_close': forms.TimeInput(attrs={'type': 'time'}),
            # 由四段数字/固定名字拼装，页面不直接展示
            'table_lan_base_url': forms.HiddenInput(),
        }
        labels = {
            'dine_channel_enabled': '当前允许堂食接单（扫桌码等现场入口）',
            'takeaway_channel_enabled': '当前允许打包接单',
            'delivery_channel_enabled': '当前允许外卖接单',
            'dine_open': '堂食接单开始（可留空；打包暂共用此时段）',
            'dine_close': '堂食接单结束（可留空）',
            'delivery_open': '外卖接单开始（可留空）',
            'delivery_close': '外卖接单结束（可留空）',
            'dine_default_wait_minutes': '堂食普通默认等待时间（分钟）',
            'takeaway_default_wait_minutes': '打包普通默认等待时间（分钟）',
            'delivery_default_wait_minutes': '外卖普通默认等待时间（分钟）',
            'share_table_enabled': '开启拼桌功能',
            'share_table_mode': '拼桌模式（二选一）',
            'restrict_same_device': '同桌仅允许同一台手机下单',
            'table_lan_base_url': '桌码局域网固定地址',
        }
        help_texts = {
            'dine_default_wait_minutes': '没有匹配分时段规则时使用。',
            'takeaway_default_wait_minutes': '没有匹配分时段规则时使用。',
            'delivery_default_wait_minutes': '没有匹配分时段规则时使用。',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .operating_helpers import parse_table_lan_url

        for name in ('lan_ip1', 'lan_ip2', 'lan_ip3', 'lan_ip4'):
            self.fields[name].widget.attrs.update({
                'inputmode': 'numeric',
                'pattern': '[0-9]*',
                'maxlength': '3',
                'class': 'lan-ip-octet',
                'autocomplete': 'off',
            })
        self.fields['lan_port'].widget.attrs.update({
            'inputmode': 'numeric',
            'pattern': '[0-9]*',
            'maxlength': '5',
            'class': 'lan-port-input',
            'autocomplete': 'off',
        })
        self.fields['lan_hostname'].widget.attrs.update({
            'placeholder': '例如 yecao.local',
            'class': 'lan-hostname-input',
            'autocomplete': 'off',
        })

        # 回显：已保存地址拆开填入各框（仅初始展示；有 POST 时用 POST）
        if not self.is_bound:
            parsed = parse_table_lan_url(getattr(self.instance, 'table_lan_base_url', '') or '')
            self.fields['lan_mode'].initial = parsed['mode']
            self.fields['lan_ip1'].initial = parsed['ip1']
            self.fields['lan_ip2'].initial = parsed['ip2']
            self.fields['lan_ip3'].initial = parsed['ip3']
            self.fields['lan_ip4'].initial = parsed['ip4']
            self.fields['lan_port'].initial = parsed['port'] or '8000'
            self.fields['lan_hostname'].initial = parsed['hostname']

    def clean(self):
        from .operating_helpers import assemble_table_lan_url

        cleaned = super().clean()
        for field in (
            'dine_default_wait_minutes',
            'takeaway_default_wait_minutes',
            'delivery_default_wait_minutes',
        ):
            value = cleaned.get(field)
            if value is not None and (value < 1 or value > 240):
                self.add_error(field, '请填写 1～240 分钟')

        url, err = assemble_table_lan_url(
            mode=cleaned.get('lan_mode') or 'ip',
            ip1=cleaned.get('lan_ip1') or '',
            ip2=cleaned.get('lan_ip2') or '',
            ip3=cleaned.get('lan_ip3') or '',
            ip4=cleaned.get('lan_ip4') or '',
            port=cleaned.get('lan_port') or '',
            hostname=cleaned.get('lan_hostname') or '',
        )
        if err:
            mode = cleaned.get('lan_mode') or 'ip'
            if mode == 'name':
                self.add_error('lan_hostname', err)
            else:
                self.add_error('lan_ip1', err)
        cleaned['table_lan_base_url'] = url
        return cleaned


class ShopWorkbenchSettingsForm(forms.ModelForm):
    """员工工作台协作设置（在「员工工作台管理」页维护）"""

    class Meta:
        model = ShopOperatingSettings
        fields = [
            'delivery_handoff_mode', 'auto_dispatch_enabled', 'attendance_retention_days',
            'alert_volume', 'alert_interval_sec', 'alert_sound',
            'order_notify_enabled', 'order_notify_email',
        ]
        labels = {
            'delivery_handoff_mode': '外卖交接方式',
            'auto_dispatch_enabled': '开启自动派单',
            'attendance_retention_days': '考勤记录保留时长',
            'alert_volume': '新单提醒音量（0～100）',
            'alert_interval_sec': '新单提醒重复间隔（秒）',
            'alert_sound': '自定义提醒音频（可留空）',
            'order_notify_enabled': '开启新订单邮件通知',
            'order_notify_email': '新订单通知收件邮箱（多个用逗号分隔）',
        }
        help_texts = {
            'delivery_handoff_mode': '外卖备好后由谁交给骑手：默认服务员交接；可选后厨直交骑手。',
            'auto_dispatch_enabled': '开启后，订单进入可派单阶段时会自动分给当前上班中的本店骑手；关闭后需人工派单。',
            'attendance_retention_days': '超过保留期的旧考勤记录可后续清理；当前先按这个规则展示与导出。',
            'alert_volume': '工作台/后厨页面开着时，新单提醒响铃的音量。',
            'alert_interval_sec': '有新单未处理时，每隔多少秒再响一次（最少 3 秒）。',
            'alert_sound': '可上传自己的提示音（MP3/WAV/OGG，最大 2MB）；留空则用系统默认提示音。',
            'order_notify_enabled': '开启后，有新订单时给下面的邮箱发一封提醒邮件（需服务器已配置发信邮箱才会真的发出）。',
            'order_notify_email': '可填多个邮箱，用逗号分隔，例如：a@qq.com, b@163.com。',
        }

    def clean_order_notify_email(self):
        raw = (self.cleaned_data.get('order_notify_email') or '').strip()
        if not raw:
            return ''
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError as DjangoValidationError

        emails = [e.strip() for e in raw.replace('；', ',').replace(';', ',').replace(' ', ',').split(',') if e.strip()]
        for e in emails:
            try:
                validate_email(e)
            except DjangoValidationError:
                raise forms.ValidationError(f'邮箱格式不对：{e}')
        return ', '.join(emails)

    def clean_alert_volume(self):
        vol = self.cleaned_data.get('alert_volume')
        if vol is None:
            return 60
        if vol > 100:
            vol = 100
        return vol

    def clean_alert_interval_sec(self):
        sec = self.cleaned_data.get('alert_interval_sec')
        if sec is None or sec < 3:
            return 3
        if sec > 120:
            return 120
        return sec

    def clean_alert_sound(self):
        f = self.cleaned_data.get('alert_sound')
        # 只有新上传的文件才有 content_type / size；已存的旧文件直接放行
        if f and hasattr(f, 'content_type'):
            if getattr(f, 'size', 0) > 2 * 1024 * 1024:
                raise forms.ValidationError('音频文件不能超过 2MB')
            name = (getattr(f, 'name', '') or '').lower()
            if not name.endswith(('.mp3', '.wav', '.ogg', '.m4a')):
                raise forms.ValidationError('只支持 MP3 / WAV / OGG / M4A 格式的音频')
        return f
