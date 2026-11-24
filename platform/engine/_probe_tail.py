# -*- coding: utf-8 -*-
"""诊断脚本：检验「后接字」能否区分真人物与被引用的书名/注家。

不改任何产物，只打印。
"""
import os, io, json, re, sys, glob
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

def tail_profile(text, w):
    """统计 w 每次出现后紧跟的那个字符。"""
    c = Counter()
    for m in re.finditer(re.escape(w), text):
        i = m.end()
        c[text[i] if i < len(text) else ''] += 1
    return c

TARGETS = ['日知录', '礼记', '徐霞客游记', '阅微草堂笔记', '红楼梦', '金瓶梅',
           '三国志演义', '西游记', '儒林外史', '世说新语', '左传', '汉书']

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
for b in books:
    if b['book'] not in TARGETS:
        continue
    segs = jl(f'{OUT}/{b["code"]}/segments.jsonl')
    txt = '\n'.join(s['文本'] for s in segs)
    ppl = jl(f'{OUT}/{b["code"]}/people.jsonl')
    hi = [r for r in ppl if r.get('证据') == '强证据'][:12]
    print('=' * 70)
    print(f"{b['book']}  强证据 {b['强证据人物数']} 人  "
          f"图谱{'✓' if b['可出关系图谱'] else '×'}")
    for r in hi:
        tp = tail_profile(txt, r['人物'])
        top = tp.most_common(6)
        # 书名号占比
        paren = sum(v for k, v in tp.items() if k in '《》〈〉「」『』')
        tot = sum(tp.values()) or 1
        print(f"  {r['人物']:<5} 频{r['频次']:>4} 对白{r.get('对白归属',0):>4} "
              f"书名号{paren*100//tot:>3}%  "
              + '  '.join(f'{k or "␀"}{v}' for k, v in top))