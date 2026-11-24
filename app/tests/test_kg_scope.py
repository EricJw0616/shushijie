"""CLC book selection stays explicit and never widens to the whole graph."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kg_build as KG
import qa_service
import server
import clc


class GraphFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = os.path.join(self.tmp.name, 'app')
        self.out = os.path.join(self.tmp.name, 'out')
        self.graph_dir = os.path.join(self.app, 'data', 'kg')
        os.makedirs(self.graph_dir)
        self.books = {
            'B01': {'代码': 'I', '名称': '文学'},
            'B02': {'代码': 'K'},
            'B03': {'代码': 'I247', '名称': '不应当作一级大类'},
            'B04': None,
        }
        self.write_json(os.path.join(self.app, 'data', 'library.json'), {
            'books': {code: {'book': '测试书 ' + code} for code in self.books}})
        for code, value in self.books.items():
            root = os.path.join(self.out, code)
            os.makedirs(root)
            self.write_json(os.path.join(root, 'book.json'), {'CLC': value, '原型': 'P4'})
            with open(os.path.join(root, 'segments.jsonl'), 'w', encoding='utf-8') as stream:
                stream.write(json.dumps({'id': code + '-P1', '文本': '甲遇见乙。'}, ensure_ascii=False) + '\n')
            if code != 'B04':
                self.write_json(os.path.join(self.graph_dir, code + '.json'), {
                    'meta': {'counts': {'nodes': 2, 'edges': 1}},
                    'nodes': [{'id': 'A', 'label': '甲', 'kind': 'person'},
                              {'id': 'B', 'label': '乙', 'kind': 'person'}],
                    'edges': [{'id': 'A-B', 'source': 'A', 'target': 'B', 'kind': 'relation',
                               'rel': '遇见', 'evidence': {'anchor': code + '-P1'}}],
                })
        self.patches = [patch.object(KG, 'APP_DIR', self.app), patch.object(KG, 'OUT', self.out),
                        patch.object(KG, 'KGDIR', self.graph_dir),
                        patch.object(KG, 'REQFILE', os.path.join(self.graph_dir, 'requests.json')),
                        patch.object(qa_service.E, 'OUT', self.out)]
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


class GraphScopeTests(GraphFixture, unittest.TestCase):
    def test_catalog_uses_persisted_primary_clc_and_matches_qa(self):
        with patch.object(clc, 'annotate', side_effect=AssertionError('must not reclassify')):
            rows = {row['code']: row for row in KG.catalog()}
            for code in self.books:
                self.assertEqual((rows[code]['clc_code'], rows[code]['clc_name']),
                                 qa_service._classification(code))
            self.assertEqual((rows['B02']['clc_code'], rows['B02']['clc_name']), ('K', clc.NAME['K']))
            self.assertEqual(rows['B03']['clc_code'], 'unclassified')
            self.assertEqual(rows['B04']['clc_code'], 'unclassified')
            self.assertEqual(rows['B04']['status'], '待建图')
            for code in clc.ORDER:
                self.assertEqual(KG._classification({'CLC': {'代码': code}}), (code, clc.NAME[code]))
            for value in (None, [], 'I', {'代码': []}, {'代码': 'L'}, {'代码': ' I '}, {'名称': '文学'}):
                self.assertEqual(KG._classification({'CLC': value}), ('unclassified', '未分类'))

    def test_selection_deduplicates_in_requested_order_and_loads_only_selected_graphs(self):
        with patch.object(KG, 'load_graph', wraps=KG.load_graph) as load:
            graph = KG.view_graph(codes=['B02', 'B01', 'B02'])
            self.assertEqual([call.args[0] for call in load.call_args_list], ['B02', 'B01'])
        self.assertEqual(graph['meta']['mode'], 'selection')
        self.assertEqual(graph['meta']['codes'], ['B02', 'B01'])
        self.assertEqual([book['code'] for book in graph['meta']['books']], ['B02', 'B01'])
        self.assertEqual([book['clc_code'] for book in graph['meta']['books']], ['K', 'I'])
        self.assertEqual({node['code'] for node in graph['nodes']}, {'B01', 'B02'})
        self.assertEqual(graph['meta']['counts'], {'books': 2, 'nodes': 4, 'edges': 2})
        ids = {node['id'] for node in graph['nodes']}
        self.assertTrue(all(edge['source'] in ids and edge['target'] in ids for edge in graph['edges']))

    def test_scoped_view_filters_before_any_unselected_book_or_graph_reads(self):
        for kwargs, expected in (({'code': 'B01'}, {'B01'}),
                                 ({'codes': ['B02', 'B01']}, {'B01', 'B02'}),
                                 ({'codes': []}, set())):
            with self.subTest(kwargs=kwargs), \
                    patch.object(KG, 'read_json', wraps=KG.read_json) as read, \
                    patch.object(KG, 'load_jsonl', wraps=KG.load_jsonl) as rows, \
                    patch.object(KG, '_count', wraps=KG._count) as count:
                KG.view_graph(**kwargs)
                for observed in (read, rows, count):
                    for call in observed.call_args_list:
                        path = call.args[0]
                        if path.startswith(self.out + os.sep):
                            self.assertIn(os.path.relpath(path, self.out).split(os.sep)[0], expected)
                        if path.startswith(self.graph_dir + os.sep) and path != KG.REQFILE:
                            self.assertIn(os.path.basename(path)[:-5], expected)

    def test_picker_reads_only_library_and_built_book_metadata(self):
        # A directory with a .json name is not a built graph.
        os.makedirs(os.path.join(self.graph_dir, 'B04.json'))
        with patch.object(KG, 'read_json', wraps=KG.read_json) as read, \
                patch.object(KG, 'load_jsonl', side_effect=AssertionError('must not scan rows')), \
                patch.object(KG, '_count', side_effect=AssertionError('must not count lines')), \
                patch.object(KG, 'load_graph', side_effect=AssertionError('must not read graph')):
            rows = KG.catalog(picker=True)
        self.assertEqual([row['code'] for row in rows], ['B01', 'B02', 'B03'])
        self.assertTrue(all(set(row) == {'code', 'title', 'clc_code', 'clc_name', 'status'} for row in rows))
        self.assertTrue(all(row['status'] == '已建图' for row in rows))
        self.assertEqual({call.args[0] for call in read.call_args_list}, {
            os.path.join(self.app, 'data', 'library.json'),
            *(os.path.join(self.out, code, 'book.json') for code in ('B01', 'B02', 'B03')),
        })
        self.assertEqual(rows[1]['clc_name'], clc.NAME['K'])
        self.assertEqual(rows[2]['clc_code'], 'unclassified')

    def test_empty_selection_never_loads_a_graph(self):
        with patch.object(KG, 'load_graph') as load:
            graph = KG.view_graph(codes=[])
        load.assert_not_called()
        self.assertEqual(graph['nodes'], [])
        self.assertEqual(graph['edges'], [])
        self.assertEqual(graph['meta']['codes'], [])
        self.assertEqual(graph['meta']['mode'], 'selection')

    def test_invalid_or_unbuilt_selection_fails_before_loading_any_graph(self):
        for codes in ('B01', [None], [''], ['../B01'], ['B01\n'], ['B04'],
                      ['B01', 'missing'], ['x' * 25], ['B01'] * 101):
            with self.subTest(codes=codes), patch.object(KG, 'load_graph') as load:
                with self.assertRaises(ValueError):
                    KG.view_graph(codes=codes)
                load.assert_not_called()
        with self.assertRaises(ValueError):
            KG.view_graph('B01', codes=['B02'])

    def test_global_and_legacy_single_book_keep_existing_modes(self):
        all_books = KG.view_graph()
        self.assertEqual(all_books['meta']['mode'], 'global')
        self.assertEqual(all_books['meta']['counts']['books'], 3)
        book = KG.view_graph('B02')
        self.assertEqual(book['meta']['mode'], 'book')
        self.assertEqual(book['meta']['code'], 'B02')
        self.assertEqual({node['code'] for node in book['nodes']}, {'B02'})
        self.assertEqual(KG.view_graph('missing')['nodes'], [])


class GraphScopeHTTPTests(GraphFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.patches.extend([patch.object(server, 'AUTH_USER', ''), patch.object(server, '_log'),
                             patch.object(server.traceback, 'print_exc')])
        for item in self.patches[-3:]:
            item.start()
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.worker = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.worker.join(timeout=2)
        super().tearDown()

    def get(self, path):
        connection = http.client.HTTPConnection(*self.httpd.server_address, timeout=5)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode('utf-8'))
        finally:
            connection.close()

    def test_catalog_and_selected_scope_http_contract(self):
        status, body = self.get('/api/kg/books')
        self.assertEqual(status, 200)
        self.assertEqual(body['books'][0]['clc_code'], 'I')
        status, body = self.get('/api/kg/view?codes=B02,B01,B02')
        self.assertEqual(status, 200)
        self.assertTrue(body['ok'])
        self.assertEqual(body['meta']['codes'], ['B02', 'B01'])
        self.assertEqual(body['meta']['mode'], 'selection')

    def test_picker_http_contract_is_lightweight_and_default_catalog_remains_full(self):
        with patch.object(KG, '_count', side_effect=AssertionError('must not count lines')), \
                patch.object(KG, 'load_jsonl', side_effect=AssertionError('must not scan rows')):
            status, body = self.get('/api/kg/books?view=picker')
        self.assertEqual(status, 200)
        self.assertEqual([row['code'] for row in body['books']], ['B01', 'B02', 'B03'])
        self.assertTrue(all('cards' not in row for row in body['books']))
        status, body = self.get('/api/kg/books')
        self.assertEqual(status, 200)
        self.assertEqual(len(body['books']), 4)
        self.assertTrue(all('cards' in row and 'segments' in row for row in body['books']))

    def test_blank_codes_is_empty_but_absent_codes_preserves_global_and_single(self):
        for query in ('?codes=', '?codes'):
            status, body = self.get('/api/kg/view' + query)
            self.assertEqual(status, 200)
            self.assertEqual(body['meta']['mode'], 'selection')
            self.assertEqual(body['meta']['counts']['books'], 0)
        self.assertEqual(self.get('/api/kg/view')[1]['meta']['counts']['books'], 3)
        status, body = self.get('/api/kg/view?code=B02')
        self.assertEqual(status, 200)
        self.assertEqual(body['meta']['mode'], 'book')
        self.assertEqual(body['meta']['code'], 'B02')

    def test_invalid_queries_return_400_without_graph_load(self):
        queries = ['codes=B01&codes=B02', 'code=B01&codes=B02', 'code=&codes=',
                   'codes=B01,', 'codes=,B01', 'codes=B01,,B02', 'codes=B01%0A',
                   'codes=../B01', 'codes=B04', 'codes=B01,missing',
                   'codes=' + ','.join(['B01'] * 101), 'codes=' + 'a' * 2500]
        for query in queries:
            with self.subTest(query=query), patch.object(KG, 'load_graph') as load:
                status, body = self.get('/api/kg/view?' + query)
                self.assertEqual(status, 400)
                self.assertFalse(body['ok'])
                load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
