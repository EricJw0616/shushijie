# -*- coding: utf-8 -*-
"""实验：第三通道 —— 引语后置说话人（现代白话小说的主格式）。

  “瑞宣还没回来哪？”瑞宣说。      ← 引号后 + 名字 + 说
  “……”他说，
  “……”祁老人慢慢的道，

只打印，不改产物。
"""
import os, io, json, re, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

# 引号收尾 + 可选逗号/空白 + 2-4 汉字 + 说话动词
POST = re.compile(r'[”」』"]\s*[，,]?\s*([\u4e00-\u9fff]{2,4})'
                  r'(?:说|說|道|问|問|答|喊|叫|嚷|笑|叹|歎)')

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
TARGET = ['四世同堂-上册', '四世同堂-中册', '四世同堂-下册', '呐喊', '朝花夕拾',
          '故事新编', '红楼梦', '儒林外史', '聊斋志异', '神曲-1地狱']
for b in books:
    if b['book'] not in TARGET:
        continue
    segs = jl(f'{OUT}/{b["code"]}/segments.jsonl')
    c = Counter()
    for s in segs:
        for m in POST.finditer(s['文本']):
            c[m.group(1)] += 1
    print('=' * 58)
    print(b['book'], ' 后置锚点总数', sum(c.values()))
    for w, n in c.most_common(18):
        print(f'   {w:<8}{n}')