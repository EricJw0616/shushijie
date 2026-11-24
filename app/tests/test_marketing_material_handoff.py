"""Marketing material handoff creates one task without adopting or approving it."""
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
import projects as P
import store


class MarketingMaterialHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, 'data')
        self.out = os.path.join(self.tmp.name, 'out')
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.out, 'B01'))
        patches = [patch.object(store, 'DATA', self.data), patch.object(A.E, 'OUT', self.out),
                   patch.object(A, 'REVIEW_FILE', os.path.join(self.data, 'reviews.json')),
                   patch.object(P, 'DIR', os.path.join(self.data, 'projects')),
                   patch.object(store, 'library_rows', return_value=[{'code': 'B01', 'book': '测试书'}]),
                   patch.object(store, 'editor_flags', return_value={}),
                   patch.object(store, 'marketing_flags', return_value={})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.segment = {'id': 'B01-01-P01', '文本': '书中介绍了观察日常植物的方法。'}
        self.write('segments.jsonl', self.segment, jsonl=True)
        self.write('book.json', {'篇数': 1})
        self.write('understanding.json', {'quotes': [{'seg': self.segment['id'], 'quote': self.segment['文本']}]})
        self.write('marketing.json', {'items': {'summary': {'name': '内容简介',
                   'value': {'text': '这本书介绍日常植物观察。'},
                   'evidence': [{'seg': self.segment['id'], 'quote': self.segment['文本']}]}}})
        self.asset = next(a for a in A.all_assets() if a['kind'] == 'marketing')
        self.body = {'kind': 'marketing', 'title': '植物阅读推广',
                     'brief': {'source_code': 'B01', 'topic': '日常植物'},
                     'marketing_asset_id': self.asset['id'],
                     'request_id': 'handoff-000000000001'}

    def write(self, name, data, jsonl=False):
        with open(os.path.join(self.out, 'B01', name), 'w') as handle:
            json.dump(data, handle, ensure_ascii=False)
            if jsonl:
                handle.write('\n')

    def test_pending_material_is_pinned_without_adoption_or_global_approval(self):
        p = P.create_project(self.body)
        stored = P.get_project(p['id'])
        self.assertEqual(len(stored['items']), 1)
        item = stored['items'][0]
        self.assertEqual(item['status'], 'selected')
        self.assertEqual(item['snapshot']['status'], 'review')
        self.assertEqual(item['asset_revision'], self.asset['revision'])
        self.assertEqual(item['snapshot']['evidence'], self.asset['evidence'])
        self.assertEqual(A.get_asset(self.asset['id'])['status'], 'review')
        self.assertEqual(stored['draft'], '')
        self.assertEqual(stored['draft_asset_ids'], [])
        self.assertIsNone(stored['draft_review'])
        self.assertEqual(stored['status'], 'draft')

    def test_reviewed_material_keeps_its_content_version_without_becoming_adopted(self):
        reviewed = A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'],
                                   'status': 'approved', 'text': '编辑修订后的植物观察简介。'})
        p = P.create_project(self.body)
        item = p['items'][0]
        self.assertEqual(item['asset_revision'], reviewed['revision'])
        self.assertEqual(item['snapshot']['text'], reviewed['text'])
        self.assertEqual(item['snapshot']['status'], 'approved')
        self.assertEqual(item['status'], 'selected')

    def test_invalid_rejected_and_non_marketing_assets_leave_no_project(self):
        quote = next(a for a in A.all_assets() if a['kind'] == 'quote')
        for aid in ('B01:marketing:missing', '', None, quote['id']):
            with self.subTest(aid=aid), self.assertRaises(ValueError):
                P.create_project(dict(self.body, marketing_asset_id=aid))
            self.assertEqual(P.list_projects(), [])
        A.review_asset({'id': self.asset['id'], 'revision': self.asset['revision'], 'status': 'rejected'})
        with self.assertRaises(ValueError):
            P.create_project(self.body)
        self.assertEqual(P.list_projects(), [])

    def test_wrong_project_kind_mixed_material_and_scope_leave_no_project(self):
        invalid = [dict(self.body, kind='editorial'), dict(self.body, relation_asset_id='B01:relation:any'),
                   dict(self.body, brief={}), dict(self.body, brief={'source_code': 'B02'}),
                   dict(self.body, brief={'marketing_task': 'reposition', 'source_code': 'B02'}),
                   dict(self.body, brief={'marketing_task': 'theme', 'source_code': 'B01', 'target_codes': ['B02']}),
                   dict(self.body, brief={'marketing_task': 'channel', 'source_code': 'B01', 'target_codes': []})]
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(ValueError):
                P.create_project(body)
            self.assertEqual(P.list_projects(), [])

    def test_each_task_uses_its_own_scope_and_incomplete_drafts_remain_allowed(self):
        briefs = [{'source_code': 'B01'}, {'marketing_task': 'reposition', 'source_code': 'B01'},
                  {'marketing_task': 'theme', 'target_codes': ['B01']},
                  {'marketing_task': 'channel', 'target_codes': ['B01'], 'channels': []}]
        for index, brief in enumerate(briefs):
            body = dict(self.body, brief=brief, request_id='handoff-task-%016d' % index)
            p = P.create_project(body)
            self.assertEqual(p['items'][0]['snapshot']['code'], 'B01')
        self.assertEqual(len(P.list_projects()), 4)

    def test_retried_and_concurrent_requests_return_one_project(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: P.create_project(copy.deepcopy(self.body)), range(4)))
        self.assertEqual(len({p['id'] for p in results}), 1)
        self.assertEqual(len(P.list_projects()), 1)
        p = results[0]
        changed = P.update_project(p['id'], {'revision': p['revision'], 'action': 'save', 'title': '后续编辑'})['project']
        replay = P.create_project(self.body)
        self.assertEqual(replay['id'], changed['id'])
        self.assertEqual(replay['title'], '后续编辑')
        self.assertEqual(replay['revision'], changed['revision'])
        self.assertEqual(len(replay['items']), 1)

    def test_same_key_with_changed_create_content_conflicts_without_writes(self):
        p = P.create_project(self.body)
        before = store.read_json(P._path(p['id']))
        for changes in ({'title': '另外一个项目'}, {'brief': {'source_code': 'B01', 'topic': '新主题'}},
                        {'marketing_asset_id': 'B01:marketing:missing'}):
            with self.subTest(changes=changes), self.assertRaises(A.Conflict):
                P.create_project(dict(self.body, **changes))
            self.assertEqual(store.read_json(P._path(p['id'])), before)
        self.assertEqual(len(P.list_projects()), 1)

    def test_invalid_request_keys_fail_without_projects_and_optional_key_is_supported(self):
        for request_id in ('short', '../../bad-request-key', 123, 'a' * 81):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                P.create_project(dict(self.body, request_id=request_id))
            self.assertEqual(P.list_projects(), [])
        body = dict(self.body)
        body.pop('request_id')
        self.assertEqual(len(P.create_project(body)['items']), 1)

    def test_failed_save_can_retry_without_leaving_an_empty_project(self):
        with patch.object(store, 'write_json', side_effect=OSError('simulated failed save')):
            with self.assertRaises(OSError):
                P.create_project(self.body)
        self.assertEqual(P.list_projects(), [])
        self.assertEqual(len(P.create_project(self.body)['items']), 1)
        self.assertEqual(len(P.list_projects()), 1)

    def test_material_changes_keep_original_snapshot_and_mark_project_reference_stale(self):
        p = P.create_project(self.body)
        snapshot = copy.deepcopy(p['items'][0]['snapshot'])
        self.segment['文本'] += '这是后来补充的内容。'
        self.write('segments.jsonl', self.segment, jsonl=True)
        current = P.get_project(p['id'])
        self.assertTrue(current['items'][0]['stale'])
        self.assertEqual(current['items'][0]['snapshot'], snapshot)
        self.assertEqual(P.create_project(self.body)['items'][0]['snapshot'], snapshot)

    def test_duplicate_add_keeps_existing_selection_and_revision(self):
        p = P.create_project(self.body)
        P.update_project(p['id'], {'revision': p['revision'], 'action': 'update_item',
                                  'asset_id': self.asset['id'], 'status': 'not_fit'})
        before = store.read_json(P._path(p['id']))
        with self.assertRaises(ValueError):
            P.update_project(p['id'], {'revision': before['revision'], 'action': 'add_asset',
                                      'asset_id': self.asset['id']})
        self.assertEqual(store.read_json(P._path(p['id'])), before)
        self.assertEqual(A.get_asset(self.asset['id'])['status'], 'review')

    def test_collecting_marketing_candidate_preserves_delivered_legacy_draft_until_adoption(self):
        quote = next(a for a in A.all_assets() if a['kind'] == 'quote')
        A.review_asset({'id': quote['id'], 'revision': quote['revision'], 'status': 'approved'})
        p = P.create_project({'kind': 'marketing', 'title': '已有营销稿', 'brief': {'source_code': 'B01'}})
        def update(project, action, **fields):
            return P.update_project(project['id'], {'revision': project['revision'], 'action': action, **fields})['project']
        p = update(p, 'add_asset', asset_id=quote['id'])
        p = update(p, 'update_item', asset_id=quote['id'], status='adopted')
        p = update(p, 'save', draft='这本书提供了植物观察的方法。', draft_asset_ids=[quote['id']])
        p = update(p, 'review')
        p = update(p, 'export', mode='approved')
        self.assertFalse(P._explicit_draft_scope(p))
        self.assertEqual(p['status'], 'delivered')
        original = copy.deepcopy(p)
        p = update(p, 'add_asset', asset_id=self.asset['id'])
        for key in ('draft', 'draft_asset_ids', 'draft_asset_revisions', 'draft_review', 'status', 'exports', 'brief'):
            self.assertEqual(p[key], original[key], key)
        candidate = next(i for i in p['items'] if i['asset_id'] == self.asset['id'])
        self.assertEqual(candidate['status'], 'selected')
        self.assertEqual(candidate['current_status'], 'review')
        self.assertFalse(p['draft_outdated'])
        self.assertEqual(p['revision'], original['revision'] + 1)
        p = update(p, 'update_item', asset_id=self.asset['id'], status='adopted')
        self.assertIsNone(p['draft_review'])
        self.assertEqual(p['status'], 'draft')
        self.assertEqual(p['draft'], original['draft'])
        self.assertEqual(p['exports'], original['exports'])
        with self.assertRaises(ValueError):
            update(p, 'export', mode='approved')


if __name__ == '__main__':
    unittest.main()
