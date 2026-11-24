"""Relationship material resolves from real source text without indexing all graphs."""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import assets_service as A
import kg_build as KG
import projects as P
import store


class RelationAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, 'out')
        self.graph_dir = os.path.join(self.tmp.name, 'kg')
        self.data = os.path.join(self.tmp.name, 'data')
        os.makedirs(os.path.join(self.out, 'B58'))
        os.makedirs(self.graph_dir)
        os.makedirs(self.data)
        self.rows = [{'code': 'B58', 'book': '小王子', 'updated_at': '2026-11-23'}]
        self.segments = [
            {'id': 'B58-00-P91', '篇': '第二十一章', '段': 91, '文本': '狐狸说：“如果你想找个朋友，请驯化我！”'},
            {'id': 'B58-00-P92', '篇': '第二十一章', '段': 92,
             '文本': '于是小王子驯化了狐狸。转眼他们就要彼此分别。“唉！”狐狸说，“我会哭的。”'},
        ]
        self.edge = {'id': 'E-小王子-狐狸-驯养', 'source': 'P-小王子', 'target': 'P-狐狸',
                     'kind': 'relation', 'rel': '驯养', 'confidence': 'A', 'note': '旧展示说明',
                     'evidence': {'anchor': 'B58-00-P91', 'text': '这是不能直接引用的图谱摘要…'}}
        self.graph = {'meta': {}, 'nodes': [
            {'id': 'P-小王子', 'label': '小王子', 'kind': 'person'},
            {'id': 'P-狐狸', 'label': '狐狸', 'kind': 'person'},
        ], 'edges': [self.edge]}
        self.patches = [patch.object(A.E, 'OUT', self.out), patch.object(KG, 'OUT', self.out),
                        patch.object(KG, 'KGDIR', self.graph_dir), patch.object(store, 'DATA', self.data),
                        patch.object(A, 'REVIEW_FILE', os.path.join(self.data, 'reviews.json')),
                        patch.object(P, 'DIR', os.path.join(self.data, 'projects')),
                        patch.object(store, 'library_rows', return_value=self.rows),
                        patch.object(store, 'editor_flags', return_value={}),
                        patch.object(store, 'marketing_flags', return_value={}),
                        patch.object(KG, 'catalog', return_value=[{'code': 'B58', 'title': '小王子', 'status': '已建图'}])]
        for item in self.patches:
            item.start()
        self.write_sources()
        self.write_graph()
        self.aid = KG.relation_asset_id('B58', self.edge['id'])

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def write_sources(self):
        root = os.path.join(self.out, 'B58')
        with open(os.path.join(root, 'segments.jsonl'), 'w') as stream:
            for row in self.segments:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        with open(os.path.join(root, 'book.json'), 'w') as stream:
            json.dump({'book': '小王子', '篇数': 1}, stream)
        with open(os.path.join(root, 'understanding.json'), 'w') as stream:
            json.dump({'quotes': [{'seg': self.segments[1]['id'], 'quote': self.segments[1]['文本']}]}, stream)

    def write_graph(self):
        with open(os.path.join(self.graph_dir, 'B58.json'), 'w') as stream:
            json.dump(self.graph, stream, ensure_ascii=False)

    def call(self, project, action, **fields):
        return P.update_project(project['id'], dict(revision=project['revision'], action=action, **fields))

    def test_public_edge_resolves_to_directional_material_and_repairs_legacy_source_without_writes(self):
        path = os.path.join(self.graph_dir, 'B58.json')
        with open(path, 'rb') as stream:
            original = stream.read()
        public = next(e for e in KG.view_graph()['edges'] if e.get('asset_id'))
        self.assertEqual(public['asset_id'], self.aid)
        self.assertEqual(public['edge_id'], self.edge['id'])
        self.assertEqual(public['evidence']['anchor'], 'B58-00-P92')
        asset = A.get_asset(public['asset_id'])
        self.assertEqual(asset['text'], '小王子 —驯养→ 狐狸')
        self.assertEqual(asset['relation']['source_id'], 'B58:P-小王子')
        self.assertEqual(asset['relation']['target_id'], 'B58:P-狐狸')
        self.assertEqual(asset['relation']['body'], asset['text'])
        self.assertTrue(asset['relation']['source_route'].startswith('#/kglab/B58/'))
        self.assertEqual(asset['evidence'], [{'anchor': 'B58-00-P92', 'quote': '于是小王子驯化了狐狸。'}])
        self.assertEqual(asset['status'], 'review', 'graph confidence must not grant approval')
        with open(path, 'rb') as stream:
            self.assertEqual(stream.read(), original)

    def test_structural_unsupported_missing_and_ambiguous_edges_cannot_be_collected(self):
        for update in ({'rel': '包含'}, {'rel': '下一页'}, {'rel': '收录'}, {'rel': '未支持关系'},
                       {'evidence': {'anchor': 'B58-missing'}}, {'target': 'missing'}, {'kind': 'in_book'}):
            with self.subTest(update=update):
                self.graph['edges'] = [dict(self.edge, **update)]
                self.write_graph()
                self.assertIsNone(A.get_asset(self.aid))
                self.assertFalse(any(e.get('asset_id') for e in KG.view_graph()['edges']))
        self.graph['edges'] = [self.edge, copy.deepcopy(self.edge)]
        self.write_graph()
        self.assertIsNone(A.get_asset(self.aid))
        self.assertFalse(any(e.get('asset_id') for e in KG.view_graph()['edges']))

    def test_source_pointer_correction_requires_actual_support_and_clean_source(self):
        self.segments[1]['文本'] = '小王子只是提出以后再来看望狐狸。'
        self.write_sources()
        self.assertEqual(KG.load_graph('B58')['edges'][0]['evidence']['anchor'], 'B58-00-P91')
        self.assertIsNone(A.get_asset(self.aid))
        self.segments[1]['文本'] = '于是小王子驯化了狐狸。'
        self.segments[1]['source_structure_suspect'] = True
        self.write_sources()
        self.assertIsNone(A.get_asset(self.aid))

    def test_identity_is_stable_while_direction_and_source_changes_invalidate_review(self):
        before = A.get_asset(self.aid)
        self.graph['nodes'][0]['degree'] = 999
        self.graph['nodes'][0]['x'] = 111
        self.write_graph()
        self.assertEqual(A.get_asset(self.aid)['revision'], before['revision'])
        approved = A.review_asset({'id': self.aid, 'revision': before['revision'], 'status': 'approved'})
        self.assertTrue(A.reference_matches(approved, before['revision'], before))
        self.segments[1]['文本'] += '狐狸继续看着小王子。'
        self.write_sources()
        changed = A.get_asset(self.aid)
        self.assertEqual(changed['id'], before['id'])
        self.assertNotEqual(changed['revision'], approved['revision'])
        self.assertEqual(changed['status'], 'review')
        self.assertTrue(changed['previous_review_stale'])
        with self.assertRaises(A.Conflict):
            A.review_asset({'id': self.aid, 'revision': approved['revision'], 'status': 'approved'})
        self.edge['source'], self.edge['target'] = self.edge['target'], self.edge['source']
        self.edge['evidence']['anchor'] = 'B58-00-P92'
        self.write_graph()
        reversed_asset = A.get_asset(self.aid)
        self.assertEqual(reversed_asset['id'], before['id'])
        self.assertNotEqual(reversed_asset['revision'], changed['revision'])
        self.assertEqual(reversed_asset['text'], '狐狸 —驯养→ 小王子')

    def test_snapshot_relation_metadata_and_manual_revision_are_checked(self):
        asset = A.get_asset(self.aid)
        altered = copy.deepcopy(asset)
        altered['relation']['predicate'] = '捏造的关系'
        self.assertFalse(A.reference_matches(asset, asset['revision'], altered))
        edited = A.review_asset({'id': self.aid, 'revision': asset['revision'], 'status': 'review',
                                 'text': '小王子驯化了狐狸，二者即将分别。'})
        self.assertEqual(edited['relation']['body'], edited['text'])
        self.assertEqual(edited['relation']['title'], edited['title'])
        self.assertFalse(A.reference_matches(edited, asset['revision'], asset))

    def test_normal_asset_listing_never_reads_graphs_and_lazy_cache_handles_both_kinds(self):
        with patch.object(KG, 'load_graph', side_effect=AssertionError('graph must remain on demand')):
            rows = A.all_assets('B58')
            self.assertFalse(any(A.is_relation_id(a['id']) for a in rows))
            self.assertEqual(A.list_assets(code='B58')['total'], len(rows))
        regular = rows[0]
        cache = {}
        relation = A.cached_asset(self.aid, 'B58', cache)
        self.assertEqual(relation['id'], self.aid)
        self.assertEqual(A.cached_asset(regular['id'], 'B58', cache)['id'], regular['id'])
        with patch.object(A, 'get_asset', side_effect=AssertionError('cached relationship should be reused')):
            self.assertEqual(A.cached_asset(self.aid, 'B58', cache)['revision'], relation['revision'])
        prefilled = {'B58': {a['id']: a for a in rows}}
        self.assertEqual(A.cached_asset(self.aid, 'B58', prefilled)['id'], self.aid)
        self.assertFalse(A.is_relation_id('B58:relation:bad'))
        self.assertIsNone(A.get_asset('B58:relation:' + '0' * 20))

    def test_project_collect_review_adopt_and_export_preserves_evidence_snapshot(self):
        project = P.create_project({'title': '人物关系选题', 'kind': 'editorial', 'brief': {'topic': '关系'}})
        project = self.call(project, 'add_asset', asset_id=self.aid)['project']
        item = project['items'][0]
        self.assertFalse(item['stale'])
        self.assertEqual(item['status'], 'selected')
        self.assertEqual(item['current_status'], 'review')
        with self.assertRaises(ValueError):
            self.call(project, 'add_asset', asset_id=self.aid)
        project = self.call(project, 'update_item', asset_id=self.aid, status='adopted')['project']
        project = self.call(project, 'save', draft='小王子驯化了狐狸。', draft_asset_ids=[self.aid])['project']
        with self.assertRaises(ValueError):
            self.call(project, 'review')
        asset = A.get_asset(self.aid)
        A.review_asset({'id': self.aid, 'revision': asset['revision'], 'status': 'approved'})
        project = self.call(project, 'review')['project']
        exported = self.call(project, 'export', mode='approved')
        self.assertIn('B58-00-P92', exported['text'])
        self.assertIn('> 于是小王子驯化了狐狸。', exported['text'])
        self.segments[1]['文本'] += '一处后来的原文修改。'
        self.write_sources()
        self.assertTrue(P.get_project(project['id'])['items'][0]['stale'])
        self.assertEqual(exported['project']['items'][0]['snapshot']['evidence'][0]['quote'], asset['evidence'][0]['quote'])
        saved = store.read_json(os.path.join(P.DIR, 'exports', exported['export']['id'] + '.json'))
        self.assertEqual(saved['text'], exported['text'])

    def test_create_with_relation_is_one_write_and_invalid_relationship_never_creates_empty_project(self):
        body = {'title': '从关系开始的新选题', 'kind': 'editorial',
                'brief': {'topic': '人与关系'}, 'relation_asset_id': self.aid}
        for aid in ('B58:relation:invalid', 'B58:relation:' + '0' * 20):
            with self.subTest(asset_id=aid), patch.object(store, 'write_json', wraps=store.write_json) as write:
                with self.assertRaises(ValueError):
                    P.create_project(dict(body, relation_asset_id=aid))
                write.assert_not_called()
                self.assertEqual(P.list_projects(), [])
        asset = A.get_asset(self.aid)
        A.review_asset({'id': self.aid, 'revision': asset['revision'], 'status': 'rejected'})
        with patch.object(store, 'write_json', wraps=store.write_json) as write:
            with self.assertRaises(ValueError):
                P.create_project(body)
            write.assert_not_called()
            self.assertEqual(P.list_projects(), [])
        asset = A.get_asset(self.aid)
        A.review_asset({'id': self.aid, 'revision': asset['revision'], 'status': 'review'})
        with patch.object(store, 'write_json', wraps=store.write_json) as write:
            project = P.create_project(body)
            self.assertEqual(write.call_count, 1)
            self.assertEqual(write.call_args.args[1]['items'][0]['asset_id'], self.aid)
        saved = P.get_project(project['id'])
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['status'], 'draft')
        self.assertEqual(saved['items'][0]['status'], 'selected')
        self.assertEqual(saved['items'][0]['current_status'], 'review')
        self.assertEqual(saved['items'][0]['snapshot']['relation']['source_label'], '小王子')
        self.assertEqual(len(P.list_projects()), 1)

    def test_create_write_failure_does_not_leave_a_visible_project(self):
        with patch.object(store, 'write_json', side_effect=OSError('simulated storage failure')):
            with self.assertRaises(OSError):
                P.create_project({'title': '尚未创建', 'relation_asset_id': self.aid})
        self.assertEqual(P.list_projects(), [])

    def test_collecting_into_approved_project_preserves_old_review_until_material_is_adopted(self):
        regular = next(a for a in A.all_assets('B58') if a['kind'] == 'quote')
        A.review_asset({'id': regular['id'], 'revision': regular['revision'], 'status': 'approved'})
        project = P.create_project({'title': '已审核的原项目', 'brief': {'topic': '友谊'}})
        project = self.call(project, 'add_asset', asset_id=regular['id'])['project']
        project = self.call(project, 'update_item', asset_id=regular['id'], status='adopted')['project']
        project = self.call(project, 'save', draft='转眼他们就要彼此分别。', draft_asset_ids=[regular['id']])['project']
        project = self.call(project, 'review')['project']
        baseline = copy.deepcopy(project)
        collected = self.call(project, 'add_asset', asset_id=self.aid)['project']
        for key in ('status', 'draft', 'draft_review', 'draft_asset_ids', 'draft_asset_revisions', 'exports'):
            self.assertEqual(collected[key], baseline[key], key)
        self.assertEqual(collected['revision'], baseline['revision'] + 1)
        self.assertEqual(collected['items'][-1]['status'], 'selected')
        self.assertEqual(collected['items'][-1]['current_status'], 'review')
        delivered = self.call(collected, 'export', mode='approved')
        self.assertNotIn(self.aid, delivered['export']['asset_revisions'])
        adopted = self.call(delivered['project'], 'update_item', asset_id=self.aid, status='adopted')['project']
        self.assertIsNone(adopted['draft_review'])
        self.assertEqual(adopted['status'], 'draft')
        with self.assertRaises(ValueError):
            self.call(adopted, 'export', mode='approved')

    def test_duplicate_stale_project_revision_and_stale_relation_confirmation_do_not_write(self):
        project = P.create_project({'title': '关系资料', 'relation_asset_id': self.aid})
        project_path = P._path(project['id'])
        before = store.read_json(project_path)
        for operation in (
                lambda: self.call(project, 'add_asset', asset_id=self.aid),
                lambda: P.update_project(project['id'], {'revision': 0, 'action': 'add_asset', 'asset_id': self.aid})):
            with self.assertRaises(ValueError):
                operation()
            self.assertEqual(store.read_json(project_path), before)
        self.segments[1]['文本'] += '原文后来更新了。'
        self.write_sources()
        with self.assertRaises(A.Conflict):
            self.call(project, 'confirm_collected_material', asset_id=self.aid,
                      asset_revision=project['items'][0]['asset_revision'])
        self.assertEqual(store.read_json(project_path), before)
        refreshed = self.call(project, 'refresh_asset', asset_id=self.aid)['project']
        self.assertEqual(refreshed['items'][0]['status'], 'selected')
        self.assertEqual(refreshed['items'][0]['current_status'], 'review')
        self.assertNotEqual(refreshed['items'][0]['asset_revision'], before['items'][0]['asset_revision'])

    def test_relationship_reaches_assist_input_and_source_changes_invalidate_generation_snapshot(self):
        import project_assist
        import project_intelligence
        project = P.create_project({'title': '关系选题', 'kind': 'editorial',
                                    'brief': {'topic': '友谊与分别', 'audience': '成人读者'},
                                    'relation_asset_id': self.aid})
        project = self.call(project, 'update_item', asset_id=self.aid, status='adopted')['project']
        snapshot = project_intelligence.build_input(project, 'draft')
        self.assertEqual(snapshot['materials'][0]['asset_id'], self.aid)
        self.assertEqual(snapshot['materials'][0]['evidence'][0]['anchor'], 'B58-00-P92')
        self.assertEqual(project_assist._source_issue({'snapshot': snapshot}), '')
        self.segments[1]['文本'] += '此处的来源版本已经变化。'
        self.write_sources()
        self.assertTrue(project_assist._source_issue({'snapshot': snapshot}))
        with self.assertRaisesRegex(ValueError, '来源或版本已变化'):
            project_intelligence.build_input(project, 'draft')


if __name__ == '__main__':
    unittest.main()
