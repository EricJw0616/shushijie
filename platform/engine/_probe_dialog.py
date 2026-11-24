# -*- coding: utf-8 -*-
"""实验：与人物表无关的「有对话场景」判据。

D1 对话段比：含说话动词+冒号/引号的段数 / 总段数
D2 对话轮次：说话动词+冒号的**总次数** / 总段数（一段里有几轮来回）

只打印，不改产物。
"""
import os, io, json, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

SPEECH = re.compile(
    r'(?:說道|说道|說|说|問|问|答|曰|云|笑道|叫道|嚷道|罵道|骂道|喊道|喚道|唤道)'
    r'[:：]\s*[“「"『]?')

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
rows = []
for b in books:
    segs = jl(f'{OUT}/{b["code"]}/segments.jsonl')
    n = len(segs)
    if not n:
        continue
    seg_hit = turn = 0
    for s in segs:
        k = len(SPEECH.findall(s['文本']))
        if k:
            seg_hit += 1
            turn += k
    rows.append((b['book'], b['原型'] or '--', n,
                 seg_hit / n, turn / n))

rows.sort(key=lambda x: -x[3])
print(f"{'书':<20}{'原':<4}{'段数':>6}{'对话段比':>9}{'轮次/段':>8}")
for nm, p, n, r1, r2 in rows:
    print(f'{nm[:19]:<20}{p:<4}{n:>6}{r1:>9.3f}{r2:>8.2f}')