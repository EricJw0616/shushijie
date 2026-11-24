# -*- coding: utf-8 -*-
import copy
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import source_context as S
import source_names as N


class SourceContextTests(unittest.TestCase):
    def asset(self, text='观察植物成长，连续记录叶片变化。', kind='summary'):
        return {'id': 'DEMO:summary:x', 'code': 'DEMO', 'kind': kind, 'title': '观察',
                'text': text, 'status': 'review', 'revision': 'r1', 'evidence_valid': True,
                'evidence': [{'anchor': 'DEMO-01-P01', 'quote': '人物介绍。'}]}

    def test_summary_context_follows_content_and_preserves_asset(self):
        a = self.asset(); original = copy.deepcopy(a)
        segs = [{'id': 'DEMO-01-P01', '篇': '第一章', '文本': '人物介绍。'},
                {'id': 'DEMO-01-P02', '篇': '第一章', '文本': '观察植物成长，连续记录叶片变化。'},
                {'id': 'DEMO-02-P01', '篇': '第二章', '文本': '观察植物成长，连续记录叶片变化。'}]
        enriched = S.enrich_asset(a, segments=segs)
        self.assertEqual(enriched['source_context'][0]['anchor'], 'DEMO-01-P02')
        self.assertNotIn('DEMO-02-P01', [x['anchor'] for x in enriched['source_context']])
        self.assertEqual(a, original)
        self.assertIn('不代表覆盖全章', enriched['context_coverage'])

    def test_missing_numbers_block_body_but_complete_numbers_do_not(self):
        for text in ['竣工仅天的大桥', '并将万元存款捐给学校', '培养了名院士']:
            self.assertEqual(S.enrich_asset(self.asset(text), segments=[])['source_quality'], 'blocked')
        for text in ['竣工仅30天的大桥', '将10万元存款捐给学校', '培养了多名学生', '连续观察多年']:
            self.assertNotEqual(S.enrich_asset(self.asset(text), segments=[])['source_quality'], 'blocked')

    def test_source_noise_is_warning_not_automatic_rejection(self):
        segs = [{'id': 'DEMO-01-P01', '篇': '观察', '文本': '生卒年：— 观察植物成长。'}]
        a = S.enrich_asset(self.asset(), segments=segs)
        self.assertEqual(a['source_quality'], 'needs_review')
        self.assertEqual(a['status'], 'review')

    def test_body_error_is_not_downgraded_by_same_context_warning(self):
        text = '竣工仅天的大桥'
        a = S.enrich_asset(self.asset(text), segments=[{'id': 'DEMO-01-P01', '篇': '观察', '文本': text}])
        self.assertEqual(a['source_quality'], 'blocked')
        self.assertEqual(next(w for w in a['quality_warnings'] if w['code'] == 'missing_number')['severity'], 'error')

    def test_context_is_bounded_and_exact(self):
        text = '阅读文字。' * 500 + '观察植物成长，连续记录叶片变化。' + '后文。' * 500
        segs = [{'id': 'DEMO-01-P01', '篇': '观察', '文本': text}]
        a = S.enrich_asset(self.asset(), max_chars=400, segments=segs)
        self.assertLessEqual(sum(len(x['quote']) for x in a['source_context']), 400)
        self.assertTrue(all(x['quote'] in text for x in a['source_context']))
        self.assertIn('观察', a['source_context'][0]['quote'])

    def test_rejected_or_invalid_evidence_is_blocked(self):
        for field, value in [('status', 'rejected'), ('stale', True), ('evidence_valid', False)]:
            a = self.asset(); a[field] = value
            self.assertEqual(S.enrich_asset(a, segments=[])['source_quality'], 'blocked')


class SourceNameTests(unittest.TestCase):
    def test_note_is_local_to_the_paragraph_and_expires_when_text_changes(self):
        segments = {'T01-01-P01': '宣宗谕令停止折价。', 'T01-02-P01': '宣宗另有谕令。'}
        def segment(code, anchor):
            return {'id': anchor, '文本': segments[anchor]}

        with tempfile.TemporaryDirectory() as directory, patch.object(N.store, 'DATA', directory), \
             patch.object(N.store, 'get_record', return_value={'code': 'T01'}), \
             patch.object(N.E, 'book_json', return_value={'source_version': 'v1'}), \
             patch.object(N, '_segment', side_effect=segment):
            first = N.get_check('T01', 'T01-01-P01', '宣宗')
            N.save_check(dict(first, note='清宣宗'))
            self.assertEqual(N.get_check('T01', 'T01-01-P01', '宣宗')['review']['note'], '清宣宗')
            self.assertIsNone(N.get_check('T01', 'T01-02-P01', '宣宗')['review'])
            segments['T01-01-P01'] = '宣宗取消折价。'
            self.assertIsNone(N.get_check('T01', 'T01-01-P01', '宣宗')['review'])
            with self.assertRaises(N.SourceChanged):
                N.save_check(dict(first, note='旧说明'))

    def test_name_prompt_requires_cited_excerpt_and_the_matching_draft_passage(self):
        quote = '宣宗谕令停止折价。'
        snapshot = {'code': 'T01', 'evidence': [{'anchor': 'T01-01-P01', 'quote': quote}]}
        item = {'asset_id': 'a1', 'status': 'adopted', 'evidence_valid': True, 'snapshot': snapshot}
        p = {'draft_generation': {'source_labels': {'a1': 'S1'}}, 'draft_asset_ids': ['a1'], 'items': [item]}
        with patch.object(N, '_segment', return_value={'id': 'T01-01-P01', '文本': quote}), \
             patch.object(N, '_conflicts', return_value={}), patch.object(N, 'reviews', return_value={}):
            self.assertEqual(N.project_checks(dict(p, draft='正文其他要点[S1]。宣宗颁布了谕令[S2]。')), [])
            self.assertEqual(N.project_checks(dict(p, draft='清宣宗发布了命令[S1]。')), [])
            self.assertEqual(N.project_checks(dict(p, draft='宣宗发出命令[S1]。', draft_asset_ids=[])), [])
            self.assertEqual([r['name'] for r in N.project_checks(dict(p, draft='宣宗发出命令[S1][S3]。'))], ['宣宗'])


if __name__ == '__main__':
    unittest.main()
