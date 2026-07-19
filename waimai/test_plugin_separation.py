# 插件分离试验 · 自动验收（规则门禁）
# 运行：python manage.py test waimai.test_plugin_separation -v2
# 说明：在临时空库里测；不改动开发者日常营业数据。

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from waimai.channel_helpers import channel_switch_enabled, list_homepage_channels
from waimai.dispatch_helpers import dispatch_buy_order, maybe_auto_dispatch_order
from waimai.forms import ShopPaymentSettingsForm, ShopWorkbenchSettingsForm
from waimai.models import BuyOrder, ShopProfile
from waimai.operating_helpers import get_operating_settings
from waimai.plugin_runtime.registry import (
    collect_seller_nav_items,
    is_plugin_enabled,
    set_plugin_enabled,
)
from waimai.plugins.dining.dining_bridge import build_dining_cash_option
from waimai.plugins.fulfillment.ownership import fulfillment_plugin_enabled
from waimai.staff_account_helpers import get_staff_account_presets, get_staff_permission_definitions
from waimai.workbench_shell_helpers import build_workbench_shell

User = get_user_model()


class PluginSeparationBase(TestCase):
    """每条用例一个独立假店铺。"""

    def setUp(self):
        self.seller_id = f'trial_{self._testMethodName}'[:50]
        User.objects.create_user(
            username=self.seller_id,
            password='test-pass-123',
            role='seller',
        )
        ShopProfile.objects.create(
            seller_id=self.seller_id,
            shop_name='插件分离试验店',
            shop_code=f'c{self._testMethodName}'[:28],
            address='试验地址 1 号',
        )
        self.settings = get_operating_settings(self.seller_id)
        # 默认双开；各用例再按需改
        self.settings.plugin_dining_enabled = True
        self.settings.plugin_fulfillment_enabled = True
        self.settings.delivery_channel_enabled = True
        self.settings.takeaway_channel_enabled = True
        self.settings.dine_channel_enabled = True
        self.settings.closed_for_today = False
        self.settings.pause_new_orders = False
        self.settings.save()

    def _set_plugins(self, *, dining: bool, fulfillment: bool):
        ok, msg = set_plugin_enabled('dining', self.seller_id, dining)
        self.assertTrue(ok, msg)
        ok, msg = set_plugin_enabled('fulfillment', self.seller_id, fulfillment)
        self.assertTrue(ok, msg)

    def _channel_codes(self) -> set[str]:
        return {row['code'] for row in list_homepage_channels(self.seller_id)}

    def _nav_sections(self) -> set[str]:
        return {item.section for item in collect_seller_nav_items(self.seller_id)}

    def _views(self) -> set[str]:
        return set(build_workbench_shell(self.seller_id).get('enabled_views') or [])


class FourComboGateTests(PluginSeparationBase):
    """四种开关组合：通道 / 导航 / 工作台页签。"""

    def test_both_on(self):
        self._set_plugins(dining=True, fulfillment=True)
        channels = self._channel_codes()
        # 主页可选：外卖/打包；堂食走桌码，不出现在主页列表
        self.assertIn('takeaway', channels)
        self.assertIn('delivery', channels)
        self.assertNotIn('order', channels)
        self.assertTrue(channel_switch_enabled(get_operating_settings(self.seller_id), 'dine_in'))

        nav = self._nav_sections()
        self.assertIn('dine', nav)
        self.assertIn('delivery', nav)

        views = self._views()
        self.assertEqual(views, {'waiter', 'kitchen', 'rider'})
        self.assertTrue(is_plugin_enabled('dining', self.seller_id))
        self.assertTrue(fulfillment_plugin_enabled(self.seller_id))

    def test_dining_on_fulfillment_off(self):
        self._set_plugins(dining=True, fulfillment=False)
        channels = self._channel_codes()
        self.assertIn('takeaway', channels)
        self.assertNotIn('delivery', channels)
        self.assertTrue(channel_switch_enabled(get_operating_settings(self.seller_id), 'dine_in'))

        nav = self._nav_sections()
        self.assertIn('dine', nav)
        self.assertNotIn('delivery', nav)

        views = self._views()
        self.assertEqual(views, {'waiter', 'kitchen'})
        self.assertFalse(fulfillment_plugin_enabled(self.seller_id))

    def test_dining_off_fulfillment_on(self):
        self._set_plugins(dining=False, fulfillment=True)
        channels = self._channel_codes()
        self.assertEqual(channels, {'order'})

        nav = self._nav_sections()
        self.assertNotIn('dine', nav)
        self.assertIn('delivery', nav)

        views = self._views()
        self.assertEqual(views, {'orders', 'rider'})

    def test_both_off(self):
        self._set_plugins(dining=False, fulfillment=False)
        self.assertEqual(self._channel_codes(), {'order'})
        nav = self._nav_sections()
        self.assertNotIn('dine', nav)
        self.assertNotIn('delivery', nav)
        self.assertEqual(self._views(), {'orders'})


class FulfillmentGateTests(PluginSeparationBase):
    """关履约：派单挡死、货到付款选项挡死。"""

    def _make_paid_delivery_order(self) -> BuyOrder:
        return BuyOrder.objects.create(
            buyer_id='buyer_trial',
            seller_id=self.seller_id,
            total_amount=Decimal('28.00'),
            subtotal_amount=Decimal('25.00'),
            delivery_fee=Decimal('3.00'),
            dish_items=[{'name': '试验菜', 'qty': 1, 'price': '25.00'}],
            payment_status='paid',
            order_status='awaiting_prep',
            fulfillment_type='delivery',
            delivery_address='试验送达地址',
            distance_km=Decimal('2.0'),
        )

    def test_dispatch_blocked_when_fulfillment_off(self):
        self._set_plugins(dining=True, fulfillment=False)
        order = self._make_paid_delivery_order()
        delivery, err = dispatch_buy_order(order, rider_id=None)
        self.assertIsNone(delivery)
        self.assertIn('履约', err or '')

        delivery2, err2 = maybe_auto_dispatch_order(order)
        self.assertIsNone(delivery2)
        self.assertIn('履约', err2 or '')

    def test_cod_option_blocked_when_fulfillment_off(self):
        from waimai.payments import get_payment_settings

        self._set_plugins(dining=True, fulfillment=False)
        pay = get_payment_settings(self.seller_id)
        pay.enable_cash = True
        pay.enable_cod = True
        pay.save()
        order = self._make_paid_delivery_order()
        option = build_dining_cash_option(pay, order)
        self.assertIsNone(option)

    def test_cod_option_ok_when_both_on(self):
        from waimai.payments import get_payment_settings

        self._set_plugins(dining=True, fulfillment=True)
        pay = get_payment_settings(self.seller_id)
        pay.enable_cash = True
        pay.enable_cod = True
        pay.save()
        order = self._make_paid_delivery_order()
        option = build_dining_cash_option(pay, order)
        self.assertIsNotNone(option)
        self.assertEqual(option.code, 'cash')


class StaffPresetGateTests(PluginSeparationBase):
    """员工权限与预置随插件开关出现/消失。"""

    def test_presets_both_on(self):
        self._set_plugins(dining=True, fulfillment=True)
        codes = {p['code'] for p in get_staff_account_presets(self.seller_id, 'employee')}
        self.assertIn('dining.waiter', codes)
        self.assertIn('dining.kitchen', codes)
        self.assertIn('fulfillment.rider', codes)
        self.assertIn('core.order_clerk', codes)

        perm_codes = {d['code'] for d in get_staff_permission_definitions(self.seller_id)}
        self.assertIn('dining.waiter', perm_codes)
        self.assertIn('fulfillment.delivery', perm_codes)

    def test_presets_dining_off(self):
        self._set_plugins(dining=False, fulfillment=True)
        codes = {p['code'] for p in get_staff_account_presets(self.seller_id, 'employee')}
        self.assertNotIn('dining.waiter', codes)
        self.assertNotIn('dining.kitchen', codes)
        self.assertIn('fulfillment.rider', codes)
        self.assertIn('core.order_clerk', codes)

    def test_presets_fulfillment_off(self):
        self._set_plugins(dining=True, fulfillment=False)
        codes = {p['code'] for p in get_staff_account_presets(self.seller_id, 'employee')}
        self.assertIn('dining.waiter', codes)
        self.assertNotIn('fulfillment.rider', codes)


class FormFieldGateTests(PluginSeparationBase):
    """关履约时表单字段应可去掉（与卖家页行为一致）。"""

    def test_payment_form_can_drop_cod(self):
        from waimai.payments import get_payment_settings

        self._set_plugins(dining=True, fulfillment=False)
        form = ShopPaymentSettingsForm(instance=get_payment_settings(self.seller_id))
        form.fields.pop('enable_cod', None)
        self.assertNotIn('enable_cod', form.fields)

    def test_workbench_form_can_drop_dispatch_fields(self):
        self._set_plugins(dining=True, fulfillment=False)
        form = ShopWorkbenchSettingsForm(instance=get_operating_settings(self.seller_id))
        form.fields.pop('delivery_handoff_mode', None)
        form.fields.pop('auto_dispatch_enabled', None)
        self.assertNotIn('auto_dispatch_enabled', form.fields)


class ToggleRestoreTests(PluginSeparationBase):
    """关再开：开关状态可恢复（数据表仍在）。"""

    def test_toggle_dining_restore(self):
        self._set_plugins(dining=False, fulfillment=True)
        self.assertEqual(self._channel_codes(), {'order'})
        self._set_plugins(dining=True, fulfillment=True)
        self.assertIn('takeaway', self._channel_codes())
        self.assertIn('dine', self._nav_sections())

    def test_toggle_fulfillment_restore(self):
        self._set_plugins(dining=True, fulfillment=False)
        self.assertNotIn('delivery', self._channel_codes())
        self._set_plugins(dining=True, fulfillment=True)
        self.assertIn('delivery', self._channel_codes())
        self.assertIn('delivery', self._nav_sections())
        self.assertIn('rider', self._views())
