# -*- coding: utf-8 -*-
"""专名按书型的审计：必备抽不到=缺陷，不需要却抽到=噪音。

规则表在 platform/config/entity_requirements.json。
只读 out/<code>/entities.jsonl 与 book.json，不改任何产物。

用法：
    python3 entity_audit.py            # 全库
    python3 entity_audit.py B56 B64    # 指定几本
"""
import collections
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P          # noqa: E402

OUT = P.OUT
REQ_FILE = os.path.join(P.PLATFORM, 'config', 'entity_requirements.json')

# 与 store.get_entities 一致：分类阶元按后缀改判，方位词按后缀改判
_TAXON_RE = re.compile(r'(科|属|目|纲|门|族)$')
_PLACE_TAIL = re.compile(r'(洲|南部|北部|东部|西部|中部|地区|一带)$')


def load_req():
    with io.open(REQ_FILE, encoding='utf-8') as fp:
        return json.load(fp)


def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with io.open(path, encoding='utf-8') as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def read_json(path, default=None):
    try:
        with io.open(path, encoding='utf-8') as fp:
            return json.load(fp)
    except Exception:
        return default


def unique_by_cat(code):
    """返回 {类: 去重名数}，类别规则与页面一致。"""
    uniq = collections.defaultdict(set)
    for r in read_jsonl(os.path.join(OUT, code, 'entities.jsonl')):
        name, cat = r.get('name'), r.get('cat')
        if not name or not cat or cat == 'other':
            continue
        if cat in ('org', 'plant', 'animal') and len(name) <= 8 and _TAXON_RE.search(name):
            cat = 'taxon'
        if cat == 'org' and _PLACE_TAIL.search(name):
            cat = 'place'
        uniq[cat].add(name)
    # 人物另有 people.jsonl
    people = {x.get('人物') or x.get('name') for x in read_jsonl(os.path.join(OUT, code, 'people.jsonl'))}
    people = {p for p in people if p}
    if people:
        uniq['person'] |= people
    uniq['org_group'] = uniq.get('org_group') or set()   # 组织：抽取器尚未产出
    return {k: len(v) for k, v in uniq.items()}


def audit(code, req):
    book = read_json(os.path.join(OUT, code, 'book.json'), {}) or {}
    proto = book.get('原型') or ''
    spec = req['types'].get(proto)
    if not spec:
        return {'code': code, 'proto': proto, 'error': '未知书型'}
    got = unique_by_cat(code)
    # 必备缺分两种：抽取器还没做（未实现），做了但抽到 0（要人看是不是这本真没有）
    missing = [c for c in spec['required'] if got.get(c, 0) == 0]
    todo = [c for c in missing if c in req.get('not_implemented', [])]
    empty = [c for c in missing if c not in todo]
    noise = [(c, got.get(c, 0)) for c in spec['noise'] if got.get(c, 0) > 0]
    return {
        'code': code,
        'book': book.get('book') or code,
        'proto': proto,
        'proto_name': spec['name'],
        'required': spec['required'],
        'missing': missing,
        'missing_not_implemented': todo,
        'missing_empty': empty,
        'noise': noise,
        'counts': {c: got.get(c, 0) for c in req['categories']},
    }


def main(argv):
    req = load_req()
    codes = argv or [d for d in sorted(os.listdir(OUT))
                     if os.path.isdir(os.path.join(OUT, d)) and not d.startswith('.')
                     and os.path.exists(os.path.join(OUT, d, 'entities.jsonl'))]
    rows = [audit(c, req) for c in codes]
    rows = [r for r in rows if r.get('proto_name')]

    print('%-6s %-10s %-8s %s' % ('书', '书型', '缺陷', '噪音'))
    print('-' * 78)
    for r in rows:
        miss = '、'.join(req['categories'][c] + ('(未做)' if c in r['missing_not_implemented'] else '')
                         for c in r['missing']) or '—'
        noise = '、'.join('%s%d' % (req['categories'][c], n) for c, n in r['noise']) or '—'
        print('%-6s %-10s %-8s %s' % (r['code'], r['proto_name'], miss, noise))

    print('\n缺陷分两种：')
    for r in rows:
        if r['missing_not_implemented']:
            print('  %s %s：抽取器未做 —— %s' % (
                r['code'], r['proto_name'],
                '、'.join(req['categories'][c] for c in r['missing_not_implemented'])))
    for r in rows:
        if r['missing_empty']:
            print('  %s %s：抽了但为空，需人确认是否真没有 —— %s' % (
                r['code'], r['proto_name'],
                '、'.join(req['categories'][c] for c in r['missing_empty'])))

    report = os.path.join(P.PLATFORM, 'entity_audit.json')
    with io.open(report, 'w', encoding='utf-8') as fp:
        json.dump({'updated_at': req['updated_at'], 'rows': rows}, fp, ensure_ascii=False, indent=1)
    print('\n报告：%s' % report)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
