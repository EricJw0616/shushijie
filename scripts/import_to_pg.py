# -*- coding: utf-8 -*-
"""把现有文件资产导入 PostgreSQL。可重复执行（UPSERT）。

用法：
  python3 scripts/import_to_pg.py --dry-run
  DATABASE_URL=... python3 scripts/import_to_pg.py
  python3 scripts/import_to_pg.py --book B58
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'platform' / 'out'
DATA = ROOT / 'app' / 'data'
KG = DATA / 'kg'


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception:
        return default


def load_jsonl(p):
    rows = []
    try:
        with open(p, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def book_rows():
    rows = load_json(OUT / 'books.json', []) or []
    seen = {}
    for b in rows:
        code = b.get('code')
        if not code:
            continue
        bj = load_json(OUT / code / 'book.json', {}) or {}
        cip = bj.get('CIP') or {}
        title = bj.get('book') or b.get('book') or code
        seen[code] = {
            'code': code,
            'title': title,
            'author': cip.get('作者') or b.get('author') or '',
            'publisher': cip.get('出版社') or b.get('publisher') or '',
            'prototype': bj.get('原型') or b.get('prototype') or '',
            'prototype_name': bj.get('原型名') or b.get('prototypeName') or '',
            'status': b.get('status') or '',
            'form': bj.get('form') or '',
            'meta': bj or b,
        }
    # out 里存在但汇总 books.json 漏掉的书也补上
    for d in sorted(OUT.iterdir()) if OUT.exists() else []:
        if not d.is_dir() or d.name.startswith('.'):
            continue
        bj = load_json(d / 'book.json', None)
        if not bj or d.name in seen:
            continue
        cip = bj.get('CIP') or {}
        seen[d.name] = {
            'code': d.name, 'title': bj.get('book') or d.name,
            'author': cip.get('作者') or '', 'publisher': cip.get('出版社') or '',
            'prototype': bj.get('原型') or '', 'prototype_name': bj.get('原型名') or '',
            'status': '', 'form': bj.get('form') or '', 'meta': bj,
        }
    return list(seen.values())


def collect(book=None):
    books = [b for b in book_rows() if not book or b['code'] == book]
    codes = {b['code'] for b in books}
    jobs, operations = [], []
    for p in sorted((DATA / 'jobs').glob('*.json')) if (DATA / 'jobs').exists() else []:
        j = load_json(p, None)
        if not j:
            continue
        code = j.get('book_code') or ''
        if book and code != book:
            continue
        jobs.append({
            'id': j.get('id') or p.stem, 'kind': j.get('kind') or 'upload',
            'status': j.get('status') or '', 'progress': int(j.get('progress') or 0),
            'book_code': code if code in codes else None,
            'title': j.get('title') or '', 'steps': j.get('steps') or [],
            'result': j.get('result'), 'error': j.get('error') or '',
            'log': j.get('log') or '', 'created_at': j.get('created_at') or None,
            'updated_at': j.get('finished_at') or j.get('started_at') or j.get('created_at') or None,
        })
    for a in load_jsonl(DATA / 'operations.jsonl'):
        code = a.get('code') or a.get('book_code') or ''
        if book and code != book:
            continue
        operations.append({
            'book_code': code, 'action': a.get('action') or a.get('op') or a.get('event') or 'op',
            'payload': a, 'created_at': a.get('time') or a.get('created_at') or None,
        })

    segments, cards, people, entities = [], [], [], []
    kg_nodes, kg_edges = [], []
    for b in books:
        code = b['code']
        for s in load_jsonl(OUT / code / 'segments.jsonl'):
            segments.append({
                'id': s.get('id') or '', 'book_code': code,
                'seq': int(s.get('段') or s.get('seq') or 0), 'chapter': s.get('篇') or '',
                'text': s.get('文本') or '', 'anchor': s.get('id') or '',
                'meta': s, 'search_text': (s.get('篇') or '') + '\n' + (s.get('文本') or ''),
            })
        for c in load_jsonl(OUT / code / 'cards.jsonl'):
            fields = c.get('字段') or {}
            cards.append({
                'id': c.get('id') or '', 'book_code': code, 'type': c.get('类型') or '',
                'fields': fields, 'raw': c.get('原文') or '', 'anchor': c.get('锚点') or '',
                'status': c.get('状态') or '',
                'search_text': (c.get('类型') or '') + '\n' + json.dumps(fields, ensure_ascii=False) + '\n' + (c.get('原文') or ''),
            })
        for p in load_jsonl(OUT / code / 'people.jsonl'):
            name = p.get('人物') or ''
            if not name:
                continue
            people.append({
                'id': code + ':' + name, 'book_code': code, 'name': name,
                'frequency': int(p.get('频次') or 0), 'evidence': p.get('证据') or '',
                'anchor': p.get('锚点') or '', 'meta': p,
            })
        for e in load_jsonl(OUT / code / 'entities.jsonl'):
            name = str(e.get('name_s') or e.get('name') or e.get('名称') or '')
            if not name:
                continue
            seg = str(e.get('seg') or '')
            eid = code + ':' + seg + ':' + name
            entities.append({
                'id': eid, 'book_code': code,
                'type': e.get('cat') or e.get('type') or e.get('类型') or '',
                'label': name, 'meta': e,
            })
        g = load_json(KG / (code + '.json'), None)
        if g:
            code_of = {}
            for n in g.get('nodes') or []:
                nid = n.get('id') or ''
                if not nid:
                    continue
                code_of[nid] = n.get('code') or code
                text = ' '.join(str(n.get(k) or '') for k in ('label', 'role', 'quote', 'raw', 'type'))
                text += ' ' + ' '.join(n.get('disciplines') or [])
                kg_nodes.append({
                    'id': nid, 'book_code': n.get('code') or code,
                    'node_key': nid, 'type': n.get('type') or '',
                    'label': n.get('label') or nid, 'payload': n, 'search_text': text,
                })
            for i, e in enumerate(g.get('edges') or []):
                eid = e.get('id') or ('%s|%s|%s|%d' % (e.get('source'), e.get('target'), e.get('rel'), i))
                ev = e.get('evidence') or {}
                kg_edges.append({
                    'id': eid,
                    'book_code': code_of.get(e.get('source')) or code_of.get(e.get('target')) or code,
                    'source_id': e.get('source') or '', 'target_id': e.get('target') or '',
                    'rel': e.get('rel') or '', 'kind': e.get('kind') or '',
                    'confidence': e.get('confidence') or '',
                    'evidence_anchor': ev.get('anchor') or '',
                    'evidence_text': ev.get('text') or '',
                    'payload': e,
                })
    return {
        'books': books, 'jobs': jobs, 'operations': operations,
        'segments': segments, 'cards': cards, 'people': people, 'entities': entities,
        'kg_nodes': kg_nodes, 'kg_edges': kg_edges,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--book', default='')
    args = ap.parse_args()
    plan = collect(args.book or None)
    for k, v in plan.items():
        print('%-12s %d' % (k, len(v)))
    if args.dry_run:
        for n in plan['kg_nodes'][:3]:
            print('node sample:', n['id'], n['type'], n['label'])
        return 0

    import psycopg
    from psycopg.types.json import Jsonb

    url = os.environ.get('DATABASE_URL', 'postgresql://book:book@127.0.0.1:5432/bookworld')
    with psycopg.connect(url) as conn:
        with conn.transaction():
            for b in plan['books']:
                conn.execute("""INSERT INTO books(code,title,author,publisher,prototype,prototype_name,status,form,meta)
                    VALUES (%(code)s,%(title)s,%(author)s,%(publisher)s,%(prototype)s,%(prototype_name)s,%(status)s,%(form)s,%(meta)s)
                    ON CONFLICT (code) DO UPDATE SET title=EXCLUDED.title,author=EXCLUDED.author,publisher=EXCLUDED.publisher,
                      prototype=EXCLUDED.prototype,prototype_name=EXCLUDED.prototype_name,status=EXCLUDED.status,
                      form=EXCLUDED.form,meta=EXCLUDED.meta,updated_at=now()""",
                    {**b, 'meta': Jsonb(b['meta'])})
            for j in plan['jobs']:
                conn.execute("""INSERT INTO jobs(id,kind,status,progress,book_code,title,steps,result,error,log,created_at,updated_at)
                    VALUES (%(id)s,%(kind)s,%(status)s,%(progress)s,%(book_code)s,%(title)s,%(steps)s,%(result)s,%(error)s,%(log)s,coalesce(%(created_at)s,now()),coalesce(%(updated_at)s,now()))
                    ON CONFLICT (id) DO UPDATE SET status=EXCLUDED.status,progress=EXCLUDED.progress,steps=EXCLUDED.steps,
                      result=EXCLUDED.result,error=EXCLUDED.error,log=EXCLUDED.log,updated_at=EXCLUDED.updated_at""",
                    {**j, 'steps': Jsonb(j['steps']), 'result': Jsonb(j['result']) if j['result'] is not None else None})
            for s in plan['segments']:
                conn.execute("""INSERT INTO segments(id,book_code,seq,chapter,text,anchor,meta,search_text)
                    VALUES (%(id)s,%(book_code)s,%(seq)s,%(chapter)s,%(text)s,%(anchor)s,%(meta)s,%(search_text)s)
                    ON CONFLICT (id) DO UPDATE SET seq=EXCLUDED.seq,chapter=EXCLUDED.chapter,text=EXCLUDED.text,
                      anchor=EXCLUDED.anchor,meta=EXCLUDED.meta,search_text=EXCLUDED.search_text""",
                    {**s, 'meta': Jsonb(s['meta'])})
            for c in plan['cards']:
                conn.execute("""INSERT INTO cards(id,book_code,type,fields,raw,anchor,status,search_text)
                    VALUES (%(id)s,%(book_code)s,%(type)s,%(fields)s,%(raw)s,%(anchor)s,%(status)s,%(search_text)s)
                    ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,fields=EXCLUDED.fields,raw=EXCLUDED.raw,
                      anchor=EXCLUDED.anchor,status=EXCLUDED.status,search_text=EXCLUDED.search_text""",
                    {**c, 'fields': Jsonb(c['fields'])})
            for p in plan['people']:
                conn.execute("""INSERT INTO people(id,book_code,name,frequency,evidence,anchor,meta)
                    VALUES (%(id)s,%(book_code)s,%(name)s,%(frequency)s,%(evidence)s,%(anchor)s,%(meta)s)
                    ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name,frequency=EXCLUDED.frequency,
                      evidence=EXCLUDED.evidence,anchor=EXCLUDED.anchor,meta=EXCLUDED.meta""",
                    {**p, 'meta': Jsonb(p['meta'])})
            for e in plan['entities']:
                conn.execute("""INSERT INTO entities(id,book_code,type,label,meta)
                    VALUES (%(id)s,%(book_code)s,%(type)s,%(label)s,%(meta)s)
                    ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,label=EXCLUDED.label,meta=EXCLUDED.meta""",
                    {**e, 'meta': Jsonb(e['meta'])})
            for n in plan['kg_nodes']:
                conn.execute("""INSERT INTO kg_nodes(id,book_code,node_key,type,label,payload,search_text)
                    VALUES (%(id)s,%(book_code)s,%(node_key)s,%(type)s,%(label)s,%(payload)s,%(search_text)s)
                    ON CONFLICT (id) DO UPDATE SET type=EXCLUDED.type,label=EXCLUDED.label,
                      payload=EXCLUDED.payload,search_text=EXCLUDED.search_text""",
                    {**n, 'payload': Jsonb(n['payload'])})
            for e in plan['kg_edges']:
                conn.execute("""INSERT INTO kg_edges(id,book_code,source_id,target_id,rel,kind,confidence,evidence_anchor,evidence_text,payload)
                    VALUES (%(id)s,%(book_code)s,%(source_id)s,%(target_id)s,%(rel)s,%(kind)s,%(confidence)s,%(evidence_anchor)s,%(evidence_text)s,%(payload)s)
                    ON CONFLICT (id) DO UPDATE SET rel=EXCLUDED.rel,kind=EXCLUDED.kind,confidence=EXCLUDED.confidence,
                      evidence_anchor=EXCLUDED.evidence_anchor,evidence_text=EXCLUDED.evidence_text,payload=EXCLUDED.payload""",
                    {**e, 'payload': Jsonb(e['payload'])})
            for o in plan['operations']:
                conn.execute("""INSERT INTO operations(book_code,action,payload,created_at)
                    VALUES (%(book_code)s,%(action)s,%(payload)s,coalesce(%(created_at)s,now()))""",
                    {**o, 'payload': Jsonb(o['payload'])})
    print('imported')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
