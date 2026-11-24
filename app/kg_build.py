# -*- coding: utf-8 -*-
"""从平台资产派生「知识图谱」数据（第一版：B59 国之脊梁）。

设计原则：
  - 节点复用资产（人物条目 / 身份字段 / 籍贯字段），不另建一套数据；
  - 每条边带原文锚点与证据文本；
  - 图谱是派生资产，可重跑，不改原资产。

产物：app/data/kg/<code>.json
用法：python3 app/kg_build.py B59
"""
import datetime
import hashlib
import json
import os
import re
import sys
from urllib.parse import quote
from collections import Counter
import kg_curated

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(APP_DIR)
OUT = os.path.join(ROOT, 'platform', 'out')
KGDIR = os.path.join(APP_DIR, 'data', 'kg')
REQFILE = os.path.join(KGDIR, 'requests.json')
MAX_VIEW_BOOKS = 100
VIEW_CODE_RE = re.compile(r'[A-Za-z0-9_-]{1,24}')

# Only semantic / classification relationships are collectible. Structural
# navigation edges stay visible in the graph without becoming writing material.
MATERIAL_RELATIONS = frozenset(('学科', '籍贯', '位于', '关联', '出现于', '属于',
                                '驯养', '照顾', '咬', '命令', '遇见', '告别'))
RELATION_BASIS_LABELS = {'explicit': '原文明示', 'field': '按字段整理',
                         'interpretation': '待核对解释', 'structure': '目录结构'}


def _curated_fact(code, edge):
    return next((fact for fact in kg_curated.FACTS.get(code, ()) if fact['id'] == edge.get('id')), None)


def _fact_sources(fact):
    return [fact, *fact.get('support_evidence', ())]


def _fact_source_valid(fact, segments):
    for item in _fact_sources(fact):
        segment = segments.get(item['anchor'])
        if not segment or segment.get('篇') != item['chapter']:
            return False
        text = segment.get('文本')
        if not isinstance(text, str) or not item['quote'] or item['quote'] not in text:
            return False
        if any(term not in text for term in item.get('required', ())):
            return False
        if any(segment.get(key) for key in ('source_structure_suspect', 'source_layout_suspect', 'source_issue')):
            return False
    return True


def _fact_edge_valid(code, fact, edge, nodes, segments):
    if not _fact_source_valid(fact, segments):
        return False
    if any(edge.get(key) != fact[key] for key in ('source', 'target', 'rel')):
        return False
    if (edge.get('kind') != 'relation' or edge.get('note') != fact['quote'] or
            (edge.get('evidence') or {}).get('anchor') != fact['anchor']):
        return False
    return all(nodes.get(fact[key], {}).get('label') == kg_curated.NODES[code][fact[key]]['label']
               for key in ('source', 'target'))


def relation_basis(code, edge, nodes=None, segments=None):
    """Describe the source of a relation, independently of material approval."""
    fact = _curated_fact(code, edge)
    if fact and nodes is not None and segments is not None and _fact_edge_valid(code, fact, edge, nodes, segments):
        basis = fact.get('basis', 'explicit')
    elif edge.get('kind') == 'in_book' or edge.get('rel') in ('包含', '收录', '下一页'):
        basis = 'structure'
    elif edge.get('rel') in ('学科', '籍贯', '属于', '出现于'):
        basis = 'field'
    else:
        basis = 'interpretation'
    return {'relation_basis': basis, 'relation_basis_label': RELATION_BASIS_LABELS[basis]}


def _with_curated_facts(code, graph, source_rows=None):
    """Rebuild the small read-time overlay from current evidence, never on disk."""
    facts = kg_curated.FACTS.get(code)
    if not graph or not facts:
        return graph
    specs = kg_curated.NODES[code]
    owned_nodes = {nid for nid, spec in specs.items() if not spec.get('existing')}
    owned_edges = {fact['id'] for fact in facts}
    nodes = [node for node in graph.get('nodes', ())
             if node['id'] not in owned_nodes and not node.get('curated_node')]
    edges = [edge for edge in graph.get('edges', ())
             if edge.get('id') not in owned_edges and not edge.get('curated_fact')]
    by_node = {node['id']: node for node in nodes}
    source_rows = source_rows if source_rows is not None else load_jsonl(os.path.join(OUT, code, 'segments.jsonl'))
    anchor_counts = Counter(segment.get('id') for segment in source_rows)
    segments = {segment['id']: segment for segment in source_rows if anchor_counts[segment.get('id')] == 1}
    added = 0
    for fact in facts:
        if not _fact_source_valid(fact, segments):
            continue
        endpoints = (fact['source'], fact['target'])
        if any((specs[nid].get('existing') and nid not in by_node) or
               (nid in by_node and by_node[nid].get('label') != specs[nid]['label']) for nid in endpoints):
            continue
        anchors = [{'id': item['anchor'], 'label': segment_label(segments[item['anchor']])}
                   for item in _fact_sources(fact)]
        for nid in endpoints:
            spec = specs[nid]
            if nid not in by_node:
                kind = {'人物': 'person', '事件': 'event', '工程': 'project', '概念': 'concept', '案例': 'case'}[spec['type']]
                node = {'id': nid, 'label': spec['label'], 'kind': kind, 'type': spec['type'],
                        'chapter': fact['chapter'], 'role': spec.get('desc') or '书中记载的' + spec['type'],
                        'desc': spec.get('desc') or '', 'raw': fact['quote'], 'quote': fact['quote'],
                        'anchors': [], 'degree': 0, 'curated_node': True}
                nodes.append(node)
                by_node[nid] = node
            if by_node[nid].get('curated_node'):
                known = {anchor['id'] for anchor in by_node[nid]['anchors']}
                for anchor in anchors:
                    if anchor['id'] not in known:
                        by_node[nid]['anchors'].append(anchor)
                        known.add(anchor['id'])
        edges.append({'id': fact['id'], 'source': fact['source'], 'target': fact['target'],
                      'kind': 'relation', 'rel': fact['rel'], 'confidence': 'A', 'note': fact['quote'],
                      'curated_fact': True,
                      'evidence': {'anchor': fact['anchor'], 'label': segment_label(segments[fact['anchor']]),
                                   'text': fact['quote'],
                                   'excerpts': [{'anchor': item['anchor'], 'quote': item['quote']}
                                                for item in _fact_sources(fact)]}})
        added += 1
    degrees = Counter(endpoint for edge in edges for endpoint in (edge['source'], edge['target']))
    for node in nodes:
        if node.get('curated_node'):
            node['degree'] = degrees[node['id']]
    graph['nodes'], graph['edges'] = nodes, edges
    meta = graph.setdefault('meta', {})
    counts = meta.setdefault('counts', {})
    counts.update(nodes=len(nodes), edges=len(edges), relationEdges=sum(e.get('kind') == 'relation' for e in edges),
                  event=sum(n.get('type') == '事件' for n in nodes), project=sum(n.get('type') == '工程' for n in nodes),
                  concept=sum(n.get('type') == '概念' for n in nodes), case=sum(n.get('type') == '案例' for n in nodes))
    base_form = '人物 · 学科 · 籍贯' if code == 'B59' else '篇章 · 条目'
    extras = [typ for typ in ('事件', '工程', '概念', '案例') if any(n.get('type') == typ for n in nodes)]
    meta['form'] = ' · '.join([base_form, *extras])
    meta['catalogReason'] = '%d 个节点 / %d 条边；其中 %d 条关系带逐字核对的原文摘录' % (len(nodes), len(edges), added)
    meta['curatedRelations'] = added
    return graph


def relation_asset_id(code, edge_id):
    token = hashlib.sha256(json.dumps(edge_id, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()[:20]
    return '%s:relation:%s' % (code, token)


def relation_material(code, edge, nodes, segments):
    """Resolve graph facts against current text; this does not approve semantics."""
    fact = _curated_fact(code, edge)
    if fact:
        if not _fact_edge_valid(code, fact, edge, nodes, segments):
            return None, '关系的原文摘录、对象或章节已变化，请重新核对依据'
    elif edge.get('rel') not in MATERIAL_RELATIONS or edge.get('kind') == 'in_book':
        return None, '这条边用于目录或阅读导航，暂不作为关系材料收集'
    source, target = nodes.get(edge.get('source')), nodes.get(edge.get('target'))
    if not edge.get('id') or not source or not target or not source.get('label') or not target.get('label'):
        return None, '关系对象或稳定标识不完整，暂不能收集'
    anchor = (edge.get('evidence') or {}).get('anchor')
    segment = segments.get(anchor)
    if not segment or not str(segment.get('文本') or '').strip():
        return None, '原文锚点或正文已失效，暂不能收集'
    if any(segment.get(key) for key in ('source_structure_suspect', 'source_layout_suspect', 'source_issue')):
        return None, '这处原文的版面或章节需要核对，暂不能收集'
    if code == 'B58' and edge.get('id') == 'E-小王子-狐狸-驯养' and (
            anchor != 'B58-00-P92' or '小王子驯化了狐狸' not in segment['文本']):
        return None, '当前原文尚不能支持这条已发生的关系，请重新核对依据'
    title = '%s —%s→ %s' % (source['label'], edge['rel'], target['label'])
    paragraph = segment['文本']
    # Use a curated excerpt only when it appears verbatim in the source.
    excerpt = str(edge.get('note') or '') if edge.get('kind') == 'relation' else ''
    evidence = [{'anchor': segment['id'], 'quote': excerpt if excerpt and excerpt in paragraph else paragraph}]
    if fact:
        evidence = [{'anchor': item['anchor'], 'quote': item['quote']} for item in _fact_sources(fact)]
    origin = {'学科': '按书中身份归类', '籍贯': '据书中籍贯整理', '属于': '据图鉴分类整理'}.get(edge['rel'], '据书中内容整理')
    relation = {'edge_id': edge['id'], 'source_id': code + ':' + source['id'],
                'source_label': source['label'], 'predicate': edge['rel'],
                'target_id': code + ':' + target['id'], 'target_label': target['label'],
                'source_route': '#/kglab/' + quote(code, safe='') + '/' + quote(source['id'], safe=''),
                'graph_route': '#/kg/' + quote(code, safe='') + '/' + quote(source['id'], safe=''),
                'title': title, 'body': title}
    return {'relation': relation, 'evidence': evidence, 'origin': origin}, ''

# 学科大类：把「身份」里的细粒度头衔归并成可读的簇。
# 顺序有意义：先匹配更具体的词（生物化学→生命，物理化学→化学，物理冶金→工程）。
RULES = [
    ('生命', ['生物', '植物', '微生物', '病理', '病毒', '遗传', '生理']),
    ('化学', ['化学', '化工', '燃料', '无机']),
    ('地学', ['地质', '地理', '气象', '环境', '海洋', '大气']),
    ('数学', ['数学']),
    ('工程', ['桥梁', '航天', '系统工程', '电子', '导弹', '火箭', '无线电',
              '自动控制', '材料', '冶金', '半导体', '信息', '核工程']),
    ('物理', ['物理', '力学', '核物理']),
    ('考古', ['考古', '古人类', '石器']),
    ('医学', ['医学', '妇产', '临床', '药学']),
    ('社科', ['社会活动', '教育', '哲学', '经济']),
]
DISC_ORDER = ['物理', '化学', '地学', '生命', '数学', '工程', '考古', '医学', '社科', '其他']
DISC_DESC = {
    '物理': '物理学家、力学家、核物理学家',
    '化学': '化学家、化工与燃料专家',
    '地学': '地质、地理、气象、环境',
    '生命': '生物、植物、微生物、病理',
    '数学': '数学家、应用数学',
    '工程': '桥梁、航天、电子、材料、自动控制',
    '考古': '古人类、旧石器考古',
    '医学': '妇产、临床医学',
    '社科': '社会活动、教育',
    '其他': '未归入上述大类的身份',
}


def load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def clean_place(raw):
    """籍贯：去掉括号补充，保留主地名；同时抽出「生于 X」。"""
    raw = (raw or '').strip()
    born = ''
    m = re.search(r'生于([^）)]+)', raw)
    if m:
        born = m.group(1).strip()
    place = re.split(r'[（(]', raw)[0].strip()
    return place, born


def map_disciplines(identity):
    """把身份拆成学科大类；返回 [(大类, 命中词)]，保持出现顺序。"""
    hits = []
    seen = set()
    for term in re.split(r'[、，,；;/]', identity or ''):
        term = term.strip()
        if not term or '院士' in term or term in ('教授', '研究员', '高级工程师'):
            continue
        for disc, kws in RULES:
            if any(k in term for k in kws):
                if disc not in seen:
                    seen.add(disc)
                    hits.append((disc, term))
                break
    if not hits:
        hits = [('其他', '身份未归类')]
    return hits


def segment_label(seg):
    if not seg:
        return ''
    return '%s 第%s段' % (seg.get('篇') or '', seg.get('段') or '')


def build_book(code):
    book = read_json(os.path.join(OUT, code, 'book.json'))
    if not book:
        raise SystemExit('没有找到 %s 的 book.json' % code)
    cards = load_jsonl(os.path.join(OUT, code, 'cards.jsonl'))
    segs = load_jsonl(os.path.join(OUT, code, 'segments.jsonl'))
    people = load_jsonl(os.path.join(OUT, code, 'people.jsonl'))
    seg_by_id = {s['id']: s for s in segs}

    persons = [c for c in cards if c.get('类型') == '人物条目']
    if not persons:
        raise SystemExit('%s 没有人物条目，暂不支持建图' % code)

    nodes, edges = [], []
    disco_used = {}
    place_used = {}

    for c in persons:
        f = c.get('字段') or {}
        name = (f.get('姓名') or '').strip()
        if not name:
            continue
        pid = 'P-' + name
        raw_place = (f.get('籍贯') or '').strip()
        place, born = clean_place(raw_place)
        identity = (f.get('身份') or '').strip()
        disc_hits = map_disciplines(identity)
        anchor = c.get('锚点') or ''
        seg = seg_by_id.get(anchor)
        chapter = (seg or {}).get('篇') or ''
        raw = (c.get('原文') or '').strip()
        raw = re.sub(r'^生卒年：—?', '', raw).replace('\\', '\n')
        nodes.append({
            'id': pid, 'label': name, 'kind': 'person', 'chapter': chapter,
            'role': identity, 'place': place, 'birthplace': born,
            'achievement': (f.get('主要成就') or '').strip(),
            'quote': (f.get('院士语录') or '').strip(),
            'raw': raw,
            'anchors': [{'id': anchor, 'label': segment_label(seg) if seg else anchor}] if anchor else [],
            'disciplines': [d for d, _ in disc_hits],
            'degree': 0,
        })
        for disc, term in disc_hits:
            did = 'D-' + disc
            disco_used.setdefault(did, []).append(name)
            edges.append({
                'id': 'E-%s-%s' % (name, disc), 'kind': 'discipline',
                'source': pid, 'target': did, 'rel': '学科',
                'confidence': 'A',
                'primary': disc == disc_hits[0][0],
                'note': term,
                'evidence': {
                    'anchor': anchor,
                    'label': segment_label(seg) if seg else anchor,
                    'text': '身份：' + identity,
                },
            })
        if place:
            lid = 'L-' + place
            place_used.setdefault(lid, []).append(name)
            edges.append({
                'id': 'E-%s-%s' % (name, place), 'kind': 'place',
                'source': pid, 'target': lid, 'rel': '籍贯',
                'confidence': 'A', 'note': born and ('生于' + born) or '',
                'evidence': {
                    'anchor': anchor,
                    'label': segment_label(seg) if seg else anchor,
                    'text': '籍贯：' + raw_place,
                },
            })

    for did, names in disco_used.items():
        disc = did[2:]
        nodes.append({
            'id': did, 'label': disc, 'kind': 'discipline', 'chapter': '',
            'desc': DISC_DESC.get(disc, ''), 'count': len(names),
            'persons': names, 'anchors': [], 'degree': len(names),
        })
    for lid, names in place_used.items():
        nodes.append({
            'id': lid, 'label': lid[2:], 'kind': 'place', 'chapter': '',
            'count': len(names), 'persons': names, 'anchors': [], 'degree': len(names),
        })

    deg = {}
    for e in edges:
        deg[e['source']] = deg.get(e['source'], 0) + 1
        deg[e['target']] = deg.get(e['target'], 0) + 1
    for n in nodes:
        if n['kind'] == 'person':
            n['degree'] = deg.get(n['id'], 0)

    counts = {
        'person': sum(1 for n in nodes if n['kind'] == 'person'),
        'discipline': sum(1 for n in nodes if n['kind'] == 'discipline'),
        'place': sum(1 for n in nodes if n['kind'] == 'place'),
        'edges': len(edges),
        'disciplineEdges': sum(1 for e in edges if e['kind'] == 'discipline'),
        'placeEdges': sum(1 for e in edges if e['kind'] == 'place'),
        'nodes': len(nodes),
    }
    data = {
        'meta': {
            'code': code,
            'book': book.get('book') or code,
            'author': (book.get('CIP') or {}).get('作者') or '',
            'prototype': book.get('原型') or '',
            'prototypeName': book.get('原型名') or '',
            'version': 1,
            'built_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'counts': counts,
            'note': '人物—学科/籍贯关系由人物条目的「身份 / 籍贯」字段派生；学科大类的归并为人工规则，每条边可回到人物条目锚点。',
            'disciplineRule': '生物化学→生命；物理化学→化学；物理冶金→工程；空间物理→物理；系统工程→工程。',
        },
        'nodes': nodes,
        'edges': edges,
    }
    data = _with_curated_facts(code, data, segs)
    os.makedirs(KGDIR, exist_ok=True)
    path = os.path.join(KGDIR, code + '.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return data


def _count(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding='utf-8', errors='replace') as f:
        return sum(1 for line in f if line.strip())



# ── 叙事型（B58 小王子）：人工校验的试跑版 ───────────────────────────
NARR_PEOPLE = [
    # 姓名, 身份一句话, 语录, 锚点, 所属地点, 关联意象
    ('小王子', '来自 B612 小行星的旅行者，在地球上寻找人与关系的意义',
     '重要的东西用眼睛是看不见的。', 'B58-00-P94', ['B612', '地球', '沙漠'],
     ['绵羊', '猴面包树', '星星', '水井', '火山']),
    ('飞行员', '在撒哈拉沙漠迫降的叙述者，小时候画过蟒蛇吞大象',
     '水对心灵也是有益的。', 'B58-00-P41', ['地球', '沙漠'], ['绵羊', '星星', '水井']),
    ('玫瑰', 'B612 上那朵骄傲又脆弱的花，小王子为她浇水、罩玻璃罩',
     '我是宇宙里唯一的玫瑰花。', 'B58-00-P59', ['B612'], ['花园']),
    ('狐狸', '地球上的狐狸，教小王子什么叫「驯养」',
     '你只能了解你驯化的东西。', 'B58-00-P89', ['地球'], []),
    ('蛇', '沙漠里的蛇，说能把人送回他来的地方', '无论谁被我碰过，都会被我送回到他来的地方。',
     'B58-00-P85', ['沙漠'], []),
    ('国王', '第一颗小行星上的国王，命令一切，却没有一个子民',
     '我命令你坐下。', 'B58-00-P65', ['小行星'], []),
    ('商人', '忙着数星星的生意人，认为先想到就等于拥有',
     '它们就属于我，因为我是最先想到的。', 'B58-00-P72', ['小行星'], ['星星']),
    ('点灯人', '每分钟点灯、熄灯的人，遵守一个不会改的规定',
     '规定没有改，这就是悲剧所在。', 'B58-00-P76', ['小行星'], []),
    ('地理学家', '写地理书却从不走出办公室的老先生',
     '地理学家的职责不是走出去弄清楚外面有什么。', 'B58-00-P79', ['小行星'], []),
]
NARR_IMAGES = ['绵羊', '猴面包树', '星星', '水井', '花园', '火山']
NARR_REL = {
    '小王子': [('B612', 'B58-00-P47'), ('地球', 'B58-00-P85'), ('沙漠', 'B58-00-P85')],
    '飞行员': [('地球', 'B58-00-P85'), ('沙漠', 'B58-00-P96')],
    '玫瑰': [('B612', 'B58-00-P59')],
    '狐狸': [('地球', 'B58-00-P89')],
    '蛇': [('沙漠', 'B58-00-P85')],
    '国王': [('小行星', 'B58-00-P65')],
    '商人': [('小行星', 'B58-00-P72')],
    '点灯人': [('小行星', 'B58-00-P76')],
    '地理学家': [('小行星', 'B58-00-P79')],
}
NARR_IMG_ANCHOR = {
    '绵羊': 'B58-00-P42', '猴面包树': 'B58-00-P52', '星星': 'B58-00-P85',
    '水井': 'B58-00-P100', '火山': 'B58-00-P75', '花园': 'B58-00-P88',
}



# ── 索引型（B60 河北廉洁故事）：主题—人物，人工白名单 ───────────────
B60_PEOPLE = ['苏天爵','西门豹','赵奢','杨震','孟子','王翱','魏裔介','李藩','于成龙','魏忠贤',
              '李卫','曹彬','白芬','郭威','吴三桂','陆陇其','平原君','唐玄宗','季吉泰','柴荣',
              '刘缵','穆宗','杨骏','赵云旺']


def _b60_theme(raw):
    s = (raw or '').split('\u3000')[0]
    s = re.sub(r'^第[一二三四五六七八九十]+章\s*', '', s)
    s = re.split(r'[，。；]', s)[0]
    return s.strip()


def build_b60():
    code = 'B60'
    book = read_json(os.path.join(OUT, code, 'book.json'))
    segs = load_jsonl(os.path.join(OUT, code, 'segments.jsonl'))
    themes = []
    for s in segs:
        t = _b60_theme(s.get('篇'))
        if t and t != '前置' and t not in themes:
            themes.append(t)
    theme_order = {t: i for i, t in enumerate(themes)}
    people = []
    for name in B60_PEOPLE:
        hits = []
        for s in segs:
            if name in (s.get('文本') or ''):
                t = _b60_theme(s.get('篇'))
                if t and t != '前置' and t not in [h[0] for h in hits]:
                    hits.append((t, s))
        if hits:
            people.append((name, hits))
    nodes, edges = [], []
    for name, hits in people:
        pid = 'P-' + name
        first = hits[0][1]
        nodes.append({
            'id': pid, 'label': name, 'kind': 'person', 'chapter': '',
            'role': '《河北廉洁故事》人物 · 出现在「%s」等 %d 个主题' % (hits[0][0], len(hits)),
            'place': '', 'birthplace': '', 'achievement': '',
            'quote': (first.get('文本') or '')[:90],
            'raw': (first.get('文本') or '')[:320],
            'anchors': [{'id': first['id'], 'label': segment_label(first)}],
            'disciplines': [h[0] for h in hits], 'images': [], 'degree': len(hits),
        })
        for theme, seg in hits:
            edges.append({
                'id': 'E-%s-%s' % (name, theme), 'kind': 'discipline',
                'source': pid, 'target': 'T-' + theme, 'rel': '出现于',
                'confidence': 'A', 'primary': theme == hits[0][0], 'note': '主题',
                'evidence': {'anchor': seg['id'], 'label': segment_label(seg),
                             'text': (seg.get('文本') or '')[:240]},
            })
    for theme in themes:
        ps = [n for n in B60_PEOPLE if any(h[0] == theme for nm, h in people if nm == n)]
        nodes.append({'id': 'T-' + theme, 'label': theme, 'kind': 'discipline', 'chapter': '',
                      'desc': '廉洁主题（按篇目）', 'count': len(ps), 'persons': ps,
                      'anchors': [], 'degree': len(ps)})
    counts = {'person': len(people), 'discipline': len(themes), 'place': 0,
              'edges': len(edges), 'disciplineEdges': len(edges), 'placeEdges': 0,
              'nodes': len(nodes), 'relationEdges': 0}
    meta = {'code': code, 'book': book.get('book') or code,
            'author': (book.get('CIP') or {}).get('作者') or '',
            'prototype': book.get('原型') or '', 'prototypeName': book.get('原型名') or '',
            'template': 'index', 'form': '主题 · 人物', 'draft': False, 'version': 1,
            'built_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'counts': counts,
            'note': '主题—人物索引：9 个篇目主题 + 人工白名单人物；每条边来自该篇原文。',
            'catalogReason': '索引已建：%d 个主题 / %d 位人物 / %d 条边' % (len(themes), len(people), len(edges)),
            'labels': {'group': '主题', 'place': '人物', 'groupLayer': '主题归属', 'placeLayer': '人物',
                       'groupEdge': '出现于', 'placeEdge': '人物', 'chip': '按主题聚焦', 'personUnit': '主题数'}}
    data = {'meta': meta, 'nodes': nodes, 'edges': edges}
    os.makedirs(KGDIR, exist_ok=True)
    path = os.path.join(KGDIR, code + '.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return data

def _seg_text(seg_by_id, anchor, n=260):
    s = seg_by_id.get(anchor)
    if not s:
        return ''
    t = (s.get('文本') or '').replace('\n', ' ')
    return t if len(t) <= n else t[:n] + '…'


def build_b58():
    code = 'B58'
    book = read_json(os.path.join(OUT, code, 'book.json'))
    segs = load_jsonl(os.path.join(OUT, code, 'segments.jsonl'))
    seg_by_id = {s['id']: s for s in segs}
    nodes, edges = [], []
    place_counts, image_counts = {}, {}
    for name, role, quote, anchor, places, images in NARR_PEOPLE:
        pid = 'P-' + name
        seg = seg_by_id.get(anchor)
        nodes.append({
            'id': pid, 'label': name, 'kind': 'person', 'chapter': '',
            'role': role, 'place': places[0], 'birthplace': '',
            'achievement': '', 'quote': quote,
            'raw': _seg_text(seg_by_id, anchor, 320),
            'anchors': [{'id': anchor, 'label': segment_label(seg)}] if seg else [],
            'disciplines': places, 'images': images, 'degree': len(places) + len(images),
        })
        place_anchors = dict(NARR_REL.get(name, []))
        for place in places:
            place_counts[place] = place_counts.get(place, 0) + 1
            pa = place_anchors.get(place, anchor)
            pseg = seg_by_id.get(pa)
            edges.append({
                'id': 'E-%s-%s' % (name, place), 'kind': 'discipline',
                'source': pid, 'target': 'D-' + place, 'rel': '位于',
                'confidence': 'A', 'primary': place == places[0], 'note': '出场地点',
                'evidence': {'anchor': pa, 'label': segment_label(pseg),
                             'text': _seg_text(seg_by_id, pa, 240)},
            })
        for image in images:
            image_counts[image] = image_counts.get(image, 0) + 1
            ia = NARR_IMG_ANCHOR.get(image, anchor)
            iseg = seg_by_id.get(ia)
            edges.append({
                'id': 'E-%s-%s' % (name, image), 'kind': 'place',
                'source': pid, 'target': 'L-' + image, 'rel': '关联',
                'confidence': 'A', 'note': '意象',
                'evidence': {'anchor': ia, 'label': segment_label(iseg),
                             'text': _seg_text(seg_by_id, ia, 240)},
            })
    for place, count in place_counts.items():
        nodes.append({'id': 'D-' + place, 'label': place, 'kind': 'discipline', 'chapter': '',
                      'desc': '故事发生的地点', 'count': count,
                      'persons': [p[0] for p in NARR_PEOPLE if place in p[4]], 'anchors': [], 'degree': count})
    for image, count in image_counts.items():
        nodes.append({'id': 'L-' + image, 'label': image, 'kind': 'place', 'chapter': '',
                      'desc': '反复出现的意象', 'count': count,
                      'persons': [p[0] for p in NARR_PEOPLE if image in p[5]], 'anchors': [], 'degree': count})
    # 人物—人物：叙事图谱的主干关系，人工从原文抽
    relations = [
        ('小王子', '狐狸', '驯养', 'B58-00-P92', '于是小王子驯化了狐狸。'),
        ('小王子', '玫瑰', '照顾', 'B58-00-P63', '他给花浇了最后一次水，准备把她放到玻璃罩里。'),
        ('蛇', '小王子', '咬', 'B58-00-P104', '“怎么回事！你为什么要跟蛇说话？”'),
        ('国王', '小王子', '命令', 'B58-00-P66', '“我命令你坐下，”国王回答说。'),
        ('飞行员', '小王子', '遇见', 'B58-00-P41', '“请你……帮我画只绵羊。”'),
        ('小王子', '飞行员', '告别', 'B58-00-P109', '“你知道吗……我的花……我要为她负责！”'),
    ]
    for a, b, rel, anchor, quote in relations:
        seg = seg_by_id.get(anchor)
        edges.append({
            'id': 'E-%s-%s-%s' % (a, b, rel), 'kind': 'relation',
            'source': 'P-' + a, 'target': 'P-' + b, 'rel': rel,
            'confidence': 'A', 'note': quote,
            'evidence': {'anchor': anchor, 'label': segment_label(seg),
                         'text': _seg_text(seg_by_id, anchor, 240)},
        })
    counts = {
        'person': len(NARR_PEOPLE), 'discipline': len(place_counts), 'place': len(image_counts),
        'edges': len(edges), 'disciplineEdges': sum(1 for e in edges if e['kind'] == 'discipline'),
        'placeEdges': sum(1 for e in edges if e['kind'] == 'place'),
        'nodes': len(nodes), 'relationEdges': sum(1 for e in edges if e['kind'] == 'relation'),
    }
    meta = {
        'code': code, 'book': book.get('book') or code, 'author': (book.get('CIP') or {}).get('作者') or '',
        'prototype': book.get('原型') or '', 'prototypeName': book.get('原型名') or '',
        'template': 'narrative', 'form': '人物 · 地点 · 意象 · 关系', 'draft': True, 'version': 0.1,
        'built_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        'counts': counts,
        'note': '试跑版：人工从原文抽 28 条关系，每条带锚点；地点/意象为人工归类，待编辑确认后才算正式图谱。',
        'catalogReason': '试跑版已建：9 个人物 / 4 个地点 / 6 个意象 / 28 条边，待编辑确认',
        'labels': {'group': '地点', 'place': '意象', 'groupLayer': '地点归属', 'placeLayer': '意象关联',
                   'groupEdge': '位于', 'placeEdge': '关联', 'chip': '按地点聚焦', 'personUnit': '出场地点数'},
    }
    data = {'meta': meta, 'nodes': nodes, 'edges': edges}
    os.makedirs(KGDIR, exist_ok=True)
    path = os.path.join(KGDIR, code + '.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return data


# ── 通用构建器：保证每一本书都能出一张图 ─────────────────────────────
def _card_label(c):
    f = c.get('字段') or {}
    for k in ('中名', '姓名', '篇名', '书名', '名称'):
        if f.get(k):
            return str(f[k])[:20]
    t = (c.get('原文') or '').strip()
    return t[:14] or c.get('id', '')


def _chapter_name(raw):
    raw = (raw or '').split('\u3000')[0].strip()
    return raw[:24] or '全书'


def _write_kg(code, meta, nodes, edges):
    data = _with_curated_facts(code, {'meta': meta, 'nodes': nodes, 'edges': edges})
    os.makedirs(KGDIR, exist_ok=True)
    path = os.path.join(KGDIR, code + '.json')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return data


def _structural_meta(code, book, form, labels, default_hidden=None):
    return {'code': code, 'book': book.get('book') or code,
            'author': (book.get('CIP') or {}).get('作者') or '',
            'prototype': book.get('原型') or '', 'prototypeName': book.get('原型名') or '',
            'template': 'structural', 'form': form, 'draft': False, 'version': 1,
            'built_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'labels': labels, 'defaultHidden': default_hidden or []}


def build_illustrated(code):
    """图鉴型：篇章 → 科 → 物种。物种默认收起，先看篇章与科。"""
    book = read_json(os.path.join(OUT, code, 'book.json'))
    cards = load_jsonl(os.path.join(OUT, code, 'cards.jsonl'))
    segs = load_jsonl(os.path.join(OUT, code, 'segments.jsonl'))
    if not cards:
        return build_structural(code)
    seg_by_id = {s['id']: s for s in segs}
    chapters, families = [], []
    nodes, edges = [], []
    chapter_cards, family_cards = {}, {}
    for c in cards:
        f = c.get('字段') or {}
        if not f.get('中名'):
            continue
        seg = seg_by_id.get(c.get('锚点'))
        chap = _chapter_name(seg.get('篇')) if seg else '全书'
        fam = (f.get('科名') or '').strip() or '未分科'
        if chap not in chapters:
            chapters.append(chap)
        if fam not in families:
            families.append(fam)
        chapter_cards.setdefault(chap, []).append(c)
        family_cards.setdefault(fam, []).append(c)
        sid = 'S-' + c['id']
        nodes.append({
            'id': sid, 'label': str(f.get('中名'))[:20], 'kind': 'place', 'type': '物种',
            'role': '科名：%s · 药用部位：%s' % (fam, f.get('药用部位') or '—'),
            'place': fam, 'quote': (f.get('性味功效') or '')[:80],
            'raw': (c.get('原文') or '')[:260],
            'anchors': [{'id': c['锚点'], 'label': segment_label(seg)}],
            'disciplines': [fam, chap], 'images': [], 'degree': 1, 'size': 1,
            'code': code, 'book': book.get('book') or code,
        })
        edges.append({
            'id': 'E-%s-F-%s' % (c['id'], fam), 'kind': 'discipline',
            'source': sid, 'target': 'F-' + fam, 'rel': '属于', 'confidence': 'A',
            'primary': True, 'note': '科属',
            'evidence': {'anchor': c['锚点'], 'label': segment_label(seg),
                         'text': (c.get('原文') or '')[:220]},
        })
    if not nodes:
        return build_structural(code)
    for chap in chapters:
        nodes.append({'id': 'C-' + chap, 'label': chap, 'kind': 'discipline', 'type': '篇章',
                      'desc': '篇目', 'count': len(chapter_cards.get(chap, [])),
                      'persons': [], 'anchors': [], 'degree': len(chapter_cards.get(chap, [])), 'code': code})
    for fam in families:
        nodes.append({'id': 'F-' + fam, 'label': fam, 'kind': 'discipline', 'type': '科',
                      'desc': '科名', 'count': len(family_cards.get(fam, [])),
                      'persons': [], 'anchors': [], 'degree': len(family_cards.get(fam, [])), 'code': code})
    seen = set()
    for fam in families:
        for c in family_cards.get(fam, []):
            seg = seg_by_id.get(c.get('锚点'))
            chap = _chapter_name(seg.get('篇')) if seg else '全书'
            key = (fam, chap)
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                'id': 'E-F-%s-C-%s' % (fam, chap), 'kind': 'discipline',
                'source': 'F-' + fam, 'target': 'C-' + chap, 'rel': '收录', 'confidence': 'A',
                'note': '篇目收录', 'evidence': {'anchor': c['锚点'], 'label': segment_label(seg),
                                                  'text': (c.get('原文') or '')[:220]},
            })
    counts = {'person': 0, 'discipline': len(chapters) + len(families), 'place': len([n for n in nodes if n['type'] == '物种']),
              'edges': len(edges), 'disciplineEdges': sum(1 for e in edges if e['kind'] == 'discipline'),
              'placeEdges': 0, 'nodes': len(nodes), 'relationEdges': 0}
    meta = _structural_meta(code, book, '篇章 · 科 · 物种',
                            {'group': '篇章', 'place': '物种', 'groupEdge': '收录', 'placeEdge': '属于'},
                            ['物种'])
    meta.update({'counts': counts, 'template': 'illustrated',
                 'note': '篇章 → 科 → 物种；物种默认收起，先看篇章与科。',
                 'catalogReason': '图鉴已建：%d 篇 / %d 科 / %d 物种' % (len(chapters), len(families), counts['place'])})
    return _write_kg(code, meta, nodes, edges)


def build_structural(code):
    """通用兜底：篇章 → 条目；没有条目就用段落连成阅读路径。"""
    book = read_json(os.path.join(OUT, code, 'book.json'))
    cards = load_jsonl(os.path.join(OUT, code, 'cards.jsonl'))
    segs = load_jsonl(os.path.join(OUT, code, 'segments.jsonl'))
    seg_by_id = {s['id']: s for s in segs}
    nodes, edges = [], []
    if cards:
        chapters, by_chapter = [], {}
        for c in cards:
            seg = seg_by_id.get(c.get('锚点'))
            chap = _chapter_name(seg.get('篇')) if seg else '全书'
            if chap not in chapters:
                chapters.append(chap)
            by_chapter.setdefault(chap, []).append(c)
        for chap in chapters:
            nodes.append({'id': 'C-' + chap, 'label': chap, 'kind': 'discipline', 'type': '篇章',
                          'desc': '篇目', 'count': len(by_chapter[chap]), 'persons': [],
                          'anchors': [], 'degree': len(by_chapter[chap]), 'code': code})
        for c in cards:
            seg = seg_by_id.get(c.get('锚点'))
            chap = _chapter_name(seg.get('篇')) if seg else '全书'
            cid = 'I-' + c['id']
            nodes.append({'id': cid, 'label': _card_label(c), 'kind': 'place', 'type': '条目',
                          'role': c.get('类型') or '知识条目', 'place': '',
                          'quote': (c.get('原文') or '')[:80], 'raw': (c.get('原文') or '')[:260],
                          'anchors': [{'id': c['锚点'], 'label': segment_label(seg)}],
                          'disciplines': [chap], 'images': [], 'degree': 1, 'size': 1,
                          'code': code, 'book': book.get('book') or code})
            edges.append({'id': 'E-C-%s-I-%s' % (chap, c['id']), 'kind': 'place',
                          'source': 'C-' + chap, 'target': cid, 'rel': '包含', 'confidence': 'A',
                          'note': '篇目包含', 'evidence': {'anchor': c['锚点'], 'label': segment_label(seg),
                                                            'text': (c.get('原文') or '')[:220]}})
        counts = {'person': 0, 'discipline': len(chapters), 'place': len(cards), 'edges': len(edges),
                  'disciplineEdges': 0, 'placeEdges': len(edges), 'nodes': len(nodes), 'relationEdges': 0}
        meta = _structural_meta(code, book, '篇章 · 条目',
                                {'group': '篇章', 'place': '条目', 'groupEdge': '包含', 'placeEdge': '条目'})
        meta.update({'counts': counts, 'note': '篇章 → 知识条目；每条边来自条目锚点。',
                     'catalogReason': '条目图已建：%d 篇 / %d 条' % (len(chapters), len(cards))})
        return _write_kg(code, meta, nodes, edges)
    # 没有条目：用段落连成阅读路径
    ordered = [s for s in segs if s.get('篇') != '前置'] or segs
    prev = None
    for s in ordered:
        nid = 'G-' + s['id']
        nodes.append({'id': nid, 'label': '第%s段' % (s.get('段') or ''), 'kind': 'place', 'type': '段落',
                      'role': '原文段落', 'place': '', 'quote': (s.get('文本') or '')[:80],
                      'raw': (s.get('文本') or '')[:260],
                      'anchors': [{'id': s['id'], 'label': segment_label(s)}],
                      'disciplines': [], 'images': [], 'degree': 1, 'size': 1,
                      'code': code, 'book': book.get('book') or code})
        if prev:
            edges.append({'id': 'E-%s-%s' % (prev['id'], s['id']), 'kind': 'relation',
                          'source': 'G-' + prev['id'], 'target': nid, 'rel': '下一页', 'confidence': 'A',
                          'note': '阅读顺序', 'evidence': {'anchor': s['id'], 'label': segment_label(s),
                                                            'text': (s.get('文本') or '')[:220]}})
        prev = s
    counts = {'person': 0, 'discipline': 0, 'place': len(nodes), 'edges': len(edges),
              'disciplineEdges': 0, 'placeEdges': 0, 'nodes': len(nodes), 'relationEdges': len(edges)}
    meta = _structural_meta(code, book, '段落 · 阅读顺序',
                            {'group': '段落', 'place': '段落', 'groupEdge': '顺序', 'placeEdge': '段落'})
    meta.update({'counts': counts, 'note': '没有条目：用原文段落连成阅读路径。',
                 'catalogReason': '段落图已建：%d 段' % len(nodes)})
    return _write_kg(code, meta, nodes, edges)


def auto_build(code, force=False):
    """新书统一入口：有专门构建器用专门的，没有就用通用兜底。"""
    path = os.path.join(KGDIR, code + '.json')
    if os.path.exists(path) and not force:
        return load_graph(code)
    book = read_json(os.path.join(OUT, code, 'book.json'))
    if not book:
        raise SystemExit('没有 book.json：%s' % code)
    proto = book.get('原型') or ''
    if proto == 'P11':
        return build_illustrated(code)
    return build_structural(code)

def _classification(book):
    """Use the persisted CLC major class, matching source books and QA."""
    import engine_bridge  # Registers the shared engine modules for CLI use too.
    import clc
    value = book.get('CLC') if isinstance(book, dict) else None
    code = value.get('代码') if isinstance(value, dict) else None
    if not isinstance(code, str) or code not in clc.NAME:
        return 'unclassified', '未分类'
    name = value.get('名称')
    return code, name.strip() if isinstance(name, str) and name.strip() else clc.NAME[code]


def catalog(book_codes=None, *, picker=False):
    """图谱书目；选择器只读已建图书的基本元数据，不扫描图谱或正文。"""
    lib = read_json(os.path.join(APP_DIR, 'data', 'library.json'), {}).get('books') or {}
    selected = set(book_codes) if book_codes is not None else None
    rows = []
    for code, b in lib.items():
        if selected is not None and code not in selected:
            continue
        kg_path = os.path.join(KGDIR, code + '.json')
        if picker and not os.path.isfile(kg_path):
            continue
        bj = read_json(os.path.join(OUT, code, 'book.json'))
        clc_code, clc_name = _classification(bj)
        if picker:
            rows.append({'code': code, 'title': b.get('book') or code,
                         'clc_code': clc_code, 'clc_name': clc_name, 'status': '已建图'})
            continue
        proto = bj.get('原型') or ''
        proto_name = bj.get('原型名') or ''
        cards = _count(os.path.join(OUT, code, 'cards.jsonl'))
        people = _count(os.path.join(OUT, code, 'people.jsonl'))
        segs = _count(os.path.join(OUT, code, 'segments.jsonl'))
        strong = 0
        for p in load_jsonl(os.path.join(OUT, code, 'people.jsonl')):
            if p.get('证据') in ('确认', '强证据'):
                strong += 1
        quality = (strong / people) if people else 0
        graph = load_graph(code) if code in kg_curated.FACTS else read_json(kg_path, {})
        kg_meta = (graph or {}).get('meta') or {}
        req = requests().get(code)
        if os.path.exists(kg_path):
            status = '已建图'
            form = kg_meta.get('form') or '人物 · 学科 · 籍贯'
            reason = kg_meta.get('catalogReason') or '已建图，边带原文锚点'
        elif proto == 'P11':
            status, form, reason = '待建图', '物种 · 科属 · 功效', '%d 条物种条目，科名/功效字段可派生分类与属性边' % cards
        elif people >= 20 and quality >= 0.8:
            status, form, reason = '待建图', '人物 · 事件 · 地点', '%d 个人物、%d 条条目，人物证据强' % (people, cards)
        elif proto == 'P4':
            status, form, reason = '待建图', '人物 · 意象 · 情节', '%d 条条目（多为引书）、%d 段原文；叙事关系需人工从原文抽' % (cards, segs)
        elif cards >= 30 and people < 3:
            status, form, reason = '可出索引', '意象 · 篇目 · 主题', '%d 条条目、%d 个人物；关系弱，先出主题索引' % (cards, people)
        elif segs < 20:
            status, form, reason = '数据不足', '故事地图（手工）', '仅 %d 段原文、%d 条条目' % (segs, cards)
        elif people >= 10 and quality < 0.5:
            status = '可出索引'
            form = '人物 · 事件 · 时间线' if proto == 'P6' else '主题 · 故事 · 人物'
            reason = '人物表含泛称/动词（强证据 %d/%d），先出索引' % (strong, people)
        else:
            status, form, reason = '待建图', '人物 · 意象 · 情节', '%d 条条目、%d 段原文，关系需人工确认' % (cards, segs)
        rows.append({
            'code': code, 'title': b.get('book') or code, 'author': b.get('author') or '',
            'clc_code': clc_code, 'clc_name': clc_name,
            'prototype': proto, 'prototypeName': proto_name,
            'cards': cards, 'people': people, 'segments': segs,
            'status': status, 'form': form, 'reason': reason,
            'nodes': (kg_meta.get('counts') or {}).get('nodes') or 0,
            'edges': (kg_meta.get('counts') or {}).get('edges') or 0,
            'draft': bool(kg_meta.get('draft')),
            'requested_at': (req or {}).get('at'),
        })
    order = {'已建图': 0, '待建图': 1, '可出索引': 2, '数据不足': 3}
    rows.sort(key=lambda r: (order.get(r['status'], 9), r['code']))
    return rows



def _cross_book_links(nodes, source_rows):
    """Admit only reviewed cross-book links with both endpoints in this view."""
    node_counts = Counter(node['id'] for node in nodes)
    by_node = {node['id']: node for node in nodes if node_counts[node['id']] == 1}
    by_source = {}
    for code, rows in source_rows.items():
        counts = Counter(row.get('id') for row in rows)
        by_source[code] = {row['id']: row for row in rows if counts[row.get('id')] == 1}
    links = []
    for item in kg_curated.CROSS_LINKS:
        source, target = by_node.get(item['source']), by_node.get(item['target'])
        if not source or not target or source.get('code') == target.get('code'):
            continue
        if source.get('label') != item['source_label'] or target.get('label') != item['target_label']:
            continue
        sources = item['evidence']
        if {ev['code'] for ev in sources} != {source.get('code'), target.get('code')}:
            continue
        evidence = []
        for ev in sources:
            segments = by_source.get(ev['code'], {})
            if not _fact_source_valid(ev, segments):
                break
            segment = segments[ev['anchor']]
            if hashlib.sha256(segment['文本'].encode('utf-8')).hexdigest() != ev['sha256']:
                break
            evidence.append({'code': ev['code'], 'anchor': ev['anchor'], 'quote': ev['quote'],
                             'label': segment_label(segment)})
        if len(evidence) != len(sources) or not evidence:
            continue
        links.append({key: item[key] for key in ('id', 'label', 'title', 'source', 'target', 'basis', 'via', 'reason')})
        links[-1]['evidence'] = evidence
    return links


def view_graph(code=None, codes=None):
    """统一视图：全部已建图书、单本书或明确选择的一组图书。

    返回前端直接可用的 canvas 图数据：
      node.kind = book | entity；node.type = 人物/学科/籍贯/地点/意象
      edge.kind = in_book | discipline | place | relation
    """
    if codes is not None:
        if code is not None:
            raise ValueError('code 与 codes 不能同时使用')
        if not isinstance(codes, list) or len(codes) > MAX_VIEW_BOOKS:
            raise ValueError('一次最多选择 %d 本图书' % MAX_VIEW_BOOKS)
        if any(not isinstance(value, str) or not VIEW_CODE_RE.fullmatch(value) for value in codes):
            raise ValueError('图书编号格式不正确')
        codes = list(dict.fromkeys(codes))
    scope = codes if codes is not None else [code] if code else None
    built = [r for r in catalog(book_codes=scope) if r['status'] == '已建图']
    if codes is not None:
        by_code = {row['code']: row for row in built}
        if any(value not in by_code for value in codes):
            raise ValueError('所选图书不存在或尚未建图，请刷新书目后重新选择')
        built = [by_code[value] for value in codes]
    elif code:
        built = [r for r in built if r['code'] == code]
    nodes, edges, books = [], [], []
    source_rows = {}
    type_counts = {}
    default_hidden = set()
    for row in built:
        code_ = row['code']
        g = load_graph(code_)
        if not g:
            continue
        meta = g.get('meta') or {}
        labels = meta.get('labels') or {}
        for x in (meta.get('defaultHidden') or []):
            default_hidden.add(x)
        group_name = labels.get('group') or '学科'
        place_name = labels.get('place') or '籍贯'
        book_id = 'BOOK:' + code_
        short = re.split(r'——|—', row['title'])[0].strip() or row['title']
        books.append({'code': code_, 'id': book_id, 'title': row['title'], 'short': short,
                      'form': row.get('form') or '',
                      'clc_code': row.get('clc_code', 'unclassified'), 'clc_name': row.get('clc_name', '未分类')})
        nodes.append({
            'id': book_id, 'kind': 'book', 'type': '书', 'label': '《' + short + '》', 'full': row['title'],
            'code': code_, 'size': 22, 'form': row.get('form') or '',
            'counts': {'nodes': row.get('nodes') or 0, 'edges': row.get('edges') or 0},
        })
        idmap = {}
        raw_nodes = {n['id']: n for n in g.get('nodes') or []}
        source_rows[code_] = load_jsonl(os.path.join(OUT, code_, 'segments.jsonl'))
        segments = {s['id']: s for s in source_rows[code_]}
        edge_ids = Counter(e.get('id') for e in g.get('edges') or [])
        for n in g.get('nodes') or []:
            nid = code_ + ':' + n['id']
            idmap[n['id']] = nid
            kind = n.get('kind')
            typ = n.get('type') or ('人物' if kind == 'person' else group_name if kind == 'discipline' else place_name)
            type_counts[typ] = type_counts.get(typ, 0) + 1
            nn = dict(n)
            nn.update({'id': nid, 'kind': 'entity', 'type': typ, 'code': code_,
                       'book': row['title'], 'size': max(1, n.get('degree') or n.get('count') or 1)})
            nodes.append(nn)
            edges.append({'source': book_id, 'target': nid, 'kind': 'in_book', 'weight': 0.2,
                          'relation_basis': 'structure', 'relation_basis_label': RELATION_BASIS_LABELS['structure']})
        for e in g.get('edges') or []:
            s_, t_ = idmap.get(e['source']), idmap.get(e['target'])
            if not s_ or not t_:
                continue
            ee = dict(e)
            ee.update({'source': s_, 'target': t_, 'weight': e.get('weight') or 1})
            ee.update(relation_basis(code_, e, raw_nodes, segments))
            material, reason = relation_material(code_, e, raw_nodes, segments)
            if edge_ids[e.get('id')] != 1:
                material, reason = None, '关系标识重复，暂不能收集'
            ee.pop('asset_id', None)
            ee.update(code=code_, edge_id=e.get('id', ''))
            if material:
                ee['asset_id'] = relation_asset_id(code_, e['id'])
                ee['relation_origin'] = material['origin']
                ee['evidence'] = {**ee.get('evidence', {}), 'text': material['evidence'][0]['quote']}
            else:
                ee['material_unavailable_reason'] = reason
            edges.append(ee)
    return {
        'meta': {
            'mode': 'selection' if codes is not None else 'book' if code else 'global',
            'code': code or '',
            'codes': codes if codes is not None else [book['code'] for book in books],
            'books': books,
            'types': [{'name': k, 'count': v} for k, v in type_counts.items()],
            'defaultHidden': sorted(default_hidden),
            'counts': {
                'nodes': len([n for n in nodes if n['kind'] == 'entity']),
                'edges': len([e for e in edges if e['kind'] != 'in_book']),
                'books': len(books),
            },
        },
        'nodes': nodes,
        'edges': edges,
        'cross_links': _cross_book_links(nodes, source_rows),
    }

def segment(code, anchor_id):
    for s in load_jsonl(os.path.join(OUT, code, 'segments.jsonl')):
        if s.get('id') == anchor_id:
            return {'id': anchor_id, 'label': segment_label(s) or anchor_id,
                    'text': s.get('文本') or '', 'chapter': s.get('篇') or '',
                    'no': s.get('段') or 0}
    return None


def load_graph(code):
    graph = read_json(os.path.join(KGDIR, code + '.json'), None)
    # Correct this known legacy evidence pointer on read, without rewriting
    # stored graphs or manufacturing evidence if the source has changed.
    if code == 'B58' and graph:
        for edge in graph.get('edges') or []:
            if (edge.get('id'), edge.get('source'), edge.get('target'), edge.get('rel'),
                    (edge.get('evidence') or {}).get('anchor')) != (
                    'E-小王子-狐狸-驯养', 'P-小王子', 'P-狐狸', '驯养', 'B58-00-P91'):
                continue
            current = segment(code, 'B58-00-P92')
            if current and '小王子驯化了狐狸' in current['text']:
                edge['note'] = '于是小王子驯化了狐狸。'
                edge['evidence'] = {'anchor': current['id'], 'label': current['label'], 'text': current['text']}
    return _with_curated_facts(code, graph)


def requests():
    return read_json(REQFILE, {}) or {}


def set_request(code, note='', cancel=False):
    req = requests()
    if cancel:
        req.pop(code, None)
    else:
        req[code] = {
            'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
            'note': (note or '').strip()[:300],
        }
    os.makedirs(KGDIR, exist_ok=True)
    tmp = REQFILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(req, f, ensure_ascii=False, indent=1)
    os.replace(tmp, REQFILE)
    return req.get(code)


if __name__ == '__main__':
    code = sys.argv[1] if len(sys.argv) > 1 else 'B59'
    d = build_book(code)
    c = d['meta']['counts']
    print('built', code, c)
