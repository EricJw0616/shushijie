# -*- coding: utf-8 -*-
"""诊断脚本：为图谱准入找一条能同时挡下「注疏书」与「游记」的判据。

对全库 56 本计算多个候选指标，人工看哪条分得开。不改产物。
"""
import os, io, json, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

# 注释/引用标记：这些字紧跟人名时，该人是在「被引用」，不是「在行动」
CITE_TAIL = set('注註笺箋疏解云曰言謂谓箋案按')

def metrics(segs, ppl):
    hi = [r for r in ppl if r.get('证据') == '强证据']
    if len(hi) < 6:
        return None
    txt = '\n'.join(s['文本'] for s in segs)

    # --- M1 对白密度：对白归属 / 频次 ---
    dens = []
    for r in hi:
        f = r['频次'] or 1
        dens.append(r.get('对白归属', 0) / f)
    dens.sort()
    med_dens = dens[len(dens) // 2] if dens else 0
    # 有多少人「几乎不说话」（密度<3%）
    low = sum(1 for d in dens if d < 0.03) / max(1, len(dens))

    # --- M2 书名号后接占比（取最高那位）---
    mx_paren = 0
    for r in hi[:40]:
        c = Counter()
        for m in re.finditer(re.escape(r['人物']), txt):
            i = m.end()
            c[txt[i] if i < len(txt) else ''] += 1
        tot = sum(c.values()) or 1
        p = sum(v for k, v in c.items() if k in '《》〈〉') / tot
        mx_paren = max(mx_paren, p)

    # --- M3 配对共现：有对白的人之间，平均同段次数 ---
    talk = [r for r in hi if r.get('对白归属', 0) >= 5][:30]
    pair_n, pair_hit3, pair_sum = 0, 0, 0
    if len(talk) >= 2:
        names = [r['人物'] for r in talk]
        cnt = Counter()
        for s in segs:
            t = s['文本']
            hit = [n for n in names if n in t]
            if len(hit) >= 2:
                for i in range(len(hit)):
                    for j in range(i + 1, len(hit)):
                        cnt[(hit[i], hit[j])] += 1
        pair_n = len(names) * (len(names) - 1) // 2
        pair_hit3 = sum(1 for v in cnt.values() if v >= 3)
        pair_sum = sum(cnt.values())

    return {
        'n': len(hi), 'med_dens': round(med_dens, 3), 'low': round(low, 2),
        'mx_paren': round(mx_paren, 2),
        'pair_n': pair_n, 'pair3': pair_hit3,
        'pair3_rate': round(pair_hit3 / max(1, pair_n), 2),
        'pair_sum': pair_sum,
        'pair_sum_rate': round(pair_sum / max(1, pair_n), 2),
    }

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
rows = []
for b in books:
    segs = jl(f'{OUT}/{b["code"]}/segments.jsonl')
    ppl = jl(f'{OUT}/{b["code"]}/people.jsonl')
    m = metrics(segs, ppl)
    if not m:
        continue
    rows.append((b['book'], b['可出关系图谱'], b['原型'] or '--', m))

# 配对率在「只有 2 个人」时恒为 1.00（1/1），没有区分度 —— 必须先按配对数排序看
rows.sort(key=lambda x: -x[3]['pair3'])
print(f"{'书':<18}{'原':<4}{'图':<3}{'人':>4}{'中位对白密度':>8}"
      f"{'低密度比':>7}{'书名号':>7}{'配对>=3':>9}{'配对率':>7}{'共现数':>8}{'共现率':>7}")
for nm, ok, p, m in rows:
    print(f"{nm[:17]:<18}{p:<4}{'✓' if ok else '×':<3}{m['n']:>4}"
          f"{m['med_dens']:>10.3f}{m['low']:>8.2f}{m['mx_paren']:>8.2f}"
          f"{m['pair3']:>8}{m['pair3_rate']:>9.2f}{m['pair_sum']:>8}{m['pair_sum_rate']:>8.2f}")