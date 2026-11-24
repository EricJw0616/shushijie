# -*- coding: utf-8 -*-
"""实验：用「跨书重复」判据区分真名与通用词。

假设：真人物名只属于一本书（玄德只出现在三国），
通用词/被引古人跨多本书出现（一面跨8本、有人跨18本、孔子跨21本）。

只打印，不改产物。
"""
import os, io, json, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
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
nocross = Counter()
for nm, c in per.items():
    for w in c:
        nocross[w] += 1

# 检查四世同堂、呐喊、朝花夕拾的高频词，看跨书判据是否奏效
for nm in ['四世同堂-上册', '四世同堂-中册', '呐喊', '朝花夕拾', '故事新编']:
    if nm not in per:
        continue
    print('=' * 54)
    print(nm)
    for w, n in per[nm].most_common(26):
        print(f'   {w:<9}{n:>4}  跨{nocross[w]:>2}本  '
              + ('← 通用词' if nocross[w] >= 3 else ''))