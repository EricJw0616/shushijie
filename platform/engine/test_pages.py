# -*- coding: utf-8 -*-
"""第 2 期页面结构的回归测试（不依赖 pytest）。

真实四本书 + 一组假页面（补真实书里没有的后记/附录/参考文献/索引/勘误）。
"""
import sys

import pages as PG

FAILED = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond:
        FAILED.append(msg)


def role(rec, key):
    return next(r for r in rec['roles'] if r['role'] == key)


def spans(rec, key):
    return [(s['from'], s['to']) for s in role(rec, key)['spans']]


def test_b58():
    print('B58 小王子')
    r = PG.build('B58')
    check(spans(r, 'copyright') == [(151, 152)], '版权页 151-152（CIP 在书末）')
    check(spans(r, 'toc') == [(3, 3)], '目录 p3')
    check(spans(r, 'preface') == [(5, 26)], '前言（导读）5-26')
    check(spans(r, 'body') == [(27, 150)], '正文 27-150')
    check(role(r, 'headings')['status'] == 'found' and len(r['headings']) >= 20, 'Chapter 标题 >=20')
    check(spans(r, 'headings'), '标题层级有页码')


def test_b60():
    print('B60 河北廉洁故事')
    r = PG.build('B60')
    check(spans(r, 'copyright') == [(3, 3)], '版权页 p3')
    check(spans(r, 'toc') == [(10, 14)], '目录 10-14')
    check(spans(r, 'preface') == [(6, 8)], '前言 6-8')
    check(spans(r, 'body') == [(16, 282)], '正文 16-282')
    check(spans(r, 'postscript') == [(283, 283)], '后记 p283')
    check(len(r['headings']) == 9, '九章标题')


def test_b59():
    print('B59 国之脊梁')
    r = PG.build('B59')
    check(spans(r, 'toc') == [(11, 12)], '目录 11-12')
    check(spans(r, 'preface') == [(9, 10)], '序言 9-10')
    check(spans(r, 'body') == [(13, 312)], '正文 13-312')
    check(len(r['headings']) == 37, '37 位人物篇')


def test_b56():
    print('B56 图鉴')
    r = PG.build('B56')
    check(spans(r, 'title_page') == [(1, 1)], '书名页 p1')
    check(spans(r, 'copyright') == [(4, 4)], '版权页 p4')
    check(spans(r, 'toc') == [(6, 40)], '目录 6-40')
    check(spans(r, 'body') == [(42, 832)], '正文 42-832')
    check(len(r['headings']) == 14, '十四章')


def _pg(n, lines):
    return {'page': n, 'lines': [{'t': t, 'k': 'body'} for t in lines]}


def test_synthetic_back():
    print('假页面：后记/附录/参考文献/索引/勘误')
    pages = [
        _pg(1, ['测试之书']),
        _pg(2, ['图书在版编目（CIP）数据', '测试之书 / 张三著', 'ISBN 978-7-000-00000-0',
                '定价 10.00 元', '开本 880×1230毫米 1/32', '字数 80 千字', '版次 2020年1月第1版']),
        _pg(3, ['目录', '第一章 开始........1', '第二章 继续........5']),
        _pg(4, ['前言', '这是一段前言文字，说明本书的写作缘由和阅读方法。']),
        _pg(5, ['第一章 开始', '正文第一段，讲清楚这本书要讨论的问题和背景。']),
    ]
    for i in range(6, 21):
        pages.append(_pg(i, ['第%d段正文' % i, '这是一段正常的正文，长度足够，用来判断正文范围。' * 2]))
    pages += [
        _pg(21, ['后记', '书写完了，说几句感谢的话。']),
        _pg(22, ['附录', '附录一 数据表']),
        _pg(23, ['参考文献', '[1] 张三. 测试之书. 2020.']),
        _pg(24, ['索引', '关键词A........1']),
        _pg(25, ['勘误表', '页码 行 原文 更正']),
    ]
    r = PG.classify_pages(pages, '测试之书', outline=None)
    check(spans(r, 'cover') == [(1, 1)], '文字封面 p1')
    check(spans(r, 'postscript') == [(21, 21)], '后记 p21')
    check(spans(r, 'appendix') == [(22, 22)], '附录 p22')
    check(spans(r, 'references') == [(23, 23)], '参考文献 p23')
    check(spans(r, 'index') == [(24, 24)], '索引 p24')
    check(spans(r, 'errata') == [(25, 25)], '勘误表 p25')
    check(spans(r, 'body') == [(5, 20)], '正文止于后记前')


def test_shapes():
    print('结构检查')
    for c in ('B56', 'B58', 'B59', 'B60'):
        r = PG.build(c)
        check(len(r['roles']) == 12, '%s 12 项结构' % c)
        names = [x['name'] for x in r['roles']]
        check(len(names) == len(set(names)), '%s 结构名不重复' % c)
        for x in r['roles']:
            check(x['status'] in ('found', 'not_found', 'needs_review', 'not_applicable'),
                  '%s/%s 状态合法' % (c, x['name']))
            if x['status'] == 'found':
                check(bool(x['spans']), '%s/%s 有区间' % (c, x['name']))


if __name__ == '__main__':
    test_b58()
    test_b60()
    test_b59()
    test_b56()
    test_synthetic_back()
    test_shapes()
    print('\n%s' % ('全部通过' if not FAILED else '失败 %d 项：%s' % (len(FAILED), FAILED)))
    sys.exit(1 if FAILED else 0)
