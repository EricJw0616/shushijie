# -*- coding: utf-8 -*-
"""实验：找一条能把「有人物关系的书」与「引用/游记/语录」分开的判据。

候选指标：
  M1 场景段占比：同段出现 ≥3 个候选人的段数 / 含 ≥1 人的段数
  M2 最大连通分量占会说话人的比例（真社交网络是一个大连通块）
  M3 配对共现（当前判据，作对照）

只打印，不改产物。
"""
import os, io, json, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

def analyze(segs, ppl):
    hi = [r for r in ppl if r.get('证据') == '强证据']
    if len(hi) < 6:
        return None
    names = [r['人物'] for r in hi]
    talk = [r for r in hi if r.get('对白归属', 0) >= 5]
    tnames = [r['人物'] for r in talk]

    seg1 = seg2 = seg3 = 0
    pair = Counter()
    for s in segs:
        t = s['文本']
        hit = [n for n in names if n in t]
        k = len(hit)
        if k >= 1:
            seg1 += 1
        if k >= 2:
            seg2 += 1
            for i in range(k):
                for j in range(i + 1, k):
                    pair[(hit[i], hit[j])] += 1
        if k >= 3:
            seg3 += 1

    # M2 连通分量：把「共现 ≥3 次」的配对连起来
    par = {n: n for n in tnames}
    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    edges = [(a, b) for (a, b), v in pair.items() if v >= 3 and a in par and b in par]
    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            par[ra] = rb
    comp = Counter(find(n) for n in tnames)
    big = max(comp.values()) if comp else 0
    pair3 = len(edges)
    pn = len(tnames) * (len(tnames) - 1) // 2 if len(tnames) > 1 else 1

    return {
        '人': len(hi), '说话人': len(tnames), '配对': pair3,
        '配对率': round(pair3 / max(1, pn), 2),
        '场景2比': round(seg2 / max(1, seg1), 2),
        '场景3比': round(seg3 / max(1, seg1), 3),
        '最大块': round(big / max(1, len(tnames)), 2),
    }

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
rows = []
for b in books:
    segs = jl(f'{OUT}/{b["code"]}/segments.jsonl')
    ppl = jl(f'{OUT}/{b["code"]}/people.jsonl')
    m = analyze(segs, ppl)
    if m:
        rows.append((b['book'], b['原型'] or '--', m))

rows.sort(key=lambda x: -x[2]['场景3比'])
print(f"{'书':<20}{'原':<4}{'人':>4}{'说':>4}{'配对':>5}{'配对率':>6}"
      f"{'场景3比':>8}{'最大块':>7}")
for nm, p, m in rows:
    print(f"{nm[:19]:<20}{p:<4}{m['人']:>4}{m['说话人']:>4}{m['配对']:>5}"
          f"{m['配对率']:>7.2f}{m['场景3比']:>9.3f}{m['最大块']:>8.2f}")