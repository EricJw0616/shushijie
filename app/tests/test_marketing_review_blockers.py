"""Batch review blocks without partial writes and identifies actionable source pages."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import assets_service as A
import marketing_state
import server
import store


class MarketingReviewBlockerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, 'data')
        self.out = os.path.join(self.tmp.name, 'out')
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.out, 'B69'))
        for p in [patch.object(store, 'DATA', self.data), patch.object(A.E, 'OUT', self.out),
                  patch.object(A, 'REVIEW_FILE', os.path.join(self.data, 'reviews.json')),
                  patch.object(store, 'FLAGFILE', os.path.join(self.data, 'marketing_flags.jsonl')),
                  patch.object(store, 'library_rows', return_value=[{'code': 'B69', 'book': '测试图书'}]),
                  patch.object(store, 'get_record', return_value={'code': 'B69', 'book': '测试图书'}),
                  patch.object(store, 'editor_flags', return_value={}),
                  patch.object(store, 'append_op'),
                  patch.object(store, 'original_pdf', return_value='/private/source/original.pdf')]:
            p.start()
            self.addCleanup(p.stop)
        self.good = {'id': 'B69-01-P01', '篇': '正文', '文本': '正文介绍了植物观察的方法。', 'source_page': 3}
        self.bad = {'id': 'B69-00-P01', '篇': '前置', '文本': '测试图书出版信息和封面文字。',
                    'source_page': 1, 'source_method': 'ocr', 'source_ocr_status': 'review',
                    'source_layout_suspect': True, 'source_layout_issue': 'ocr_review'}
        self.write_sources()
        self.marketing = {'items': {'keywords': {'name': '关键词', 'value': [
            {'keyword': '植物观察', 'evidence': [{'seg': self.good['id'], 'quote': self.good['文本']}]},
            {'keyword': '出版信息', 'evidence': [{'seg': self.good['id'], 'quote': self.good['文本']},
                                                {'seg': self.bad['id'], 'quote': self.bad['文本']}]}]}}}
        self.write('marketing.json', self.marketing)

    def write(self, filename, value):
        with open(os.path.join(self.out, 'B69', filename), 'w') as handle:
            json.dump(value, handle, ensure_ascii=False)

    def write_sources(self):
        with open(os.path.join(self.out, 'B69', 'segments.jsonl'), 'w') as handle:
            for value in (self.good, self.bad):
                handle.write(json.dumps(value, ensure_ascii=False) + '\n')
        self.write('book.json', {'篇数': 2})

    def assets(self):
        return [a for a in A.all_assets('B69') if a['kind'] == 'marketing']

    def call(self, ids, status='adopt'):
        h = object.__new__(server.Handler)
        h._auth_ok = lambda: True
        h._qs = lambda: ('/api/marketing/flag', {})
        h._read_json = lambda: {'code': 'B69', 'ids': ids, 'status': status}
        h._json = lambda body, status=200: (status, body)
        h._err = lambda message, status=400: (status, {'ok': False, 'error': str(message)})
        return h.do_POST()

    def test_batch_preflight_returns_blocked_source_and_confirms_nothing(self):
        before = self.assets()
        status, response = self.call([a['legacy_id'] for a in before])
        self.assertEqual(status, 400)
        self.assertEqual(response['error_code'], 'marketing_review_blocked')
        self.assertEqual(response['changed_count'], 0)
        self.assertEqual(response['count'], 0)
        self.assertFalse(os.path.exists(A.REVIEW_FILE))
        self.assertFalse(os.path.exists(store.FLAGFILE))
        self.assertEqual([a['status'] for a in self.assets()], ['review', 'review'])
        blocked = response['blocked_items'][0]
        self.assertEqual(blocked['asset_id'], before[1]['id'])
        self.assertEqual(blocked['legacy_id'], before[1]['legacy_id'])
        self.assertEqual(blocked['code'], 'B69')
        self.assertEqual(blocked['title'], '出版信息')
        self.assertIn('source_structure', [reason['code'] for reason in blocked['reasons']])
        self.assertIn('PDF 第 1 页', blocked['reasons'][0]['message'])
        self.assertEqual(blocked['source_url'], '#/book/B69/text/B69-00-P01')
        self.assertEqual(blocked['report_url'], '#/report/B69')
        self.assertEqual(blocked['pdf_pages'], [1, 3])
        source = blocked['sources'][0]
        self.assertEqual(source['anchor'], self.bad['id'])
        self.assertEqual(source['pdf_url'], '/api/book/source?code=B69#page=1')
        self.assertEqual(source['source_ocr_status'], 'review')
        self.assertEqual(source['text'], self.bad['文本'])
        self.assertNotIn('/private/', json.dumps(response))

    def test_readonly_issues_endpoint_matches_blockers_and_resolves_after_source_repair(self):
        h = object.__new__(server.Handler)
        h._auth_ok = lambda: True
        h._qs = lambda: ('/api/marketing/review-issues', {'code': ['B69']})
        h._json = lambda body, status=200: (status, body)
        h._err = lambda message, status=400: (status, {'ok': False, 'error': str(message)})
        status, body = h.do_GET()
        self.assertEqual(status, 200)
        self.assertEqual(body['checked_count'], 2)
        self.assertEqual(body['blocked_count'], 1)
        self.assertEqual(body['blocked_items'][0]['sources'][0]['source_page'], 1)
        self.assertFalse(os.path.exists(A.REVIEW_FILE))
        self.assertFalse(os.path.exists(store.FLAGFILE))
        self.bad.pop('source_layout_suspect')
        self.bad['source_ocr_status'] = 'body'
        self.write_sources()
        self.assertEqual(h.do_GET()[1]['blocked_items'], [])
        self.assertFalse(os.path.exists(A.REVIEW_FILE))
        self.assertFalse(os.path.exists(store.FLAGFILE))

    def test_readonly_issues_exclude_confirmed_and_disabled_materials(self):
        good, bad = self.assets()
        A.review_asset({'id': good['id'], 'revision': good['revision'], 'status': 'approved'})
        A.review_asset({'id': bad['id'], 'revision': bad['revision'], 'status': 'rejected'})
        with patch.object(store, 'write_json', side_effect=AssertionError('read-only check wrote state')):
            issues = A.marketing_review_issues('B69')
        self.assertEqual(issues['checked_count'], 0)
        self.assertEqual(issues['blocked_items'], [])

    def test_preflight_failure_preserves_existing_confirmation_and_manual_text(self):
        good, bad = self.assets()
        A.review_asset({'id': good['id'], 'revision': good['revision'], 'status': 'approved', 'text': '人工确认的植物简介'})
        with open(A.REVIEW_FILE, 'rb') as handle:
            before = handle.read()
        with open(store.FLAGFILE, 'rb') as handle:
            flags_before = handle.read()
        self.assertEqual(self.call([good['legacy_id'], bad['legacy_id']])[0], 400)
        with open(A.REVIEW_FILE, 'rb') as handle:
            self.assertEqual(handle.read(), before)
        with open(store.FLAGFILE, 'rb') as handle:
            self.assertEqual(handle.read(), flags_before)

    def test_fixed_source_allows_one_atomic_review_write_and_keeps_revision_checks(self):
        self.bad.pop('source_layout_suspect')
        self.bad['source_ocr_status'] = 'body'
        self.write_sources()
        assets = self.assets()
        with patch.object(store, 'write_json', wraps=store.write_json) as write:
            status, body = self.call([a['legacy_id'] for a in assets])
        self.assertEqual(status, 200)
        self.assertEqual(body['count'], 2)
        self.assertEqual(body['changed_count'], 2)
        self.assertEqual(sum(call.args[0] == A.REVIEW_FILE for call in write.call_args_list), 1)
        self.assertEqual([a['status'] for a in self.assets()], ['approved', 'approved'])
        self.assertEqual(len(marketing_state.rows('B69', approved_only=True)), 2)
        with self.assertRaises(A.Conflict):
            A.review_asset({'id': assets[0]['id'], 'revision': assets[0]['revision'], 'status': 'rejected'})

    def test_no_pdf_does_not_offer_dead_pdf_link_and_missing_anchor_is_explicit(self):
        self.marketing['items']['keywords']['value'][1]['evidence'] = [{'seg': 'B69-missing', 'quote': '无此原文'}]
        self.write('marketing.json', self.marketing)
        with patch.object(store, 'original_pdf', return_value=None):
            status, body = self.call([self.assets()[1]['legacy_id']])
        self.assertEqual(status, 400)
        blocked = body['blocked_items'][0]
        self.assertEqual(blocked['reasons'][0]['code'], 'invalid_evidence')
        self.assertEqual(blocked['source_url'], '#/book/B69/text')
        self.assertEqual(blocked['pdf_pages'], [])
        self.assertFalse(blocked['has_original_pdf'])
        self.assertEqual(blocked['sources'][0]['source_url'], '')
        self.assertEqual(blocked['sources'][0]['pdf_url'], '')

    def test_stale_or_missing_item_blocks_the_entire_request(self):
        self.marketing['stale'] = True
        self.write('marketing.json', self.marketing)
        status, body = self.call([self.assets()[0]['legacy_id'], 'keywords:no-longer-here'])
        self.assertEqual(status, 400)
        self.assertEqual(len(body['blocked_items']), 2)
        self.assertIn('source_stale', [r['code'] for r in body['blocked_items'][0]['reasons']])
        self.assertEqual(body['blocked_items'][1]['reasons'][0]['code'], 'asset_missing')
        self.assertFalse(os.path.exists(A.REVIEW_FILE))

    def test_rejection_is_allowed_for_blocked_sources_and_duplicate_ids_are_deduplicated(self):
        bad = self.assets()[1]
        status, body = self.call([bad['legacy_id'], bad['legacy_id']], 'reject')
        self.assertEqual(status, 200)
        self.assertEqual(body['count'], 1)
        self.assertEqual(A.get_asset(bad['id'])['status'], 'rejected')

    def test_review_write_failure_does_not_write_legacy_flags(self):
        with patch.object(store, 'write_json', side_effect=OSError('write failed')), \
                patch.object(store, 'set_marketing_flags') as flags:
            with self.assertRaises(OSError):
                A.review_marketing_assets('B69', [self.assets()[0]['legacy_id']], 'approved')
        flags.assert_not_called()
        self.assertFalse(os.path.exists(A.REVIEW_FILE))

    def test_legacy_mirror_failure_reports_saved_reviews_instead_of_false_zero_success(self):
        good = self.assets()[0]
        with patch.object(store, 'set_marketing_flags', side_effect=OSError('legacy disk failed')):
            status, body = self.call([good['legacy_id']])
        self.assertEqual(status, 200)
        self.assertEqual(body['changed_count'], 1)
        self.assertTrue(body['warnings'])
        self.assertEqual(A.get_asset(good['id'])['status'], 'approved')


if __name__ == '__main__':
    unittest.main()
