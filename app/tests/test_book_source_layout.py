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
    def test_shared_pdf_baseline_retains_digits_with_different_font_boxes(self):
        glyphs = []
        for index, char in enumerate('生卒年：1913—2011'):
            top = 177 if char.isdigit() else 169
            glyphs.append({'text': char, 'x0': 150 + index * 6, 'x1': 156 + index * 6,
                           'top': top, 'y1': 683 - top, 'matrix': (12, 0, 0, 12, 0, 505)})
        lines = atlas._split_lines(glyphs)
        self.assertEqual([line['t'] for line in lines], ['生卒年：1913—2011'])
        self.assertEqual(atlas._kind_of('123456元', 200, 680), 'body')
        self.assertEqual(atlas._kind_of('123', 675, 680), 'header')

    def test_stranded_year_fuses_only_inside_the_same_source_block(self):
        text = '<<<PAGE 8>>>\n2021\n年5月开始。\n<<<PAGE 9>>>\n2022\n<<<PAGE 10>>>\n年终结项。'
        rows, _ = wash.build(text, 'T01', [])
        self.assertEqual([row['文本'] for row in rows], ['2021年5月开始。', '年终结项。'])

    def test_short_chapter_sequence_and_standalone_english_numbering(self):
        for headings in (['Chapter 01', 'Chapter 02', 'Chapter 03'], ['第一章', '第二章', '第三章']):
            with self.subTest(headings=headings):
                prose = '书中的这一章节有足够的中文正文供读者核对。'
                contents = '\n'.join(headings)
                text = contents + '\n' + '\n'.join(f'{h}\n{prose}' for h in headings)
                plan = structure.probe(text)
                result = structure.outline(text, plan)
                self.assertEqual([heading for heading, _, _ in result], headings)
                self.assertEqual(result[0][1], len(headings))

    def test_unsectioned_prose_is_body_but_possible_headings_keep_review(self):
        prose = '这段材料解释了图书借阅的办理办法、开放时间以及遇到问题时的咨询渠道。'
        text = '\n'.join([prose] * 10)
        self.assertTrue(structure.continuous_short_body(text))
        self.assertFalse(structure.continuous_short_body(prose + '\n第二章\n' + text))
        self.assertFalse(structure.continuous_short_body(prose + '\n开放时间\n' + text))
        prose_rows, _ = wash.build(text, 'T01', [], continuous_body=True)
        unresolved_rows, _ = wash.build(text, 'T02', [])
        self.assertEqual({row['篇'] for row in prose_rows}, {'正文'})
        self.assertFalse(tocclean.audit(prose_rows, [])['结构待复核'])
        self.assertTrue(tocclean.audit(unresolved_rows, [])['结构待复核'])

    def test_toc_does_not_create_an_appendix_before_body(self):
        text = ('目录\n2导读\n10开篇\n15后记\n20附录：个人·群体·社会——\n'
                '一生学术历程的自我思考\n导读\n正文甲。\n开篇\n正文乙。\n'
                '后记\n正文丙。\n附录: 个人·群体·社会\n—— 一生学术历程的自我思考\n正文丁。')
        plan = {'mode': 'toc', 'toc': [('导读', 2), ('开篇', 10), ('后记', 15), ('附录：个人·群体·社会——', 20)]}
        result = structure.outline(text, plan)
        self.assertEqual([heading for heading, _, _ in result], [heading for heading, _ in plan['toc']])
        self.assertEqual(result[-1][1], 12)

    def test_complete_short_verse_need_not_be_expanded(self):
        row = {'id': 'T01-01-P01', '篇序': 1, '篇': '短诗', '文本': '何处闻啼鸟，幽林入晓光。行来溪水畔，春色正悠长。'}
        report = tocclean.audit([row], [{'篇': '短诗'}])
        self.assertEqual(report['异常短篇'], [])

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
