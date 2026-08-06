# 幂等第 10 步：留言板 Ajax 新建主题防重复

from django.test import Client, TestCase

from waimai.guestbook_models import GuestbookThread


class GuestbookPostIdempotencyTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.post_url = '/guestbook/post/'
        self.json_headers = {
            'HTTP_X_YC_GUESTBOOK': '1',
            'HTTP_ACCEPT': 'application/json',
        }

    def _post_payload(self, body: str, key: str = ''):
        data = {
            'body': body,
            'guest_name': '幂等测试访客',
            'guest_email': '',
        }
        if key:
            data['idempotency_key'] = key
        return data

    def test_same_key_post_creates_one_thread(self):
        key = 'gb-post-key-00000001'
        body = '幂等键重复提交测试留言内容'
        payload = self._post_payload(body, key)

        resp1 = self.client.post(self.post_url, payload, **self.json_headers)
        resp2 = self.client.post(self.post_url, payload, **self.json_headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        data1 = resp1.json()
        data2 = resp2.json()
        self.assertTrue(data1.get('ok'))
        self.assertTrue(data2.get('ok'))
        self.assertEqual(data1.get('public_code'), data2.get('public_code'))
        self.assertEqual(GuestbookThread.objects.count(), 1)

    def test_same_key_replays_first_response_even_if_body_differs(self):
        key = 'gb-post-key-00000002'
        payload1 = self._post_payload('第一次留言正文内容', key)
        payload2 = self._post_payload('第二次不同正文不应新建', key)

        resp1 = self.client.post(self.post_url, payload1, **self.json_headers)
        resp2 = self.client.post(self.post_url, payload2, **self.json_headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.json()['public_code'], resp2.json()['public_code'])
        self.assertEqual(GuestbookThread.objects.count(), 1)
