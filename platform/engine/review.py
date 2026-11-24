# -*- coding: utf-8 -*-
"""列级复核：抽取之后，逐条问模型「这条到底是不是这一类」。

为什么需要它：规则只能挡形态噪声（章标题、动宾短语），挡不住「像但不是」。
判定层决定「这一列跑不跑」，复核层决定「这一条留不留」，两件事分开。

协议同样用行式（不用 JSON）：
    IDX: 1
    VERDICT: yes
    WHY: 是一个完整事件
    ---

用法：
    python3 review.py B02 情节
    python3 review.py B60 名物 --drop
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P      # noqa: E402
import llm             # noqa: E402
import cards           # noqa: E402

OUT = P.OUT
PROMPT_VERSION = 'review-v1'
BATCH = 15

QUESTION = {
    '情节': '这一段/这一条是不是一个「事件」（有人做了什么、发生了什么），而不是主题词、章标题或场景描写？',
    '名物': '这一条是不是一个具体名物（器物、动植物、地名、机构），而不是抽象概念或动宾短语？',
    '规则': '这一段是不是在「立规矩」（提出要求、禁令、条件—动作），而不是角色在说话或作者在叙述？',
    '作品': '这一条是不是一个独立作品（诗、画、曲目、书），而不是普通名词？',
    '释义': '这一条是不是对词义/句意的解释，而不是举例或叙述？',
    '条目': '这一条是不是一个有独立标题的条目（志书/图谱/辞书体），而不是正文段落？',
    '引书': '这一条是不是真的引用了另一本书？本书自己的书名、篇名、普通书名号用法都不算。',
    '篇目': '这一条是不是一个真正的篇章标题，而不是正文段落或一句话？',
}


def parse(text):
    items, cur = [], {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if line == '---':
            if cur.get('idx'):
                items.append(cur)
            cur = {}
            continue
        up = line.upper()
        for key, tag in (('idx', 'IDX:'), ('verdict', 'VERDICT:'), ('why', 'WHY:')):
            if up.startswith(tag):
                cur[key] = line.split(':', 1)[1].strip()
    if cur.get('idx'):
        items.append(cur)
    return items


def review_items(column, rows, batch=BATCH):
    q = QUESTION.get(column)
    if not q:
        raise RuntimeError('这一列没有复核问句：%s' % column)
    kept, dropped = [], []
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        body = '\n'.join('%d. 【%s】%s' % (n + 1, r.get('原文') or '', (r.get('字段', {}) or {}).get('说明', ''))
                         for n, r in enumerate(part))
        prompt = ('逐条判断下面的内容是否属于【%s】。\n问题：%s\n'
                  '拿不准就答 no。严格按下面格式输出，每条一组，用单独一行 --- 分隔：\n'
                  'IDX: 序号\nVERDICT: yes 或 no\nWHY: 一句话\n---\n\n%s' % (column, q, body))
        res = llm.chat([{'role': 'system', 'content': '你是严格的图书质检员，宁可错杀不可放过。'},
                        {'role': 'user', 'content': prompt}], max_tokens=1200)
        got = {int(x['idx']): x for x in parse(res['text']) if str(x.get('idx', '')).isdigit()}
        for n, r in enumerate(part):
            v = got.get(n + 1) or {}
            ok = str(v.get('verdict', '')).lower().startswith('y')
            item = dict(r, 复核={'通过': ok, '理由': v.get('why', ''), '列': column})
            (kept if ok else dropped).append(item)
    return kept, dropped


def main():
    code, column = sys.argv[1], sys.argv[2]
    segs = [json.loads(l) for l in io.open(os.path.join(OUT, code, 'segments.jsonl'), encoding='utf-8') if l.strip()]
    fn = cards._EXTRACTORS.get(column)
    if not fn:
        print('未知列：%s' % column)
        return
    rows = fn(segs, code)
    kept, dropped = review_items(column, rows)
    path = os.path.join(OUT, code, 'review.json')
    data = {}
    if os.path.exists(path):
        data = json.load(io.open(path, encoding='utf-8'))
    data.setdefault('code', code)
    data.setdefault('prompt', PROMPT_VERSION)
    data.setdefault('columns', {})[column] = {
        'kept': len(kept), 'dropped': len(dropped),
        'past_rate': round(len(kept) / max(len(kept) + len(dropped), 1), 3),
        'dropped_samples': [{'原文': d.get('原文', '')[:60], '理由': d['复核']['理由']} for d in dropped[:10]],
    }
    json.dump(data, io.open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('%s %s：抽取 %d → 通过 %d，丢弃 %d' % (code, column, len(rows), len(kept), len(dropped)))
    for d in dropped[:5]:
        print('   × %s  ← %s' % ((d.get('原文') or '')[:40], d['复核']['理由'][:40]))


if __name__ == '__main__':
    main()
