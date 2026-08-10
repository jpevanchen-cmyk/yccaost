# 幂等第 6 步：现金管理 Panel 防重复入账/确认

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .time_helpers import now_local_wall

from waimai.models import BuyOrder
from waimai.panel_refresh_helpers import PANEL_REQUEST_HEADER
from waimai.rider_cash_helpers import create_cash_remittance_request
from waimai.shop_work_auth import establish_shop_work_session
from waimai.staff_account_helpers import PERM_FULFILLMENT_CASH_MANAGE
from waimai.test_shop_helpers import create_test_shop_bundle

User = get_user_model()


class CashManageIdempotencyTests(TestCase):
    def setUp(self):
        bundle = create_test_shop_bundle(
            username='cm_idem_seller',
            shop_code='cmidem',
            shop_name='现金幂等店',
        )
        self.seller = bundle.seller
        self.manager = User.objects.create_user(
            username='cm_idem_mgr',
            password='pass12345',
            role='manager',
            employer_seller_id=self.seller.username,
            staff_permissions=[PERM_FULFILLMENT_CASH_MANAGE],
        )
        now = now_local_wall()
        BuyOrder.objects.create(
            buyer_id='buyer_remit',
            seller_id=self.seller.username,
            total_amount=Decimal('40.00'),
            subtotal_amount=Decimal('40.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by='rider1',
            cash_collected_amount=Decimal('40.00'),
        )
        self.remit, _ = create_cash_remittance_request(
            self.seller.username, 'rider1',
        )
        self.assertIsNotNone(self.remit)
        self.client = Client()
        self.panel_headers = {'HTTP_X_REQUESTED_WITH': PANEL_REQUEST_HEADER}

    def _make_pending_remit(self, rider_id: str, buyer_id: str):
        """再建一笔可交款订单并生成待确认入金申请。"""
        now = now_local_wall()
        BuyOrder.objects.create(
            buyer_id=buyer_id,
            seller_id=self.seller.username,
            total_amount=Decimal('25.00'),
            subtotal_amount=Decimal('25.00'),
            delivery_fee=Decimal('0'),
            dish_items=[],
            payment_status='paid',
            order_status='completed',
            fulfillment_type='delivery',
            payment_method='cash',
            cash_collected_at=now,
            cash_collected_by=rider_id,
            cash_collected_amount=Decimal('25.00'),
        )
        remit, msg = create_cash_remittance_request(self.seller.username, rider_id)
        self.assertIsNotNone(remit, msg)
        return remit

    def _workbench_session(self):
        session = self.client.session
        establish_shop_work_session(
            type('Req', (), {'session': session})(),
            self.manager,
            seller_id=self.seller.username,
            shop_code='cmidem',
        )
        session.save()

    def test_workbench_same_key_confirm_remittance_once(self):
        self._workbench_session()
        url = reverse('shop_work', kwargs={'shop_code': 'cmidem'}) + '?view=cash_manage'
        payload = {
            'cash_manage_action': 'confirm_remittance',
            'request_id': str(self.remit.request_id),
            'idempotency_key': 'cm-remit-key-00000001',
        }
        resp1 = self.client.post(url, payload, **self.panel_headers)
        resp2 = self.client.post(url, payload, **self.panel_headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.content, resp2.content)
        self.remit.refresh_from_db()
        self.assertEqual(self.remit.status, 'confirmed')

    def test_seller_same_key_confirm_remittance_once(self):
        self.client.force_login(self.seller)
        url = reverse('seller_panel_section', kwargs={'section': 'cash_manage'})
        remit2 = self._make_pending_remit('rider2', 'buyer_seller2')
        payload = {
            'cash_manage_action': 'confirm_remittance',
            'request_id': str(remit2.request_id),
            'idempotency_key': 'cm-seller-key-0000001',
        }
        self.client.post(url, payload, **self.panel_headers)
        self.client.post(url, payload, **self.panel_headers)
        remit2.refresh_from_db()
        self.assertEqual(remit2.status, 'confirmed')

    def test_without_key_double_confirm_second_fails_gracefully(self):
        """无编号连点：第二笔可能已被第一笔确认，须返回失败 JSON 而非重复入账。"""
        self._workbench_session()
        remit3 = self._make_pending_remit('rider3', 'buyer_wb3')
        url = reverse('shop_work', kwargs={'shop_code': 'cmidem'}) + '?view=cash_manage'
        payload = {
            'cash_manage_action': 'confirm_remittance',
            'request_id': str(remit3.request_id),
        }
        resp1 = self.client.post(url, payload, **self.panel_headers)
        resp2 = self.client.post(url, payload, **self.panel_headers)
        self.assertEqual(resp1.status_code, 200)
        self.assertTrue(resp1.json()['ok'])
        remit3.refresh_from_db()
        self.assertEqual(remit3.status, 'confirmed')
        self.assertEqual(resp2.status_code, 400)
