# -*- coding: utf-8 -*-
"""Exercise the QA HTTP boundary without a model call or production data writes."""
import http.client
import json
import os
import sys
import threading
import types
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import server


class QAHTTPTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            'answer': '观察需要持续记录。[1]',
            'sources': [{'id': 1, 'code': 'B01', 'book': '观察手册',
                         'chapter': '记录', 'anchor': 'B01-01-P01',
                         'quote': '观察需要持续记录。'}],
            'suggestions': [], 'mode': 'answer', 'notice': '',
            'scope': {'book_codes': ['B01'], 'book_count': 1, 'revision': 'source-v1'},
        }
        self.service = types.SimpleNamespace(
            status=Mock(return_value={'books': [{'code': 'B01', 'title': '观察手册', 'segments': 1}],
                                      'book_count': 1, 'segment_count': 1,
                                      'ready': True, 'model_ready': True, 'revision': 'source-v1'}),
            ask=Mock(return_value=self.result),
        )
        self.slots = threading.BoundedSemaphore(1)
        self.patches = [patch.dict(sys.modules, {'qa_service': self.service}),
                        patch.object(server, 'QA_SLOTS', self.slots),
                        patch.object(server, 'AUTH_USER', ''),
                        patch.object(server, '_log'),
                        patch.object(server.traceback, 'print_exc')]
        for item in self.patches:
            item.start()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.worker = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()

    def request(self, method='POST', path='/api/qa/ask', body=None, raw=None, headers=None):
        connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=5)
        try:
            payload = raw if raw is not None else json.dumps(body or {}, ensure_ascii=False).encode('utf-8')
            connection.request(method, path, body=payload if method == 'POST' else None,
                               headers=headers or {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode('utf-8'))
        finally:
            connection.close()

    def test_status_and_answer_preserve_scope_and_source_contract(self):
        status, body = self.request('GET', '/api/qa/status')
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['books'][0]['code'], 'B01')
        question = {'question': '如何观察？', 'book_codes': ['B01'],
                    'history': [{'role': 'user', 'content': '查找记录方法'}]}
        status, body = self.request(body=question)
        self.assertEqual(status, 200)
        self.assertEqual(body, {'ok': True, **self.result})
        self.service.ask.assert_called_once_with(question)

    def test_malformed_json_is_rejected_before_service(self):
        status, body = self.request(raw=b'{"question":')
        self.assertEqual(status, 400)
        self.assertFalse(body['ok'])
        self.service.ask.assert_not_called()

    def test_oversize_payload_is_rejected_before_service(self):
        status, body = self.request(raw=b'{}', headers={'Content-Length': str(2 * 1024 * 1024 + 1)})
        self.assertEqual(status, 400)
        self.assertIn('过大', body['error'])
        self.service.ask.assert_not_called()

    def test_service_validation_returns_400_and_releases_slot(self):
        self.service.ask.side_effect = [ValueError('问题必须是文本'), self.result]
        status, body = self.request(body={'question': ['invalid']})
        self.assertEqual(status, 400)
        self.assertEqual(body['error'], '问题必须是文本')
        status, body = self.request(body={'question': '如何记录？'})
        self.assertEqual(status, 200)
        self.assertEqual(body['answer'], self.result['answer'])

    def test_unexpected_failure_releases_slot(self):
        self.service.ask.side_effect = [RuntimeError('测试失败'), self.result]
        self.assertEqual(self.request(body={'question': '测试'} )[0], 500)
        self.assertEqual(self.request(body={'question': '重试'} )[0], 200)

    def test_inflight_request_limits_concurrency_then_recovers(self):
        entered, release = threading.Event(), threading.Event()
        completed = []

        def answer(_):
            entered.set()
            if not release.wait(4):
                raise RuntimeError('测试没有及时释放请求')
            return self.result

        self.service.ask.side_effect = answer
        worker = threading.Thread(target=lambda: completed.append(
            self.request(body={'question': '第一个问题'})), daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            status, body = self.request(body={'question': '第二个问题'})
            self.assertEqual(status, 429)
            self.assertFalse(body['ok'])
            self.assertEqual(self.service.ask.call_count, 1)
        finally:
            release.set()
            worker.join(timeout=3)
        self.assertEqual(completed[0][0], 200)
        self.assertEqual(self.request(body={'question': '后续问题'})[0], 200)

    def test_authentication_applies_to_both_qa_endpoints(self):
        with patch.object(server, 'AUTH_USER', 'qa-test'), patch.object(server, 'AUTH_PASS', 'test-only'):
            for method, path in [('GET', '/api/qa/status'), ('POST', '/api/qa/ask')]:
                connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=5)
                try:
                    connection.request(method, path, body=b'{}' if method == 'POST' else None)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 401)
                    self.assertIn('Basic', response.getheader('WWW-Authenticate'))
                    response.read()
                finally:
                    connection.close()
        self.service.status.assert_not_called()
        self.service.ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
