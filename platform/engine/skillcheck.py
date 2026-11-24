# -*- coding: utf-8 -*-
"""核对文档里的数字与 library/ 实际数据是否一致。

2026-11-09 新增。起因：skill 停在 11-07 下午，当晚又跑了两轮
（拒判清零 5,684→7,218、加 L7 议题层），文档数字全部过期却没报错。
这个项目最贵的一类错误是「数字看着对、其实对不上」，所以把核对写成脚本。

  python3 skillcheck.py          # 对不上就返回 1
"""
import io, json, os, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P

SKILL = os.path.join(P.ROOT, '.workbuddy', 'skills', 'book-distill', 'SKILL.md')


def load():
    cards = [json.loads(l) for l in io.open(
        os.path.join(P.LIB, 'cards_candidate.jsonl'), encoding='utf-8')]
    cat = json.load(io.open(os.path.join(P.LIB, 'catalog.json'), encoding='utf-8'))
    tags = json.load(io.open(os.path.join(P.LIB, 'tags.json'), encoding='utf-8'))
    return cards, cat, tags


def main():
    cards, cat, tags = load()
    n = len(cards)
    books = len(cat)
    by = collections.Counter(c['资产性质'] for c in cards)
    proto = collections.Counter(c['原型'] for c in cards)
    lay = collections.Counter()
    for b in tags['书']:
        for L in ('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7'):
            lay[L] += len(b.get(L) or [])
    l7_books = sum(1 for b in tags['书'] if b.get('L7'))
    weak = sum(1 for b in cat if not (b.get('强证据人物数') or 0))
    min_ret = min(b['保留率'] for b in cat)
    meta = proto_meta = sum(1 for c in cards if c['类型'] in ('引书候选', '篇目候选'))

    skill = io.open(SKILL, encoding='utf-8').read()

    # (标签, 数据应显示为, 文档里应能查到的片段)
    targets = [
        (SKILL, 'SKILL', [
            ('候选卡总数', f'{n:,}', f'**{n:,}** 条'),
            ('可直接用', f'{by["可直接用"]:,}', f'| **{by["可直接用"]:,}** |'),
            ('需人筛', f'{by["需人筛"]:,}', f'| **{by["需人筛"]:,}** |'),
            ('仅定位器', f'{by["仅为定位器"]:,}', f'| **{by["仅为定位器"]:,}** |'),
            ('书数', f'{books} 本', f'{books} 本'),
            ('标签合计', f'{sum(lay.values()):,}', f'八层 {sum(lay.values()):,} 条'),
            ('L7 条数', str(lay['L7']), f'L7 议题层 {lay["L7"]} 条'),
            ('L7 覆盖书数', str(l7_books), f'{l7_books} 本'),
            ('P4 候选卡', f'{proto["P4"]:,}', f'| {proto["P4"]:,} |'),
            ('P10 候选卡', f'{proto["P10"]:,}', f'| {proto["P10"]:,} |'),
            ('保留率最低', f'{min_ret}', f'{min_ret}%'),
        ]),
        (os.path.join(P.ROOT, '图书分类与产物-定稿.md'), '定稿', [
            ('候选卡/本数', f'{n:,}', f'**{n:,} 条 / {books} 本**'),
            ('可直接用', f'{by["可直接用"]:,}', f'**可直接用 {by["可直接用"]:,} 条**'),
            ('保留率破线', f'{min_ret}', f'{min_ret}%'),
            ('无强证据书数', f'{weak}', f'**{weak} 本**'),
        ]),
        (os.path.join(P.ROOT, '什么书能蒸馏什么-产出规格.md'), '产出规格', [
            ('候选卡总数', f'{n:,}', f'**{n:,} 条候选卡**'),
            ('元数据', f'{meta:,}', f'元数据 {meta:,} 条'),
            ('知识单元', f'{n - meta:,}', f'知识单元 {n - meta:,} 条'),
        ]),
    ]

    bad = total = 0
    for path, label, items in targets:
        body = io.open(path, encoding='utf-8').read()
        for name, shown, needle in items:
            total += 1
            ok = needle in body
            print(('  ok  ' if ok else ' FAIL ')
                  + f'{label} · {name}: 数据 {shown} / 查「{needle}」')
            bad += 0 if ok else 1
        print('')

    print(f'{total - bad}/{total} 项一致')
    if bad:
        print('文档与 library/ 数据不一致，先改文档再对外报数。')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
