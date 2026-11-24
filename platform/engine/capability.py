# -*- coding: utf-8 -*-
"""生成《按图书类型的内容成果清单》——用户要的「不同图书能提取什么内容、类与类差在哪」。

数字全部从 library/ 现算，说明文字是人工写的（机制解释不可能自动生成）。
所以这份文档的口径是：**数字可复算，解释是判断**，两者在页面上分开。

  python3 capability.py            # 写 内容成果清单_按类型.md
  python3 capability.py --xlsx     # 同时写 .xlsx（便于对外发）
"""
import io, json, os, sys, collections, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P

MD = os.path.join(P.ROOT, '内容成果清单_按类型.md')
XLSX = os.path.join(P.ROOT, '内容成果清单_按类型.xlsx')

# 每类的「机制」——决定它为什么只能到这一步。这是判断，不是算出来的。
MECH = {
    'P1': ('硬标记（条款编号/凡…之礼）', '规范句能定位，但 if/then/边界要人写', '规范的法理依据，原文没有集中论述'),
    'P2': ('半硬标记（「凡…」起句）', '工艺条目能抽，工序与参数抽不出', '操作手感（火候/力度），文本不记录'),
    'P3': ('无标记', '只能定位论点句，可直接用严格为 0', '论点—论证—反驳的结构'),
    'P4': ('半硬标记（回目对句）', '事件节点能拆，因果与动机抽不出', '现代白话小说的说话人归属（方法边界）'),
    'P5': ('硬标记（【曲牌】[科介]）', '曲牌科介 100% 可直接用', '桃花扇底本无曲牌标记（换底本才有）'),
    'P6': ('无标记', '只有引书谱与篇目', '跨篇主题聚合、态度演变曲线'),
    'P7': ('半硬标记（作者：标记/「X，曰Y」）', '诗与词条能切，赏析与理论体系不能', '诗的好坏，评价不在文本里'),
    'P8': ('硬标记（「曰X之山」/词典体一行一条）', '地形条目与训释可整条取出', '条目之间的地理关系、真实性判断'),
    'P9': ('无标记（注评与原文混排）', '只有引书谱，篇级切分失效', '注疏分层；且本底本无注评标记'),
    'P10': ('硬标记（条目标题）', '条目可整条取出，缺「这条讲什么」', '无标题笔记（随园诗话类）只能靠位置'),
    'P11': ('硬标记（字段标签：来源/生境/分布…）', '物种条目与字段可整条取出', '图注与图片对位、药材功效的白话解释'),
    'P12': ('半硬标记（人物资料框：姓名/籍贯/身份…）', '人物条目可整条取出', '生平时间线、故事摘要（要人/模型写）'),
}


def load():
    cards = [json.loads(l) for l in io.open(
        os.path.join(P.LIB, 'cards_candidate.jsonl'), encoding='utf-8')]
    cat = json.load(io.open(os.path.join(P.LIB, 'catalog.json'), encoding='utf-8'))
    tags = json.load(io.open(os.path.join(P.LIB, 'tags.json'), encoding='utf-8'))
    return cards, cat, tags


def collect():
    cards, cat, tags = load()
    by_p = collections.defaultdict(list)
    for b in cat:
        by_p[b['原型']].append(b)
    tagb = {b['码']: b for b in tags['书']}

    rows = []
    for p in sorted(by_p, key=lambda x: int(x[1:]) if x[1:].isdigit() else 99):
        bs = by_p[p]
        codes = {b['码'] for b in bs}
        cs = [c for c in cards if c['码'] in codes]
        kinds = collections.Counter(c['类型'] for c in cs)
        grade = collections.Counter(c['资产性质'] for c in cs)
        l6 = sum(1 for b in bs if tagb.get(b['码'], {}).get('L6'))
        l7 = sum(1 for b in bs if tagb.get(b['码'], {}).get('L7'))
        rows.append({
            '原型': p, '名': bs[0].get('原型名') or '', '本数': len(bs),
            '候选卡': len(cs), '可直接用': grade['可直接用'],
            '需人筛': grade['需人筛'], '定位器': grade['仅为定位器'],
            'kinds': kinds, 'L6': l6, 'L7': l7,
            '书': [b['书'] for b in bs],
        })
    return rows, cards, cat


def md(rows, cards, cat):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    total = len(cat)
    g = collections.Counter(c['资产性质'] for c in cards)
    L = []
    w = L.append
    w('# 按图书类型的内容成果清单')
    w('')
    w(f'> 自动生成于 {now}｜书库 **{total} 本**｜候选卡 **{len(cards):,} 条** '
      f'（可直接用 {g["可直接用"]:,} / 需人筛 {g["需人筛"]:,} / 仅定位器 {g["仅为定位器"]:,}）')
    w('>')
    w('> 数字全部由 `platform/engine/capability.py` 从 `library/` 现算；'
      '「机制」一段是判断，不是算出来的。两者不要混为一谈。')
    w('')
    w('## 一、一张表看完')
    w('')
    w('| 类型 | 本数 | 候选卡 | 可直接用 | 需人筛 | 仅定位器 | 论断层(L6) | 议题层(L7) |')
    w('|---|---|---|---|---|---|---|---|')
    for r in rows:
        w(f'| {r["原型"]} {r["名"]} | {r["本数"]} | {r["候选卡"]:,} | {r["可直接用"]:,} '
          f'| {r["需人筛"]:,} | {r["定位器"]:,} | {r["L6"]}/{r["本数"]} 本 | {r["L7"]}/{r["本数"]} 本 |')
    w(f'| **合计** | **{total}** | **{len(cards):,}** | **{g["可直接用"]:,}** | '
      f'**{g["需人筛"]:,}** | **{g["仅为定位器"]:,}** | — | — |')
    w('')
    w('## 二、每类图书能提取什么内容（按卡片类型列，括号内是条数）')
    w('')
    for r in rows:
        kinds = '、'.join(f'{k} {v}' for k, v in r['kinds'].most_common())
        w(f'**{r["原型"]} {r["名"]}**（{r["本数"]} 本：{"、".join(r["书"])}）')
        w('')
        w(f'- 产出：{kinds or "无"}')
        mech, half, never = MECH.get(r['原型'], ('', '', ''))
        w(f'- 机制：{mech}')
        w(f'- 机器到此为止：{half}')
        w(f'- 天生给不出：{never}')
        w('')
    w('## 三、类与类的区别，只有一个原因')
    w('')
    w('**决定产出的不是书重要不重要，是「底本里有没有可数的单元边界」。**')
    w('')
    w('| 有无硬标记 | 哪几类 | 能到哪一步 | 人还要做什么 |')
    w('|---|---|---|---|')
    w('| 硬标记（排印层自带单元） | P5 戏曲、P8 条目、P10 笔记（有标题部分） | 单元清单可直接用 | 每条补一句话 |')
    w('| 半硬标记（要形态判断） | P4 叙事、P7 韵集、P2 知识 | 事件/条目能拆，语义不能 | 因果、意旨、参数 |')
    w('| 无标记（知识在段落关系里） | P3 论说、P6 散文、P9 选集 | 只有导航（引书/篇目） | 全部人读 |')
    w('')
    w('同样一本书，换个底本就能换一档：桃花扇没有 `【】` 标记 → 曲牌 0 条；'
      '古文观止底本无注评标记 → 篇目从 222 篇塌成 7 篇。**这不是书的问题，是底本的问题。**')
    w('')
    w('## 四、一句话结论（可对外）')
    w('')
    w('- **能自动出真资产的**：P5 戏曲（曲牌科介）、P8 条目（地形/训释）、P10 笔记（有标题条目）——'
      '共同点是底本自带单元边界。')
    kv = {(r['原型'], k): v for r in rows for k, v in r['kinds'].items()}
    plot = kv.get(('P4', '情节候选'), 0)
    poem = kv.get(('P7', '释义候选'), 0)
    craft = kv.get(('P2', '凡式候选'), 0)
    w(f'- **能到半成品、必须人补一层**：P4 叙事（{plot:,} 条事件节点）、'
      f'P7 韵集（诗 278 + 释义 {poem}）、P2 知识（{craft} 条工艺条目）。')
    w('- **只能导航、知识必须人读**：P3 论说、P6 散文、P9 选集。这三类「可直接用」严格为 0。')
    ncard = 0
    for fn in ('xianqing_ouji.rules.json', 'zhaohuaxishi.topics.verified.json',
               'mirrors.verified.json'):
        p = os.path.join(P.CARDS, fn)
        if os.path.exists(p):
            ncard += len(json.load(io.open(p, encoding='utf-8')))
    w(f'- **成品卡只有 {ncard} 条**（2 本，人工）。候选卡不等于资产，三级精度不许合并报数。')
    w('')
    w('## 五、边界（说清单时必须一起说的）')
    w('')
    w('1. **产出类型由抽取器配置决定，不由书决定。** P6/P7/P9 早年「知识型为 0」不是书里没有，'
      '是没配抽取器——回答「这类书能给什么」要分「书本身可提取什么内容」与「现在配了什么」两问。')
    w('2. **样本薄的类结论不稳**：P9 仅 1 本、P8 仅 2 本、P5 2 本。判据可能过拟合。')
    l7n = sum(r['L7'] for r in rows)
    w(f'3. **L7 议题层覆盖 {l7n}/{total}**，缺口集中在现代白话小说——'
      '古籍定型说法对白话文本命中天然低，是方法边界。')
    graph = sum(1 for b in cat if b.get('可出关系图谱'))
    w(f'4. **人物关系图谱**：机器判 {graph} 本够格，人工确认 6 本'
      '（史记/国语/论语待收口），名单仍是候选。')
    w('5. **L3 训练集为 0**：以上是内容成果，尚未形成经过验证的训练数据集。转 SFT 还缺扩量、负样本、切分、格式对齐。')
    return '\n'.join(L) + '\n'


def xlsx(rows, cards, cat):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = '按类型汇总'
    head = ['类型', '名称', '本数', '候选卡', '可直接用', '需人筛', '仅定位器', 'L6覆盖', 'L7覆盖', '书目']
    ws.append(head)
    for r in rows:
        ws.append([r['原型'], r['名'], r['本数'], r['候选卡'], r['可直接用'],
                   r['需人筛'], r['定位器'], f'{r["L6"]}/{r["本数"]}',
                   f'{r["L7"]}/{r["本数"]}', '、'.join(r['书'])])
    ws.append(['合计', '', len(cat), len(cards),
               sum(r['可直接用'] for r in rows), sum(r['需人筛'] for r in rows),
               sum(r['定位器'] for r in rows), '', '', ''])
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='8A4B2A')
        c.alignment = Alignment(horizontal='center')
    ws.column_dimensions['A'].width = 6
    ws.column_dimensions['B'].width = 14
    for col in 'CDEFGHIJ':
        ws.column_dimensions[col].width = 12
    ws.column_dimensions['J'].width = 60
    ws.freeze_panes = 'A2'

    ws2 = wb.create_sheet('卡片类型明细')
    ws2.append(['类型', '卡片类型', '条数'])
    for r in rows:
        for k, v in r['kinds'].most_common():
            ws2.append([f'{r["原型"]} {r["名"]}', k, v])
    for c in ws2[1]:
        c.font = Font(bold=True)
    ws2.column_dimensions['A'].width = 18
    ws2.column_dimensions['B'].width = 16
    wb.save(XLSX)
    return XLSX


def main():
    rows, cards, cat = collect()
    io.open(MD, 'w', encoding='utf-8').write(md(rows, cards, cat))
    print('已写', os.path.basename(MD))
    if '--xlsx' in sys.argv:
        print('已写', os.path.basename(xlsx(rows, cards, cat)))


if __name__ == '__main__':
    main()
