#!/usr/bin/env python3
"""解析三份标签规则 docx，输出结构化 JSON（标签、输出组、包元信息）。

只使用文档中明确写出的字段，不推断、不补全。
"""
import json
import re
from pathlib import Path

from docx import Document

BASE = Path(__file__).resolve().parent
RAW = BASE / "原始解析"

FILES = [
    ("P01", "01_内容与知识包.txt", "出版内容与知识包", "publishing_structured_knowledge", "1.8.0"),
    ("P02", "02_基础信息与结构包.txt", "出版基础信息与结构包", "publishing_dataset_foundation", "1.7.0"),
    ("P03", "03_营销分析包.txt", "出版营销分析包", "publishing_marketing_insight", "1.5.0"),
]

TAG_RE = re.compile(r"^(\d{3})\s+(.+)$")
GROUP_RE = re.compile(r"^(\d{2})\s+(.+)$")

FIELD_PREFIXES = [
    ("rule_form", r"^规则形式[：:]\s*"),
    ("definition", r"^打什么内容[：:]\s*"),
    ("hint", r"^标签补充判定提示[：:]\s*"),
    ("same_name", r"^同名标签提醒[：:]\s*"),
    ("materials", r"^看哪些资料\s*\d*\s*[：:]\s*"),
    ("当", r"^何时打这个标签\s*\d*\s*[：:]\s*"),
    ("excludes", r"^边界和排除\s*\d*\s*[：:]\s*"),
    ("value_rule", r"^结果取值和保存要求\s*\d*\s*[：:]\s*"),
    ("evidence", r"^要保留哪些证据\s*\d*\s*[：:]\s*"),
    ("check", r"^怎么核对和处理不确定\s*\d*\s*[：:]\s*"),
    ("result_type", r"^结果类型[：:]\s*"),
    ("program_check", r"^程序核对方式[：:]\s*"),
    ("validator", r"^冻结核对配置[：:]\s*"),
    ("observe_scope", r"^文档观察范围[：:]\s*"),
    ("freeze_observe", r"^冻结观察配置[：:]\s*"),
    ("rule_source", r"^逐字段规则来源[：:]\s*"),
    ("fill_identity", r"^回填身份[：:]\s*"),
    ("remark", r"^修改意见[：:]\s*"),
]

GROUP_FIELD_PREFIXES = [
    ("layer", r"^处理层级[：:]\s*"),
    ("exec", r"^执行方式[：:]\s*"),
    ("need_evidence", r"^需要证据[：:]\s*"),
    ("manual_review", r"^配置要求逐项人工复核[：:]\s*"),
    ("auto_note", r"^包内声明"),
    ("auto_note2", r"^包内允许"),
    ("thresholds", r"^配置原值[：:]\s*"),
    ("threshold_note", r"^使用分数方式时"),
    ("shared_note", r"^本组以各标签"),
    ("shared_materials", r"^本组共用资料要求"),
    ("object", r"^识别什么对象[：:]\s*"),
    ("how", r"^本组怎么打[：:]\s*"),
    ("boundary", r"^本组边界[：:]\s*"),
    ("verify", r"^本组怎么核对[：:]\s*"),
    ("member_hint", r"^本组各标签使用下面"),
    ("frozen_input", r"^冻结的输入或观察身份[：:]\s*"),
    ("rule_source", r"^本组规则来源[：:]\s*"),
]


def parse_dump(path):
    """把 dump_docx.py 的文本还原为 [(kind, payload)]，kind in {p, table_row, file}."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("P") and len(line) > 5 and line[1:5].isdigit():
            body = line[5:].strip()
            style = ""
            m = re.match(r"^\[([^\]]+)\]\s*(.*)$", body)
            if m:
                style, body = m.group(1), m.group(2)
            out.append(("p", style, body))
        elif line.startswith("R") and "|" in line:
            out.append(("row", "", line))
    return out


def new_field():
    return {k: [] for k, _ in FIELD_PREFIXES}


def match_field(text, prefixes):
    for key, pat in prefixes:
        m = re.match(pat, text)
        if m:
            return key, text[m.end():].strip()
    return None, None


def parse_package(pkg_id, fname, pkg_name, package_key, version):
    items = parse_dump(RAW / fname)
    groups, tags = [], []
    cur_group = None
    cur_tag = None

    def close_tag():
        nonlocal cur_tag
        if not cur_tag:
            return
        t = cur_tag
        fields = t["fields"]
        # 回填身份
        ident = "\n".join(fields["fill_identity"]).strip()
        m = re.search(r"(BT-[A-Za-z0-9\-]+)", ident)
        t["tag_id"] = m.group(1) if m else ""
        m = re.search(r"标签\s*([\d.]+)\s*修订\s*(\d+)", ident)
        t["tag_version"] = m.group(1) if m else ""
        t["tag_revision"] = int(m.group(2)) if m else None
        m = re.search(r"字段\s*([a-z_0-9]+)", ident)
        t["field_name"] = m.group(1) if m else ""
        # 去空
        for k in fields:
            fields[k] = [x for x in fields[k] if x]
        t["definition"] = "\n".join(fields["definition"]).strip()
        t["hint"] = "\n".join(fields["hint"]).strip()
        t["same_name_note"] = "\n".join(fields["same_name"]).strip()
        t["result_type"] = "\n".join(fields["result_type"]).strip()
        t["program_check"] = "\n".join(fields["program_check"]).strip()
        t["validator"] = "\n".join(fields["validator"]).strip()
        t["observe_scope"] = "\n".join(fields["observe_scope"]).strip()
        t["freeze_observe"] = "\n".join(fields["freeze_observe"]).strip()
        t["rule_source"] = "\n".join(fields["rule_source"]).strip()
        t["rule_form"] = "\n".join(fields["rule_form"]).strip()
        t["materials"] = fields["materials"]
        t["when"] = fields["当"]
        t["excludes"] = fields["excludes"]
        t["value_rule"] = fields["value_rule"]
        t["evidence"] = fields["evidence"]
        t["check"] = fields["check"]
        t["undefined_fields"] = [
            k for k, label in [
                ("when", "何时打这个标签"), ("excludes", "边界和排除"),
                ("value_rule", "结果取值和保存要求"),
            ] if any("当前版本未单独列出此项" in x for x in t[k])
        ]
        t["text_len"] = len(t["definition"]) + sum(len(x) for x in t["when"] + t["excludes"] + t["value_rule"] + t["evidence"] + t["check"])
        t["group_no"] = cur_group["group_no"] if cur_group else ""
        t["group_name"] = cur_group["group_name"] if cur_group else ""
        t.pop("fields", None)
        tags.append(t)
        cur_tag = None

    for kind, style, body in items:
        if kind != "p" or not body:
            continue
        if style == "Heading 1":
            close_tag()
            m = GROUP_RE.match(body)
            if m and not body.startswith("附录"):
                cur_group = {
                    "package": pkg_id, "group_no": m.group(1),
                    "group_name": m.group(2).strip(), "count_declared": None,
                    "fields": {k: [] for k, _ in GROUP_FIELD_PREFIXES},
                }
                groups.append(cur_group)
            else:
                cur_group = None
            continue
        if style == "Heading 2":
            close_tag()
            m = TAG_RE.match(body)
            if m:
                cur_tag = {
                    "package": pkg_id, "tag_no": m.group(1),
                    "tag_name": m.group(2).strip(), "fields": new_field(),
                }
            continue
        if cur_tag is not None:
            key, val = match_field(body, FIELD_PREFIXES)
            if key:
                if val:
                    cur_tag["fields"][key].append(val)
                cur_tag["_last"] = key
            elif body.startswith("修改意见"):
                cur_tag["_last"] = "remark"
            else:
                last = cur_tag.get("_last", "remark")
                cur_tag["fields"][last].append(body)
            continue
        if cur_group is not None:
            key, val = match_field(body, GROUP_FIELD_PREFIXES)
            if key:
                if val:
                    cur_group["fields"][key].append(val)
                cur_group["_last"] = key
            else:
                last = cur_group.get("_last")
                if last:
                    cur_group["fields"][last].append(body)
    close_tag()

    # 组装组
    for g in groups:
        f = g.pop("fields")
        g["layer"] = "\n".join(f["layer"]).strip()
        # 处理层级与执行方式写在同一行，用“；”分隔，需拆开
        first = g["layer"].split("\n")[0]
        kv = dict(re.findall(r"(执行方式|需要证据|配置要求逐项人工复核)\s*[：:]\s*([^；;]+)", first))
        g["layer"] = first.split("；")[0].strip()
        g["exec"] = kv.get("执行方式", "").strip()
        g["need_evidence"] = kv.get("需要证据", "").strip()
        g["manual_review"] = kv.get("配置要求逐项人工复核", "").strip()
        g["layer_note"] = "\n".join(f["layer"][1:]).strip()
        g["exec"] = "\n".join(f["exec"]).strip() or g["exec"]
        g["need_evidence"] = "\n".join(f["need_evidence"]).strip() or g["need_evidence"]
        g["manual_review"] = "\n".join(f["manual_review"]).strip() or g["manual_review"]
        g["auto_note"] = "\n".join(f["auto_note"] + f["auto_note2"]).strip()
        g["threshold_text"] = "\n".join(f["thresholds"]).strip()
        g["threshold_note"] = "\n".join(f["threshold_note"]).strip()
        g["shared_note"] = "\n".join(f["shared_note"]).strip()
        g["shared_materials"] = "\n".join(f["shared_materials"]).strip()
        g["object"] = "\n".join(f["object"]).strip()
        g["how"] = "\n".join(f["how"]).strip()
        g["boundary"] = "\n".join(f["boundary"]).strip()
        g["verify"] = "\n".join(f["verify"]).strip()
        g["member_hint"] = "\n".join(f["member_hint"]).strip()
        g["frozen_input"] = "\n".join(f["frozen_input"]).strip()
        g["rule_source"] = "\n".join(f["rule_source"]).strip()
        g["tag_count"] = sum(1 for t in tags if t["group_no"] == g["group_no"] and t["package"] == pkg_id)

    return {"package": pkg_id, "name": pkg_name, "package_key": package_key,
            "version": version, "groups": groups, "tags": tags}


def merge():
    result = []
    for pkg_id, fname, pkg_name, key, ver in FILES:
        result.append(parse_package(pkg_id, fname, pkg_name, key, ver))
    return result


if __name__ == "__main__":
    pkgs = merge()
    total_tags = sum(len(p["tags"]) for p in pkgs)
    total_groups = sum(len(p["groups"]) for p in pkgs)
    print(f"packages={len(pkgs)} groups={total_groups} tags={total_tags}")
    for p in pkgs:
        print(f"  {p['package']} {p['name']} v{p['version']}: groups={len(p['groups'])} tags={len(p['tags'])}")
    ids = [t["tag_id"] for p in pkgs for t in p["tags"]]
    print(f"unique ids={len(set(ids))} empty ids={ids.count('')}")
    # 每包内组标签数核对
    for p in pkgs:
        print(" ", p["package"], [(g["group_no"], g["group_name"], g["tag_count"]) for g in p["groups"]])
    (BASE / "tags.json").write_text(json.dumps(pkgs, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written tags.json")
