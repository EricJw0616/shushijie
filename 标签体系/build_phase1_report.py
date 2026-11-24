#!/usr/bin/env python3
"""把第 1 期 publication.json 汇总成质检报告（Markdown + Excel）。

注意：这里显示“未找到”，是为了让团队知道缺什么；交付导出不显示缺项。
"""
import json
import os
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
OUT = ROOT / 'platform' / 'out'
CODES = ['B56', 'B58', 'B59', 'B60']
MD = BASE / '第1期_出版信息_首轮结果.md'
XLSX = BASE / '第1期_出版信息_首轮结果.xlsx'

HEAD_FILL = PatternFill('solid', fgColor='1F4E79')
HEAD_FONT = Font(color='FFFFFF', bold=True, size=10)
WRAP = Alignment(wrap_text=True, vertical='top')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STATUS_FILL = {
    'found': PatternFill('solid', fgColor='E2EFDA'),
    'needs_review': PatternFill('solid', fgColor='FFF2CC'),
    'not_found': PatternFill('solid', fgColor='F2F2F2'),
}


def load(code):
    p = OUT / code / 'publication.json'
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def short(it):
    v = it.get('value')
    if it['status'] == 'not_found' or v is None:
        return ''
    if it['status'] == 'needs_review' and not v:
        return '待核'
    k = it['field']
    if k == 'author':
        ppl = v.get('people') or []
        if ppl:
            return '、'.join('%s（%s）' % (p['name'], p['role']) for p in ppl[:4]) + ('…' if len(ppl) > 4 else '')
        return v.get('raw') or ''
    if k == 'translators':
        return '、'.join('%s（%s）' % (p['name'], p['role']) for p in v)
    if k == 'book_format':
        return '；'.join('%s %s' % (x['type'], x['value']) for x in v)
    if k == 'word_count':
        return '%s（%s 字）' % (v.get('raw'), v.get('normalized')) if v.get('normalized') else '%s（待核）' % v.get('raw')
    if k == 'price':
        return v.get('raw') or ''
    if k == 'isbn':
        return '；'.join('%s %s%s' % (x['type'], x['value'], '（校验通过）' if x.get('valid') else '（校验未过）') for x in v)
    if k == 'classification':
        return '；'.join('%s %s %s' % (x.get('system'), x.get('code'), x.get('name') or '') for x in v)
    if k == 'cip_number':
        return v.get('number') or ''
    if k == 'author_bio':
        return '有（%d 字，现成简介）' % len(v)
    return str(v)


def code_names(code):
    return {'B56': 'B56 图鉴', 'B58': 'B58 小王子', 'B59': 'B59 纪事', 'B60': 'B60 廉洁故事'}[code]


def build():
    recs = {c: load(c) for c in CODES}
    assert all(recs.values()), '缺少 publication.json，请先跑 publication.py'
    fields = list(recs['B58']['items'].values())
    order = [x['no'] for x in fields]
    fields = sorted(fields, key=lambda x: x['no'])

    stats = {c: recs[c]['stats'] for c in CODES}
    total = {k: sum(stats[c][k] for c in CODES) for k in ('found', 'not_found', 'needs_review')}

    # Markdown
    L = []
    A = L.append
    A('# 第 1 期（出版信息 19 项）首轮结果\n')
    A('> 运行：`python3 platform/engine/publication.py --all --library app/data/library.json`')
    A('> 说明：本表是**质检表**，缺项显示为空；交付导出不显示缺项。\n')
    A('## 一、总表\n')
    A('| # | 项目 | ' + ' | '.join(code_names(c) for c in CODES) + ' |')
    A('|---|---|' + '---|' * len(CODES))
    for f in fields:
        cells = []
        for c in CODES:
            it = recs[c]['items'][f['field']]
            cells.append(short(it) if it['status'] != 'not_found' else '')
        A('| %s | %s | ' % (f['no'], f['name']) + ' | '.join(cells) + ' |')
    A('')
    A('## 二、统计\n')
    A('| 书 | 有值 | 待复核 | 未找到 | 合计 |')
    A('|---|---|---|---|---|')
    for c in CODES:
        s = stats[c]
        A('| %s | %d | %d | %d | 19 |' % (code_names(c), s['found'], s['needs_review'], s['not_found']))
    A('| **合计** | **%d** | **%d** | **%d** | **76** |' % (total['found'], total['needs_review'], total['not_found']))
    A('')
    A('## 三、每本缺什么\n')
    for c in CODES:
        miss = [it['name'] for it in recs[c]['items'].values() if it['status'] == 'not_found']
        review = [it['name'] for it in recs[c]['items'].values() if it['status'] == 'needs_review']
        A('- **%s**：缺 %s%s' % (code_names(c), '、'.join(miss) if miss else '无',
                                 ('；待复核 ' + '、'.join(review)) if review else ''))
    A('')
    A('## 四、缺口原因（不是规则失败）\n')
    A('1. **B58/B60 有版权页**：出版事实基本齐；缺的 5–6 项是版权页本身没印（副书名、装帧、页数、丛书、作者简介），B60 还没有译者（不是译作）。')
    A('2. **B56/B59 没有版权页**：CIP、书号、出版时间、版次、印次、字数、定价整组没有；书名/作者/出版社靠书目库导入，B56 的作者简介从封面抽到。')
    A('3. **页数一律不用 PDF 物理页数**：B56 的 PDF 有 832 页，但版权页没印页数，所以记“未找到”。这是规范要求。')
    A('')
    A('## 五、已验证的规则\n')
    A('- 作者/译者/主编/副主编拆分：B58 著+译、B60 主编2+副主编2、B59 主编+编著。')
    A('- 开本拆成“开数/成品尺寸”两条：B58 880×1230毫米 + 1/32；B60 787×1092毫米 + 1/16。')
    A('- 字数保留原文+归一：86千字→86000；250 000→250000（原文无单位，已标注）。')
    A('- ISBN-13 校验：B58/B60 通过；CIP 号保留完整年份/序号。')
    A('- 每条有值都能回到原文段（测试逐字校验通过）。')
    A('')
    A('## 六、已知限制\n')
    A('- 作者名里的拉丁原文（如 `圣埃克苏佩里（Exupery,S.）`）暂未拆成“中文名/外文名”两个字段。')
    A('- 分类名只到中图法一级（如 I565.88 → “文学”），没有细分目录，所以标“版权页+一级类目”。')
    A('- 无版权页的书，作者/出版社依赖书目库导入；没有书目库时只能留空。')
    A('- 副书名、装帧、页数、丛书这 4 项在现有 4 本书里都没有可抽原文，规则正确性还没被真实样本验证；等样书。')
    A('')
    A('## 七、下一步\n')
    A('1. 把 `publication.json` 接进书详情接口与导出（Excel + JSONL）。')
    A('2. 等样书补 20–30 本，重点验版权页变体（无“责任编辑”标签、套书页数、丛书层级）。')
    A('3. 第 2 期页面结构开工：先做“封面/版权页/书名页/目录/前言/正文/后记/附录/参考文献”9 类。')
    A('')
    MD.write_text('\n'.join(L), encoding='utf-8')

    # Excel
    wb = Workbook()
    ws = wb.active
    ws.title = '结果矩阵'
    head = ['#', '项目'] + [code_names(c) for c in CODES]
    widths = [5, 12, 32, 46, 40, 40]
    ws.append(head)
    for f in fields:
        row = [f['no'], f['name']]
        for c in CODES:
            it = recs[c]['items'][f['field']]
            row.append(short(it) if it['status'] != 'not_found' else '')
        ws.append(row)
        for j in range(1, len(head) + 1):
            ws.cell(row=ws.max_row, column=j).alignment = WRAP
        lines = 1
        for j, cell in enumerate(row):
            w = widths[j] if j < len(widths) else 30
            txt = str(cell or '')
            units = sum(2 if ord(ch) > 127 else 1 for ch in txt)
            lines = max(lines, int(units / max(4, w * 1.05)) + 1)
        ws.row_dimensions[ws.max_row].height = min(72, max(20, lines * 14))
    for j in range(1, len(head) + 1):
        cell = ws.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = WRAP
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = 'C2'

    ws2 = wb.create_sheet('明细')
    head2 = ['书码', '书', '#', '项目', '状态', '值', '方法', '置信', '证据段', '证据原文', '备注']
    ws2.append(head2)
    for c in CODES:
        for f in fields:
            it = recs[c]['items'][f['field']]
            ev = (it.get('evidence') or [{}])[0]
            ws2.append([c, recs[c]['book'], it['no'], it['name'], it['status'],
                        short(it), it['method'], it['confidence'],
                        ev.get('seg', ''), ev.get('quote', ''), it.get('note', '')])
            for j in range(1, len(head2) + 1):
                ws2.cell(row=ws2.max_row, column=j).alignment = WRAP
            ws2.cell(row=ws2.max_row, column=5).fill = STATUS_FILL.get(it['status'], PatternFill())
    for j in range(1, len(head2) + 1):
        cell = ws2.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
    for j, w in enumerate([7, 26, 5, 12, 12, 40, 8, 6, 14, 52, 26], start=1):
        ws2.column_dimensions[get_column_letter(j)].width = w
    ws2.freeze_panes = 'D2'
    ws2.auto_filter.ref = 'A1:K%d' % ws2.max_row

    ws3 = wb.create_sheet('说明')
    notes = [
        ('第 1 期范围', '出版信息 19 项'),
        ('运行命令', 'python3 platform/engine/publication.py --all --library app/data/library.json'),
        ('状态口径', 'found=有原文依据；needs_review=规则推断待人工；not_found=书上没有/没抽到'),
        ('显示口径', '本表为质检表，缺项留空；交付导出不写缺项，不显示“未找到”'),
        ('页数', '绝不使用 PDF 物理页数；只认版权页印的页数'),
        ('证据', '每个 found 值都带段号和逐字原文；测试会校验引文逐字存在'),
    ]
    ws3.append(['项', '说明'])
    for k, v in notes:
        ws3.append([k, v])
    ws3.cell(row=1, column=1).fill = HEAD_FILL
    ws3.cell(row=1, column=2).fill = HEAD_FILL
    ws3.cell(row=1, column=1).font = HEAD_FONT
    ws3.cell(row=1, column=2).font = HEAD_FONT
    ws3.column_dimensions['A'].width = 14
    ws3.column_dimensions['B'].width = 100
    for row in ws3.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = WRAP

    wb.save(XLSX)
    print('written', MD.name, XLSX.name)
    print('stats', stats)


if __name__ == '__main__':
    build()
