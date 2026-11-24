"""Coordinate-backed PDF review gates; no OCR or model service required."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'platform' / 'engine'))

import atlas
import wash


def glyph_rows(spacing=24, leading=13, columns=2):
    return [{'text': '甲乙丙丁'[col], 'x0': 80 + col * spacing,
             'x1': 90 + col * spacing, 'top': 100 + row * leading,
             'bottom': 110 + row * leading}
            for row in range(6) for col in range(columns)]


def booklist(page=198):
    lines = [{'t': '系列书目', 'k': 'body', 'top': 60, 'x0': 180, 'x1': 220}]
    for i in range(12):
        x0 = 40 if i % 2 == 0 else 230
        lines.append({'t': '作者' + chr(0x7532 + i) + '：一部有趣的作品',
                      'k': 'body', 'top': 100 + i // 2 * 20, 'x0': x0, 'x1': x0 + 140})
    return {'page': page, 'w': 440, 'h': 600, 'lines': lines}


class PageSafetyTests(unittest.TestCase):
    def test_interleaved_vertical_glyphs_require_repeated_coordinates(self):
        self.assertTrue(atlas._interleaved_vertical_rows(glyph_rows()))
        self.assertFalse(atlas._interleaved_vertical_rows(glyph_rows()[:6]))
        self.assertFalse(atlas._interleaved_vertical_rows(glyph_rows(columns=1)))

    def test_horizontal_short_lines_and_prose_are_not_vertical(self):
        self.assertFalse(atlas._interleaved_vertical_rows(glyph_rows(spacing=11)))
        self.assertFalse(atlas._interleaved_vertical_rows(glyph_rows(leading=24)))
        prose = glyph_rows(spacing=11, columns=4)
        self.assertFalse(atlas._interleaved_vertical_rows(prose))

    def test_catalogue_requires_tail_heading_and_aligned_distinct_authors(self):
        self.assertTrue(atlas._backmatter_booklist(booklist(), 200))
        self.assertFalse(atlas._backmatter_booklist(booklist(page=100), 200))
        for heading in ('参考文献', '人物对话', '目录'):
            page = booklist()
            page['lines'][0]['t'] = heading
            self.assertFalse(atlas._backmatter_booklist(page, 200))
        page = booklist()
        page['bookmarks'] = [{'title': '系列书目', 'level': 1}]
        self.assertFalse(atlas._backmatter_booklist(page, 200))
        page = booklist()
        for line in page['lines'][1:]:
            line['x0'] = 40
        self.assertFalse(atlas._backmatter_booklist(page, 200))

    def test_catalogue_does_not_absorb_explanatory_prose(self):
        page = booklist()
        page['lines'].append({'t': '这段文字解释作者的观点。', 'k': 'body',
                              'top': 400, 'x0': 40, 'x1': 220})
        self.assertFalse(atlas._backmatter_booklist(page, 200))

    def test_non_body_is_preserved_in_layout_but_excluded_from_text_and_entries(self):
        pages = [{'page': 1, 'lines': [{'t': '正常正文。', 'k': 'body'}]},
                 {'page': 2, 'non_body': 'backmatter_booklist',
                  'lines': [{'t': '目录中的作者和书名。', 'k': 'body'}]},
                 {'page': 3, 'layout_review': 'vertical_text_order',
                  'lines': [{'t': '串列的待核对文字。', 'k': 'body'}]}]
        text = atlas.pages_to_text(pages, mark_pages=True)
        self.assertNotIn('目录中的作者', text)
        self.assertIn('串列的待核对文字', text)
        self.assertEqual(pages[1]['lines'][0]['t'], '目录中的作者和书名。')
        with patch.object(atlas, '_cut_entries', side_effect=lambda full, *args: full):
            self.assertEqual(atlas.entries_from_pages(pages), '正常正文。\n')

    def test_layout_review_survives_accepted_ocr_and_old_raw_cannot_restore_catalogue(self):
        pages = [{'page': 1},
                 {'page': 2, 'layout_review': 'vertical_text_order', 'ocr': {'status': 'body'}},
                 {'page': 3, 'non_body': 'backmatter_booklist'}]
        raw = '\n'.join(f'<<<PAGE {i}>>>\n这是一段需要保留出处的中文内容。' for i in (1, 2, 3))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'book.layout.jsonl'
            path.write_text('\n'.join(json.dumps(page) for page in pages), encoding='utf-8')
            segments, _ = wash.build(raw, 'T01', [], layout_path=path)
        self.assertEqual([row['source_page'] for row in segments], [1, 2])
        self.assertNotIn('source_layout_suspect', segments[0])
        self.assertTrue(segments[1]['source_layout_suspect'])
        self.assertEqual(segments[1]['source_layout_issue'], 'vertical_text_order')
        self.assertEqual(segments[1]['source_ocr_status'], 'body')


if __name__ == '__main__':
    unittest.main()
