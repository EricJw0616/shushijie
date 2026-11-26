"""Paragraph proofreading commits a bounded source change, never a marketing approval."""
import copy
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import assets_service as A
import source_review as R
import store


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        from reportlab.pdfgen.canvas import Canvas
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, 'data')
        self.out = os.path.join(self.tmp.name, 'out')
        self.folder = os.path.join(self.out, 'B69')
        os.makedirs(self.folder)
        os.makedirs(self.data)
        self.pdf = os.path.join(self.tmp.name, 'original.pdf')
        canvas = Canvas(self.pdf)
        canvas.drawString(20, 400, 'Original page 1'); canvas.showPage()
        canvas.drawString(20, 400, 'Original page 2'); canvas.save()
        for p in [patch.object(store, 'DATA', self.data), patch.object(A.E, 'OUT', self.out),
                  patch.object(A, 'REVIEW_FILE', os.path.join(self.data, 'reviews.json')),
                  patch.object(store, 'FLAGFILE', os.path.join(self.data, 'marketing_flags.jsonl')),
                  patch.object(store, 'library_rows', return_value=[{'code': 'B69', 'book': '核对图书'}]),
                  patch.object(store, 'get_record', return_value={'code': 'B69', 'book': '核对图书'}),
                  patch.object(store, 'editor_flags', return_value={}),
                  patch.object(store, 'original_pdf', side_effect=lambda _code: self.pdf)]:
            p.start(); self.addCleanup(p.stop)
        self.rows = [
            {'id': 'B69-00-P01', '篇': '前置', '篇序': 0, '文本': '第一页的图书编写机构信息。', 'source_kind': 'front_matter',
             'source_page': 1, 'source_method': 'ocr', 'source_ocr_status': 'review',
             'source_layout_suspect': True, 'source_layout_issue': 'ocr_review'},
            {'id': 'B69-00-P02', '篇': '前置', '篇序': 0, '文本': '同页另一个尚未核对的段落。', 'source_page': 1,
             'source_method': 'ocr', 'source_ocr_status': 'review', 'source_layout_suspect': True, 'source_layout_issue': 'ocr_review'},
            {'id': 'B69-01-P01', '篇': '正文', '篇序': 1, '文本': '已经可以正常引用的正文。', 'source_page': 2}]
        self.write_sources()
        self.marketing = {'generated_at': 'before', 'items': {'keywords': {'name': '关键词', 'value': [
            {'keyword': label, 'evidence': [{'seg': row['id'], 'quote': row['文本']}]}
            for label, row in zip(('编写机构', '第二段', '正文'), self.rows)]},
            'leads': {'name': '营销线索', 'value': [{'text': '编写机构是一个内容线索',
                       'evidence': [{'seg': self.rows[0]['id'], 'quote': self.rows[0]['文本']}]}]}}}
        self.write('marketing.json', self.marketing)
        self.write('book.json', {'篇数': 1})

    def write(self, name, value):
        with open(os.path.join(self.folder, name), 'w') as handle:
            json.dump(value, handle, ensure_ascii=False)

    def write_sources(self):
        with open(os.path.join(self.folder, 'segments.jsonl'), 'w') as handle:
            for row in self.rows:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    def asset(self, title='编写机构'):
        return next(a for a in A.all_assets('B69') if a['kind'] == 'marketing' and a['title'] == title)

    def body(self, title='编写机构'):
        a = self.asset(title)
        context = R.get_context('B69', a['id'])
        segment = context['segments'][0]
        return {'code': 'B69', 'asset_id': a['id'], 'anchor': segment['anchor'],
                'revision': segment['revision'], 'confirmed': True}

    def test_text_and_word_use_uploaded_document_without_pdf_pages(self):
        from docx import Document
        for source_format, label, text in (
                ('txt', 'TXT', '社区借阅日为每周三。'),
                ('docx', 'Word', '阅览区每周五开放。')):
            with self.subTest(source_format=source_format):
                original = os.path.join(self.tmp.name, 'original.' + source_format)
                if source_format == 'txt':
                    with open(original, 'w', encoding='utf-8') as handle:
                        handle.write('社区服务\n' + text)
                else:
                    doc = Document()
                    doc.add_paragraph('开放安排')
                    doc.add_paragraph(text)
                    doc.save(original)
                self.rows[0].update(文本=text, source_page=None, source_layout_suspect=True,
                                    source_layout_issue='ocr_review', source_ocr_status='review')
                self.rows[0].pop('source_review', None)
                self.write_sources()
                self.marketing['items']['keywords']['value'][0]['evidence'][0]['quote'] = text
                self.write('marketing.json', self.marketing)
                record = {'code': 'B69', 'book': '核对图书', 'source_format': source_format}
                with patch.object(store, 'get_record', return_value=record), \
                        patch.object(store, 'original_source', return_value=original):
                    context = R.get_context('B69', self.asset()['id'])
                    segment = context['pending_segments'][0]
                    self.assertTrue(segment['can_verify'])
                    self.assertEqual(segment['document_label'], label)
                    self.assertEqual(segment['document_excerpt'], text)
                    self.assertEqual(segment['pdf_url'], '')
                    result = R.verify(self.body())
                    self.assertFalse(result['changed'])
                    self.assertTrue(R.get_context('B69', self.asset()['id'])['can_proceed'])

    def test_repeated_source_text_remains_unverified(self):
        original = os.path.join(self.tmp.name, 'original.txt')
        repeated = self.rows[0]['文本']
        with open(original, 'w', encoding='utf-8') as handle:
            handle.write(repeated + '\n' + repeated)
        record = {'code': 'B69', 'book': '核对图书', 'source_format': 'txt'}
        with patch.object(store, 'get_record', return_value=record), \
                patch.object(store, 'original_source', return_value=original):
            context = R.get_context('B69', self.asset()['id'])
            segment = context['pending_segments'][0]
            self.assertFalse(segment['can_verify'])
            self.assertEqual(segment['document_excerpt'], '')
            with self.assertRaisesRegex(ValueError, '唯一定位'):
                R.verify(self.body())

    def test_stock_number_repairs_are_backed_up_and_invalidate_evidence_without_manual_credit(self):
        self.rows[2]['文本'] = '获年度科技奖励。'
        self.write_sources()
        self.marketing['items']['keywords']['value'][2]['evidence'][0]['quote'] = '获年度科技奖励。'
        self.write('marketing.json', self.marketing)
        path = os.path.join(self.folder, 'segments.jsonl')
        segment_sha256, pdf_sha256 = R._file_hash(path), R._file_hash(self.pdf)
        items = [{'anchor': self.rows[2]['id'], 'page': 2, 'current_page': 2,
                  'before': '获年度科技奖励。', 'after': '获2000年度科技奖励。'}]
        with patch.object(store, 'list_jobs', return_value=[]):
            result = R.apply_number_repairs('B69', segment_sha256, pdf_sha256, items)
            with self.assertRaises(R.SourceChanged):
                R.apply_number_repairs('B69', segment_sha256, pdf_sha256, items)
        self.assertEqual(result['applied'], 1)
        self.assertEqual(R._file_hash(result['backup']), segment_sha256)
        _, _, _, segments = R._load('B69')
        self.assertEqual(segments[2][1]['文本'], items[0]['after'])
        self.assertFalse(segments[2][1].get('source_review'))
        self.assertTrue(self.asset('正文')['stale'])

    def test_stock_number_repair_rejects_prose_rewrites_before_backup(self):
        self.rows[2]['文本'] = '获年度科技奖励。'
        self.write_sources()
        path = os.path.join(self.folder, 'segments.jsonl')
        before = R._file_hash(path)
        items = [{'anchor': self.rows[2]['id'], 'page': 2, 'current_page': 2,
                  'before': '获年度科技奖励。', 'after': '获奖时间不详。'}]
        with patch.object(store, 'list_jobs', return_value=[]), self.assertRaises(R.SourceChanged):
            R.apply_number_repairs('B69', before, R._file_hash(self.pdf), items)
        self.assertEqual(R._file_hash(path), before)
        self.assertFalse(os.path.exists(os.path.join(self.data, 'source_backups')))

    def test_context_gives_full_text_original_page_and_readonly_state(self):
        self.marketing['items']['keywords']['value'][0]['evidence'].append(
            {'seg': self.rows[2]['id'], 'quote': '正常引用的正文'})
        self.write('marketing.json', self.marketing)
        a = self.asset()
        with patch.object(store, 'write_json', side_effect=AssertionError('read-only')):
            context = R.get_context('B69', a['id'])
        self.assertEqual(context['text'], a['text'])
        self.assertEqual(context['legacy_id'], a['legacy_id'])
        self.assertEqual(context['pending_count'], 1)
        self.assertFalse(context['can_proceed'])
        segment = context['segments'][0]
        self.assertEqual(segment['text'], self.rows[0]['文本'])
        self.assertTrue(segment['can_verify'])
        self.assertEqual(segment['pdf_url'], '/api/book/source?code=B69#page=1')
        self.assertEqual(segment['preview_url'], '/api/book/source-page?code=B69&page=1')
        self.assertEqual(len(context['segments']), 1)
        self.assertEqual(context['evidence'], [
            {'anchor': self.rows[0]['id'], 'quote': self.rows[0]['文本'], 'chapter': '前置',
             'source_page': 1, 'text': self.rows[0]['文本']},
            {'anchor': self.rows[2]['id'], 'quote': '正常引用的正文', 'chapter': '正文',
             'source_page': 2, 'text': self.rows[2]['文本']}])
        self.assertFalse(os.path.exists(os.path.join(self.data, 'source_reviews')))

    def test_confirmation_updates_only_one_segment_records_backup_and_preserves_other_approval(self):
        good = self.asset('正文')
        good = A.review_asset({'id': good['id'], 'revision': good['revision'], 'status': 'approved'})
        path = os.path.join(self.folder, 'segments.jsonl')
        with open(path, 'rb') as handle:
            before = handle.read().splitlines(keepends=True)
        result = R.verify(self.body())
        self.assertFalse(result['changed'])
        self.assertFalse(result['requires_regeneration'])
        self.assertEqual(result['review']['action'], 'verified')
        with open(path, 'rb') as handle:
            after = handle.read().splitlines(keepends=True)
        self.assertEqual(before[1:], after[1:])
        corrected = json.loads(after[0])
        self.assertEqual(corrected['source_kind'], 'front_matter')
        self.assertEqual(corrected['source_ocr_status'], 'body')
        self.assertNotIn('source_layout_suspect', corrected)
        self.assertTrue(R.valid_verification(corrected))
        self.assertEqual(self.asset('正文')['revision'], good['revision'])
        self.assertEqual(self.asset('正文')['status'], 'approved')
        self.assertEqual(self.asset()['status'], 'review')
        self.assertTrue(self.asset('第二段')['needs_structure_review'])
        for title in ('编写机构', '编写机构是一个内容线索'):
            context = R.get_context('B69', self.asset(title)['id'])
            self.assertTrue(context['can_proceed'])
            self.assertEqual(context['pending_count'], 0)
            self.assertEqual(context['segments'][0]['review']['id'], result['review']['id'])
        audit = store.read_json(os.path.join(self.data, 'source_reviews', 'B69', result['review']['id'] + '.json'))
        self.assertEqual(audit['before'], self.rows[0])
        self.assertEqual(audit['after'], corrected)
        self.assertTrue(audit['confirmed'])

    def test_edit_with_still_matching_quote_blocks_derived_material_until_regenerated(self):
        body = self.body()
        body['text'] = self.rows[0]['文本'] + '补全的机构名称。'
        result = R.verify(body)
        self.assertTrue(result['changed'])
        a = self.asset()
        self.assertTrue(a['evidence_valid'], 'the old quote remains a substring but must not grant approval')
        self.assertTrue(a['stale'])
        self.assertTrue(a['source_corrected'])
        self.assertIn(a['id'], result['invalidated_asset_ids'])
        self.assertFalse(R.get_context('B69', a['id'])['can_proceed'])
        with self.assertRaises(ValueError):
            A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})
        self.marketing['stats'] = {'unrelated_update': True}
        self.write('marketing.json', self.marketing)
        self.assertTrue(self.asset()['stale'], 'changing unrelated metadata is not regeneration')
        self.marketing['generated_at'] = 'regenerated'
        self.marketing['items']['keywords']['value'][0]['evidence'][0]['quote'] = body['text']
        self.write('marketing.json', self.marketing)
        refreshed = self.asset()
        self.assertFalse(refreshed['stale'])
        self.assertTrue(R.get_context('B69', refreshed['id'])['can_proceed'])
        self.assertEqual(refreshed['status'], 'review')

    def test_stale_and_concurrent_confirmation_does_not_overwrite(self):
        body = self.body()
        def attempt(_):
            try:
                return R.verify(copy.deepcopy(body))
            except R.SourceChanged:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(isinstance(x, dict) for x in outcomes), 1)
        self.assertEqual(outcomes.count('conflict'), 1)
        files = os.listdir(os.path.join(self.data, 'source_reviews', 'B69'))
        self.assertEqual(len(files), 1)

    def test_multiple_corrected_sources_do_not_hide_the_newest_unregenerated_change(self):
        self.marketing['items']['keywords']['value'][0]['evidence'].append(
            {'seg': self.rows[1]['id'], 'quote': self.rows[1]['文本']})
        self.write('marketing.json', self.marketing)
        second = self.body('第二段')
        R.verify(dict(second, text=self.rows[1]['文本'] + '第二段补正。'))
        self.marketing['generated_at'] = 'middle-generation'
        self.write('marketing.json', self.marketing)
        first = self.body()
        R.verify(dict(first, text=self.rows[0]['文本'] + '第一段后续补正。'))
        self.assertTrue(self.asset()['stale'], 'a later paragraph with an older marker must not replace this marker')
        self.assertFalse(R.get_context('B69', self.asset()['id'])['can_proceed'])

    def test_missing_pdf_empty_text_and_structure_cannot_be_confirmed(self):
        original_rows = copy.deepcopy(self.rows)
        for changes in ({'文本': ''}, {'source_structure_suspect': True}, {'source_issue': 'chapter_owner_unknown'},
                        {'source_kind': 'blank'}, {'source_ocr_status': 'no_text'}, {'source_page': 99},
                        {'source_layout_issue': 'unknown_structure'}):
            self.rows = copy.deepcopy(original_rows); self.rows[0].update(changes); self.write_sources()
            a = self.asset()
            context = R.get_context('B69', a['id'])
            segment = context['segments'][0]
            self.assertFalse(segment['can_verify'], changes)
            with self.assertRaises(ValueError):
                R.verify({'code': 'B69', 'anchor': segment['anchor'], 'revision': segment['revision'], 'confirmed': True})
        self.rows = original_rows; self.write_sources()
        with patch.object(store, 'original_pdf', return_value=None):
            body = self.body()
            with self.assertRaises(ValueError):
                R.verify(body)
        self.assertFalse(os.path.exists(os.path.join(self.data, 'source_reviews')))

    def test_explicit_confirmation_and_matching_asset_are_required(self):
        body = self.body()
        for value in (False, 'true', 1, None):
            with self.assertRaises(ValueError):
                R.verify(dict(body, confirmed=value))
        with self.assertRaises(ValueError):
            R.verify(dict(body, asset_id=self.asset('第二段')['id']))
        self.assertFalse(os.path.exists(os.path.join(self.data, 'source_reviews')))

    def test_rejected_material_can_be_read_for_resume_but_not_verified(self):
        body = self.body()
        a = self.asset()
        A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'rejected'})
        with patch.object(store, 'write_json', side_effect=AssertionError('reading receipt wrote state')):
            context = R.get_context('B69', a['id'])
        self.assertEqual(context['status'], 'rejected')
        self.assertEqual(context['legacy_id'], a['legacy_id'])
        self.assertFalse(context['can_proceed'])
        self.assertFalse(context['segments'][0]['can_verify'])
        with self.assertRaises(ValueError):
            R.verify(body)
        self.assertFalse(os.path.exists(os.path.join(self.data, 'source_reviews')))

    def test_server_routes_return_context_enforce_confirmation_and_report_stale_revision(self):
        import server
        def request(method, path, body=None):
            handler = object.__new__(server.Handler)
            handler._auth_ok = lambda: True
            handler._qs = lambda: (path, {'code': ['B69'], 'asset_id': [self.asset()['id']]})
            handler._read_json = lambda: body or {}
            handler._json = lambda value, status=200: (status, value)
            handler._err = lambda message, status=400: (status, {'ok': False, 'error': str(message)})
            return handler.do_GET() if method == 'GET' else handler.do_POST()
        code, context = request('GET', '/api/marketing/source-review')
        self.assertEqual(code, 200)
        self.assertTrue(context['ok'])
        body = self.body()
        self.assertEqual(request('POST', '/api/marketing/source-review/verify', dict(body, confirmed=False))[0], 400)
        code, saved = request('POST', '/api/marketing/source-review/verify', body)
        self.assertEqual(code, 200)
        self.assertTrue(saved['ok'])
        self.assertEqual(request('POST', '/api/marketing/source-review/verify', body)[0], 409)
        context = request('GET', '/api/marketing/source-review')[1]
        self.assertTrue(context['can_proceed'])
        self.assertEqual(context['status'], 'review')
        approved = request('POST', '/api/content-assets/review',
                           {'id': context['asset_id'], 'revision': context['revision'], 'status': 'approved'})
        self.assertEqual(approved[0], 200)
        self.assertEqual(approved[1]['asset']['status'], 'approved')

    def test_audit_failure_leaves_original_source_unchanged(self):
        body = self.body()
        path = os.path.join(self.folder, 'segments.jsonl')
        with open(path, 'rb') as handle:
            before = handle.read()
        with patch.object(store, 'write_json', side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):
                R.verify(body)
        with open(path, 'rb') as handle:
            self.assertEqual(handle.read(), before)

    def test_unmatched_source_change_cannot_reuse_verified_metadata(self):
        R.verify(self.body())
        path = os.path.join(self.folder, 'segments.jsonl')
        rows = store.read_jsonl(path)
        rows[0]['source_ocr_status'] = 'review'
        self.assertFalse(R.valid_verification(rows[0]))
        self.assertEqual(R.source_version_entry(rows[0])[-1], 'review')

    def test_later_text_change_reopens_verification_even_if_old_flags_stay_cleared(self):
        R.verify(self.body())
        a = self.asset()
        A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})
        path = os.path.join(self.folder, 'segments.jsonl')
        self.rows = store.read_jsonl(path)
        self.rows[0]['文本'] += '其他流程后来追加了文字。'
        self.write_sources()
        current = self.asset()
        self.assertEqual(current['status'], 'review')
        self.assertTrue(current['needs_structure_review'])
        context = R.get_context('B69', current['id'])
        self.assertFalse(context['can_proceed'])
        self.assertEqual(context['pending_count'], 1)
        self.assertIsNone(context['segments'][0]['review'])
        self.assertTrue(context['segments'][0]['can_verify'])
        with self.assertRaises(ValueError):
            A.review_asset({'id': current['id'], 'revision': current['revision'], 'status': 'approved'})


if __name__ == '__main__':
    unittest.main()
