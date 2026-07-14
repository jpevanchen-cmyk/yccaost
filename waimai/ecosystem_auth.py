# 野草生态登录：仅买家、店主可从此门进入

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .shop_work_helpers import SHOP_STAFF_ROLES


class EcosystemAuthenticationForm(AuthenticationForm):
    """生态登录表单：子账号在此门一律视为账号或密码错误"""

    def confirm_login_allowed(self, user):
        # 先走 Django 默认检查（是否激活等）
        super().confirm_login_allowed(user)
        if user.role in SHOP_STAFF_ROLES:
            # 与「未注册野草账号」相同提示，不透露工牌账号存在
            raise forms.ValidationError(
                self.error_messages['invalid_login'],
                code='invalid_login',
                params={'username': self.username_field.verbose_name},
            )
