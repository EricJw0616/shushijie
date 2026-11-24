"""Portable PDF rendering and frozen downloads; no live project writes."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pdfplumber
import manuscript_pdf as pdf
import projects


def extracted(content):
    with pdfplumber.open(io.BytesIO(content)) as document:
        return '\n'.join(page.extract_text() or '' for page in document.pages), len(document.pages)


class ManuscriptPdfTests(unittest.TestCase):
    def test_chinese_closing_punctuation_does_not_become_a_separate_line(self):
        font, bold = pdf._typefaces('阅读，？！')
        style = pdf.ParagraphStyle('ChinesePunctuation', fontName=font, fontSize=10,
                                   leading=15, wordWrap='CJK')
        for mark in '，？！':
            for prefix in ('阅读阅读阅读', '<b>阅读</b>阅读阅读'):
                paragraph = pdf.Paragraph(prefix + mark, style)
                paragraph.wrap(60.1, 100)
                self.assertEqual(len(paragraph.blPara.lines), 1, (prefix, mark))

    def test_visual_production_long_prompt_keeps_all_text_across_pages(self):
        prompt = '主体位于画面中部，保留右侧留白，形态遵循已确认的参考图。' * 180
        snapshot = {'filename': '视频展示-制作包.md',
                    'text': '# 视频展示制作包\n\n## 第八镜头\n\n' + prompt +
                            '\n\n尾部完整标记。\n\n## 制作步骤\n\n合成画面与口播后核对成片。',
                    'export': {'content_kind': 'visual_production', 'presentation_mode': 'video',
                               'mode': 'approved'}}
        data = pdf.render_export_pdf(snapshot)
        text, pages = extracted(data)
        with pdfplumber.open(io.BytesIO(data)) as document:
            body = ''.join(page.crop((0, 50, page.width, page.height - 50)).extract_text() or ''
                           for page in document.pages)
        compact = ''.join(text.split())
        self.assertGreater(pages, 1)
        self.assertIn(prompt, ''.join(body.split()))
        self.assertIn('尾部完整标记', compact)
        self.assertIn('合成画面与口播后核对成片', compact)
        self.assertEqual(text.count('视频展示-制作包'), pages)
        self.assertNotIn('已审核', text)
        self.assertNotIn('审阅稿', text)

    def test_channel_pdf_identifies_the_output_without_internal_project_labels(self):
        snapshot = {'text': '# 名字里的植物\n\n从名字开始，翻开图志认识植物。',
                    'export': {'content_kind': 'channel_content', 'channels': ['公众号'],
                               'mode': 'approved', 'project_revision': 7}}
        content, _ = extracted(pdf.render_export_pdf(snapshot))
        self.assertIn('公众号文章', content)
        self.assertIn('名字里的植物', content)
        self.assertNotIn('项目版本', content)
        self.assertNotIn('交付稿', content)
        snapshot['export']['mode'] = 'review'
        content, _ = extracted(pdf.render_export_pdf(snapshot))
        self.assertIn('待审核', content)

    def test_embeds_bundled_regular_and_bold_without_system_fonts(self):
        text = '# 植物观察笔记\n\n**认识桔梗与元宝草**。繁體中文：觀察與發現。English 123 β →。'
        with patch.dict(os.environ, {'BOOKDISTILL_PDF_FONT': '', 'WINDIR': '/no-system-fonts'}), \
             patch.object(Path, 'home', side_effect=AssertionError('Must not read personal fonts')), \
             patch.object(pdf, '_load_font', wraps=pdf._load_font) as loaded:
            result = pdf.render_export_pdf({'text': text, 'export': {'mode': 'approved'}})
        self.assertTrue(result.startswith(b'%PDF-'))
        self.assertGreaterEqual(result.count(b'/FontFile2'), 2)
        self.assertTrue(all(Path(call.args[0]).parent == pdf._FONT_DIR for call in loaded.call_args_list))
        content, pages = extracted(result)
        self.assertIn('植物观察笔记', content)
        self.assertIn('认识桔梗与元宝草', content)
        self.assertIn('觀察與發現', content)
        self.assertNotIn('\ufffd', content)
        self.assertEqual(pages, 1)

    def test_plan_pdf_keeps_arrangements_without_internal_project_wrapper(self):
        snapshot={'text':'# 共读营销方案\n\n## 推进安排\n\n内容编辑准备公众号文章，营销编辑记录读者提问。',
                  'export':{'content_kind':'marketing_plan','mode':'approved','project_revision':12}}
        content,_=extracted(pdf.render_export_pdf(snapshot))
        for text in ('营销方案','推进安排','内容编辑准备公众号文章'):
            self.assertIn(text,content)
        for text in ('项目版本','已审核交付稿','任务说明','材料与来源'):
            self.assertNotIn(text,content)

    def test_tables_and_long_chinese_text_paginate_and_preserve_last_row(self):
        rows = ['| 时段 | 画面与口播 |', '| --- | --- |']
        rows += ['| 第%d段 | %s |' % (n, '观察植物形态，翻阅原书核对名称。' * 8) for n in range(1, 29)]
        result = pdf.render_export_pdf({'text': '# 植物短视频脚本\n\n' + '\n'.join(rows),
                                       'export': {'mode': 'review', 'project_revision': 7}})
        content, pages = extracted(result)
        compact = ''.join(content.split())
        self.assertGreater(pages, 1)
        self.assertIn('第28段', compact)
        self.assertIn('观察植物形态', compact)
        self.assertEqual(content.count('审阅稿'), pages)
        self.assertEqual(content.count('画面与口播'), pages)

    def test_missing_glyph_fails_explicitly_instead_of_silent_tofu(self):
        with patch.dict(os.environ, {'BOOKDISTILL_PDF_FONT': ''}):
            with self.assertRaisesRegex(ValueError, '缺少稿件中的字形'):
                pdf.render_export_pdf({'text': '# 未覆盖字形\n\n' + '🦕'})

    def test_font_files_match_the_recorded_build(self):
        manifest = json.loads((pdf._FONT_DIR / 'manifest.json').read_text())
        for name, info in manifest['files'].items():
            content = (pdf._FONT_DIR / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), info['sha256'])
            self.assertEqual(content[:4], b'\x00\x01\x00\x00')
        self.assertTrue((pdf._FONT_DIR / 'OFL-NotoSansSC.txt').is_file())

    def test_cached_download_uses_frozen_export_without_changing_project(self):
        pid, eid = 'prj-' + 'a' * 16, 'export-' + 'b' * 16
        with tempfile.TemporaryDirectory() as folder, patch.object(projects, 'DIR', folder):
            root = Path(folder); (root / 'exports').mkdir()
            project = {'id': pid, 'draft': '正在修改但未交付的新内容', 'exports': [{'id': eid}]}
            original = json.dumps(project, ensure_ascii=False)
            (root / (pid + '.json')).write_text(original)
            (root / 'exports' / (eid + '.json')).write_text(json.dumps({
                'id': eid, 'mode': 'approved', 'filename': '植物交付稿.md',
                'text': '# 冻结的植物交付稿\n\n这一份只包含审核时保存的内容。'}, ensure_ascii=False))
            filename, content, mime = projects.get_export_download(pid, eid, 'pdf')
            self.assertEqual((filename, mime), ('植物交付稿.pdf', 'application/pdf'))
            text, _ = extracted(content)
            self.assertIn('冻结的植物交付稿', text)
            self.assertNotIn('未交付的新内容', text)
            self.assertEqual((root / (pid + '.json')).read_text(), original)
            with patch.object(pdf, 'render_export_pdf', side_effect=AssertionError('Cached file should be reused')):
                self.assertEqual(projects.get_export_download(pid, eid, 'pdf')[1], content)
            self.assertEqual(list((root / 'exports').glob('.pdf-*')), [])


if __name__ == '__main__':
    unittest.main()
