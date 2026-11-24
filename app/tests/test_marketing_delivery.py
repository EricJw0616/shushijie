"""The channel delivery is a projection of the current draft, never of an old model run."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import marketing_delivery as D
import projects as P
import video_production as V
from test_video_production import sample_production


LEGACY = ('# 内部讨论稿\n\n原始策划判断。\n\n## 传播角度与受众价值\n\n内部角度。\n\n'
          '## 渠道内容与表达安排\n\n制作顺序。\n\n## 渠道素材初稿\n\n'
          '### 公众号：观察植物的名字 [S1]\n\n《植物图志》写到了民间命名方法。[S1]\n\n'
          '## 从名字找线索\n\n这是编辑手工增加的正文。\n\n### 看看叶子\n\n留下自己的观察。\n\n'
          '行动引导：翻开原书，找一种喜欢的植物。\n\n'
          '## 材料怎样复用\n\n内部加工建议。[S1]\n\n## 来源索引\n\n[S1] 来源条目。')


class MarketingDeliveryTests(unittest.TestCase):
    def project(self, draft=LEGACY):
        return {'kind': 'marketing', 'title': '植物科普讲座', 'revision': 7,
                'brief': {'marketing_task': 'channel', 'channels': ['公众号'], 'target_codes': ['B56']},
                'draft': draft, 'draft_generation': {'source_labels': {'B56:quote:a': 'S1'}},
                'items': []}

    def test_legacy_copy_retains_manual_edits_and_ordinary_subheadings(self):
        p = self.project(); before = copy.deepcopy(p)
        text = P._markdown(p, [], 'approved')
        self.assertTrue(text.startswith('# 观察植物的名字\n'))
        for body in ('《植物图志》写到了民间命名方法。', '## 从名字找线索', '### 看看叶子',
                     '这是编辑手工增加的正文。', '翻开原书，找一种喜欢的植物。'):
            self.assertIn(body, text)
        for note in ('内部', '制作顺序', '材料怎样复用', '来源索引', '[S1]', '任务说明', '行动引导：'):
            self.assertNotIn(note, text)
        self.assertEqual(p, before)

    def test_clean_channel_document_keeps_user_sections_even_with_process_words(self):
        source = ('## 渠道素材初稿\n\n### 公众号：如何写一本书 [S1]\n\n正文。\n\n'
                  '## 材料怎样复用\n\n这是本文真正讨论的问题。\n\n行动引导：也可以成为文章谈论的概念。')
        result = D.channel_document(source, ['公众号'], {'a': 'S1'})['text']
        self.assertIn('## 材料怎样复用', result)
        self.assertIn('行动引导：也可以成为文章谈论的概念。', result)

    def test_multichannel_keeps_film_instructions_and_edited_content(self):
        source = ('## 渠道素材初稿\n\n### 公众号：我的文章 [S1]\n\n人工文章。\n\n'
                  '### 短视频：植物一分钟 [S2]\n\n| 秒数 | 画面 | 口播 |\n| --- | --- | --- |\n'
                  '| 0-10 | 叶片特写 | 来认一认这片叶子。 |\n\n## 拍摄补充\n\n自然光。')
        result = D.channel_document(source, ['公众号', '短视频'], {'a': 'S1', 'b': 'S2'})
        self.assertEqual(result['channels'], ['公众号', '短视频'])
        self.assertIn('# 公众号：我的文章', result['text'])
        self.assertIn('# 短视频：植物一分钟', result['text'])
        self.assertIn('| 0-10 | 叶片特写 | 来认一认这片叶子。 |', result['text'])
        self.assertIn('## 拍摄补充', result['text'])

    def test_markers_do_not_erase_links_footnotes_literal_code_or_unknown_labels(self):
        protected = ('[S1](https://example.org) [S1][note] [^S1] [S9] `示例 [S1]` '
                     '``示例 ` [S1]`` \\[S1]\n[S9]: https://example.org\n'
                     '    示例 [S1]\n\n```md\n## 渠道素材初稿\n### 短视频：示例 [S1]\n```')
        cleaned = D.clean_markers('实际引用[S1]。\n' + protected, {'a': 'S1'})
        self.assertEqual(cleaned, '实际引用。\n' + protected)
        self.assertEqual(D.clean_markers('标题 [S1] [S2]', {'a': 'S1', 'b': 'S2'}).strip(), '标题')
        defined = '[S1] [S2]\n\n[S2]: https://example.org\n\n[S1]\n\n[S1]: https://example.net'
        self.assertEqual(D.clean_markers(defined, {'a': 'S1', 'b': 'S2'}), defined)

    def test_code_fences_never_create_scene_boundaries(self):
        source = ('## 渠道素材初稿\n\n### 公众号：讲解格式 [S1]\n\n真实正文。\n\n'
                  '~~~md\n## 渠道素材初稿\n### 短视频：只在示例里\n~~~\n\n正文结尾。')
        text = D.channel_document(source, ['公众号'], {'a': 'S1'})['text']
        self.assertIn('### 短视频：只在示例里', text)
        self.assertTrue(text.endswith('正文结尾。'))

    def test_handwritten_single_channel_is_preserved(self):
        source = '# 人工标题\n\n正文谈论材料复用，不应因这些字被删除。\n\n## 自己的小标题\n\n结尾。'
        result = D.channel_document(source, ['公众号'], {}, '项目名')
        self.assertEqual(result['text'], source)
        self.assertFalse(result['structured'])

    def test_ambiguous_documents_fail_without_silently_dropping_text(self):
        cases = [
            ('## 渠道素材初稿\n\n### 公众号：标题\n\n一段\n\n### 公众号：另一标题\n\n另一段', ['公众号']),
            ('## 渠道素材初稿\n\n### 公众号：标题\n\n一段', ['公众号', '短视频']),
            ('## 渠道素材初稿\n\n编辑新增的前言不能丢。\n\n### 公众号：标题\n\n一段', ['公众号']),
            ('额外的正文不能丢。\n\n## 渠道素材初稿\n\n### 公众号：标题\n\n一段', ['公众号']),
            (LEGACY.replace('## 渠道素材初稿', '## 渠道部分'), ['公众号']),
            ('不区分场景的混合内容', ['公众号', '短视频']),
            ('## 渠道素材初稿\n\n### 公众号：标题\n\n', ['公众号']),
        ]
        for source, channels in cases:
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, '返回稿件'):
                D.channel_document(source, channels, {})

    def test_review_export_keeps_real_reference_issue_visible(self):
        p = self.project()
        text = P._markdown(p, [], 'review', [{'kind': 'source_changed', 'title': '植物', 'reason': '出处已变化'}])
        self.assertTrue(text.startswith('> 审阅稿：引用尚待核对'))
        self.assertIn('# 观察植物的名字', text)
        self.assertNotIn('材料怎样复用', text)

    def test_legacy_reserved_article_headings_do_not_silently_cut_copy(self):
        normal = LEGACY.replace('## 来源索引', '## 需要补充\n\n系统待补说明。\n\n## 来源索引')
        for heading in ('需要补充', '材料怎样复用', '来源索引'):
            edited = normal.replace('## 从名字找线索', '## ' + heading)
            with self.subTest(heading=heading), self.assertRaisesRegex(ValueError, '返回稿件'):
                D.channel_document(edited, ['公众号'], {'a': 'S1'})
        # Even without a duplicate, a false boundary cannot begin with a needs heading.
        with self.assertRaisesRegex(ValueError, '返回稿件'):
            D.channel_document(LEGACY.replace('## 从名字找线索', '## 需要补充'), ['公众号'], {'a': 'S1'})
        # Different, correctly ordered appendix sections remain valid.
        text = D.channel_document(normal, ['公众号'], {'a': 'S1'})['text']
        self.assertIn('这是编辑手工增加的正文。', text)
        self.assertNotIn('系统待补说明。', text)

    def test_legacy_unknown_or_reordered_appendix_is_rejected(self):
        for edited in (
                LEGACY.replace('## 来源索引', '## 另一个正文小标题\n\n不能漏掉。\n\n## 来源索引'),
                LEGACY.replace('## 来源索引', '## 来源索引\n\n正常索引。\n\n## 需要补充'),
                LEGACY.replace('## 来源索引', '### 短视频：另一场景不能漏掉\n\n正文。\n\n## 来源索引')):
            with self.subTest(edited=edited), self.assertRaisesRegex(ValueError, '返回稿件'):
                D.channel_document(edited, ['公众号'], {'a': 'S1'})

    def test_existing_frozen_export_and_cached_pdf_are_not_rewritten(self):
        pid, eid = 'prj-' + 'a' * 16, 'export-' + 'b' * 16
        with tempfile.TemporaryDirectory() as folder, patch.object(P, 'DIR', folder):
            root = Path(folder); (root / 'exports').mkdir()
            (root / (pid + '.json')).write_text(json.dumps({'id': pid, 'draft': '新稿', 'exports': [{'id': eid}]}))
            old = json.dumps({'id': eid, 'filename': '旧讨论稿.md', 'mode': 'approved', 'text': LEGACY})
            (root / 'exports' / (eid + '.json')).write_text(old)
            old_pdf = b'%PDF-1.4 frozen legacy bytes'
            (root / 'exports' / (eid + '.pdf')).write_bytes(old_pdf)
            self.assertEqual(P.get_export(pid, eid)['text'], LEGACY)
            self.assertEqual(P.get_export_download(pid, eid, 'pdf')[1], old_pdf)
            self.assertEqual((root / 'exports' / (eid + '.json')).read_text(), old)

    def test_new_video_export_contains_only_title_and_complete_narration(self):
        for with_prompts in (False, True):
            production = V.validate(sample_production(), include_prompts=with_prompts)
            body = V.render_body(production)
            source = '## 渠道素材初稿\n\n### 短视频：观察在哪里\n\n' + body
            before = source
            text = D.channel_document(source, ['短视频'])['text']
            self.assertTrue(text.startswith('# 观察在哪里\n\n'))
            self.assertEqual(text.count('先观察根和叶。'), 5)
            self.assertEqual(text.count('翻开原书，找找植物生长在哪里。'), 1)
            for hidden in ('####', '画面：', '屏幕文字：', '剪辑：', '使用素材：', '素材要求', '封面文字',
                           '发布说明', '生图提示词', '生视频提示词', '计划 60 秒'):
                self.assertNotIn(hidden, text)
            internal = D.channel_document(source, ['短视频'], include_video_production=True)['text']
            self.assertIn('#### 镜头脚本', internal)
            self.assertIn('50–60 秒', internal)
            self.assertEqual(source, before)
            standalone = D.channel_document('# 当前人工标题\n\n' + body, ['短视频'], fallback_title='项目名')['text']
            self.assertTrue(standalone.startswith('# 当前人工标题\n\n'))
            self.assertNotIn('#### 准备素材', standalone)


if __name__ == '__main__':
    unittest.main()
