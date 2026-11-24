import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'platform' / 'engine'))

import atlas
import structure
import tocclean
import wash


class SourceLayoutTests(unittest.TestCase):
    def test_narrow_spread_uses_its_central_gutter(self):
        chars = [{'x0': x, 'x1': x + 8} for x in range(45, 310, 8)]
        chars += [{'x0': x, 'x1': x + 8} for x in range(427, 696, 8)]
        self.assertTrue(310 < atlas._detect_gutter(chars, 743, 612) < 427)

    def test_segments_keep_their_page_and_do_not_join_columns(self):
        text = atlas.pages_to_text([
            {'page': 7, 'lines': [
                {'t': '左页的句子还没有结束', 'col': 0, 'k': 'body'},
                {'t': '右页开始另一段正文。', 'col': 1, 'k': 'body'}]},
            {'page': 8, 'lines': [{'t': '下一页另有正文。', 'col': 0, 'k': 'body'}]},
        ], mark_pages=True)
        items, _ = wash.build(text, 'T01', [])
        self.assertEqual([row['source_page'] for row in items], [7, 7, 8])
        self.assertEqual([row['文本'] for row in items], [
            '左页的句子还没有结束', '右页开始另一段正文。', '下一页另有正文。',
        ])
        legacy, _ = wash.build('没有标记的旧纯文本。', 'T02', [])
        self.assertNotIn('source_page', legacy[0])

    def test_native_bookmark_uses_real_heading_page_and_keeps_parent(self):
        text = ('<<<PAGE 4>>>\n目录\n第一节 演算\n第二节 记录\n'
                '<<<PAGE 5>>>\n项目甲\n第一节 演算\n正文甲。\n'
                '<<<PAGE 7>>>\n第二节 记录1\n正文乙。')
        pages = [{'page': 4, 'bookmarks': [{'title': '目录', 'level': 1}]},
                 {'page': 5, 'bookmarks': [{'title': '项目甲', 'level': 1},
                                           {'title': '第一节 演算', 'level': 2}]},
                 {'page': 7, 'bookmarks': [{'title': '第二节 记录', 'level': 2}]}]
        with tempfile.TemporaryDirectory() as folder:
            layout = Path(folder) / 'test.layout.jsonl'
            layout.write_text('\n'.join(json.dumps(page) for page in pages), encoding='utf-8')
            plan = structure.probe(text, layout_path=layout)
            heads = structure.outline(text, plan)
        self.assertEqual(plan['mode'], 'pdf_outline')
        self.assertEqual(heads, [('项目甲', 3, 5), ('项目甲 · 第一节 演算', 4, 5),
                                 ('项目甲 · 第二节 记录', 6, 7)])

    def test_printed_directory_is_confirmed_on_body_pages(self):
        text = ('<<<PAGE 4>>>\n目 录\n一 初识测试 / 1\n二 记录观察 制作温度计 / 3\n'
                '<<<PAGE 5>>>\n三 串联电路 / 5\n'
                '<<<PAGE 9>>>\n一\n初识测试\n有正文。\n'
                '<<<PAGE 11>>>\n二\n记录观察\n制作\n温度计\n有正文。\n'
                '<<<PAGE 13>>>\n三\n串联电路\n有正文。\n')
        plan = structure.probe(text)
        self.assertEqual(plan['pattern'], 'printed_contents')
        self.assertEqual([(name, page) for name, _, page in structure.outline(text, plan)],
                         [('一 初识测试', 9), ('二 记录观察 制作温度计', 11), ('三 串联电路', 13)])

    def test_missing_bookmark_needs_a_unique_chapter_heading(self):
        begin = '<<<PAGE 5>>>\n第1089章 章节甲\n正文甲。\n<<<PAGE 8>>>\n第1090章 章节乙\n正文乙。\n'
        tail = '<<<PAGE 15>>>\n第1091章 章节丙\n正文丙。\n'
        pages = [{'page': 5, 'bookmarks': [{'title': '第1089章 章节甲', 'level': 1}]},
                 {'page': 15, 'bookmarks': [{'title': '第1091章 章节丙', 'level': 1}]}]
        with tempfile.TemporaryDirectory() as folder:
            layout = Path(folder) / 'test.layout.jsonl'
            layout.write_text('\n'.join(json.dumps(page) for page in pages), encoding='utf-8')
            unique = structure.probe(begin + tail, layout_path=layout)
            duplicate = structure.probe(begin + '<<<PAGE 9>>>\n第1090章 章节乙\n' + tail, layout_path=layout)
        self.assertEqual(unique['titles'], ['第1089章 章节甲', '第1090章 章节乙', '第1091章 章节丙'])
        self.assertEqual(duplicate['titles'], ['第1089章 章节甲', '第1091章 章节丙'])

    def test_only_affected_page_segments_are_marked_for_layout_review(self):
        body = '这是一段用于核对标签依据的中文正文，这句话在原书中有完整出处。'
        text = (f'<<<PAGE 5>>>\n第一章 正文\n{body}\n'
                f'<<<PAGE 6>>>\n{body}\n<<<PAGE 7>>>\n读数是2×10－4。')
        with tempfile.TemporaryDirectory() as folder:
            layout = Path(folder) / 'test.layout.jsonl'
            layout.write_text('{"page": 6, "picture_dominant": true}\n', encoding='utf-8')
            rows, _ = wash.build(text, 'T01', [('第一章 正文', 0)], layout_path=layout)
        self.assertEqual([s.get('source_layout_issue') for s in rows],
                         [None, 'picture_dominant', 'formula_or_encoding'])
        report = tocclean.audit(rows, [('第一章 正文', 0, 5)])
        self.assertTrue(report['异常'])
        self.assertFalse(report['结构待复核'])
        self.assertEqual(report['图片为主正文页'], [6])
        self.assertEqual(report['公式或字符待核对段'], ['T01-01-P03'])

    def test_concentration_fails_even_if_short_chapters_have_text(self):
        segs = [{'id': f'T01-{i}-P01', '篇序': i, '篇': f'第{i}章', '文本': '甲' * length}
                for i, length in enumerate((99, 120, 4100), 1)]
        report = tocclean.audit(segs, [(r['篇'], i, i + 1) for i, r in enumerate(segs)])
        self.assertTrue(report['异常'])
        self.assertTrue(report['章节过度集中'])
        self.assertEqual(report['受影响篇序'], [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
