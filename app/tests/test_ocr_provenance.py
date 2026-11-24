"""OCR source routing and review boundaries; isolated files and no model calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'platform' / 'engine'))
sys.path.insert(0, str(ROOT / 'app'))

import assets_service as assets
import cards
import entities
import library
import marketing_state
import qa_service
import source_context
import store
import taglib
import understanding
import wash


BODY = '图像识别是基于图像特征识别物体的一种技术。使用前应当核对原书中的数字和名称。'


def make_segments(folder, statuses, picture=True, text=BODY):
    pages = [{'page': i, 'picture_dominant': picture,
              **({'ocr': {'status': status}} if status is not None else {})}
             for i, status in enumerate(statuses, 1)]
    path = Path(folder) / 'source.layout.jsonl'
    path.write_text(''.join(json.dumps(p) + '\n' for p in pages), encoding='utf-8')
    raw = '\n'.join('<<<PAGE %d>>>\n%s%s' %
                    (i, '第一章 图像识别\n' if i == 1 else '', text)
                    for i in range(1, len(pages) + 1))
    return wash.build(raw, 'T01', [('第一章 图像识别', 0)], layout_path=path)[0]


class OCRRoutingTests(unittest.TestCase):
    def test_accepted_ocr_recovers_image_prose_but_other_pages_keep_their_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = make_segments(folder, ['body', 'review', 'no_text', 'failed', 'unavailable', None])
        self.assertEqual([s['source_page'] for s in rows], list(range(1, 7)))
        self.assertFalse(rows[0].get('source_layout_suspect'))
        self.assertEqual(rows[0]['source_method'], 'ocr')
        self.assertEqual(rows[0]['source_ocr_status'], 'body')
        self.assertEqual(rows[1]['source_method'], 'ocr')
        self.assertEqual([s.get('source_layout_issue') for s in rows[1:]],
                         ['ocr_review', 'ocr_no_text', 'ocr_failed', 'ocr_unavailable', 'picture_dominant'])
        self.assertTrue(all(s['文本'] == BODY for s in rows))
        self.assertTrue(all('source_method' not in row for row in rows[2:]))

    def test_partial_ocr_never_depends_on_picture_flag_and_formula_gate_stays(self):
        with tempfile.TemporaryDirectory() as folder:
            review = make_segments(folder, ['review'], picture=False)[0]
            formula = make_segments(folder, ['body'], text='读数是2×10－4。')[0]
            front = wash.build('<<<PAGE 1>>>\n序言内容。\n第一章 图像识别\n正文。',
                               'T01', [('第一章 图像识别', 1)],
                               layout_path=Path(folder) / 'source.layout.jsonl')[0][0]
        self.assertTrue(review['source_layout_suspect'])
        self.assertEqual(formula['source_layout_issue'], 'formula_or_encoding')
        self.assertEqual(formula['source_method'], 'ocr')
        self.assertEqual(front['source_kind'], 'front_matter')
        self.assertFalse(understanding.supported_source(front))

    def test_known_consumers_only_select_accepted_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = make_segments(folder, ['body', 'review', 'failed', 'unavailable', 'no_text'])
        for selector in (cards.content_evidence_segment, understanding.supported_source,
                         entities.source_readable, library.name_evidence_segment):
            with self.subTest(selector=selector.__name__):
                self.assertEqual([selector(row) for row in rows], [True, False, False, False, False])
        self.assertEqual(set(taglib._evidence_by_anchor(rows)), {rows[0]['id']})
        with patch.object(store, 'read_json', return_value={}), \
                patch.object(store, 'read_jsonl', return_value=rows), \
                patch.object(qa_service, '_hints', return_value=({}, [])), \
                patch.object(qa_service, '_classification', return_value=('unclassified', '未分类')):
            index = qa_service._build([{'code': 'T01', 'book': '测试书'}], 'ocr-test')
        self.assertEqual(index['books'][0]['segments'], 1)
        self.assertEqual({doc['anchor'] for doc in index['docs']}, {rows[0]['id']})


class OCRAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'out'
        (self.out / 'T01').mkdir(parents=True)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.row = {'code': 'T01', 'book': '测试书'}
        for target, name, value in ((assets.E, 'OUT', str(self.out)),
                                    (store, 'DATA', str(self.data)),
                                    (assets, 'REVIEW_FILE', str(self.data / 'reviews.json'))):
            p = patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        for target, name, value in ((store, 'library_rows', [self.row]),
                                    (store, 'editor_flags', {}),
                                    (marketing_state, 'raw_rows', [])):
            p = patch.object(target, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def source(self, statuses):
        rows = make_segments(self.root, statuses)
        folder = self.out / 'T01'
        (folder / 'segments.jsonl').write_text(''.join(json.dumps(s, ensure_ascii=False) + '\n'
                                                    for s in rows), encoding='utf-8')
        (folder / 'understanding.json').write_text(json.dumps({'quotes': [
            {'seg': s['id'], 'quote': s['文本']} for s in rows]}), encoding='utf-8')
        return rows, [a for a in assets.all_assets() if a['kind'] == 'quote']

    def test_source_method_and_note_are_visible_without_auto_approval(self):
        rows, found = self.source(['body', 'review'])
        accepted, partial = found
        self.assertEqual(accepted['status'], 'review')
        self.assertFalse(accepted.get('needs_structure_review'))
        self.assertEqual(accepted['source_method'], 'ocr')
        self.assertEqual(accepted['evidence'][0]['source_page'], 1)
        self.assertIn('人名、数字和标点', accepted['source_verification_note'])
        self.assertTrue(partial['needs_structure_review'])
        self.assertIn('PDF 第 2 页', partial['quality_note'])
        self.assertIn('不完整或置信度不足', partial['source_verification_note'])
        enriched = source_context.enrich_asset(partial, segments=rows)
        self.assertEqual(enriched['source_quality'], 'blocked')
        self.assertEqual(enriched['source_method'], 'ocr')
        with self.assertRaisesRegex(ValueError, 'OCR'):
            assets.review_asset({'id': partial['id'], 'revision': partial['revision'], 'status': 'approved'})
        approved = assets.review_asset({'id': accepted['id'], 'revision': accepted['revision'], 'status': 'approved'})
        self.assertEqual(approved['status'], 'approved')

    def test_recognition_status_change_invalidates_previous_approval(self):
        _, found = self.source(['body'])
        original = found[0]
        assets.review_asset({'id': original['id'], 'revision': original['revision'], 'status': 'approved'})
        _, found = self.source(['review'])
        changed = found[0]
        self.assertNotEqual(changed['source_revision'], original['source_revision'])
        self.assertEqual(changed['status'], 'review')
        self.assertTrue(changed['previous_review_stale'])
        # Even an externally supplied old approval cannot override the source gate.
        approved = dict(source_revision=changed['source_revision'], status='approved',
                        revision='old-review', updated_at='before')
        self.assertEqual(assets._apply_review(changed, {changed['id']: approved})['status'], 'review')

    def test_native_versions_are_unchanged_and_original_locator_keeps_provenance(self):
        native = [{'id': 'T01-01-P01', '文本': BODY, 'source_page': 1}]
        self.assertEqual(assets.digest(assets._source_version_rows(native)),
                         assets.digest([(s['id'], s['文本']) for s in native]))
        rows, _ = self.source(['body', 'review'])
        with patch.object(store, 'original_pdf', return_value='/example/original.pdf'):
            located = store.get_segment_at('T01', rows[1]['id'], radius=1)
        self.assertEqual(located['source_method'], 'ocr')
        self.assertEqual(located['source_ocr_status'], 'review')
        self.assertTrue(located['source_layout_suspect'])
        self.assertEqual([s['source_ocr_status'] for s in located['items']], ['body', 'review'])


if __name__ == '__main__':
    unittest.main()
