# -*- coding: utf-8 -*-
"""营销 7 项的回归测试：不调真实模型，用假响应验证解析、证据校验、字段完整。"""
import json
import sys

import marketing as M

FAILED = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond:
        FAILED.append(msg)


def test_json():
    print('JSON 解析')
    check(M._json('{"a":1}')['a'] == 1, '纯 JSON')
    check(M._json('```json\n{"a":2}\n```')['a'] == 2, '代码块')
    check(M._json('说明\n{"a":3}\n结束')['a'] == 3, '前后有解释')
    check(M._json('{"a":"第一行\n第二行"}')['a'].startswith('第一行'), '字符串内换行容错')


def test_ev():
    print('证据校验')
    seg = {'S1': '这是一段测试原文，包含关键词。'}
    check(M._fix_ev({'seg': 'S1', 'quote': '包含关键词'}, seg) ==
          {'seg': 'S1', 'quote': '包含关键词'}, '同段逐字命中')
    check(M._fix_ev({'seg': 'S9', 'quote': '包含关键词'}, seg)['seg'] == 'S1', '段号错但引文能找回')
    check(M._fix_ev({'seg': 'S1', 'quote': '原文没有这句'}, seg) is None, '引文不存在 → 丢弃')
    check(M._fix_ev({'seg': 'S1', 'quote': ''}, seg) is None, '空引文 → 丢弃')


def test_input():
    print('输入压缩')
    text, n = M.build_input('B58', 5000)
    check(0 < n <= 5200, '长度封顶（%d 字）' % n)
    check('书名：小王子' in text, '带书名')
    check('[B58-' in text, '带段号')


def test_build_mock():
    print('假模型跑完整 7 项')
    segs = M._rows('B58')
    q = '诗人、小说家、飞行员'
    real_seg = next(r['id'] for r in segs if q in (r.get('文本') or ''))
    valid = {'seg': real_seg, 'quote': q}

    def fake(messages, **kw):
        p = messages[-1]['content']
        if '关键词' in p and '内容简介' in p:
            return {'text': json.dumps({
                'keywords': [
                    {'keyword': '飞行员', 'seg': real_seg, 'quote': q, 'reason': '核心身份'},
                    {'keyword': '假词', 'seg': real_seg, 'quote': '原文没有这句', 'reason': '应丢弃'},
                ],
                'summary': '这是一段测试简介。',
                'summary_evidence': [valid],
            }, ensure_ascii=False)}
        return {'text': json.dumps({
            'audience': [{'text': '文学读者', 'seg': real_seg, 'quote': q,
                          'reason': '测试', 'basis': '推断'}],
            'scenarios': [{'text': '读书会', 'seg': real_seg, 'quote': q,
                           'reason': '测试', 'basis': '推断'}],
            'gains': [{'text': '理解飞行员', 'seg': real_seg, 'quote': q,
                       'reason': '测试', 'basis': '原文明示'}],
            'emotions': [{'text': '感动', 'seg': real_seg, 'quote': q,
                          'reason': '测试', 'basis': '推断'}],
            'leads': [{'text': '身份卖点', 'seg': real_seg, 'quote': q,
                       'reason': '测试', 'basis': '原文明示'}],
        }, ensure_ascii=False)}

    old = M.llm.chat
    M.llm.chat = fake
    try:
        rec = M.build('B58', 5000)
    finally:
        M.llm.chat = old
    check(len(rec['items']) == 7, '7 项齐全')
    check(rec['items']['keywords']['value'][0]['keyword'] == '飞行员', '关键词保留')
    check(len(rec['items']['keywords']['value']) == 1, '假证据关键词被丢弃')
    check(rec['items']['summary']['status'] == 'needs_review', '简介待人工')
    check(len(rec['items']['audience']['value']) == 1, '目标读者保留')
    check(rec['stats']['dropped'] == 1, '丢弃计数 1')
    for k, v in rec['items'].items():
        check(v['status'] == 'needs_review', '%s 状态待复核' % v['name'])
        check(bool(v['evidence']), '%s 有证据' % v['name'])


if __name__ == '__main__':
    test_json()
    test_ev()
    test_input()
    test_build_mock()
    print('\n%s' % ('全部通过' if not FAILED else '失败 %d 项：%s' % (len(FAILED), FAILED)))
    sys.exit(1 if FAILED else 0)
