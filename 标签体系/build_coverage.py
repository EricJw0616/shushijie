#!/usr/bin/env python3
"""生成 105 项标签 × 当前系统覆盖对照的 Excel + Markdown。"""
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
OUT_XLSX = BASE / "系统覆盖对照_105项.xlsx"
OUT_MD = BASE / "系统覆盖对照_105项.md"

HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14, color="1F4E79")
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STATUS_FILL = {
    "已拥有": PatternFill("solid", fgColor="E2EFDA"),
    "部分拥有": PatternFill("solid", fgColor="FFF2CC"),
    "未拥有": PatternFill("solid", fgColor="F2F2F2"),
}
PRIORITY_NOTE = {
    "P0": "已拥有，可直接复用，无需开发",
    "P1": "低成本补齐：扩展现有 CIP/元数据/标签字段即可",
    "P2": "中成本新建：页面级版式/结构/数据集元数据/营销基础项",
    "P3": "高成本新建：语言结构、概念事实、知识关系、营销洞察",
}

PRI_FILL = {
    "P0": PatternFill("solid", fgColor="C6EFCE"),
    "P1": PatternFill("solid", fgColor="FFF2CC"),
    "P2": PatternFill("solid", fgColor="FCE4D6"),
    "P3": PatternFill("solid", fgColor="F8CBAD"),
}
BLOCK = {
    ("P01", "01"): "原文实体",
    ("P01", "02"): "章节理解",
    ("P01", "03"): "语言结构",
    ("P01", "04"): "语用指代",
    ("P01", "05"): "图表理解",
    ("P01", "06"): "事实数值",
    ("P01", "07"): "概念技能",
    ("P01", "08"): "知识关系",
    ("P01", "09"): "金句",
    ("P02", "01"): "出版事实",
    ("P02", "02"): "出版书目",
    ("P02", "03"): "数据集元数据",
    ("P02", "04"): "分类",
    ("P02", "05"): "可追溯",
    ("P02", "06"): "质量权利",
    ("P02", "07"): "出版物结构",
    ("P02", "08"): "图文版式",
    ("P02", "09"): "文字样式",
    ("P02", "10"): "语义标识",
    ("P03", "01"): "营销关键词",
    ("P03", "02"): "营销洞察",
}


def est_height(texts, widths, cap=409, line_h=13, min_h=20):
    lines = 1
    for text, w in zip(texts, widths):
        if not text:
            continue
        s = str(text)
        per = max(4, w * 1.05)
        est = 0
        for seg in s.split("\n"):
            u = sum(2 if ord(ch) > 127 else 1 for ch in seg)
            est += max(1, int(u / per) + (1 if u % per else 0))
        lines = max(lines, est)
    return max(min_h, min(cap, lines * line_h + 6))


def sheet_write(ws, rows, widths, freeze="A2"):
    for i, row in enumerate(rows, start=1):
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=i, column=j, value=v)
            c.alignment = WRAP
            c.border = BORDER
            if i == 1:
                c.fill = HEAD_FILL
                c.font = HEAD_FONT
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = freeze
    ws.auto_filter.ref = f"A1:{get_column_letter(len(widths))}{len(rows)}"
    ws.row_dimensions[1].height = 30


def main():
    data = json.loads((BASE / "coverage.json").read_text(encoding="utf-8"))
    tags = data["tags"]
    counts = data["meta"]["counts"]
    for i, t in enumerate(tags, start=1):
        t["seq"] = i
    pri = Counter(t["priority"] for t in tags)
    total = len(tags)

    wb = Workbook()

    # ---------- 00 结论 ----------
    ws = wb.active
    ws.title = "00_结论"
    ws["A1"] = "105 项出版标签 × 当前系统覆盖对照"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:D1")
    lines = [
        ("核对时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("核对对象", "app/（图书知识库 B56/B58/B59/B60）+ platform/engine/（抽取引擎）+ platform/library/（标签产物）"),
        ("一句话结论", f"已拥有 {counts['已拥有']} 项、部分拥有 {counts['部分拥有']} 项、未拥有 {counts['未拥有']} 项。已有能力集中在出版 CIP 元数据、原文专名、篇摘要/金句、标注证据链；缺口集中在页面级结构/版式/文字样式（42 项）与营销理解。"),
        ("重要前提", "现有系统的标签词表（191 条 L0–L7）与这 105 项没有任何同名标签（仅“人物→人物候选”“索引→专名索引”两处字面包含、含义不同）。所以下表是“底层能力”对照，不是标签已存在。"),
        ("", ""),
        ("覆盖状态", "数量 / 占比 / 判定口径"),
        ("已拥有", f"{counts['已拥有']} / {counts['已拥有']/total:.1%} / 已有对应字段或产物，可实际产出；其中 9 项可直接用（P0），6 项需按原文格式微调（P1）"),
        ("部分拥有", f"{counts['部分拥有']} / {counts['部分拥有']/total:.1%} / 有相邻能力或字段，但口径/粒度/覆盖面不足，需改造"),
        ("未拥有", f"{counts['未拥有']} / {counts['未拥有']/total:.1%} / 无对应实现"),
        ("", ""),
        ("分包", "已拥有 / 部分 / 未拥有 / 合计"),
    ]
    for p in ("P01", "P02", "P03"):
        sub = [t for t in tags if t["package"] == p]
        c = Counter(t["status"] for t in sub)
        lines.append((p, f"{c['已拥有']} / {c['部分拥有']} / {c['未拥有']} / {len(sub)}"))
    lines += [
        ("", ""),
        ("优先级", "数量 / 含义"),
        ("P0", f"{pri['P0']} / {PRIORITY_NOTE['P0']}"),
        ("P1", f"{pri['P1']} / {PRIORITY_NOTE['P1']}"),
        ("P2", f"{pri['P2']} / {PRIORITY_NOTE['P2']}"),
        ("P3", f"{pri['P3']} / {PRIORITY_NOTE['P3']}"),
    ]
    for r, (k, v) in enumerate(lines, start=2):
        ws.cell(row=r, column=1, value=k).font = Font(bold=(k in ("覆盖状态", "分包", "优先级")))
        ws.cell(row=r, column=2, value=v).alignment = WRAP
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 125

    # ---------- 01 覆盖对照 ----------
    ws = wb.create_sheet("01_覆盖对照")
    head = ["序号", "包", "组", "编号", "标签", "覆盖状态", "系统对应能力/字段", "证据（仓库内可核对）", "差距与补法", "优先级"]
    rows = [head]
    for t in tags:
        rows.append([t["seq"], t["package"], t["group_name"], t["tag_no"], t["tag_name"],
                     t["status"], t["system"], t["evidence"], t["gap"], t["priority"]])
    widths = [6, 7, 18, 7, 16, 10, 30, 64, 44, 8]
    sheet_write(ws, rows, widths)
    for i, t in enumerate(tags, start=2):
        ws.cell(row=i, column=6).fill = STATUS_FILL[t["status"]]
        ws.cell(row=i, column=10).fill = PRI_FILL[t["priority"]]
        ws.row_dimensions[i].height = est_height([t["system"], t["evidence"], t["gap"]], [30, 64, 44])

    # ---------- 02 已拥有 ----------
    ws = wb.create_sheet("02_已拥有")
    head = ["序号", "包-编号", "标签", "系统对应能力/字段", "证据", "可直接复用的方式", "现状限制"]
    rows = [head]
    for t in tags:
        if t["status"] != "已拥有":
            continue
        rows.append([t["seq"], f"{t['package']}-{t['tag_no']}", t["tag_name"], t["system"],
                     t["evidence"], "读现成字段/产物，映射到目标字段名即可", t["gap"]])
    sheet_write(ws, rows, [6, 10, 16, 30, 62, 34, 40])
    for i in range(2, len(rows) + 1):
        ws.row_dimensions[i].height = 60

    # ---------- 03 部分拥有 ----------
    ws = wb.create_sheet("03_部分拥有")
    head = ["序号", "包-编号", "标签", "现有能力", "差距 / 改造点", "现有证据", "优先级"]
    rows = [head]
    for t in tags:
        if t["status"] != "部分拥有":
            continue
        rows.append([t["seq"], f"{t['package']}-{t['tag_no']}", t["tag_name"], t["system"],
                     t["gap"], t["evidence"], t["priority"]])
    sheet_write(ws, rows, [6, 10, 16, 30, 62, 44, 8])
    for i in range(2, len(rows) + 1):
        ws.row_dimensions[i].height = 64

    # ---------- 04 未拥有按块 ----------
    ws = wb.create_sheet("04_未拥有按块")
    head = ["缺口块", "包", "组", "编号", "标签", "为什么没有（现状）", "建议补法", "优先级"]
    rows = [head]
    order = []
    for t in tags:
        if t["status"] != "未拥有":
            continue
        b = BLOCK[(t["package"], t["group_no"])]
        if b not in order:
            order.append(b)
    for b in order:
        sub = [t for t in tags if t["status"] == "未拥有" and BLOCK[(t["package"], t["group_no"])] == b]
        rows.append([f"{b}（{len(sub)} 项）", "", "", "", "", "", "", ""])
        for t in sub:
            rows.append(["", t["package"], t["group_name"], t["tag_no"], t["tag_name"],
                         t["evidence"], t["gap"], t["priority"]])
    sheet_write(ws, rows, [18, 7, 18, 7, 16, 60, 44, 8])
    for i, row in enumerate(rows[1:], start=2):
        if row[0]:
            ws.merge_cells(start_row=i, start_column=1, end_row=i, end_column=8)
            c = ws.cell(row=i, column=1)
            c.font = Font(bold=True, color="1F4E79")
            c.fill = PatternFill("solid", fgColor="DDEBF7")
            c.alignment = Alignment(vertical="center")
            ws.row_dimensions[i].height = 24
        else:
            ws.row_dimensions[i].height = 58

    # ---------- 05 按组汇总 ----------
    ws = wb.create_sheet("05_按组汇总")
    head = ["包", "组", "标签块", "项数", "已拥有", "部分拥有", "未拥有", "覆盖率"]
    rows = [head]
    groups = []
    for t in tags:
        key = (t["package"], t["group_no"], t["group_name"])
        if key not in groups:
            groups.append(key)
    for pkg, gno, gname in groups:
        sub = [t for t in tags if (t["package"], t["group_no"]) == (pkg, gno)]
        c = Counter(t["status"] for t in sub)
        rows.append([pkg, f"{gno} {gname}", BLOCK[(pkg, gno)], len(sub),
                     c["已拥有"], c["部分拥有"], c["未拥有"],
                     f"{(c['已拥有'] + c['部分拥有'] * 0.5) / len(sub):.0%}"])
    sheet_write(ws, rows, [7, 26, 16, 7, 8, 10, 8, 9])

    # ---------- 06 建议路线 ----------
    ws = wb.create_sheet("06_建议路线")
    head = ["优先级", "含义", "项数", "标签清单"]
    rows = [head]
    for p in ("P0", "P1", "P2", "P3"):
        sub = [t for t in tags if t["priority"] == p]
        rows.append([p, PRIORITY_NOTE[p], len(sub),
                     "、".join(f"{t['package']}-{t['tag_no']} {t['tag_name']}" for t in sub)])
    sheet_write(ws, rows, [8, 30, 6, 150])
    for i in range(2, len(rows) + 1):
        ws.row_dimensions[i].height = est_height([rows[i - 1][3]], [150])

    wb.save(OUT_XLSX)

    # ---------- Markdown ----------
    L = []
    A = L.append
    A("# 105 项出版标签 × 当前系统覆盖对照\n")
    A(f"> 核对时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}｜对象：app/ + platform/engine/（B56/B58/B59/B60）\n")
    A("## 一、结论\n")
    A(f"**已拥有 {counts['已拥有']} 项（{counts['已拥有']/total:.0%}）、部分拥有 {counts['部分拥有']} 项（{counts['部分拥有']/total:.0%}）、未拥有 {counts['未拥有']} 项（{counts['未拥有']/total:.0%}）。**\n")
    A("已拥有 15 项里，9 项（P0）可直接映射进数据集；另外 6 项（作者、出版社、章节核心意思、字数、定价、金句）已有字段或产物，但格式/复核口径要小改（P1）。\n")
    A("要先说清一个前提：系统现在的“标签体系”是 191 条 L0–L7 标签（篇目结构、专名索引、人物候选、类型/语体/议题…），**与这 105 项没有任何同名标签**，只有“人物→人物候选”“索引→专名索引”两处字面包含。所以下面的“已拥有”指的是**底层抽取能力或字段已经存在**，不是标签已经建好。\n")
    A("| 状态 | 数量 | 占比 | 判定口径 |")
    A("|---|---|---|---|")
    A(f"| 已拥有 | {counts['已拥有']} | {counts['已拥有']/total:.1%} | 已有对应字段或产物，可实际产出 |")
    A(f"| 部分拥有 | {counts['部分拥有']} | {counts['部分拥有']/total:.1%} | 有相邻能力，口径/粒度/覆盖面不足 |")
    A(f"| 未拥有 | {counts['未拥有']} | {counts['未拥有']/total:.1%} | 无对应实现 |")
    A("")
    A("| 包 | 已拥有 | 部分 | 未拥有 | 合计 |")
    A("|---|---|---|---|---|")
    for p in ("P01", "P02", "P03"):
        sub = [t for t in tags if t["package"] == p]
        c = Counter(t["status"] for t in sub)
        A(f"| {p} {sub[0]['pkg_name']} | {c['已拥有']} | {c['部分拥有']} | {c['未拥有']} | {len(sub)} |")
    A("")
    A("## 二、已拥有的 15 项（现有字段/产物）\n")
    A("| # | 编号 | 标签 | 系统里对应什么 | 证据 |")
    A("|---|---|---|---|---|")
    for t in tags:
        if t["status"] == "已拥有":
            A(f"| {t['seq']} | {t['package']}-{t['tag_no']} | {t['tag_name']} | {t['system']} | {t['evidence']} |")
    A("")
    A("## 三、部分拥有的 13 项（有底子，需改造）\n")
    A("| # | 编号 | 标签 | 现有能力 | 差距 / 改造点 |")
    A("|---|---|---|---|---|")
    for t in tags:
        if t["status"] == "部分拥有":
            A(f"| {t['seq']} | {t['package']}-{t['tag_no']} | {t['tag_name']} | {t['system']} | {t['gap']} |")
    A("")
    A("## 四、未拥有的 77 项（按缺口块）\n")
    A("| 缺口块 | 项数 | 包含标签 | 缺口性质 |")
    A("|---|---|---|---|")
    for b in order:
        sub = [t for t in tags if t["status"] == "未拥有" and BLOCK[(t["package"], t["group_no"])] == b]
        names = "、".join(t["tag_name"] for t in sub)
        if len(names) > 90:
            names = names[:90] + "…"
        nature = {
            "章节理解": "无概念抽取（系统明确只做论断段定位）",
            "语言结构": "无分词/词性/句法",
            "语用指代": "无跨句关系识别",
            "图表理解": "无图/表对象检测",
            "事实数值": "无事实抽取",
            "概念技能": "无概念/规则抽取",
            "知识关系": "无知识图谱",
            "出版事实": "版权页未抽责任编辑",
            "出版书目": "版权页字段未抽全（副书名/装帧/页数/丛书/作者简介）",
            "数据集元数据": "无数据集身份/版本/责任/语言等字段",
            "质量权利": "无权利记录结构",
            "出版物结构": "无页面角色分类（封面/版权页/前言/后记…）",
            "图文版式": "无图片/表格/公式对象与图注关联",
            "文字样式": "layout 未存字体/字号/颜色/对齐",
            "语义标识": "上市时间需外部商品资料",
            "营销洞察": "无营销理解模块",
        }.get(b, "未实现")
        A(f"| {b} | {len(sub)} | {names} | {nature} |")
    A("")
    A("> 42 项（出版物结构 11 + 图文版式 16 + 文字样式 15）占了未拥有项的一半以上，都是**页面级版式**问题；剩下的主要是理解层（概念/事实/关系/词法）和营销层。\n")
    A("## 五、建议路线\n")
    A("| 优先级 | 含义 | 项数 | 做什么 |")
    A("|---|---|---|---|")
    A(f"| P0 | {PRIORITY_NOTE['P0']} | {pri['P0']} | 直接映射字段，先接进数据集 schema |")
    A(f"| P1 | {PRIORITY_NOTE['P1']} | {pri['P1']} | 扩 CIP/元数据字段：责任编辑、副书名、装帧、页数、丛书、译者拆分、开本拆分、字数/定价保留原文、ISBN-10、标注方法、质量记录 |")
    A(f"| P2 | {PRIORITY_NOTE['P2']} | {pri['P2']} | 页面级版式管线（结构 12 + 图文 16 + 文字样式 17）+ 数据集元数据 + 营销基础项 |")
    A(f"| P3 | {PRIORITY_NOTE['P3']} | {pri['P3']} | 语言结构、概念/事实、知识关系（依赖前序产物） |")
    A("")
    A("## 六、文件\n")
    A("| 文件 | 内容 |")
    A("|---|---|")
    A("| 系统覆盖对照_105项.xlsx | 结论、105 行对照、已拥有、部分拥有、未拥有按块、按组汇总、路线 |")
    A("| coverage.json | 105 行结构化对照（状态/证据/差距/优先级） |")
    A("| 出版标签体系_105项解析.xlsx | 上一轮的三包规则全文与问题清单 |")
    A("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print("written", OUT_XLSX.name, OUT_MD.name)


if __name__ == "__main__":
    main()
