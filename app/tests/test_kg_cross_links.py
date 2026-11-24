"""Cross-book connections require two unchanged, scoped and reviewed contexts."""
import copy
import hashlib
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
import store


class CrossBookLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = os.path.join(self.tmp.name, 'app')
        self.data = os.path.join(self.app, 'data')
        self.graph_dir = os.path.join(self.data, 'kg')
        self.out = os.path.join(self.tmp.name, 'out')
        os.makedirs(self.graph_dir)
        self.links = copy.deepcopy(C.CROSS_LINKS)
        self.sources, self.graphs = {}, {}
        for item in self.links:
            for endpoint in ('source', 'target'):
                code, nid = item[endpoint].split(':', 1)
                graph = self.graphs.setdefault(code, {'meta': {}, 'nodes': [], 'edges': []})
                if not any(node['id'] == nid for node in graph['nodes']):
                    graph['nodes'].append({'id': nid, 'label': item[endpoint + '_label'],
                                           'kind': 'person' if code == 'B59' else 'discipline',
                                           'type': '人物' if code == 'B59' else '篇章'})
            for evidence in item['evidence']:
                text = '段落前文。' + evidence['quote'] + '段落后文。'
                evidence['sha256'] = hashlib.sha256(text.encode()).hexdigest()
                self.sources.setdefault(evidence['code'], []).append({
                    'id': evidence['anchor'], '篇': evidence['chapter'], '段': 8, '文本': text})
        # An ordinary existing relationship must remain independent of cross-links.
        self.graphs['B59']['nodes'].append({'id': 'D-考古', 'label': '考古', 'kind': 'discipline'})
        self.old_edge = {'id': 'OLD-PWZ-DISCIPLINE', 'source': 'P-裴文中', 'target': 'D-考古',
                         'rel': '学科', 'kind': 'discipline', 'note': '考古学家',
                         'evidence': {'anchor': 'B59-08-P08'}}
        self.graphs['B59']['edges'].append(self.old_edge)
        for code, graph in self.graphs.items():
            os.makedirs(os.path.join(self.out, code))
            self.write_json(os.path.join(self.out, code, 'book.json'), {'book': code})
            self.write_json(os.path.join(self.graph_dir, code + '.json'), graph)
            self.write_sources(code)
        self.write_json(os.path.join(self.data, 'library.json'), {
            'books': {code: {'book': code} for code in self.graphs}})
        self.patches = [patch.object(KG, 'APP_DIR', self.app), patch.object(KG, 'OUT', self.out),
                        patch.object(KG, 'KGDIR', self.graph_dir),
                        patch.object(KG, 'REQFILE', os.path.join(self.graph_dir, 'requests.json')),
                        patch.object(A.E, 'OUT', self.out), patch.object(C, 'CROSS_LINKS', self.links),
                        patch.dict(C.FACTS, {}, clear=True),
                        patch.object(A, 'REVIEW_FILE', os.path.join(self.data, 'reviews.json')),
                        patch.object(store, 'library_rows', return_value=[
                            {'code': code, 'book': code, 'updated_at': ''} for code in self.graphs])]
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
            for row in self.sources[code]:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    def test_scoped_contract_includes_existing_endpoints_and_both_literal_sources(self):
        view = KG.view_graph(codes=['B59', 'YC'])
        self.assertEqual(len(view['cross_links']), 1)
        link = view['cross_links'][0]
        self.assertEqual(link['id'], 'XL-B59-YC-LUXUN')
        self.assertEqual(link['basis'], '共同人物')
        self.assertEqual(link['via'], '鲁迅')
        node_ids = {node['id'] for node in view['nodes']}
        self.assertIn(link['source'], node_ids)
        self.assertIn(link['target'], node_ids)
        self.assertEqual({ev['code'] for ev in link['evidence']}, {'B59', 'YC'})
        for ev in link['evidence']:
            segment = next(row for row in self.sources[ev['code']] if row['id'] == ev['anchor'])
            self.assertIn(ev['quote'], segment['文本'])
            self.assertEqual(ev['label'], segment['篇'] + ' 第8段')
            self.assertEqual(set(ev), {'code', 'anchor', 'quote', 'label'})
        self.assertNotIn('asset_id', link)

    def test_empty_single_and_unrelated_scopes_have_no_cross_links(self):
        for codes in ([], ['B59'], ['B66'], ['YC'], ['B66', 'YC']):
            with self.subTest(codes=codes):
                self.assertEqual(KG.view_graph(codes=codes)['cross_links'], [])
        self.assertEqual(KG.view_graph('B59')['cross_links'], [])
        self.assertEqual(len(KG.view_graph()['cross_links']), 2)
        self.assertEqual(len(KG.view_graph(codes=['YC', 'B59', 'YC', 'B66'])['cross_links']), 2)

    def test_unselected_book_is_not_read_to_find_additional_connections(self):
        with patch.object(KG, 'read_json', wraps=KG.read_json) as read, \
                patch.object(KG, 'load_jsonl', wraps=KG.load_jsonl) as rows:
            KG.view_graph(codes=['B59', 'YC'])
        for observed in (read, rows):
            self.assertFalse(any('/B66/' in call.args[0] or call.args[0].endswith('/B66.json')
                                 for call in observed.call_args_list))

    def test_any_context_change_even_outside_excerpt_retracts_connection(self):
        for code in ('B59', 'YC'):
            with self.subTest(code=code):
                original = copy.deepcopy(self.sources[code])
                self.sources[code][0]['文本'] += '后来修改了原文中的上下文。'
                self.write_sources(code)
                self.assertEqual(KG.view_graph(codes=['B59', 'YC'])['cross_links'], [])
                self.sources[code] = original
                self.write_sources(code)
                self.assertEqual(len(KG.view_graph(codes=['B59', 'YC'])['cross_links']), 1)

    def test_missing_duplicate_wrong_chapter_or_suspect_source_is_not_admitted(self):
        original = copy.deepcopy(self.sources['YC'])
        for mutation in ('missing', 'duplicate', 'chapter', 'suspect'):
            with self.subTest(mutation=mutation):
                self.sources['YC'] = copy.deepcopy(original)
                if mutation == 'missing':
                    self.sources['YC'] = []
                elif mutation == 'duplicate':
                    self.sources['YC'].append(copy.deepcopy(self.sources['YC'][0]))
                elif mutation == 'chapter':
                    self.sources['YC'][0]['篇'] = '另一篇'
                else:
                    self.sources['YC'][0]['source_layout_suspect'] = True
                self.write_sources('YC')
                self.assertEqual(KG.view_graph(codes=['B59', 'YC'])['cross_links'], [])

    def test_missing_renamed_or_ambiguous_endpoint_is_not_admitted(self):
        original = copy.deepcopy(self.graphs['YC'])
        for mutation in ('missing', 'renamed', 'duplicate'):
            with self.subTest(mutation=mutation):
                graph = copy.deepcopy(original)
                if mutation == 'missing':
                    graph['nodes'] = []
                elif mutation == 'renamed':
                    graph['nodes'][0]['label'] = '另一个篇章'
                else:
                    graph['nodes'].append(copy.deepcopy(graph['nodes'][0]))
                self.write_json(os.path.join(self.graph_dir, 'YC.json'), graph)
                self.assertEqual(KG.view_graph(codes=['B59', 'YC'])['cross_links'], [])

    def test_cross_links_do_not_modify_graph_edges_materials_or_files(self):
        aid = KG.relation_asset_id('B59', self.old_edge['id'])
        paths = [os.path.join(self.graph_dir, code + '.json') for code in self.graphs]
        paths += [os.path.join(self.out, code, 'segments.jsonl') for code in self.sources]
        def fingerprints():
            result = {}
            for path in paths:
                with open(path, 'rb') as stream:
                    result[path] = hashlib.sha256(stream.read()).hexdigest()
            return result
        before_files = fingerprints()
        with patch.object(C, 'CROSS_LINKS', ()):
            before_view = KG.view_graph(codes=['B59', 'YC'])
            before_asset = A.get_asset(aid)
        after_view = KG.view_graph(codes=['B59', 'YC'])
        after_asset = A.get_asset(aid)
        for key in ('nodes', 'edges', 'meta'):
            self.assertEqual(before_view[key], after_view[key])
        self.assertEqual(before_asset, after_asset)
        link_id = KG.relation_asset_id('B59', after_view['cross_links'][0]['id'])
        self.assertIsNone(A.get_asset(link_id))
        self.assertEqual(fingerprints(), before_files)


if __name__ == '__main__':
    unittest.main()
