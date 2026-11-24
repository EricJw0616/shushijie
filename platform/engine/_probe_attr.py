# -*- coding: utf-8 -*-
"""实验：对白归属两路判据。

路 1（紧邻）：说话动词前紧跟的 2-3 字，形如姓名 → 古代白话/文言
路 2（主语）：同句内**第一个**姓氏开头词 → 现代小说（主语前置）

只打印，不改产物。
"""
import os, io, json, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import library as LIB

OUT = 'D:/workbuddy/图书蒸馏/platform/out'
BAD_TAIL = set('的了是在有和就都也很不没这那什么个们着过地说'
               '要会能可应为所如如果但是而且所以因为')
COMMON = getattr(LIB, 'COMMON', set())
han_run = re.compile(r'[\u4e00-\u9fff]{2,4}')
anchor = re.compile(r'(?:说道|问道|答道|笑道|叫道|喝道|骂道|道|说|问|答)'
                    r'[:：]?\s*[“「]')

def _name_in(run):
    """从一个汉字串里取最像名字的片段：先试尾部（紧邻说话动词）。"""
    for L in (3, 2):
        if len(run) < L:
            continue
        w = run[-L:]
        if LIB._is_xing(w[0]) and w[-1] not in BAD_TAIL and w not in COMMON:
            return w
        w = run[:L]
        if LIB._is_xing(w[0]) and w[-1] not in BAD_TAIL and w not in COMMON:
            return w
    return None

def attr(segs, use_subject=True):
    B, mode = Counter(), Counter()
    for s in segs:
        t = s['文本']
        for mm in anchor.finditer(t):
            win = t[max(0, mm.start() - 160):mm.start()]
            parts = re.split(r'[。！？；…\.!?][”」』"]?', win)
            tail = parts[-1] if parts else win
            runs = han_run.findall(tail)
            best, how = None, None
            if runs:
                best = _name_in(runs[-1])
                if best:
                    how = '紧邻'
            if not best and use_subject:
                for run in runs:
                    w = _name_in(run)
                    if w:
                        best, how = w, '主语'
                        break
            if best:
                B[best] += 1
                mode[how] += 1
    return B, mode

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
TARGET = ['四世同堂-上册', '四世同堂-中册', '红楼梦', '儒林外史', '日知录',
          '徐霞客游记', '礼记', '呐喊', '朝花夕拾']
for b in books:
    if b['book'] not in TARGET:
        continue
    segs = [json.loads(l) for l in io.open(f'{OUT}/{b["code"]}/segments.jsonl',
                                           encoding='utf-8') if l.strip()]
    ppl = [json.loads(l) for l in io.open(f'{OUT}/{b["code"]}/people.jsonl',
                                          encoding='utf-8') if l.strip()]
    B, mode = attr(segs)
    print('=' * 62)
    print(f"{b['book']}   紧邻 {mode['紧邻']}  主语 {mode['主语']}")
    hi = [r for r in ppl if r.get('证据') == '强证据' and r['频次'] >= 40]
    for r in hi[:14]:
        old = r.get('对白归属', 0)
        new = B.get(r['人物'], 0)
        print(f"  {r['人物']:<7} 频{r['频次']:>5}  旧{old:>4} 新{new:>4}"
              f"  {'↑' if new > old else ''}")