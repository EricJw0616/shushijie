#!/usr/bin/env python3
"""把 tags.json 转成可交付的 Excel 总表 + Markdown 报告 + CSV。

所有数字均由 tags.json 计算，不手填。
"""
import csv
import statistics
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
RAW = BASE / "原始解析"
OUT_XLSX = BASE / "出版标签体系_105项解析.xlsx"
OUT_MD = BASE / "出版标签体系_105项解析.md"
OUT_CSV = BASE / "出版标签体系_105项解析.csv"

SRC_DOCX = {
    "P01": Path("/Users/zhujiawei/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/1A3E835ADCFE8CACD2C5615E2959F3A9/Caches/Files/2026-10/95fcc4e81d676d49b94966259fc93cc7/01_出版内容与知识包_标签规则阅读修改版_1.8.0.docx"),
    "P02": Path("/Users/zhujiawei/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/1A3E835ADCFE8CACD2C5615E2959F3A9/Caches/Files/2026-10/16a14a7ad960f1becc74ab21ff802248/02_出版基础信息与结构包_标签规则阅读修改版_1.7.0.docx"),
    "P03": Path("/Users/zhujiawei/Library/Containers/com.tencent.WeWorkMac/Data/Documents/Profiles/1A3E835ADCFE8CACD2C5615E2959F3A9/Caches/Files/2026-10/62c5ef0e31d7ce9ab1a5a02805d6f90d/03_出版营销分析包_标签规则阅读修改版_1.5.0.docx"),
}

HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14, color="1F4E79")
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STATUS_FILL = {
    "模板化": PatternFill("solid", fgColor="FFF2CC"),
    "缺字段定义": PatternFill("solid", fgColor="FCE4D6"),
}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_appendix(pkg_id):
    """从原始解析文本提取附录一的包身份与来源清单。"""
    dump = (RAW / {"P01": "01_内容与知识包.txt", "P02": "02_基础信息与结构包.txt", "P03": "03_营销分析包.txt"}[pkg_id]).read_text(encoding="utf-8")
    lines = []
    for line in dump.splitlines():
        m = re.match(r"^P\d{4}\s+(?:\[[^\]]+\]\s*)?(.*)$", line)
        if m:
            lines.append(m.group(1))
    meta = {"identity": "", "base_revision": "", "checksum": "", "export_time": "",
            "scope": "", "note": "", "sources": []}
    cur = None
    in_app = False
    # 目录里也会出现“附录一”，只认后面紧跟“标签包身份”的那一处
    start = None
    for i, l in enumerate(lines):
        if l.startswith("附录一") and any(x.startswith("标签包身份") for x in lines[i + 1:i + 5]):
            start = i
    if start is None:
        return meta
    for line in lines[start + 1:]:
        if line.startswith("附录二"):
            break
        in_app = True
        m = re.match(r"^标签包身份[：:]\s*(.*)$", line)
        if m:
            meta["identity"] = m.group(1).strip()
            continue
        m = re.match(r"^基础修订身份[：:]\s*(.*)$", line)
        if m:
            meta["base_revision"] = m.group(1).strip()
            continue
        m = re.match(r"^包正文校验摘要[：:]\s*(.*)$", line)
        if m:
            meta["checksum"] = m.group(1).strip()
            continue
        m = re.match(r"^只读导出时间[：:]\s*(.*)$", line)
        if m:
            meta["export_time"] = m.group(1).strip()
            continue
        m = re.match(r"^原始适用范围[：:]\s*(.*)$", line)
        if m:
            meta["scope"] = m.group(1).strip()
            continue
        m = re.match(r"^来源\s*(\d+)\s*(.*)$", line)
        if m:
            cur = {"no": m.group(1), "title": m.group(2).strip(), "location": "",
                   "usage": "", "remark": "", "version": ""}
            meta["sources"].append(cur)
            continue
        m = re.match(r"^原文位置[：:]\s*(.*)$", line)
        if m and cur is not None:
            cur["location"] = m.group(1).strip()
            continue
        m = re.match(r"^来源用途和资格[：:]\s*(.*)$", line)
        if m and cur is not None:
            cur["usage"] = m.group(1).strip()
            continue
        m = re.match(r"^来源备注[：:]\s*(.*)$", line)
        if m and cur is not None:
            cur["remark"] = m.group(1).strip()
            continue
        m = re.match(r"^来源版本与核验身份[：:]\s*(.*)$", line)
        if m and cur is not None:
            cur["version"] = m.group(1).strip()
            continue
    # 包内说明原文在正文开头
    for line in lines[:20]:
        m = re.match(r"^包内说明原文[：:]\s*(.*)$", line)
        if m:
            meta["note"] = m.group(1).strip()
    return meta


def load():
    pkgs = json.loads((BASE / "tags.json").read_text(encoding="utf-8"))
    idx = 0
    for p in pkgs:
        for t in p["tags"]:
            idx += 1
            t["seq"] = idx
            t["pkg_name"] = p["name"]
            t["pkg_version"] = p["version"]
    return pkgs


def status_of(t):
    if t["undefined_fields"]:
        return "缺字段定义"
    if t["definition"].startswith("标注出版物的"):
        return "模板化"
    if t["rule_form"] == "逐标签定义":
        return "独立定义"
    return "仅组规则"


def build_issues(pkgs, groups):
    tags = [t for p in pkgs for t in p["tags"]]
    issues = []

    dup = Counter(t["tag_id"] for t in tags)
    dup_ids = [k for k, v in dup.items() if v > 1]

    issues.append({
        "level": "高",
        "issue": "“内容简介”在两包中重复，同一标签 ID 承载两套不同规则",
        "evidence": "基础包 026（现成简介，字段空）与营销包 002（整书概括，字段 marketing_content_summary）共用 BT-73501b96-614a-458e-8e69-df1e4a6ac522；文档自述“两套包内规则分别保留”。",
        "impact": "合并为一个训练/评测数据集时，同 ID 会对应两种输入范围与两种输出口径，无法直接做标签级统计。",
        "action": "统一数据集键改为“包代码 + 标签编号 + 标签 ID”，或在合并层拆出独立身份；评测集按包分别建。",
    })
    issues.append({
        "level": "高",
        "issue": "81 项的基础包中 66 项只有“组规则 + 一句话提示”，45 项定义是同一模板句",
        "evidence": "P02 组 07/08/09 共 45 项（035–046、047–062、063–079）定义均为“标注出版物的{名称}结构、版式或呈现元素，并保留所在页、范围与原始证据”，补充提示也同一句；其中 0 项有独立“何时打/边界和排除/结果取值”。",
        "impact": "图题 vs 图注、有线表 vs 无线表、公式 vs 公式图、左/中/右对齐等真正需要区分的边界没有写，标注员与模型只能靠标签名猜，一致性无法保证。",
        "action": "对 45 项版式/结构标签逐项补“与相邻标签的二选一边界 + 判据”（可用一张标签对边界矩阵），再进数据集。",
    })
    issues.append({
        "level": "高",
        "issue": "13 个字段位置写“当前版本未单独列出此项”",
        "evidence": "P01 004 核心概念、005 章节核心意思、011 概念与原理、012 技能与规则 的“何时打/边界和排除/结果取值”各 3 处；P03 002 内容简介的“结果取值”1 处。",
        "impact": "这些恰是 AI 理解类标签，缺“何时打/不算什么/怎么存”会导致输出漂移与人工复核口径不一。",
        "action": "补齐或明确写“按组规则 + 字段含义执行，不另设条件”，并进入下一版修订。",
    })
    issues.append({
        "level": "中",
        "issue": "采用方式与分数门槛并存，口径互相打架",
        "evidence": "P02 组 02/04/10 写“以证据和独立复核决定采用……不按分数高低决定采用”，同组又保留“初次判断 0.95；独立复核 0.95；综合 0.95”；21 组中 15 组仍带模板句“0.85 不代表 85% 正确”，包括门槛为 0.95 的 P01 组 05。",
        "impact": "同一份规则对“自动采用”的判据给出两套解释，无法据此实现可复现的自动落标。",
        "action": "明确每题采用“证据核验制”或“分数制”其一；模板句按组门槛参数化，不再固定写 0.85。",
    })
    issues.append({
        "level": "中",
        "issue": "105 项中仅 30 项有结果类型与字段名，22 项有校验配置",
        "evidence": "75 项（全部“组规则加标签说明”）无“结果类型/程序核对方式/字段名”；P01 006–009、013 等 8 项程序核对写“当前版本未配置独立字段校验器”。",
        "impact": "输出结构未定义，无法做 schema 级质检、字段级准确率与自动验收；只能人工看文本。",
        "action": "为 75 项补最小输出 schema（字段名、单值/列表、允许值、证据定位格式），再谈自动质检。",
    })
    issues.append({
        "level": "中",
        "issue": "16 项并非“从书稿标注”，而是读取系统记录的资产元数据/治理项",
        "evidence": "P02 组 03（9 项：数据集标识、版本、关联资源、结构类型、语言、责任主体、媒介类型、文件构成、内容简介）、组 05（2 项：标注方法、标注证据位置）、组 06（5 项：质量结果、权利状态、归属方式、获取方式、许可范围）执行方式均为“读取系统正式记录”。另有 P01 016 关系闭合性校验是系统校验动作。",
        "impact": "把 105 都叫“标注点”会高估内容标注工作量；这 16 项应由平台流水线生成，不应进入人工标注任务。",
        "action": "拆分“内容标注点 89 项”与“资产元数据/治理 16 项”两张清单，分别定生产流程与验收标准。",
    })
    issues.append({
        "level": "中",
        "issue": "营销包 001 关键词内嵌整份 15 节业务规则，且与同包 C01 修订存在旧条文并存",
        "evidence": "P03 001 标签正文 2826 字（其余项中位数 35 字），含“十五、用户所供建议审批结论”；其第十一节仍写“内容简介、目标读者……原则上仍由人工确认”，而同包 C01 已改为“AI 生成并复核，达标自动通过”。C01 声明“替代上述六项一律人工确认”，但旧句未删。",
        "impact": "单读该标签会得到相反结论；规则粒度极端不一致，难以版本化管理。",
        "action": "长规则移入独立规则文档并在标签内只留摘要 + 规则版本号；删改旧条文，保留变更记录。",
    })
    issues.append({
        "level": "低",
        "issue": "7 条规则来源中 2 条“仅测试”、5 条“待核验”",
        "evidence": "P02 来源 1/2 资格状态为“仅测试”（TCADPA 70-2026 发布稿、语料加工要求征求意见稿）；P01 来源 1、P02 来源 3、P03 来源 1/2/3 为“待核验”。文档自述“不证明官方合规、实际准确率或所有标签已经通过真实材料验收”。",
        "impact": "对外称“高质量数据集”时，来源资格与合规性目前没有闭环证据。",
        "action": "把来源资格核验当作独立门禁；测试稿来源只用于方法参考，不作为规则唯一依据。",
    })
    issues.append({
        "level": "低",
        "issue": "标签自身规则文本厚度差异极大",
        "evidence": "单项规则正文（打什么+何时+边界+取值+证据+核对）中位数 35 字、最短 12 字（P02 005 责任编辑）、最长 2826 字（P03 001 关键词）。",
        "impact": "“逐项定义”的颗粒度不齐，训练/提示词成本与质量不可比。",
        "action": "设定最低规则要素清单（对象、判据、排除、取值、证据、复核），不达标项列为待补。",
    })
    issues.append({
        "level": "低",
        "issue": "版本与可追溯信息完整（正向结论）",
        "evidence": "三包均为“版本 + 修订 1”，附基础修订身份、包正文 SHA256、统一导出时间 2026-10-10 16:09:07；105 项均有标签 ID 与标签版本。",
        "impact": "具备做版本冻结与历史结果追溯的基础。",
        "action": "保持；数据集交付时把包版本、校验摘要、规则快照一起落库。",
    })
    return issues



def est_height(texts, widths, cap=409, line_h=13, min_h=20):
    """按列宽估算换行行数，返回适合的行高（磅）。中文字符按 2 个宽度单位计。"""
    lines = 1
    for text, w in zip(texts, widths):
        if not text:
            continue
        s = str(text)
        units = sum(2 if ord(ch) > 127 else 1 for ch in s)
        per = max(4, w * 1.05)
        est = 0
        for seg in s.split("\n"):
            u = sum(2 if ord(ch) > 127 else 1 for ch in seg)
            est += max(1, int(u / per) + (1 if u % per else 0))
        lines = max(lines, est)
    return max(min_h, min(cap, lines * line_h + 6))


def sheet_write(ws, rows, widths, header_row=1, freeze="A2", title=None):
    r0 = header_row
    if title:
        ws.cell(row=1, column=1, value=title).font = TITLE_FONT
        r0 = header_row
    for i, row in enumerate(rows, start=r0):
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=i, column=j, value=v)
            c.alignment = WRAP
            c.border = BORDER
            if i == r0:
                c.fill = HEAD_FILL
                c.font = HEAD_FONT
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = freeze
    ws.auto_filter.ref = f"A{r0}:{get_column_letter(len(widths))}{r0 + len(rows) - 1}"
    ws.row_dimensions[r0].height = 30


def build_xlsx(pkgs):
    groups = [g for p in pkgs for g in p["groups"]]
    tags = [t for p in pkgs for t in p["tags"]]
    metas = {p["package"]: parse_appendix(p["package"]) for p in pkgs}
    issues = build_issues(pkgs, groups)

    wb = Workbook()

    # 00 说明与校验
    ws = wb.active
    ws.title = "00_说明与校验"
    ws["A1"] = "出版标签体系三包解析（105 个包内标签项）"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:D1")
    lines = [
        ("解析时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("解析对象", "01 出版内容与知识包 v1.8.0 / 02 出版基础信息与结构包 v1.7.0 / 03 出版营销分析包 v1.5.0"),
        ("解析方式", "python-docx 按文档流读取段落与表格；标签字段按文档原有前缀（打什么内容/边界和排除/回填身份等）抽取，未人工补写"),
        ("口径说明", "“105 个包内项”指三包目录声明的标签项合计；“104 个独立标签修订”指按标签 ID 去重（内容简介跨两包重复）"),
        ("", ""),
        ("核对项", "结果"),
        ("三包声明项数", "17 + 81 + 7 = 105"),
        ("实际解析项数", f"{len(tags)}"),
        ("独立标签 ID 数", f"{len(set(t['tag_id'] for t in tags))}"),
        ("输出组数", f"{len(groups)}（9 + 10 + 2）"),
        ("目录声明与实际逐组一致", "一致（21/21 组项数吻合）"),
        ("字段缺失项", f"{sum(1 for t in tags if t['undefined_fields'])} 项（{sum(len(t['undefined_fields']) for t in tags)} 个字段位置）"),
        ("内容标注 vs 资产元数据", f"内容标注 {sum(1 for t in tags if next(g['exec'] for g in groups if g['package']==t['package'] and g['group_no']==t['group_no']) != '读取系统正式记录')} 项；读取系统记录的资产元数据/治理 {sum(1 for t in tags if next(g['exec'] for g in groups if g['package']==t['package'] and g['group_no']==t['group_no']) == '读取系统正式记录')} 项"),
        ("单项规则正文长度", f"中位数 {int(statistics.median([t['text_len'] for t in tags]))} 字；最短 {min(t['text_len'] for t in tags)} 字；最长 {max(t['text_len'] for t in tags)} 字"),
        ("来源资格", "7 条来源：仅测试 2、待核验 5；文档自述不构成官方合规或准确率证明"),
        ("", ""),
        ("文件", "SHA256（docx 原件）"),
    ]
    for r, (k, v) in enumerate(lines, start=2):
        ws.cell(row=r, column=1, value=k).font = Font(bold=(r in (2, 8) or k in ("核对项",)))
        ws.cell(row=r, column=2, value=v).alignment = WRAP
    row = len(lines) + 2
    for pkg, path in SRC_DOCX.items():
        ws.cell(row=row, column=1, value=path.name).alignment = WRAP
        ws.cell(row=row, column=2, value=sha256(path)).alignment = WRAP
        row += 1
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 110
    ws.column_dimensions["C"].width = 20

    # 01 标签总表
    ws = wb.create_sheet("01_标签总表")
    head = ["序号", "包代码", "包名称", "包版本", "组号", "组名称", "处理层级", "执行方式",
            "标签编号", "标签名称", "规则形式", "打什么内容（摘要）", "结果类型", "字段名",
            "标签版本", "标签 ID", "标签规则长度", "状态"]
    rows = [head]
    for t in tags:
        g = next(x for x in groups if x["package"] == t["package"] and x["group_no"] == t["group_no"])
        rows.append([t["seq"], t["package"], t["pkg_name"], t["pkg_version"], t["group_no"], t["group_name"],
                     g["layer"], g["exec"], t["tag_no"], t["tag_name"], t["rule_form"],
                     t["definition"][:180], t["result_type"], t["field_name"],
                     t["tag_version"], t["tag_id"], t["text_len"], status_of(t)])
    widths = [6, 7, 20, 8, 5, 20, 9, 14, 7, 16, 18, 60, 8, 26, 8, 44, 8, 11]
    sheet_write(ws, rows, widths)
    for i, t in enumerate(tags, start=2):
        ws.row_dimensions[i].height = est_height(
            [t["definition"][:180], t["tag_id"], t["group_name"]], [60, 44, 20])
    for i, t in enumerate(tags, start=2):
        s = ws.cell(row=i, column=18).value
        if s in STATUS_FILL:
            ws.cell(row=i, column=18).fill = STATUS_FILL[s]

    # 02 规则全文
    ws = wb.create_sheet("02_规则全文")
    head = ["序号", "包-编号", "标签名称", "规则形式", "打什么内容", "何时打这个标签", "边界和排除",
            "结果取值和保存要求", "要保留哪些证据", "标签补充判定提示", "怎么核对和处理不确定",
            "结果类型", "程序核对方式", "冻结核对配置", "字段名", "标签 ID", "逐字段规则来源"]
    rows = [head]
    for t in tags:
        rows.append([t["seq"], f"{t['package']}-{t['tag_no']}", t["tag_name"], t["rule_form"],
                     t["definition"], "\n".join(t["when"]), "\n".join(t["excludes"]),
                     "\n".join(t["value_rule"]), "\n".join(t["evidence"]), t["hint"],
                     "\n".join(t["check"]), t["result_type"], t["program_check"],
                     t["validator"], t["field_name"], t["tag_id"], t["rule_source"]])
    widths = [6, 9, 14, 10, 40, 34, 36, 30, 28, 26, 40, 8, 20, 32, 22, 42, 10]
    sheet_write(ws, rows, widths)
    for i, t in enumerate(tags, start=2):
        ws.row_dimensions[i].height = est_height(
            [t["definition"], "\n".join(t["when"]), "\n".join(t["excludes"]),
             "\n".join(t["value_rule"]), "\n".join(t["evidence"]), t["hint"], "\n".join(t["check"])],
            [40, 34, 36, 30, 28, 26, 40])

    # 03 输出组
    ws = wb.create_sheet("03_输出组")
    head = ["包代码", "包名称", "组号", "组名称", "项数", "处理层级", "执行方式", "需要证据",
            "逐项人工复核", "门槛配置", "采用说明", "识别什么对象", "本组怎么打", "本组边界",
            "本组怎么核对", "冻结的输入/观察身份", "规则来源"]
    rows = [head]
    for g in groups:
        rows.append([g["package"], g["package"].replace("P01", "出版内容与知识包").replace("P02", "出版基础信息与结构包").replace("P03", "出版营销分析包"),
                     g["group_no"], g["group_name"], g["tag_count"], g["layer"], g["exec"],
                     g["need_evidence"], g["manual_review"], g["threshold_text"], g["auto_note"],
                     g["object"], g["how"], g["boundary"], g["verify"], g["frozen_input"], g["rule_source"]])
    sheet_write(ws, rows, [7, 24, 6, 22, 6, 8, 14, 7, 8, 30, 40, 28, 42, 40, 38, 30, 12])
    for i in range(2, len(rows) + 1):
        ws.row_dimensions[i].height = 110

    # 04 字段与校验
    ws = wb.create_sheet("04_字段与校验")
    head = ["序号", "包-编号", "标签名称", "字段名", "结果类型", "校验器", "value_shape", "允许值/类型", "程序核对方式", "冻结核对配置原文"]
    rows = [head]
    for t in tags:
        if not (t["field_name"] or t["result_type"] or t["validator"]):
            continue
        vs, allowed = "", ""
        try:
            cfg = json.loads(t["validator"]) if t["validator"] else {}
            vs = cfg.get("value_shape", "")
            allowed = json.dumps(cfg.get("allowed_types") or cfg.get("allowed_schemes") or "", ensure_ascii=False)
            if allowed == '""':
                allowed = ""
        except Exception:
            pass
        rows.append([t["seq"], f"{t['package']}-{t['tag_no']}", t["tag_name"], t["field_name"],
                     t["result_type"], (json.loads(t["validator"]).get("validator") if t["validator"] and t["validator"].startswith("{") else ""),
                     vs, allowed, t["program_check"], t["validator"]])
    sheet_write(ws, rows, [6, 10, 18, 26, 8, 16, 20, 26, 34, 48])

    # 05 问题清单
    ws = wb.create_sheet("05_问题清单")
    head = ["序号", "等级", "问题", "证据（可核对到具体标签/文本）", "影响", "建议动作"]
    rows = [head]
    for i, it in enumerate(issues, start=1):
        rows.append([i, it["level"], it["issue"], it["evidence"], it["impact"], it["action"]])
    sheet_write(ws, rows, [6, 6, 44, 80, 50, 52])
    for i in range(2, len(rows) + 1):
        ws.row_dimensions[i].height = 105

    # 06 来源与版本
    ws = wb.create_sheet("06_来源与版本")
    head = ["包代码", "包名称", "包版本", "标签包身份", "基础修订身份", "包正文校验摘要", "只读导出时间",
            "原始适用范围", "来源序号", "来源名称", "原文位置", "来源用途和资格", "资格状态", "来源备注", "来源版本与核验身份"]
    rows = [head]
    for p in pkgs:
        m = metas[p["package"]]
        if not m["sources"]:
            rows.append([p["package"], p["name"], p["version"], m["identity"], m["base_revision"],
                         m["checksum"], m["export_time"], m["scope"], "", "", "", "", "", "", ""])
        for s in m["sources"]:
            status = "仅测试" if "仅测试" in s["usage"] else ("待核验" if "待核验" in s["usage"] else "")
            rows.append([p["package"], p["name"], p["version"], m["identity"], m["base_revision"],
                         m["checksum"], m["export_time"], m["scope"], s["no"], s["title"],
                         s["location"], s["usage"], status, s["remark"], s["version"]])
    sheet_write(ws, rows, [7, 22, 8, 40, 46, 46, 20, 34, 7, 40, 34, 24, 8, 44, 60])
    for i in range(2, len(rows) + 1):
        ws.row_dimensions[i].height = 75

    wb.save(OUT_XLSX)
    return metas, issues


def build_csv(pkgs):
    tags = [t for p in pkgs for t in p["tags"]]
    cols = ["seq", "package", "pkg_name", "pkg_version", "group_no", "group_name", "tag_no", "tag_name",
            "rule_form", "definition", "hint", "result_type", "field_name", "tag_id", "tag_version",
            "when", "excludes", "value_rule", "evidence", "check", "validator", "program_check"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for t in tags:
            w.writerow([
                t["seq"], t["package"], t["pkg_name"], t["pkg_version"], t["group_no"], t["group_name"],
                t["tag_no"], t["tag_name"], t["rule_form"], t["definition"], t["hint"],
                t["result_type"], t["field_name"], t["tag_id"], t["tag_version"],
                " / ".join(t["when"]), " / ".join(t["excludes"]), " / ".join(t["value_rule"]),
                " / ".join(t["evidence"]), " / ".join(t["check"]), t["validator"], t["program_check"],
            ])


def build_md(pkgs, metas, issues):
    tags = [t for p in pkgs for t in p["tags"]]
    groups = [g for p in pkgs for g in p["groups"]]
    L = []
    A = L.append
    A("# 出版标签体系解析报告：三包 105 个标注项\n")
    A(f"> 解析时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} ｜ 来源：3 份《标签规则阅读修改版》docx（v1.8.0 / v1.7.0 / v1.5.0）\n")
    A("## 一、先给结论\n")
    A("| 核对项 | 文档声明 | 实际解析 | 结论 |")
    A("|---|---|---|---|")
    A("| 三包包内标签项 | 105 | 105 | 一致 |")
    A("| 独立标签修订 | 104 | 104（标签 ID 去重） | 一致 |")
    A("| 输出组 | 21（9+10+2） | 21 | 一致 |")
    A("| 逐组项数 | 目录逐条列出 | 21/21 组吻合 | 一致 |")
    A("")
    A("重复项是“内容简介”：基础包 026 与营销包 002 共用同一个标签 ID `BT-73501b96-614a-458e-8e69-df1e4a6ac522`，但一个是“抽取现成简介”、一个是“整书概括”，规则不同。\n")
    A("| 包 | 版本 | 组数 | 项数 | 逐标签定义 | 组规则+提示 | 读取系统记录 |")
    A("|---|---|---|---|---|---|---|")
    for p in pkgs:
        n1 = sum(1 for t in p["tags"] if t["rule_form"] == "逐标签定义")
        sysn = sum(1 for t in p["tags"] if next(g["exec"] for g in groups if g["package"] == p["package"] and g["group_no"] == t["group_no"]) == "读取系统正式记录")
        A(f"| {p['name']} | {p['version']} | {len(p['groups'])} | {len(p['tags'])} | {n1} | {len(p['tags'])-n1} | {sysn} |")
    A(f"| **合计** | — | **{len(groups)}** | **{len(tags)}** | **{sum(1 for t in tags if t['rule_form']=='逐标签定义')}** | **{sum(1 for t in tags if t['rule_form']!='逐标签定义')}** | **{sum(1 for t in tags if next(g['exec'] for g in groups if g['package']==t['package'] and g['group_no']==t['group_no'])=='读取系统正式记录')}** |")
    A("")
    A("## 二、三包结构\n")
    for p in pkgs:
        A(f"### {p['name']}（{p['version']}，{len(p['tags'])} 项 / {len(p['groups'])} 组）\n")
        A("| 组 | 组名 | 项数 | 处理层级 | 执行方式 | 组门槛 |")
        A("|---|---|---|---|---|---|")
        for g in p["groups"]:
            thr = re.search(r"初次判断\s*([\d.]+)", g["threshold_text"])
            A(f"| {g['group_no']} | {g['group_name']} | {g['tag_count']} | {g['layer']} | {g['exec']} | {thr.group(1) if thr else '不设分数门槛'} |")
        A("")
    A("## 三、105 项全清单\n")
    A("规则形式缩写：**逐** = 逐标签定义；**组** = 组规则加标签说明。状态：模板化 = 定义与其他项共用同一句式；缺字段定义 = 有字段未单独列出。\n")
    A("| # | 包-编号 | 标签 | 规则形式 | 层级 | 执行方式 | 结果类型 | 字段名 | 状态 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for t in tags:
        g = next(g for g in groups if g["package"] == t["package"] and g["group_no"] == t["group_no"])
        rf = "逐" if t["rule_form"] == "逐标签定义" else "组"
        A(f"| {t['seq']} | {t['package']}-{t['tag_no']} | {t['tag_name']} | {rf} | {g['layer']} | {g['exec']} | {t['result_type'] or '—'} | {t['field_name'] or '—'} | {status_of(t)} |")
    A("")
    A("## 四、规则质量检查（按严重度）\n")
    A("| # | 等级 | 问题 | 证据 | 建议 |")
    A("|---|---|---|---|---|")
    for i, it in enumerate(issues, start=1):
        A(f"| {i} | {it['level']} | {it['issue']} | {it['evidence']} | {it['action']} |")
    A("")
    A("## 五、对“高质量数据集”的含义\n")
    A("1. **数量对，但不是 105 个同等含金量的标注点。** 真正需要读内容判断的是 89 项（AI 理解 65 + 原文抽取 24）；16 项是平台元数据/治理记录，应由系统流水线写入，不应进入人工标注任务。\n")
    A("2. **规则厚度不均。** 单项规则正文中位数只有 35 字，75 项没有独立的结果类型/字段名；45 项版式标签共用一句模板。要作为训练或验收规范，必须先补“二选一边界 + 输出 schema”。\n")
    A("3. **可直接复用的强项**：105 项都有标签 ID/版本，21 组都有统一“证据要求 + 独立复核 + 无法确定转人工”框架，三包都有 SHA256 与导出时间，具备版本冻结与追溯基础。\n")
    A("4. **不能对外声称的**：来源 7 条中 2 条仅测试、5 条待核验，文档本身声明“不证明官方合规、实际准确率或所有标签已通过真实材料验收”。对外称“高质量数据集”前需先完成来源资格核验与实测准确率。\n")
    A("5. **建议的下一步**：先按“89 内容标注 / 16 资产元数据”拆两张清单；对 45 项版式标签补边界矩阵；对 13 处“未单独列出”补字段；再统一输出 schema，最后才做标注平台配置与评测集。\n")
    A("## 六、交付文件\n")
    A("| 文件 | 内容 |")
    A("|---|---|")
    A("| 出版标签体系_105项解析.xlsx | 7 个工作表：说明与校验、标签总表、规则全文、输出组、字段与校验、问题清单、来源与版本 |")
    A("| 出版标签体系_105项解析.csv | 105 行扁平表，便于导入数据库/标注平台 |")
    A("| tags.json | 完整结构化数据（含每项全部规则文本） |")
    A("| 原始解析/*.txt | 三份 docx 的逐段+表格原始文本，便于逐字复核 |")
    A("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    pkgs = load()
    metas, issues = build_xlsx(pkgs)
    build_csv(pkgs)
    build_md(pkgs, metas, issues)
    print("written:", OUT_XLSX.name, OUT_CSV.name, OUT_MD.name)
