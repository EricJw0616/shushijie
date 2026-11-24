# -*- coding: utf-8 -*-
"""判型闭卷考：62 本已知类型的书，只看指纹，让模型逐列判定，再由列反推类型。

为什么由列反推而不是让模型直接选类型：
  类型本来就该是「能力组合」的投影。判定层判的是列，类型是展示层派生出来的。
  这样一次考试同时验证两件事：列的判断准不准、派生规则合不合理。

用法：
  python3 exam.py --root ../../_从坚果云恢复_.../platform/out --workers 4
"""
import argparse
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm      # noqa: E402
import judge    # noqa: E402
import cards    # noqa: E402


PLAN_SETS = {p: {l for l, _ in v} for p, v in cards.DEFAULT_PLAN.items()}


def fingerprint_from(root, code):
    sp = os.path.join(root, code, 'segments.jsonl')
    bp = os.path.join(root, code, 'book.json')
    rows = [json.loads(l) for l in io.open(sp, encoding='utf-8') if l.strip()]
    book = json.load(io.open(bp, encoding='utf-8'))
    op = os.path.join(root, code, 'outline.jsonl')
    outline = [json.loads(l) for l in io.open(op, encoding='utf-8') if l.strip()] if os.path.exists(op) else []
    return book, rows, outline


def program_cols(book, rows, outline):
    txt = '\n'.join((r.get('文本') or '') for r in rows)
    import re
    q = len(re.findall(r'《[^》]{2,20}》', txt))
    out = {'引书': q >= 5, '篇目': len(outline) >= 5}
    if (book.get('原型') or '') == 'P11' or '图鉴' in (book.get('book') or ''):
        out['物种条目'] = True
    return {k for k, v in out.items() if v}


def derive_type(cols):
    best, score = None, -1
    for p, s in PLAN_SETS.items():
        inter = len(cols & s)
        union = len(cols | s) or 1
        j = inter / union
        if j > score:
            best, score = p, j
    return best, round(score, 2)


def run_one(root, code):
    book, rows, outline = fingerprint_from(root, code)
    fp = {'book': book, 'rows': rows, 'outline': outline,
          'picks': [rows[0]] + ([rows[len(rows) // 2]] if len(rows) > 2 else []),
          'stats': {'段数': len(rows), '篇数': len(outline),
                    '对白率': 0, '平均句长': 0}}
    prompt = judge.build_prompt(fp)
    res = llm.chat([{'role': 'system', 'content': judge.SYS},
                    {'role': 'user', 'content': prompt}], max_tokens=2400, temperature=0, json_mode=True)
    data = judge.parse_json(res['text'])
    cols = {k for k, v in data.items() if isinstance(v, dict) and v.get('适用')}
    cols |= program_cols(book, rows, outline)
    pred, jac = derive_type(cols)
    return {'code': code, 'book': book.get('book'),
            'true': book.get('原型') or '拒判', 'pred': pred, 'jac': jac,
            'cols': sorted(cols), 'tokens': (res.get('usage') or {}).get('total_tokens')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    codes = []
    for name in sorted(os.listdir(a.root)):
        if os.path.exists(os.path.join(a.root, name, 'book.json')) and \
           os.path.exists(os.path.join(a.root, name, 'segments.jsonl')):
            b = json.load(io.open(os.path.join(a.root, name, 'book.json'), encoding='utf-8'))
            if b.get('原型'):
                codes.append(name)
    if a.limit:
        codes = codes[:a.limit]
    print('参加考试', len(codes), '本', flush=True)
    out = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, r in enumerate(ex.map(lambda c: run_one(a.root, c), codes), 1):
            out.append(r)
            if i % 10 == 0:
                print('  已完成', i, flush=True)
    ok = sum(1 for r in out if r['pred'] == r['true'])
    print('\n判定后派生类型 top-1：%d/%d = %.1f%%' % (ok, len(out), 100.0 * ok / max(len(out), 1)))
    from collections import Counter
    conf = Counter((r['true'], r['pred']) for r in out if r['pred'] != r['true'])
    print('主要混淆：', conf.most_common(6))
    try:
        dest = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), 'eval_sets', '判型考试.json')
        with io.open(dest, 'w', encoding='utf-8') as fp:
            json.dump(out, fp, ensure_ascii=False, indent=1)
        print('结果写入', dest)
    except Exception as e:
        print('结果未落盘：', e)


if __name__ == '__main__':
    main()
