# -*- coding: utf-8 -*-
"""Read-only project aggregation, pagination and interrupted task visibility."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_records as records
import projects
import project_assist
import store


class ProjectRecordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project_dir = os.path.join(self.tmp.name, 'projects')
        self.run_dir = os.path.join(self.tmp.name, 'runs')
        self.patches = [patch.object(projects, 'DIR', self.project_dir),
                        patch.object(project_assist, 'DIR', self.run_dir)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def project(self, number, **fields):
        pid = 'prj-%016x' % number
        p = {'id': pid, 'title': '项目%d' % number, 'kind': 'editorial', 'status': 'draft',
             'created_at': '2026-11-18T08:00:00+08:00', 'updated_at': '2026-11-18T08:00:00+08:00',
             'items': [], 'exports': [], 'feedback': [], 'brief': {}, 'draft': ''}
        p.update(fields)
        store.write_json(os.path.join(self.project_dir, pid + '.json'), p)
        return p

    def create_run(self, number, project, **fields):
        rid = 'assist-%016x' % number
        r = {'id': rid, 'project_id': project['id'], 'status': 'done', 'capability': 'draft',
             'created_at': '2026-11-18T09:00:00+08:00', 'finished_at': '2026-11-18T09:01:00+08:00'}
        r.update(fields)
        store.write_json(os.path.join(self.run_dir, rid + '.json'), r)
        return r

    def test_multiple_generations_stay_one_row_with_metadata_only(self):
        p = self.project(1, title='跨书方案', draft='PRIVATE-DRAFT',
                         brief={'topic': '关系', 'audience': '学生', 'goal': '设计讨论册', 'new_book_brief': 'PRIVATE-BRIEF'},
                         items=[{'status': 'adopted', 'snapshot': {'book': '图书甲', 'text': 'PRIVATE-SOURCE'}},
                                {'status': 'selected', 'snapshot': {'book': '图书甲'}},
                                {'status': 'not_fit', 'snapshot': {'book': '图书乙'}}],
                         exports=[{'created_at': '2026-11-18T08:30:00+08:00', 'text': 'PRIVATE-EXPORT'}],
                         feedback=[{'outcome': 'not_used', 'created_at': '2026-11-18T08:31:00+08:00'},
                                   {'outcome': 'needs_revision', 'created_at': '2026-11-18T08:31:00+08:00'}])
        empty = self.project(2)
        self.create_run(1, p, capability='recommend', snapshot={'materials': ['PRIVATE-SNAPSHOT']})
        latest = self.create_run(2, p, created_at='2026-11-18T10:00:00+08:00',
                          finished_at='2026-11-18T10:02:00+08:00', markdown='PRIVATE-RESULT')
        path = os.path.join(self.project_dir, p['id'] + '.json')
        with open(path, 'rb') as f:
            before = f.read()
        with patch.object(project_assist, 'list_runs', side_effect=AssertionError('must not validate sources')):
            out = records.list_records()
        self.assertEqual(out['total'], 2)
        a, b = out['items']
        self.assertEqual(a['id'], p['id']); self.assertEqual(a['run_count'], 2)
        self.assertEqual(a['latest_run']['id'], latest['id'])
        self.assertEqual(a['last_activity_at'], latest['finished_at'])
        self.assertEqual(a['source_books'], ['图书甲', '图书乙'])
        self.assertEqual(a['item_count'], 3); self.assertEqual(a['adopted_count'], 1)
        self.assertEqual(a['export_count'], 1); self.assertEqual(a['feedback_count'], 2)
        self.assertEqual(a['last_outcome'], 'needs_revision'); self.assertTrue(a['has_draft'])
        self.assertEqual(b['id'], empty['id']); self.assertIsNone(b['latest_run'])
        self.assertIsNone(b['last_outcome']); self.assertFalse(b['has_draft'])
        self.assertNotIn('PRIVATE-', json.dumps(out))
        self.assertEqual(set(a['latest_run']), {'id', 'status', 'result_status', 'capability', 'created_at'})
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), before)

        # A successful task can finish without useful matches; expose only its
        # outcome so the index need not label that task as a successful result.
        self.create_run(3, p, created_at='2026-11-18T11:00:00+08:00', capability='recommend',
                        result={'status': 'insufficient_materials', 'gaps': ['PRIVATE-GAP']})
        latest = records.list_records()['items'][0]['latest_run']
        self.assertEqual(latest['status'], 'done')
        self.assertEqual(latest['result_status'], 'insufficient_materials')
        self.assertNotIn('PRIVATE-', json.dumps(records.list_records()))

    def test_prompt_generation_is_visible_without_exposing_the_confirmed_manuscript(self):
        p = self.project(1, kind='marketing', draft='PRIVATE-CONFIRMED-OUTLINE')
        self.create_run(1, p, capability='video_prompts',
                        snapshot={'confirmed_draft': p['draft']},
                        result={'status': 'ok', 'video_prompts': {'shots': ['PRIVATE-PROMPT']}})
        result = records.list_records(kind='marketing')
        self.assertEqual(result['items'][0]['run_count'], 1)
        self.assertEqual(result['items'][0]['latest_run']['capability'], 'video_prompts')
        self.assertNotIn('PRIVATE-', json.dumps(result))

    def test_search_type_pagination_and_counts(self):
        self.project(1, title='ALPHA关系', brief={'goal': '课堂讨论'})
        self.project(2, title='Beta', kind='marketing', items=[{'snapshot': {'book': '关系之书'}}],
                     updated_at='2026-11-18T09:00:00+08:00')
        self.project(3, title='关系再读', updated_at='2026-11-18T10:00:00+08:00')
        first = records.list_records(q='关系', limit='1')
        second = records.list_records(q='关系', limit=1, offset=1)
        self.assertEqual(first['total'], 3); self.assertNotEqual(first['items'][0]['id'], second['items'][0]['id'])
        self.assertEqual(records.list_records(q='alpha')['total'], 1)
        self.assertEqual(records.list_records(q='课堂')['total'], 1)
        filtered = records.list_records(q='关系', kind='marketing')
        self.assertEqual(filtered['total'], 1)
        self.assertEqual(filtered['counts'], {'total': 3, 'editorial': 2, 'marketing': 1})
        self.assertEqual(records.list_records(limit=1000)['limit'], 100)
        self.assertEqual(records.list_records(offset=100)['items'], [])
        for args in ({'offset': -1}, {'limit': 0}, {'limit': 'nan'}, {'kind': 'other'}):
            with self.assertRaises(ValueError):
                records.list_records(**args)

    def test_interrupted_runs_do_not_stay_running_and_shared_jobs_are_read_once(self):
        a, b, c = [self.project(i) for i in range(1, 4)]
        self.create_run(1, a, status='running', job_id='missing')
        self.create_run(2, b, status='queued', job_id='shared')
        self.create_run(3, c, status='running', job_id='shared')
        with patch.object(store, 'get_job', side_effect=lambda jid: None if jid == 'missing' else
                          {'status': 'failed', 'finished_at': '2026-11-18T11:00:00+08:00'}) as get_job:
            out = records.list_records()
        self.assertTrue(all(r['latest_run']['status'] == 'failed' for r in out['items']))
        self.assertEqual(get_job.call_count, 2)
        self.assertEqual(out['items'][0]['last_activity_at'], '2026-11-18T11:00:00+08:00')
        with patch.object(store, 'get_job', return_value={'status': 'running'}):
            self.assertTrue(all(r['latest_run']['status'] == 'running' for r in records.list_records()['items']))
        with patch.object(store, 'get_job', return_value={'status': 'done'}):
            self.assertTrue(all(r['latest_run']['status'] == 'failed' for r in records.list_records()['items']))

    def test_marketing_scenes_preserve_legacy_projects_and_ignore_invalid_channels(self):
        channel = self.project(1, kind='marketing', brief={
            'marketing_task': 'channel', 'channels': ['公众号', '短视频', '公众号', '未知渠道', None, {}]})
        legacy = self.project(2, kind='marketing', brief={'channel': '公众号'})
        planning = self.project(3, kind='marketing', brief={
            'marketing_task': 'reposition', 'channels': ['短视频']})
        editorial = self.project(4, brief={'marketing_task': 'channel', 'channels': ['公众号']})
        malformed = self.project(5, kind='marketing', brief={'marketing_task': 'channel', 'channels': '公众号'})
        before = {}
        for name in os.listdir(self.project_dir):
            with open(os.path.join(self.project_dir, name), 'rb') as f:
                before[name] = f.read()

        result = {row['id']: row for row in records.list_records()['items']}
        self.assertEqual(result[channel['id']]['marketing_scenes'], ['公众号', '短视频'])
        self.assertEqual(result[legacy['id']]['marketing_scenes'], ['planning'])
        self.assertEqual(result[planning['id']]['marketing_scenes'], ['planning'])
        self.assertEqual(result[editorial['id']]['marketing_scenes'], [])
        self.assertEqual(result[malformed['id']]['marketing_scenes'], [])
        for name, content in before.items():
            with open(os.path.join(self.project_dir, name), 'rb') as f:
                self.assertEqual(f.read(), content)

    def test_scene_filter_runs_before_pagination_and_combines_with_search(self):
        first = self.project(1, title='植物公众号', kind='marketing', brief={
            'marketing_task': 'channel', 'channels': ['公众号']}, updated_at='2026-11-18T10:00:00+08:00')
        both = self.project(2, title='植物多场景', kind='marketing', brief={
            'marketing_task': 'channel', 'channels': ['公众号', '短视频']}, updated_at='2026-11-18T11:00:00+08:00')
        self.project(3, kind='marketing', brief={
            'marketing_task': 'channel', 'channels': ['短视频']}, updated_at='2026-11-18T12:00:00+08:00')
        plan = self.project(4, kind='marketing', updated_at='2026-11-18T13:00:00+08:00')
        self.project(5, title='植物选题', updated_at='2026-11-18T14:00:00+08:00')

        page = records.list_records(kind='marketing', scene='公众号', limit=1)
        self.assertEqual(page['total'], 2)
        self.assertEqual([row['id'] for row in page['items']], [both['id']])
        second = records.list_records(kind='marketing', scene='公众号', limit=1, offset=1)
        self.assertEqual([row['id'] for row in second['items']], [first['id']])
        self.assertEqual(second['counts'], {'total': 5, 'editorial': 1, 'marketing': 4})
        self.assertEqual(records.list_records(scene='短视频')['total'], 2)
        self.assertEqual(records.list_records(scene='短视频', q='植物')['items'][0]['id'], both['id'])
        self.assertEqual(records.list_records(scene='短视频', q='植物')['total'], 1)
        self.assertEqual(records.list_records(scene='planning')['items'][0]['id'], plan['id'])
        self.assertEqual(records.list_records(kind='editorial', scene='公众号')['total'], 0)
        self.assertEqual(records.list_records(scene='小红书')['total'], 0)

    def test_unknown_scene_returns_a_clear_error(self):
        for scene in ('不存在', 'wechat', [], None):
            with self.subTest(scene=scene):
                with self.assertRaisesRegex(ValueError, '营销场景无效'):
                    records.list_records(scene=scene)

    def test_malformed_deleted_and_orphan_records_do_not_break_the_index(self):
        p = self.project(1, items=[None, 'bad', {'snapshot': []}], brief=[], exports='bad', feedback=None)
        deleted = self.project(2, deleted=True)
        self.create_run(1, deleted)
        self.create_run(2, {'id': 'prj-0000000000000999'})
        self.create_run(5, {'id': []})
        for number, value in [(3, []), (4, None), (5, {'id': 'different'})]:
            store.write_json(os.path.join(self.project_dir, 'prj-%016x.json' % number), value)
        store.write_json(os.path.join(self.run_dir, 'assist-0000000000000003.json'), [])
        with open(os.path.join(self.run_dir, 'assist-0000000000000004.json'), 'w') as f:
            f.write('{broken json')
        out = records.list_records()
        self.assertEqual(out['total'], 1); self.assertEqual(out['items'][0]['id'], p['id'])
        self.assertEqual(out['items'][0]['run_count'], 0)
        self.assertEqual(out['items'][0]['source_books'], [])
        self.assertEqual(out['items'][0]['brief'], {'topic': '', 'audience': '', 'goal': ''})

    def test_timestamp_offsets_are_compared_chronologically(self):
        earlier = self.project(1, updated_at='2026-11-18T09:00:00+08:00')
        later = self.project(2, updated_at='2026-11-18T02:00:00Z')
        self.project(3, updated_at='invalid')
        self.assertEqual([p['id'] for p in records.list_records()['items']][:2], [later['id'], earlier['id']])

    def test_absent_directories_are_a_valid_empty_state(self):
        self.assertEqual(records.list_records(), {'items': [], 'total': 0, 'limit': 20, 'offset': 0,
                                                'counts': {'total': 0, 'editorial': 0, 'marketing': 0}})


if __name__ == '__main__':
    unittest.main()
