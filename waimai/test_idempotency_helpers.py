# 幂等第 1 步：公共零件自动测试

import json

from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from waimai.idempotency_helpers import (
    IDEMPOTENCY_HEADER,
    extract_idempotency_key,
    idempotency_scope,
    run_idempotent,
)
from waimai.models import IdempotencyRecord


class IdempotencyHelpersTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.scope = idempotency_scope('test', 'demo')
        self.key = 'test-key-12345678'

    def _post(self, *, key: str = ''):
        req = self.factory.post('/test/', {'foo': '1'})
        if key:
            req.META[f'HTTP_{IDEMPOTENCY_HEADER.upper().replace("-", "_")}'] = key
        return req

    def test_extract_key_from_header(self):
        req = self._post(key=self.key)
        self.assertEqual(extract_idempotency_key(req), self.key)

    def test_extract_key_from_form_field(self):
        req = self.factory.post('/test/', {'idempotency_key': self.key})
        self.assertEqual(extract_idempotency_key(req), self.key)

    def test_invalid_key_returns_empty(self):
        req = self._post(key='短')
        self.assertEqual(extract_idempotency_key(req), '')

    def test_without_key_runs_execute_each_time(self):
        counter = {'n': 0}

        def execute():
            counter['n'] += 1
            return JsonResponse({'ok': True, 'n': counter['n']})

        run_idempotent(self.factory.post('/test/'), self.scope, execute)
        run_idempotent(self.factory.post('/test/'), self.scope, execute)
        self.assertEqual(counter['n'], 2)

    def test_same_key_runs_execute_once_and_replays(self):
        counter = {'n': 0}

        def execute():
            counter['n'] += 1
            return JsonResponse({'ok': True, 'n': counter['n']})

        req1 = self._post(key=self.key)
        req2 = self._post(key=self.key)

        resp1 = run_idempotent(req1, self.scope, execute)
        resp2 = run_idempotent(req2, self.scope, execute)

        self.assertEqual(counter['n'], 1)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        body1 = json.loads(resp1.content.decode())
        body2 = json.loads(resp2.content.decode())
        self.assertEqual(body1, {'ok': True, 'n': 1})
        self.assertEqual(body2, body1)
        self.assertEqual(
            IdempotencyRecord.objects.filter(
                scope=self.scope, idempotency_key=self.key, state='completed',
            ).count(),
            1,
        )

    def test_redirect_response_replays_location(self):
        from django.http import HttpResponseRedirect

        counter = {'n': 0}

        def execute():
            counter['n'] += 1
            return HttpResponseRedirect('/pay/demo/')

        req1 = self._post(key=self.key)
        req2 = self._post(key=self.key)
        resp1 = run_idempotent(req1, self.scope, execute)
        resp2 = run_idempotent(req2, self.scope, execute)

        self.assertEqual(counter['n'], 1)
        self.assertEqual(resp1.status_code, 302)
        self.assertEqual(resp2.status_code, 302)
        self.assertEqual(resp1['Location'], '/pay/demo/')
        self.assertEqual(resp2['Location'], '/pay/demo/')

    def test_different_scopes_same_key_both_execute(self):
        counter = {'n': 0}

        def execute():
            counter['n'] += 1
            return JsonResponse({'ok': True, 'n': counter['n']})

        req = self._post(key=self.key)
        run_idempotent(req, idempotency_scope('a'), execute)
        run_idempotent(req, idempotency_scope('b'), execute)
        self.assertEqual(counter['n'], 2)
