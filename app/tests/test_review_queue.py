"""The review queue follows intended project use, never the size of the inventory."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import assets_service as assets
import projects
import store


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = os.path.join(self.tmp.name, 'projects')
        self.asset = {
            'id': 'B01:quote:one', 'code': 'B01', 'book': '测试书', 'kind': 'quote',
            'title': '原文摘录', 'text': '原文内容', 'status': 'review',
            'revision': 'source-v1', 'evidence_valid': True, 'evidence': [],
        }
        self.current = [self.asset]
        self.patches = [patch.object(projects, 'DIR', self.directory),
                        patch.object(assets, 'all_assets', side_effect=self.lookup)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def lookup(self, code=''):
        return copy.deepcopy([a for a in self.current if not code or a['code'] == code])

    def project(self, material=True, item_status='selected', project_status='draft', **fields):
        p = projects.create_project({'kind': fields.pop('kind', 'editorial'),
                                     'title': fields.pop('title', '选题任务'),
                                     'brief': {'topic': '阅读', 'goal': '形成选题依据'}})
        p['status'] = project_status
        if material:
            p['items'] = [{'asset_id': self.asset['id'], 'asset_revision': self.asset['revision'],
                           'status': item_status, 'snapshot': copy.deepcopy(self.asset), 'note': ''}]
        p.update(fields)
        store.write_json(projects._path(p['id']), p)
        return p

    def test_unselected_inventory_and_empty_projects_are_not_work(self):
        self.assertEqual(projects.review_queue(), {'items': [], 'total': 0, 'project_count': 0})
        self.project(material=False)
        self.assertEqual(projects.review_queue()['total'], 0)

    def test_selected_material_is_grouped_across_projects_without_writes(self):
        p = self.project()
        q = self.project(kind='marketing', title='阅读推广', item_status='adopted', draft='宣传文案')
        paths = [projects._path(p['id']), projects._path(q['id'])]
        before = {path: Path(path).read_bytes() for path in paths}
        with patch.object(assets, 'all_assets', side_effect=self.lookup) as reads:
            result = projects.review_queue()
        self.assertEqual(reads.call_count, 1)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['project_count'], 2)
        row = result['items'][0]
        self.assertEqual(row['action'], 'review_asset')
        self.assertEqual(row['status'], 'review')
        self.assertEqual({p['id'], q['id']}, {x['id'] for x in row['projects']})
        self.assertEqual(row['projects'][0]['brief']['goal'], '形成选题依据')
        self.assertEqual(before, {path: Path(path).read_bytes() for path in paths})

    def test_marketing_candidates_wait_until_they_are_used_in_the_draft(self):
        p = self.project(kind='marketing', item_status='adopted')
        self.assertEqual(projects.review_queue()['total'], 0)
        p.update(draft='宣传文案', draft_asset_ids=[], draft_refs_confirmed=True)
        store.write_json(projects._path(p['id']), p)
        self.assertEqual(projects.review_queue()['total'], 0)
        p['draft_asset_ids'] = [self.asset['id']]
        store.write_json(projects._path(p['id']), p)
        self.assertEqual(projects.review_queue()['total'], 1)

    def test_not_fit_and_closed_projects_do_not_create_work(self):
        self.project(item_status='not_fit')
        for status in ('paused', 'delivered', 'used'):
            self.project(project_status=status)
        self.assertEqual(projects.review_queue()['total'], 0)

    def test_approved_material_leaves_only_after_reference_is_current(self):
        p = self.project()
        self.asset.update(status='approved', revision='approved-v2')
        result = projects.review_queue()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['action'], 'refresh_reference')
        self.assertTrue(result['items'][0]['stale'])
        p['items'][0]['asset_revision'] = self.asset['revision']
        store.write_json(projects._path(p['id']), p)
        self.assertEqual(projects.review_queue()['total'], 0)

    def test_missing_rejected_invalid_and_stale_sources_have_explicit_reasons(self):
        self.project()
        self.current = []
        row = projects.review_queue()['items'][0]
        self.assertFalse(row['asset_exists'])
        self.assertEqual(row['status'], 'missing')
        self.assertEqual(row['action'], 'replace_asset')
        self.assertIn('不存在', row['reason'])
        self.current = [self.asset]
        self.asset.update(status='rejected', evidence_valid=False, stale=True)
        row = projects.review_queue()['items'][0]
        self.assertEqual(row['action'], 'replace_asset')
        self.assertIn('已停用', row['reason'])
        self.assertIn('依据无效', row['reason'])
        self.assertIn('重新生成', row['reason'])

    def test_regenerated_summary_keeps_verified_project_reference_without_creating_work(self):
        segment = {'id': 'paragraph-1', '文本': '本书由多位学者编写。'}
        original = assets._asset('B01', '测试书', 'marketing', 'summary:old',
                                 '图书简介', '本书由多位学者编写。',
                                 [{'anchor': segment['id'], 'quote': '由多位学者编写'}],
                                 marketing_key='summary', legacy_id='summary:old')
        version = assets.digest(assets._source_version_rows([segment]))
        original.update(source_version=version, source_revision=assets.digest([original['source_revision'], version]),
                        revision='reviewed-old', evidence_valid=True, status='approved')
        self.asset = original
        p = self.project(kind='marketing', item_status='adopted', draft='现有文案',
                         draft_asset_ids=[original['id']], draft_refs_confirmed=True,
                         draft_asset_revisions={original['id']: original['revision']})
        path = Path(projects._path(p['id']))
        before = path.read_bytes()
        current = dict(original, id='B01:marketing:new', text='新版简介正文', revision='source-v2')
        self.current = [current]
        review = {key: original[key] for key in ('source_revision', 'revision', 'status')}
        segment_index = ([segment], {segment['id']: 0}, {})
        with patch.object(assets, '_reviews', return_value={original['id']: review}), \
                patch.object(store, '_seg_rows', return_value=segment_index), \
                patch.object(store, 'marketing_flags', return_value={}) as flags:
            self.assertEqual(projects.review_queue(), {'items': [], 'total': 0, 'project_count': 0})
            project = projects.get_project(p['id'])
            self.assertFalse(project['draft_outdated'])
            item = project['items'][0]
            self.assertTrue(item['archived'])
            self.assertEqual(item['replacement']['id'], current['id'])
            self.assertEqual(item['snapshot'], original)
            self.assertEqual(item['current_revision'], original['revision'])
            self.assertIsNone(assets.get_asset(original['id']))
            self.assertEqual(before, path.read_bytes())

            review['status'] = 'rejected'
            self.assertEqual(projects.review_queue()['items'][0]['action'], 'replace_asset')
            review['status'] = 'approved'
            flags.return_value = {original['legacy_id']: 'reject'}
            self.assertEqual(projects.review_queue()['total'], 1)
            flags.return_value = {}
            segment['source_structure_suspect'] = True
            self.assertEqual(projects.review_queue()['total'], 1)
            segment.pop('source_structure_suspect')
            segment['文本'] = '原书已更新。'
            self.assertEqual(projects.review_queue()['total'], 1)

    def test_reference_pending_leaves_only_after_the_draft_citation_is_resolved(self):
        old = self.asset
        usable = dict(old, id='B01:quote:usable', revision='approved-v2', status='approved')
        p = self.project(kind='marketing', item_status='adopted', draft='原稿 [S1]，保留部分 [S2]。',
                         draft_refs_confirmed=True, draft_asset_ids=[old['id'], usable['id']],
                         draft_asset_revisions={old['id']: old['revision'], usable['id']: usable['revision']},
                         draft_generation={'source_labels': {old['id']: 'S1', usable['id']: 'S2'}})
        p['items'].append({'asset_id': usable['id'], 'asset_revision': usable['revision'], 'status': 'adopted',
                           'snapshot': usable, 'note': ''})
        store.write_json(projects._path(p['id']), p)
        self.current = [usable]
        self.assertEqual(projects.review_queue()['items'][0]['action'], 'replace_asset')
        p = projects.update_project(p['id'], {'action': 'update_item', 'asset_id': old['id'],
                                             'status': 'not_fit', 'revision': p['revision']})['project']
        self.assertEqual(projects.review_queue()['total'], 1)
        save = {'action': 'reconcile_draft_refs', 'revision': p['revision'], 'asset_ids': [usable['id']]}
        with self.assertRaisesRegex(ValueError, '正文仍有'):
            projects.update_project(p['id'], save)
        save['draft'] = '保留部分 [S2]。'
        p = projects.update_project(p['id'], save)['project']
        self.assertFalse(p['draft_outdated'])
        self.assertEqual(projects.review_queue()['total'], 0)

    def test_http_route_returns_queue_contract(self):
        import server
        self.project()
        h = object.__new__(server.Handler)
        h._auth_ok = lambda: True
        h._qs = lambda: ('/api/review-queue', {})
        h._json = lambda data: data
        result = h.do_GET()
        self.assertTrue(result['ok'])
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['project_count'], 1)


if __name__ == '__main__':
    unittest.main()
