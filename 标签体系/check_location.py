#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""47 项交付台账的“原文定位”自查。

口径（2026-11-13 与用户确认）：
  1. 除理解/生成类外，每一条标注都必须能定位到原文：
     - 正文类：段 id + 逐字引文（quote 必须是该段文本的子串）
     - 页面结构：PDF 页码 + 该页原文（quote 必须是该页文本的子串）
  2. 理解/生成类（事实数值、技能规则、核心概念、概念原理、章节摘要、营销 7 项）
     也尽量给段+引文；同时必须给“理由/依据”，不能只有结论。
  3. 没有定位、引文对不上、页码对不上、理由为空，都算失败；退出码 1。

用法：
    python3 标签体系/check_location.py
输出：
    终端统计 + 标签体系/定位自查报告.md + 定位自查报告.json
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT = os.path.join(ROOT, 'platform', 'out')
ANN = os.path.join(OUT, 'delivery', 'annotations.jsonl')
RAW = os.path.join(ROOT, '书库分类', 'raw')

PAGE_GROUP = '出版物结构'
KIND_NAMES = {'extract': '摘录/正文', 'page': '页面结构', 'understanding': '理解 4 项',
              'summary': '章节摘要', 'marketing': '营销 7 项'}
UNDERSTANDING = {'事实与数值', '技能与规则', '核心概念', '概念与原理'}
SUMMARY = '章节核心意思'
REASON_MARK = {
    '事实与数值': '类别',
    '技能与规则': '条件',
    '核心概念': '为什么核心',
    '概念与原理': '解释',
}


def norm(s):
    """只归一空白；标点、异体字一律不动，避免把“对不上”洗成“对得上”。"""
    return re.sub(r'[\s\u3000\xa0]+', '', s or '')


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as fp:
        for line in fp:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def seg_index(code):
    return {r['id']: (r.get('文本') or '') for r in read_jsonl(os.path.join(OUT, code, 'segments.jsonl')) if r.get('id')}


_PAGE_CACHE = {}


def page_texts(book):
    if book in _PAGE_CACHE:
        return _PAGE_CACHE[book]
    path = os.path.join(RAW, book + '.layout.jsonl')
    pages = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    pg = json.loads(line)
                except Exception:
                    continue
                txt = ' '.join((ln.get('t') or '') for ln in (pg.get('lines') or [])
                               if (ln.get('t') or '').strip())
                pages.append(txt)
    _PAGE_CACHE[book] = pages
    return pages


_OCR_CACHE = {}


def ocr_pages(code):
    if code in _OCR_CACHE:
        return _OCR_CACHE[code]
    path = os.path.join(OUT, code, 'ocr', 'pages.jsonl')
    rows = read_jsonl(path)
    _OCR_CACHE[code] = {r.get('page'): (r.get('text') or '') for r in rows}
    return _OCR_CACHE[code]


def kind_of(row):
    if row.get('group') == PAGE_GROUP:
        return 'page'
    if row.get('name') in UNDERSTANDING:
        return 'understanding'
    if row.get('name') == SUMMARY:
        return 'summary'
    if row.get('pack_code') == 'P03':
        return 'marketing'
    return 'extract'


def check_row(row, segs, pages):
    """返回 (ok, errors, warnings)。"""
    err, warn = [], []
    evs = row.get('evidence') or []
    kind = kind_of(row)
    name = row.get('name') or ''
    code = row.get('book_code') or ''

    if kind == 'page':
        good = 0
        for e in evs:
            pg = e.get('page')
            q = e.get('quote') or ''
            if not isinstance(pg, int):
                err.append('页面证据缺页码')
                continue
            if pages and not (1 <= pg <= len(pages)):
                err.append('页码越界 p%s' % pg)
                continue
            if not q:
                err.append('p%s 的页面引文为空' % pg)
                continue
            if pages and norm(q) not in norm(pages[pg - 1]):
                err.append('p%s 的页面引文对不上' % pg)
                continue
            good += 1
        if not good:
            err.append('没有一条可校验的页面证据')
        spans = (row.get('value') or {}).get('spans') if isinstance(row.get('value'), dict) else None
        if spans:
            for sp in spans:
                if not (isinstance(sp.get('from'), int) and isinstance(sp.get('to'), int)):
                    err.append('页码区间不是整数')
        return not err, err, warn

    # 正文类：至少一条 seg+quote，或 OCR 的 page+parts 能校验
    good = 0
    seg_evs = [e for e in evs if e.get('seg')]
    ocr_evs = [e for e in evs if e.get('source') == 'ocr' and e.get('page')]
    if ocr_evs and not seg_evs:
        pages = ocr_pages(code)
        for e in ocr_evs:
            pno = e.get('page')
            t = pages.get(pno)
            parts = e.get('parts') or [e.get('quote') or '']
            if not t:
                err.append('OCR 页不存在：p%s' % pno)
                continue
            if not all(p and norm(p) in norm(t) for p in parts):
                err.append('OCR 引文对不上：p%s' % pno)
                continue
            good += 1
            warn.append('OCR 页级定位（p%s，已与书目库交叉校验）' % pno)
    else:
        for e in evs:
            sid = e.get('seg') or ''
            q = e.get('quote') or ''
            if not sid and not q:
                continue
            if not sid:
                err.append('有引文但没有段 id')
                continue
            t = segs.get(sid)
            if t is None:
                err.append('段 id 不存在：%s' % sid)
                continue
            if not q:
                err.append('%s 没有引文' % sid)
                continue
            if norm(q) not in norm(t):
                err.append('%s 的引文对不上' % sid)
                continue
            good += 1
    if not good:
        err.append('没有可校验的段+引文')

    note = (row.get('note') or '').strip()
    if kind == 'understanding':
        mark = REASON_MARK.get(name)
        if not note:
            err.append('理解类缺理由')
        elif mark and mark not in note:
            err.append('理解类理由缺字段：%s' % mark)
    elif kind == 'summary':
        if not note:
            err.append('章节摘要缺理由')
        elif '依据' not in note and '段' not in note:
            warn.append('章节摘要只写“篇”，未写依据段范围/生成理由')
    elif kind == 'marketing':
        if not note:
            err.append('营销类缺理由/依据')

    if not str(row.get('value') or '').strip():
        err.append('有值行但值为空')

    if (kind == 'extract' and row.get('name') in ('书名', '作者', '出版社')
            and isinstance(row.get('value'), str)):
        q0 = next((e.get('quote') for e in evs if isinstance(e, dict) and e.get('seg')), '')
        if q0 and q0 != row['value'] and q0 in row['value']:
            warn.append('值只有一部分在原文（段级·部分）')

    return not err, err, warn


def main():
    rows = read_jsonl(ANN)
    if not rows:
        print('找不到 %s，请先跑 delivery.py' % ANN)
        return 2

    segs = {}
    for code in {r.get('book_code') for r in rows}:
        segs[code] = seg_index(code)

    stats = Counter()
    failures = []
    warnings = []
    for r in rows:
        code = r.get('book_code') or ''
        kind = kind_of(r)
        stats[kind] += 1
        ok, err, warn = check_row(r, segs.get(code) or {}, page_texts(r.get('book') or ''))
        stats[kind + '_ok' if ok else kind + '_bad'] += 1
        if not ok:
            failures.append({'book': code, 'name': r.get('name'), 'kind': kind,
                             'value': r.get('value'), 'errors': err})
        for w in warn:
            warnings.append({'book': code, 'name': r.get('name'), 'kind': kind, 'warning': w})

    total = len(rows)
    ok_total = total - len(failures)
    print('交付长表 %d 行；可定位/可校验 %d 行；不通过 %d 行；提醒 %d 条'
          % (total, ok_total, len(failures), len(warnings)))
    for k in ('extract', 'page', 'understanding', 'summary', 'marketing'):
        if stats[k]:
            print('  %-8s %4d 行，通过 %4d，不通过 %3d'
                  % (KIND_NAMES[k], stats[k], stats[k + '_ok'], stats[k + '_bad']))
    if failures:
        print('\n不通过（前 20 条）：')
        for f in failures[:20]:
            print('  - %s %s：%s' % (f['book'], f['name'], '；'.join(f['errors'][:2])))
    if warnings:
        print('\n提醒（前 10 条）：')
        for w in warnings[:10]:
            print('  - %s %s：%s' % (w['book'], w['name'], w['warning']))

    report = {
        'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        'total': total, 'ok': ok_total, 'failed': len(failures), 'warnings': len(warnings),
        'by_kind': {k: {'rows': stats[k], 'ok': stats[k + '_ok'], 'bad': stats[k + '_bad']}
                    for k in ('extract', 'page', 'understanding', 'summary', 'marketing') if stats[k]},
        'failures': failures, 'warning_items': warnings,
    }
    with open(os.path.join(BASE, '定位自查报告.json'), 'w', encoding='utf-8') as fp:
        json.dump(report, fp, ensure_ascii=False, indent=1)

    lines = ['# 47 项交付：原文定位自查', '',
             '> 生成时间：%s' % report['generated_at'], '',
             '| 类型 | 行数 | 通过 | 不通过 |', '|---|---:|---:|---:|']
    for k, v in report['by_kind'].items():
        lines.append('| %s | %d | %d | %d |' % (KIND_NAMES[k], v['rows'], v['ok'], v['bad']))
    lines += ['', '合计 %d 行，通过 %d，不通过 %d，提醒 %d。'
              % (total, ok_total, len(failures), len(warnings)), '']
    if failures:
        lines += ['## 不通过', '', '| 书 | 标签 | 值 | 原因 |', '|---|---|---|---|']
        for f in failures:
            val = f['value']
            if isinstance(val, (dict, list)):
                val = json.dumps(val, ensure_ascii=False)
            lines.append('| %s | %s | %s | %s |' % (f['book'], f['name'],
                                                    (val or '')[:60].replace('|', '／'),
                                                    '；'.join(f['errors']).replace('|', '／')))
        lines.append('')
    if warnings:
        lines += ['## 提醒', '', '| 书 | 标签 | 提醒 |', '|---|---|---|']
        for w in warnings:
            lines.append('| %s | %s | %s |' % (w['book'], w['name'], w['warning']))
        lines.append('')
    with open(os.path.join(BASE, '定位自查报告.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(lines))

    print('\n报告：标签体系/定位自查报告.md')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
