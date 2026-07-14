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
            from .home_page_helpers import ensure_home_page_for_seller, set_server_entry
            from .models import ShopHomePage
            ensure_home_page_for_seller(user.username, profile)
            if not ShopHomePage.objects.filter(is_server_entry=True).exists():
                set_server_entry(user.username)
        return user


class CreateRiderForm(UserCreationForm):
    """卖家为本店创建专属骑手账号（工牌名仅本店唯一）"""

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
        if commit:
            user.save()
            from .experience_helpers import inherit_experience_from_employer
            inherit_experience_from_employer(user, self.seller_id)
        return user


class CreateWaiterForm(UserCreationForm):
    """卖家为本店创建服务员子账号（工牌名仅本店唯一）"""

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
        if commit:
            user.save()
            from .experience_helpers import inherit_experience_from_employer
            inherit_experience_from_employer(user, self.seller_id)
        return user


class CreateKitchenForm(UserCreationForm):
    """卖家为本店创建后厨子账号（工牌名仅本店唯一）"""

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
            'is_showcase_shop',
            'wechat_mch_id',
            'wechat_app_id',
            'wechat_api_key',
            'public_site_url',
        ]
        labels = {
            'enable_simulate': '开启模拟支付（演示，不扣真钱）',
            'enable_wechat': '开启微信支付（真扣款）',
            'enable_cash': '开启现金支付',
            'is_showcase_shop': '示范店模式（可同时开模拟+真微信供体验）',
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


class ShopOperatingSettingsForm(forms.ModelForm):
    """堂食营业与拼桌设置"""

    acknowledge_table_rules = forms.BooleanField(
        required=False, label='已阅读并理解「桌码主单」硬规则',
    )
    confirm_share_rules = forms.BooleanField(
        required=False, label='已阅读并理解拼桌硬规则（开启拼桌时必填）',
    )

    class Meta:
        model = ShopOperatingSettings
        fields = [
            'business_open', 'business_close',
            'dine_open', 'dine_close',
            'delivery_open', 'delivery_close',
            'dine_channel_enabled', 'delivery_channel_enabled',
            'closed_for_today', 'pause_new_orders',
            'share_table_enabled', 'share_table_mode',
            'restrict_same_device',
        ]
        widgets = {
            'business_open': forms.TimeInput(attrs={'type': 'time'}),
            'business_close': forms.TimeInput(attrs={'type': 'time'}),
            'dine_open': forms.TimeInput(attrs={'type': 'time'}),
            'dine_close': forms.TimeInput(attrs={'type': 'time'}),
            'delivery_open': forms.TimeInput(attrs={'type': 'time'}),
            'delivery_close': forms.TimeInput(attrs={'type': 'time'}),
        }
        labels = {
            'business_open': '全天营业开始',
            'business_close': '全天营业结束',
            'dine_open': '堂食接单开始（可留空）',
            'dine_close': '堂食接单结束（可留空）',
            'delivery_open': '外卖接单开始（可留空）',
            'delivery_close': '外卖接单结束（可留空）',
            'dine_channel_enabled': '当前允许堂食/打包接单',
            'delivery_channel_enabled': '当前允许外卖接单',
            'closed_for_today': '本日打烊',
            'pause_new_orders': '暂停接单',
            'share_table_enabled': '开启拼桌功能',
            'share_table_mode': '拼桌模式（二选一）',
            'restrict_same_device': '同桌仅允许同一台手机下单',
        }


class ShopWorkbenchSettingsForm(forms.ModelForm):
    """员工工作台协作设置（在「员工工作台管理」页维护）"""

    class Meta:
        model = ShopOperatingSettings
        fields = ['delivery_handoff_mode', 'auto_dispatch_enabled', 'attendance_retention_days']
        labels = {
            'delivery_handoff_mode': '外卖交接方式',
            'auto_dispatch_enabled': '开启自动派单',
            'attendance_retention_days': '考勤记录保留时长',
        }
        help_texts = {
            'delivery_handoff_mode': '外卖备好后由谁交给骑手：默认服务员交接；可选后厨直交骑手。',
            'auto_dispatch_enabled': '开启后，订单进入可派单阶段时会自动分给当前上班中的本店骑手；关闭后需人工派单。',
            'attendance_retention_days': '超过保留期的旧考勤记录可后续清理；当前先按这个规则展示与导出。',
        }
