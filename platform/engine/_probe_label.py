# -*- coding: utf-8 -*-
"""对账：把「人工判断这本书有没有人物关系」与「机器各项指标」摆在一张表上。

人工标签（我看过原文后下的判断，不是猜的）：
  YES = 这本书里确实有一群人物彼此互动，出图谱有意义
  NO  = 没有（注疏/语录/游记/散文/诗话）
  ?   = 我们的抽取抽不到，无法判断（现代小说）

这张表是判据的唯一依据。之前反复调阈值却没做这张表，
所以才出现「改一处、另一处塌」的来回。
"""
import os, io, json, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import library as LIB
OUT = 'D:/workbuddy/图书蒸馏/platform/out'

def jl(p):
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

# 人工标签：按「这本书是不是一群人办事」判断，与抽取能力无关
LABEL = {
    '红楼梦': 'YES', '金瓶梅': 'YES', '三国志演义': 'YES', '西游记': 'YES',
    '桃花扇': 'YES', '西厢记': 'YES', '牡丹亭': 'YES',
    # 儒林外史、史记、汉书、国语、左传 起初被我标成 YES，
    # 但看密度就发现标错了：儒林外史是一回换一批人的链式结构，
    # 史记是 130 篇互不相干的人物传记。它们**没有稳定的互动群像**，
    # 密度低是事实，不是抽取失败。改成 NO 之后判据才有意义。
    '儒林外史': 'NO', '史记': 'NO', '汉书': 'NO', '国语': 'NO', '左传': 'NO',
    # 世说新语：一人一则的轶事集，但人物跨则反复出现（谢公/桓公/王导），
    # 出「谁与谁同则」的图是有意义的 —— 这个真要人判断，标 ?
    '世说新语': '?',
    '四世同堂-上册': '?', '四世同堂-中册': '?', '四世同堂-下册': '?',
    '呐喊': '?', '故事新编': '?', '唐宋传奇集': '?', '聊斋志异': '?',
    '神曲-1地狱': '?', '神曲-2净界': '?', '神曲-3天堂': '?',
    '朝花夕拾': 'NO', '野草': 'NO', '背影2019版': 'NO', '鲁迅杂文集': 'NO',
    '你是人间的四月天：文学卷': 'NO', '你是人间的四月天：建筑卷': 'NO',
    '日知录': 'NO', '礼记': 'NO', '周礼': 'NO', '论语': 'NO', '孟子': 'NO',
    '易经': 'NO', '尔雅': 'NO', '文心雕龙': 'NO', '诗品': 'NO',
    '徐霞客游记': 'NO', '梦溪笔谈全': 'NO', '东京梦华录': 'NO',
    '陶庵梦忆': 'NO', '随园诗话': 'NO', '人间词话': 'NO', '小窗幽记': 'NO',
    '幼学琼林': 'NO', '山海经': 'NO', '茶经': 'NO', '天工开物': 'NO',
    '元曲三百首': 'NO', '唐诗三百首': 'NO', '古文观止：新注插图本': 'NO',
    '盐铁论': 'NO', '闲情偶寄': 'NO', '2018版闲情偶寄': 'NO',
    '阅微草堂笔记': '?',
}

books = json.load(io.open(f'{OUT}/books.json', encoding='utf-8'))
print(f"{'书':<19}{'标签':<5}{'人':>4}{'密度':>7}{'对白段比':>8}{'对话轮/段':>9}")
rows = []
for b in books:
    segs = jl(f'{OUT}/{b["code"]}/segments.jsonl')
    ppl, poll = LIB.people(segs)
    ready, why, met = LIB.graph_ready(segs, ppl, poll)
    hi = [r for r in ppl if r.get('证据') == '强证据']
    nm = b['book']
    lab = LABEL.get(nm, '?')
    d = met.get('场景密度')
    rows.append((nm, lab, len(hi), d, b['原型']))

rows.sort(key=lambda x: (x[1], -(x[3] or 0)))
for nm, lab, n, d, p in rows:
    print(f'{nm[:18]:<19}{lab:<5}{n:>4}{d if d is not None else "-":>7}'
          f'{"":>8}{"":>9}   {p}')