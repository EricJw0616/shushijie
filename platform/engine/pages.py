# -*- coding: utf-8 -*-
"""第 2 期：页面结构识别（12 项）。

输入：书库分类/raw/<书名>.layout.jsonl（每页每行的文字、坐标、行类型）
输出：platform/out/<code>/page_roles.json

原则：
  1. 只判“这一页是什么”，不改版面、不改切分。
  2. 一页可以同时属于多个结构（例如 CIP 和前言同页），roles 用区间表示，允许重叠。
  3. 判不准就标 needs_review / not_found，不硬塞；封面是图像，文字层判不了就明说。
  4. 没有页面数据的书（DOCX/TXT）页级项标 not_applicable，不假装按页判了。
"""
import io
import json
import os
import re
import sys

import paths as P

ROLES = [
    ('cover', '封面'),
    ('copyright', '版权页'),
    ('title_page', '书名页'),
    ('toc', '目录'),
    ('preface', '前言'),
    ('body', '正文内容'),
    ('headings', '标题层级'),
    ('postscript', '后记'),
    ('appendix', '附录'),
    ('references', '参考文献'),
    ('index', '索引'),
    ('errata', '勘误表'),
]

BACK_WORDS = {
    'postscript': re.compile(r'后\s*记|跋|结\s*语'),
    'appendix': re.compile(r'附\s*录'),
    'references': re.compile(r'参考文献|引用书目|参考书目'),
    'index': re.compile(r'索\s*引'),
    'errata': re.compile(r'勘\s*误'),
}

FRONT_WORDS = re.compile(r'前\s*言|序\s*言|导\s*读|编者的话|自\s*序|代\s*序')
CHAPTER = re.compile(r'第[一二三四五六七八九十百零〇0-9]{1,4}\s*章')
CHAPTER_EN = re.compile(r'Chapter\s*[0-9]{1,3}', re.I)
ENTRY = re.compile(r'姓名\s*[：:]|生卒年\s*[：:]|来\s*源|生\s*境|分\s*布')


def _norm(s):
    return re.sub(r'[\s\u3000\xa0]+', '', s or '')


def page_text(pg, include_header=False):
    parts = []
    for ln in pg.get('lines') or []:
        if not include_header and ln.get('k') == 'header':
            continue
        t = ln.get('t') or ''
        if t.strip():
            parts.append(t)
    return ' '.join(parts)


def page_norm(pg):
    return _norm(page_text(pg))


def page_lines(pg):
    return [ln for ln in (pg.get('lines') or []) if (ln.get('t') or '').strip()]


def is_empty(pg):
    return not page_norm(pg)


def is_short(pg, max_lines=3, max_len=40):
    return len(page_lines(pg)) <= max_lines and len(page_norm(pg)) <= max_len


def dot_lines(pg):
    n = 0
    for ln in page_lines(pg):
        if re.search(r'[.．…·]{5,}', ln.get('t') or ''):
            n += 1
    return n


def _toc_number_page(pg):
    """目录续页：多行短条目，且大部分行以页码结尾；正文页有页码页脚但行不短。"""
    ls = page_lines(pg)
    if len(ls) < 5:
        return False
    if any(len((ln.get('t') or '')) > 45 for ln in ls):
        return False
    n_num = sum(1 for ln in ls if re.search(r'[0-9]{1,4}\s*$', ln.get('t') or ''))
    t = page_norm(pg)
    if ENTRY.search(t) or CHAPTER.search(t):
        return False
    return n_num >= max(3, int(len(ls) * 0.5))


def _body_head(line):
    s = re.sub(r'[\s\u3000]+', '', line or '')
    if not s or len(s) > 40:
        return False
    return bool(re.match(r'^第[一二三四五六七八九十百零〇0-9]{1,4}章', s)
                or re.match(r'^Chapter[0-9]{1,3}', s, re.I)
                or re.match(r'^(姓名|生卒年)[：:]', s)
                or re.match(r'^(来源|生境|分布)[：:]?', s))


def _heading_hit(line, pat):
    s = re.sub(r'[\s\u3000]+', '', line or '')
    if not s or len(s) > 12:
        return False
    return bool(pat.match(s))


def is_toc_like(pg):
    t = page_norm(pg)
    if '目录' in t or 'CONTENTS' in t.upper():
        return True
    if dot_lines(pg) >= 3:
        return True
    return False


def page_text_full(pg):
    """页面证据用：保留全部有字行，避免把竖排页里被误判成 header 的字漏掉。"""
    parts = []
    for ln in pg.get('lines') or []:
        t = ln.get('t') or ''
        if t.strip():
            parts.append(t)
    return ' '.join(parts)


def _ev(pg, n=60):
    t = page_text_full(pg)
    return {'page': pg.get('page'), 'quote': t.strip()[:n]}


def _span(role, name, pages, confidence=0.9, note=''):
    if not pages:
        return {'role': role, 'name': name, 'status': 'not_found', 'spans': [],
                'confidence': None, 'method': 'rule', 'evidence': [], 'note': note}
    pages = sorted(pages)
    spans = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            spans.append({'from': start, 'to': prev})
            start = prev = p
    spans.append({'from': start, 'to': prev})
    return {'role': role, 'name': name, 'status': 'found', 'spans': spans,
            'confidence': confidence, 'method': 'rule',
            'evidence': [], 'note': note}


def classify_pages(pages, book='', outline=None):
    """纯函数：给页面列表，返回结构记录。便于用假页面做测试。"""
    n = len(pages)
    rec = {'book': book, 'page_count': n, 'roles': [], 'headings': [], 'stats': {}}
    if not n:
        for role, name in ROLES:
            rec['roles'].append({'role': role, 'name': name, 'status': 'not_applicable',
                                 'spans': [], 'confidence': None, 'method': '',
                                 'evidence': [], 'note': '没有页面数据（DOCX/TXT）'})
        return rec

    texts = [page_norm(p) for p in pages]
    full_texts = [_norm(page_text(p, include_header=True)) for p in pages]
    empty = [is_empty(p) for p in pages]

    # 版权页
    copyright_pages = []
    for i, t in enumerate(texts):
        if ('图书在版编目' in t or ('ISBN' in t.upper() and ('CIP数据核字' in t or '定价' in t))
                or ('责任编辑' in t and ('封面设计' in t or '出版人' in t))):
            copyright_pages.append(i)

    # 目录：从第一个“目录/CONTENTS/大量点线”页开始，向后延伸到不再是目录
    toc_start = None
    for i in range(min(n, max(1, int(n * 0.6)))):
        if texts[i] and is_toc_like(pages[i]):
            toc_start = i
            break
    toc_end = None
    if toc_start is not None:
        j = toc_start
        while j + 1 < n:
            nxt = pages[j + 1]
            if not empty[j + 1] and (is_toc_like(nxt) or _toc_number_page(nxt)):
                j += 1
            elif empty[j + 1]:
                j += 1
            else:
                break
        while j > toc_start and empty[j]:
            j -= 1
        toc_end = j

    # 前言：目录前找“前言/序/导读”
    pre_start = None
    scan = list(range((toc_end + 1) if toc_end is not None else 0, n)) + \
           list(range(0, (toc_start if toc_start is not None else n)))
    for i in scan:
        if texts[i] and FRONT_WORDS.search(texts[i]):
            pre_start = i
            break

    # 正文起点：目录之后，找章标题/条目字段；找不到再退到长正文页
    front_copyright = [i for i in copyright_pages if toc_start is not None and i < toc_start] \
        or [i for i in copyright_pages if i < (pre_start or 0)]
    search_from = 0
    for x in (toc_end, pre_start, max(front_copyright) if front_copyright else None):
        if x is not None:
            search_from = max(search_from, x + 1)

    body_start = None
    # 前言在目录之前：目录之后就是正文（总论/章前图版都算）
    preface_after_toc = (toc_start is not None and pre_start is not None and pre_start > toc_end)
    if toc_end is not None and not preface_after_toc:
        for i in range(toc_end + 1, n):
            if not empty[i]:
                body_start = i
                break
    else:
        for i in range(search_from, n):
            if empty[i]:
                continue
            # 章标题/条目字段必须在页首几行，正文里提到“第一章”不算
            heads = [(ln.get('t') or '').strip() for ln in page_lines(pages[i])[:6]]
            if any(_body_head(h) for h in heads):
                body_start = i
                break
    if body_start is None:
        for i in range(search_from, n):
            if empty[i]:
                continue
            ls = page_lines(pages[i])
            if len(ls) >= 4 and sum(len(ln['t']) for ln in ls) / len(ls) >= 18:
                body_start = i
                break
    if body_start is None:
        body_start = search_from if search_from < n else n - 1

    # 卷首题名/题献：正文前 1-2 页若是短题名，归回正文
    if body_start - 1 >= 0 and not empty[body_start - 1] and is_short(pages[body_start - 1]):
        prev = texts[body_start - 1]
        if prev and not FRONT_WORDS.search(prev) and '目录' not in prev:
            body_start -= 1
    if body_start - 2 >= 0 and texts[body_start - 1].startswith('献给') and is_short(pages[body_start - 2]):
        body_start -= 2

    body_end = n - 1
    while body_end > body_start and empty[body_end]:
        body_end -= 1
    tail_cp = [i for i in copyright_pages if i > body_start + 5]
    if tail_cp:
        body_end = min(body_end, min(tail_cp) - 1)

    # 前言结束：目录在它后面就停在目录前，否则停在正文前
    pre_end = None
    if pre_start is not None:
        pre_end = body_start - 1
        if toc_start is not None and toc_start > pre_start:
            pre_end = min(pre_end, toc_start - 1)
        while pre_end is not None and pre_end > pre_start and empty[pre_end]:
            pre_end -= 1

    # 后置结构：正文后半段找关键词
    back_pages = {k: [] for k in BACK_WORDS}
    scan_from = body_start + int((body_end - body_start) * 0.5)
    for i in range(scan_from, body_end + 1):
        if empty[i]:
            continue
        heads = [ (ln.get('t') or '').strip() for ln in page_lines(pages[i])[:3] ]
        for k, pat in BACK_WORDS.items():
            if any(_heading_hit(h, pat) for h in heads):
                back_pages[k].append(i)
    if any(back_pages.values()):
        first_back = min(min(v) for v in back_pages.values() if v)
        body_end = min(body_end, first_back - 1)

    # 封面/书名页：文字层只能认“有字”的
    cover_page = None
    title_page = None
    limit = min(n, (toc_start if toc_start is not None else n))
    for i in range(0, limit):
        if empty[i]:
            continue
        ls = page_lines(pages[i])
        t = texts[i]
        # 只有书名、没有作者/出版社 → 当文字封面；有作者/出版社 → 书名页
        if book and _norm(book)[:6] in t and len(ls) <= 3 and '出版社' not in t \
                and not re.search(r'著|编|译', t):
            cover_page = i
            break
    for i in range(0, limit):
        if empty[i] or i == cover_page:
            continue
        ls = page_lines(pages[i])
        t = texts[i]
        if len(ls) <= 6 and ('出版社' in t or (book and _norm(book)[:6] in t)):
            title_page = i
            break

    # 标题层级：优先用 outline；没有 outline 用 Chapter 行
    headings = []
    if outline:
        for r in outline:
            nm = r.get('篇') or ''
            if not nm:
                continue
            page = _find_heading_page(pages, nm, body_start)
            headings.append({'level': 1, 'title': nm, 'page': page,
                             'seg': r.get('首锚点') or '',
                             'confidence': 0.9 if page else 0.4})
    else:
        for i in range(body_start, body_end + 1):
            m = CHAPTER_EN.search(texts[i]) or CHAPTER.search(texts[i])
            if m:
                headings.append({'level': 1, 'title': m.group(0).strip(),
                                 'page': pages[i]['page'], 'seg': '',
                                 'confidence': 0.8})

    # 组装
    def add(role, name, idxs, conf, note=''):
        r = _span(role, name, [pages[i]['page'] for i in idxs], conf, note)
        if r['status'] == 'found':
            r['evidence'] = [e for e in (_ev(pages[i]) for i in idxs[:2]) if e.get('quote')]
        rec['roles'].append(r)

    add('cover', '封面', [cover_page] if cover_page is not None else [], 0.6,
        '' if cover_page is not None else '无文字封面；图像封面需 PDF 页面图（第 3 期）')
    add('copyright', '版权页', copyright_pages, 0.95)
    add('title_page', '书名页', [title_page] if title_page is not None else [], 0.7)
    add('toc', '目录', list(range(toc_start, toc_end + 1)) if toc_start is not None else [], 0.9)
    add('preface', '前言', list(range(pre_start, pre_end + 1)) if pre_start is not None else [], 0.8)
    add('body', '正文内容', list(range(body_start, body_end + 1)), 0.85)
    hp = sorted({h['page'] for h in headings if h.get('page')})
    rh = _span('headings', '标题层级', hp, 0.8,
               '按篇章标题映射，未使用字号' if headings else '未找到章/节标题')
    rh['heading_total'] = len(headings)
    if headings and rh['status'] == 'found':
        rh['evidence'] = [{'page': h['page'], 'quote': h['title'][:60]}
                          for h in headings if h.get('page')][:2]
    rec['roles'].append(rh)
    for k in ('postscript', 'appendix', 'references', 'index', 'errata'):
        name = dict(ROLES)[k]
        add(k, name, back_pages[k], 0.75, '' if back_pages[k] else '全书未检出该结构')

    rec['headings'] = headings
    found = sum(1 for r in rec['roles'] if r['status'] == 'found')
    rec['stats'] = {'roles': len(rec['roles']), 'found': found,
                    'body_from': pages[body_start]['page'], 'body_to': pages[body_end]['page'],
                    'headings': len(headings)}
    return rec


def _find_heading_page(pages, name, body_start):
    target = _norm(name)
    if not target:
        return None
    # 全名
    for i in range(body_start, len(pages)):
        if target in page_norm(pages[i]):
            return pages[i]['page']
    # 去掉“第X章”前缀再找
    tail = re.sub(r'^第[一二三四五六七八九十百零〇0-9]{1,4}章', '', target)
    if tail and len(tail) >= 2:
        for i in range(body_start, len(pages)):
            if tail in page_norm(pages[i]):
                return pages[i]['page']
    return None


def load_layout(code):
    bk = {}
    p = os.path.join(P.OUT, code, 'book.json')
    if os.path.exists(p):
        bk = json.load(io.open(p, encoding='utf-8'))
    name = bk.get('book') or ''
    lp = os.path.join(P.RAW, name + '.layout.jsonl')
    if not os.path.exists(lp):
        return [], bk
    pages = [json.loads(l) for l in io.open(lp, encoding='utf-8') if l.strip()]
    return pages, bk


def load_outline(code):
    p = os.path.join(P.OUT, code, 'outline.jsonl')
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]


def build(code):
    pages, bk = load_layout(code)
    outline = load_outline(code)
    if not pages:
        rec = classify_pages([], bk.get('book') or '', outline)
        rec['code'] = code
        rec['source_format'] = 'docx/txt'
        return rec
    rec = classify_pages(pages, bk.get('book') or '', outline)
    rec['code'] = code
    rec['source_format'] = 'pdf'
    return rec


def write(rec):
    d = os.path.join(P.OUT, rec['code'])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'page_roles.json')
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(rec, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def main(argv):
    codes = []
    for a in argv[1:]:
        if a == '--all':
            codes = sorted([d for d in os.listdir(P.OUT)
                            if os.path.isdir(os.path.join(P.OUT, d)) and re.match(r'^[A-Z][A-Z0-9]{0,3}$', d)])
        elif a.startswith('-'):
            print('unknown option', a)
            return 2
        else:
            codes.append(a)
    if not codes:
        print(__doc__)
        return 2
    for c in codes:
        rec = build(c)
        p = write(rec)
        print('%s %-30s 结构 %d/%d 正文 %s-%s 标题 %d -> %s'
              % (c, rec['book'][:28], rec['stats'].get('found', 0), 12,
                 rec['stats'].get('body_from'), rec['stats'].get('body_to'),
                 rec['stats'].get('headings', 0), p))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
