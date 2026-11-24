# -*- coding: utf-8 -*-
"""OCR 版权页 → 出版档案字段。

只做“识别 + 解析 + 校验”，不做扩写：
- 在 OCR 页里找“图书在版编目 / ISBN / 定价”；
- 用现有 CIP 解析器提取字段；
- 每个字段带页码、引文、OCR 来源；
- 找不到就返回空，并说明“OCR 未发现版权页”。
"""
import json
import os
import re

import cip

MAP = {
    '书名': 'book_title', '著者': 'author', '出版社': 'publisher',
    '出版年月': 'publication_date', 'ISBN': 'isbn', 'CIP核字号': 'cip_number',
    '中图法': 'classification', '开本': 'book_format', '字数': 'word_count',
    '定价': 'price', '版次': 'edition', '印次': 'impression',
}


def _quote_for(text, value):
    if not value:
        return ''
    for line in re.split(r'[\n]', text):
        if value in line:
            return line.strip()[:300]
    return str(value)[:300]


def extract(pages):
    """pages: [{'page': int, 'text': str, ...}]"""
    best = None
    for p in pages or []:
        t = (p.get('text') or '').strip()
        if not t:
            continue
        if '图书在版编目' not in t and not ('ISBN' in t.upper() and ('定价' in t or '元' in t)):
            continue
        got = cip.parse(t)
        if not got.get('_found'):
            continue
        score = sum(1 for k in got if not k.startswith('_') and got.get(k))
        if not best or score > best[0]:
            best = (score, p, got, t)
    if not best:
        return {'found': False, 'page': None, 'fields': {},
                'note': 'OCR 未发现可读版权页（CIP）'}

    _, p, got, t = best
    fields = {}
    for k, key in MAP.items():
        v = got.get(k)
        if v:
            fields[key] = {'value': v, 'page': p.get('page'),
                           'quote': _quote_for(t, str(v)), 'method': 'ocr'}

    # 责任编辑：CIP 解析器不管这一项，单独正则
    m = re.search(r'责任编辑[：:\s]*([^\s，,。；;]{2,12})', t)
    if m:
        v = m.group(1).strip()
        if v:
            fields['editor_in_charge'] = {'value': v, 'page': p.get('page'),
                                          'quote': _quote_for(t, v), 'method': 'ocr'}

    # CIP 核字号：OCR 常见“核字（2012)第260176号”
    if 'cip_number' not in fields:
        m = re.search(r'核\s*字\s*[（(]?\s*(\d{4})\s*[）)]?\s*第?\s*([0-9A-Za-z]+)\s*号?', t)
        if m:
            v = '(%s)第%s号' % (m.group(1), m.group(2))
            fields['cip_number'] = {'value': v, 'page': p.get('page'),
                                    'quote': _quote_for(t, m.group(0)), 'method': 'ocr'}

    # 字数：CIP 页常只写“86千字 / 250 000 / 99千字”
    if 'word_count' not in fields:
        m = re.search(r'(\d+(?:\.\d+)?)\s*(千字|万字)', t)
        if m:
            num = float(m.group(1)) * (1000 if m.group(2) == '千字' else 10000)
            fields['word_count'] = {'value': str(int(num)), 'page': p.get('page'),
                                    'quote': _quote_for(t, m.group(0)), 'method': 'ocr'}
        else:
            m = re.search(r'(?<![\d.])(\d{2,3})\s+(\d{3})(?![\d.])', t)
            if m:
                v = str(int(m.group(1)) * 1000 + int(m.group(2)))
                fields['word_count'] = {'value': v, 'page': p.get('page'),
                                        'quote': _quote_for(t, m.group(0)), 'method': 'ocr'}

    # 开本：OCR 常见“880×1230毫米 1/32”“787毫米×1092毫米1/16”
    if 'book_format' not in fields:
        m = re.search(r'(\d{2,4}\s*(?:毫米)?\s*[×xX]\s*\d{2,4}\s*毫米)\s*(\d+\s*/\s*\d+)', t)
        if m:
            v = '%s %s' % (re.sub(r'\s+', '', m.group(1)), re.sub(r'\s+', '', m.group(2)))
            fields['book_format'] = {'value': v, 'page': p.get('page'),
                                     'quote': _quote_for(t, m.group(0)), 'method': 'ocr'}

    # 定价兜底：OCR 常把“定价”两个字漏掉，只剩“32.00元”
    if 'price' not in fields:
        m = re.search(r'(?<![\d.])(\d{1,3}\.\d{2})\s*元', t)
        if m:
            fields['price'] = {'value': m.group(1), 'page': p.get('page'),
                               'quote': _quote_for(t, m.group(1)), 'method': 'ocr'}
    return {'found': True, 'page': p.get('page'), 'fields': fields,
            'note': 'OCR 版权页识别', 'engine': p.get('engine'),
            'engine_version': p.get('engine_version')}


def write(pages, outdir):
    rec = extract(pages)
    os.makedirs(outdir, exist_ok=True)
    p = os.path.join(outdir, 'publication.json')
    with open(p, 'w', encoding='utf-8') as fp:
        json.dump(rec, fp, ensure_ascii=False, indent=1)
    return rec
