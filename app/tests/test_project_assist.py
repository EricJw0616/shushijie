# -*- coding: utf-8 -*-
"""Task-generation isolation, source versions and safe cross-project reuse."""
import copy
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import assets_service as assets
import project_assist as assist
import projects
import store


class ProjectAssistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.asset = {'id': 'B01:quote:demo', 'code': 'B01', 'kind': 'quote', 'title': '可核对的观点',
                      'book': '测试来源', 'text': '观察与记录', 'revision': 'source-v1', 'status': 'review',
                      'evidence_valid': True, 'evidence': [{'anchor': 'B01-01-P01', 'quote': '观察与记录'}]}
        self.current = {self.asset['id']: copy.deepcopy(self.asset)}
        def fingerprint(p):
            return assets.digest([p['title'], p['brief'], p['items'], p['draft']])
        def build(p, capability, book_codes=None):
            return {'project_id': p['id'], 'capability': capability, 'profile_version': '1',
                    'input_hash': fingerprint(p), 'materials': [copy.deepcopy(self.asset)],
                    'input_asset_revisions': {self.asset['id']: self.asset['revision']}}
        self.engine = types.SimpleNamespace(PROFILE_VERSION='1', fingerprint=fingerprint,
                       build_input=Mock(side_effect=build),
                       execute=Mock(return_value={'asset_ids': [self.asset['id']], 'source_labels': {self.asset['id']: 'S1'},
                                                  'summary': '依据材料形成的建议'}),
                       render_markdown=Mock(return_value='# 讨论稿\n\n建议内容 [S1]，尚需编辑核对。'))
        self.patches = [patch.object(projects, 'DIR', os.path.join(self.tmp.name, 'projects')),
                        patch.object(assist, 'DIR', os.path.join(self.tmp.name, 'assists')),
                        patch.object(store, 'DATA', self.tmp.name),
                        patch.object(store, 'JOBDIR', os.path.join(self.tmp.name, 'jobs')),
                        patch.object(store, 'library_rows', return_value=[{'code': 'B01'}]),
                        patch.object(assets, 'all_assets', side_effect=lambda code='': list(self.current.values())),
                        patch.object(assets, 'get_asset', side_effect=lambda aid: self.current.get(aid)),
                        patch.object(assist, '_engine', return_value=self.engine)]
        for p in self.patches: p.start()
        self.p = projects.create_project({'kind': 'editorial', 'title': '通用选题任务',
                                         'brief': {'topic': '观察记录', 'goal': '形成讨论材料'}})
        self.p = self.update(self.p, 'add_asset', asset_id=self.asset['id'])
        self.p = self.update(self.p, 'update_item', asset_id=self.asset['id'], status='adopted')
        self.p = self.update(self.p, 'save', draft='原有人工正文')

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def update(self, p, action, **fields):
        return projects.update_project(p['id'], dict(action=action, revision=p['revision'], **fields))['project']

    def enqueue(self, p=None, capability='draft'):
        p = p or self.p
        return assist.enqueue(p['id'], {'revision': p['revision'], 'capability': capability})

    def add_source(self, name, text):
        aid = 'B01:quote:' + name
        self.current[aid] = dict(self.asset, id=aid, title=text, text=text,
                                 evidence=[{'anchor': 'B01-02-P01', 'quote': text}])
        return aid

    def test_review_failure_trace_is_private_and_never_changes_project(self):
        before=projects.get_project(self.p['id'])
        error=ValueError('本次内容检查未完成，请重试生成；已保存的稿件和历史记录不受影响。')
        marker='内部审查响应，不进入公开接口或任务日志'
        error.diagnostics={'stage':'semantic_review_validation','review_input':{'candidate':marker},
                           'attempts':[{'response_text':marker,'validation_error':'candidate_quote_not_found'}]}
        self.engine.execute.side_effect=error
        queued=self.enqueue();assist.execute_job(queued['job']['id'])
        path=os.path.join(assist.DIR,'.diagnostics',queued['run']['id']+'.json')
        trace=store.read_json(path)
        self.assertEqual(trace['diagnostics'],error.diagnostics)
        self.assertEqual(trace['run_id'],queued['run']['id'])
        self.assertEqual(trace['project_id'],self.p['id'])
        if os.name=='posix':
            self.assertEqual(os.stat(path).st_mode & 0o077,0)
            self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o077,0)
        public=[assist.get_run(self.p['id'],queued['run']['id']),assist.list_runs(self.p['id']),
                store.get_job(queued['job']['id'])]
        self.assertNotIn(marker,json.dumps(public,ensure_ascii=False))
        self.assertNotIn(marker,json.dumps(assist._read(self.p['id'],queued['run']['id']),ensure_ascii=False))
        self.assertEqual(public[0]['status'],'failed')
        self.assertEqual(projects.get_project(self.p['id']),before)

    def test_oversized_diagnostics_are_bounded_and_disk_error_preserves_failure(self):
        error=ValueError('本次内容检查未完成')
        error.diagnostics={'stage':'semantic_review_validation','response':'甲'*600000}
        self.engine.execute.side_effect=error
        queued=self.enqueue();assist.execute_job(queued['job']['id'])
        path=os.path.join(assist.DIR,'.diagnostics',queued['run']['id']+'.json')
        self.assertLess(os.path.getsize(path),512000)
        self.assertTrue(store.read_json(path)['diagnostics']['truncated'])
        # A separate internal trace failure does not hide or replace the job error.
        queued=self.enqueue()
        original=store.write_json
        def write(path,value):
            if '.diagnostics' in path:raise OSError('disk unavailable')
            return original(path,value)
        with patch.object(store,'write_json',side_effect=write):
            assist.execute_job(queued['job']['id'])
        self.assertEqual(assist.get_run(self.p['id'],queued['run']['id'])['error'],str(error))

    def run_with_model_result(self, p, capability, result):
        import project_intelligence as engine

        # Use the real project engine and mocked bibliographic, enrichment and model data.
        with patch.object(assist, '_engine', return_value=engine), \
                patch.object(engine, '_enrich', side_effect=lambda a: dict(a, source_quality='usable')), \
                patch.object(engine.llm, 'chat', return_value={'text': json.dumps(result, ensure_ascii=False)}):
            queued = self.enqueue(p, capability)
            assist.execute_job(queued['job']['id'])
            run = assist.get_run(p['id'], queued['run']['id'])
            self.assertEqual(run['status'], 'done', run.get('error'))
            return run

    def run_topic_comparison(self, p, ids):
        return self.run_with_model_result(p, 'recommend', {
            'suggestions': [], 'gaps': [],
            'topic_angles': [
                {'title': '比较不同生境', 'summary': '已有植物生境记录可作对照。',
                 'supported_scope': '可组一个对照样章。', 'gap': '仍缺生长条件的因果依据。',
                 'strength': 'strong', 'asset_ids': ids},
                {'title': '解释生境成因', 'summary': '现有记录以描述为主。',
                 'supported_scope': '现有记录可提供背景。', 'gap': '缺少实测过程。',
                 'strength': 'limited', 'asset_ids': []},
            ],
        })

    def test_chosen_topic_angle_scopes_draft_without_altering_other_materials(self):
        import project_intelligence as engine

        target = self.add_source('habitat', '植物的生境观察记录')
        old = projects._read(self.p['id'])
        run = self.run_topic_comparison(self.p, [target])
        self.assertEqual(projects._read(self.p['id']), old)
        self.assertFalse(run['topic_angle_choices_stale'])
        with patch.object(assets, 'review_asset') as global_review:
            p = self.update(self.p, 'adopt_topic_angle', run_id=run['id'], angle_index=0)
        global_review.assert_not_called()
        self.assertEqual(p['topic_angle']['title'], '比较不同生境')
        self.assertEqual(p['topic_angle']['asset_ids'], [target])
        self.assertEqual(projects._read(p['id'])['items'][0], old['items'][0])
        self.assertEqual(p['items'][1]['current_status'], 'review')
        self.assertEqual(p['draft'], old['draft'])
        self.assertEqual(p['brief'], old['brief'])

        fresh = self.run_with_model_result(p, 'draft', {
            'title': '比较不同生境的观察样章', 'summary': '现有植物观察记录可以对照。',
            'angles': [{'title': '比较不同生境', 'rationale': '材料记载植物生境。',
                        'reader_value': '学习观察记录', 'difference': '按生境并排阅读。',
                        'asset_ids': [target]}],
            'outline': [{'title': '对照观察', 'objective': '区分地点与生境',
                         'content': '并排阅读记录。', 'asset_ids': [target]}],
            'reuse': [{'asset_id': target, 'use': '对照小节', 'adaptations': '整理地点与生境',
                       'constraints': '描述记录可支持的范围'}],
            'gaps': [], 'next_steps': ['整理对照表'],
        })
        self.assertEqual([m['asset_id'] for m in fresh['snapshot']['materials']], [target])
        self.assertEqual(fresh['snapshot']['topic_angle'], p['topic_angle'])
        self.assertEqual(projects._read(p['id'])['draft'], old['draft'])
        with patch.object(assist, '_engine', return_value=engine):
            p = self.update(p, 'apply_generation', run_id=fresh['id'])
        self.assertEqual(p['draft_asset_revisions'], {target: self.current[target]['revision']})
        self.assertFalse(p['draft_outdated'])
        with self.assertRaisesRegex(ValueError, '待审'):
            self.update(p, 'review')
        self.current[target]['status'] = 'approved'
        p = self.update(p, 'review')
        self.assertEqual(list(p['draft_review']['assets']), [target])
        self.assertEqual(p['items'][0]['status'], 'adopted')
        self.assertEqual(p['items'][0]['current_status'], 'review')
        for mode in ('review', 'approved'):
            exported = projects.update_project(p['id'], {'revision': p['revision'], 'action': 'export', 'mode': mode})
            self.assertEqual(list(exported['export']['asset_revisions']), [target])
            p = exported['project']

    def test_topic_angle_adoption_is_atomic_for_stale_missing_or_excluded_sources(self):
        first = self.add_source('first', '植物生境的观察记录与地点')
        second = self.add_source('second', '草甸中植物的观察地点与记录')
        run = self.run_topic_comparison(self.p, [first, second])
        before = projects._read(self.p['id'])
        second_source = self.current[second]
        for unusable in (None, dict(second_source, revision='source-v2'), dict(second_source, status='rejected')):
            with self.subTest(unusable=unusable):
                if unusable is None:
                    del self.current[second]
                else:
                    self.current[second] = unusable
                with self.assertRaisesRegex(assets.Conflict, '来源材料'):
                    self.update(self.p, 'adopt_topic_angle', run_id=run['id'], angle_index=0)
                self.assertEqual(projects._read(self.p['id']), before)
                self.current[second] = second_source
        p = self.update(self.p, 'add_asset', asset_id=second)
        p = self.update(p, 'update_item', asset_id=second, status='not_fit')
        excluded = projects._read(p['id'])
        with self.assertRaisesRegex(assets.Conflict, '不采用'):
            self.update(p, 'adopt_topic_angle', run_id=run['id'], angle_index=0)
        self.assertEqual(projects._read(p['id']), excluded)
        with self.assertRaisesRegex(ValueError, '缺少可组稿'):
            self.update(p, 'adopt_topic_angle', run_id=run['id'], angle_index=1)
        self.assertEqual(projects._read(p['id']), excluded)

    def test_topic_angle_from_previous_brief_cannot_be_applied(self):
        target = self.add_source('habitat', '植物生境观察记录')
        run = self.run_topic_comparison(self.p, [target])
        moved = self.update(self.p, 'save', brief={'topic': '改做昆虫'})
        self.assertTrue(assist.get_run(moved['id'], run['id'])['topic_angle_choices_stale'])
        before = projects._read(moved['id'])
        with self.assertRaisesRegex(assets.Conflict, '选题说明已修改'):
            self.update(moved, 'adopt_topic_angle', run_id=run['id'], angle_index=0)
        self.assertEqual(projects._read(moved['id']), before)

    def test_success_stays_separate_until_explicit_apply_and_reuse_starts_fresh(self):
        old = projects._read(self.p['id'])
        out = self.enqueue(); assist.execute_job(out['job']['id'])
        self.assertEqual(projects._read(self.p['id']), old)
        run = assist.get_run(self.p['id'], out['run']['id'])
        self.assertEqual(run['status'], 'done'); self.assertFalse(run['stale'])
        p = self.update(self.p, 'apply_generation', run_id=run['id'])
        self.assertEqual(p['status'], 'draft'); self.assertIsNone(p['draft_review'])
        self.assertEqual(p['draft_asset_revisions'], {self.asset['id']: 'source-v1'})
        self.assertTrue(assist.get_run(p['id'], run['id'])['applied'])
        exported = projects.update_project(p['id'], {'action': 'export', 'revision': p['revision'], 'mode': 'review'})
        self.assertIn('### [S1]', exported['text'])
        self.assertEqual(exported['text'].count('### [S1]'), 1)
        p = exported['project']
        cloned = projects.reuse_project(p['id'], {'revision': p['revision'], 'title': '另一读者群的新任务', 'copy_materials': True})
        self.assertEqual(cloned['brief'], p['brief'])
        self.assertEqual(cloned['items'][0]['status'], 'selected')
        self.assertEqual(cloned['draft'], ''); self.assertEqual(cloned['exports'], [])
        self.assertEqual(cloned['feedback'], []); self.assertIsNone(cloned['draft_review'])
        self.assertNotIn('draft_generation', cloned)

    def test_failure_keeps_prior_result_and_human_draft(self):
        first = self.enqueue(); assist.execute_job(first['job']['id'])
        first_record = assist._read(self.p['id'], first['run']['id'])
        second = self.enqueue(); self.engine.execute.side_effect = RuntimeError('模型未返回有效结果')
        assist.execute_job(second['job']['id'])
        self.assertEqual(assist._read(self.p['id'], first['run']['id']), first_record)
        self.assertEqual(projects._read(self.p['id'])['draft'], '原有人工正文')
        self.assertEqual(assist.get_run(self.p['id'], second['run']['id'])['status'], 'failed')
        self.assertEqual(len(assist.list_runs(self.p['id'])), 2)

    def test_new_plan_delivery_marker_survives_apply_edit_and_clean_export(self):
        p=projects.create_project({'kind':'marketing','title':'信任主题营销',
            'brief':{'marketing_task':'general','topic':'信任','audience':'成年读者','goal':'介绍图书中的具体内容'}})
        p=self.update(p,'add_asset',asset_id=self.asset['id'])
        p=self.update(p,'update_item',asset_id=self.asset['id'],status='adopted')
        original_build=self.engine.build_input.side_effect
        self.engine.build_input.side_effect=lambda *args,**kwargs:{**original_build(*args,**kwargs),'plan_delivery_version':'1.0'}
        self.engine.render_markdown.return_value='# 信任主题营销\n\n## 推进安排\n\n准备公众号文章。[S1]'
        queued=self.enqueue(p);assist.execute_job(queued['job']['id'])
        p=self.update(p,'apply_generation',run_id=queued['run']['id'])
        self.assertEqual(p['draft_generation']['plan_delivery_version'],'1.0')
        p=self.update(p,'save',draft=p['draft']+'\n\n编辑确定交付一篇完整文章。')
        exported=projects.update_project(p['id'],{'action':'export','revision':p['revision'],'mode':'review'})
        self.assertEqual(exported['export']['content_kind'],'marketing_plan')
        self.assertIn('编辑确定交付一篇完整文章',exported['text'])
        self.assertNotIn('任务说明',exported['text'])
        self.assertNotIn('材料与来源',exported['text'])
        self.assertNotIn('[S1]',exported['text'])

    def test_applied_run_distinguishes_current_draft_history_and_changed_sources(self):
        out = self.enqueue(); assist.execute_job(out['job']['id'])
        rid = out['run']['id']
        p = self.update(self.p, 'apply_generation', run_id=rid)
        run = assist.get_run(p['id'], rid)
        self.assertTrue(run['applied']); self.assertTrue(run['is_current_draft'])
        self.assertFalse(run['stale']); self.assertFalse(run['source_stale'])
        p = self.update(p, 'save', draft=p['draft'] + '\n人工补充的适用性判断。')
        run = assist.get_run(p['id'], rid)
        self.assertTrue(run['applied']); self.assertFalse(run['is_current_draft'])
        self.assertTrue(run['stale']); self.assertFalse(run['source_stale'])
        self.current[self.asset['id']]['revision'] = 'new-source-version'
        run = assist.get_run(p['id'], rid)
        self.assertTrue(run['applied']); self.assertTrue(run['source_stale'])
        self.assertIn('来源材料已更新', run['source_stale_reason'])

    def test_blocked_excluded_material_stays_visible_but_cannot_reenter_approved_export(self):
        self.current[self.asset['id']]['status'] = 'approved'
        bad = dict(self.asset, id='B01:quote:broken', title='缺数材料', text='他仅天就完成了记录。', status='approved')
        self.current[bad['id']] = bad
        p = self.update(self.p, 'add_asset', asset_id=bad['id'])
        p = self.update(p, 'update_item', asset_id=bad['id'], status='adopted')
        # The engine has excluded this blocked material from its fixed input.
        out = self.enqueue(p); assist.execute_job(out['job']['id'])
        p = self.update(p, 'apply_generation', run_id=out['run']['id'])
        self.assertEqual(p['draft_asset_ids'], [self.asset['id']])
        broken_item = next(i for i in p['items'] if i['asset_id'] == bad['id'])
        self.assertEqual(broken_item['status'], 'adopted')
        self.assertEqual(broken_item['quality_issues'][0]['code'], 'missing_number')
        queue = projects.review_queue()['items']
        self.assertEqual([i['asset_id'] for i in queue], [bad['id']])
        self.assertEqual(queue[0]['action'], 'replace_asset')
        self.assertIn('疑似缺失数字', queue[0]['reason'])
        for action, extra in [('review', {}), ('export', {'mode': 'approved'})]:
            with self.assertRaisesRegex(ValueError, '文本残缺'):
                self.update(p, action, **extra)
        review_export = projects.update_project(p['id'], {'revision': p['revision'], 'action': 'export', 'mode': 'review'})
        self.assertIn('待核问题：疑似缺失数字', review_export['text'])
        p = self.update(review_export['project'], 'update_item', asset_id=bad['id'], status='not_fit')
        self.assertEqual(projects.review_queue()['total'], 0)
        p = self.update(p, 'review')
        exported = projects.update_project(p['id'], {'revision': p['revision'], 'action': 'export', 'mode': 'approved'})
        self.assertNotIn(bad['text'], exported['text'])
        self.assertIn('### [S1]', exported['text'])

    def test_manual_revision_preserves_uncited_adopted_baseline(self):
        self.current[self.asset['id']]['status'] = 'approved'
        unused = dict(self.asset, id='B01:quote:unused', title='另一条背景材料', text='补充视角', status='approved')
        self.current[unused['id']] = unused
        p = self.update(self.p, 'add_asset', asset_id=unused['id'])
        p = self.update(p, 'update_item', asset_id=unused['id'], status='adopted')
        out = self.enqueue(p); assist.execute_job(out['job']['id'])
        p = self.update(p, 'apply_generation', run_id=out['run']['id'])
        p = self.update(p, 'save', draft=p['draft'] + '\n编辑补充。')
        self.assertEqual(p['draft_asset_ids'], [self.asset['id']])
        self.assertEqual(set(p['draft_asset_revisions']), {self.asset['id'], unused['id']})
        self.assertFalse(p['draft_outdated'])
        self.assertEqual(self.update(p, 'review')['status'], 'approved')

    def test_reconcile_canceled_source_and_preserve_current_prose_and_history(self):
        removed_id = self.asset['id']
        retained_id = 'B01:quote:retained'
        unused_id = 'B01:quote:unused-future-source'
        self.current[removed_id]['status'] = 'approved'
        self.current[retained_id] = dict(self.asset, id=retained_id, title='保留材料', status='approved')
        self.current[unused_id] = dict(self.asset, id=unused_id, title='未引用的新材料')
        p = self.update(self.p, 'add_asset', asset_id=retained_id)
        p = self.update(p, 'update_item', asset_id=retained_id, status='adopted')
        build = self.engine.build_input.side_effect
        def build_with_both_sources(*args, **kwargs):
            snapshot = build(*args, **kwargs)
            retained = self.current[retained_id]
            snapshot['materials'].append(copy.deepcopy(retained))
            snapshot['input_asset_revisions'][retained_id] = retained['revision']
            return snapshot
        self.engine.build_input.side_effect = build_with_both_sources
        original_body = '# 讨论稿\n\n取消采用的内容 [S1]\n\n编辑保留的内容 [S2]。'
        self.engine.execute.return_value = {'asset_ids': [removed_id, retained_id],
                                            'source_labels': {removed_id: 'S1', retained_id: 'S2'}}
        self.engine.render_markdown.return_value = original_body
        queued = self.enqueue(p)
        assist.execute_job(queued['job']['id'])
        run_id = queued['run']['id']
        p = self.update(p, 'apply_generation', run_id=run_id)
        review = self.update(p, 'review')
        old_export = projects.update_project(review['id'], {'revision': review['revision'], 'action': 'export', 'mode': 'approved'})
        p = self.update(old_export['project'], 'update_item', asset_id=removed_id, status='not_fit')
        self.assertTrue(p['draft_outdated'])
        self.assertEqual(p['draft_reference_issues'][0]['kind'], 'not_adopted')
        self.assertEqual(p['draft'], original_body)
        with self.assertRaisesRegex(ValueError, 'S1'):
            self.update(p, 'reconcile_draft_refs', asset_ids=[retained_id])
        with self.assertRaisesRegex(ValueError, '核对当前稿引用'):
            self.update(p, 'review')

        p = self.update(p, 'add_asset', asset_id=unused_id)
        p = self.update(p, 'update_item', asset_id=unused_id, status='adopted')
        warning_export = projects.update_project(p['id'], {'revision': p['revision'], 'action': 'export', 'mode': 'review'})
        self.assertIn('当前稿引用待核对', warning_export['text'])
        self.assertIn('取消采用的内容 〔旧出处，待核对〕', warning_export['text'])
        self.assertIn('编辑保留的内容 [S1]。', warning_export['text'])
        p = warning_export['project']
        text = '# 讨论稿\n\n编辑保留的内容 [S2]。\n\n继续补充的编辑判断。\n\n## 来源索引\n\n- [S2] 保留材料'
        with self.assertRaisesRegex(ValueError, '只能引用本项目采用'):
            self.update(p, 'reconcile_draft_refs', asset_ids=[removed_id, retained_id], draft=text)
        p = self.update(p, 'reconcile_draft_refs', asset_ids=[retained_id], draft=text)
        self.assertEqual(p['draft'], text)
        self.assertFalse(p['draft_outdated'])
        self.assertEqual(p['draft_asset_ids'], [retained_id])
        self.assertEqual(p['draft_display_labels'], {retained_id: 'S1'})
        self.assertEqual(p['draft_generation']['source_labels'], {removed_id: 'S1', retained_id: 'S2'})
        self.assertEqual(assist._read(p['id'], run_id)['markdown'], original_body)
        self.assertEqual(projects.get_export(p['id'], old_export['export']['id'])['text'], old_export['text'])
        self.assertIsNone(p['draft_review'])
        self.assertEqual(next(i for i in p['items'] if i['asset_id'] == unused_id)['status'], 'adopted')
        p = self.update(p, 'review')
        self.assertEqual(set(p['draft_review']['assets']), {retained_id})
        review = p['draft_review']
        p = self.update(p, 'reconcile_draft_refs', asset_ids=[retained_id])
        self.assertEqual(p['draft'], text)
        self.assertEqual(p['draft_review'], review)
        p = self.update(p, 'update_item', asset_id=unused_id, note='留待另一版本使用')
        self.assertEqual(p['draft_review'], review)
        for mode in ('review', 'approved'):
            exported = projects.update_project(p['id'], {'revision': p['revision'], 'action': 'export', 'mode': mode})
            self.assertEqual(set(exported['export']['asset_revisions']), {retained_id})
            self.assertIn('编辑保留的内容 [S1]。', exported['text'])
            self.assertIn('- [S1] 保留材料', exported['text'])
            self.assertIn('### [S1] 保留材料', exported['text'])
            self.assertNotIn('[S2]', exported['text'])
            self.assertNotIn('未引用的新材料', exported['text'])
            p = exported['project']

        with self.assertRaisesRegex(ValueError, '核对当前稿引用'):
            self.update(p, 'save', draft_asset_ids=[removed_id, retained_id])
        p = self.update(p, 'save', draft=text + '\n\n重新贴入旧引用 [S1]。')
        self.assertTrue(p['draft_outdated'])
        with self.assertRaisesRegex(ValueError, 'S1'):
            self.update(p, 'review')
        review_export = projects.update_project(p['id'], {'revision': p['revision'], 'action': 'export', 'mode': 'review'})
        self.assertIn('正文仍有 原编号 S1', review_export['text'])
        self.assertIn('重新贴入旧引用 〔旧出处，待核对〕', review_export['text'])

    def test_display_labels_follow_first_use_without_changing_original_numbers(self):
        sources = {
            'a': '已取消',
            'b': '第二条原始来源',
            'c': '第三条原始来源',
            'd': '第八条原始来源',
            'e': '没有正文编号的来源',
            'f': '备用材料',
        }
        p = projects._read(self.p['id'])
        p.update(draft='第一个 [S8]，第二个 [S3]，第三个 [S2]，重复引用 [S3]。\n\n## 来源索引\n\n- [S2] 第二条原始来源',
                 draft_asset_ids=['a', 'b', 'c', 'd', 'e'],
                 draft_generation={'source_labels': {'a': 'S1', 'b': 'S2', 'c': 'S3', 'd': 'S8'}})
        p['items'] = [{'asset_id': aid, 'status': 'not_fit' if aid == 'a' else 'adopted',
                       'snapshot': dict(self.asset, id=aid, title=title),
                       'asset_revision': 'source-v1'} for aid, title in sources.items()]
        original = copy.deepcopy(p)
        self.assertEqual(projects._draft_display_labels(p), {'d': 'S1', 'c': 'S2', 'b': 'S3', 'e': 'S4'})
        exported = projects._markdown(p, p['items'][1:], 'review')
        self.assertIn('第一个 [S1]，第二个 [S2]，第三个 [S3]，重复引用 [S2]。', exported)
        self.assertIn('- [S3] 第二条原始来源', exported)
        self.assertLess(exported.index('### [S1] 第八条原始来源'), exported.index('### [S2] 第三条原始来源'))
        self.assertIn('### [S4] 没有正文编号的来源', exported)
        self.assertIn('### 备用材料', exported)
        self.assertEqual(p, original)

    def test_source_integrity_and_uncited_input_changes_block_apply(self):
        queued = self.enqueue(); assist.execute_job(queued['job']['id'])
        self.current[self.asset['id']]['text'] = '他捐出万元用于助学。'
        with self.assertRaisesRegex(assets.Conflict, '文本残缺'):
            self.update(self.p, 'apply_generation', run_id=queued['run']['id'])
        self.current[self.asset['id']] = copy.deepcopy(self.asset)
        uncited = dict(self.asset, id='B01:quote:context', title='未引述的输入上下文')
        self.current[uncited['id']] = uncited
        queued = self.enqueue()
        run = assist._read(self.p['id'], queued['run']['id'])
        run['snapshot']['input_asset_revisions'][uncited['id']] = uncited['revision']
        store.write_json(assist._path(run['id']), run)
        assist.execute_job(queued['job']['id'])
        self.current[uncited['id']]['revision'] = 'source-v2'
        with self.assertRaisesRegex(assets.Conflict, '来源材料已更新'):
            self.update(self.p, 'apply_generation', run_id=queued['run']['id'])

    def test_project_edits_during_generation_cannot_be_overwritten(self):
        queued = self.enqueue()
        p = self.update(self.p, 'save', draft='等待时继续写的人工正文')
        assist.execute_job(queued['job']['id'])
        self.assertTrue(assist.get_run(p['id'], queued['run']['id'])['stale'])
        with self.assertRaises(assets.Conflict):
            self.update(p, 'apply_generation', run_id=queued['run']['id'])
        self.assertEqual(projects._read(p['id'])['draft'], '等待时继续写的人工正文')

    def test_source_revision_or_global_rejection_blocks_apply(self):
        for change in ({'revision': 'source-v2'}, {'status': 'rejected'}):
            self.current[self.asset['id']] = copy.deepcopy(self.asset)
            queued = self.enqueue(); assist.execute_job(queued['job']['id'])
            self.current[self.asset['id']].update(change)
            self.assertTrue(assist.get_run(self.p['id'], queued['run']['id'])['stale'])
            with self.assertRaises(assets.Conflict):
                self.update(self.p, 'apply_generation', run_id=queued['run']['id'])

    def test_queued_duplicate_and_restart_failure_are_handled(self):
        first = self.enqueue(); second = self.enqueue()
        self.assertTrue(second['running']); self.assertEqual(first['run']['id'], second['run']['id'])
        self.assertEqual(self.engine.build_input.call_count, 1)
        store.update_job(first['job']['id'], status='failed', error='服务重启中断')
        self.assertEqual(assist.get_run(self.p['id'], first['run']['id'])['status'], 'failed')
        third = self.enqueue(); self.assertTrue(third['started'])
        self.assertNotEqual(first['run']['id'], third['run']['id'])

    def test_changed_brief_starts_distinct_parallel_tasks_and_old_run_cannot_overwrite(self):
        for capability in ('recommend', 'draft'):
            with self.subTest(capability=capability):
                old = self.enqueue(self.p, capability)
                current = self.update(self.p, 'save', brief={**self.p['brief'], 'audience': capability + '的新观看者'})
                new = self.enqueue(current, capability)
                self.assertTrue(new['started']); self.assertNotEqual(old['run']['id'], new['run']['id'])
                same = self.enqueue(current, capability)
                self.assertTrue(same['running']); self.assertEqual(same['run']['id'], new['run']['id'])
                assist.execute_job(old['job']['id'])
                self.assertTrue(assist.get_run(current['id'], old['run']['id'])['stale'])
                self.assertEqual(projects._read(current['id'])['draft'], '原有人工正文')
                if capability == 'draft':
                    with self.assertRaises(assets.Conflict):
                        self.update(current, 'apply_generation', run_id=old['run']['id'])
                self.p = current

    def test_recommendation_scope_is_part_of_pending_task_deduplication(self):
        with patch.object(store, 'library_rows', return_value=[{'code':'B01'},{'code':'B02'}]):
            first = assist.enqueue(self.p['id'], {'revision':self.p['revision'],'capability':'recommend','book_codes':['B01']})
            second = assist.enqueue(self.p['id'], {'revision':self.p['revision'],'capability':'recommend','book_codes':['B02']})
            same = assist.enqueue(self.p['id'], {'revision':self.p['revision'],'capability':'recommend','book_codes':['B02','B02']})
        self.assertNotEqual(first['run']['id'],second['run']['id'])
        self.assertTrue(same['running']);self.assertEqual(second['run']['id'],same['run']['id'])
        self.assertEqual(self.engine.build_input.call_count,2)

    def test_book_profile_change_marks_run_stale_and_avoids_reusing_pending_job(self):
        import marketing_context
        with patch.object(marketing_context, '_load', return_value=({},'v1')):
            first = self.enqueue()
            run = assist._read(self.p['id'], first['run']['id'])
            run['snapshot']['book_profile_revisions'] = {'B01':'v1'}
            store.write_json(assist._path(run['id']),run)
            self.assertFalse(assist.get_run(self.p['id'],run['id'])['stale'])
        with patch.object(marketing_context, '_load', return_value=({},'v2')):
            self.assertTrue(assist.get_run(self.p['id'],run['id'])['stale'])
            newer = self.enqueue()
            self.assertNotEqual(newer['run']['id'],run['id'])
            assist.execute_job(first['job']['id'])
            with self.assertRaisesRegex(assets.Conflict,'营销资料已更新'):
                self.update(self.p,'apply_generation',run_id=run['id'])
        self.assertEqual(projects._read(self.p['id'])['draft'],'原有人工正文')

    def test_scope_and_stale_revision_rejected_before_starting(self):
        for body, error in [({'revision': 0, 'capability': 'draft'}, assets.Conflict),
                            ({'revision': self.p['revision'], 'capability': 'draft', 'book_codes': ['MISSING']}, ValueError),
                            ({'revision': self.p['revision'], 'capability': 'unknown'}, ValueError)]:
            with self.assertRaises(error): assist.enqueue(self.p['id'], body)
        self.assertEqual(self.engine.build_input.call_count, 0)

    def test_unknown_model_reference_fails_without_project_write(self):
        self.engine.execute.return_value = {'asset_ids': ['UNKNOWN:quote:invented']}
        queued = self.enqueue(); assist.execute_job(queued['job']['id'])
        self.assertEqual(assist.get_run(self.p['id'], queued['run']['id'])['status'], 'failed')
        self.assertEqual(projects._read(self.p['id'])['draft'], '原有人工正文')

    def test_other_project_cannot_read_or_apply_run(self):
        queued = self.enqueue(); assist.execute_job(queued['job']['id'])
        other = projects.create_project({'title': '另一个项目'})
        with self.assertRaises(ValueError): assist.get_run(other['id'], queued['run']['id'])
        with self.assertRaises(ValueError): self.update(other, 'apply_generation', run_id=queued['run']['id'])

    def test_reuse_skips_not_fit_rejected_and_does_not_change_source(self):
        before = projects._read(self.p['id'])
        self.current[self.asset['id']]['status'] = 'rejected'
        p = projects.reuse_project(self.p['id'], {'revision': self.p['revision'], 'title': '复制说明', 'copy_materials': True})
        self.assertEqual(p['items'], []); self.assertEqual(len(p['reuse_skipped']), 1)
        self.assertEqual(projects._read(self.p['id']), before)
        p = projects.reuse_project(self.p['id'], {'revision': self.p['revision'], 'title': '仅说明', 'copy_materials': False})
        self.assertEqual(p['items'], [])
        with self.assertRaises(assets.Conflict): projects.reuse_project(self.p['id'], {'revision': 0, 'title': '错误复制'})

    def test_http_routes_return_runs_enqueue_and_reuse(self):
        import server
        h = object.__new__(server.Handler)
        h._auth_ok = lambda: True
        h._json = lambda d: d
        h._err = lambda message, status: {'error': message, 'status': status}
        h._qs = lambda: ('/api/projects/' + self.p['id'] + '/assist', {})
        h._read_json = lambda: {'revision': self.p['revision'], 'capability': 'draft'}
        with patch.object(server, '_start_job') as start:
            result = h.do_POST()
            self.assertTrue(result['started']); start.assert_called_once()
        response = h.do_GET(); self.assertEqual(len(response['runs']), 1)
        rid = result['run']['id']
        h._qs = lambda: ('/api/projects/' + self.p['id'] + '/assist/' + rid, {})
        self.assertEqual(h.do_GET()['run']['id'], rid)
        h._qs = lambda: ('/api/projects/' + self.p['id'] + '/reuse', {})
        h._read_json = lambda: {'revision': self.p['revision'], 'title': '复用任务', 'copy_materials': False}
        self.assertEqual(h.do_POST()['project']['title'], '复用任务')


if __name__ == '__main__':
    unittest.main()
