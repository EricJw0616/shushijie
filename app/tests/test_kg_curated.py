"""Evidence overlays are repeatable, source-bound and ordinary project material."""
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
import kg_curated as C
import projects as P
import store


class CuratedGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = os.path.join(self.tmp.name, 'app')
        self.data = os.path.join(self.app, 'data')
        self.graph_dir = os.path.join(self.data, 'kg')
        self.out = os.path.join(self.tmp.name, 'out')
        os.makedirs(self.graph_dir)
        self.segments, self.graphs = {}, {}
        self.rows = [{'code': code, 'book': code, 'updated_at': '2026-11-23'} for code in ('B59', 'B66')]
        for code in ('B59', 'B66'):
            os.makedirs(os.path.join(self.out, code))
            by_anchor = {}
            for fact in C.FACTS[code]:
                for item in KG._fact_sources(fact):
                    row = by_anchor.setdefault(item['anchor'], {'id': item['anchor'], '篇': item['chapter'], '段': 1, '文本': ''})
                    row['文本'] += item['quote'] + '\n'
                    for term in item.get('required', ()):
                        if term not in row['文本']:
                            row['文本'] += term + '\n'
            self.segments[code] = list(by_anchor.values())
            existing = [{'id': nid, 'label': spec['label'], 'kind': 'person', 'degree': 1}
                        for nid, spec in C.NODES[code].items() if spec.get('existing')]
            old_edges = []
            if code == 'B59':
                existing.append({'id': 'D-地学', 'label': '地学', 'kind': 'discipline'})
                old_edges.append({'id': 'OLD-LSG-GEOLOGY', 'source': 'P-李四光', 'target': 'D-地学',
                                  'kind': 'discipline', 'rel': '学科', 'note': '地质学家',
                                  'evidence': {'anchor': 'B59-01-P05', 'text': '身份字段'}})
            self.graphs[code] = {'meta': {'counts': {'nodes': len(existing), 'edges': len(old_edges)}},
                                 'nodes': existing, 'edges': old_edges}
            self.write_json(os.path.join(self.graph_dir, code + '.json'), self.graphs[code])
            self.write_json(os.path.join(self.out, code, 'book.json'), {'book': code, '原型': 'P2'})
            self.write_sources(code)
        self.write_json(os.path.join(self.data, 'library.json'), {'books': {r['code']: {'book': r['book']} for r in self.rows}})
        self.patches = [patch.object(KG, 'APP_DIR', self.app), patch.object(KG, 'OUT', self.out),
                        patch.object(KG, 'KGDIR', self.graph_dir),
                        patch.object(KG, 'REQFILE', os.path.join(self.graph_dir, 'requests.json')),
                        patch.object(A.E, 'OUT', self.out), patch.object(store, 'DATA', self.data),
                        patch.object(A, 'REVIEW_FILE', os.path.join(self.data, 'reviews.json')),
                        patch.object(P, 'DIR', os.path.join(self.data, 'projects')),
                        patch.object(store, 'library_rows', return_value=self.rows),
                        patch.object(store, 'editor_flags', return_value={}),
                        patch.object(store, 'marketing_flags', return_value={})]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    @staticmethod
    def write_json(path, value):
        with open(path, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)

    def write_sources(self, code):
        with open(os.path.join(self.out, code, 'segments.jsonl'), 'w', encoding='utf-8') as stream:
            for row in self.segments[code]:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    def call(self, project, action, **fields):
        return P.update_project(project['id'], dict(revision=project['revision'], action=action, **fields))

    def test_current_evidence_adds_events_people_and_cases_without_writes_or_duplicates(self):
        for code, expected_new_nodes in (('B59', 5), ('B66', 6)):
            with self.subTest(code=code):
                path = os.path.join(self.graph_dir, code + '.json')
                with open(path, 'rb') as stream:
                    original = stream.read()
                graph = KG.load_graph(code)
                self.assertEqual(graph, KG._with_curated_facts(code, copy.deepcopy(graph)))
                self.assertEqual(len(graph['nodes']), len(self.graphs[code]['nodes']) + expected_new_nodes)
                self.assertEqual(len(graph['edges']), len(self.graphs[code]['edges']) + len(C.FACTS[code]))
                self.assertEqual(len({n['id'] for n in graph['nodes']}), len(graph['nodes']))
                self.assertEqual(graph['meta']['counts']['edges'], len(graph['edges']))
                row = next(r for r in KG.catalog([code]) if r['code'] == code)
                self.assertEqual(row['edges'], len(graph['edges']))
                with open(path, 'rb') as stream:
                    self.assertEqual(stream.read(), original)

    def test_every_public_edge_has_basis_and_new_facts_resolve_with_literal_evidence(self):
        for code in ('B59', 'B66'):
            view = KG.view_graph(code)
            for edge in view['edges']:
                self.assertIn(edge['relation_basis'], KG.RELATION_BASIS_LABELS)
                self.assertEqual(edge['relation_basis_label'], KG.RELATION_BASIS_LABELS[edge['relation_basis']])
                if not edge.get('curated_fact'):
                    continue
                fact = next(f for f in C.FACTS[code] if f['id'] == edge['id'])
                self.assertEqual(edge['relation_basis'], fact.get('basis', 'explicit'))
                asset = A.get_asset(edge['asset_id'])
                self.assertEqual(asset['relation_basis'], fact.get('basis', 'explicit'))
                self.assertEqual(asset['status'], 'review')
                self.assertEqual(asset['evidence'], edge['evidence']['excerpts'])
                for item in asset['evidence']:
                    source = next(s for s in self.segments[code] if s['id'] == item['anchor'])
                    self.assertIn(item['quote'], source['文本'])
            self.assertFalse(any(edge['source'].split(':')[0] != edge['target'].split(':')[0]
                                 for edge in view['edges'] if edge['kind'] != 'in_book'))

    def test_multistage_bridge_shared_research_and_people_relations_keep_precise_roles(self):
        graph = KG.load_graph('B59')
        bridge = [e for e in graph['edges'] if e['target'] == 'PR-QIANTANG-BRIDGE']
        self.assertEqual({e['rel'] for e in bridge}, {'主持修建', '受命修复'})
        self.assertEqual(len({e['evidence']['anchor'] for e in bridge}), 2)
        insulin = [e for e in graph['edges'] if e['target'] == 'PR-INSULIN-SYNTHESIS']
        self.assertEqual({(e['source'], e['rel']) for e in insulin},
                         {('P-王应睐', '担任研究组长'), ('P-汪猷', '参与领导并直接参加')})
        mentoring = next(e for e in graph['edges'] if e['id'] == 'CE-QXS-GYH-GUIDANCE')
        self.assertEqual((mentoring['source'], mentoring['target'], mentoring['rel']), ('P-钱学森', 'P-郭永怀', '协助指导'))
        self.assertIn('冯·卡门', mentoring['note'])

    def test_changed_missing_ambiguous_or_suspect_evidence_retracts_only_affected_fact(self):
        code, fact = 'B66', C.FACTS['B66'][1]
        original = copy.deepcopy(self.segments[code])
        anchor = fact['support_evidence'][0]['anchor']
        for mutation in ('text', 'chapter', 'suspect', 'duplicate', 'missing'):
            with self.subTest(mutation=mutation):
                self.segments[code] = copy.deepcopy(original)
                row = next(s for s in self.segments[code] if s['id'] == anchor)
                if mutation == 'text':
                    row['文本'] = '当前正文已经更换。'
                elif mutation == 'chapter':
                    row['篇'] = '错章'
                elif mutation == 'suspect':
                    row['source_structure_suspect'] = True
                elif mutation == 'duplicate':
                    self.segments[code].append(copy.deepcopy(row))
                else:
                    self.segments[code].remove(row)
                self.write_sources(code)
                graph = KG.load_graph(code)
                self.assertNotIn(fact['id'], {e['id'] for e in graph['edges']})
                self.assertIn(C.FACTS[code][0]['id'], {e['id'] for e in graph['edges']})
                self.assertIsNone(A.get_asset(KG.relation_asset_id(code, fact['id'])))

    def test_material_rechecks_direction_and_excerpt_instead_of_falling_back_to_paragraph(self):
        graph = KG.load_graph('B59')
        fact = C.FACTS['B59'][0]
        edge = next(e for e in graph['edges'] if e['id'] == fact['id'])
        nodes, segments = {n['id']: n for n in graph['nodes']}, {s['id']: s for s in self.segments['B59']}
        for update in ({'note': '另一个未经核对的说法'}, {'source': fact['target'], 'target': fact['source']},
                       {'rel': '独自完成'}, {'evidence': {'anchor': 'missing'}}):
            with self.subTest(update=update):
                material, reason = KG.relation_material('B59', dict(edge, **update), nodes, segments)
                self.assertIsNone(material)
                self.assertIn('核对', reason)

    def test_old_asset_id_version_and_approval_survive_new_overlay_and_basis_metadata(self):
        aid = KG.relation_asset_id('B59', 'OLD-LSG-GEOLOGY')
        with patch.dict(C.FACTS, {}, clear=True):
            before = A.get_asset(aid)
            approved = A.review_asset({'id': aid, 'revision': before['revision'], 'status': 'approved'})
        after = A.get_asset(aid)
        self.assertEqual(after['id'], before['id'])
        self.assertEqual(after['source_revision'], before['source_revision'])
        self.assertEqual(after['revision'], approved['revision'])
        self.assertEqual(after['relation'], before['relation'])
        self.assertEqual(after['status'], 'approved')
        self.assertEqual(after['relation_basis'], 'field')

    def test_case_collect_review_export_keeps_all_sources_and_source_change_marks_it_stale(self):
        fact = C.FACTS['B66'][1]
        aid = KG.relation_asset_id('B66', fact['id'])
        asset = A.get_asset(aid)
        project = P.create_project({'title': '乡村社会案例', 'relation_asset_id': aid})
        project = P.get_project(project['id'])
        self.assertEqual(project['items'][0]['snapshot']['evidence'], asset['evidence'])
        self.assertEqual(project['items'][0]['status'], 'selected')
        self.assertEqual(project['items'][0]['current_status'], 'review')
        project = self.call(project, 'update_item', asset_id=aid, status='adopted')['project']
        project = self.call(project, 'save', draft=asset['text'], draft_asset_ids=[aid])['project']
        with self.assertRaises(ValueError):
            self.call(project, 'review')
        A.review_asset({'id': aid, 'revision': asset['revision'], 'status': 'approved'})
        project = self.call(project, 'review')['project']
        exported = self.call(project, 'export', mode='approved')
        for item in asset['evidence']:
            self.assertIn(item['anchor'], exported['text'])
            self.assertIn(item['quote'], exported['text'])
        next(s for s in self.segments['B66'] if s['id'] == fact['anchor'])['文本'] += '新增来源文字。'
        self.write_sources('B66')
        self.assertTrue(P.get_project(project['id'])['items'][0]['stale'])
        with self.assertRaises(ValueError):
            self.call(exported['project'], 'export', mode='approved')


if __name__ == '__main__':
    unittest.main()
