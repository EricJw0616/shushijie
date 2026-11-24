# -*- coding: utf-8 -*-
"""理解类 4 项：事实与数值、技能与规则、核心概念、概念与原理。

只出草稿（needs_review），每条带原文证据；对不上就丢。
定义见 标签体系/理解类4项_定义.md。

不做：词性、句法、跨句指代（放弃）；知识点关系 4 项（等应用层）。
"""
import io
import json
import os
import re
import sys

import llm
import marketing as MK
import paths as P

TAGS = {
    'facts': ('010', '事实与数值', 'BT-PUBKNOW-ad60cd11-1ed7-4e98-94b2-b1b49d79db28', 'facts_and_numbers'),
    'skills': ('012', '技能与规则', 'BT-PUBKNOW-7ace82ee-e14d-4bfd-a800-de13c6600b1d', 'skills_and_rules'),
    'concepts': ('004', '核心概念', 'BT-PUBKNOW-755c5204-f054-42fb-910b-59bfeca382bc', 'core_concepts'),
    'principles': ('011', '概念与原理', 'BT-PUBKNOW-ccec4b6a-06c0-4761-a4de-4660eeee2534', 'concepts_and_principles'),
}
PACK = {'id': 'publishing_structured_knowledge', 'version': '1.8.0'}

SYS = ('你是出版社的资深编辑。只依据用户给出的原文片段工作，不使用书外知识。'
       '每条结论必须能在原文里找到一字不差的引文；找不到就不写。只输出 JSON。')


def _rows(code):
    p = os.path.join(P.OUT, code, 'segments.jsonl')
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()] if os.path.exists(p) else []


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


def _call(prompt, max_tokens=2500):
    r = llm.chat([{'role': 'system', 'content': SYS},
                  {'role': 'user', 'content': prompt}],
                 max_tokens=max_tokens, temperature=0.2, json_mode=True)
    return r


def _fix_ev(ev, segmap):
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


def _skill_ok(text):
    """只留“可复用”的规则：有规范词，且不是第一人称叙事/假设句。"""
    t = (text or '').strip()
    if not t or len(t) > 100:
        return False
    norm = re.compile(r'必须|应当|应|须|不得|禁止|不准|一律|概莫|予以|凡.{0,30}者')
    if not norm.search(t):
        return False
    if re.search(r'[我他她]', t):
        return False
    if t.startswith('如果') and not re.search(r'必须|应|不得|须', t):
        return False
    return True


def _p_facts(text):
    return (
        '从下面原文片段里抽取“事实与数值”。只抽正文中直接陈述的事实、数字、时间、地点、条件、范围；'
        '不要抽出版信息（书名/作者/出版社/出版时间/定价/ISBN/开本/责任编辑/主编等），不要抽“本书由……”这类版权页内容；'
        '不推断、不补算、不跨段拼接；每条只放一项事实/一个数值。最多 15 条，宁缺毋滥。\n'
        '每条：{"fact":"一句话事实","value":"原文关键值","unit":"单位或空","time":"时间或空",'
        '"condition":"条件/范围或空","category":"时间|数量|地点|人物|事件|其他",'
        '"seg":"段号","quote":"逐字原文"}。\n'
        '没有就返回 {"facts":[]}。只输出 JSON：{"facts":[...]}\n\n原文：\n' + text
    )


def _p_skills(text):
    return (
        '从下面原文片段里抽取“技能与规则”：只抽可复用的做法、步骤、条件、限制、例外、适用范围。'
        '必须有“先…再…”“如果…就…”“须/应/不得/除外”这类明确结构；'
        '历史事件里的刑罚、家训、碑文、人物对话不算技能，除非原文明确把它作为规则要求执行；没有就返回空。\n'
        '每条：{"type":"步骤|规则|限制|例外","text":"做什么","order":序号或0,'
        '"condition":"条件或空","seg":"段号","quote":"逐字原文"}。最多 15 条。\n'
        '只输出 JSON：{"skills":[...]}\n\n原文：\n' + text
    )


def _p_concepts(text):
    return (
        '提炼这本书的 3–8 个核心概念。概念必须是书里出现、并被定义/解释/反复论述的术语或短语，'
        '不超过 12 字；不要泛词（人生/世界/生活/故事/思想/文化），不要只用一次、没有解释的专名，'
        '不要书外概念。每条说明“为什么是核心”。\n'
        '每条：{"concept":"概念","definition":"书中的定义/解释，压缩但不改事实",'
        '"why_core":"为什么是核心","seg":"段号","quote":"逐字原文"}。\n'
        '没有足够依据就少写。只输出 JSON：{"concepts":[...]}\n\n原文：\n' + text
    )


def _p_principles(text):
    return (
        '提炼这本书的 3–6 条“概念与原理”：书中明确提出的原理、机制、因果、规律。'
        '必须能说清“概念—原理—适用条件”，只能用原文信息，不能补书外理论；没有就空。\n'
        '每条：{"concept":"相关概念","principle":"一句话原理",'
        '"explanation":"书中怎么解释","condition":"适用条件/范围或空",'
        '"seg":"段号","quote":"逐字原文"}。\n'
        '只输出 JSON：{"principles":[...]}\n\n原文：\n' + text
    )


def _item(key, values, note=''):
    no, name, tid, field = TAGS[key]
    return {'no': no, 'name': name, 'tag_id': tid, 'field': field,
            'value': values, 'status': 'needs_review' if values else 'not_found',
            'method': 'llm', 'confidence': 0.6 if values else None,
            'evidence': [e for x in values for e in (x.get('evidence') or [])],
            'note': note or ('AI 草稿，需人工确认；共 %d 条' % len(values) if values else '未抽到')}


def extract(code, max_chars=14000):
    rows = _rows(code)
    if not rows:
        return {'code': code, 'items': {}, 'note': '没有原文'}
    text, used = MK.build_input(code, max_chars)
    segmap = {r['id']: (r.get('文本') or '') for r in rows}
    model = llm.CFG.get('BOOKDISTILL_LLM_MODEL', '')

    META = re.compile(r'ISBN|定价|开本|印张|责任编辑|出版社|出版时间|主编|副主编|书名|印刷')
    facts, dropped = [], 0
    for x in (_json(_call(_p_facts(text), 3000).get('text')) or {}).get('facts') or []:
        ev = _fix_ev(x, segmap)
        fact = (x.get('fact') or '').strip()
        if ev and (META.search(fact) or META.search(ev.get('quote') or '')):
            dropped += 1
            continue
        if not ev or not fact or any(f['fact'] == fact for f in facts):
            dropped += 1
            continue
        facts.append({'fact': fact, 'value': (x.get('value') or '').strip(),
                      'unit': (x.get('unit') or '').strip(), 'time': (x.get('time') or '').strip(),
                      'condition': (x.get('condition') or '').strip(),
                      'category': x.get('category') or '其他', 'evidence': [ev]})

    skills = []
    for x in (_json(_call(_p_skills(text), 2500).get('text')) or {}).get('skills') or []:
        ev = _fix_ev(x, segmap)
        t = (x.get('text') or '').strip()
        if not ev or not t or not _skill_ok(t) or any(s['text'] == t for s in skills):
            dropped += 1
            continue
        skills.append({'type': x.get('type') or '规则', 'text': t,
                       'order': x.get('order') or 0,
                       'condition': (x.get('condition') or '').strip(),
                       'evidence': [ev]})

    bk = MK._book(code)
    proto = bk.get('原型') or ''
    titles = set()
    op = os.path.join(P.OUT, code, 'outline.jsonl')
    if os.path.exists(op):
        for l in io.open(op, encoding='utf-8'):
            if l.strip():
                titles.add(re.sub(r'\s+', '', json.loads(l).get('篇') or ''))
    concepts = []
    for x in (_json(_call(_p_concepts(text), 2500).get('text')) or {}).get('concepts') or []:
        ev = _fix_ev(x, segmap)
        c = (x.get('concept') or '').strip()
        if not ev or not c or len(c) > 12 or any(y['concept'] == c for y in concepts):
            dropped += 1
            continue
        if proto in ('P4', 'P5', 'P6', 'P7'):
            cn = re.sub(r'\s+', '', c)
            if cn == re.sub(r'\s+', '', bk.get('book') or '') or cn in titles:
                dropped += 1
                continue
        concepts.append({'concept': c, 'definition': (x.get('definition') or '').strip(),
                         'why_core': (x.get('why_core') or '').strip(), 'evidence': [ev]})

    principles = []
    for x in (_json(_call(_p_principles(text), 2500).get('text')) or {}).get('principles') or []:
        ev = _fix_ev(x, segmap)
        p = (x.get('principle') or '').strip()
        EXT = re.compile(r'存在主义|哲学|流派|象征|隐喻|体现了|作者意在|反映了')
        if not ev or not p or (EXT.search(p) and not EXT.search(ev.get('quote') or '')) \
                or any(y['principle'] == p for y in principles):
            dropped += 1
            continue
        principles.append({'concept': (x.get('concept') or '').strip(), 'principle': p,
                           'explanation': (x.get('explanation') or '').strip(),
                           'condition': (x.get('condition') or '').strip(), 'evidence': [ev]})

    items = {
        'facts': _item('facts', facts, '事实/数值候选，需人工核对单位和条件'),
        'skills': _item('skills', skills, '' if skills else '原文没有明确步骤/规则，未硬凑'),
        'concepts': _item('concepts', concepts, '概念候选，需人工确认是否核心、定义是否准确'),
        'principles': _item('principles', principles, '原理候选，需人工确认因果与适用条件'),
    }
    rec = {'code': code, 'book': MK._book(code).get('book') or '', 'pack': PACK,
           'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
           'model': model, 'input_chars': used,
           'items': items,
           'stats': {'dropped': dropped,
                     'counts': {k: len(v['value']) for k, v in items.items()}}}
    return rec


def blocked(code, msg):
    items = {k: _item(k, [], '上游模型内容审核拒绝，未生成；需换模型或人工') for k in TAGS}
    return {'code': code, 'book': MK._book(code).get('book') or '', 'pack': PACK,
            'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
            'model': llm.CFG.get('BOOKDISTILL_LLM_MODEL', ''), 'input_chars': 0,
            'items': items, 'stats': {'dropped': 0, 'counts': {k: 0 for k in TAGS}},
            'error': msg[:300]}


def write(rec):
    d = os.path.join(P.OUT, rec['code'])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'deep.json')
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(rec, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def main(argv):
    codes = []
    for a in argv[1:]:
        if a == '--all':
            codes = sorted([d for d in os.listdir(P.OUT)
                            if os.path.isdir(os.path.join(P.OUT, d))
                            and re.match(r'^[A-Z][A-Z0-9]{0,3}$', d)])
        elif a.startswith('-'):
            print('unknown option', a)
            return 2
        else:
            codes.append(a)
    if not codes:
        print(__doc__)
        return 2
    if not llm.ready():
        print('模型未配置')
        return 1
    for c in codes:
        try:
            rec = extract(c)
            write(rec)
            cnt = rec['stats']['counts']
            print('%s %-28s 事实 %2d / 技能 %2d / 概念 %2d / 原理 %2d  丢弃 %d'
                  % (c, rec['book'][:26], cnt['facts'], cnt['skills'],
                     cnt['concepts'], cnt['principles'], rec['stats']['dropped']))
        except Exception as e:
            rec = blocked(c, str(e))
            write(rec)
            print('%s 失败（已写空记录）：%s' % (c, e))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
