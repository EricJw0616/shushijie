# -*- coding: utf-8 -*-
"""挖 C 通道（说话人法）的误收词表。只打印，不改产物。

目标：拿到全库真实误收样本，据此写过滤器，而不是凭想象堆一串「可能的虚词」。
"""
import os, io, json, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

say_after = re.compile(
    r'([\u4e00-\u9fff]{2,4})'
    r'(?:說道|说道|說|说|問|问|答|曰|云|笑道|叫道|嚷道|罵道|骂道)'
    r'(?:[:：]?\s*[“「"『]?)')

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
per = {}
for b in books:
    segs = jl(f'{OUT}/{b["code"]}/segments.jsonl')
    c = Counter()
    for s in segs:
        for m in say_after.finditer(s['文本']):
            c[m.group(1)] += 1
    if c:
        per[b['book']] = c

tot = Counter()
for nm, c in per.items():
    for w, n in c.items():
        tot[w] += n

print('### 全库说话人位置总频次 top70（跨书数高=通用误收）')
print('  <词> <总次数> <跨书数>   → 人工判断是否人名')
for w, n in tot.most_common(70):
    nb = len({k for k, v in per.items() if w in v})
    print(f'  {w:<6}{n:>6}  跨{nb:>3}本')