#!/usr/bin/env python3
"""第 2 期页面结构首轮结果：Markdown + Excel。"""
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
OUT = ROOT / 'platform' / 'out'
CODES = ['B56', 'B58', 'B59', 'B60']
ROLE_ORDER = ['封面', '版权页', '书名页', '目录', '前言', '正文内容',
              '标题层级', '后记', '附录', '参考文献', '索引', '勘误表']
MD = BASE / '第2期_页面结构_首轮结果.md'
XLSX = BASE / '第2期_页面结构_首轮结果.xlsx'

HEAD_FILL = PatternFill('solid', fgColor='1F4E79')
HEAD_FONT = Font(color='FFFFFF', bold=True, size=10)
WRAP = Alignment(wrap_text=True, vertical='top')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STATUS_FILL = {
    'found': PatternFill('solid', fgColor='E2EFDA'),
    'needs_review': PatternFill('solid', fgColor='FFF2CC'),
    'not_found': PatternFill('solid', fgColor='F2F2F2'),
    'not_applicable': PatternFill('solid', fgColor='F2F2F2'),
}


def load(c):
    p = OUT / c / 'page_roles.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def role(rec, name):
    return next(r for r in rec['roles'] if r['name'] == name)


def span_text(name, r):
    if r['status'] != 'found' or not r['spans']:
        return ''
    sp = r['spans']
    if name == '标题层级':
        return '%d 条（%d 页有页码）' % (r.get('heading_total', len(sp)), len(sp))
    if len(sp) == 1:
        a, b = sp[0]['from'], sp[0]['to']
        return 'p%d' % a if a == b else 'p%d–%d' % (a, b)
    return '；'.join(('p%d' % s['from']) if s['from'] == s['to'] else ('p%d–%d' % (s['from'], s['to']))
                     for s in sp)


def build():
    recs = {c: load(c) for c in CODES}
    assert all(recs.values()), '缺少 page_roles.json，请先跑 pages.py'

    stats = {c: recs[c]['stats'] for c in CODES}
    total_found = sum(stats[c]['found'] for c in CODES)
    total = len(ROLE_ORDER) * len(CODES)

    L = []
    A = L.append
    A('# 第 2 期（页面结构 12 项）首轮结果\n')
    A('> 运行：`python3 platform/engine/pages.py --all`')
    A('> 输入是 `书库分类/raw/<书名>.layout.jsonl`（每页每行的文字、坐标、行类型）；不改版面、不改切分。\n')
    A('## 一、总表\n')
    A('| # | 结构 | ' + ' | '.join({'B56': 'B56 图鉴', 'B58': 'B58 小王子',
                                     'B59': 'B59 纪事', 'B60': 'B60 廉洁故事'}[c] for c in CODES) + ' |')
    A('|---|---|' + '---|' * len(CODES))
    for i, name in enumerate(ROLE_ORDER, start=1):
        cells = []
        for c in CODES:
            r = role(recs[c], name)
            cells.append(span_text(name, r) if r['status'] == 'found' else '')
        A('| %d | %s | ' % (i, name) + ' | '.join(cells) + ' |')
    A('')
    A('## 二、统计\n')
    A('| 书 | 识别到的结构 | 正文范围 | 标题数 |')
    A('|---|---|---|---|')
    for c in CODES:
        s = stats[c]
        A('| %s | %d / 12 | p%s–%s | %d |' % (
            {'B56': 'B56 图鉴', 'B58': 'B58 小王子', 'B59': 'B59 纪事', 'B60': 'B60 廉洁故事'}[c],
            s['found'], s['body_from'], s['body_to'], s['headings']))
    A('| **合计** | **%d / %d** | — | — |' % (total_found, total))
    A('')
    A('## 三、一眼看懂\n')
    A('- **四本都能判的**：目录、前言、正文、标题层级。')
    A('- **三本有版权页**：B56 p4、B58 p151–152（CIP 印在书末）、B60 p3；B59 没有版权页。')
    A('- **书名页只认出 B56 p1**：B58/B59 前几页是空白或纯图，B60 只有“·石家庄·”，文字层认不出。')
    A('- **封面 0/4**：这几本的封面是图像，PDF 文字层没有封面文字。按约定第 3 期不做图片，所以封面只能等页面图或人工指定。')
    A('- **后记只有 B60 p283**；附录、参考文献、索引、勘误表四本都没有，用假页面测试验证了规则。')
    A('')
    A('## 四、几个关键判断（可核对）\n')
    A('- **B58**：目录 p3；“导读”长篇 5–26 归前言；正文 p27 起（p27 题名、p28 题献、p29 Chapter 01）；CIP/出版信息在 p151–152，所以正文止于 p150。')
    A('- **B60**：目录 10–14；前言 6–8；正文 16 起（章前图版算正文）；后记 p283，正文止于 p282。')
    A('- **B59**：序言 9–10；目录 11–12；正文 p13 起（李四光资料页）；37 位人物篇标题全部映射到页。')
    A('- **B56**：书名页 p1、版权页 p4、目录 6–40（图鉴的物种目录很长）、正文 42 起；14 章标题映射到页。')
    A('')
    A('## 五、已知限制\n')
    A('- 封面、纯图页、章前图版依赖页面图；文字层只能判有字的部分。')
    A('- 标题层级只按“第X章/Chapter”和篇名映射，**没有用字号**，所以只能算一层，不能区分章/节字号层级。')
    A('- 一页可以同时属于两个结构（如 B56 p4 既是版权页又是前言），spans 允许重叠；不是互斥分区。')
    A('- 附录/参考文献/索引/勘误在四本书里不存在，规则只用假页面验证过，等真实样本再调。')
    A('')
    A('## 六、文件\n')
    A('| 文件 | 内容 |')
    A('|---|---|')
    A('| platform/engine/pages.py | 页面结构识别器 |')
    A('| platform/engine/test_pages.py | 4 本真书 + 假页面回归测试 |')
    A('| platform/out/<书>/page_roles.json | 每本书的结构区间、证据、标题 |')
    A('')
    MD.write_text('\n'.join(L), encoding='utf-8')

    # Excel
    wb = Workbook()
    ws = wb.active
    ws.title = '结果矩阵'
    head = ['#', '结构'] + [{'B56': 'B56 图鉴', 'B58': 'B58 小王子',
                             'B59': 'B59 纪事', 'B60': 'B60 廉洁故事'}[c] for c in CODES]
    ws.append(head)
    widths = [5, 12, 40, 40, 36, 36]
    for i, name in enumerate(ROLE_ORDER, start=1):
        row = [i, name]
        for c in CODES:
            r = role(recs[c], name)
            row.append(span_text(name, r) if r['status'] == 'found' else '')
        ws.append(row)
        for j in range(1, len(head) + 1):
            ws.cell(row=ws.max_row, column=j).alignment = WRAP
        ws.row_dimensions[ws.max_row].height = 30
    for j in range(1, len(head) + 1):
        cell = ws.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = WRAP
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = 'C2'

    ws2 = wb.create_sheet('明细')
    head2 = ['书码', '书', '结构', '状态', '区间', '置信', '方法', '证据页', '证据原文', '备注']
    ws2.append(head2)
    for c in CODES:
        for name in ROLE_ORDER:
            r = role(recs[c], name)
            ev = (r.get('evidence') or [{}])[0]
            ws2.append([c, recs[c]['book'], name, r['status'], span_text(name, r),
                        r['confidence'], r['method'], ev.get('page', ''), ev.get('quote', ''), r.get('note', '')])
            for j in range(1, len(head2) + 1):
                ws2.cell(row=ws2.max_row, column=j).alignment = WRAP
            ws2.cell(row=ws2.max_row, column=4).fill = STATUS_FILL.get(r['status'], PatternFill())
    for j in range(1, len(head2) + 1):
        cell = ws2.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
    for j, w in enumerate([7, 28, 12, 12, 26, 6, 8, 8, 52, 34], start=1):
        ws2.column_dimensions[get_column_letter(j)].width = w
    ws2.freeze_panes = 'C2'
    ws2.auto_filter.ref = 'A1:J%d' % ws2.max_row

    ws3 = wb.create_sheet('标题')
    head3 = ['书码', '层级', '标题', '页码', '段锚点', '置信']
    ws3.append(head3)
    for c in CODES:
        for h in recs[c].get('headings') or []:
            ws3.append([c, h.get('level'), h.get('title'), h.get('page'), h.get('seg'), h.get('confidence')])
    for j in range(1, len(head3) + 1):
        cell = ws3.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
    for j, w in enumerate([7, 6, 60, 8, 18, 6], start=1):
        ws3.column_dimensions[get_column_letter(j)].width = w
    ws3.freeze_panes = 'A2'
    ws3.auto_filter.ref = 'A1:F%d' % ws3.max_row

    wb.save(XLSX)
    print('written', MD.name, XLSX.name)
    print('stats', stats)


if __name__ == '__main__':
    build()
