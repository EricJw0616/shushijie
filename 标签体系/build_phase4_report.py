#!/usr/bin/env python3
"""第 4 期营销 7 项首轮结果：Markdown + Excel。"""
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
KEYS = [('keywords', '关键词'), ('summary', '内容简介'), ('audience', '目标读者'),
        ('scenarios', '适用场景'), ('gains', '阅读收获'), ('emotions', '情绪价值'),
        ('leads', '营销线索')]
MD = BASE / '营销7项_7本结果.md'
XLSX = BASE / '营销7项_7本结果.xlsx'

HEAD_FILL = PatternFill('solid', fgColor='1F4E79')
HEAD_FONT = Font(color='FFFFFF', bold=True, size=10)
WRAP = Alignment(wrap_text=True, vertical='top')
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
REVIEW_FILL = PatternFill('solid', fgColor='FFF2CC')


def load(c):
    p = OUT / c / 'marketing.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def cell(rec, key):
    it = rec['items'][key]
    v = it.get('value')
    if key == 'summary':
        return '%d 字' % len((v or {}).get('text') or '') if v else ''
    if key == 'keywords':
        return '%d 个' % len(v or [])
    return '%d 条' % len(v or [])


def build():
    recs = {c: load(c) for c in CODES}
    assert all(recs.values()), '缺少 marketing.json，请先跑 marketing.py'

    L = []
    A = L.append
    A('# 营销 7 项结果（7 本）\n')
    A('> 运行：`python3 platform/engine/marketing.py --all --max-chars 14000`，再跑 `marketing_review.py` 做第二遍审查。')
    A('> 状态：全部是 **needs_review（草稿）**，人确认后才算数。')
    A('> 输入：全书压缩片段（每篇取开头段 + 均匀补段，约 1.2–1.4 万字），不是逐字通读。\n')
    A('## 一、总表\n')
    A('| 项目 | ' + ' | '.join(NAMES[c] for c in CODES) + ' |')
    A('|---|' + '---|' * len(CODES))
    for k, name in KEYS:
        A('| %s | ' % name + ' | '.join(cell(recs[c], k) for c in CODES) + ' |')
    A('')
    A('## 二、统计\n')
    A('| 书 | 输入字数 | 证据条数 | 丢弃 | 关键词 | 简介字数 |')
    A('|---|---|---|---|---|---|')
    for c in CODES:
        r = recs[c]
        A('| %s | %d | %d | %d | %d | %d |' % (
            NAMES[c], r['input_chars'], r['stats']['evidence'], r['stats']['dropped'],
            len(r['items']['keywords']['value']),
            len(r['items']['summary']['value']['text'])))
    A('')
    A('## 三、七本的关键词草稿\n')
    for c in CODES:
        kws = '、'.join(x['keyword'] for x in recs[c]['items']['keywords']['value'])
        A('- **%s**：%s' % (NAMES[c], kws))
    A('')
    A('## 四、内容简介草稿（节选）\n')
    for c in CODES:
        t = recs[c]['items']['summary']['value']['text']
        A('**%s**（%d 字）\n\n> %s\n' % (NAMES[c], len(t), t[:220] + ('…' if len(t) > 220 else '')))
    A('## 五、需要人工重点看的\n')
    A('- **B60 的“适用场景/情绪价值”只有 2 条**，低于规范的 3–6 条，需要人补。')
    A('- **B56 是图鉴**，关键词偏“分类/学科词”（藻类植物、地衣植物…），营销区分度弱，需要按图书市场改。')
    A('- **YC《野草》**：关键词偏篇目名（死火、墓碣文…），适合文学读者，不适合大众营销；简介已压缩到 262 字，但“多以梦境为框架”仍需人核。')
    A('- **B64《十年非梦》**：题材敏感，关键词含“工总司/一月风暴”等历史事件，营销口径需业务/合规确认后再用。')
    A('- **B65《太阳和蜉蝣》**：绘本原文只有约 2000 字（5 段），营销素材是从有限文本推出来的，目标读者/场景需编辑补。')
    A('- **B59 的关键词混入了具体科研成果**（人工合成结晶牛胰岛素、铀同位素分离…），更像内容词，不像营销词，需要人筛。')
    A('- 所有条目都带原文证据，但“推断/原文明示”的标注仍需人核；模型自评不是准确率。')
    A('- 简介里可能出现书外常识（如“20 世纪最佳图书”），虽然能在导读里找到依据，仍建议人确认口径。')
    A('')
    A('## 六、已知限制\n')
    A('- 输入是压缩文本，不是整本书；真正“整书理解”要等后续整书分块模式。')
    A('- 一条结论只挂一段证据，复杂判断可能需要多段。')
    A('- 营销是主观判断，系统只保证“有依据、可追溯”，不保证“自动正确”。')
    A('- 本次没做“两次独立 AI 判断”，只有一次生成；关键词的双复核还没上。')
    A('')
    A('## 七、文件\n')
    A('| 文件 | 内容 |')
    A('|---|---|')
    A('| platform/engine/marketing.py | 营销 7 项生成器 |')
    A('| platform/engine/test_marketing.py | 假模型回归测试 |')
    A('| platform/out/<书>/marketing.json | 每本书 7 项草稿 + 证据 |')
    A('')
    MD.write_text('\n'.join(L), encoding='utf-8')

    # Excel
    wb = Workbook()
    ws = wb.active
    ws.title = '总表'
    ws.append(['项目'] + [NAMES[c] for c in CODES])
    for k, name in KEYS:
        ws.append([name] + [cell(recs[c], k) for c in CODES])
    for j in range(1, len(CODES) + 2):
        c = ws.cell(row=1, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = WRAP
    ws.column_dimensions['A'].width = 12
    for j in range(2, len(CODES) + 2):
        ws.column_dimensions[get_column_letter(j)].width = 18

    ws2 = wb.create_sheet('关键词')
    ws2.append(['书码', '关键词', '理由', '证据段', '证据原文'])
    for c in CODES:
        for x in recs[c]['items']['keywords']['value']:
            ev = (x.get('evidence') or [{}])[0]
            ws2.append([c, x['keyword'], x.get('reason', ''), ev.get('seg', ''), ev.get('quote', '')])
            for j in range(1, 6):
                ws2.cell(row=ws2.max_row, column=j).alignment = WRAP
    for j in range(1, 6):
        c = ws2.cell(row=1, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
    for j, w in enumerate([7, 24, 40, 14, 70], start=1):
        ws2.column_dimensions[get_column_letter(j)].width = w
    ws2.freeze_panes = 'A2'
    ws2.auto_filter.ref = 'A1:E%d' % ws2.max_row

    ws3 = wb.create_sheet('七项明细')
    ws3.append(['书码', '项目', '条数/字数', '结论', '依据性质', '证据段', '证据原文', '状态'])
    for c in CODES:
        for k, name in KEYS:
            it = recs[c]['items'][k]
            v = it.get('value')
            if k == 'summary':
                rows = [('', (v or {}).get('text', ''), '', '', '')]
            elif k == 'keywords':
                rows = [(x['keyword'], x.get('reason', ''), '', '', '') for x in (v or [])]
            else:
                rows = [(x['text'], x.get('reason', ''), x.get('basis', ''),
                         (x.get('evidence') or [{}])[0].get('seg', ''),
                         (x.get('evidence') or [{}])[0].get('quote', '')) for x in (v or [])]
            for text, reason, basis, seg, quote in rows:
                if k == 'keywords':
                    ev = next((x for x in v if x['keyword'] == text), {}).get('evidence') or [{}]
                    seg, quote = ev[0].get('seg', ''), ev[0].get('quote', '')
                if k == 'summary':
                    ev = (it.get('evidence') or [{}])[0]
                    seg, quote = ev.get('seg', ''), ev.get('quote', '')
                ws3.append([c, name, cell(recs[c], k), text or reason, basis, seg, quote, it['status']])
                for j in range(1, 9):
                    ws3.cell(row=ws3.max_row, column=j).alignment = WRAP
                ws3.cell(row=ws3.max_row, column=8).fill = REVIEW_FILL
    for j in range(1, 9):
        c = ws3.cell(row=1, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
    for j, w in enumerate([7, 10, 10, 60, 10, 14, 60, 14], start=1):
        ws3.column_dimensions[get_column_letter(j)].width = w
    ws3.freeze_panes = 'A2'
    ws3.auto_filter.ref = 'A1:H%d' % ws3.max_row

    ws4 = wb.create_sheet('简介')
    ws4.append(['书码', '书名', '字数', '内容简介'])
    for c in CODES:
        it = recs[c]['items']['summary']
        ws4.append([c, recs[c]['book'], len(it['value']['text']), it['value']['text']])
        ws4.cell(row=ws4.max_row, column=4).alignment = WRAP
    for j in range(1, 5):
        c = ws4.cell(row=1, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
    for j, w in enumerate([7, 30, 7, 110], start=1):
        ws4.column_dimensions[get_column_letter(j)].width = w
    for i in range(2, ws4.max_row + 1):
        ws4.row_dimensions[i].height = 80

    wb.save(XLSX)
    print('written', MD.name, XLSX.name)


if __name__ == '__main__':
    build()
