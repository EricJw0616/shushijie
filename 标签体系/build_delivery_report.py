#!/usr/bin/env python3
"""把 43 项交付台账导成 Excel。
数据源：platform/out/<书>/delivery.json + platform/out/delivery/annotations.jsonl
"""
import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
OUT = ROOT / 'platform' / 'out'
CODES = ['B56', 'B58', 'B59', 'B60', 'YC', 'B64', 'B65']
NAMES = {'B56': 'B56 图鉴', 'B58': 'B58 小王子', 'B59': 'B59 纪事', 'B60': 'B60 廉洁故事',
         'YC': 'YC 野草', 'B64': 'B64 十年非梦', 'B65': 'B65 太阳和蜉蝣'}
XLSX = BASE / '出版标签交付_47项.xlsx'

HEAD_FILL = PatternFill('solid', fgColor='1F4E79')
HEAD_FONT = Font(color='FFFFFF', bold=True, size=10)
WRAP = Alignment(wrap_text=True, vertical='top')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FILL = {
    'found': PatternFill('solid', fgColor='E2EFDA'),
    'needs_review': PatternFill('solid', fgColor='FFF2CC'),
    'not_found': PatternFill('solid', fgColor='F2F2F2'),
}

# 定位级别颜色：绿=段级，蓝=页级，黄=理解/生成类，红=无定位
LEVEL_FILL = {
    'seg': PatternFill('solid', fgColor='C6EFCE'),
    'partial': PatternFill('solid', fgColor='F8CBAD'),
    'understand': PatternFill('solid', fgColor='FFEB9C'),
    'page': PatternFill('solid', fgColor='BDD7EE'),
    'ocr': PatternFill('solid', fgColor='D9D2E9'),
    'none': PatternFill('solid', fgColor='FFC7CE'),
}
LEVEL_NAME = {'seg': '段级', 'partial': '段级·部分', 'understand': '段级·理解',
              'page': '页级', 'ocr': '页级·OCR', 'none': '无定位'}
MISSING_FILL = PatternFill('solid', fgColor='D9D9D9')
UNDERSTANDING_NAMES = {'事实与数值', '技能与规则', '核心概念', '概念与原理', '章节核心意思'}


def locate_info(a):
    """返回 (定位级别, 颜色键, 证据位置)。

    段级：至少有一条 seg；理解/生成类再加黄标；页面结构按 spans 给页码；没有则红标。
    """
    evs = [e for e in (a.get('evidence') or []) if isinstance(e, dict)]
    if a.get('group') == '出版物结构':
        v = a.get('value')
        spans = (v or {}).get('spans') if isinstance(v, dict) else []
        if spans:
            pos = '；'.join('p%d' % s['from'] if s.get('from') == s.get('to')
                            else 'p%d–%d' % (s.get('from'), s.get('to')) for s in spans)
        else:
            pos = '、'.join('p%s' % e.get('page') for e in evs if e.get('page')) or '页码缺失'
        return LEVEL_NAME['page'], 'page', pos

    ocr_evs = [e for e in evs if e.get('source') == 'ocr' and e.get('page')]
    if ocr_evs and not any(e.get('seg') for e in evs):
        pages = sorted({e['page'] for e in ocr_evs})
        return LEVEL_NAME['ocr'], 'ocr', '、'.join('p%s' % p for p in pages)

    segs = [e.get('seg') for e in evs if e.get('seg')]
    pos = '、'.join(segs[:3]) + ('…' if len(segs) > 3 else '') if segs else '—'
    q0 = evs[0].get('quote') if evs else ''
    if (a.get('pack_code') == 'P02' and a.get('name') in ('书名', '作者', '出版社')
            and segs and isinstance(a.get('value'), str)
            and q0 and q0 != a['value'] and q0 in a['value']):
        return LEVEL_NAME['partial'], 'partial', pos
    if a.get('name') in UNDERSTANDING_NAMES or a.get('pack_code') == 'P03':
        return (LEVEL_NAME['understand'] if segs else '无定位·理解'),\
               ('understand' if segs else 'none'), pos
    return (LEVEL_NAME['seg'] if segs else LEVEL_NAME['none']),\
           ('seg' if segs else 'none'), pos


def load(c):
    p = OUT / c / 'delivery.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def short(it):
    if it['status'] == 'not_found':
        return ''
    f = it['field']
    v = it['value']
    if f in ('facts', 'skills', 'concepts', 'principles'):
        if not v:
            return ''
        first = (v[0].get('fact') or v[0].get('text') or v[0].get('concept')
                 or v[0].get('principle') or '')
        return '%d 条（%s…）' % (len(v), str(first)[:12])
    if f in ('people', 'places', 'orgs'):
        return '%d 条' % len(v or [])
    if f == 'quotes':
        return '%d 条' % len(v or [])
    if f == 'chapter_main_idea':
        return '%d 条' % len(v or [])
    if f == 'keywords':
        return '%d 个' % len(v or [])
    if f == 'summary':
        return '%d 字' % len((v or {}).get('text') or '')
    if f in ('audience', 'scenarios', 'gains', 'emotions', 'leads'):
        return '%d 条' % len(v or [])
    if f == 'author':
        ppl = (v or {}).get('people') or []
        return '、'.join('%s（%s）' % (x['name'], x['role']) for x in ppl[:3]) + ('…' if len(ppl) > 3 else '')
    if f == 'book_format':
        return '；'.join('%s %s' % (x['type'], x['value']) for x in v or [])
    if f == 'word_count':
        return '%s（%s）' % (v.get('raw'), v.get('normalized'))
    if f == 'price':
        return v.get('raw') or ''
    if f == 'cip_number':
        return v.get('number') or ''
    if f == 'classification':
        return '；'.join('%s %s %s' % (x.get('system'), x.get('code'), x.get('name') or '') for x in v or [])
    if f == 'isbn':
        return '；'.join('%s %s%s' % (x['type'], x['value'], '（校验通过）' if x.get('valid') else '') for x in v or [])
    if f == 'translators':
        return '、'.join('%s（%s）' % (x['name'], x['role']) for x in v or [])
    if f == 'headings':
        return '%d 条' % len(v or [])
    if isinstance(v, dict) and 'spans' in v:
        sp = v['spans']
        if len(sp) == 1:
            a, b = sp[0]['from'], sp[0]['to']
            return 'p%d' % a if a == b else 'p%d–%d' % (a, b)
        return '；'.join('p%d' % s['from'] if s['from'] == s['to'] else 'p%d–%d' % (s['from'], s['to']) for s in sp)
    return str(v)[:80]


def build():
    recs = {c: load(c) for c in CODES}
    assert all(recs.values()), '缺少 delivery.json，请先跑 delivery.py'
    fields = list(recs['B58']['items'].keys())
    # 按包和编号排序
    def key(f):
        it = recs['B58']['items'][f]
        return (it.get('pack_code') or '', it.get('no') or '')
    fields.sort(key=key)

    wb = Workbook()
    ws = wb.active
    ws.title = '47项总表'
    head = ['编号', '标签', '分组'] + [NAMES[c] for c in CODES]
    ws.append(head)
    widths = [10, 16, 22] + [34] * len(CODES)
    for f in fields:
        it = recs['B58']['items'][f]
        row = [it.get('tag_key'), it['name'], it['group']]
        for c in CODES:
            x = recs[c]['items'][f]
            row.append(short(x))
        ws.append(row)
        for j in range(1, len(head) + 1):
            ws.cell(row=ws.max_row, column=j).alignment = WRAP
        ws.row_dimensions[ws.max_row].height = 34
        for j, c in enumerate(CODES, start=4):
            fill = FILL.get(recs[c]['items'][f]['status'])
            if fill:
                ws.cell(row=ws.max_row, column=j).fill = fill
    for j in range(1, len(head) + 1):
        cell = ws.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = WRAP
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = 'D2'

    # 长表
    anns = [json.loads(l) for l in (OUT / 'delivery' / 'annotations.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    ws2 = wb.create_sheet('交付长表')
    head2 = ['书码', '书', '编号', '标签', '分组', '值', '状态', '方法', '置信',
             '定位级别', '证据位置', '证据原文', '备注']
    ws2.append(head2)
    for a in anns:
        ev = (a.get('evidence') or [{}])[0]
        val = a.get('value')
        if isinstance(val, (dict, list)):
            val = json.dumps(val, ensure_ascii=False)[:200]
        level, color, pos = locate_info(a)
        ws2.append([a.get('book_code'), a.get('book'), a.get('tag_key'), a.get('name'),
                    a.get('group'), val, a.get('status'), a.get('method'),
                    a.get('confidence'), level, pos, ev.get('quote', ''), a.get('note', '')])
        for j in range(1, len(head2) + 1):
            ws2.cell(row=ws2.max_row, column=j).alignment = WRAP
        fill = FILL.get(a.get('status'))
        if fill:
            ws2.cell(row=ws2.max_row, column=7).fill = fill
        ws2.cell(row=ws2.max_row, column=10).fill = LEVEL_FILL[color]
    for j in range(1, len(head2) + 1):
        cell = ws2.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
    for j, w in enumerate([7, 26, 10, 14, 20, 42, 12, 8, 6, 12, 18, 56, 30], start=1):
        ws2.column_dimensions[get_column_letter(j)].width = w
    ws2.freeze_panes = 'C2'
    ws2.auto_filter.ref = 'A1:M%d' % ws2.max_row

    # 定位颜色矩阵：行=47 项，列=7 本，一格一个定位级别
    ws6 = wb.create_sheet('定位颜色矩阵')
    ws6.append(['编号', '标签', '分组'] + [NAMES[c] for c in CODES])
    grouped = {}
    for a in anns:
        grouped.setdefault((a.get('book_code'), a.get('tag_key')), []).append(a)
    for f in fields:
        it = recs['B58']['items'][f]
        row = [it.get('tag_key'), it['name'], it['group']]
        colors = []
        for c in CODES:
            rs = grouped.get((c, it.get('tag_key'))) or []
            if not rs:
                row.append('缺项')
                colors.append('missing')
                continue
            levels = [locate_info(x)[1] for x in rs]
            if 'none' in levels:
                lv = 'none'
            elif 'ocr' in levels:
                lv = 'ocr'
            elif 'partial' in levels:
                lv = 'partial'
            elif all(x == 'page' for x in levels):
                lv = 'page'
            elif any(x == 'understand' for x in levels):
                lv = 'understand'
            else:
                lv = 'seg'
            row.append(LEVEL_NAME[lv])
            colors.append(lv)
        ws6.append(row)
        for j, color in enumerate(colors, start=4):
            ws6.cell(row=ws6.max_row, column=j).fill = (MISSING_FILL if color == 'missing'
                                                       else LEVEL_FILL[color])
            ws6.cell(row=ws6.max_row, column=j).alignment = WRAP
        ws6.row_dimensions[ws6.max_row].height = 24
    for j in range(1, len(CODES) + 4):
        cell = ws6.cell(row=1, column=j)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = WRAP
    for j, w in enumerate([10, 16, 22] + [16] * len(CODES), start=1):
        ws6.column_dimensions[get_column_letter(j)].width = w
    ws6.freeze_panes = 'D2'

    # 营销待确认
    ws3 = wb.create_sheet('营销待确认')
    ws3.append(['书码', '项目', '结论/草稿', '依据性质', '证据段', '证据原文', '状态'])
    for a in anns:
        if a.get('pack_code') != 'P03':
            continue
        ev = (a.get('evidence') or [{}])[0]
        ws3.append([a.get('book_code'), a.get('name'), a.get('value'),
                    '原文明示' if '原文明示' in (a.get('note') or '') else '推断',
                    ev.get('seg', ''), ev.get('quote', ''), a.get('status')])
        for j in range(1, 8):
            ws3.cell(row=ws3.max_row, column=j).alignment = WRAP
        ws3.cell(row=ws3.max_row, column=7).fill = FILL['needs_review']
    for j in range(1, 8):
        c = ws3.cell(row=1, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
    for j, w in enumerate([7, 12, 52, 10, 14, 56, 12], start=1):
        ws3.column_dimensions[get_column_letter(j)].width = w
    ws3.freeze_panes = 'A2'
    ws3.auto_filter.ref = 'A1:G%d' % ws3.max_row

    # 说明
    ws4 = wb.create_sheet('说明')
    manifest = json.loads((OUT / 'delivery' / 'manifest.json').read_text(encoding='utf-8'))
    rp = BASE / '定位自查报告.json'
    rep = json.loads(rp.read_text(encoding='utf-8')) if rp.exists() else {}
    rows = [
        ('范围', '第1期19 + 第2期12 + 营销7 + 已有内容5 + 理解4 = 47 项'),
        ('放弃/不做', '第4期其余16 + 词性/句法/指代3 + 知识点关系4；第3期34、上市时间1 不做'),
        ('生成时间', manifest.get('generated_at')),
        ('长表行数', manifest.get('annotations')),
        ('口径', '缺项不显示、不导出；营销草稿标“待确认”，人确认后才算交付'),
        ('证据', '段级：段 id + 逐字引文；页级：PDF 页码 + 页面文字；理解类：段+引文+理由'),
        ('OCR', '封面/书名页 OCR：A=与书目库一致自动采用；B=无独立源抽样复核；C=人工；证据带页码/bbox/引擎版本'),
        ('颜色', '绿=段级定位；橙=段级·部分；蓝=页级定位；紫=页级·OCR（识别+交叉校验）；黄=理解/生成类；红=无定位'),
        ('定位校验', '共 %s 行：通过 %s，不通过 %s；详见「定位校验」页'
         % (rep.get('total', '—'), rep.get('ok', '—'), rep.get('failed', '—'))),
    ]
    ws4.append(['项', '说明'])
    for k, v in rows:
        ws4.append([k, v])
    for j in range(1, 3):
        c = ws4.cell(row=1, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
    ws4.column_dimensions['A'].width = 14
    ws4.column_dimensions['B'].width = 110
    for row in ws4.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = WRAP

    # 定位校验：把 check_location.py 的结果放进交付包
    ws5 = wb.create_sheet('定位校验')
    ws5.append(['项目', '值'])
    ws5.append(['总行数', rep.get('total', 0)])
    ws5.append(['通过', rep.get('ok', 0)])
    ws5.append(['不通过', rep.get('failed', 0)])
    ws5.append(['提醒', rep.get('warnings', 0)])
    ws5.append([])
    ws5.append(['书码', '标签', '原因'])
    for f in rep.get('failures') or []:
        ws5.append([f.get('book'), f.get('name'), '；'.join(f.get('errors') or [])])
    ws5.append([])
    ws5.append(['提醒（不阻断）'])
    ws5.append(['书码', '标签', '说明'])
    for w in rep.get('warning_items') or []:
        ws5.append([w.get('book'), w.get('name'), w.get('warning')])
    for j, w in enumerate([12, 18, 90], start=1):
        ws5.column_dimensions[get_column_letter(j)].width = w
    for j in range(1, 4):
        c = ws5.cell(row=1, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
    for row in ws5.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = WRAP

    wb.save(XLSX)
    print('written', XLSX.name)
    for c in CODES:
        print(c, recs[c]['counts'])


if __name__ == '__main__':
    build()
