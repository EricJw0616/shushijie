"""Observable delivery boundaries, not a claim that code proves visual accuracy."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video_prompts as V
import video_production as P
from test_video_production import sample_production


ALLOWED = {'book:fact:1', 'book:fact:2'}
REVIEW_REGRESSIONS = json.loads((Path(__file__).parent / 'fixtures' / 'visual_review_regressions.json').read_text())
SOURCE_CHECK_EXPERIMENT = json.loads((Path(__file__).parent / 'fixtures' / 'visual_source_checks_experiment.json').read_text())


def snapshot(mode='video'):
    units = [{'number': 1, 'title': '第 1 段', 'source_text': '熟人社会的关系。'},
             {'number': 2, 'title': '第 2 段', 'source_text': '乡土生活的联系。'}]
    result = {'visual_contract_version': '2.0', 'presentation_mode': mode,
              'confirmed_outline': units, 'confirmed_draft_hash': 'confirmed-unchanged',
              'brief': {'audience': '11–14岁读者', 'writing_notes': '简洁纸艺图解'},
              'marketing_context': {'roles': {'viewer': '11–14岁读者', 'decision_maker': ''}}}
    if mode == 'video':
        result.update(planned_duration_seconds=60, narration_timing_plan=V.narration_timing_plan(units, 60))
    return result


def response(mode='video'):
    result = {'visual_style': '纸艺图解，低密度布局，蓝与米白区分两种关系。',
              'audience_adaptation': '先呈现两个熟悉的交往对象，再用一条连线解释关系，避免堆叠抽象术语。',
              'aspect_ratio': '9:16', 'asset_ids': sorted(ALLOWED),
              'references': [{'id': 'R1', 'name': '关系示意图组件', 'kind': 'design_asset',
                              'status': 'to_create', 'requirement': '依据书中观点制作人物符号和连线，不加入统计数字。'}],
              'shots': []}
    mappings = [[1], [1, 2], [2]] if mode == 'video' else [[1, 2]]
    for index, sources in enumerate(mappings, 1):
        shot = {'number': index, 'source_numbers': sources, 'title': '乡土生活中的关系',
                'focus': '《乡土中国》中的熟人社会关系', 'depiction_type': 'concept_diagram',
                'scene_mode': 'single_scene', 'scene_description': '纸艺概念画布上的人物与连线',
                'reference_ids': ['R1'], 'asset_ids': sorted(ALLOWED),
                'prompt': '两个纸艺人物符号分列左右，一条连线居中，下方留字幕区域。'}
        if mode == 'video':
            shot.update(duration_seconds=20,
                        motion_plan=[{'start_seconds': 0, 'end_seconds': 10,
                                      'camera': '从完整画布缓慢推近中央连线',
                                      'subject_action': '人物符号位置保持不变', 'end_frame': '连线和两端人物清楚可见'},
                                     {'start_seconds': 10, 'end_seconds': 20,
                                      'camera': '从连线近景缓慢拉远到完整画布',
                                      'subject_action': '人物符号保持原布局', 'end_frame': '完整关系图与字幕留白'}],
                        transition_type='end' if index == len(mappings) else 'cut',
                        transition='本镜结束后直接切到下一幅概念图。' if index < len(mappings) else '停在完整关系图结束。')
        result['shots'].append(shot)
    return result


class VisualContractQualityTests(unittest.TestCase):
    def test_multiple_shots_and_merged_paragraphs_keep_narration_once_and_exact_timeline(self):
        source = snapshot(); before = copy.deepcopy(source)
        pack = V.validate(response(), source, ALLOWED)['video_prompts']
        self.assertEqual([s['source_numbers'] for s in pack['shots']], [[1], [1, 2], [2]])
        self.assertEqual([(s['production_timing']['global_start_seconds'], s['production_timing']['global_end_seconds'])
                          for s in pack['shots']], [(0, 20), (20, 40), (40, 60)])
        self.assertEqual(pack['confirmed_narration'], '熟人社会的关系。\n\n乡土生活的联系。')
        self.assertEqual(source, before)
        self.assertEqual(pack['required_inputs'][0]['shot_numbers'], [1, 2, 3])
        for shot in pack['shots']:
            self.assertIn('最终观众：11–14岁读者', shot['prompt'])
            self.assertIn('《乡土中国》', shot['prompt'])
            self.assertIn('待制作', shot['reference_requirements'])
            self.assertIn('只生成画面，不生成口播或对白；完整配音在剪辑时统一加入。', shot['prompt'])

    def test_external_video_prompts_keep_audio_out_of_each_generated_clip(self):
        for mode in ('image', 'video'):
            source = snapshot(mode)
            pack = V.validate(response(mode), source, ALLOWED)['video_prompts']
            with self.subTest(mode=mode):
                self.assertEqual(pack['confirmed_narration'], '\n\n'.join(
                    row['source_text'] for row in source['confirmed_outline']))
                for shot in pack['shots']:
                    if mode == 'video':
                        self.assertIn('不生成口播或对白', shot['prompt'])
                        self.assertIn('完整配音在剪辑时统一加入', shot['prompt'])
                        self.assertNotIn('口播使用完整录音', shot['prompt'])
                    else:
                        self.assertNotIn('只生成画面，不生成口播或对白', shot['prompt'])
                self.assertIn('完整口播录制一次', pack['production_steps'][-1])
                if mode == 'video':
                    self.assertIn('统一加入完整配音和字幕', pack['production_steps'][-1])

    def test_generation_separates_identity_reference_from_historical_scene_evidence(self):
        for mode in ('image', 'video'):
            for version in (None, V.CONTRACT_VERSION):
                with self.subTest(mode=mode, version=version):
                    instruction = V.instruction(mode, contract_version=version)
                    self.assertIn('肖像参考可确认本人面貌和身份，不能证明其在某次历史事件中', instruction)
                    self.assertIn('未记载且非表达必要的工具、场景细节和操作姿态应省略', instruction)
                    self.assertIn('不要求用户另外寻找能证明这些自行添加细节的参考图', instruction)
                    self.assertIn('已有事件依据的真实情景仍可重现', instruction)
                    if mode == 'video':
                        self.assertIn('不生成口播或对白', instruction)

    def test_missing_out_of_order_or_wrong_time_mapping_is_rejected(self):
        cases = []
        x = response(); x['shots'][0]['source_numbers'] = [2]; cases.append(x)
        x = response(); x['shots'][1]['source_numbers'] = [2, 1]; cases.append(x)
        x = response(); x['shots'][2]['source_numbers'] = [1]; cases.append(x)
        x = response(); x['shots'][1]['source_numbers'] = [1, 3]; cases.append(x)
        x = response(); x['shots'][-1]['duration_seconds'] = 19; cases.append(x)
        x = response(); x['shots'][0]['motion_plan'][1]['start_seconds'] = 11; cases.append(x)
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                V.validate(data, snapshot(), ALLOWED)

    def test_one_image_can_cover_two_paragraphs_without_any_video_timing(self):
        pack = V.validate(response('image'), snapshot('image'), ALLOWED)['video_prompts']
        self.assertEqual(len(pack['shots']), 1)
        self.assertEqual(pack['shots'][0]['source_numbers'], [1, 2])
        self.assertEqual(pack['narration_timing_plan'], [])
        self.assertFalse(any(k in pack['shots'][0] for k in ('duration_seconds', 'production_timing', 'motion_plan')))
        self.assertIn('配图讲解视频', pack['production_steps'][-1])
        bad = response('image'); bad['shots'][0]['duration_seconds'] = 60
        with self.assertRaises(ValueError):
            V.validate(bad, snapshot('image'), ALLOWED)

    def test_reference_status_and_accurate_subject_requirements_are_truthful(self):
        for status in ('available', 'provided', 'verified', 'generated'):
            bad = response('image'); bad['references'][0]['status'] = status
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, '未接收'):
                V.validate(bad, snapshot('image'), ALLOWED)
        bad = response('image'); bad['shots'][0]['depiction_type'] = 'factual_object'
        with self.assertRaisesRegex(ValueError, '准确参考'):
            V.validate(bad, snapshot('image'), ALLOWED)
        good = copy.deepcopy(bad)
        good['references'][0].update(kind='accurate_reference', status='required', name='器物整体参考', requirement='待提供器物正面参考图。')
        V.validate(good, snapshot('image'), ALLOWED)
        for extra in ('未提供参考时以示意轮廓替代。', '参考图已提供。'):
            bad = copy.deepcopy(good); bad['shots'][0]['prompt'] += extra
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                V.validate(bad, snapshot('image'), ALLOWED)

    def test_copyable_prompt_keeps_reference_constraints_but_operator_steps_stay_in_handoff(self):
        data = response('image')
        data['shots'][0].update(depiction_type='factual_object', focus='书中器物的正面结构')
        data['references'][0].update(kind='accurate_reference', status='required', name='器物正面参考',
                                     requirement='待提供器物正面参考图，保留边缘缺口、孔位和表面纹理。')
        pack = V.validate(data, snapshot('image'), ALLOWED)['video_prompts']
        shot = pack['shots'][0]
        self.assertIn('器物正面参考图，保留边缘缺口、孔位和表面纹理。', shot['prompt'])
        self.assertIn('参考图未提供时，不用想象外形替代', shot['prompt'])
        for operator_copy in ('本系统尚未接收', '请先准备', '在制作工具中上传', '待提供', '待制作'):
            self.assertNotIn(operator_copy, shot['prompt'])
        self.assertIn('待提供', shot['reference_requirements'])
        self.assertEqual(pack['references'][0]['status'], 'required')
        self.assertIn('所列参考', pack['production_steps'][0])
        self.assertIn('外部制作工具中上传', pack['production_steps'][1])
        self.assertIn('配图讲解视频', pack['production_steps'][-1])

    def test_person_fiction_and_concept_modes_have_different_boundaries(self):
        person = response('image'); person['shots'][0].update(depiction_type='real_person', focus='书中院士的肖像')
        with self.assertRaisesRegex(ValueError, '身份参考'):
            V.validate(person, snapshot('image'), ALLOWED)
        person['references'][0].update(kind='identity_reference', status='required', name='人物身份参考', requirement='待提供经核对的人物肖像及拍摄时期。')
        pack = V.validate(person, snapshot('image'), ALLOWED)['video_prompts']
        self.assertIn('真实人物', pack['shots'][0]['prompt'])
        story = response('image'); story['shots'][0].update(depiction_type='fictional_scene', focus='《小王子》中的小王子与狐狸')
        pack = V.validate(story, snapshot('image'), ALLOWED)['video_prompts']
        self.assertIn('不作为真实事件影像', pack['shots'][0]['prompt'])
        self.assertNotIn('植物', pack['shots'][0]['prompt'])

    def test_conflicting_viewer_and_fake_source_scope_are_not_accepted(self):
        for key in ('audience', 'viewer'):
            bad = response('image'); bad[key] = '购买图书的家长'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '购买者'):
                V.validate(bad, snapshot('image'), ALLOWED)
        bad = response('image'); bad['shots'][0]['asset_ids'] = ['unseen:fact']
        with self.assertRaisesRegex(ValueError, '依据'):
            V.validate(bad, snapshot('image'), ALLOWED)

    def test_creative_intro_and_closing_can_have_no_citation_without_inheriting_all_sources(self):
        data = response(); data['shots'][0].update(depiction_type='fictional_scene', asset_ids=[])
        data['shots'][2]['asset_ids'] = []
        data['shots'][1]['asset_ids'] = ['book:fact:1']
        result = V.validate(data, snapshot(), ALLOWED)
        self.assertEqual(result['video_prompts']['shots'][0]['asset_ids'], [])
        self.assertEqual(result['video_prompts']['shots'][2]['asset_ids'], [])
        self.assertEqual(result['asset_ids'], ['book:fact:1'])
        self.assertEqual(result['source_scope']['asset_ids'], sorted(ALLOWED))
        data['shots'][1]['asset_ids'] = []
        with self.assertRaisesRegex(ValueError, '整包没有'):
            V.validate(data, snapshot(), ALLOWED)

    def test_factual_missing_and_unknown_citations_report_the_actual_shot(self):
        bad = response(); bad['shots'][1].update(depiction_type='historical_scene', asset_ids=[])
        with self.assertRaisesRegex(ValueError, '第2镜.*书内依据'):
            V.validate(bad, snapshot(), ALLOWED)
        bad = response(); bad['shots'][1]['asset_ids'] = ['made-up']
        with self.assertRaisesRegex(ValueError, '第2镜.*范围外'):
            V.validate(bad, snapshot(), ALLOWED)

    def test_declared_multi_space_requires_explicit_composite_semantics(self):
        data = response(); data['shots'][1].update(scene_mode='split_screen', scene_description='左侧历史照片、右侧现代环境，彼此独立。')
        pack = V.validate(data, snapshot(), ALLOWED)['video_prompts']
        self.assertIn('不跨区模拟连续实景', pack['shots'][1]['prompt'])
        data['shots'][1]['transition_type'] = 'continuous_camera'
        with self.assertRaisesRegex(ValueError, '不同空间'):
            V.validate(data, snapshot(), ALLOWED)
        # Code checks declared layout; independent review still checks its actual content.
        review = V.validate_review({'accepted': True, 'issues': [{'code': 'spatial_conflict',
             'message': '宣称分屏却要求从历史照片平移进现代街道。', 'location': 'shots[1]', 'severity': 'blocker'}]})
        self.assertFalse(review['accepted'])

    def test_review_requires_concrete_findings_and_does_not_claim_fact_verification(self):
        self.assertEqual(V.validate_review({'accepted': True, 'issues': []}), {'accepted': True, 'issues': []})
        for data in ({'accepted': 'yes', 'issues': []}, {'accepted': False, 'issues': []},
                     {'accepted': True, 'issues': [{'severity': 'warning'}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                V.validate_review(data)
        text = V.review_instruction()
        self.assertIn('引用存在不等于支持结论', text)
        self.assertIn('不要求系统保证成片', text)

    def test_real_warning_only_rejections_are_advisory_and_preserved(self):
        # Both recorded reviews failed the old validator despite having no blocker.
        for name in ('plants_youth_warnings', 'plants_adult_warnings'):
            review = REVIEW_REGRESSIONS[name]['review']
            self.assertFalse(review['accepted'])
            with self.subTest(name=name):
                result = V.validate_review(review, candidate={'stage': 'external_production_plan'})
                self.assertTrue(result['accepted'])
                self.assertEqual(result['issues'], review['issues'])
        result = V.validate_review({'accepted': False, 'issues': [{'code': 'layout', 'severity': 'warning',
                                    'location': '第1镜', 'message': '构图可简化。',
                                    'candidate_quote': '', 'source_basis': ''}]}, candidate={})
        self.assertTrue(result['accepted'])

    def test_actual_failed_candidates_are_reviewed_as_conditional_plans_without_duplicate_boilerplate(self):
        for name in ('plants_adult', 'prince_parent'):
            original = REVIEW_REGRESSIONS[name]['candidate']; before = copy.deepcopy(original)
            candidate = V.review_candidate(original)
            with self.subTest(name=name):
                self.assertEqual(candidate['stage'], 'external_production_plan')
                self.assertEqual(candidate['references'], original['references'])
                self.assertNotIn('required_inputs', candidate)
                self.assertNotIn('confirmed_outline', candidate)
                self.assertNotIn('confirmed_narration', candidate)
                self.assertEqual(len(candidate['shots']), len(original['shots']))
                for shot, saved in zip(candidate['shots'], original['shots']):
                    self.assertNotIn('prompt', shot)
                    self.assertNotIn('source_text', shot)
                    self.assertIn(shot['scene_prompt'], saved['prompt'])
                    self.assertNotIn('本系统尚未接收', shot['scene_prompt'])
                    self.assertNotIn('衔接方式：', shot['scene_prompt'])
                    self.assertNotIn('最终观众：', shot['scene_prompt'])
                    self.assertEqual(shot['asset_ids'], saved['asset_ids'])
                    self.assertEqual(shot['reference_ids'], saved['reference_ids'])
                self.assertEqual(original, before)
        # Preserve the actual conditions that the old reviewer incorrectly called readiness claims.
        plant = V.review_candidate(REVIEW_REGRESSIONS['plants_adult']['candidate'])
        self.assertTrue(any(ref['status'] == 'required' for ref in plant['references']))
        self.assertIn('孢子囊群', plant['shots'][1]['scene_prompt'])
        fiction = V.review_candidate(REVIEW_REGRESSIONS['prince_parent']['candidate'])
        self.assertIn('两只手', fiction['shots'][3]['scene_prompt'])
        self.assertIn('共同指向书页', fiction['shots'][3]['scene_prompt'])

    def test_new_packs_retain_authored_scene_prompt_for_independent_review(self):
        raw = response(); pack = V.validate(raw, snapshot(), ALLOWED)['video_prompts']
        candidate = V.review_candidate(pack)
        for raw_shot, shot in zip(raw['shots'], candidate['shots']):
            self.assertEqual(shot['scene_prompt'], raw_shot['prompt'])
            self.assertEqual(shot['motion_plan'], raw_shot['motion_plan'])

    def test_each_mode_instruction_contains_its_complete_valid_output_example(self):
        for mode in ('image', 'video'):
            text = V.instruction(mode, contract_version=V.CONTRACT_VERSION)
            data = json.loads(text.rsplit('\n', 1)[-1])
            source = snapshot(mode)
            if mode == 'video':
                source['planned_duration_seconds'] = 20
                source['narration_timing_plan'] = V.narration_timing_plan(source['confirmed_outline'], 20)
            result = V.validate(data, source, {'本次真实材料ID'})['video_prompts']
            with self.subTest(mode=mode):
                for shot in data['shots']:
                    for key in ('duration_seconds', 'motion_plan', 'transition_type', 'transition'):
                        self.assertEqual(key in shot, mode == 'video')
                self.assertEqual(result['presentation_mode'], mode)
        self.assertEqual([shot['source_numbers'] for shot in result['shots']], [[1], [1, 2]])
        self.assertEqual(result['shots'][-1]['production_timing']['global_end_seconds'], 20)

    def test_blocker_requires_actual_candidate_quote_and_source_basis(self):
        candidate = V.review_candidate(REVIEW_REGRESSIONS['plants_adult']['candidate'])
        review = {'accepted': False, 'issues': [{'code': 'false_ready', 'severity': 'blocker',
                  'location': '第2镜.scene_prompt', 'message': '把未提供的参考说成已提供。',
                  'candidate_quote': '参考图已提供并核实。', 'source_basis': 'R1为required，执行前待提供。'}]}
        with self.assertRaisesRegex(ValueError, '原句不在候选'):
            V.validate_review(review, candidate=candidate)
        # A real conflicting instruction still blocks; the stage exemption is not a blanket pass.
        candidate['shots'][1]['scene_prompt'] += '参考图已提供并核实。'
        review['accepted'] = True
        self.assertFalse(V.validate_review(review, candidate=candidate)['accepted'])
        del review['issues'][0]['source_basis']
        with self.assertRaisesRegex(ValueError, 'source_basis'):
            V.validate_review(review, candidate=candidate)

    def test_real_execution_and_role_conflicts_still_block_with_evidence(self):
        cases = [
            ('spatial_conflict', '从森林岩石连续平移进入远处海底。', '空间不相连却要求一次连续实景平移。'),
            ('fixed_structure', '盘状固着器脱离岩石游动。', '提供材料写固着器盘状，基部用于固着；此动作与固定位置矛盾。'),
            ('invented_fact', '给小王子戴上获得的诺贝尔奖章。', '文学原文没有获奖情节，候选把虚构荣誉写成角色经历。'),
            ('audience_conflict', '面对买书家长，列出孩子成绩提高的数据。', '任务最终观众为11–14岁，未指定购买者且没有成绩数据。'),
        ]
        for code, quote, basis in cases:
            candidate = {'stage': 'external_production_plan', 'shots': [{'scene_prompt': quote}]}
            issue = {'code': code, 'severity': 'blocker', 'location': '第1镜.scene_prompt',
                     'message': basis, 'candidate_quote': quote, 'source_basis': basis}
            with self.subTest(code=code):
                self.assertFalse(V.validate_review({'accepted': True, 'issues': [issue]}, candidate=candidate)['accepted'])

    def test_actual_literary_time_conflict_has_explicit_source_and_candidate_evidence(self):
        case = REVIEW_REGRESSIONS['literary_explicit_time_conflict']
        self.assertIn('黎明', case['source_context']['quote'])
        self.assertIn('夜晚', case['candidate']['shots'][0]['scene_prompt'])
        self.assertEqual(case['candidate']['shots'][0]['depiction_type'], 'fictional_scene')
        # This is an editor-labeled saved failure, not a claim that the unit test
        # independently understands literature. Root's live review tests cover that.
        report = V.validate_review(case['expected_editor_finding'], candidate=case['candidate'])
        self.assertFalse(report['accepted'])
        self.assertIn(case['source_context']['asset_id'], report['issues'][0]['source_basis'])

    def test_all_static_video_editor_finding_is_not_waived_by_valid_motion_schema(self):
        case = REVIEW_REGRESSIONS['entire_video_static']
        self.assertEqual(case['candidate']['presentation_mode'], 'video')
        self.assertEqual(len(case['candidate']['shots']), 4)
        self.assertTrue(all(shot['motion_plan'] for shot in case['candidate']['shots']))
        report = V.validate_review(case['expected_editor_finding'], candidate=case['candidate'])
        self.assertFalse(report['accepted'])
        # No keyword-based dynamic-quality classifier is introduced: a fixed
        # camera can contain useful diagram changes; semantic review sees both.
        candidate = V.review_candidate(V.validate(response(), snapshot(), ALLOWED)['video_prompts'])
        self.assertTrue(V.validate_review({'accepted': True, 'issues': []}, candidate=candidate)['accepted'])

    def test_mode_prompts_and_review_keep_reference_and_creative_boundaries(self):
        for mode in ('image', 'video'):
            text = V.instruction(mode, contract_version=V.CONTRACT_VERSION)
            with self.subTest(mode=mode):
                self.assertIn('普通纸张底色、线条、配色、标题留白直接写进prompt', text)
                self.assertIn('缺准确图片', text)
                self.assertIn('缺书内事实', text)
                self.assertIn('优先独立概念图或不特指具体器材的讲解符号', text)
                self.assertIn('真实人物的插画化重现仍保留真实身份', text)
                self.assertIn('时间、地点、人物关系和事件顺序', text)
                self.assertIn('准确对象/真人没有参考时，要求先提供参考再执行', text)
        review = V.review_instruction()
        self.assertIn('普通纸张底色、线条、标题留白', review)
        self.assertIn('全部supplied_materials', review)
        self.assertIn('镜头列出的asset_ids不是核对范围边界', review)
        self.assertIn('原文明示条件被候选改写', review)
        self.assertIn('image是用于配图讲解视频的静态图片，完全不查动态', review)
        self.assertIn('先完成所有事实核对，不能用几条构图建议代替', review)
        self.assertIn('全包所有镜头', review)
        self.assertIn('不按“运动/动态”等词出现次数判断', review)
        actual = REVIEW_REGRESSIONS['unnecessary_reference_dependencies']['candidate']
        self.assertTrue(any('书中所述' in ref['requirement'] for ref in actual['references']))
        self.assertTrue(any('纸页' in ref['requirement'] and ref['kind'] == 'design_asset' for ref in actual['references']))

    def test_source_check_experiment_retains_valid_conflict_despite_other_spliced_quotes(self):
        case = SOURCE_CHECK_EXPERIMENT
        report = V.validate_review(case['response'], candidate=case['candidate'], materials=case['materials'], require_source_checks=True)
        self.assertFalse(report['accepted'])
        self.assertEqual(report['source_checks'][5]['conclusion'], 'contradicted')
        for index in (2, 3):
            self.assertEqual(report['source_checks'][index]['conclusion'], 'unverified')
            self.assertEqual(report['source_checks'][index]['reported_conclusion'], 'supported')
            self.assertIn('source_quote_not_found', report['source_checks'][index]['validation_issues'])
        self.assertTrue(any(issue['severity'] == 'blocker' for issue in report['issues']))
        # A model's top-level acceptance cannot waive its own valid contradiction.
        response = copy.deepcopy(case['response']); response.update(accepted=True, issues=[])
        report = V.validate_review(response, candidate=case['candidate'], materials=case['materials'], require_source_checks=True)
        self.assertFalse(report['accepted'])
        self.assertEqual(report['issues'][0]['code'], 'source_check_conflict')
        self.assertIn('黎明', report['issues'][0]['source_basis'])

    def test_unverified_support_is_incomplete_without_fabricating_a_content_blocker(self):
        case = SOURCE_CHECK_EXPERIMENT
        valid = case['response']['source_checks'][0]
        for key, invalid in [('candidate_quote', '候选中没有这句话'),
                             ('source_asset_id', 'outside:material'),
                             ('source_field', 'unknown_field'),
                             ('source_quote', '原文中没有这句话')]:
            row = {**valid, key: invalid}
            response = {'accepted': True, 'issues': [], 'source_checks': [row]}
            with self.subTest(key=key):
                report = V.validate_review(response, candidate=case['candidate'], materials=case['materials'], require_source_checks=True)
                self.assertFalse(report['accepted'])
                self.assertEqual(report['source_check_status'], 'incomplete')
                self.assertEqual(report['issues'], [])
                self.assertEqual(report['source_checks'][0]['conclusion'], 'unverified')
                self.assertEqual(report['source_checks'][0]['evidence_status'], 'unverified')

    def test_not_specified_is_not_automatically_an_error_and_exact_quotes_are_not_fact_certification(self):
        case = SOURCE_CHECK_EXPERIMENT
        row = {**case['response']['source_checks'][0], 'source_asset_id': '', 'source_field': '',
               'source_quote': '', 'conclusion': 'not_specified'}
        response = {'accepted': True, 'issues': [], 'source_checks': [row]}
        report = V.validate_review(response, candidate=case['candidate'], materials=case['materials'], require_source_checks=True)
        self.assertTrue(report['accepted'])
        self.assertEqual(report['source_checks'][0]['conclusion'], 'not_specified')
        self.assertEqual(report['source_check_status'], 'needs_review')
        self.assertIn('不代表结论已被独立核实', report['source_check_notice'])
        response['source_checks'] = [case['response']['source_checks'][0]]
        report = V.validate_review(response, candidate=case['candidate'], materials=case['materials'], require_source_checks=True)
        self.assertEqual(report['source_checks'][0]['evidence_status'], 'matched')
        self.assertEqual(report['source_check_status'], 'needs_review')

    def test_atomic_history_checks_keep_supported_action_separate_from_unspecified_props(self):
        # A grounded editorial finding can reject invented historical details
        # without fabricating an opposite source quote or rejecting all design.
        candidate={'shots':[{'scene_prompt':'复原书中研究场景：研究者坐在实验台前，用显微镜观察标本。'}]}
        materials=[{'asset_id':'history:quote:1','text':'研究者反复观察标本。'}]
        check={'candidate_location':'第1镜.scene_prompt','source_asset_id':'history:quote:1',
               'source_field':'text','source_quote':'研究者反复观察标本。'}
        checks=[{**check,'candidate_quote':'观察标本','conclusion':'supported'},
                {**check,'candidate_quote':'坐在实验台前','conclusion':'not_specified'},
                {**check,'candidate_quote':'用显微镜','conclusion':'not_specified'}]
        finding={'code':'unsupported_reenactment','severity':'blocker','location':'第1镜.scene_prompt',
                 'candidate_quote':'研究者坐在实验台前，用显微镜观察标本。',
                 'source_basis':'history:quote:1只记载“研究者反复观察标本。”，未记载实验台与显微镜。',
                 'message':'删除无据道具与姿态，或改为不指代历史实景的独立观察示意图。'}
        report=V.validate_review({'accepted':True,'source_checks':checks,'issues':[finding]},
                                 candidate=candidate,materials=materials,require_source_checks=True)
        self.assertFalse(report['accepted'])
        self.assertEqual([row['conclusion'] for row in report['source_checks']],
                         ['supported','not_specified','not_specified'])
        self.assertEqual(report['issues'][0]['code'],'unsupported_reenactment')
        self.assertTrue(all(row['validation_issues']==[] for row in report['source_checks']))
        # Validation does not turn an unspecified detail into a contradiction.
        self.assertNotIn('contradicted',[row['conclusion'] for row in report['source_checks']])

    def test_source_checks_require_contiguous_quotes_not_metadata_or_concatenated_records(self):
        candidate = {'shots': [{'scene_prompt': '一个可观察的对象'}]}
        materials = [{'asset_id': 'a', 'text': '甲乙', 'source_context': [
            {'anchor': '仅为定位编号', 'quote': '丙丁'}, {'anchor': '其他编号', 'quote': '戊己'}]}]
        row = {'candidate_location': '第1镜', 'candidate_quote': '一个可观察的对象', 'source_asset_id': 'a',
               'source_field': 'source_context', 'source_quote': '', 'conclusion': 'supported'}
        for quote in ('仅为定位编号', '丙丁戊己', '丙……己'):
            response = {'accepted': True, 'issues': [], 'source_checks': [{**row, 'source_quote': quote}]}
            with self.subTest(quote=quote):
                report = V.validate_review(response, candidate=candidate, materials=materials, require_source_checks=True)
                self.assertEqual(report['source_checks'][0]['conclusion'], 'unverified')
        response['source_checks'][0]['source_quote'] = '丙 丁'
        self.assertTrue(V.validate_review(response, candidate=candidate, materials=materials, require_source_checks=True)['accepted'])

    def test_source_check_shape_is_required_only_for_new_production_review(self):
        case = SOURCE_CHECK_EXPERIMENT
        for rows in (None, {}, [], case['response']['source_checks'] + [case['response']['source_checks'][0]]):
            response = {'accepted': True, 'issues': []}
            if rows is not None:
                response['source_checks'] = rows
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, 'source_checks'):
                V.validate_review(response, candidate=case['candidate'], materials=case['materials'], require_source_checks=True)
        self.assertEqual(V.validate_review({'accepted': True, 'issues': []}), {'accepted': True, 'issues': []})

    def test_handoff_has_full_narration_once_reference_list_and_real_next_steps(self):
        result = V.validate(response(), snapshot(), ALLOWED)
        text = V.render(result)
        self.assertEqual(text.count('熟人社会的关系。'), 1)
        self.assertEqual(text.count('乡土生活的联系。'), 1)
        for section in ('## 已确认口播', '## 按序使用提示词', '## 需要准备的素材', '## 接下来怎么做'):
            self.assertIn(section, text)
        self.assertIn('完整口播录制一次', text)
        self.assertIn('尚未生成图片、视频或录音', text)
        self.assertNotIn('质量已保证', text)

    def test_overlay_copy_is_explicit_optional_and_does_not_enter_image_generation(self):
        data = response('image'); data['shots'][0]['overlay_text'] = '熟人社会：人与人的联系'
        result = V.validate(data, snapshot('image'), ALLOWED)
        self.assertEqual(result['video_prompts']['shots'][0]['overlay_text'], '熟人社会：人与人的联系')
        self.assertIn('后期文字：熟人社会：人与人的联系', V.render(result))
        self.assertNotIn('熟人社会：人与人的联系', result['video_prompts']['shots'][0]['prompt'])
        self.assertEqual(V.validate(response('image'), snapshot('image'), ALLOWED)['video_prompts']['shots'][0]['overlay_text'], '')
        for value in (None, ['错误格式'], '字' * 241):
            data['shots'][0]['overlay_text'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '后期文字'):
                V.validate(data, snapshot('image'), ALLOWED)

    def test_saved_narration_timing_is_respected_and_returned_copy_cannot_mutate_input(self):
        source = snapshot()
        source['narration_timing_plan'][0].update(duration_seconds=20, global_end_seconds=20)
        source['narration_timing_plan'][1].update(duration_seconds=40, global_start_seconds=20)
        data = response(); data['shots'][1]['source_numbers'] = [2]
        pack = V.validate(data, source, ALLOWED)['video_prompts']
        self.assertEqual(pack['shots'][1]['source_numbers'], [2])
        pack['confirmed_outline'][0]['source_text'] = '不能影响输入'
        pack['narration_timing_plan'][0]['duration_seconds'] = 99
        self.assertEqual(source['confirmed_outline'][0]['source_text'], '熟人社会的关系。')
        self.assertEqual(source['narration_timing_plan'][0]['duration_seconds'], 20)

    def test_visual_content_mapping_is_not_an_exact_audio_boundary(self):
        data = response(); data['shots'][1]['source_numbers'] = [1]
        pack = V.validate(data, snapshot(), ALLOWED)['video_prompts']
        self.assertEqual(pack['shots'][1]['source_numbers'], [1])
        self.assertEqual(pack['confirmed_narration'], '熟人社会的关系。\n\n乡土生活的联系。')
        # A reference that only touches a cut cannot be the shot's only temporal anchor.
        source = snapshot()
        source['narration_timing_plan'][0].update(duration_seconds=20, global_end_seconds=20)
        source['narration_timing_plan'][1].update(duration_seconds=40, global_start_seconds=20)
        with self.assertRaisesRegex(ValueError, '实际交叠'):
            V.validate(data, source, ALLOWED)
        data['shots'][1]['source_numbers'] = [1, 2]
        V.validate(data, source, ALLOWED)  # Adjacent carry-over plus current paragraph is valid.
        data['shots'][2]['source_numbers'] = [1, 2]
        with self.assertRaisesRegex(ValueError, '完全错位'):
            V.validate(data, source, ALLOWED)  # Paragraph 1 is well outside this shot.

    def test_actual_prince_cutpoint_carryovers_preserve_all_confirmed_text_and_timeline(self):
        recorded = REVIEW_REGRESSIONS['prince_youth_timing']
        source = copy.deepcopy(recorded['snapshot']); before = copy.deepcopy(source)
        raw = recorded['candidate']
        pack = V.validate(raw, source, set(raw['asset_ids']))['video_prompts']
        self.assertEqual([s['source_numbers'] for s in pack['shots']], [[1], [1, 2], [2, 3], [3]])
        self.assertEqual(pack['shots'][-1]['production_timing']['global_end_seconds'], 30)
        self.assertEqual(pack['confirmed_narration'], '\n\n'.join(p['source_text'] for p in source['confirmed_outline']))
        self.assertEqual(source, before)

    def test_first_stage_accepts_natural_paragraphs_without_six_shot_quota(self):
        source = sample_production(); source['shots'] = [source['shots'][0]]
        source['shots'][0]['end_seconds'] = 60
        result = P.validate(source)
        self.assertEqual(len(result['shots']), 1)
        self.assertNotIn('6至10', P.INSTRUCTION)


if __name__ == '__main__':
    unittest.main()
