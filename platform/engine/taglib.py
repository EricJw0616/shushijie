# -*- coding: utf-8 -*-
"""标签库生成：把 catalog + 各书产物压成「可按标签筛选」的图书数据库。

产物三个：
  library/tags.json            每本书的完整标签（八层，带来源与验证方式）
  library/tag_index.json       标签 → 书的倒排索引（按标签找书用）
  library/tag_dict.json        标签词典：每个标签出现在几本书、哪些书
                                （用来判断「这个标签有没有区分度」）

关键约束：抽取不出内容层标签的书，字段留空数组并写明 reason，
不填占位值、不编造。前端据此显示「未做」而不是显示一张空表。
"""
import collections
import os, io, json, sys, re
import paths as P

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tags as T
from cards import content_evidence_segment

OUT = P.OUT
LIB = P.LIB

# 八层定义，供前端渲染顺序与说明
LAYERS = [
    {'id': 'L5', '名': '能力', '问': '这本书能拿出什么产物'},
    {'id': 'L6', '名': '概念', '问': '书里哪一段在讲道理（论断段定位器）'},
    {'id': 'L7', '名': '议题', '问': '这本书能对上哪些现代议题（今用判断，非作者分类）'},
    {'id': 'L4', '名': '内容', '问': '书里写了什么（必须读正文才拿得到）'},
    {'id': 'L3', '名': '类型', '问': '属于哪一类书'},
    {'id': 'L2', '名': '语体', '问': '用什么语言写的'},
    {'id': 'L1', '名': '结构', '问': '怎么编的'},
    {'id': 'L0', '名': '原文', '问': '有多少字、可不可检索'},
]


def jl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in io.open(path, encoding='utf-8') if l.strip()]


def jf(path, default=None):
    if not os.path.exists(path):
        return default
    return json.load(io.open(path, encoding='utf-8'))


def _evidence_by_anchor(rows):
    out = {}
    for row in rows:
        if not content_evidence_segment(row):
            continue
        for key in (row['id'], row.get('锚点')):
            if key:
                out[key] = row
    return out


def _checked_quote(evidence, anchor, quote):
    row = evidence.get(anchor)
    cleaned = re.sub(r'\s+', '', quote or '')
    return bool(row and cleaned and cleaned in re.sub(r'\s+', '', row.get('文本') or ''))


def _understanding_topics(code, evidence, known):
    document = jf(f'{OUT}/{code}/understanding.json', {}) or {}
    state = (document.get('processing') or {}).get('themes') or {}
    if state.get('source_stale') or state.get('status') == 'stale' or (document.get('stale') and not state):
        return []
    out = []
    for item in document.get('themes') or []:
        title = str(item.get('议题') or '').strip()
        quote, anchor = item.get('quote'), item.get('seg')
        if not title or title in known or not _checked_quote(evidence, anchor, quote):
            continue
        known.add(title)
        out.append({'标签': title, '类': '阅读议题', '来源': '判断', '性质': '原文归纳',
                    '验证': '可查看支持这项判断的原文', '状态': '待核对', '锚点': anchor,
                    '原文': quote, '情绪词': [], '受众词': []})
    return out


_CONTENT_CARD_FIELDS = {
    '概念候选': ('术语', '词条'),
    '释义候选': ('释义', '词条'),
    '条目候选': ('条目', '条目名'),
}


def _card_content_tags(cards, evidence):
    labels, seen = [], set()
    for card in cards:
        kind = _CONTENT_CARD_FIELDS.get(card.get('类型'))
        if not kind or not card.get('可回查'):
            continue
        label_type, field = kind
        name = str((card.get('字段') or {}).get(field) or '').strip()
        quote, anchor = card.get('原文'), card.get('锚点')
        key = (label_type, name)
        if not name or key in seen or not _checked_quote(evidence, anchor, quote):
            continue
        if label_type == '条目' and evidence[anchor].get('source_structure_suspect'):
            continue
        seen.add(key)
        labels.append({'标签': name, '类': label_type, '来源': '抽取', '状态': '待核对',
                       '验证': '查看这条内容在书中的原文', '锚点': anchor, '原文': quote})
    return labels


def build_one(cat, catalog):
    """一本书 → 八层标签。所有数字都从产物实测取，不 hardcode。"""
    code = cat['码']
    segments = T.segments(code)
    evidence = _evidence_by_anchor(segments)
    audit = cat.get('结构审计') or {}
    pages = {row.get('source_page') for row in segments if row.get('source_page')}
    picture_pages = set(audit.get('图片为主正文页') or [])
    image_based = bool(picture_pages and len(picture_pages) * 2 >= len(pages))
    outline = jl(f'{OUT}/{code}/outline.jsonl')
    names = jl(f'{OUT}/{code}/names.jsonl')
    people = jl(f'{OUT}/{code}/people.jsonl')
    qupai = jl(f'{OUT}/{code}/qupai.jsonl')
    kejie = jl(f'{OUT}/{code}/kejie.jsonl')
    argu = jl(f'{OUT}/{code}/argu.jsonl')
    prod = cat.get('产物', {})

    # L5 能力
    cap = T.capability_tags(prod, cat.get('已做卡片'))

    # L4 内容（抽不出来就空着并说明）
    titles = [t for t in T.content_titles(outline)
              if t['锚点'] in evidence and not evidence[t['锚点']].get('source_structure_suspect')]
    # 引用书目：先把本书自己的书名去掉（自己出现在封面页不算「引用」），
    # 再排除纯目录篇目名（目录里列自己篇名会被误认成引用别的书）
    # 自引过滤：本书书名、以及同丛书的分册名（神曲三册互指）都算自己
    own = re.sub(r'^\d{4}版', '', cat['书'])
    own = re.sub(r'[:：].*$', '', own).strip()
    # 去掉「-1地狱」「-2净界」这类分册后缀，取主书名
    main_title = re.sub(r'-\d.*$', '', own).strip()
    self_names = {own, main_title}
    # 同主书名的其它分册也算自引
    for c in catalog:
        t = re.sub(r'^\d{4}版', '', c['书'])
        t = re.sub(r'[:：].*$', '', t).strip()
        if re.sub(r'-\d.*$', '', t).strip() == main_title:
            self_names.add(t)
            self_names.add(re.sub(r'-\d.*$', '', t).strip())
            # 分册后缀本身（神曲-1地狱 → 「地狱」）也是自己，不是引用
            mm = re.search(r'-\d(.+)$', t)
            if mm:
                self_names.add(mm.group(1).strip())
    books = [b for b in T.cited_books(names) if b['标签'] not in self_names]
    pers = T.person_names(names, people)
    cards = jl(f'{OUT}/{code}/cards.jsonl')
    marks = []
    for card in cards:
        if card.get('类型') not in ('曲牌候选', '科介候选') or card.get('抽取项') != '曲牌科介':
            continue
        quote, anchor = card.get('原文'), card.get('锚点')
        if _checked_quote(evidence, anchor, quote):
            title = '曲牌' if card['类型'] == '曲牌候选' else '科介'
            name = card.get('字段', {}).get(title)
            if name:
                marks.append({'标签': name, '类': title, '来源': '抽取', '状态': '待核对',
                              '验证': '查看对应的舞台提示和所在章节', '锚点': anchor, '原文': quote})
    if not marks and not cat.get('内容检查') and prod.get('qupai'):
        marks = T.drama_marks(qupai, kejie)

    # L6 概念层 —— 论断段定位器
    # 这一层的标签**不是概念名**，而是「这一篇里有 N 段在讲道理」。
    # 为什么这么设计：实测定型句式抽不出可信的概念名（五条路全不通，
    # 见 concepts.py），硬摆一个「主题词表」就是造假。但「哪一篇在议论」
    # 是能数准的，且正好是热点召回的第一步。
    # 标签粒度按篇聚合，不按段 —— 一段一标签会让词典塞满 887 条，
    # 既不能筛也看不出区分度（每本都有一堆）。
    concept = []
    if argu:
        byp = {}
        for r in argu:
            row = evidence.get(r.get('锚点'))
            if row and not row.get('source_structure_suspect') and _checked_quote(evidence, r.get('锚点'), r.get('原文')):
                byp.setdefault(r.get('篇', ''), []).append(r)
        for pian, rows in byp.items():
            # 原文证据必须带上：L4 的每个标签都能点开看到引文，
            # L6 若只给个标签名，读者无法核「这一段凭什么算论断」。
            concept.append({
                '标签': f'论断篇：{pian}',
                '类': '论断篇',
                '来源': '抽取',
                '验证': f'该篇有 {len(rows)} 段含强推论标记（故曰/是以/何谓/凡…者…也）',
                '锚点': rows[0]['锚点'],
                '值': f'{len(rows)} 段',
                '原文': rows[0]['原文'],
            })
    concept_gap = '' if concept else '本次未找到可回原文的论断段'

    # L7 议题 —— 接引用层的热点匹配。
    # 与 L4 的分工：L4 是「书里出现了哪些专名」（客观，可数）；
    # L7 是「这本书可以被归到哪些现代议题」（今用判断，须标明不是作者分类）。
    # 每条都带整句原文 + 锚点，点开能看到出处，这是它敢被叫「标签」的唯一理由。
    topic = []
    for g in (cat.get('议题') or []):
        if not _checked_quote(evidence, g.get('锚点'), g.get('原文')):
            continue
        topic.append({
            '标签': g['议题'],
            '类': g['代号'],
            '来源': '判断',          # 不是实测也不是抽取，是整理者的义类归属
            '验证': g['依据'],
            '锚点': g['锚点'],
            '值': f"{g['命中数']} 段",
            '原文': g['原文'],
            '情绪词': g['情绪词'],
            '受众词': g['受众词'],
            '性质': g['性质'],
            '论断段数': g.get('论断段数', 0),
        })
    topic.extend(_understanding_topics(code, evidence, {row['标签'] for row in topic}))
    topic_gap = '' if topic else '本次未找到有原文依据的议题'

    content, content_gap = _card_content_tags(cards, evidence), None
    if titles:
        content += titles
    if books:
        content += books
    if pers:
        content += pers
    if marks:
        content += marks
    # 图鉴型：L4 出「科名」标签。物种名有 574 个，逐个做成标签只会在
    # 词典里刷屏又不能筛；科名（50 来个）才是能用来分组检索的粒度。
    if prod.get('entries'):
        fams = collections.Counter()
        for c in cards:
            f = c.get('字段') or {}
            if f.get('科名'):
                fams[f['科名']] += 1
        for fam, n in fams.most_common():
            content.append({'标签': fam, '类': '科名', '来源': '抽取',
                            '验证': f'该科 {n} 个物种条目', '值': f'{n} 种'})
    if not content:
        content_gap = '本次未找到可核对的篇名、引用书目或人物线索'
    else:
        # 明确记录哪些子类没取到，不让人以为是空的
        missing = []
        if not titles:
            missing.append('篇名')
        if not books:
            missing.append('引用书目')
        if not pers:
            missing.append('人物')
        if missing:
            content_gap = '未抽出：' + '、'.join(missing)

    # L3 类型
    kind = [{'标签': f"{cat['原型']} {cat['原型名']}", '类': '原型',
             '来源': '判断', '验证': '；'.join(cat.get('依据') or []),
             '状态': f"置信{cat.get('置信')}"}] if cat.get('原型') and not image_based else []
    for mix in (cat.get('混合') or []) if not image_based else []:
        # 混合结构是 [原型码, 块数] 的二元组
        if isinstance(mix, (list, tuple)) and len(mix) == 2:
            kind.append({'标签': f"混入 {mix[0]}", '类': '混合结构', '来源': '判断',
                         '验证': f'{mix[0]} 结构占 {mix[1]} 块', '状态': '待确认'})
        else:
            kind.append({'标签': '混合结构', '类': '混合结构', '来源': '判断',
                         '验证': str(mix), '状态': '待确认'})

    # L2 语体
    style = [] if image_based else T.style_tags(cat['特征'])

    # L1 结构 —— 只出类型标签。字数段数这类「每本书都不一样」的数字
    # 不是标签，是属性；做成标签会让词典里塞满只属于一本书的条目，
    # 既不能筛选也看不出区别（实测：词典前 20 行全是「100,405 汉字」）。
    struct = []
    unit = cat['结构单位']
    if cat['篇数'] >= 2 and not audit.get('结构待复核') and not image_based:
        struct.append({'标签': f'按{unit}分编', '来源': '实测',
                       '验证': f"结构模式 {cat['结构模式']}，{unit} {cat['篇数']} 个",
                       '值': f"{cat['篇数']} {unit}"})
    # L0 原文 —— 采集质量才是标签，字数只是属性
    retention = cat['保留率']
    suspect = audit.get('异常') or audit.get('破损正文段') or image_based or retention < 95
    raw = [{'标签': '原文待核对' if suspect else '文字已整理', '来源': '实测',
            '验证': '已整理文字占比，阅读顺序和出处请回原书核对', '值': f'{retention}%'}]

    for labels in (content, concept, topic):
        for item in labels:
            page = (evidence.get(item.get('锚点')) or {}).get('source_page')
            if page:
                item['source_page'] = page

    return {
        '书': cat['书'], '码': code,
        'L5': cap, 'L6': concept, 'L6缺口': concept_gap,
        'L7': topic, 'L7缺口': topic_gap,
        'L4': content, 'L4缺口': content_gap,
        'L3': kind, 'L2': style, 'L1': struct, 'L0': raw,
        # 供筛选/排序用的扁平字段
        '原型': cat['原型'], '原型名': cat['原型名'],
        '汉字': cat['汉字'], '段数': cat['段数'], '篇数': cat['篇数'],
        '特征': cat['特征'], '保留率': cat['保留率'],
        '强证据人物数': cat.get('强证据人物数', 0),
        '可出关系图谱': cat.get('可出关系图谱', False),
        '卡片': cat.get('已做卡片') or [],
    }


def main():
    catalog = jf(f'{LIB}/catalog.json', [])
    if not catalog:
        print('catalog.json 不存在，先跑 export.py'); return

    books = [build_one(c, catalog) for c in catalog]

    # 标签倒排：只收有区分度的（出现在 ≥1 本书；出现太广的标注出来）
    from collections import defaultdict
    idx = defaultdict(list)
    origins = defaultdict(set)
    for b in books:
        seen = set()
        for lay in ('L5', 'L6', 'L7', 'L4', 'L3', 'L2', 'L1', 'L0'):
            for t in b[lay]:
                name = t['标签']
                origins[name].add(t['来源'])
                if name not in seen:
                    idx[name].append({'书': b['书'], '码': b['码'], '层': lay})
                    seen.add(name)

    tag_dict = []
    for name, rows in idx.items():
        tag_dict.append({
            '标签': name, '书数': len(rows), '层': rows[0]['层'],
            '来源': next(iter(origins[name])) if len(origins[name]) == 1 else '混合',
            '书': [r['书'] for r in rows],
            # 区分度：只在少数书出现 → 有区分度；20 本都有 → 没区分度
            '区分度': ('强' if len(rows) <= 3 else
                       '中' if len(rows) <= 8 else '弱'),
        })
    tag_dict.sort(key=lambda x: (-x['区分度'].count('强'), -x['书数'], x['标签']))

    with io.open(f'{LIB}/tags.json', 'w', encoding='utf-8') as fp:
        json.dump({'层级说明': LAYERS, '书': books}, fp, ensure_ascii=False, indent=1)
    with io.open(f'{LIB}/tag_index.json', 'w', encoding='utf-8') as fp:
        json.dump({k: v for k, v in idx.items()}, fp, ensure_ascii=False, indent=1)
    with io.open(f'{LIB}/tag_dict.json', 'w', encoding='utf-8') as fp:
        json.dump(tag_dict, fp, ensure_ascii=False, indent=1)

    # 统计
    n_tag = sum(len(b[k]) for b in books for k in ('L5', 'L6', 'L7', 'L4', 'L3', 'L2', 'L1', 'L0'))
    no_content = [b['书'] for b in books if not b['L4']]
    print(f'标签总数 {n_tag}，去重后 {len(idx)} 个')
    print(f'有区分度的标签（≤3 本书）: {len([t for t in tag_dict if t["区分度"] == "强"])}')
    print(f'内容层为空的书: {len(no_content)} 本')
    for x in no_content:
        print('   ×', x)
    print(f'\n按层统计:')
    for lay in ('L5', 'L6', 'L7', 'L4', 'L3', 'L2', 'L1', 'L0'):
        n = sum(len(b[lay]) for b in books)
        ub = len({t['标签'] for b in books for t in b[lay]})
        print(f'  {lay}: {n:>4} 条 / 去重 {ub:>3} 个')


if __name__ == '__main__':
    main()
