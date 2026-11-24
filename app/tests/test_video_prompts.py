"""The visual stage must use a confirmed saved outline, without rewriting it."""
import copy
import json
import os
import unittest
from unittest.mock import patch

import test_marketing_tasks as fixture
import assets_service as assets
import project_assist as A
import project_intelligence as I
import projects as P
import store
import video_prompts as V


class VideoPromptTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.MarketingTaskTests()
        self.fixture.setUp()
        # This suite covers previously queued 1.7 snapshots. New multi-shot
        # contracts have their own fixtures in test_video_prompts_quality.py.
        original_builder = I.build_video_prompts_input
        def legacy_builder(*args, **kwargs):
            snapshot = original_builder(*args, **kwargs)
            snapshot.pop('visual_contract_version', None)
            return snapshot
        self.patches = [patch.object(A, 'DIR', os.path.join(self.fixture.tmp.name, 'assists')),
                        patch.object(store, 'JOBDIR', os.path.join(self.fixture.tmp.name, 'jobs')),
                        patch.object(I, 'build_video_prompts_input', side_effect=legacy_builder)]
        for p in self.patches:
            p.start()
        self.project = self.fixture.adopt(self.fixture.project('channel'))
        self.project['draft'] = I.render_markdown(self.fixture.response('channel'),
                                                  I.build_input(self.project, 'draft'))

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.fixture.tearDown()

    def response(self, snapshot):
        result = {'visual_style': '自然纪实，留白构图，单画面仅呈现一个重点，适合成年观众比较观察。',
                'aspect_ratio': '9:16', 'asset_ids': [self.fixture.rows[1]['id']],
                'shots': [{'number': s['number'], 'prompt': '以参考图中的对象为主体，侧面近景，保留完整轮廓，右侧留白。',
                           'reference_requirements': '待提供对应原书图片，须能辨清对象轮廓。',
                           'source_text': '模型不能用此文字替换确认稿。', 'title': '模型不能替换镜头标题。'}
                          for s in snapshot['confirmed_outline']]}
        if snapshot['presentation_mode'] == 'video':
            for row, original in zip(result['shots'], snapshot['confirmed_outline']):
                plan = next((r for r in snapshot.get('narration_timing_plan', []) if r['number'] == original['number']), None)
                duration = (plan['duration_seconds'] if plan else
                            snapshot['planned_duration_seconds'] / len(snapshot['confirmed_outline'])
                            if snapshot.get('timing_policy') == 'replan_from_narration' else
                            original['production_timing']['duration_seconds'])
                row['duration_seconds'] = duration
                row['motion_plan'] = [
                    {'start_seconds': 0, 'end_seconds': duration / 2, 'camera': '从主体全景缓慢推进到叶片近景',
                     'subject_action': '植物保持自然静止，叶片轮廓不变', 'end_frame': '叶片居中占画面一半'},
                    {'start_seconds': duration / 2, 'end_seconds': duration, 'camera': '沿叶片轮廓向右缓慢平移',
                     'subject_action': '植物保持自然静止', 'end_frame': '停在叶缘特写并保留右侧字幕空位'}]
                row['transition'] = '从叶缘特写直接切到下一镜主体全景。'
        return result

    def persisted(self):
        p = P.create_project({key: self.project[key] for key in ('kind', 'title', 'brief')})
        for row in self.fixture.rows[:2]:
            p = P.update_project(p['id'], {'revision': p['revision'], 'action': 'add_asset', 'asset_id': row['id']})['project']
            p = P.update_project(p['id'], {'revision': p['revision'], 'action': 'update_item',
                                         'asset_id': row['id'], 'status': 'adopted'})['project']
        return P.update_project(p['id'], {'revision': p['revision'], 'action': 'save', 'draft': self.project['draft']})['project']

    def request(self, p, mode='image'):
        return {'capability': 'video_prompts', 'revision': p['revision'], 'confirmed': True,
                'confirmed_draft': p['draft'], 'presentation_mode': mode}

    def test_extracts_current_edited_video_only_and_keeps_every_confirmed_shot(self):
        self.project['draft'] = self.project['draft'].replace('先观察根和叶。', '这是编辑确认后的句子。')
        snapshot = I.build_video_prompts_input(self.project, 'image')
        self.assertEqual(len(snapshot['confirmed_outline']), 6)
        self.assertIn('编辑确认后的句子', snapshot['confirmed_outline'][0]['source_text'])
        self.assertNotIn('先观察根和叶', json.dumps(snapshot['confirmed_outline'], ensure_ascii=False))
        self.assertNotIn('关系为什么需要时间', json.dumps(snapshot['confirmed_outline'], ensure_ascii=False))
        self.assertNotIn('材料怎样复用', json.dumps(snapshot['confirmed_outline'], ensure_ascii=False))
        self.assertEqual(snapshot['confirmed_draft_hash'], assets.digest(self.project['draft']))
        self.assertEqual(snapshot['confirmed_outline'][0]['source_text'], '这是编辑确认后的句子。')
        self.assertNotIn('右侧留出字幕位置', json.dumps(snapshot['confirmed_outline'], ensure_ascii=False))
        self.assertNotIn('直接切换', json.dumps(snapshot['confirmed_outline'], ensure_ascii=False))
        self.assertNotIn('production_timing', snapshot['confirmed_outline'][0])
        self.assertEqual(snapshot['confirmed_outline'][0]['title'], '第 1 段')
        payload = json.loads(I._user_payload(snapshot))
        self.assertEqual(payload['project']['confirmed_outline'], snapshot['confirmed_outline'])

    def test_single_selected_mode_returns_self_contained_prompts_with_authoritative_source(self):
        for mode in ('image', 'video'):
            snapshot = I.build_video_prompts_input(self.project, mode)
            response = self.response(snapshot)
            response['audience'] = '不能覆盖项目受众'
            with patch.object(I.llm, 'chat', return_value={'text': json.dumps(response), 'model': 'unit-test'}) as chat:
                result = I.execute(snapshot)
            pack = result['video_prompts']
            self.assertEqual(pack['presentation_mode'], mode)
            self.assertEqual(pack['audience'], self.project['brief']['audience'])
            self.assertEqual(chat.call_args.kwargs['max_tokens'], 14000)
            for row, original in zip(pack['shots'], snapshot['confirmed_outline']):
                self.assertEqual(row['source_text'], original['source_text'])
                self.assertEqual(row['title'], original['title'])
                self.assertIn('最终观众：成年读者', row['prompt'])
                self.assertIn('统一视觉风格：自然纪实', row['prompt'])
                self.assertIn('画幅：9:16', row['prompt'])
                self.assertIn('待提供对应原书图片', row['prompt'])
                self.assertNotIn('image_prompt', row)
                self.assertNotIn('video_prompt', row)
                if mode == 'video':
                    self.assertIn('只生成画面，不生成口播或对白；完整配音在剪辑时统一加入。', row['prompt'])
                    duration = row['duration_seconds']
                    self.assertIn('计划片段时长：%g秒' % duration, row['prompt'])
                    self.assertIn('0–%g秒：运镜：从主体全景缓慢推进' % (duration / 2), row['prompt'])
                    self.assertIn('%g–%g秒：运镜：沿叶片轮廓向右缓慢平移' % (duration / 2, duration), row['prompt'])
                    self.assertIn('衔接：从叶缘特写直接切到下一镜主体全景', row['prompt'])
                else:
                    self.assertNotIn('计划片段时长', row['prompt'])
                    self.assertNotIn('motion_plan', row)
                    self.assertNotIn('transition', row)
            markdown = I.render_markdown(result, snapshot)
            self.assertNotIn('模型不能', markdown)
            self.assertNotIn('#### 配音稿', markdown)

    def test_rejects_missing_duplicate_reordered_shots_and_unknown_sources(self):
        snapshot = I.build_video_prompts_input(self.project, 'video')
        variants = []
        response = self.response(snapshot); response['shots'].pop(); variants.append(response)
        response = self.response(snapshot); response['shots'][1]['number'] = 1; variants.append(response)
        response = self.response(snapshot); response['shots'].reverse(); variants.append(response)
        response = self.response(snapshot); response['asset_ids'] = ['made-up']; variants.append(response)
        response = self.response(snapshot); response['shots'][0]['reference_requirements'] = ''; variants.append(response)
        for response in variants:
            with self.subTest(response=response), self.assertRaises(ValueError):
                V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})
        with self.assertRaisesRegex(ValueError, '图片展示或视频展示'):
            I.build_video_prompts_input(self.project, 'both')

    def test_legacy_timed_outline_keeps_unscheduled_closing_text_in_last_unit(self):
        self.project['brief']['channels'] = ['短视频']
        self.project['draft'] = '# 旧稿\n\n【开场0—5秒】\n画面：树叶。\n口播：先看叶片。\n\n【5—15秒】\n口播：再看树干。\n\n翻开书观察。'
        units = V.outline(self.project)
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]['source_text'], '先看叶片。')
        self.assertNotIn('画面', units[0]['source_text'])
        self.assertIn('翻开书观察。', units[-1]['source_text'])

    def test_plain_and_legacy_spoken_words_are_preserved_without_visual_confirmation(self):
        self.project['brief']['channels'] = ['短视频']
        plain = '保留这一句原话。\n\n再解释下一点。'
        self.project['draft'] = '# 当前标题\n\n' + plain
        self.assertEqual(V.outline(self.project)[0]['source_text'], plain)
        self.project['draft'] = ('# 当前标题\n\n【0—10秒】\n**画面**：只供内部的画面建议。\n'
                                 '**口播**：这里是用户确认的原话。\n接着解释这件事。\n'
                                 '**剪辑**：只供内部的剪辑建议。\n')
        self.assertEqual(V.outline(self.project)[0]['source_text'], '这里是用户确认的原话。\n接着解释这件事。')

    def test_multiline_narration_exports_and_confirms_exactly_but_one_sided_edit_fails(self):
        edited = '先观察根和叶。\n然后对照原书中的记录。'
        source = self.project['draft'].replace('先观察根和叶。', edited, 1)
        source = source.replace('**口播：** 先观察根和叶。', '**口播：** ' + edited, 1)
        self.project['draft'] = source
        snapshot = I.build_video_prompts_input(self.project, 'video')
        self.assertEqual(snapshot['confirmed_outline'][0]['source_text'], edited)
        exported = V.marketing_delivery.channel_document(source, self.project['brief']['channels'])['text']
        self.assertIn(edited, exported)
        self.assertNotIn('**剪辑：**', exported)
        self.assertEqual(self.project['draft'], source)
        self.project['draft'] = source.replace(edited, '只有配音副本被改过。', 1)
        with self.assertRaisesRegex(ValueError, '配音稿与镜头口播不一致'):
            I.build_video_prompts_input(self.project, 'image')
        with self.assertRaisesRegex(ValueError, '配音稿与镜头口播不一致'):
            V.marketing_delivery.channel_document(self.project['draft'], self.project['brief']['channels'])

    def test_nonzero_global_shots_use_local_time_without_rewriting_confirmed_words(self):
        self.project['brief']['channels'] = ['短视频']
        self.project['draft'] = '# 已确认\n\n【6—14秒】\n口播：这项观察记录用了14秒。\n\n【52—60秒】\n口播：这段原话含52和60，不应被更改。'
        snapshot = I.build_video_prompts_input(self.project, 'video')
        snapshot.pop('timing_policy'); snapshot.pop('planned_duration_seconds'); snapshot.pop('narration_timing_plan')
        snapshot['confirmed_outline'] = V.outline(self.project)  # Previously queued snapshots remain readable.
        before = copy.deepcopy(snapshot['confirmed_outline'])
        payload = json.loads(I._user_payload(snapshot))
        for unit, start in zip(payload['project']['confirmed_outline'], (6, 52)):
            self.assertEqual(unit['production_timing'], {'global_start_seconds': start, 'global_end_seconds': start + 8,
                             'duration_seconds': 8, 'local_start_seconds': 0, 'local_end_seconds': 8})
        response = self.response(snapshot)
        for shot in response['shots']:
            shot['prompt'] = '0–4秒缓慢推进，4–8秒停留在主体特写。'
        result = V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})
        for row, start in zip(result['video_prompts']['shots'], (6, 52)):
            self.assertIn('全片 %d–%d 秒，对应本片段 0–8 秒' % (start, start + 8), row['prompt'])
            self.assertIn('本片段从 0 秒开始计时', row['prompt'])
            self.assertIn('0–4秒缓慢推进，4–8秒停留', row['prompt'])
            self.assertNotIn('。。', row['prompt'])
        self.assertEqual(snapshot['confirmed_outline'], before)
        self.assertEqual(result['video_prompts']['shots'][0]['source_text'], before[0]['source_text'])
        self.assertIn('用了14秒', result['video_prompts']['shots'][0]['source_text'])

    def test_absolute_action_timestamps_are_rejected_for_individual_clips(self):
        self.project['brief']['channels'] = ['短视频']
        self.project['draft'] = '# 已确认\n\n【6—14秒】\n口播：第一镜。\n\n【52—60秒】\n口播：第二镜。'
        snapshot = I.build_video_prompts_input(self.project, 'video')
        snapshot.pop('timing_policy'); snapshot.pop('planned_duration_seconds'); snapshot.pop('narration_timing_plan')
        snapshot['confirmed_outline'] = V.outline(self.project)
        for index, prompt in ((0, '推进后停留到14秒。'), (1, '52—56秒推进，56—60秒静止。'),
                              (1, '8—4秒倒序安排。')):
            response = self.response(snapshot); response['shots'][index]['prompt'] = prompt
            with self.subTest(prompt=prompt), self.assertRaisesRegex(ValueError, '从 0 秒计时'):
                V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})

    def test_video_rejects_static_descriptions_without_complete_motion_plan(self):
        snapshot = I.build_video_prompts_input(self.project, 'video')
        variants = []
        response = self.response(snapshot); response['shots'][0].pop('motion_plan'); variants.append(response)
        response = self.response(snapshot); response['shots'][0].pop('transition'); variants.append(response)
        response = self.response(snapshot); response['shots'][0]['motion_plan'][0]['camera'] = ''; variants.append(response)
        response = self.response(snapshot); response['shots'][0]['motion_plan'][1]['start_seconds'] = 6; variants.append(response)
        response = self.response(snapshot); response['shots'][0]['motion_plan'][1]['end_seconds'] = 9; variants.append(response)
        response = self.response(snapshot); response['shots'][0]['motion_plan'][1]['end_seconds'] = 11; variants.append(response)
        response = self.response(snapshot); response['shots'][0]['motion_plan'][1]['camera'] = '持续推进到14秒'; variants.append(response)
        for response in variants:
            with self.subTest(response=response), self.assertRaises(ValueError):
                V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})

    def test_mode_specific_generation_schema_and_video_requires_confirmed_timing(self):
        for mode in ('image', 'video'):
            snapshot = I.build_video_prompts_input(self.project, mode)
            with patch.object(I.llm, 'chat', return_value={'text': json.dumps(self.response(snapshot))}) as chat:
                I.execute(snapshot)
            instruction = chat.call_args[0][0][0]['content']
            self.assertIn('本次只生成' + ('图片' if mode == 'image' else '视频') + '展示提示词', instruction)
            if mode == 'video':
                self.assertIn('"motion_plan":[', instruction)
                self.assertNotIn('"prompt":"可执行的静态画面描述"', instruction)
            else:
                self.assertNotIn('"motion_plan":[', instruction)
        self.project['brief']['channels'] = ['短视频']
        self.project['draft'] = '一份未安排时间的手工口播稿。'
        with self.assertRaisesRegex(ValueError, '填写总计划时长'):
            I.build_video_prompts_input(self.project, 'video')
        self.assertEqual(len(I.build_video_prompts_input(self.project, 'image')['confirmed_outline']), 1)

    def test_video_replans_hidden_shot_times_using_only_narration_and_total_budget(self):
        production = I.video_production.validate(fixture.sample_production(), include_prompts=False)
        cursor = 0
        for shot, duration in zip(production['shots'], (8, 10, 12, 12, 12, 6)):
            shot.update(start_seconds=cursor, end_seconds=cursor + duration)
            cursor += duration
        ending = '最后请翻开原书，看看记录中的对象是什么样子，再带着这个问题重新读一遍。观察之后，把你发现的相同之处和不同之处记下来。'
        production['shots'][-1]['voiceover'] = ending
        self.project['brief']['channels'] = ['短视频']
        self.project['draft'] = '# 口播稿\n\n' + I.video_production.render_body(production)
        before = self.project['draft']
        snapshot = I.build_video_prompts_input(self.project, 'video')
        snapshot.pop('narration_timing_plan')  # Older budget-only snapshots keep their original contract.
        self.assertEqual(snapshot['planned_duration_seconds'], 60)
        self.assertEqual(snapshot['confirmed_outline'][-1]['source_text'], ending)
        self.assertNotIn('54–60', json.dumps(snapshot['confirmed_outline'], ensure_ascii=False))
        self.assertFalse(any('production_timing' in row for row in snapshot['confirmed_outline']))
        response = self.response(snapshot)
        for row, duration in zip(response['shots'], (6, 8, 10, 10, 12, 14)):
            row['duration_seconds'] = duration
            row['motion_plan'][0]['end_seconds'] = duration / 2
            row['motion_plan'][1].update(start_seconds=duration / 2, end_seconds=duration)
        result = V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})
        last = result['video_prompts']['shots'][-1]
        self.assertEqual(last['source_text'], ending)
        self.assertEqual(last['production_timing']['global_start_seconds'], 46)
        self.assertEqual(last['duration_seconds'], 14)
        self.assertIn('全片 46–60 秒，对应本片段 0–14 秒', last['prompt'])
        self.assertEqual(self.project['draft'], before)
        response['shots'][0]['duration_seconds'] = 7
        response['shots'][0]['motion_plan'][-1]['end_seconds'] = 7
        with self.assertRaisesRegex(ValueError, '之和必须等于总计划时长'):
            V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})

    def test_length_weighted_plan_keeps_a_long_ending_and_exact_tenth_second_total(self):
        units = [{'number': i + 1, 'source_text': '字' * length}
                 for i, length in enumerate((27, 26, 25, 25, 25, 24, 24, 53))]
        plan = V.narration_timing_plan(units, 60)
        self.assertEqual(plan[-1]['duration_seconds'], 13.9)
        self.assertEqual(plan[-1]['global_start_seconds'], 46.1)
        self.assertEqual(plan[-1]['global_end_seconds'], 60.0)
        self.assertEqual(sum(round(row['duration_seconds'] * 10) for row in plan), 600)
        self.assertEqual(V.narration_timing_plan(units, 60), plan)
        for i, row in enumerate(plan):
            self.assertEqual(row['global_start_seconds'], plan[i - 1]['global_end_seconds'] if i else 0)
            for field in ('duration_seconds', 'global_start_seconds', 'global_end_seconds'):
                self.assertEqual(row[field], round(row[field], 1))

    def test_model_cannot_replace_system_allocations_even_with_valid_motion(self):
        snapshot = I.build_video_prompts_input(self.project, 'video')
        self.assertFalse(any('production_timing' in row for row in snapshot['confirmed_outline']))
        payload = json.loads(I._user_payload(snapshot))
        self.assertEqual(payload['project']['narration_timing_plan'], snapshot['narration_timing_plan'])
        response = self.response(snapshot)
        result = V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})
        for row, planned in zip(result['video_prompts']['shots'], snapshot['narration_timing_plan']):
            self.assertEqual(row['duration_seconds'], planned['duration_seconds'])
            self.assertEqual(row['production_timing']['global_end_seconds'], planned['global_end_seconds'])
        response['shots'][-1]['duration_seconds'] = 7
        response['shots'][-1]['motion_plan'] = [{'start_seconds': 0, 'end_seconds': 7,
                                                'camera': '平稳向右移动', 'subject_action': '植物静止', 'end_frame': '叶缘特写'}]
        with self.assertRaisesRegex(ValueError, '系统分配的制作计划不一致'):
            V.validate(response, snapshot, {r['id'] for r in self.fixture.rows})

    def test_missing_source_ids_inherit_only_supplied_scope_without_claiming_citations(self):
        snapshot = I.build_video_prompts_input(self.project, 'video')
        response = self.response(snapshot); response.pop('asset_ids')
        before = copy.deepcopy(response)
        one_supplied = {self.fixture.rows[1]['id']}
        result = V.validate(response, snapshot, one_supplied)
        self.assertEqual(result['asset_ids'], sorted(one_supplied))
        self.assertEqual(result['source_scope'], {'kind': 'provided_materials', 'asset_ids': sorted(one_supplied)})
        self.assertEqual(response, before)
        with patch.object(I.llm, 'chat', return_value={'text': json.dumps(response)}) as chat:
            result = I.execute(snapshot)
        payload = json.loads(chat.call_args[0][0][1]['content'].split('\n', 1)[1])
        supplied = {row['asset_id'] for row in payload['materials']}
        self.assertEqual(set(result['asset_ids']), supplied)
        self.assertEqual(result['cited_asset_ids'], [])
        self.assertEqual(result['source_labels'], {})
        self.assertEqual(result['provenance']['supplied_assets'], len(supplied))

    def test_missing_scope_or_explicit_invalid_source_ids_remain_rejected(self):
        snapshot = I.build_video_prompts_input(self.project, 'video')
        response = self.response(snapshot); response.pop('asset_ids')
        with self.assertRaisesRegex(ValueError, '有效依据'):
            V.validate(response, snapshot, set())
        for ids in ([], None, ['invented']):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, '有效依据'):
                V.validate({**response, 'asset_ids': ids}, snapshot, {r['asset_id'] for r in snapshot['materials']})

    def test_explicit_confirmation_and_saved_revision_are_required_before_enqueue(self):
        p = self.persisted()
        variants = []
        request = self.request(p); request.pop('confirmed'); variants.append(request)
        request = self.request(p); request['confirmed_draft'] += '未保存编辑'; variants.append(request)
        request = self.request(p); request['revision'] -= 1; variants.append(request)
        request = self.request(p); request['presentation_mode'] = 'both'; variants.append(request)
        for request in variants:
            with self.subTest(request=request), self.assertRaises(ValueError):
                A.enqueue(p['id'], request)
        self.assertEqual(A.list_runs(p['id']), [])
        run = A.enqueue(p['id'], self.request(p))['run']
        self.assertEqual(run['snapshot']['confirmed_draft_hash'], assets.digest(p['draft']))
        self.assertTrue(run['snapshot']['confirmed_at'])
        self.assertEqual(P._read(p['id'])['draft'], p['draft'])

    def test_generated_prompts_never_replace_draft_and_edits_make_them_stale(self):
        p = self.persisted()
        queued = A.enqueue(p['id'], self.request(p))
        snapshot = queued['run']['snapshot']
        before = P._read(p['id'])
        with patch.object(I.llm, 'chat', return_value={'text': json.dumps(self.response(snapshot)), 'model': 'unit-test'}):
            A.execute_job(queued['job']['id'])
        run = A.get_run(p['id'], queued['run']['id'])
        self.assertEqual(run['status'], 'done', run.get('error'))
        self.assertTrue(run['markdown'])
        self.assertFalse(run['stale'])
        self.assertEqual(P._read(p['id']), before)
        with self.assertRaisesRegex(ValueError, '只能应用'):
            A.apply_to_project(copy.deepcopy(before), run['id'])
        p = P.update_project(p['id'], {'revision': p['revision'], 'action': 'save', 'draft': p['draft'] + '\n新编辑内容'})['project']
        self.assertTrue(A.get_run(p['id'], run['id'])['stale'])
        self.assertEqual(A.get_run(p['id'], run['id'])['result']['confirmed_draft_hash'], assets.digest(before['draft']))

    def test_duplicate_requests_deduplicate_only_same_saved_outline_and_presentation(self):
        p = self.persisted()
        first = A.enqueue(p['id'], self.request(p, 'image'))
        duplicate = A.enqueue(p['id'], self.request(p, 'image'))
        video = A.enqueue(p['id'], self.request(p, 'video'))
        self.assertEqual(first['run']['id'], duplicate['run']['id'])
        self.assertTrue(duplicate['running'])
        self.assertNotEqual(first['run']['id'], video['run']['id'])


if __name__ == '__main__':
    unittest.main()
