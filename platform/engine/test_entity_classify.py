# -*- coding: utf-8 -*-
"""分类器回归：通用规则，不按书写死名字。"""
import unittest
from entity_classify import classify

CASES = [
    ('上海市人民检察分院', '对我的所谓起诉书', 'org'),
    ('上海市人民检察院', '', 'org'),
    ('上海', '', 'city'),
    ('中国', '', 'country'),
    ('江苏', '', 'province'),
    ('华东', '', 'region'),
    ('青浦县', '', 'district'),
    ('巨鹿路', '', 'landmark'),
    ('崇明岛', '', 'nature'),
    ('北京猿人', '', 'fossil'),
    ('五代', '', 'dynasty'),
    ('诺贝尔奖', '', 'award'),
    ('文化大革命', '', 'event'),
    ('腊鸭', '', 'object'),
    ('差序格局', '', 'concept'),
    ('孔子', '孔子说：', 'person'),
    ('保卫科', '', 'org'),
    ('水下考古部门', '', 'org'),
    ('上柴厂', '', 'org'),
    ('二中', '', 'org'),
    ('江村', '', 'district'),
    ('通榆', '', 'district'),
    ('七台河', '', 'city'),
    ('戒石坊', '', 'landmark'),
    ('文化广场', '', 'landmark'),
    ('黄门', '', 'concept'),
    ('天国', '', 'concept'),
    ('徐家汇', '', 'landmark'),
    ('核试验场区', '', 'landmark'),
]

class T(unittest.TestCase):
    def test_cases(self):
        for name, ctx, want in CASES:
            got, conf, why = classify(name, ctx)
            self.assertEqual(got, want, '%s -> %s (%s), want %s' % (name, got, why, want))

    def test_hints(self):
        self.assertEqual(classify('红松', '', hint='plant')[0], 'plant')
        self.assertEqual(classify('毛茛科', '', hint='plant')[0], 'taxon')
        self.assertEqual(classify('物理科', '', hint='taxon')[0], 'org')

if __name__ == '__main__':
    unittest.main()
