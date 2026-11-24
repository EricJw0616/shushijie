# -*- coding: utf-8 -*-
"""第 1 期出版信息抽取的回归测试（不依赖 pytest，直接 python3 跑）。

覆盖四本现有书：两本有版权页、两本没有；验证“有就抽、没有就 not_found、不用 PDF 页数”。
"""
import sys

import publication as PUB

LIB = {
    'B56': {'book': '中国东北药用植物彩色图志（上册）', 'author': '周繇',
            'publisher': '黑龙江科学技术出版社'},
    'B59': {'book': '国之脊梁——中国院士的科学人生百年', 'author': '项目组编',
            'publisher': '浙江少年儿童出版社'},
}

FAILED = []


def check(cond, msg):
    if cond:
        print('  ok  ', msg)
    else:
        print('  FAIL', msg)
        FAILED.append(msg)


def val(rec, key):
    return rec['items'][key]['value']


def status(rec, key):
    return rec['items'][key]['status']


def test_b58():
    print('B58 小王子（有版权页）')
    r = PUB.build('B58', LIB)
    check(val(r, 'book_title') == '小王子', '书名')
    names = [p['name'] for p in val(r, 'author')['people']]
    check('圣埃克苏佩里（Exupery,S.）' in names, '作者含圣埃克苏佩里')
    check(status(r, 'translators') == 'found' and val(r, 'translators')[0]['name'] == '李继宏', '译者李继宏')
    check(val(r, 'editor_in_charge') == '玮丽斯', '责任编辑玮丽斯')
    check(val(r, 'publication_date') == '2013年1月', '出版时间 2013年1月')
    check(val(r, 'edition') == '第1版', '版次第1版')
    check(val(r, 'impression') == '第49次印刷', '印次第49次')
    types = {x['type']: x['value'] for x in val(r, 'book_format')}
    check(types.get('开数') == '1/32', '开数 1/32')
    check(types.get('成品尺寸') == '880×1230毫米', '成品尺寸 880×1230毫米')
    check(val(r, 'word_count')['normalized'] == 86000, '字数 86千字 → 86000')
    check(val(r, 'price')['amount'] == 32.0, '定价 32.00')
    check(val(r, 'isbn')[0]['valid'] is True, 'ISBN 校验通过')
    check(val(r, 'classification')[0]['code'] == 'I565.88', '分类 I565.88')
    check(status(r, 'pages') == 'not_found', '页数：版权页没印，标 not_found')
    check(status(r, 'binding') == 'not_found', '装帧：没印，标 not_found')
    check(status(r, 'series') == 'not_found', '丛书：没印，标 not_found')


def test_b60():
    print('B60 河北廉洁故事（有版权页）')
    r = PUB.build('B60', LIB)
    check(val(r, 'book_title') == '河北廉洁故事', '书名')
    check(len(val(r, 'author')['people']) == 4, '作者 4 人（主编2+副主编2）')
    check(val(r, 'editor_in_charge') == '郭忠', '责任编辑郭忠')
    check('2024TN7626' in val(r, 'cip_number')['number'], 'CIP 号 2024TN7626')
    check(val(r, 'publication_date') == '2024年10月', '出版时间 2024年10月')
    check(val(r, 'word_count')['normalized'] == 250000, '字数 250 000')
    check(val(r, 'price')['amount'] == 60.0, '定价 60.00')
    check(val(r, 'classification')[0]['code'] == 'D630.9-49', '分类 D630.9-49')
    check(status(r, 'pages') == 'not_found', '页数 not_found（不用 PDF 285 页）')
    check(status(r, 'translators') == 'not_found', '译者 not_found')


def test_b56():
    print('B56 图鉴（无版权页，靠书目库+作者简介）')
    r = PUB.build('B56', LIB)
    check(val(r, 'book_title') == '中国东北药用植物彩色图志（上册）', '书名来自书目库')
    check(val(r, 'publisher') == '黑龙江科学技术出版社', '出版社来自书目库')
    check(status(r, 'author_bio') == 'found' and '周繇' in val(r, 'author_bio'), '作者简介抽到')
    check(status(r, 'classification') == 'needs_review', '规则分类需人工确认')
    check(status(r, 'isbn') == 'not_found', '无版权页 → 书号 not_found')
    check(status(r, 'pages') == 'not_found', '无版权页 → 页数 not_found')


def test_b59():
    print('B59 纪事（无版权页，封面署名）')
    r = PUB.build('B59', LIB)
    names = [p['name'] for p in val(r, 'author')['people']]
    check('胡海岩' in names and '毛晓青' in names, '作者：胡海岩/毛晓青')
    check(val(r, 'publisher') == '浙江少年儿童出版社', '出版社来自书目库')
    check(status(r, 'classification') == 'needs_review', '规则分类需人工确认')
    check(status(r, 'cip_number') == 'not_found', 'CIP 号 not_found')
    check(status(r, 'author_bio') == 'not_found', '作者简介 not_found')


def test_shapes():
    print('结构检查')
    for code in ('B56', 'B58', 'B59', 'B60'):
        r = PUB.build(code, LIB)
        seg = {x['id']: x['文本'] for x in PUB._rows(code)}
        for it in r['items'].values():
            for ev in it.get('evidence') or []:
                if ev.get('quote'):
                    check(ev['quote'] in seg.get(ev['seg'], ''),
                          '%s/%s 证据逐字存在' % (code, it['name']))
        check(len(r['items']) == 19, '%s 共 19 项' % code)
        check(set(r['stats']) >= {'found', 'not_found'}, '%s 有统计' % code)
        for it in r['items'].values():
            check(it['status'] in ('found', 'not_found', 'needs_review', 'not_applicable'),
                  '%s/%s 状态合法' % (code, it['name']))
            if it['status'] == 'found':
                check(bool(it['evidence']) or it['method'] == 'import',
                      '%s/%s 有值必须有证据或为导入' % (code, it['name']))
            if it['status'] == 'needs_review':
                check(bool(it['note']), '%s/%s 待复核要有原因' % (code, it['name']))


if __name__ == '__main__':
    test_b58()
    test_b60()
    test_b56()
    test_b59()
    test_shapes()
    print('\n%s' % ('全部通过' if not FAILED else '失败 %d 项：%s' % (len(FAILED), FAILED)))
    sys.exit(1 if FAILED else 0)
