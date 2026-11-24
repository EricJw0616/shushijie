"""Isolated acceptance tests for review, persistent projects and versioned exports."""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store
import assets_service as A
import projects as P


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.tmp.name, 'data')
        self.out = os.path.join(self.tmp.name, 'out')
        os.makedirs(os.path.join(self.out, 'B01'))
        os.makedirs(self.data)
        self.rows = [{'code': 'B01', 'book': '测试书', 'segments': 1, 'updated_at': '2026-11-18'}]
        self.patches = [patch.object(store, 'DATA', self.data), patch.object(A.E, 'OUT', self.out),
                        patch.object(A, 'REVIEW_FILE', os.path.join(self.data, 'reviews.json')),
                        patch.object(P, 'DIR', os.path.join(self.data, 'projects')),
                        patch.object(store, 'library_rows', return_value=self.rows),
                        patch.object(store, 'editor_flags', return_value={}),
                        patch.object(store, 'marketing_flags', return_value={})]
        for p in self.patches:
            p.start()
        self.write('book.json', {'篇数': 1, '原型名': '知识型'})
        self.segment = {'id': 'B01-01-P01', '锚点': 'B01·一·P01', '文本': '这是用于验证材料审核与引用关系的原文。'}
        self.write('segments.jsonl', self.segment, jsonl=True)
        self.write('understanding.json', {'quotes': [{'seg': self.segment['id'], 'quote': self.segment['文本']}]})
        self.asset = next(a for a in A.all_assets() if a['kind'] == 'quote')

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def write(self, name, data, jsonl=False):
        with open(os.path.join(self.out, 'B01', name), 'w') as f:
            json.dump(data, f, ensure_ascii=False)
            if jsonl:
                f.write('\n')

    def approve(self):
        self.asset = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'], 'status': 'approved'})

    def call(self, p, action, **fields):
        return P.update_project(p['id'], dict(revision=p['revision'], action=action, **fields))

    def project_with_material(self, approved=True):
        if approved:
            self.approve()
        p = P.create_project({'title': '新选题资料包', 'kind': 'editorial', 'brief': {'topic': '知识整理'}})
        p = self.call(p, 'add_asset', asset_id=self.asset['id'])['project']
        p = self.call(p, 'update_item', asset_id=self.asset['id'], status='adopted', note='用于第一部分')['project']
        return self.call(p, 'save', draft='正文引用本书资料。', draft_asset_ids=[self.asset['id']])['project']

    def test_editorial_closed_loop_and_export_snapshot(self):
        p = self.project_with_material()
        p = self.call(p, 'review', approved=True)['project']
        r = self.call(p, 'export', mode='approved')
        self.assertIn('已审核交付稿', r['text'])
        self.assertIn(self.segment['id'], r['text'])
        p = self.call(r['project'], 'feedback', outcome='used', export_id=r['export']['id'], note='已用于选题评审')['project']
        self.assertEqual(P.get_project(p['id'])['status'], 'used')
        self.assertEqual(len(p['feedback']), 1)
        A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'], 'status': 'rejected'})
        self.assertTrue(P.get_project(p['id'])['warnings'])
        with self.assertRaises(ValueError):
            self.call(p, 'export', mode='approved')
        snapshot = store.read_json(os.path.join(P.DIR, 'exports', r['export']['id'] + '.json'))
        self.assertEqual(snapshot['text'], r['text'])

    def test_unreviewed_assets_cannot_be_approved_exported(self):
        p = self.project_with_material(approved=False)
        with self.assertRaises(ValueError):
            self.call(p, 'review')
        r = self.call(p, 'export', mode='review')
        self.assertIn('审阅稿', r['text'])
        with self.assertRaises(ValueError):
            self.call(r['project'], 'export', mode='approved')

    def test_confirmation_completes_shared_review_without_rewriting_projects(self):
        p = self.project_with_material(approved=False)
        other = self.project_with_material(approved=False)
        originals = {pid: P._read(pid) for pid in (p['id'], other['id'])}
        queued = P.review_queue()
        self.assertEqual(queued['total'], 1)
        self.assertEqual(queued['project_count'], 2)
        pinned = self.asset['revision']
        self.approve()
        self.assertNotEqual(self.asset['revision'], pinned)  # audit/write token remains distinct
        self.assertEqual(P.review_queue()['total'], 0)
        for pid, original in originals.items():
            current = P.get_project(pid)
            self.assertFalse(current['items'][0]['stale'])
            self.assertEqual(current['items'][0]['status'], 'adopted')
            self.assertEqual(current['items'][0]['current_status'], 'approved')
            self.assertFalse(current['draft_outdated'])
            self.assertEqual(current['warnings'], [])
            self.assertEqual(P._read(pid), original)
        # No refresh, second material adoption or regeneration is needed.
        reviewed = self.call(p, 'review')['project']
        exported = self.call(reviewed, 'export', mode='approved')
        self.assertIn('已审核交付稿', exported['text'])
        with self.assertRaises(A.Conflict):
            A.review_asset({'id': self.asset['id'], 'revision': pinned, 'status': 'rejected'})

    def test_review_history_preserves_manual_content_but_never_grants_approval(self):
        self.asset = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                                    'status': 'review', 'text': '编辑补充了适用范围的资料说明。'})
        p = self.project_with_material(approved=False)
        pinned = self.asset['revision']
        self.approve()
        self.assertFalse(P.get_project(p['id'])['items'][0]['stale'])
        self.assertEqual(P.review_queue()['total'], 0)
        self.asset = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                                    'status': 'review', 'reason': '重新检查适用性'})
        self.assertFalse(P.get_project(p['id'])['items'][0]['stale'])
        self.assertEqual(P.review_queue()['items'][0]['action'], 'review_asset')
        with self.assertRaises(ValueError):
            self.call(p, 'review')
        self.approve()
        self.assertTrue(A.reference_matches(self.asset, pinned, p['items'][0]['snapshot']))
        self.assertGreaterEqual(len(A._reviews()[self.asset['id']]['history']), 3)
        self.assertEqual(P.review_queue()['total'], 0)
        self.asset = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                                    'status': 'rejected', 'reason': '当前不适用'})
        self.assertEqual(P.review_queue()['items'][0]['status'], 'rejected')
        with self.assertRaises(ValueError):
            self.call(p, 'review')

    def test_confirmation_keeps_existing_generation_and_new_generation_available(self):
        import project_assist as assist
        import project_intelligence as intelligence
        p = self.project_with_material(approved=False)
        p = self.call(p, 'save', brief={'topic': '知识整理', 'audience': '编辑'})['project']
        snapshot = intelligence.build_input(p, 'draft')
        snapshot['project_context_hash'] = assist._context_hash(p)
        run = {'id': 'assist-0123456789abcdef', 'project_id': p['id'], 'capability': 'draft',
               'status': 'done', 'snapshot': snapshot, 'input_hash': intelligence.fingerprint(p),
               'profile_version': intelligence.PROFILE_VERSION, 'finished_at': store.now(),
               'markdown': '# 可供核对的讨论稿\n\n材料用于形成选题建议。',
               'result': {'asset_ids': [self.asset['id']]}}
        self.approve()
        self.assertEqual(assist._source_issue(run), '')
        self.assertEqual(len(intelligence.build_input(p, 'draft')['materials']), 1)
        with patch.object(assist, 'DIR', os.path.join(self.data, 'assists')):
            store.write_json(assist._path(run['id']), run)
            p = self.call(p, 'apply_generation', run_id=run['id'])['project']
            public = assist.get_run(p['id'], run['id'])
            self.assertFalse(public['source_stale'])
            self.assertFalse(public['stale'])
            self.assertTrue(public['is_current_draft'])
            self.assertEqual(self.call(p, 'review')['project']['status'], 'approved')
        self.asset = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                                    'status': 'rejected'})
        self.assertIn('失效', assist._source_issue(run))

    def test_real_content_edit_still_blocks_old_reference_and_generation(self):
        import project_assist as assist
        import project_intelligence as intelligence
        p = self.project_with_material()
        p = self.call(p, 'save', brief={'topic': '知识整理', 'audience': '编辑'})['project']
        snapshot = intelligence.build_input(p, 'draft')
        self.asset = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                                    'status': 'approved', 'text': '这是一份内容已经实质改写的资料。'})
        self.assertTrue(P.get_project(p['id'])['items'][0]['stale'])
        self.assertEqual(P.review_queue()['items'][0]['action'], 'refresh_reference')
        self.assertIn('已更新', assist._source_issue({'snapshot': snapshot}))
        with self.assertRaisesRegex(ValueError, '版本已变化'):
            intelligence.build_input(p, 'draft')
        with self.assertRaises(ValueError):
            self.call(p, 'review')

    def test_unknown_reference_versions_are_not_inferred_from_matching_text(self):
        self.approve()
        self.assertFalse(A.reference_matches(self.asset, 'unrecorded-revision', self.asset))
        without_source = dict(self.asset, source_revision='', reference_revisions=['unknown'])
        self.assertFalse(A.reference_matches(without_source, 'unknown', self.asset))

    def test_project_not_fit_does_not_reject_shared_asset(self):
        p = self.project_with_material()
        self.call(p, 'update_item', asset_id=self.asset['id'], status='not_fit', note='与本选题不符')
        self.assertEqual(A.get_asset(self.asset['id'])['status'], 'approved')

    def test_stale_project_write_conflicts(self):
        p = self.project_with_material()
        self.call(p, 'save', title='更新标题')
        with self.assertRaises(A.Conflict):
            self.call(p, 'save', title='过期页面的修改')

    def test_source_update_invalidates_approval(self):
        p = self.project_with_material()
        self.segment['文本'] += '新版补充。'
        self.write('segments.jsonl', self.segment, jsonl=True)
        a = A.get_asset(self.asset['id'])
        self.assertEqual(a['status'], 'review')
        self.assertTrue(a['previous_review_stale'])
        self.assertTrue(P.get_project(p['id'])['items'][0]['stale'])
        with self.assertRaises(A.Conflict):
            A.review_asset({'id': a['id'], 'revision': self.asset['revision'], 'status': 'approved'})

    def test_stale_generation_marker_blocks_old_approval(self):
        self.approve()
        self.write('understanding.json', {'stale': True, 'quotes': [{'seg': self.segment['id'], 'quote': self.segment['文本']}]})
        a = A.get_asset(self.asset['id'])
        self.assertEqual(a['status'], 'review')
        self.assertTrue(a['stale'])
        with self.assertRaises(ValueError):
            A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})

    def test_successful_quotes_not_blocked_by_stale_summaries(self):
        self.write('understanding.json', {'stale': True,
            'processing': {'quotes': {'status': 'done'}, 'summaries': {'status': 'stale'}},
            'quotes': [{'seg': self.segment['id'], 'quote': self.segment['文本']}],
            'summaries': [{'篇': '章节一', 'summary': '旧摘要', 'seg_from': self.segment['id']}]})
        rows = A.all_assets()
        quote = next(a for a in rows if a['kind'] == 'quote')
        summary = next(a for a in rows if a['kind'] == 'summary')
        self.assertFalse(quote['stale'])
        self.assertTrue(summary['stale'])
        A.review_asset({'id': quote['id'], 'revision': quote['revision'], 'status': 'approved'})

    def test_failure_retaining_same_source_does_not_invalidate_old_approval(self):
        self.approve()
        for status in ('failed', 'partial'):
            self.write('understanding.json', {'stale': True,
                'processing': {'quotes': {'status': status, 'retained_previous': True},
                               'summaries': {'status': 'stale'}},
                'quotes': [{'seg': self.segment['id'], 'quote': self.segment['文本']}]})
            a = A.get_asset(self.asset['id'])
            self.assertFalse(a['stale'])
            self.assertEqual(a['status'], 'approved')
            self.assertIn('保留上次成果', a['quality_note'])

    def test_failure_retaining_old_source_remains_stale(self):
        self.approve()
        for status in ('failed', 'partial'):
            self.write('understanding.json', {'stale': False,
                'processing': {'quotes': {'status': status, 'retained_previous': True, 'source_stale': True}},
                'quotes': [{'seg': self.segment['id'], 'quote': self.segment['文本']}]})
            a = A.get_asset(self.asset['id'])
            self.assertTrue(a['stale'])
            self.assertEqual(a['status'], 'review')
            with self.assertRaises(ValueError):
                A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})

    def test_invalid_anchor_rejects_approval(self):
        self.write('understanding.json', {'quotes': [{'seg': 'missing', 'quote': '不存在的证据'}]})
        a = next(x for x in A.all_assets() if x['kind'] == 'quote')
        self.assertFalse(a['evidence_valid'])
        with self.assertRaises(ValueError):
            A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})

    def test_new_book_marketing_requires_brief(self):
        p = self.project_with_material()
        raw = P._read(p['id']); raw['kind'] = 'marketing'; store.write_json(P._path(p['id']), raw)
        with self.assertRaisesRegex(ValueError, '新书营销'):
            self.call(p, 'review')
        p = self.call(p, 'save', brief={'new_book_brief': '新书定位、已确认目录及读者资料。'})['project']
        self.call(p, 'review')

    def test_global_edit_is_searchable_and_changes_revision(self):
        a = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                            'status': 'review', 'text': '人工修订的选题观点'})
        self.assertNotEqual(a['revision'], self.asset['revision'])
        self.assertEqual(A.list_assets(q='人工修订')['total'], 1)
        self.assertEqual(a['origin'], '人工修订')

    def test_marketing_edit_and_legacy_review_share_one_state(self):
        import marketing_state
        import server
        self.write('marketing.json', {'items': {'summary': {'name': '内容简介', 'value': {'text': '原有简介'},
                   'evidence': [{'seg': self.segment['id'], 'quote': self.segment['文本']}]}}})
        a = next(x for x in A.all_assets() if x['kind'] == 'marketing')
        with patch.object(store, 'FLAGFILE', os.path.join(self.data, 'marketing_flags.jsonl')):
            a = A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved', 'text': '编辑修订后的简介'})
            row = marketing_state.rows('B01')[0]
            self.assertEqual(row['main'], '编辑修订后的简介')
            self.assertEqual(row['status'], 'approved')
            self.assertIn('编辑修订后的简介', marketing_state.export('B01')['text'])
            h = object.__new__(server.Handler)
            h._auth_ok = lambda: True
            h._qs = lambda: ('/api/marketing/flag', {})
            h._read_json = lambda: {'code': 'B01', 'id': a['legacy_id'], 'status': 'reject'}
            h._json = lambda d: d
            h._err = lambda e, status: {'error': e, 'status': status}
            with patch.object(store, 'get_record', return_value={'code': 'B01'}), patch.object(store, 'append_op'):
                response = h.do_POST()
            self.assertTrue(response['ok'])
            self.assertEqual(A.get_asset(a['id'])['status'], 'rejected')
            self.assertEqual(marketing_state.rows('B01'), [])
            with self.assertRaises(ValueError):
                marketing_state.export('B01')

    def test_directory_fragment_summary_cannot_be_approved(self):
        name = '附录：个人·群体·社会——'
        self.segment.update(篇=name, 文本='一生学术历程的自我思考')
        self.write('segments.jsonl', self.segment, jsonl=True)
        self.write('understanding.json', {'summaries': [{'篇': name, 'summary': '根据标题生成的摘要', 'seg_from': self.segment['id']}]})
        a = next(x for x in A.all_assets() if x['kind'] == 'summary')
        self.assertTrue(a['needs_structure_review'])
        self.assertIn('11 个汉字', a['quality_note'])
        with self.assertRaisesRegex(ValueError, '版面或章节需要核对'):
            A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})

    def test_short_poem_does_not_trigger_structure_block(self):
        for name in ('静夜思', '序'):
            self.write('book.json', {'篇数': 1, '原型': 'P7', '原型名': '韵文集型'})
            self.segment.update(篇=name, 文本='床前明月光，疑是地上霜。举头望明月，低头思故乡。')
            self.write('segments.jsonl', self.segment, jsonl=True)
            self.write('understanding.json', {'summaries': [{'篇': name, 'summary': '月夜思乡。', 'seg_from': self.segment['id']}]})
            a = next(x for x in A.all_assets() if x['kind'] == 'summary')
            self.assertFalse(a['needs_structure_review'])
            A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})

    def test_refreshing_material_does_not_reapprove_old_draft(self):
        p = self.project_with_material()
        a = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                            'status': 'approved', 'text': '更新后的人工修订材料'})
        p = self.call(p, 'refresh_asset', asset_id=a['id'])['project']
        p = self.call(p, 'update_item', asset_id=a['id'], status='adopted')['project']
        self.assertTrue(p['draft_outdated'])
        with self.assertRaisesRegex(ValueError, '正文引用版本已过期'):
            self.call(p, 'review')
        p = self.call(p, 'save', brief={'topic': '只修改项目说明'}, draft=p['draft'])['project']
        with self.assertRaisesRegex(ValueError, '正文引用版本已过期'):
            self.call(p, 'review')
        p = self.call(p, 'save', draft=p['draft'] + '只调整措辞。')['project']
        self.assertTrue(p['draft_outdated'])
        with self.assertRaisesRegex(ValueError, '正文引用版本已过期'):
            self.call(p, 'review')
        p = self.call(p, 'save', draft=p['draft'], rebuild_draft=True)['project']
        self.assertFalse(p['draft_outdated'])
        self.call(p, 'review')

    def test_card_spanning_paragraphs_has_verified_evidence_per_paragraph(self):
        second = {'id': 'B01-01-P02', '文本': '下一段继续解释资料。'}
        with open(os.path.join(self.out, 'B01', 'segments.jsonl'), 'w') as f:
            for row in (self.segment, second):
                f.write(json.dumps(row, ensure_ascii=False) + '\n')
        self.write('cards.jsonl', {'id': 'B01-C001', '类型': '规则', '锚点': self.segment['id'],
                                   '原文': self.segment['文本'] + second['文本'], '字段': {'规则': '跨段规则'}}, jsonl=True)
        a = next(x for x in A.all_assets() if x['kind'] == 'fact')
        self.assertTrue(a['evidence_valid'])
        self.assertEqual([x['anchor'] for x in a['evidence']], [self.segment['id'], second['id']])

    def test_engine_candidates_are_internal_without_changing_source_cards(self):
        cards = [
            {'id': 'B01-C001', '类型': '规则候选', '字段': {'强规范信号数': 3}},
            {'id': 'B01-C002', '类型': '情节候选', '字段': {'标题拆解': '第一回'}},
            {'id': 'B01-C003', '类型': '物种', '字段': {'中名': '松树'}},
            {'id': 'B01-C004', '类型': '人物', '字段': {'姓名': '书中人物'}},
        ]
        for card in cards:
            card.update(锚点=self.segment['id'], 原文=self.segment['文本'])
        path = os.path.join(self.out, 'B01', 'cards.jsonl')
        original = ''.join(json.dumps(c, ensure_ascii=False) + '\n' for c in cards)
        with open(path, 'w') as f:
            f.write(original)
        facts = A.list_assets(kind='fact')['items']
        self.assertEqual({a['source_type'] for a in facts}, {'物种', '人物'})
        self.assertEqual({a['legacy_id'] for a in facts}, {'B01-C003', 'B01-C004'})
        self.assertEqual(A.list_assets(q='强规范信号')['total'], 0)
        with open(path) as f:
            self.assertEqual(f.read(), original)

    def test_draft_change_requires_another_review(self):
        p = self.project_with_material()
        p = self.call(p, 'review')['project']
        p = self.call(p, 'save', draft='改变后的交付正文')['project']
        with self.assertRaises(ValueError):
            self.call(p, 'export', mode='approved')

    def test_used_feedback_requires_explicit_approved_export(self):
        p = self.call(self.project_with_material(), 'review')['project']
        exported = self.call(p, 'export', mode='approved')
        p = exported['project']
        with self.assertRaisesRegex(ValueError, '请选择实际使用'):
            self.call(p, 'feedback', outcome='used')
        review_export = self.call(p, 'export', mode='review')
        with self.assertRaisesRegex(ValueError, '不符合使用条件'):
            self.call(review_export['project'], 'feedback', outcome='used', export_id=review_export['export']['id'])

    def test_old_export_feedback_does_not_mark_changed_draft_used(self):
        p = self.call(self.project_with_material(), 'review')['project']
        old = self.call(p, 'export', mode='approved')
        p = self.call(old['project'], 'save', draft='尚未审核的新正文')['project']
        p = self.call(p, 'feedback', outcome='used', export_id=old['export']['id'], note='确实使用的是旧稿')['project']
        self.assertEqual(p['status'], 'draft')
        self.assertIsNone(p['draft_review'])
        self.assertFalse(p['feedback'][-1]['applies_to_current_draft'])
        self.assertEqual(p['feedback'][-1]['export_id'], old['export']['id'])
        with self.assertRaises(ValueError):
            self.call(p, 'export', mode='approved')

    def test_old_export_feedback_preserves_new_review(self):
        p = self.call(self.project_with_material(), 'review')['project']
        old = self.call(p, 'export', mode='approved')
        p = self.call(old['project'], 'save', brief={'topic': '新的项目说明'})['project']
        p = self.call(p, 'review')['project']
        new_review = copy.deepcopy(p['draft_review'])
        for outcome in ('used', 'needs_revision'):
            p = self.call(p, 'feedback', outcome=outcome, export_id=old['export']['id'])['project']
            self.assertEqual(p['status'], 'approved')
            self.assertEqual(p['draft_review'], new_review)
            self.assertFalse(p['feedback'][-1]['applies_to_current_draft'])

    def test_current_export_with_invalidated_asset_feedback_is_historical(self):
        p = self.call(self.project_with_material(), 'review')['project']
        exported = self.call(p, 'export', mode='approved')
        A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'], 'status': 'rejected'})
        p = self.call(exported['project'], 'feedback', outcome='used', export_id=exported['export']['id'])['project']
        self.assertEqual(p['status'], 'delivered')
        self.assertFalse(p['feedback'][-1]['applies_to_current_draft'])

    def test_marketing_source_must_exist_in_library(self):
        p = self.project_with_material()
        raw = P._read(p['id'])
        raw['kind'] = 'marketing'
        store.write_json(P._path(p['id']), raw)
        p = self.call(p, 'save', brief={'source_code': 'NOT_A_BOOK'})['project']
        with self.assertRaisesRegex(ValueError, '不在当前书库'):
            self.call(p, 'review')
        p = self.call(p, 'save', brief={'source_code': 'B01'})['project']
        self.assertEqual(self.call(p, 'review')['project']['status'], 'approved')

    def test_historical_export_download_is_frozen_and_project_scoped(self):
        import server
        p = self.call(self.project_with_material(), 'review')['project']
        exported = self.call(p, 'export', mode='approved')
        p = self.call(exported['project'], 'save', title='修改后的标题', draft='新正文')['project']
        result = P.get_export(p['id'], exported['export']['id'])
        self.assertEqual(result['filename'], exported['filename'])
        self.assertEqual(result['text'], exported['text'])
        other = P.create_project({'title': '另一项目'})
        with self.assertRaisesRegex(ValueError, '没有这份交付记录'):
            P.get_export(other['id'], exported['export']['id'])
        h = object.__new__(server.Handler)
        h._auth_ok = lambda: True
        h._qs = lambda: ('/api/projects/' + p['id'] + '/exports/' + exported['export']['id'], {})
        h._json = lambda d: d
        h._err = lambda e, status: {'error': e, 'status': status}
        response = h.do_GET()
        self.assertTrue(response['ok'])
        self.assertEqual(response['text'], exported['text'])


    def test_saved_chapter_note_needs_explicit_review_before_use(self):
        self.write('cards.jsonl', {'id': 'B01-C001', '类型': '篇目候选',
                                 '字段': {'篇名': '第一章'}, '锚点': self.segment['id']}, jsonl=True)
        with patch.object(store, 'editor_flags', return_value={'B01-C001': {'主旨': '人工整理的阅读提要'}}):
            a = next(x for x in A.all_assets() if x['kind'] == 'summary')
            self.assertEqual(a['origin'], '人工修订')
            self.assertEqual(a['status'], 'review')
            approved = A.review_asset({'id': a['id'], 'revision': a['revision'], 'status': 'approved'})
            self.assertEqual(approved['status'], 'approved')


if __name__ == '__main__':
    unittest.main()
