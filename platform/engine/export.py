# -*- coding: utf-8 -*-
"""资产汇总导出：把各书的稳定层 + 已确认的半稳定层卡片
汇总成平台可直接调用的库。

产物：
  library/catalog.json      书目录（每本书的判型、可用产物、质检结论）
  library/segments.jsonl    全书片段（跨书统一，带书码与锚点）
  library/rules.jsonl       规则卡（仅已通过质检的）—— 人工确认
  library/topics.jsonl      主题卡（数字已实测填充）—— 人工确认
  library/mirrors.jsonl     易错对照 —— 人工确认
  library/cards_candidate.jsonl  候选卡（机器抽，未确认）—— **单独成表**
  library/manifest.json     总清单与统计

候选卡为什么必须单独一张表：它们的「字段」是抽取器填的，
不是人写的。混进 rules/topics 会让下游把机器推断当人工确认，
这是本项目最不能犯的错。两张表，两个可信度，不许合并。
"""
import os, io, json, glob
import paths as P

OUT = P.OUT
CARDS = P.CARDS
LIB = P.LIB

# 哪些书已做出半稳定层卡片，各自是什么
CARDED = {
    'B01': {'书': '闲情偶寄', '规则卡': 'xianqing_ouji.rules.json'},
    'ZHS': {'书': '朝花夕拾', '主题卡': 'zhaohuaxishi.topics.verified.json'},
}


def confirmed_cards(book):
    """Historical signed-off packs only belong to their original title and book code."""
    code, title = book['code'], book['book']
    configured = CARDED.get(code, {})
    if configured.get('书') != title:
        return {}
    return {label: rows for label, filename in configured.items() if label != '书'
            and (rows := jf(os.path.join(CARDS, filename)) or [])}


def jl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in io.open(path, encoding='utf-8') if l.strip()]


def jf(path):
    if not os.path.exists(path):
        return None
    return json.load(io.open(path, encoding='utf-8'))


def main():
    os.makedirs(LIB, exist_ok=True)
    books = jf(f'{OUT}/books.json') or []

    catalog, all_seg, all_card = [], [], []
    rules, topics, mirrors = [], [], []
    for b in books:
        code = b['code']
        segs = jl(f'{OUT}/{code}/segments.jsonl')
        all_seg.extend(segs)
        crows = jl(f'{OUT}/{code}/cards.jsonl')
        all_card.extend(crows)
        idx = jl(f'{OUT}/{code}/outline.jsonl')
        nm = jl(f'{OUT}/{code}/names.jsonl')
        ppl = jl(f'{OUT}/{code}/people.jsonl')
        qp = jl(f'{OUT}/{code}/qupai.jsonl')
        kj = jl(f'{OUT}/{code}/kejie.jsonl')

        # 该书实际可交付的产物（按能力等级标注，不虚报）
        # 曲牌/科介索引只对戏曲型（P5）有产物意义。
        # 闲情偶寄讲词曲时会举曲牌为例，抽出 32 条【金索挂梧桐】之类，
        # 若列成「已交付产物」，会让人误判这本书是剧本结构。
        is_drama = b['原型'] == 'P5'
        checks = b.get('内容检查') or {}
        drama_cards = [c for c in crows if c.get('抽取项') == '曲牌科介']
        done = {
            'segments': len(segs) > 0,
            'outline': len(idx) > 0,
            'names': len(nm) > 0,
            # 人物候选是半稳定层：只有强证据够数才算「有」，
            # 否则「古人/孔子」这类 2 条噪声会被显示成已交付产物。
            'people': b['强证据人物数'] >= 6,
            'qupai': (any(c['类型'] == '曲牌候选' for c in drama_cards) if checks else is_drama and bool(qp)),
            'kejie': (any(c['类型'] == '科介候选' for c in drama_cards) if checks else is_drama and bool(kj)),
            '_qupai_raw': len(qp),      # 原始抽到多少，仅备查不外显
        }
        card = confirmed_cards(b)
        if card.get('规则卡'):
            done['rules'] = True
            rules.extend(dict(row, 码=code) for row in card['规则卡'])
        if card.get('主题卡'):
            done['topics'] = True
            topics.extend(dict(row, 码=code) for row in card['主题卡'])
        # 候选卡单独一个键，绝不并进 rules/topics：
        # 「有候选」和「有确认卡」是两回事，合并显示就是把机器推断冒充人工成果。
        done['cards_candidate'] = len(crows) > 0
        done['entries'] = any(c.get('类型') == '物种条目' and c.get('可回查') for c in crows)

        catalog.append({
            '书': b['book'], '码': code, '源文件': b['源文件'],
            '原型': b['原型'], '原型名': b['原型名'], '置信': b['置信'],
            '稳定性': b.get('稳定性'),
            '拒判': b.get('拒判', False), '拒判性质': b.get('拒判性质'),
            '依据': b['依据'], '混合': b['混合'],
            '吻合': b.get('吻合'), '合集': b.get('合集') or [],
            '结构模式': b['结构模式'], '结构单位': b['结构单位'],
            '篇数': b['篇数'], '段数': b['段数'],
            # 篇名质量：引用层能否「按篇回溯」的前提。
            # 必须区分「书无篇名」（书的体例）与「抽取失败」（工程缺陷），
            # 否则四世同堂（原作者只分节不写标题）会被误报成我们没抽到。
            '篇名质量': b.get('篇名质量') or {},
            '汉字': b['汉字_切段'], '保留率': b['保留率'],
            '强证据人物数': b['强证据人物数'],
            '可出关系图谱': b['可出关系图谱'], '图谱判定': b['图谱判定'],
            # 图谱准入的原始指标（强证据人数 / 有人段数 / 三人同段 / 场景密度）。
            # 之前只把一句「可出图谱」写进 catalog，页面上就只剩结论没有依据 ——
            # 而本项目的规矩是每个数字都要能回查到算法输出。
            '图谱指标': b.get('图谱指标') or {},
            # 人物抽取的能力边界（开关状态 + 状语形态占比 + 判定语）。
            # 让页面能区分「书里没有人物关系」与「我们的方法抽不出」。
            '人物抽取边界': b.get('人物抽取边界') or {},
            '特征': {k: b['特征'][k] for k in
                     ('R', 'D', 'A', 'Q', 'wen', 'p3', 'p1', 'savg', 'smed', 'h')},
            '产物': done,
            '已做卡片': list(card),
            '内容检查': checks,
            '结构审计': b.get('结构审计') or {},
            '候选卡数': len(crows),
            # 概念层：本层是「论断段定位器」，不是主题词表。
            # 数量 + 性质 + 边界 + 缺口四项一起落盘，
            # 缺任何一项都会让人误以为已经有可用的主题标签。
            '论断段数': b.get('论断段数') or 0,
            '概念层性质': b.get('概念层性质') or '',
            '概念层边界': b.get('概念层边界') or '',
            '概念层缺口': b.get('概念层缺口') or '',
            # 议题层：与 L4 专名不同，这一层是「今用判断」，必须整包带下去 ——
            # 每条标签都要能点开看到整句原文，否则读者无法核「凭什么说这书讲这个」。
            '议题': b.get('议题') or [],
        })

    # 卡片汇总
    mf = jf(f'{CARDS}/mirrors.verified.json') or []
    for m in mf:
        mirrors.append(m)

    def dump(name, rows):
        with io.open(f'{LIB}/{name}', 'w', encoding='utf-8') as fp:
            for x in rows:
                fp.write(json.dumps(x, ensure_ascii=False) + '\n')

    dump('segments.jsonl', all_seg)
    dump('rules.jsonl', rules)
    dump('topics.jsonl', topics)
    dump('mirrors.jsonl', mirrors)
    dump('cards_candidate.jsonl', all_card)
    with io.open(f'{LIB}/catalog.json', 'w', encoding='utf-8') as fp:
        json.dump(catalog, fp, ensure_ascii=False, indent=1)

    # 候选卡按类型分项统计，供页面与 skill 如实报数
    from collections import Counter as _C
    kind_cnt = _C(c['类型'] for c in all_card)
    manifest = {
        '书数': len(catalog),
        '汉字总数': sum(c['汉字'] for c in catalog),
        '片段总数': len(all_seg),
        '规则卡': len(rules),
        '主题卡': len(topics),
        '易错对照': len(mirrors),
        '候选卡': len(all_card),
        '候选卡按类型': dict(kind_cnt.most_common()),
        '有候选卡的书数': len([c for c in catalog if c['候选卡数'] > 0]),
        '按原型': {},
        # 能力分层必须分清三种，别把「有候选」说成「有卡」：
        #   只到检索层   —— 连候选都没有（拒判书）
        #   含候选卡     —— 机器抽了候选，无人确认
        #   含确认卡片   —— 237 条那批，人工整理、已过引文回查
        '能力分层的书数': {
            '只到检索层': len([c for c in catalog if not any(
                c['产物'].get(k) for k in ('rules', 'topics'))
                and c['候选卡数'] == 0]),
            '含候选卡': len([c for c in catalog if c['候选卡数'] > 0]),
            '含确认卡片': len([c for c in catalog if any(
                c['产物'].get(k) for k in ('rules', 'topics'))]),
        },
    }
    for c in catalog:
        k = f"{c['原型']} {c['原型名']}"
        manifest['按原型'][k] = manifest['按原型'].get(k, 0) + 1
    with io.open(f'{LIB}/manifest.json', 'w', encoding='utf-8') as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=1)

    print(json.dumps(manifest, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
