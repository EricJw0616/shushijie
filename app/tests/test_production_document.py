"""Production PDFs reorganize saved instructions; they do not author a new plan."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import production_document as document
import video_prompts as prompts
from test_video_prompts_quality import snapshot, response, ALLOWED


def saved_run(mode='image', *, references=True):
    frozen = snapshot(mode)
    frozen.update(title='乡土生活中的联系',
                  marketing={'target_books': [{'code': 'B1', 'book': '乡土中国'}]},
                  materials=[{'book': '乡土中国', 'text': '书中材料原文'},
                             {'book': '另一本背景资料', 'text': '辅助说明'}])
    data = response(mode)
    if not references:
        data['references'] = []
        for shot in data['shots']:
            shot['reference_ids'] = []
    result = prompts.validate(data, frozen, ALLOWED)
    return {'result': result, 'snapshot': frozen, 'markdown': prompts.render(result)}


def legacy_run():
    frozen = snapshot('video')
    frozen['title'] = '旧版口播与镜头'
    pack = {'presentation_mode': 'video', 'audience': '成年文学读者',
            'visual_style': '黑白木刻插画', 'aspect_ratio': '16:9', 'shots': [
                {'number': row['number'], 'title': row['title'], 'source_text': row['source_text'],
                 'prompt': '面向成年文学读者。黑白木刻，16:9。第%d镜的原始提示词，必须完整保留。' % row['number'],
                 'duration_seconds': 12.5,
                 'production_timing': {'global_start_seconds': (row['number'] - 1) * 12.5,
                                       'global_end_seconds': row['number'] * 12.5}}
                for row in frozen['confirmed_outline']]}
    result = {'video_prompts': pack}
    return {'snapshot': frozen, 'result': result, 'markdown': prompts.render(result)}


class ProductionDocumentTests(unittest.TestCase):
    def test_image_layout_preserves_every_saved_prompt_and_confirmed_paragraph(self):
        run = saved_run(); before = copy.deepcopy(run)
        result = document.build_production_document(run)
        pack = run['result']['video_prompts']
        self.assertEqual([s['prompt'] for s in result['shots']], [s['prompt'] for s in pack['shots']])
        self.assertEqual([r['text'] for r in result['narration']],
                         [r['source_text'] for r in pack['confirmed_outline']])
        self.assertEqual(result['shots'][0]['source_numbers'], [1, 2])
        self.assertEqual(result['audience'], pack['audience'])
        self.assertEqual(result['visual_style'], pack['visual_style'])
        self.assertEqual(result['aspect_ratio'], pack['aspect_ratio'])
        self.assertEqual(result['book_titles'], ['乡土中国'])
        self.assertNotIn('材料原文', str(result))
        self.assertNotIn('辅助说明', str(result))
        self.assertEqual(run, before)

    def test_video_layout_keeps_global_timing_and_self_contained_motion_prompts(self):
        run = saved_run('video')
        result = document.build_production_document(run)
        self.assertEqual(result['title'], '视频制作包')
        self.assertEqual([(s['timing']['global_start_seconds'], s['timing']['global_end_seconds'])
                          for s in result['shots']], [(0, 20), (20, 40), (40, 60)])
        self.assertEqual([s['duration_seconds'] for s in result['shots']], [20, 20, 20])
        for shot, source in zip(result['shots'], run['result']['video_prompts']['shots']):
            self.assertEqual(shot['prompt'], source['prompt'])
            self.assertIn('0–10秒', shot['prompt'])
            self.assertIn('运镜', shot['prompt'])
        self.assertIn('逐镜', result['steps'][0])
        self.assertNotIn('逐张', result['steps'][0])
        self.assertIn('只生成画面，不生成口播或对白', result['steps'][0])
        self.assertIn('统一加入完整配音和字幕', result['steps'][-1])

    def test_previous_video_steps_keep_compact_delivery_without_changing_saved_run(self):
        run = saved_run('video')
        run['result']['video_prompts']['production_steps'] = [
            '逐项准备所列参考素材；准确对象或真实人物先核对参考。',
            '在外部制作工具中上传各条提示词所需的参考图，再按顺序复制提示词生成画面，核对对象、结构和文字留白。',
            '完整口播录制一次；将片段按计划顺序剪辑，配上完整录音、字幕，再按实际录音调整时长。']
        run['markdown'] = prompts.render(run['result'])
        before = copy.deepcopy(run)
        projected = document.build_production_document(run)
        self.assertIn('逐镜', projected['steps'][0])
        self.assertIn('不生成口播或对白', projected['steps'][0])
        self.assertIn('统一加入完整配音和字幕', projected['steps'][-1])
        self.assertEqual(run, before)

    def test_extended_system_steps_are_custom_and_remain_verbatim(self):
        for mode in ('image', 'video'):
            run = saved_run(mode)
            instructions = run['result']['video_prompts']['production_steps']
            instructions[-1] += '另外导出不含字幕的 16:9 版本供合作方使用。'
            run['markdown'] = prompts.render(run['result'])
            with self.subTest(mode=mode):
                projected = document.build_production_document(run)
                self.assertEqual(projected['steps'], instructions)
                self.assertIsNot(projected['steps'], instructions)

    def test_legacy_video_uses_frozen_outline_not_a_current_or_invented_narration(self):
        run = legacy_run()
        self.assertNotIn('confirmed_narration', run['result']['video_prompts'])
        run['draft'] = '当前项目的新稿件不能混进旧版。'
        result = document.build_production_document(run)
        self.assertEqual([r['text'] for r in result['narration']],
                         [r['source_text'] for r in run['snapshot']['confirmed_outline']])
        self.assertEqual([s['source_numbers'] for s in result['shots']], [[1], [2]])
        self.assertEqual([s['title'] for s in result['shots']], ['', ''])
        self.assertNotIn('当前项目的新稿件', str(result))
        self.assertEqual(result['shots'][0]['prompt'], run['result']['video_prompts']['shots'][0]['prompt'])

    def test_literary_package_without_references_has_no_phantom_upload_task(self):
        frozen = snapshot('image')
        frozen['title'] = '小王子与狐狸'
        frozen['marketing'] = {'target_books': [{'book': '小王子'}]}
        data = response('image')
        data['visual_style'] = '平涂水彩插画，橙色沙漠与蓝色夜空。'
        data['references'] = []
        data['shots'][0].update(reference_ids=[], depiction_type='fictional_scene',
                                focus='小王子与狐狸', prompt='橙色沙漠上，小王子与狐狸相对而坐。')
        result = prompts.validate(data, frozen, ALLOWED)
        run = {'snapshot': frozen, 'result': result, 'markdown': prompts.render(result)}
        exported = document.build_production_document(run)
        self.assertEqual(exported['book_titles'], ['小王子'])
        self.assertEqual(exported['references'], [])
        self.assertNotIn('上传', ''.join(exported['steps']))
        self.assertNotIn('植物', str(exported))
        self.assertIn('小王子与狐狸', exported['shots'][0]['prompt'])

    def test_unknown_viewer_does_not_become_a_buyer_or_book_reader(self):
        run = saved_run()
        del run['result']['video_prompts']['audience']
        run['snapshot']['marketing_context'] = {'roles': {'viewer': '', 'decision_maker': '购买图书的家长',
                                                         'book_readers': '高中生'}}
        result = document.build_production_document(run)
        self.assertEqual(result['audience'], '')
        self.assertNotIn('购买图书的家长', str(result))
        self.assertNotIn('高中生', str(result))

    def test_historical_book_for_adults_keeps_its_own_subject_and_viewer(self):
        frozen = snapshot('image')
        frozen.update(title='古城街巷', marketing={'target_books': [{'book': '古城生活史'}]})
        frozen['brief']['audience'] = '成年历史爱好者'
        frozen['marketing_context']['roles'] = {'viewer': '成年历史爱好者', 'book_readers': '城市史研究者',
                                               'decision_maker': '图书馆采购人员'}
        frozen['confirmed_outline'] = [
            {'number': 1, 'title': '第 1 段', 'source_text': '从城门进入，沿着街巷看古城的生活。'},
            {'number': 2, 'title': '第 2 段', 'source_text': '市集与民居沿街展开。'}]
        data = response('image')
        data.update(visual_style='赭石与灰蓝的历史场景插画，区分街巷与建筑轮廓。',
                    audience_adaptation='用街巷俯视图说明市集和民居的相邻位置。')
        data['shots'][0].update(title='城门后的街市', focus='古城街巷与市集',
                                depiction_type='historical_scene', scene_description='城门内的街市一角',
                                prompt='从城门内侧看街市，民居在街道两侧。这是历史场景重现，不是档案照片。')
        data['references'][0].update(name='街巷形制参考', kind='accurate_reference', status='required',
                                      requirement='待提供书中对应年代的街巷与建筑形制图，保留街道布局。')
        result = prompts.validate(data, frozen, ALLOWED)
        run = {'snapshot': frozen, 'result': result, 'markdown': prompts.render(result)}
        exported = document.build_production_document(run)
        self.assertEqual(exported['audience'], '成年历史爱好者')
        self.assertEqual(exported['book_titles'], ['古城生活史'])
        self.assertIn('历史场景重现', exported['shots'][0]['prompt'])
        self.assertNotIn('植物', str(exported))
        self.assertNotIn('11–14', str(exported))
        self.assertNotIn('图书馆采购人员', str(exported))
        self.assertNotIn('城市史研究者', str(exported))

    def test_customized_markdown_uses_original_document_instead_of_dropping_notes(self):
        for change in ('\n\n## 编辑补充\n\n出版方指定：保留结尾的联系信息。',
                       '\n\n原书引用：[S9] 引用说明。'):
            run = saved_run(); run['markdown'] += change
            self.assertIsNone(document.build_production_document(run))
        run = saved_run()
        run['markdown'] = run['markdown'].replace('书中观点', '编辑改写的观点')
        self.assertIsNone(document.build_production_document(run))

    def test_malformed_or_missing_structured_shots_fall_back_without_guessing(self):
        for value in (None, [], {}, [None], [{'number': 1, 'prompt': ''}],
                      [{'number': True, 'prompt': '正文'}]):
            run = saved_run(); run['result']['video_prompts']['shots'] = value
            with self.subTest(shots=value):
                self.assertIsNone(document.build_production_document(run))

    def test_conflicting_full_narration_wins_over_inconsistent_paragraph_metadata(self):
        run = saved_run()
        pack = run['result']['video_prompts']
        pack['confirmed_narration'] = '编辑已确认的完整口播，不能被旧段落覆盖。'
        run['markdown'] = prompts.render(run['result'])
        result = document.build_production_document(run)
        self.assertEqual(result['narration'], [{'number': None, 'text': pack['confirmed_narration']}])
        self.assertTrue(all(not s['source_numbers'] and not s['source_text'] for s in result['shots']))

    def test_missing_frozen_narration_is_omitted_instead_of_using_a_draft(self):
        run = legacy_run(); run['snapshot'].pop('confirmed_outline')
        run['snapshot']['draft'] = '未确认草稿不属于口播全文。'
        result = document.build_production_document(run)
        self.assertEqual(result['narration'], [])
        self.assertNotIn('未确认草稿', str(result))
        self.assertEqual(len(result['steps']), 1)
        for instruction in ('录制', '配音', '字幕', '剪辑'):
            self.assertNotIn(instruction, ''.join(result['steps']))

    def test_book_titles_can_come_from_frozen_materials_without_live_library(self):
        run = legacy_run()
        run['snapshot']['materials'] = [{'book': '诗经'}, {'book': '楚辞'}, {'book': '诗经'}, {}]
        result = document.build_production_document(run)
        self.assertEqual(result['book_titles'], ['诗经', '楚辞'])

    def test_bad_optional_book_metadata_does_not_block_an_existing_package(self):
        for malformed in (42, '无法识别的旧字段', {'book': '不是列表'}):
            run = legacy_run()
            run['snapshot']['materials'] = malformed
            with self.subTest(materials=malformed):
                result = document.build_production_document(run)
                self.assertEqual(result['book_titles'], [])
                self.assertEqual(result['shots'][0]['prompt'], run['result']['video_prompts']['shots'][0]['prompt'])

    def test_unrecognized_result_or_reference_collection_falls_back_safely(self):
        for bad_result in ([], ['unexpected'], 'unexpected', 123):
            run = saved_run(); run['result'] = bad_result
            with self.subTest(result=bad_result):
                self.assertIsNone(document.build_production_document(run))
        for bad_references in (None, {'R1': {'name': '资料'}}, 42, '资料'):
            run = legacy_run(); run['result']['video_prompts']['references'] = bad_references
            with self.subTest(references=bad_references):
                self.assertIsNone(document.build_production_document(run))

    def test_custom_production_steps_are_preserved_in_both_modes(self):
        instructions = ['先使用出版社提供的封面原图，不重新绘制书名。',
                        '在结尾保留书店活动时间：周六 14:30。',
                        '交付 16:9 横版，另存无字幕版本供合作方剪辑。']
        for mode in ('image', 'video'):
            run = saved_run(mode)
            run['result']['video_prompts']['production_steps'] = list(instructions)
            run['markdown'] = prompts.render(run['result'])
            with self.subTest(mode=mode):
                result = document.build_production_document(run)
                self.assertEqual(result['steps'], instructions)
                result['steps'].append('仅修改显示副本。')
                self.assertEqual(run['result']['video_prompts']['production_steps'], instructions)

    def test_malformed_custom_production_steps_keep_the_original_document(self):
        for steps in (['明确动作', None], ['明确动作', ''], ['明确动作', {'note': '附件'}]):
            run = saved_run()
            run['result']['video_prompts']['production_steps'] = steps
            run['markdown'] = prompts.render(run['result'])
            with self.subTest(steps=steps):
                self.assertIsNone(document.build_production_document(run))

    def test_reference_status_is_not_presented_as_a_second_confirmation_workflow(self):
        run = saved_run()
        reference = run['result']['video_prompts']['references'][0]
        reference.update(requirement='待提供：器物正面图，保留 4 个孔位与 0.5 厘米的边缘缺口。',
                         status='required')
        run['markdown'] = prompts.render(run['result'])
        result = document.build_production_document(run)
        self.assertEqual(result['references'][0]['requirement'], '器物正面图，保留 4 个孔位与 0.5 厘米的边缘缺口。')
        self.assertEqual(result['references'][0]['shot_numbers'], [1])
        self.assertNotIn('status', result['references'][0])
        self.assertEqual(result['shots'][0]['prompt'], run['result']['video_prompts']['shots'][0]['prompt'])


if __name__ == '__main__':
    unittest.main()
