"""User-facing production pages keep frozen instructions and survive long content."""

import copy
import io
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pdfplumber
from manuscript_pdf import render_export_pdf


def document():
    return {'title': '图片制作包', 'presentation_mode': 'image', 'topic': '读懂小说中的城市',
            'book_titles': ['城市记忆'], 'audience': '成年文学读者', 'visual_style': '黑白木刻插画，人物是小说中的虚构形象。',
            'aspect_ratio': '4:5', 'narration': [{'number': 1, 'text': '跟随这位虚构人物，走进书里的街道。'}],
            'shots': [{'number': 1, 'title': '巷口', 'source_numbers': [1],
                       'source_text': '跟随这位虚构人物，走进书里的街道。', 'overlay_text': '一座城，一段往事',
                       'prompt': '最终观众：成年文学读者。风格：黑白木刻。\n\n画面要求：虚构人物走在巷口，保留左侧空位。\n\n字幕由后期添加。'}],
            'references': [], 'steps': ['按顺序制作图片。', '录制口播，配字幕剪辑成片。']}


def snapshot(value):
    return {'text': '# 保存的旧排版\n\n本包尚未生成图片。', 'production_document': value,
            'export': {'content_kind': 'visual_production', 'presentation_mode': value['presentation_mode']}}


class ProductionPdfTests(unittest.TestCase):
    def inspect(self, value):
        data = render_export_pdf(snapshot(value))
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            texts = [p.extract_text() or '' for p in pdf.pages]
            body = ''.join(p.crop((0, 50, p.width, p.height - 50)).extract_text() or '' for p in pdf.pages)
            for page in pdf.pages:
                # No content escapes the body frame or enters the running labels.
                content = page.crop((0, 50, page.width, page.height - 50))
                if content.chars:
                    self.assertGreaterEqual(min(c['x0'] for c in content.chars), 50)
                    self.assertLessEqual(max(c['x1'] for c in content.chars), page.width - 50)
            self.assertTrue(list(pdf.doc.get_outlines()))
        return data, texts, re.sub(r'\s+', '', body)

    def test_non_nature_package_has_concise_cover_full_prompt_and_no_empty_reference_task(self):
        value = document()
        before = copy.deepcopy(value)
        data, pages, body = self.inspect(value)
        self.assertEqual(value, before)
        self.assertEqual(len(pages), 2)
        self.assertIn('读懂小说中的城市', pages[0])
        self.assertIn('《城市记忆》', pages[0])
        self.assertIn('成年文学读者', pages[0])
        self.assertIn('第 1 张', pages[1])
        self.assertIn('一座城，一段往事', pages[1])
        self.assertIn(re.sub(r'\s+', '', value['shots'][0]['prompt']), body)
        self.assertNotIn('参考图', pages[-1])
        self.assertNotIn('本包尚未生成', '\n'.join(pages))
        self.assertGreaterEqual(data.count(b'/FontFile2'), 2)

    def test_long_video_prompt_spans_pages_with_correct_continuation_then_next_shot(self):
        value = document()
        value.update(title='视频制作包', presentation_mode='video')
        long_prompt = '画面要求：' + '主体保持完整轮廓，镜头缓慢横移，画面中的人物是小说角色。' * 210 + '末尾完整标记。'
        value['shots'][0].update(prompt=long_prompt, duration_seconds=8,
                                  timing={'global_start_seconds': 0, 'global_end_seconds': 8})
        value['shots'].append({'number': 2, 'title': '夜色', 'prompt': '画面要求：远景呈现虚构城市的夜色。'})
        _, pages, body = self.inspect(value)
        self.assertGreater(len(pages), 4)
        self.assertIn(long_prompt, body)
        self.assertIn('时长：8 秒', pages[1])
        self.assertIn('全片位置：0-8 秒', pages[1])
        self.assertIn('书世界 · 第 1 镜 · 续', pages[2])
        next_page = next(p for p in pages if '第 2 镜 / 共 2 镜' in p)
        self.assertIn('书世界 · 第 2 镜', next_page)
        self.assertNotIn('第 1 镜 · 续', next_page)

    def test_old_version_label_on_every_page_and_literal_prompt_symbols_survive(self):
        value = document()
        value['shots'][0]['prompt'] = '字样 <A&B>，保留 **加粗标记** 与 [连接](https://example.test) 原文。'
        snap = snapshot(value)
        snap['export']['stale'] = True
        data = render_export_pdf(snap)
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [p.extract_text() or '' for p in pdf.pages]
        self.assertTrue(all('旧版 · 图片制作包' in p for p in pages))
        self.assertIn(value['shots'][0]['prompt'], ''.join(pages).replace('\n', ''))
        self.assertNotIn('已审核', ''.join(pages))

    def test_partial_structured_record_falls_back_without_losing_saved_markdown(self):
        snap = snapshot(document())
        snap['production_document']['shots'] = []
        data = render_export_pdf(snap)
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            text = '\n'.join(p.extract_text() or '' for p in pdf.pages)
        self.assertIn('保存的旧排版', text)
        self.assertIn('本包尚未生成图片', text)

    def test_no_saved_narration_does_not_claim_the_document_contains_a_voiceover(self):
        value = document()
        value['narration'] = []
        value['shots'][0].pop('source_text')
        value['shots'][0].pop('source_numbers')
        value['steps'] = ['按顺序制作图片。']
        _, pages, _ = self.inspect(value)
        self.assertIn('按顺序制作画面。', pages[0])
        self.assertNotIn('再配口播', pages[0])
        self.assertNotIn('口播稿', pages[0])


if __name__ == '__main__':
    unittest.main()
