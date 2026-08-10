# 操作留痕页 + 服务器排错日志

from django.test import TestCase
from django.urls import reverse

from waimai.audit_helpers import (
    build_seller_audit_querystring,
    build_tech_log_querystring,
    filter_log_lines,
    parse_audit_view_params,
    parse_tech_log_view_params,
    query_audit_logs,
    write_audit_log,
)
from waimai.owner_helpers import user_is_server_manager
from waimai.test_shop_helpers import create_logged_in_seller_client, create_test_shop_bundle


class AuditViewHelperTests(TestCase):
    def test_parse_audit_view_params_defaults(self):
        params = parse_audit_view_params({})
        self.assertEqual(params['view'], 'audit')
        self.assertEqual(params['scope'], 'all')

    def test_build_seller_audit_querystring(self):
        qs = build_seller_audit_querystring(scope='mine', q='登录')
        self.assertIn('scope=mine', qs)
        self.assertIn('q=', qs)

    def test_parse_tech_log_view_params(self):
        params = parse_tech_log_view_params({'view': 'tech_error', 'q': 'error'})
        self.assertEqual(params['view'], 'tech_error')
        self.assertEqual(params['q'], 'error')

    def test_build_tech_log_querystring(self):
        qs = build_tech_log_querystring(view='tech_error', q='pay')
        self.assertIn('view=tech_error', qs)

    def test_filter_log_lines(self):
        lines = ['ERROR foo', 'INFO bar', 'ERROR baz']
        self.assertEqual(filter_log_lines(lines, 'error'), ['ERROR foo', 'ERROR baz'])


class SellerAuditPageTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='audit_only_seller')
        self.seller_id = self.bundle.seller.username
        self.client = create_logged_in_seller_client(self.bundle)
        write_audit_log(
            action_code='login',
            summary='测试登录成功留痕',
            seller_id=self.seller_id,
            actor=self.bundle.seller,
        )

    def test_audit_page_no_tech_log_tabs(self):
        url = reverse('seller_panel_section', kwargs={'section': 'audit'})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '操作留痕')
        self.assertNotContains(resp, '普通技术日志')
        self.assertNotContains(resp, '错误与支付日志')
        self.assertNotContains(resp, '程序运行记录')

    def test_audit_search_finds_summary(self):
        url = reverse('seller_panel_section', kwargs={'section': 'audit'})
        resp = self.client.get(url, {'q': '登录成功'})
        self.assertContains(resp, '测试登录成功留痕')

    def test_query_audit_logs_keyword(self):
        qs = query_audit_logs(
            seller_id=self.seller_id,
            keyword='登录成功',
        )
        summaries = [log.summary for log in qs]
        self.assertTrue(any('登录成功' in s for s in summaries))


class ServerTechLogsPageTests(TestCase):
    def setUp(self):
        self.bundle = create_test_shop_bundle(username='tech_log_mgr')
        self.user = self.bundle.seller
        self.user.is_server_owner = True
        self.user.save(update_fields=['is_server_owner'])
        self.client = create_logged_in_seller_client(self.bundle)
        self.assertTrue(user_is_server_manager(self.user))

    def test_manager_can_open_server_tech_logs(self):
        url = reverse('server_settings_tech_logs')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '系统排错日志')
        self.assertContains(resp, '程序运行记录')

    def test_non_manager_blocked(self):
        self.user.is_server_owner = False
        self.user.save(update_fields=['is_server_owner'])
        url = reverse('server_settings_tech_logs')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
