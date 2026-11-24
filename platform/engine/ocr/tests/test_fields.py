# -*- coding: utf-8 -*-
"""OCR 字段抽取/路由的单元测试（不加载模型，CI 可跑）。"""
import unittest

from ocr.fields import extract, norm_match
from ocr.router import plan
from ocr.types import OCRLine


def line(text, score, x0, y0, x1, y1, page=5):
    return OCRLine(text=text, score=score, box=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                   bbox=[x0, y0, x1, y1], page=page)


class FieldTest(unittest.TestCase):
    def setUp(self):
        self.lines = [
            line('国之脊梁', 0.94, 1634, 231, 1915, 1205),
            line('中国院士的科学人生百年', 0.99, 1528, 973, 1623, 2122),
            line('中国科学院学部科学人生·百年『项目组编著', 0.97, 1428, 1138, 1479, 2123),
            line('浙江少年儿童出版社', 0.99, 1426, 2652, 1799, 2698),
        ]
        self.lib = {'book': '国之脊梁——中国院士的科学人生百年',
                    'publisher': '浙江少年儿童出版社'}

    def test_title_a(self):
        out = extract(self.lines, 5, self.lib, 'rapidocr', '1.4.4')
        t = out['book_title']
        self.assertEqual(t['value'], '国之脊梁——中国院士的科学人生百年')
        self.assertEqual(t['status'], 'A')
        ev = t['evidence'][0]
        self.assertEqual(ev['source'], 'ocr')
        self.assertEqual(ev['page'], 5)
        self.assertEqual(ev['parts'], ['国之脊梁', '中国院士的科学人生百年'])
        self.assertEqual(ev['cross_check'], 'library')

    def test_publisher_prefers_library(self):
        out = extract(self.lines, 5, self.lib, 'rapidocr', '1.4.4')
        self.assertEqual(out['publisher']['value'], '浙江少年儿童出版社')
        self.assertEqual(out['publisher']['status'], 'A')

    def test_match_ignores_dash(self):
        self.assertEqual(norm_match('国之脊梁——中国院士的科学人生百年'),
                         norm_match('国之脊梁-中国院士的科学人生百年'))

    def test_no_title_is_c(self):
        out = extract([line('浙江少年儿童出版社', 0.99, 0, 0, 100, 20)], 5,
                      self.lib, 'rapidocr', '1.4.4')
        self.assertEqual(out['book_title']['status'], 'C')


class RouterTest(unittest.TestCase):
    def test_empty_goes_ocr(self):
        p = plan([1, 2], {1: '', 2: '正文' * 20})
        self.assertEqual([x['action'] for x in p], ['ocr', 'native'])

    def test_force_goes_ocr(self):
        p = plan([5], {5: '正文' * 20}, force=[5])
        self.assertEqual(p[0]['action'], 'ocr')

    def test_bad_goes_ocr(self):
        p = plan([3], {3: '正\ufffd\ufffd文' * 20})
        self.assertEqual(p[0]['action'], 'ocr')


if __name__ == '__main__':
    unittest.main()
