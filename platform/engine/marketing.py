# -*- coding: utf-8 -*-
"""第 4 期仅保留：营销 7 项（草稿 + 原文证据 + 待人工确认）。

2026-11-13 决定：第 4 期 23 项中，营销 7 项保留；其余 16 项（数据集 9 + 可追溯 3 + 版权 4）放弃。
营销产物默认不自动跑；需要时用命令行，或在上传时设 BOOKDISTILL_MARKETING=1。

7 项：关键词、内容简介、目标读者、适用场景、阅读收获、情绪价值、营销线索。

原则：
  1. 只给“草稿”，状态一律 needs_review，人确认后才算数。
  2. 每条结论必须挂一段逐字原文；挂不上的条目直接丢，不硬留。
  3. 输入是全书压缩片段（不是整本原文），所以 note 里写明“基于压缩文本”，
     真正通读复核由人或后续整书模式完成。
  4. 营销是主观判断，系统不承诺“自动正确”。

用法：
    python3 marketing.py B58 B60
    python3 marketing.py --all --max-chars 16000
"""
import io
import json
import os
import re
import sys

import llm
from product_language import PRODUCT_LANGUAGE
import paths as P

TAGS = {
    'keywords': ('001', '关键词', 'BT-SEED-2a10bc5c-3dc5-4231-9395-c1926e9c1a1e', 'marketing_keywords'),
    'summary': ('002', '内容简介', 'BT-73501b96-614a-458e-8e69-df1e4a6ac522', 'marketing_content_summary'),
    'audience': ('003', '目标读者', 'BT-SEED-0532369b-5eb2-4a53-89b2-6959e112a9a2', 'marketing_target_readers'),
    'scenarios': ('004', '适用场景', 'BT-SEED-d4b3b846-45c7-4842-9966-14696a727fea', 'marketing_use_scenarios'),
    'gains': ('005', '阅读收获', 'BT-SEED-5689bcdc-5f26-4719-b946-aeac2df5615c', 'marketing_reading_gains'),
    'emotions': ('006', '情绪价值', 'BT-SEED-6c288dcb-6d8c-43f6-ae76-28d9b4a7eeb8', 'marketing_emotional_value'),
    'leads': ('007', '营销线索', 'BT-SEED-403a005c-1a3e-48d5-b855-17d835543707', 'marketing_leads'),
}
PACK = {'id': 'publishing_marketing_insight', 'version': '1.5.0', 'revision': 1}

SYSTEM = ('你是出版社的营销编辑。你只依据用户给出的图书原文片段工作，'
          '不使用书外知识，不编造事实。每一条结论都必须能在给出的原文里找到'
          '一字不差的引文；找不到就宁可不写。只输出 JSON。') + PRODUCT_LANGUAGE


def _rows(code):
    p = os.path.join(P.OUT, code, 'segments.jsonl')
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()] if os.path.exists(p) else []


def _book(code):
    p = os.path.join(P.OUT, code, 'book.json')
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else {}


def _pub(code):
    p = os.path.join(P.OUT, code, 'publication.json')
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else {}


def build_input(code, max_chars=16000):
    """全书压缩：每篇取开头 2 段 + 均匀补段，封顶 max_chars。"""
    rows = _rows(code)
    bk = _book(code)
    pub = _pub(code)
    items = (pub.get('items') or {})
    meta = ['书名：%s' % (bk.get('book') or '')]
    for k, label in (('author', '作者'), ('publisher', '出版社'), ('classification', '分类')):
        v = (items.get(k) or {}).get('value')
        if v:
            meta.append('%s：%s' % (label, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)))
    outline = []
    p = os.path.join(P.OUT, code, 'outline.jsonl')
    if os.path.exists(p):
        outline = [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]

    # 选段：每篇开头 2 段，再均匀补
    by_pian = {}
    for r in rows:
        by_pian.setdefault(str(r.get('篇序')), []).append(r)
    picked, seen = [], set()

    def add(r):
        if r['id'] not in seen:
            seen.add(r['id'])
            picked.append(r)

    for k in sorted(by_pian, key=lambda x: (x != '0', x)):
        for r in by_pian[k][:2]:
            add(r)
    rest = [r for r in rows if r['id'] not in seen]
    step = max(1, len(rest) // 40) if rest else 1
    for r in rest[::step]:
        add(r)

    lines, total = [], 0
    if outline:
        lines.append('篇目：' + '、'.join((x.get('篇') or '') for x in outline[:30]))
    for r in picked:
        t = (r.get('文本') or '').strip()
        if not t:
            continue
        block = '[%s] %s' % (r['id'], t)
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)
    return '\n'.join(meta + lines), total


def _json(text):
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    i, j = t.find('{'), t.rfind('}')
    if i >= 0 and j > i:
        t = t[i:j + 1]
    try:
        return json.loads(t)
    except Exception:
        return json.loads(t, strict=False)


def _segmap(rows):
    return {r['id']: (r.get('文本') or '') for r in rows}


def _fix_ev(ev, segmap):
    """把模型给的引文对回真实段；对不上就返回 None。"""
    if not isinstance(ev, dict):
        return None
    q = (ev.get('quote') or '').strip()
    sid = ev.get('seg') or ''
    if not q:
        return None
    if sid in segmap and q in segmap[sid]:
        return {'seg': sid, 'quote': q}
    for k, t in segmap.items():
        if q in t:
            return {'seg': k, 'quote': q}
    return None


def _call(prompt, max_tokens=3000):
    r = llm.chat([{'role': 'system', 'content': SYSTEM},
                  {'role': 'user', 'content': prompt}],
                 max_tokens=max_tokens, temperature=0.3, json_mode=True)
    return r


def _call_json(prompt, max_tokens=3000):
    """模型偶尔吐出坏 JSON；失败时让它只修格式，不重写内容。"""
    r = _call(prompt, max_tokens)
    try:
        return _json(r['text'])
    except Exception:
        bad = (r.get('text') or '')[:8000]
        fix = llm.chat([{'role': 'system', 'content': '你只修 JSON 格式，不改结论。'},
                        {'role': 'user', 'content':
                         '下面这段 JSON 被截断或格式有误。请重新输出一份完整、合法的 JSON；'
                         '引文每条不超过 60 字，关键词最多 8 个，其他每类最多 4 条；不要解释。\n' + bad}],
                       max_tokens=max_tokens, temperature=0, json_mode=True)
        return _json(fix['text'])


def _prompt_a(text):
    return (
        '下面是这本书的原文片段和出版信息。请完成两项：\n'
        '1) 提炼 5-15 个营销关键词。要求：代表全书主题/人物/事件/题材/概念，'
        '有区分度；排除“人生/世界/生活/故事/思想/文化”这类泛词，'
        '排除“重磅好书/年度必读/爆款”这类广告词；每项给 reason。\n'
        '2) 写一段 150-300 字的客观内容简介，不要改写成广告口号。\n'
        '每一项都要给 evidence：{"seg":"段号","quote":"原文逐字引文"}。'
        '引文必须来自下面给出的片段，一个字都不能改。\n\n'
        '只输出 JSON：{"keywords":[{"keyword":"","seg":"","quote":"","reason":""}],'
        '"summary":"","summary_evidence":[{"seg":"","quote":""}]}\n\n'
        '===== 原文 =====\n' + text
    )


def _prompt_b(text):
    return (
        '下面是这本书的原文片段。请给出五类营销判断，每类 3-6 条：\n'
        '- audience 目标读者\n- scenarios 适用场景\n- gains 阅读收获\n'
        '- emotions 情绪价值\n- leads 营销线索\n'
        '每条：{"text":"一句结论","seg":"段号","quote":"原文逐字引文",'
        '"reason":"为什么","basis":"原文明示或推断"}。\n'
        '要求：只依据给出的原文；推断必须标“推断”，不能包装成原文明示；'
        '找不到依据就少写或不写。引文必须逐字来自片段。\n\n'
        '只输出 JSON：{"audience":[...],"scenarios":[...],"gains":[...],'
        '"emotions":[...],"leads":[...]}\n\n'
        '===== 原文 =====\n' + text
    )


def _item(key, value, evidence, note='', confidence=0.6):
    no, name, tid, field = TAGS[key]
    return {'no': no, 'name': name, 'tag_id': tid, 'field': field,
            'value': value, 'status': 'needs_review', 'method': 'llm',
            'confidence': confidence, 'evidence': evidence, 'note': note}


def build(code, max_chars=16000, model_note=''):
    rows = _rows(code)
    bk = _book(code)
    if not rows:
        return {'code': code, 'book': bk.get('book') or '', 'pack': PACK,
                'items': {}, 'stats': {'items': 0, 'dropped': 0},
                'note': '没有原文，跳过'}
    text, used = build_input(code, max_chars)
    segmap = _segmap(rows)
    a = _call_json(_prompt_a(text), 4000)
    b = _call_json(_prompt_b(text), 4500)

    items, dropped = {}, 0

    kws = []
    for x in a.get('keywords') or []:
        ev = _fix_ev({'seg': x.get('seg'), 'quote': x.get('quote')}, segmap)
        if not ev or not (x.get('keyword') or '').strip():
            dropped += 1
            continue
        k = x['keyword'].strip()
        if all(k != y['keyword'] for y in kws):
            kws.append({'keyword': k, 'reason': x.get('reason') or '', 'evidence': [ev]})
    items['keywords'] = _item('keywords', kws, [e for x in kws for e in x['evidence']],
                              '基于压缩文本，需人工确认；共 %d 个' % len(kws))

    sev = [e for e in (_fix_ev({'seg': x.get('seg'), 'quote': x.get('quote')}, segmap)
                       for x in (a.get('summary_evidence') or [])) if e]
    if (a.get('summary') or '').strip() and sev:
        items['summary'] = _item('summary', {'text': a['summary'].strip()}, sev,
                                 'AI 概括，需人工确认')
    else:
        items['summary'] = _item('summary', None, [], '未生成或证据不足')
        items['summary']['status'] = 'not_found'
        dropped += 1

    for key, label in (('audience', '目标读者'), ('scenarios', '适用场景'),
                       ('gains', '阅读收获'), ('emotions', '情绪价值'), ('leads', '营销线索')):
        vals = []
        for x in b.get(key) or []:
            ev = _fix_ev({'seg': x.get('seg'), 'quote': x.get('quote')}, segmap)
            txt = (x.get('text') or '').strip()
            if not ev or not txt:
                dropped += 1
                continue
            vals.append({'text': txt, 'basis': x.get('basis') or '推断',
                         'reason': x.get('reason') or '', 'evidence': [ev]})
        items[key] = _item(key, vals, [e for x in vals for e in x['evidence']],
                           'AI 草稿，需人工确认；共 %d 条' % len(vals))

    rec = {'code': code, 'book': bk.get('book') or '', 'pack': PACK,
           'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
           'model': llm.CFG.get('BOOKDISTILL_LLM_MODEL', ''),
           'input_chars': used,
           'items': items,
           'stats': {'items': len(items), 'dropped': dropped,
                     'evidence': sum(len(x.get('evidence') or []) for x in items.values())}}
    return rec


def write(rec):
    d = os.path.join(P.OUT, rec['code'])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'marketing.json')
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(rec, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def main(argv):
    codes, max_chars = [], 16000
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == '--all':
            codes = sorted([d for d in os.listdir(P.OUT)
                            if os.path.isdir(os.path.join(P.OUT, d)) and re.match(r'^[A-Z][A-Z0-9]{0,3}$', d)])
        elif a == '--max-chars':
            i += 1
            max_chars = int(argv[i])
        elif a.startswith('-'):
            print('unknown option', a)
            return 2
        else:
            codes.append(a)
        i += 1
    if not codes:
        print(__doc__)
        return 2
    if not llm.ready():
        print('模型未配置（app/.env 缺 BASE/KEY/MODEL），无法生成营销草稿')
        return 1
    for c in codes:
        try:
            rec = build(c, max_chars)
            p = write(rec)
            s = rec['stats']
            print('%s %-28s 7 项，证据 %d 条，丢弃 %d，输入 %d 字 -> %s'
                  % (c, rec['book'][:26], s.get('evidence', 0), s.get('dropped', 0),
                     rec.get('input_chars', 0), p))
        except Exception as e:
            print('%s 失败：%s' % (c, e))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
