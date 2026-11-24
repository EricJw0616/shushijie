"""Production contracts: useful recording copy, continuous shots and explicit asset needs."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import video_production as V
import marketing_delivery as D


def sample_production():
    return {'format': '配图讲解', 'duration_seconds': 60, 'aspect_ratio': '9:16',
            'audience': '成年读者', 'visual_style': '自然纪实配图，留白构图，单镜仅呈现一个观察重点，节奏从容。',
            'shots': [{'start_seconds': n * 10, 'end_seconds': (n + 1) * 10,
                       'voiceover': '先观察根和叶。' if n < 5 else '翻开原书，找找植物生长在哪里。',
                       'visual': '植物叶片近景，右侧留出字幕位置。',
                       'onscreen_text': '观察植物', 'editing': '从全景缓慢推近叶片，末尾直接切换。',
                       'material_ids': ['M01'],
                       'image_prompt': '依照待提供的准确叶片参考图，平视近景，以真实叶形为主体，右侧留白。',
                       'video_prompt': '依照确认过的静帧，镜头缓慢推进叶缘后停留，保持叶片轮廓不变。'} for n in range(6)],
            'materials': [{'id': 'M01', 'name': '植物叶片近景', 'source': '待提供原书照片或核对过的实拍图。',
                           'description': '竖屏，叶片占左侧三分之二，右侧保留白色文字区；使用准确参考图。'}],
            'publishing': {'cover_text': '植物长在哪里？', 'caption': '翻开图志，看一看植物的生长环境。'}}


class VideoProductionTests(unittest.TestCase):
    def test_new_chinese_editorial_budget_counts_spoken_characters_without_mutating_text(self):
        production = {'duration_seconds': 30, 'shots': [{'voiceover': '汉' * 117 + '，10\nA。'}]}
        before = copy.deepcopy(production)
        stats = V.validate_narration_budget(production)
        self.assertEqual(stats['characters'], 120)
        self.assertEqual(stats['limit'], 120)
        self.assertTrue(stats['applies'])
        self.assertEqual(production, before)
        production['shots'][0]['voiceover'] += '多'
        before = copy.deepcopy(production)
        with self.assertRaisesRegex(ValueError, '121.*30秒.*120.*不是实测语速'):
            V.validate_narration_budget(production)
        self.assertEqual(production, before)

    def test_budget_uses_user_duration_and_does_not_mistake_english_for_chinese(self):
        production = {'duration_seconds': 60, 'shots': [{'voiceover': '字' * 160}]}
        self.assertEqual(V.validate_narration_budget(production)['limit'], 240)
        with self.assertRaisesRegex(ValueError, '160.*30秒.*120'):
            V.validate_narration_budget(production, expected_duration=30)
        english = {'duration_seconds': 30, 'shots': [{'voiceover': 'English narration with some 中文. ' * 20}]}
        self.assertFalse(V.validate_narration_budget(english)['applies'])
        for duration in (0, True, float('nan'), 601, '30'):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                V.validate_narration_budget(production, expected_duration=duration)

    def test_recording_copy_and_timeline_share_one_complete_voiceover(self):
        production = V.validate(sample_production())
        body = V.render_body(production)
        for heading in ('配音稿', '镜头脚本', '准备素材', '发布文案', '生成提示词'):
            self.assertEqual(body.count('#### ' + heading), 1)
        recorded = body.split('#### 配音稿\n', 1)[1].split('#### 镜头脚本', 1)[0]
        self.assertEqual(''.join(recorded.split()), ''.join(''.join(x['voiceover'].split()) for x in production['shots']))
        self.assertIn('##### 镜头 06 · 50–60 秒', body)
        self.assertIn('尚未生成图片文件', body)
        self.assertTrue(V.validate_manuscript(body))

    def test_timeline_rejects_gaps_overlaps_missing_ending_and_invalid_seconds(self):
        variants = []
        for field, value in [('start_seconds', 11), ('start_seconds', 9), ('end_seconds', 10),
                             ('end_seconds', 90), ('start_seconds', True), ('end_seconds', 20.5)]:
            p = sample_production(); p['shots'][1][field] = value; variants.append(p)
        p = sample_production(); p['shots'][-1]['end_seconds'] = 59; variants.append(p)
        for p in variants:
            with self.subTest(production=p), self.assertRaises(ValueError):
                V.validate(p)

    def test_materials_are_concrete_named_requirements_used_by_shots(self):
        variants = []
        p = sample_production(); p['shots'][0]['material_ids'] = ['M404']; variants.append(p)
        p = sample_production(); p['materials'].append(copy.deepcopy(p['materials'][0])); variants.append(p)
        p = sample_production(); p['materials'].append({**p['materials'][0], 'id': 'M02'}); variants.append(p)
        p = sample_production(); p['materials'][0]['description'] = ''; variants.append(p)
        p = sample_production(); p['shots'][0]['onscreen_text'] = ''; variants.append(p)
        for p in variants:
            with self.subTest(production=p), self.assertRaises(ValueError):
                V.validate(p)

    def test_production_details_are_not_truncated_to_a_short_channel_paragraph(self):
        p = sample_production()
        p['materials'][0]['description'] = '主体在画面左侧，右侧留出字幕。' * 75
        for shot in p['shots']:
            shot['visual'] = '具体镜头中保留叶片轮廓，并按参考图核对。' * 10
        body = V.render_body(V.validate(p))
        self.assertGreater(len(body), 2400)
        self.assertIn(p['materials'][0]['description'], body)
        self.assertIn('**发布说明：** ' + p['publishing']['caption'], body)

    def test_full_package_export_refuses_divergent_voiceover_without_replacing_edits(self):
        body = V.render_body(V.validate(sample_production()))
        changed = body.replace('先观察根和叶。', '这是手工修改过的配音。', 1)
        source = '## 渠道素材初稿\n\n### 短视频：植物观察 [S1]\n\n' + changed
        before = source
        with self.assertRaisesRegex(ValueError, '配音稿与镜头口播不一致'):
            D.channel_document(source, ['短视频'], {'a': 'S1'})
        self.assertEqual(source, before)
        self.assertIn('先观察根和叶。', D.channel_document(source.replace(changed, body), ['短视频'], {'a': 'S1'})['text'])

    def test_edited_timing_and_duplicate_sections_are_rejected(self):
        body = V.render_body(V.validate(sample_production()))
        for edit in (body.replace('10–20', '11–20'), body.replace('计划 60 秒', '计划 90 秒'),
                     body + '\n\n#### 配音稿\n\n不能出现第二份配音。'):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                V.validate_manuscript(edit)

    def test_legacy_scripts_and_code_samples_are_not_treated_as_new_packages(self):
        self.assertFalse(V.validate_manuscript('【0–10秒】\n口播：原有短稿。'))
        self.assertFalse(V.validate_manuscript('```md\n' + V.render_body(V.validate(sample_production())) + '\n```'))

    def test_prompts_remain_self_contained_for_different_audiences_and_styles(self):
        p = sample_production()
        p['visual_style'] = '黑白学术纪录片，明确器官特写，稳定慢推，单镜只呈现一个比较。'
        production = V.validate(p, audience='植物研究人员')
        for shot in production['shots']:
            prompts = V.generation_prompts(production, shot)
            for text in prompts.values():
                self.assertIn('最终观众：植物研究人员', text)
                self.assertIn('黑白学术纪录片', text)
                self.assertIn('画幅：9:16', text)
                self.assertIn('待提供原书照片', text)
                self.assertIn('文字由剪辑时叠加', text)
            self.assertIn('已确认的静帧', prompts['video_prompt'])
            self.assertIn('计划片段时长：10秒', prompts['video_prompt'])
        self.assertEqual(production['audience'], '植物研究人员')

    def test_legacy_four_section_production_remains_valid_without_new_prompt_fields(self):
        p = sample_production(); p.pop('visual_style'); p.pop('audience')
        for shot in p['shots']:
            shot.pop('image_prompt'); shot.pop('video_prompt')
        body = V.render_body(V.validate(p, require_prompts=False))
        self.assertNotIn('#### 生成提示词', body)
        self.assertTrue(V.validate_manuscript(body))
        with self.assertRaisesRegex(ValueError, '最终观众'):
            V.validate(p)

    def test_new_production_rejects_missing_style_or_per_shot_prompts(self):
        variants = []
        p = sample_production(); p.pop('visual_style'); variants.append(p)
        p = sample_production(); p['shots'][1].pop('image_prompt'); variants.append(p)
        p = sample_production(); p['shots'][2]['video_prompt'] = ''; variants.append(p)
        for p in variants:
            with self.subTest(production=p), self.assertRaises(ValueError):
                V.validate(p)


if __name__ == '__main__':
    unittest.main()
