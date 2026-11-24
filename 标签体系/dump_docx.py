#!/usr/bin/env python3
"""按文档流顺序导出 docx 的全部结构（段落 + 表格），输出为便于阅读的纯文本。"""
import sys
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn


def iter_block_items(parent):
    body = parent.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def cell_text(cell):
    parts = []
    for p in cell.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(t)
    return " / ".join(parts)


def dump(path, out):
    doc = Document(path)
    lines = []
    lines.append(f"===== FILE: {path} =====")
    lines.append(f"===== paragraphs={len(doc.paragraphs)} tables={len(doc.tables)} =====")
    pi = 0
    ti = 0
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            pi += 1
            text = block.text.strip()
            style = block.style.name if block.style is not None else ""
            if not text:
                continue
            prefix = ""
            if style and style.lower() != "normal":
                prefix = f"[{style}] "
            lines.append(f"P{pi:04d} {prefix}{text}")
        else:
            ti += 1
            lines.append(f"--- TABLE {ti} ({len(block.rows)}x{len(block.columns)}) ---")
            seen = set()
            for ri, row in enumerate(block.rows):
                vals = []
                for cell in row.cells:
                    key = id(cell._tc)
                    if key in seen:
                        vals.append("<merged>")
                    else:
                        seen.add(key)
                        vals.append(cell_text(cell))
                lines.append(f"R{ri:03d} | " + " | ".join(vals))
            lines.append(f"--- END TABLE {ti} ---")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{path} -> {out} ({len(lines)} lines)")


if __name__ == "__main__":
    dump(sys.argv[1], sys.argv[2])
