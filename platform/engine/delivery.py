# -*- coding: utf-8 -*-
"""43 项交付收口：把出版信息、页面结构、营销草稿、已有内容合并成一份台账。

范围（2026-11-13）：
  - 第 1 期 出版信息 19 项（publication.json）
  - 第 2 期 页面结构 12 项（page_roles.json）
  - 营销 7 项（marketing.json，草稿/待确认）
  - 已有内容 5 项（人物/地点/机构/章节大意/金句，来自现有产物）
  - 第 4 期其余 16 项放弃；第 3 期/理解类/上市时间不做

输出：
  platform/out/<code>/delivery.json       单本台账（43 项，含缺项状态）
  platform/out/delivery/annotations.jsonl 长表（只导出有值/待确认项）
  platform/out/delivery/books.jsonl       书目级汇总
  platform/out/delivery/manifest.json     清单与统计

原则：
  - 缺项只在内部统计，不进 JSONL/Excel 的交付列。
  - 每条有值都带证据；营销草稿标 needs_review，不冒充已确认。
"""
import io
import json
import os
import re
import sys

import paths as P
import publication as PUB
import pages as PG
import marketing as MK

PACK_P01 = {'id': 'publishing_structured_knowledge', 'version': '1.8.0'}
PACK_P02 = {'id': 'publishing_dataset_foundation', 'version': '1.7.0'}
PACK_P03 = {'id': 'publishing_marketing_insight', 'version': '1.5.0'}
PREFIX = {'publishing_structured_knowledge': 'P01',
          'publishing_dataset_foundation': 'P02',
          'publishing_marketing_insight': 'P03'}

PAGE_TAGS = {
    '封面': ('035', 'BT-PUBLAYOUT-7c44a514-1300-46a3-9aa2-e2abc5f6e7ab', 'cover'),
    '版权页': ('036', 'BT-PUBLAYOUT-a9a9f870-739f-4602-a4a2-32dbcf64bedf', 'copyright'),
    '书名页': ('037', 'BT-PUBLAYOUT-d9477ef3-8b0e-4eb5-9088-82cf9341c5a8', 'title_page'),
    '目录': ('038', 'BT-PUBLAYOUT-571c7df7-149c-49ed-89c2-e053d5598133', 'toc'),
    '前言': ('039', 'BT-PUBLAYOUT-6332b22a-789b-4214-b04f-4caf4e214058', 'preface'),
    '正文内容': ('040', 'BT-PUBLAYOUT-191c4516-1a96-4d7a-b449-dd41e766bd08', 'body'),
    '标题层级': ('041', 'BT-PUBLAYOUT-b027ed68-1a1d-42a0-8193-d67260f9ce55', 'headings'),
    '后记': ('042', 'BT-PUBLAYOUT-8f0b79d3-c9eb-4135-aad9-e8bb82bb7b2e', 'postscript'),
    '附录': ('043', 'BT-PUBLAYOUT-d8ca8d78-ef8d-4d5f-a731-752850753227', 'appendix'),
    '参考文献': ('044', 'BT-PUBLAYOUT-6e3797d4-4457-49ca-85be-93dc25299d71', 'references'),
    '索引': ('045', 'BT-PUBLAYOUT-f3213ff0-b619-4861-9146-744086a7812c', 'index'),
    '勘误表': ('046', 'BT-PUBLAYOUT-a9723464-833f-4909-8348-d55cbad7af1c', 'errata'),
}

DEEP_TAGS = {
    'facts': ('010', '事实与数值', 'BT-PUBKNOW-ad60cd11-1ed7-4e98-94b2-b1b49d79db28', '原文事实与数值'),
    'skills': ('012', '技能与规则', 'BT-PUBKNOW-7ace82ee-e14d-4bfd-a800-de13c6600b1d', '概念、原理、技能与规则'),
    'concepts': ('004', '核心概念', 'BT-PUBKNOW-755c5204-f054-42fb-910b-59bfeca382bc', '章节概念与核心意思'),
    'principles': ('011', '概念与原理', 'BT-PUBKNOW-ccec4b6a-06c0-4761-a4de-4660eeee2534', '概念、原理、技能与规则'),
}

P01_TAGS = {
    'people': ('001', '人物', 'BT-PUBKNOW-87eede57-bb41-483a-b174-5b6a881ce6ba', '原文人物、地点与机构'),
    'places': ('002', '地点', 'BT-PUBKNOW-b9468753-44a3-4000-9c9c-72271596d029', '原文人物、地点与机构'),
    'orgs': ('003', '机构', 'BT-PUBKNOW-7dec8360-0bf3-421c-89ae-1f659621961b', '原文人物、地点与机构'),
    'chapter_main_idea': ('005', '章节核心意思', 'BT-PUBKNOW-f5e67ecb-4527-4010-b98d-f5c5c78783a9', '章节概念与核心意思'),
    'quotes': ('017', '图书金句', 'BT-SEED-348aaff3-7b6e-4b74-8034-d24b783347d2', '图书金句'),
}

GROUP_P02 = {}
for no in range(1, 6):
    GROUP_P02['%03d' % no] = '出版事实信息'
for no in range(6, 18):
    GROUP_P02['%03d' % no] = '出版书目信息'
GROUP_P02['027'] = '分类与索引'
GROUP_P02['081'] = '语义交付基础标识'


def _rows(code, fn):
    p = os.path.join(P.OUT, code, fn)
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()] if os.path.exists(p) else []


def _read(code, fn):
    p = os.path.join(P.OUT, code, fn)
    return json.load(io.open(p, encoding='utf-8')) if os.path.exists(p) else {}


def _segmap(code):
    return {r['id']: (r.get('文本') or '') for r in _rows(code, 'segments.jsonl')}


def _ctx(segmap, seg, name, width=50):
    t = segmap.get(seg) or ''
    i = t.find(name)
    if i < 0:
        return ''
    a, b = max(0, i - width), min(len(t), i + len(name) + width)
    return t[a:b]


def _item(pack, no, name, group, field, value, status, method='',
          confidence=None, evidence=None, note='', tag_id=''):
    return {'pack': pack, 'pack_code': PREFIX.get(pack.get('id'), ''),
            'tag_key': '%s-%s' % (PREFIX.get(pack.get('id'), ''), no),
            'tag_id': tag_id, 'no': no, 'name': name, 'group': group,
            'field': field, 'value': value, 'status': status, 'method': method,
            'confidence': confidence, 'evidence': evidence or [], 'note': note}


def build(code):
    pub = _read(code, 'publication.json')
    pg = _read(code, 'page_roles.json')
    mk = _read(code, 'marketing.json')
    seg = _segmap(code)
    items = {}

    # 19 项出版信息
    for field, it in (pub.get('items') or {}).items():
        no = it.get('no') or ''
        ev = it.get('evidence') or []
        if not ev and it.get('method') == 'import':
            ev = [{'seg': '', 'quote': '', 'source': '书目库导入'}]
        items[field] = _item(PACK_P02, no, it.get('name') or '', GROUP_P02.get(no, '出版信息'),
                             field, it.get('value'), it.get('status') or 'not_found',
                             it.get('method') or '', it.get('confidence'),
                             ev, it.get('note') or '',
                             it.get('tag_id') or '')

    # 12 项页面结构
    for name, (no, tid, field) in PAGE_TAGS.items():
        r = next((x for x in (pg.get('roles') or []) if x.get('name') == name), None)
        if not r:
            items[field] = _item(PACK_P02, no, name, '出版物结构', field, None, 'not_found',
                                 'rule', None, [], '未运行页面结构或缺少版面数据', tid)
            continue
        if name == '标题层级':
            value = pg.get('headings') or []
            status = 'found' if value else r.get('status', 'not_found')
        else:
            value = {'spans': r.get('spans') or []}
            status = r.get('status') or 'not_found'
        items[field] = _item(PACK_P02, no, name, '出版物结构', field, value, status,
                             r.get('method') or 'rule', r.get('confidence'),
                             r.get('evidence') or [], r.get('note') or '', tid)

    # 7 项营销
    for field, it in (mk.get('items') or {}).items():
        no = it.get('no') or ''
        group = '营销关键词' if no == '001' else '营销与读者洞察'
        items[field] = _item(PACK_P03, no, it.get('name') or '', group, field,
                             it.get('value'), it.get('status') or 'not_found',
                             it.get('method') or 'llm', it.get('confidence'),
                             it.get('evidence') or [], it.get('note') or '',
                             it.get('tag_id') or '')

    # 5 项已有内容
    ppl = _rows(code, 'people.jsonl')
    ppl = sorted(ppl, key=lambda x: -int(x.get('频次') or 0))[:30]
    pv = []
    for p in ppl:
        nm = p.get('人物') or ''
        if not nm:
            continue
        pv.append({'name': nm, 'freq': p.get('频次'), 'seg': p.get('首现') or '',
                   'quote': _ctx(seg, p.get('首现') or '', nm)})
    items['people'] = _item(PACK_P01, '001', '人物', '原文人物、地点与机构', 'people',
                            pv, 'found' if pv else 'not_found', 'rule', 0.9,
                            [{'seg': x['seg'], 'quote': x['quote']} for x in pv[:5] if x['quote']],
                            '人物表按频次取前 30；完整表在 people.jsonl' if pv else '未抽出人物',
                            P01_TAGS['people'][2])

    ents = _rows(code, 'entities.jsonl')
    for cat, field, nm in (('place', 'places', '地点'), ('org', 'orgs', '机构')):
        seen, vals = set(), []
        for e in ents:
            if e.get('cat') != cat:
                continue
            n = e.get('name') or ''
            if not n or n in seen:
                continue
            seen.add(n)
            vals.append({'name': n, 'seg': e.get('seg') or '',
                         'quote': _ctx(seg, e.get('seg') or '', n)})
            if len(vals) >= 30:
                break
        items[field] = _item(PACK_P01, P01_TAGS[field][0], nm, '原文人物、地点与机构', field,
                             vals, 'found' if vals else 'not_found', 'rule', 0.85,
                             [{'seg': x['seg'], 'quote': x['quote']} for x in vals[:5] if x['quote']],
                             '实体表按出现顺序取前 30；完整表在 entities.jsonl' if vals else '未抽出%s' % nm,
                             P01_TAGS[field][2])

    und = _read(code, 'understanding.json')
    sums = und.get('summaries') or []
    sv = [{'篇': x.get('篇') or '', 'summary': x.get('summary') or '',
           'seg_from': x.get('seg_from') or '', 'seg_to': x.get('seg_to') or '',
           'quote': (seg.get(x.get('seg_from')) or '')[:80]} for x in sums]
    items['chapter_main_idea'] = _item(PACK_P01, '005', '章节核心意思', '章节概念与核心意思',
                                       'chapter_main_idea', sv, 'found' if sv else 'not_found',
                                       'llm', 0.7,
                                       [{'seg': x['seg_from'], 'quote': (seg.get(x['seg_from']) or '')[:80]} for x in sv[:3] if x.get('seg_from')],
                                       '来自篇摘要，未做第二遍复核' if sv else '未生成篇摘要',
                                       P01_TAGS['chapter_main_idea'][2])

    qs = (und.get('quotes') or [])[:20]
    qv = [{'quote': x.get('quote') or '', 'seg': x.get('seg') or '',
           'reason': x.get('reason') or ''} for x in qs if x.get('quote')]
    items['quotes'] = _item(PACK_P01, '017', '图书金句', '图书金句', 'quotes', qv,
                            'found' if qv else 'not_found', 'llm', 0.8,
                            [{'seg': x['seg'], 'quote': x['quote']} for x in qv[:5]],
                            '共 %d 条，交付取前 20 条' % len(und.get('quotes') or []) if qv else '未生成金句',
                            P01_TAGS['quotes'][2])

    deep = _read(code, 'deep.json')
    for key, (no, name, tid, group) in DEEP_TAGS.items():
        it = (deep.get('items') or {}).get(key)
        if it:
            items[key] = _item(PACK_P01, no, name, group, key, it.get('value'),
                               it.get('status') or 'not_found', it.get('method') or 'llm',
                               it.get('confidence'), it.get('evidence') or [],
                               it.get('note') or '', tid)
        else:
            items[key] = _item(PACK_P01, no, name, group, key, None, 'not_found',
                               'llm', None, [], '未运行理解层或缺少 deep.json', tid)

    assert len(items) == 47, '应有 47 项，实际 %d' % len(items)
    found = sum(1 for x in items.values() if x['status'] == 'found')
    review = sum(1 for x in items.values() if x['status'] == 'needs_review')
    missing = sum(1 for x in items.values() if x['status'] == 'not_found')
    return {'code': code, 'book': (pub.get('book') or ''), 'generated_at':
            __import__('datetime').datetime.now().isoformat(timespec='seconds'),
            'items': items,
            'counts': {'total': 47, 'found': found, 'needs_review': review,
                       'missing': missing, 'exported': found + review}}


def flatten(rec):
    """把 43 项展开成可交付长表；缺项不导出。"""
    rows = []
    for field, it in rec['items'].items():
        if it['status'] not in ('found', 'needs_review'):
            continue
        v = it['value']
        base = {'book_code': rec['code'], 'book': rec['book'], 'pack': it['pack'],
                'pack_code': it.get('pack_code'), 'tag_key': it.get('tag_key'),
                'tag_id': it['tag_id'], 'no': it['no'], 'name': it['name'],
                'group': it['group'], 'field': field, 'status': it['status'],
                'method': it['method'], 'confidence': it['confidence'],
                'note': it['note']}
        if field in ('people', 'places', 'orgs'):
            for x in v or []:
                r = dict(base, value=x.get('name'))
                r['evidence'] = [{'seg': x.get('seg'), 'quote': x.get('quote')}] if x.get('quote') else []
                rows.append(r)
        elif field == 'quotes':
            for x in v or []:
                rows.append(dict(base, value=x.get('quote'),
                                 evidence=[{'seg': x.get('seg'), 'quote': x.get('quote')}],
                                 note=(it['note'] + '；' + (x.get('reason') or '')).strip('；')))
        elif field == 'chapter_main_idea':
            for x in v or []:
                if not (x.get('summary') or '').strip():
                    continue
                rng = x.get('seg_from') or ''
                if x.get('seg_to') and x.get('seg_to') != x.get('seg_from'):
                    rng = '%s–%s' % (rng, x.get('seg_to'))
                rows.append(dict(base, value=x.get('summary'),
                                 evidence=[{'seg': x.get('seg_from'), 'quote': x.get('quote') or ''}],
                                 note='篇：%s；依据：%s 段摘要生成' % (x.get('篇'), rng or '该篇')))
        elif field == 'facts':
            for x in v or []:
                rows.append(dict(base, value=x.get('fact'),
                                 evidence=x.get('evidence') or [],
                                 note='值：%s %s；时间：%s；条件：%s；类别：%s' % (
                                     x.get('value') or '', x.get('unit') or '', x.get('time') or '',
                                     x.get('condition') or '', x.get('category') or '')))
        elif field == 'skills':
            for x in v or []:
                rows.append(dict(base, value=x.get('text'),
                                 evidence=x.get('evidence') or [],
                                 note='%s；顺序 %s；条件 %s' % (
                                     x.get('type') or '', x.get('order') or 0, x.get('condition') or '')))
        elif field == 'concepts':
            for x in v or []:
                rows.append(dict(base, value=x.get('concept'),
                                 evidence=x.get('evidence') or [],
                                 note='定义：%s；为什么核心：%s' % (
                                     x.get('definition') or '', x.get('why_core') or '')))
        elif field == 'principles':
            for x in v or []:
                rows.append(dict(base, value=x.get('principle'),
                                 evidence=x.get('evidence') or [],
                                 note='概念：%s；解释：%s；条件：%s' % (
                                     x.get('concept') or '', x.get('explanation') or '', x.get('condition') or '')))
        elif field == 'summary':
            rows.append(dict(base, value=(v or {}).get('text'), evidence=it.get('evidence') or []))
        elif field in ('keywords', 'audience', 'scenarios', 'gains', 'emotions', 'leads'):
            for x in v or []:
                ev = x.get('evidence') or []
                txt = x.get('keyword') if field == 'keywords' else x.get('text')
                note = x.get('reason') or ''
                if field == 'keywords':
                    pass
                else:
                    note = ('%s；%s' % (x.get('basis') or '', note)).strip('；')
                rows.append(dict(base, value=txt, evidence=ev, note=note))
        else:
            rows.append(dict(base, value=v, evidence=it.get('evidence') or []))
    return rows


def export_all(codes, outdir=None):
    outdir = outdir or os.path.join(P.OUT, 'delivery')
    os.makedirs(outdir, exist_ok=True)
    books, anns = [], []
    for c in codes:
        rec = build(c)
        books.append(rec)
        anns.extend(flatten(rec))
        d = os.path.join(P.OUT, c)
        with io.open(os.path.join(d, 'delivery.json'), 'w', encoding='utf-8') as fp:
            json.dump(rec, fp, ensure_ascii=False, indent=1)
    manifest = {
        'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        'scope': {'phase1': 19, 'phase2': 12, 'marketing': 7, 'existing': 5,
                  'understanding': 4, 'total': 47},
        'packs': [PACK_P01, PACK_P02, PACK_P03],
        'books': [{'code': b['code'], 'book': b['book'], 'counts': b['counts']} for b in books],
        'annotations': len(anns),
    }
    with io.open(os.path.join(outdir, 'annotations.jsonl'), 'w', encoding='utf-8') as fp:
        for a in anns:
            fp.write(json.dumps(a, ensure_ascii=False) + '\n')
    with io.open(os.path.join(outdir, 'books.jsonl'), 'w', encoding='utf-8') as fp:
        for b in books:
            fp.write(json.dumps({'code': b['code'], 'book': b['book'],
                                 'counts': b['counts'],
                                 'items': {k: {'no': v['no'], 'name': v['name'],
                                               'status': v['status']}
                                           for k, v in b['items'].items()}},
                                ensure_ascii=False) + '\n')
    with io.open(os.path.join(outdir, 'manifest.json'), 'w', encoding='utf-8') as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=1)
    return outdir, books, anns, manifest


def main(argv):
    codes = []
    for a in argv[1:]:
        if a == '--all':
            codes = sorted([d for d in os.listdir(P.OUT)
                            if os.path.isdir(os.path.join(P.OUT, d)) and re.match(r'^[A-Z][A-Z0-9]{0,3}$', d)])
        elif a.startswith('-'):
            print('unknown option', a)
            return 2
        else:
            codes.append(a)
    if not codes:
        print(__doc__)
        return 2
    outdir, books, anns, manifest = export_all(codes)
    print('输出目录：%s' % outdir)
    for b in books:
        print('%s %-28s %d 项：有值 %2d / 待确认 %d / 缺 %2d -> 导出 %d'
              % (b['code'], b['book'][:26], b['counts']['total'],
                 b['counts']['found'], b['counts']['needs_review'],
                 b['counts']['missing'], b['counts']['exported']))
    print('长表 %d 行' % len(anns))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
