# -*- coding: utf-8 -*-
"""从 distill/ 的共读资产构建「概念图谱」原型数据。

产物：kg_data.json（内联进原型页，不走网络请求）。
边分三层：
  argue  概念—概念 论证关系（人工校验，每条带原文锚点）
  chapter 概念—篇 结构关系
  topic  主题—概念 聚合关系（由主题层的锚点对齐得到）
"""
import json
import os
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kg_data.json')


def load(name):
    p = os.path.join(ROOT, 'distill', name)
    with open(p, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


K = load('knowledge.jsonl')
T = load('topics.jsonl')
S = load('segments.jsonl')

segs = {s['id']: s for s in S}
by_label = {k['词条']: k for k in K}

EDGES = [
    ('五事', '七计', '组成', '五事拆维度，七计逐条打分'),
    ('五事', '庙算', '前提', '庙算之前先经五事、校之以计'),
    ('七计', '庙算', '手段', '用七问比较敌我，得出胜负判断'),
    ('诡道', '示形动敌', '同源', '示形动敌是诡道在兵势篇的展开'),
    ('势（因利制权）', '诡道', '组成', '「因利而制权」是诡道的造势环节'),
    ('日费千金', '兵贵胜不贵久', '因果', '十万之师日费千金，所以只能速胜'),
    ('兵贵胜不贵久', '因粮于敌', '手段', '速胜的物质条件是就地取粮'),
    ('因粮于敌', '胜敌而益强', '目的', '取用于敌，越打越强'),
    ('胜敌而益强', '日费千金', '对照', '一边消耗本国，一边从敌国取给'),
    ('全胜', '伐谋四层', '手段', '全胜的路径：伐谋→伐交→伐兵→攻城'),
    ('兵力比六法', '全胜', '手段', '按兵力对比选打法，避免硬拼'),
    ('知胜有五', '知彼知己', '前提', '知胜五条，落脚在知彼知己'),
    ('知彼知己', '全胜', '前提', '知彼知己，才能不战而屈人之兵'),
    ('伐谋四层', '兵力比六法', '对照', '上策用谋，下策攻城；六法管打的时候'),
    ('先为不可胜', '胜兵先胜而后求战', '前提', '先做到不可胜，再等敌之可胜'),
    ('守则不足攻则有余', '先为不可胜', '手段', '不足则守，有余则攻'),
    ('度数量称胜', '先为不可胜', '手段', '度数量称，是判断强弱的方法'),
    ('度数量称胜', '五事', '同源', '把五事逐层折算成可比较的量'),
    ('胜兵先胜而后求战', '庙算', '同源', '都是未战先算、先胜后战'),
    ('分数、形名、奇正、虚实', '奇正相生', '组成', '治众四要的第三项'),
    ('奇正相生', '势险节短', '手段', '奇正变化造势，势险节短是势的形态'),
    ('势险节短', '任势', '目的', '造势之后要择人任势'),
    ('示形动敌', '任势', '手段', '示形调动敌人，才有势可任'),
    ('致人而不致于人', '攻其所必救', '手段', '调动敌人的第一招'),
    ('攻其所必救', '形人而我无形', '手段', '攻其必救，敌形自露'),
    ('形人而我无形', '无所不备则无所不寡', '因果', '我专而敌分，敌处处设防则处处薄弱'),
    ('兵形象水', '策作形角', '前提', '因敌制胜的前提是察敌：策、作、形、角'),
    ('策作形角', '形人而我无形', '手段', '四种侦察手段，都是让敌形暴露'),
    ('致人而不致于人', '知彼知己', '前提', '要调动敌人，先要知道敌我'),
    ('无所不备则无所不寡', '兵力比六法', '同源', '集中兵力的算术'),
    ('以迂为直以患为利', '军争为利众争为危', '前提', '迂直患利，是化解争利之危的办法'),
    ('军争为利众争为危', '用兵八戒', '风险', '争利的风险，具体化成八戒'),
    ('四治', '军争为利众争为危', '手段', '治气治心治力治变，才能争而不危'),
    ('以迂为直以患为利', '致人而不致于人', '同源', '都是争夺主动权'),
    ('九变', '杂于利害', '手段', '九变的前提是杂于利害'),
    ('九变', '将有五危', '风险', '不知九变，则将有五危'),
    ('杂于利害', '以迂为直以患为利', '同源', '利害互转，患利相生'),
    ('将有五危', '进不求名退不避罪', '对照', '五危是性格之失，后者是担当'),
    ('四军之利', '贵阳贱阴', '组成', '处军四法，贵阳贱阴是其中原则'),
    ('相敌之法', '知彼知己', '手段', '三十二法，都是知彼'),
    ('令文齐武', '四治', '同源', '恩威并施，就是治气治心'),
    ('兵非贵益多', '全胜', '同源', '不求多而求精，与全胜同调'),
    ('地形六形', '地形者兵之助', '组成', '六形是地形之助的分类'),
    ('六败', '地形者兵之助', '风险', '地形之助用错，就是六败'),
    ('视卒如婴儿', '令文齐武', '同源', '爱兵与恩威并施，是一体两面'),
    ('进不求名退不避罪', '将有五危', '对照', '五危是失，进不求名是守'),
    ('九地', '九地之策', '组成', '九地分类，对策随之'),
    ('九地之策', '投之亡地然后存', '手段', '死地则战，投之亡地然后存'),
    ('为客之道', '九地之策', '手段', '深入则专，是九地之策的一条'),
    ('率然', '九地之策', '同源', '率然是九地协同的比喻'),
    ('始如处女后如脱兔', '势险节短', '同源', '静如处女、动如脱兔，就是势险节短'),
    ('火攻五变', '五火之变', '组成', '五变是火攻的五种情形'),
    ('五火之变', '费留', '风险', '火攻之后不修功，就是费留'),
    ('先知', '五间', '手段', '先知必取于人，取于间'),
    ('五间', '反间为要', '组成', '五间之中，反间最要'),
    ('间事之密', '五间', '风险', '间事不密，五间尽废'),
    ('上智为间', '反间为要', '前提', '非上智不能用间'),
    ('相敌之法', '策作形角', '同源', '一处军观察，一虚实侦察'),
    ('全胜', '先为不可胜', '同源', '全胜是目标，先为不可胜是起点'),
    ('庙算', '度数量称胜', '同源', '庙算要算的，正是度数量称'),
]

missing = [a for a, b, _, _ in EDGES if a not in by_label] + [b for a, b, _, _ in EDGES if b not in by_label]
assert not missing, missing

ch_order = []
for _s in S:
    if _s['篇'] not in ch_order:
        ch_order.append(_s['篇'])
chapters = [c for c in ch_order if c in {k['篇'] for k in K}]
concept_by_name = {k['词条']: k for k in K}
cid = {k['词条']: k['id'] for k in K}


def seg_text(anchor_id, n=140):
    s = segs.get(anchor_id)
    if not s:
        return ''
    t = s['文本'].replace('\n', '')
    return t if len(t) <= n else t[:n] + '…'


nodes = []
for k in K:
    nodes.append({
        'id': k['id'],
        'label': k['词条'],
        'kind': 'concept',
        'chapter': k['篇'],
        'aliases': k.get('别称', []),
        'def': k.get('定义', ''),
        'points': k.get('要点', []),
        'quote': k.get('原文', ''),
        'confuse': k.get('易混淆', ''),
        'extend': k.get('延伸', ''),
        'tags': k.get('标签', []),
        'anchors': [{'id': a, 'label': segs[a]['锚点'] if a in segs else a,
                     'text': seg_text(a, 200)} for a in k.get('锚点', [])],
        'sources': k.get('出处', []),
    })

chapter_ids = {}
for i, c in enumerate(chapters):
    ch_id = 'CH-%02d' % (i + 1)
    chapter_ids[c] = ch_id
    nodes.append({
        'id': ch_id, 'label': c + '篇', 'kind': 'chapter', 'chapter': c,
        'def': '%s篇，共 %d 个概念条目。' % (c, sum(1 for k in K if k['篇'] == c)),
        'points': [], 'quote': '', 'aliases': [], 'tags': [],
        'anchors': [], 'sources': [],
    })

edges = []
for i, (a, b, rel, note) in enumerate(EDGES):
    ka, kb = concept_by_name[a], concept_by_name[b]
    aid = ka['锚点'][0] if ka['锚点'] else None
    edges.append({
        'id': 'E-%03d' % (i + 1), 'kind': 'argue', 'source': cid[a], 'target': cid[b],
        'rel': rel, 'note': note, 'confidence': '已校验',
        'evidence': {
            'anchor': aid, 'label': segs[aid]['锚点'] if aid in segs else '',
            'text': seg_text(aid, 220) if aid else '',
            'target_anchor': kb['锚点'][0] if kb['锚点'] else None,
            'target_label': segs[kb['锚点'][0]]['锚点'] if kb['锚点'] and kb['锚点'][0] in segs else '',
        },
    })
for k in K:
    edges.append({
        'id': 'EC-' + k['id'], 'kind': 'chapter', 'source': cid[k['词条']],
        'target': chapter_ids[k['篇']], 'rel': '出自', 'note': '', 'confidence': '',
        'evidence': None,
    })

# 主题层 → 概念：主题层里的锚点，正好也是某条概念的锚点
topic_nodes = []
topic_edges = []
used = 0
tcount = collections.Counter()
for t in T:
    links = []
    for layer in t.get('层', []):
        anchors = [layer.get('锚点')] + list(layer.get('又见', []) or [])
        for a in anchors:
            if not a:
                continue
            for k in K:
                if a in k.get('锚点', []) and k['词条'] not in [x[0] for x in links]:
                    links.append((k['词条'], layer, a))
    if not links:
        continue
    tid = 'T-' + t['id']
    tcount[tid] = len(links)
    topic_nodes.append({
        'id': tid, 'label': t['主题'], 'kind': 'topic', 'chapter': '', 'sub': t.get('副', ''),
        'def': t.get('为什么难读', ''), 'points': [l['层'] for l in t.get('层', [])],
        'quote': '', 'aliases': [], 'tags': [], 'anchors': [], 'sources': [],
    })
    seen = set()
    for name, layer, a in links:
        if name in seen:
            continue
        seen.add(name)
        topic_edges.append({
            'id': 'ET-%s-%s' % (t['id'], cid[name]), 'kind': 'topic',
            'source': tid, 'target': cid[name], 'rel': '聚合',
            'note': layer.get('层', ''), 'confidence': '自动',
            'evidence': {
                'anchor': a, 'label': segs[a]['锚点'] if a in segs else a,
                'text': layer.get('句', ''), 'target_anchor': None, 'target_label': '',
            },
        })

nodes += topic_nodes
edges += topic_edges

deg = collections.Counter()
for e in edges:
    if e['kind'] == 'argue':
        deg[e['source']] += 1
        deg[e['target']] += 1
for n in nodes:
    n['degree'] = deg[n['id']] if n['kind'] == 'concept' else 0

data = {
    'meta': {
        'book': '孙子兵法',
        'code': 'SZ',
        'note': '蒸馏样例书的 60 条概念资产 + 15 个主题；论证关系为人工校验版，每条带原文锚点。',
        'counts': {
            'concept': len(K), 'chapter': len(chapters), 'topic': len(topic_nodes),
            'argue': len(EDGES), 'chapterEdge': len(K), 'topicEdge': len(topic_edges),
        },
        'relTypes': sorted({e['rel'] for e in edges if e['kind'] == 'argue'}),
        'chapters': chapters,
    },
    'nodes': nodes,
    'edges': edges,
    'segments': {s['id']: {'label': s['锚点'], 'text': s['文本'], 'chapter': s['篇'], 'no': s['段序']} for s in S},
}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

print('nodes', len(nodes), 'edges', len(edges))
print('kinds', collections.Counter(n['kind'] for n in nodes))
print('edges', collections.Counter(e['kind'] for e in edges))
print('argue rel', collections.Counter(e['rel'] for e in edges if e['kind'] == 'argue'))
print('top degree', [(n['label'], n['degree']) for n in sorted(nodes, key=lambda x: -x['degree'])[:10]])
print('topics kept', len(topic_nodes), 'of', len(T), 'topic edges', len(topic_edges))
print('size KB', os.path.getsize(OUT) // 1024)
