"""Marketing task contracts, isolated from the user's library and model service.

These tests verify scope, attribution, persistence and delivery behavior. Mocked
model responses do not measure writing quality or marketing effectiveness.
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import project_intelligence as I
import projects as P
import store
from test_video_production import sample_production


def material(code, number, text):
    anchor = code + '-01-P01'
    return {'id': '%s:quote:%s' % (code, number), 'code': code, 'kind': 'quote',
            'book': '来源' + code, 'title': text[:16], 'text': text,
            'revision': 'r' + str(number), 'status': 'approved', 'evidence_valid': True,
            'evidence': [{'anchor': anchor, 'seg': anchor, 'quote': text}]}


def enrich(asset):
    asset = copy.deepcopy(asset)
    asset['source_context'] = copy.deepcopy(asset['evidence'])
    asset['quality_warnings'] = []
    asset['source_quality'] = 'blocked' if asset.get('blocked') else 'usable'
    return asset


class MarketingTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rows = [material('A1', 1, '共同经历与长期陪伴构成了建立信任的故事。'),
                     material('B2', 2, '社会关系中的信任依赖具体生活规则与交往。'),
                     material('C3', 3, '观察植物需要持续记录形态的变化。')]
        self.patches = [
            patch.object(store, 'DATA', self.tmp.name),
            patch.object(P, 'DIR', os.path.join(self.tmp.name, 'projects')),
            patch.object(store, 'library_rows', return_value=[
                {'code': c, 'book': '来源' + c} for c in ('A1', 'B2', 'C3')]),
            patch.object(I.assets, 'all_assets', side_effect=lambda code='': copy.deepcopy([
                a for a in self.rows if not code or a['code'] == code])),
            patch.object(I.assets, 'get_asset', side_effect=lambda aid: copy.deepcopy(next(
                (a for a in self.rows if a['id'] == aid), None))),
            patch.object(I, '_enrich', side_effect=enrich),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def project(self, task='theme'):
        brief = {'topic': '关系中的信任', 'audience': '成年读者',
                 'goal': '用可核对的内容组织阅读讨论', 'marketing_task': task}
        if task == 'reposition':
            brief['source_code'] = 'A1'
        elif task in ('theme', 'channel'):
            brief['target_codes'] = ['A1', 'B2']
        if task == 'channel':
            brief['channels'] = ['公众号', '短视频']
        return {'id': 'project-test', 'kind': 'marketing', 'title': '关系与信任营销',
                'brief': brief, 'draft': '用户已有工作稿', 'items': [], 'revision': 1}

    def adopt(self, project, indices=(0, 1)):
        for index in indices:
            asset = copy.deepcopy(self.rows[index])
            project['items'].append({'asset_id': asset['id'], 'asset_revision': asset['revision'],
                                     'snapshot': asset, 'status': 'adopted', 'note': '本次使用'})
        return project

    def response(self, task='theme'):
        a, b = (row['id'] for row in self.rows[:2])
        result = {'title': '关系需要时间', 'summary': '根据两种材料提出可讨论的表达。',
                  'angles': [{'title': '如何建立信任', 'rationale': '材料记载了陪伴的过程。',
                              'reader_value': '帮助讨论自身经验', 'difference': '表达方式尚待实际验证',
                              'asset_ids': [a]}],
                  'outline': [{'title': '从故事进入讨论', 'objective': '引出阅读问题',
                               'content': '先呈现故事，再请读者比较自身经历。', 'asset_ids': [a]}],
                  'reuse': [{'asset_id': a, 'use': '活动开篇', 'adaptations': '增加一个提问',
                             'constraints': '引用需保留原文含义'}],
                  'gaps': [], 'next_steps': ['编辑核对后选择具体表达']}
        if task == 'theme':
            result['book_roles'] = [
                {'code': 'A1', 'role': '提供陪伴与信任的文学情境', 'asset_ids': [a]},
                {'code': 'B2', 'role': '提供理解交往规则的另一种视角', 'asset_ids': [b]},
            ]
        elif task == 'channel':
            production = I.video_production.validate(sample_production(), require_prompts=False, include_prompts=False)
            result['channel_assets'] = [
                {'channel': '公众号', 'title': '关系为什么需要时间',
                 'body': '从长期陪伴的故事开始，讨论关系怎样逐步建立。',
                 'cta': '阅读相关章节，记下自己的问题。', 'asset_ids': [a]},
                {'channel': '短视频', 'title': '信任从哪里开始',
                 'body': I.video_production.render_body(production), 'video_production': production,
                 'cta': '', 'asset_ids': [b]},
            ]
        return result

    def execute(self, snapshot, response):
        with patch.object(I.llm, 'chat', side_effect=self.model_responses(response)):
            return I.execute(snapshot)

    @staticmethod
    def model_responses(value):
        def respond(messages, **kwargs):
            result = {'accepted': True, 'issues': []} if '独立的出版内容语义预审员' in messages[0]['content'] else value
            return {'text': json.dumps(result, ensure_ascii=False), 'model': 'contract-test', 'usage': {}}
        return respond

    def call(self, project, action, **body):
        return P.update_project(project['id'], {'revision': project['revision'], 'action': action, **body})

    def test_task_arrays_survive_create_save_and_reload_without_touching_old_project(self):
        old = P.create_project({'kind': 'marketing', 'title': '已有营销项目',
                                'brief': {'source_code': 'A1', 'topic': '原有主题'}})
        old_path = P._path(old['id'])
        with open(old_path, 'rb') as handle:
            original = handle.read()
        p = P.create_project({'kind': 'marketing', 'title': '跨书主题',
                              'brief': {'marketing_task': 'theme', 'target_codes': []}})
        self.assertEqual(p['brief']['target_codes'], [])  # incomplete drafts are allowed
        brief = self.project('channel')['brief']
        p = self.call(p, 'save', brief=brief)['project']
        stored = P.get_project(p['id'])
        self.assertEqual(stored['brief']['target_codes'], ['A1', 'B2'])
        self.assertEqual(stored['brief']['channels'], ['公众号', '短视频'])
        self.assertEqual(stored['brief']['marketing_task'], 'channel')
        with open(old_path, 'rb') as handle:
            self.assertEqual(handle.read(), original)

    def test_incomplete_task_is_blocked_at_discovery_and_generation(self):
        for task, changes in [
            ('reposition', {'source_code': ''}),
            ('theme', {'target_codes': ['A1']}),
            ('theme', {'target_codes': ['A1', 'A1']}),
            ('channel', {'target_codes': []}),
            ('channel', {'channels': []}),
        ]:
            for capability in ('recommend', 'draft'):
                p = self.adopt(self.project(task)); p['brief'].update(changes)
                with self.subTest(task=task, fields=changes, capability=capability), self.assertRaises(ValueError):
                    I.build_input(p, capability)

    def test_malformed_task_fields_are_rejected_without_creating_a_project(self):
        for brief in [
            {'marketing_task': ['theme']},
            {'marketing_task': {'kind': 'theme'}},
            {'marketing_task': 'invented'},
            {'marketing_task': 'theme', 'target_codes': 'A1,B2'},
            {'marketing_task': 'theme', 'target_codes': ['A1', 2]},
            {'marketing_task': 'channel', 'channels': '公众号'},
            {'marketing_task': 'channel', 'channels': ['未知渠道']},
        ]:
            with self.subTest(brief=brief), self.assertRaises(ValueError):
                P.create_project({'kind': 'marketing', 'title': '错误任务', 'brief': brief})
        self.assertEqual(P.list_projects(), [])

    def test_unknown_target_cannot_enter_discovery_or_generation(self):
        for task in ('reposition', 'theme', 'channel'):
            for capability in ('recommend', 'draft'):
                p = self.adopt(self.project(task))
                if task == 'reposition':
                    p['brief']['source_code'] = 'UNKNOWN'
                else:
                    p['brief']['target_codes'].append('UNKNOWN')
                with self.subTest(task=task, capability=capability), self.assertRaises(ValueError):
                    I.build_input(p, capability)

    def test_reposition_requires_its_own_book_evidence(self):
        p = self.adopt(self.project('reposition'), (1,))
        with self.assertRaises(ValueError):
            I.build_input(p, 'draft')
        self.adopt(p, (0,))
        snapshot = I.build_input(p, 'draft')
        result = self.execute(snapshot, self.response('reposition'))
        self.assertIn(self.rows[0]['id'], result['asset_ids'])
        self.assertEqual(result['status'], 'needs_review')

    def test_each_promoted_book_needs_effective_adopted_evidence(self):
        for task in ('theme', 'channel'):
            with self.subTest(task=task):
                p = self.adopt(self.project(task), (0,))
                with self.assertRaises(ValueError):
                    I.build_input(p, 'draft')
                self.adopt(p, (1,))
                self.rows[1]['blocked'] = True
                with self.assertRaises(ValueError):
                    I.build_input(p, 'draft')
                self.rows[1].pop('blocked')
                self.assertEqual({m['code'] for m in I.build_input(p, 'draft')['materials']}, {'A1', 'B2'})

    def test_outside_adopted_book_is_excluded_before_version_check(self):
        for task in ('reposition', 'theme', 'channel'):
            with self.subTest(task=task):
                p = self.adopt(self.project(task), (0, 1, 2))
                outside = next(item for item in p['items'] if item['snapshot']['code'] == 'C3')
                outside['asset_revision'] = 'outdated-outside-revision'
                before = copy.deepcopy(p)
                snapshot = I.build_input(p, 'draft')
                expected = {'A1'} if task == 'reposition' else {'A1', 'B2'}
                self.assertEqual({m['code'] for m in snapshot['materials']}, expected)
                omitted = next(row for row in snapshot['excluded'] if row['asset_id'] == outside['asset_id'])
                self.assertIn('推广图书范围', omitted['reason'])
                self.assertNotIn(outside['asset_id'], snapshot['input_asset_revisions'])
                self.assertEqual(p, before)
                # An out-of-scope book must not stand in for a missing target.
                missing_code = 'A1' if task == 'reposition' else 'B2'
                p['items'] = [item for item in p['items'] if item['snapshot']['code'] != missing_code]
                with self.assertRaises(ValueError):
                    I.build_input(p, 'draft')

    def test_theme_roles_are_preserved_with_both_books_in_citations_and_export(self):
        p = self.adopt(self.project()); before = copy.deepcopy(p)
        snapshot = I.build_input(p, 'draft')
        result = self.execute(snapshot, self.response())
        self.assertEqual(p, before)
        self.assertEqual({r['code'] for r in result['book_roles']}, {'A1', 'B2'})
        self.assertEqual(set(result['asset_ids']), {a['id'] for a in self.rows[:2]})
        markdown = I.render_markdown(result, snapshot)
        for role in self.response()['book_roles']:
            self.assertIn(role['role'], markdown)
        self.assertIn('来源A1', markdown); self.assertIn('来源B2', markdown)
        self.assertIn('[S1]', markdown); self.assertIn('[S2]', markdown)

    def test_theme_rejects_missing_books_unknown_books_and_cross_book_attribution(self):
        snapshot = I.build_input(self.adopt(self.project()), 'draft')
        variants = []
        missing = self.response(); missing['book_roles'].pop(); variants.append(missing)
        absent = self.response(); absent.pop('book_roles'); variants.append(absent)
        unknown = self.response(); unknown['book_roles'][1]['code'] = 'UNKNOWN'; variants.append(unknown)
        swapped = self.response(); swapped['book_roles'][1]['asset_ids'] = [self.rows[0]['id']]; variants.append(swapped)
        forged = self.response(); forged['book_roles'][1]['asset_ids'] = ['invented']; variants.append(forged)
        duplicate = self.response(); duplicate['book_roles'][1]['code'] = 'A1'; variants.append(duplicate)
        for index, data in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.execute(snapshot, data)

    def test_channel_pack_preserves_actual_copy_and_each_channel_in_markdown(self):
        p = self.adopt(self.project('channel')); before = copy.deepcopy(p)
        snapshot = I.build_input(p, 'draft')
        result = self.execute(snapshot, self.response('channel'))
        self.assertEqual(p, before)
        self.assertEqual({r['channel'] for r in result['channel_assets']}, {'公众号', '短视频'})
        self.assertEqual(set(result['asset_ids']), {a['id'] for a in self.rows[:2]})
        markdown = I.render_markdown(result, snapshot)
        for piece in self.response('channel')['channel_assets']:
            for field in ('channel', 'title', 'body', 'cta'):
                self.assertIn(piece[field], markdown)

    def test_channel_pack_rejects_missing_unrequested_and_ungrounded_deliverables(self):
        snapshot = I.build_input(self.adopt(self.project('channel')), 'draft')
        variants = []
        missing = self.response('channel'); missing['channel_assets'].pop(); variants.append(missing)
        absent = self.response('channel'); absent.pop('channel_assets'); variants.append(absent)
        extra = self.response('channel'); extra['channel_assets'].append({
            **extra['channel_assets'][0], 'channel': '小红书'}); variants.append(extra)
        unknown = self.response('channel'); unknown['channel_assets'][1]['channel'] = '未知渠道'; variants.append(unknown)
        no_refs = self.response('channel'); no_refs['channel_assets'][1]['asset_ids'] = []; variants.append(no_refs)
        forged = self.response('channel'); forged['channel_assets'][1]['asset_ids'] = ['invented']; variants.append(forged)
        for index, data in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.execute(snapshot, data)

    def test_current_video_profile_requires_production_but_legacy_copy_still_reads(self):
        snapshot = I.build_input(self.adopt(self.project('channel')), 'draft')
        response = self.response('channel')
        scene = response['channel_assets'][1]
        scene.pop('video_production'); scene.update(body='旧版镜头与口播。', cta='翻开原书。')
        with self.assertRaisesRegex(ValueError, '缺少完整制作稿'):
            self.execute(snapshot, response)
        snapshot['profile_version'] = '1.3'
        result = self.execute(snapshot, response)
        self.assertEqual(result['channel_assets'][1]['body'], '旧版镜头与口播。')

    def test_video_generation_requests_complete_production_and_derives_copy(self):
        snapshot = I.build_input(self.adopt(self.project('channel')), 'draft')
        response = self.response('channel'); response['channel_assets'][1]['body'] = '不应覆盖结构中的真实配音。'
        response['channel_assets'][1]['cta'] = '这条结尾不能重复追加。'
        with patch.object(I.llm, 'chat', side_effect=self.model_responses(response)) as chat:
            result = I.execute(snapshot)
        self.assertIn('video_production', chat.call_args_list[0][0][0][0]['content'])
        self.assertEqual(chat.call_args_list[0].kwargs['max_tokens'], 12000)
        scene = result['channel_assets'][1]
        self.assertEqual(scene['cta'], '')
        self.assertNotIn('不应覆盖', scene['body'])
        self.assertNotIn('不能重复追加', I.render_markdown(result, snapshot))
        self.assertNotIn('#### 生成提示词', scene['body'])
        self.assertNotIn('image_prompt', scene['video_production']['shots'][0])

    def test_task_target_and_channel_changes_invalidate_generation_fingerprint(self):
        p = self.project('channel'); original = I.fingerprint(p)
        for key, value in [('marketing_task', 'theme'), ('target_codes', ['A1', 'C3']),
                           ('channels', ['小红书'])]:
            changed = copy.deepcopy(p); changed['brief'][key] = value
            with self.subTest(field=key):
                self.assertNotEqual(I.fingerprint(changed), original)

    def test_legacy_marketing_and_new_book_flows_keep_working(self):
        p = self.adopt(self.project('general'), (0,)); p['brief'].pop('marketing_task')
        p['brief']['source_code'] = 'A1'
        result = self.execute(I.build_input(p, 'draft'), self.response('general'))
        self.assertEqual(result['status'], 'needs_review')
        p['brief']['source_code'] = ''
        p['brief']['new_book_brief'] = '已确认新书讨论人际交往与信任。'
        result = self.execute(I.build_input(p, 'draft'), self.response('general'))
        self.assertEqual(result['status'], 'needs_review')

    def test_writing_notes_persist_reach_model_and_invalidate_old_generation(self):
        old = P.create_project({'kind': 'marketing', 'title': '未改动的旧项目',
                                'brief': {'source_code': 'A1', 'topic': '原有主题'}})
        with open(P._path(old['id']), 'rb') as handle:
            original = handle.read()
        p = P.create_project({'kind': 'marketing', 'title': '公众号内容',
                              'brief': self.project('channel')['brief']})
        self.assertNotIn('writing_notes', p['brief'])
        before = I.fingerprint(p)
        notes = '用孩子听得懂的话讲述，控制在300字，结尾邀请读者翻阅原书。'
        p = self.call(p, 'save', brief={**p['brief'], 'writing_notes': notes})['project']
        self.assertEqual(P.get_project(p['id'])['brief']['writing_notes'], notes)
        self.assertNotEqual(I.fingerprint(p), before)
        snapshot = I.build_input(self.adopt(p), 'draft')
        self.assertEqual(snapshot['brief']['writing_notes'], notes)
        response = self.response('channel'); response.update(next_steps=[], writing_needs=[])
        with patch.object(I.llm, 'chat', side_effect=self.model_responses(response)) as chat:
            result = I.execute(snapshot)
        messages = chat.call_args_list[0].args[0]
        payload = json.loads(messages[1]['content'].split('\n', 1)[1])
        self.assertEqual(payload['project']['brief']['writing_notes'], notes)
        self.assertEqual(result['writing_needs'], [])
        self.assertIn('写作要求', messages[0]['content'])
        self.assertIn('不自动成为原书证据', messages[0]['content'])
        self.assertIn('不要求先提供读者兴趣', messages[0]['content'])
        self.assertIn('不能悄悄换题当作完成', messages[0]['content'])
        with open(P._path(old['id']), 'rb') as handle:
            self.assertEqual(handle.read(), original)

    def test_writing_notes_have_bounded_storage_and_can_be_cleared(self):
        p = P.create_project({'kind': 'marketing', 'title': '输入长度测试',
                              'brief': {**self.project('channel')['brief'], 'writing_notes': '写' * 4001}})
        self.assertEqual(p['brief']['writing_notes'], '写' * 4000)
        p = self.call(p, 'save', brief={**p['brief'], 'writing_notes': ''})['project']
        self.assertEqual(P.get_project(p['id'])['brief']['writing_notes'], '')

    def test_marketing_allows_no_followup_work_but_editorial_keeps_its_contract(self):
        snapshot = I.build_input(self.adopt(self.project('channel')), 'draft')
        response = self.response('channel'); response.update(next_steps=[], writing_needs=[])
        result = self.execute(snapshot, response)
        self.assertEqual(result['next_steps'], [])
        editorial = copy.deepcopy(snapshot); editorial['profile'] = 'editorial'
        with self.assertRaisesRegex(ValueError, '后续验证行动'):
            self.execute(editorial, response)

    def test_writing_needs_validate_actionable_shape_and_short_message(self):
        snapshot = I.build_input(self.adopt(self.project('channel')), 'draft')
        valid = [{'kind': 'materials', 'message': '现有素材只介绍俗名，缺少植物生长过程的内容。'},
                 {'kind': 'requirements', 'message': '请确定这篇内容是活动预告还是读书短文。'}]
        response = self.response('channel'); response.update(writing_needs=valid, next_steps=[])
        self.assertEqual(self.execute(snapshot, response)['writing_needs'], valid)
        for invalid in [None, {}, [None], [{'kind': 'research', 'message': '调研市场'}],
                        [{'kind': 'materials', 'message': ''}],
                        [{'kind': 'materials', 'message': '长' * 181}],
                        [{'kind': 'materials', 'message': '第一项\n第二项'}], valid * 2]:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.execute(snapshot, {**response, 'writing_needs': invalid})

    def test_legacy_generation_without_writing_needs_remains_readable(self):
        snapshot = I.build_input(self.adopt(self.project('channel')), 'draft')
        response = self.response('channel')
        response['gaps'] = [{'issue': '旧版完整说明保留', 'next_action': '原始建议仍可查看'}]
        result = self.execute(snapshot, response)
        self.assertNotIn('writing_needs', result)
        self.assertEqual(result['gaps'], response['gaps'])
        self.assertEqual(result['channel_assets'], response['channel_assets'])

    def test_channel_working_copy_excludes_process_notes_and_keeps_needs_in_result(self):
        snapshot = I.build_input(self.adopt(self.project('channel')), 'draft')
        response = self.response('channel'); response.update(writing_needs=[], next_steps=[])
        result = self.execute(snapshot, response)
        markdown = I.render_markdown(result, snapshot)
        for generic in ['## 下一步验证', '## 资料缺口', '## 需要补充', '本次未识别出额外缺口',
                        '尚未经市场或读者验证']:
            self.assertNotIn(generic, markdown)
        message = '本次素材未包含生长过程，请选入相关章节后重写。'
        result['writing_needs'] = [{'kind': 'materials', 'message': message}]
        specific = I.render_markdown(result, snapshot)
        self.assertNotIn('## 需要补充', specific)
        self.assertNotIn(message, specific)
        self.assertEqual(result['writing_needs'][0]['message'], message)
        self.assertIn('[S1]', specific)
        self.assertIn(response['channel_assets'][0]['body'], specific)
        for process_note in ('## 材料怎样复用', '## 来源索引', '## 传播角度与受众价值', '行动引导：'):
            self.assertNotIn(process_note, specific)
        editorial = copy.deepcopy(snapshot); editorial['profile'] = 'editorial'
        result['next_steps'] = ['核对选题的具体安排']
        editorial_text = I.render_markdown(result, editorial)
        self.assertIn('## 下一步验证', editorial_text)
        self.assertIn('## 资料缺口', editorial_text)

    def test_multi_book_tasks_can_review_and_export_through_existing_workflow(self):
        for task in ('theme', 'channel'):
            with self.subTest(task=task):
                p = P.create_project({'title': '跨书交付验证', 'kind': 'marketing',
                                      'brief': self.project(task)['brief']})
                for asset in self.rows[:2]:
                    p = self.call(p, 'add_asset', asset_id=asset['id'])['project']
                    p = self.call(p, 'update_item', asset_id=asset['id'], status='adopted')['project']
                draft = '两本书分别为讨论提供不同角度。'
                if task == 'channel':
                    draft = ('## 渠道素材初稿\n\n### 公众号：书中的信任\n\n《来源A1》和《来源B2》帮助理解信任。'
                             '\n\n### 短视频：聊聊信任\n\n画面：翻开两本书。口播：今天聊聊信任。')
                p = self.call(p, 'save', draft=draft,
                              draft_asset_ids=[a['id'] for a in self.rows[:2]])['project']
                p = self.call(p, 'review', approved=True)['project']
                exported = self.call(p, 'export', mode='approved')
                if task == 'channel':
                    self.assertNotIn('已审核交付稿', exported['text'])
                    self.assertEqual(exported['export']['content_kind'], 'channel_content')
                    self.assertEqual(exported['export']['channels'], ['公众号', '短视频'])
                    self.assertNotIn('## 任务说明', exported['text'])
                    self.assertNotIn('## 材料与来源', exported['text'])
                else:
                    self.assertIn('已审核交付稿', exported['text'])
                self.assertIn('来源A1', exported['text']); self.assertIn('来源B2', exported['text'])
                self.assertEqual(exported['project']['status'], 'delivered')


if __name__ == '__main__':
    unittest.main()
