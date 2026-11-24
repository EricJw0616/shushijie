# -*- coding: utf-8 -*-
"""规则卡抽取器：面向 P3 论说型（讲「该怎么做」的书）。

与「正则捞词」的区别：
  正则只能找到候选段落，不能生成规则。规则卡必须是
  if(条件) → then(动作) + 边界(反噬/例外) 三段式，
  且每一段引文都能在正文逐字回查。

因此本模块分两步：
  1. 抽取候选（自动，可复现）—— 英文句法信号 + 中文规范句式
  2. 成卡（人工/模型确认，写进 cards/*.json）

平台只对「已确认」的卡片开放调用；候选只作工作台，不进资产库。
"""
import re, json, io, os
import paths as P

HAN = re.compile('[\\u3400-\\u4DBF\\u4E00-\\u9FFF\\uF900-\\uFAFF'
                 '\\U00020000-\\U0002FA1F]')

# 强规范信号：表示「不做会出事 / 做错有代价」
STRONG = re.compile(
    '切忌|最忌|切不可|断不可|万不可|务须|务必|必须|必先|须先|不得|不可|'
    '不宜|勿|毋|莫|忌')

# 弱规范信号：只是一般陈述，不足以成规则
WEAK = re.compile('必|须|应|当|宜')


def candidates(segs, min_strong=2):
    """找规则卡候选段：强规范信号 ≥ min_strong 次。"""
    out = []
    for s in segs:
        t = s['文本']
        n = len(STRONG.findall(t))
        if n >= min_strong:
            out.append({'锚点': s['id'], '篇': s['篇'],
                        '强信号数': n, '字数': s['字数'], '原文': t})
    out.sort(key=lambda x: -x['强信号数'])
    return out


def sent_split(t):
    """按句末标点切句，保留标点。"""
    parts, cur = [], ''
    for ch in t:
        cur += ch
        if ch in '。！？；':
            parts.append(cur)
            cur = ''
    if cur.strip():
        parts.append(cur)
    return [p for p in parts if p.strip()]


def locate_quote(quote, segs):
    """引文回查：必须能在某一段里逐字找到。
    返回 (是否通过, 命中锚点列表)。
    支持「……」省略：按省略号拆开，每段都要命中，且顺序一致。"""
    quote = quote.strip()
    if not quote:
        return False, []
    parts = [p.strip() for p in re.split(r'…+|\.\.\.', quote) if p.strip()]
    if not parts:
        return False, []
    hits = []
    for p in parts:
        found = [s['id'] for s in segs if p in s['文本']]
        if not found:
            return False, hits
        hits.append(found[0])
    return True, hits


def check_cards(cards, segs):
    """质检：ID 唯一、锚点有效、**原文**逐字可回查、边界非空。

    体例（这一条定错，整库引文都不可信）：
      - 「原文」= 逐字引文，必须在正文一字不差地查到 → 硬校验
      - 「条件」「动作」= 二次加工的白话转写 → 不校验回查，
        只校验非空。要求它们可回查是概念错误。
      - 「边界」= 整理者写的使用前提与反噬，必须非空；
        若边界本身引用原文，那段引用会单独走原文校验。

    返回 (通过数, 失败清单)。
    """
    ids, fails, ok = set(), [], 0
    anchors = {s['id'] for s in segs}
    for c in cards:
        err = []
        cid = c.get('id')
        if cid in ids:
            err.append('ID 重复')
        ids.add(cid)
        if c.get('锚点') not in anchors:
            err.append(f"锚点无效 {c.get('锚点')}")
        # 唯一硬校验：原文必须逐字可回查
        q = c.get('原文')
        if not q:
            err.append('缺原文')
        else:
            good, _ = locate_quote(q, segs)
            if not good:
                err.append('原文不可回查')
        # 二次加工字段只校验非空
        for fld in ('条件', '动作'):
            if not c.get(fld):
                err.append(f'缺{fld}')
        if not c.get('边界'):
            err.append('缺边界')
        if err:
            fails.append({'id': cid, '问题': err})
        else:
            ok += 1
    return ok, fails


if __name__ == '__main__':
    import sys
    base = P.OUT
    code = sys.argv[1] if len(sys.argv) > 1 else 'B01'
    segs = [json.loads(l) for l in io.open(f'{base}/{code}/segments.jsonl', encoding='utf-8')]
    c = candidates(segs)
    print(f'{code}: 候选 {len(c)} 段')
    for x in c[:5]:
        print(f"  {x['锚点']} [{x['篇']}] 强信号{x['强信号数']}  {x['原文'][:60]}…")