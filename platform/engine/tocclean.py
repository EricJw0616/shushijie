# -*- coding: utf-8 -*-
"""目录/索引页清洗与结构审计。

为什么单独一层：PDF 抽取会把书前目录当成正文，目录里又会出现「第十四章 …」
这种章标题。结构探测取第一次出现的标题，于是目录被切成第一章，真正的正文
反而被挂到后面。页面只是如实显示，问题在切分输入。

本模块只做两件事：
  1. clean(text)  —— 在判型/切段之前，去掉成块的目录/索引行；无目录时原样返回
  2. audit(segs, outline) —— 对已切好的产物做只读体检，给页面与全库报告用

硬约束：
  · 只在检测到「成块目录」时改文本；普通书零改动（保证旧书产物不变）
  · 不合并、不改写正文，只删目录行
  · 删了什么、删了多少行/字，必须落盘可复核
"""
import re

HAN = re.compile('[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF'
                 '\U00020000-\U0002FA1F]')
# 目录行的典型形态：一行里至少 6 个点/省略号/下划线，通常后面跟页码。
DOT_LINE = re.compile(r'(?:\.{6,}|…{3,}|·{3,}|_{6,})\s*\d{0,4}\s*$')
DOT_ANY = re.compile(r'(?:\.{6,}|…{3,}|·{3,}|_{6,})')
TOC_MARK = re.compile(r'^\s*(目\s*录|目\s*錄|Contents|CONTENTS|索引|索\s*引)\s*$')
HEADING = re.compile(r'^\s*(?:第[一二三四五六七八九十百零〇两]+[章节篇回]|'
                     r'[一二三四五六七八九十]+[、.]|各论|總論|总论|附\s*录|附录)')
CHAPTER = re.compile(r'第([一二三四五六七八九十百零〇两]+)章')
PAGE_LINE = re.compile(r'^<<<PAGE \d+>>>$')
BROKEN_TEXT = re.compile(r'\ufffd{3,}')

_CN = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
       '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def _cn_num(s):
    """中文数字 → int，只覆盖章号常见的 1–999。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    total, section, num = 0, 0, 0
    for ch in s:
        if ch == '百':
            section = (section or 1) * 100
        elif ch == '十':
            section = (section or 1) * 10
        elif ch in _CN:
            num = _CN[ch]
            section += num
        else:
            return None
    return total + section


def _dot_count(line):
    return len(DOT_ANY.findall(line or ''))


def clean(text):
    """返回 (清理后文本, 清洗记录)。无成块目录时 text 原样返回。"""
    if not text:
        return text, {'检测': '无', '删除行数': 0, '删除汉字': 0}
    lines = text.splitlines()
    idx = [i for i, l in enumerate(lines) if DOT_LINE.search(l)]
    if not idx:
        return text, {'检测': '无', '删除行数': 0, '删除汉字': 0}

    # 目录行按间隔聚簇；间隔 >12 行视为两段（正文里偶尔出现的点线不该连带删）。
    clusters, cur = [], []
    for i in idx:
        if cur and i - cur[-1] > 12:
            clusters.append(cur)
            cur = []
        cur.append(i)
    if cur:
        clusters.append(cur)

    blocks = []
    for c in clusters:
        if len(c) < 12:
            continue
        start, end = c[0], c[-1]
        # 往前扩：目录标题、章标题、各论/总论等，通常紧贴在目录第一行前。
        j = start - 1
        steps = 0
        while j >= 0 and steps < 20:
            s = lines[j].strip()
            if not s:
                j -= 1
                steps += 1
                continue
            if TOC_MARK.match(s) or HEADING.match(s):
                start = j
                j -= 1
                steps += 1
                continue
            break
        # 往后扩：目录尾部的空行不删正文；只把紧邻的目录行/标题纳入。
        j = end + 1
        steps = 0
        while j < len(lines) and steps < 3:
            s = lines[j].strip()
            if not s:
                j += 1
                steps += 1
                continue
            if DOT_LINE.search(s) or TOC_MARK.match(s):
                end = j
                j += 1
                steps += 1
                continue
            break
        blocks.append((start, end))

    if not blocks:
        return text, {'检测': '无', '删除行数': 0, '删除汉字': 0}

    # 合并重叠区块，按行删除。
    blocks.sort()
    merged = []
    for a, b in blocks:
        if merged and a <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    drop = set()
    for a, b in merged:
        drop.update(range(a, b + 1))
    # Ingested PDF text uses these separators to retain the original page number.
    kept = [l for i, l in enumerate(lines) if i not in drop or PAGE_LINE.fullmatch(l)]
    removed = [l for i, l in enumerate(lines) if i in drop and not PAGE_LINE.fullmatch(l)]
    out = '\n'.join(kept)
    if text.endswith('\n') and not out.endswith('\n'):
        out += '\n'
    info = {
        '检测': '目录块',
        '删除行数': len(removed),
        '删除汉字': sum(len(HAN.findall(l)) for l in removed),
        '区块': [{'起行': a + 1, '止行': b + 1,
                  '行数': b - a + 1} for a, b in merged],
        '目录标记': any(TOC_MARK.match(l.strip()) for l in removed),
    }
    return out, info


def is_parent_heading(title, following):
    return bool(title and str(following or '').startswith(str(title) + ' · '))


def audit(segs, outline, source_text=None):
    """只读体检。返回可落进 book.json 的审计结果。"""
    toc_segs, broken, formulas = [], [], []
    picture_pages = set()
    for s in segs or []:
        if s.get('篇序', 0) <= 0:
            continue  # 前置里的目录不算「正文混目录」
        text = s.get('文本') or ''
        if BROKEN_TEXT.search(text):
            broken.append(s)
        elif s.get('source_layout_issue') == 'formula_or_encoding':
            formulas.append(s)
        if s.get('source_layout_issue') == 'picture_dominant' and s.get('source_page'):
            picture_pages.add(s['source_page'])
        n = _dot_count(text)
        if n >= 3:
            toc_segs.append({'锚点': s.get('锚点'), '篇': s.get('篇'),
                             '篇序': s.get('篇序'), '点线数': n})
    def _title(o):
        if isinstance(o, dict):
            return o.get('篇')
        if isinstance(o, (list, tuple)) and o:
            return o[0]
        return str(o)
    titles = [_title(o) for o in (outline or [])]
    from collections import Counter
    dup = [{'篇': k, '次数': v} for k, v in Counter(titles).items() if v > 1]

    nums = []
    for t in titles:
        m = CHAPTER.search(str(t or ''))
        if m:
            n = _cn_num(m.group(1))
            if n:
                nums.append(n)
    order_bad = False
    if len(nums) >= 3:
        # 章号应大体递增；首章不是 1 或出现明显回退（如 14 → 1）即异常。
        if nums[0] != 1 or any(nums[i] > nums[i + 1] for i in range(len(nums) - 1)):
            order_bad = True
    # 很短的章节不能直接判成错误，但必须复核；目录尾行常被误当成附录。
    grouped = {}
    parent_dividers = set()
    for i, (entry, title) in enumerate(zip(outline or [], titles)):
        number = entry.get('篇序', i + 1) if isinstance(entry, dict) else i + 1
        key = number, title or ''
        if i + 1 == len(titles) or not is_parent_heading(title, titles[i + 1]):
            grouped[key] = 0
        else:
            parent_dividers.add(key)
    for seg in segs or []:
        if seg.get('篇序', 0) > 0:
            key = (seg.get('篇序'), seg.get('篇') or '')
            if key not in grouped and not len(HAN.findall(seg.get('文本') or '')):
                continue
            grouped[key] = grouped.get(key, 0) + len(HAN.findall(seg.get('文本') or ''))
    short = [{'篇序': k[0], '篇': k[1], '汉字': n} for k, n in grouped.items()
             if n < 30 and k not in parent_dividers]
    sizes = sorted(grouped.values(), reverse=True)
    total = sum(sizes)
    concentrated = (len(sizes) >= 3 and sizes[0] >= 2000
                    and sizes[0] >= total * .72 and sizes[1] <= sizes[0] * .12)
    unstructured = bool(segs and not outline)
    missed = []
    if source_text and not outline:
        pattern = re.compile(r'^第[一二三四五六七八九十百零〇0-9]+(?:[篇章节回]|[\s　]+[^。！？]{1,20}[篇章])')
        missed = [line.strip() for line in source_text.splitlines() if pattern.match(line.strip())]
    structure_abnormal = bool(toc_segs or order_bad or short or unstructured or concentrated or broken)
    abnormal = structure_abnormal or bool(formulas or picture_pages)
    chapters = {seg['篇序'] for seg in short + toc_segs + broken if seg.get('篇序') is not None}
    if concentrated or order_bad:
        chapters.update(number for number, _ in grouped)
    if unstructured:
        chapters.add(0)
    notes = []
    if unstructured:
        notes.append('未识别出章节结构，需核对原文；不能据此认定本书没有章节')
    if missed:
        notes.append('原文有 %d 个疑似章节标题未识别' % len(missed))
    if short:
        notes.append('%d 个章节没有正文或正文很短，请核对章节位置' % len(short))
    if toc_segs:
        notes.append('有 %d 段目录内容可能混进了正文' % len(toc_segs))
    if concentrated:
        notes.append('约 %d%% 的正文都落在一章，请核对章节划分' % round(sizes[0] * 100 / total))
    if broken:
        notes.append('有 %d 段文字没能完整读取，请查看原书' % len(broken))
    if formulas:
        notes.append('有 %d 段公式或特殊字符需对照原书核对' % len(formulas))
    if picture_pages:
        notes.append('有 %d 个正文页面以图片为主，只能读到少量文字' % len(picture_pages))
    if order_bad:
        notes.append('章号顺序异常：%s' % ('→'.join(str(x) for x in nums[:20])))
    if dup:
        notes.append('重复篇名 %d 个（同名诗/条目可能正常）' % len(dup))
    return {
        '异常': abnormal,
        '目录残留段': toc_segs[:20],
        '异常短篇': short[:30],
        '结构待复核': structure_abnormal,
        '受影响篇序': sorted(chapters),
        '章节过度集中': concentrated,
        '破损正文段': [seg.get('id') for seg in broken[:30]],
        '公式或字符待核对段': [seg.get('id') for seg in formulas[:30]],
        '图片为主正文页': sorted(picture_pages),
        '遗漏标题': missed[:30],
        '章号顺序异常': order_bad,
        '章号序列': nums[:40],
        '重复篇名': dup[:30],
        '说明': '；'.join(notes),
    }
