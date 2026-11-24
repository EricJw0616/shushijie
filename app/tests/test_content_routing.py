import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'platform/engine'))

import cards
import entities
import export
import library
import taglib
import tags
import understanding


def paragraph(number, body, **source):
    return {'id': f'BK-01-P{number:02}', '篇序': 1, '篇': '第一章 材料', '段': number,
            '书': '实作练习', '文本': body, '字数': len(body), **source}


class ContentRoutingTests(unittest.TestCase):
    def test_book_type_does_not_gate_definitions_or_enable_drama(self):
        segs = [
            paragraph(1, '人脸识别是基于脸部特征识别身份的一种技术。[原理分析]'),
            paragraph(2, '请阅读本章的操作实例。[阅读提示]'),
        ]
        options = {'enabled': ('定义', '篇目', '曲牌科介')}
        book = {'book': '实作练习', 'code': 'BK'}
        for genre in (None, 'P2', 'P5', 'P11'):
            with self.subTest(genre=genre):
                rows, status, _ = cards.extract_by_content(book, segs, genre, **options)
                self.assertEqual(status['定义']['count'], 1)
                self.assertEqual(status['曲牌科介']['status'], 'not_found')
                self.assertEqual(status['篇目']['count'], 1)
                self.assertEqual(status['凡式']['status'], 'disabled')
                definition = next(row for row in rows if row['抽取项'] == '定义')
                self.assertEqual(definition['字段']['词条'], '人脸识别')
                self.assertEqual(definition['锚点'], segs[0]['id'])
                self.assertIn(definition['原文'], segs[0]['文本'])

    def test_picture_based_source_and_wrong_chapter_do_not_publish_labels(self):
        book = {'book': '实作练习', 'code': 'BK'}
        bad = paragraph(1, '近视是一种视觉现象。', source_layout_suspect=True)
        uncertain = paragraph(1, '近视是一种视觉现象。', source_structure_suspect=True)
        rows, status, _ = cards.extract_by_content(book, [bad], enabled=['定义'])
        self.assertEqual(rows, [])
        self.assertEqual(status['定义']['status'], 'needs_review')
        _, status, _ = cards.extract_by_content(book, [uncertain], enabled=['篇目'])
        self.assertEqual(status['篇目']['status'], 'needs_review')
        self.assertEqual(status['篇目']['count'], 0)

    def test_rule_and_drama_use_content_signals(self):
        book = {'book': '实作练习', 'code': 'BK'}
        segs = [
            paragraph(1, '小明：今天我会走过来。\n[他走上台，看着对方]'),
            paragraph(2, '版权所有。未经许可，禁止转载并不得使用本书内容。'),
        ]
        _, status, _ = cards.extract_by_content(book, segs, enabled=['曲牌科介', '规则'])
        self.assertEqual(status['曲牌科介']['count'], 1)
        self.assertEqual(status['规则']['count'], 0)

    def test_atlas_anchor_identifies_the_start_of_the_full_entry(self):
        rows = [{'id': 'X', '锚点': 'BK-01-P01', '原文': '甲乙丙丁戊己', '核对路': 'atlas'}]
        segs = [paragraph(1, '甲乙丙。'), paragraph(2, '甲乙丙'), paragraph(3, '丁戊己')]
        verified, dropped, _ = cards.verify(rows, segs, strict_anchors=True)
        self.assertEqual(dropped, 0)
        self.assertEqual(verified[0]['锚点'], 'BK-01-P02')

    def test_reference_uses_real_evidence_instead_of_first_recorded_anchor(self):
        segs = [paragraph(1, '一些介绍。', source_role='copyright'),
                paragraph(2, '有关背景可参看《自然读本》。')]
        with patch.object(tags, 'segments', return_value=segs):
            label = tags.cited_books([{'词': '《自然读本》', '类': '书名篇名', '频次': 2,
                                      '分布篇数': 1, '首现': segs[0]['id']}])[0]
        self.assertEqual(label['锚点'], segs[1]['id'])
        self.assertIn(label['原文'], segs[1]['文本'])

    def test_understanding_only_publishes_current_quotes_as_candidates(self):
        segs = [paragraph(1, '两种材料有不同的性质。', source_page=8)]
        item = {'议题': '选材原则', 'quote': '两种材料有不同的性质。', 'seg': segs[0]['id']}
        bad = dict(item, 议题='无出处', quote='完全不同的内容')
        data = {'themes': [item, bad]}
        with patch.object(taglib, 'jf', return_value=data):
            evidence = taglib._evidence_by_anchor(segs)
            actual = taglib._understanding_topics('BK', evidence, set())
            self.assertEqual([t['标签'] for t in actual], ['选材原则'])
            self.assertEqual(actual[0]['状态'], '待核对')
            data['processing'] = {'themes': {'status': 'stale'}}
            self.assertEqual(taglib._understanding_topics('BK', evidence, set()), [])

    def test_old_profiles_are_combined_when_global_choices_are_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            config = pathlib.Path(folder) / 'capabilities.json'
            plan = {proto: [] for proto in cards.DEFAULT_PLAN}
            plan['P8'] = ['定义']
            config.write_text(json.dumps({'plan': plan}), encoding='utf8')
            self.assertEqual(cards.enabled_labels(config), {'定义'})
            config.write_text(json.dumps({'plan': plan, 'content_labels': []}), encoding='utf8')
            self.assertEqual(cards.enabled_labels(config), set())

    def test_confirmed_card_type_is_not_inferred_from_book_code(self):
        self.assertEqual(export.confirmed_cards({'code': 'B01', 'book': '青少年人工智能探秘'}), {})

    def test_definition_omits_column_titles_and_recognizes_named_term(self):
        segs = [paragraph(1, '科学链接黄金思维圈黄金思维圈是一种高效的思考模型。'),
                paragraph(2, '前方所得的图形，即物体的正面投影，称为主视图，通常反映外形。')]
        rows, _, _ = cards.extract_by_content({'book': '实作练习', 'code': 'BK'}, segs,
                                              enabled=['定义', '释义'])
        self.assertEqual([r['字段']['词条'] for r in rows], ['黄金思维圈', '主视图'])
        self.assertTrue(rows[0]['原文'].startswith('黄金思维圈是'))

    def test_reading_selections_use_numbered_original_and_report_progress(self):
        seg = paragraph(1, '人物说：“先查一遍原书，再说这话有没有出处。” 后文还有几句需要找对原书。')
        response = {'text': ('SENTENCE: 1\nQUOTE: 将理由改写成新的引文。\n'
                             'THEME: 追查出处\nWHY: 这句话直接说明了核对的方法。')}
        expected = '人物说：“先查一遍原书，再说这话有没有出处。”'
        with tempfile.TemporaryDirectory() as folder, patch.object(understanding, 'OUT', folder), \
                patch.object(understanding, 'rows_of', return_value=[seg]), \
                patch.object(understanding.llm, 'chat', return_value=response):
            for fn in (understanding.quotes, understanding.themes):
                progress = []
                rows, report = fn('BK', on_progress=lambda count, total: progress.append((count, total)))
                self.assertEqual((rows[0]['seg'], rows[0]['quote']), (seg['id'], expected))
                self.assertEqual(report.get('blocked', 0), 0)
                self.assertEqual(progress, [(1, 1)])

    def test_unknown_sentence_number_does_not_replace_previous_quotes(self):
        seg = paragraph(1, '原稿中还保留着一条已经人工核对过的句子。')
        previous = [{'seg': seg['id'], 'quote': seg['文本']}]
        with tempfile.TemporaryDirectory() as folder, patch.object(understanding, 'OUT', folder), \
                patch.object(understanding, 'rows_of', return_value=[seg]), \
                patch.object(understanding.llm, 'chat', return_value={'text': 'SENTENCE: 999'}):
            understanding._save('BK', 'quotes', previous, {'kept': 1})
            rows, report = understanding.quotes('BK')
            self.assertEqual(rows, previous)
            self.assertEqual(report['blocked'], 1)
            self.assertEqual(report['dropped'], 1)

    def test_title_subject_needs_person_evidence_and_keeps_same_name_elsewhere(self):
        rows = [
            paragraph(1, '陶澍Ⅰ.①…Ⅲ.①(1779-1839)—人物研究', source_kind='front_matter'),
            paragraph(2, '陶澍于道光元年三月入晋赴任。'),
            paragraph(3, '陶澍年五十一时参与此事。'),
            paragraph(4, '村中有一座取名陶澍的纪念馆。'),
            paragraph(5, '陶澍生于此地。', source_issue='layout'),
        ]
        previous = [{'name': '陶澍', 'cat': 'concept', 'seg': rows[2]['id']},
                    {'name': '陶澍', 'cat': 'other', 'seg': rows[3]['id']},
                    {'name': '京师', 'cat': 'city', 'seg': rows[1]['id']}]
        evidence = entities.explicit_name_rows('陶澍在江南', rows)
        self.assertEqual({row['seg'] for row in evidence}, {rows[1]['id'], rows[2]['id']})
        self.assertEqual({row['cat'] for row in evidence}, {'person'})
        merged = entities.merge_explicit_names(previous, evidence)
        self.assertNotIn(previous[0], merged)
        self.assertIn(previous[1], merged)
        self.assertIn(previous[2], merged)
        reviewed = dict(previous[0], src='人工复核')
        self.assertIn(reviewed, entities.merge_explicit_names([reviewed], evidence))
        self.assertFalse(any(row.get('name_evidence') and row['seg'] == reviewed['seg']
                             for row in entities.merge_explicit_names([reviewed], evidence)))
        self.assertEqual(entities.explicit_name_rows('陶澍在江南', rows[1:]), [])

    def test_cited_book_has_original_quote_when_pdf_title_marks_are_displaced(self):
        original = '兹根据清宣宗实录所载陶澍任内历年灾荒《》并列出。另见《黄河水利志》。'
        rows = [paragraph(1, original), paragraph(2, '清宣宗实录具有史料价值。'),
                paragraph(3, '参见《排除的资料》。', source_kind='toc')]
        evidence = entities.explicit_name_rows('实作练习', rows)
        self.assertEqual({it['name'] for it in evidence}, {'清宣宗实录', '黄河水利志'})
        self.assertTrue(all(it['seg'] == rows[0]['id'] and it['quote'] in original for it in evidence))
        self.assertEqual(next(it['quote'] for it in evidence if it['name'] == '清宣宗实录'),
                         '根据清宣宗实录所载')
        with patch.object(tags, 'segments', return_value=rows):
            self.assertIn('清宣宗实录', [t['标签'] for t in tags.cited_books(library.names(rows))])
        candidates = cards._quote_candidates(rows, 'BK')
        self.assertEqual([c['字段']['书名'] for c in candidates], ['《清宣宗实录》'])
        self.assertIn(candidates[0]['原文'], original)

    def test_title_words_can_remain_other_entities_in_distinct_original_context(self):
        rows = [paragraph(1, '《黄河水利志》记载，黄河当年水位上涨。其次参看《流域漕运计划》。')]
        block = 'SEG: ' + rows[0]['id'] + '\nPLACE: 黄河 | 流域'
        found = entities._accept(rows, block, set())
        self.assertEqual([row['name'] for row in found], ['黄河'])


if __name__ == '__main__':
    unittest.main()
