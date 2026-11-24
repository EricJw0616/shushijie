# -*- coding: utf-8 -*-
"""古腾堡中文文本清洗：去掉页眉页脚与每行硬折行。

为什么必须单独写：古腾堡的 txt 按 78 字节硬折行，
若不去掉，「行中位长」永远是 30 上下、句读被切断，
六轴里的 savg/smed 全部失真 —— 会把诗判成散文，把散文判成诗。
"""
import re


def strip_gutenberg(t):
    # 取 *** START OF ... *** 与 *** END OF ... *** 之间
    m = re.search(r'\*\*\*\s*START OF[^\n]*\*\*\*(.*?)\*\*\*\s*END OF',
                  t, re.S | re.I)
    if m:
        t = m.group(1)
    # 去古腾堡版权声明块（部分书没有 START/END 标记）
    t = re.sub(r'This eBook is for the use of anyone anywhere.*?\n\n', '', t, flags=re.S)
    t = re.sub(r'Project Gutenberg[^\n]*\n', '', t)
    return t


def unwrap(t):
    """把硬折行接回自然段。

    规则：某行若不以句末标点/段落标记结尾，而下一行非空，
    则视为同一段被折断，接起来。诗行（短行）保留。

    分隔虚线必须先删：底本用 `-------`（60+ 字符）画章回分界，
    长度超过 14，于是被当成正文与回目标题粘成一行 ——
    《红楼梦》回目因此与正文连成「第一回　甄士隱…-------------此開卷第…」，
    以「第X回」开头的标题行判据全部失效，120 回只剩 62 回。
    """
    # 分隔线：连续 3 个以上的 - = _ * ~ 或全角破折号，独立成行
    t = re.sub(r'^[ \t]*[-=_*~─—－]{3,}[ \t]*$', '', t, flags=re.M)
    lines = t.split('\n')
    out = []
    buf = ''
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            if buf:
                out.append(buf)
                buf = ''
            out.append('')
            continue
        # 短行（<=14 字）视为标题/诗行，独立成行
        if len(s.strip()) <= 14:
            if buf:
                out.append(buf)
                buf = ''
            out.append(s.strip())
            continue
        # 章回标题行：以「第X回/出/章/卷」开头，且标题部分本身不长。
        # 这类行必须独立成行 —— 否则会被当成上一段正文的续行接掉，
        # 整本书结构全丢（实测红楼梦 120 回 → 62 回）。
        if re.match(r'^第[一二三四五六七八九十百零〇0-9]{1,4}[回出章卷节篇部]', s.strip()) \
                and len(s.strip()) <= 40:
            if buf:
                out.append(buf)
                buf = ''
            out.append(s.strip())
            continue
        if not buf:
            buf = s.strip()
        else:
            buf += s.strip()
        # 以句末标点结尾 → 段落结束
        if re.search(r'[。！？；：”』」]$', buf):
            out.append(buf)
            buf = ''
    if buf:
        out.append(buf)
    return '\n'.join(out)


def clean(t):
    return unwrap(strip_gutenberg(t))