# -*- coding: utf-8 -*-
"""评测集跑分：在固定的人工标注样本上，量抽取器的精度与召回。

为什么要有：改规则、换模型之后，没有这张表就说不清是变好还是变坏。

评测集格式（eval_sets/<列>.jsonl）：每行
  {"code","book","原文","label":"yes|no","why"}

用法：
  python3 eval.py 情节
  python3 eval.py 名物
  python3 eval.py 情节 --root ../../_从坚果云恢复_.../platform/out
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P      # noqa: E402
import cards           # noqa: E402

SETS = os.path.join(P.ROOT, 'eval_sets')


def load(column):
    path = os.path.join(SETS, column + '.jsonl')
    return [json.loads(l) for l in io.open(path, encoding='utf-8') if l.strip()]


def produced(column, code, root):
    seg_path = os.path.join(root, code, 'segments.jsonl')
    if not os.path.exists(seg_path):
        return set()
    segs = [json.loads(l) for l in io.open(seg_path, encoding='utf-8') if l.strip()]
    fn = cards._EXTRACTORS.get(column)
    if not fn:
        return set()
    return {r.get('原文') for r in fn(segs, code)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('column')
    ap.add_argument('--root', default=P.OUT)
    a = ap.parse_args()
    rows = load(a.column)
    by_code = {}
    for r in rows:
        by_code.setdefault(r['code'], []).append(r)
    tp = fp = fn = 0
    for code, items in by_code.items():
        got = produced(a.column, code, a.root)
        for it in items:
            hit = it['原文'] in got
            if it['label'] == 'yes' and hit:
                tp += 1
            elif it['label'] == 'yes' and not hit:
                fn += 1
                print('  漏掉  %s %s' % (code, (it['原文'] or '')[:36]))
            elif it['label'] == 'no' and hit:
                fp += 1
                print('  误留  %s %s' % (code, (it['原文'] or '')[:36]))
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    print('\n%s：标注 %d 条（yes %d / no %d）' % (a.column, len(rows),
                                             sum(1 for r in rows if r['label'] == 'yes'),
                                             sum(1 for r in rows if r['label'] == 'no')))
    print('  命中 %d / 误留 %d / 漏掉 %d' % (tp, fp, fn))
    print('  precision %.3f   recall %.3f' % (prec, rec))


if __name__ == '__main__':
    main()
