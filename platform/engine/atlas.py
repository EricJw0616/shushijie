# -*- coding: utf-8 -*-
"""图鉴型（P11）的版面还原与条目抽取。

为什么单开一个模块：图鉴的正文不是「篇→段」，而是「页→条目→字段」。
普通流水线把 PDF 当一段文字读，遇到双页拼版（一本 PDF 里左右两页并排）
和多栏排版就会串行：左页的「采 制」会和右页的「性味功效」拼到同一行。
本模块先按版面把每行归到它所在的半页，再按阅读顺序拼回正文。

两件事：
  1. layout_pdf()       PDF → 每页每条线的坐标、类型（正文/图注/页眉/参考文献）
  2. entries_from_*()   正文 → 物种条目（以「来 源」为唯一边界，按字段标签切）

条目的身份（中名/学名/科名/药用部位）从「来 源」字段解析，不依赖标题编号——
这本书的条目标题是转曲图形，文本层读不到。
"""
import collections
import io
import json
import os
import re
import sys



# ============================================================
# 版面层：PDF → 页 / 列 / 行
# ============================================================

_CAP_RE = re.compile(r'^[▲▼△▽]')
_HAN1 = re.compile(r'^[\u4e00-\u9fff]$')
_BODY_START_RE = re.compile(
    r'^(?:来源|别名|俗名|原植物|形态特征|识别要点|生境|分布|产地|采制|采收加工|'
    r'性味功效|性味功能|功能主治|主治用法|用量|用法用量|附注|附方|化学成分|'
    r'药理作用|贮藏|炮制|配伍)')
_HEADING_RE = re.compile(r'[\u4e00-\u9fa5]{1,8}(?:科|属)[A-Z]')
# 图注与正文撞在同一行时（▼某某根来　　源　…），用来找正文的起点
_LABEL_ANY_RE = re.compile(
    r'来\s*源|别\s*名|俗\s*名|原\s*植\s*物|生\s*境|分\s*布|采\s*制|'
    r'性味功效|性味功能|主治用法|用\s*量|附\s*注|附\s*方')


def _detect_gutter(chars, w, h=None):
    """找双页拼版的中缝。单页返回 None。

    判据是「中段有一段连续 18pt 以上没有任何字」：拼版书的装订缝一定满足，
    单页书的正文通常跨过中心线。横向页面仍要检查较窄的双页拼版。
    """
    if w < 760 and (not h or w / h < 1.15):
        return None
    bins = [0] * (int(w) + 2)
    for c in chars:
        x = int((c['x0'] + c['x1']) / 2)
        if 0 <= x < len(bins):
            bins[x] += 1
    runs, st = [], None
    for x in range(int(w * 0.30), int(w * 0.70)):
        if bins[x] == 0:
            if st is None:
                st = x
        else:
            if st is not None:
                runs.append((st, x - 1))
                st = None
    if st is not None:
        runs.append((st, int(w * 0.70)))
    runs = [r for r in runs if r[1] - r[0] >= 18]
    if not runs:
        return None
    runs.sort(key=lambda r: abs((r[0] + r[1]) / 2.0 - w / 2.0))
    st, en = runs[0]
    return (st + en) / 2.0


def _glyph_line_position(char):
    """Use the text baseline when the PDF provides an upright glyph matrix."""
    matrix = char.get('matrix')
    if (matrix and char.get('upright', True) and 'y1' in char
            and abs(matrix[1]) < .001 and abs(matrix[2]) < .001):
        return char['top'] + char['y1'] - matrix[5]
    return char['top']


def _split_lines(chars):
    """同一列内按纵坐标归行，行内按横坐标拼字（原样保留空格字符）。"""
    chars = sorted(chars, key=lambda c: (_glyph_line_position(c), c['x0']))
    groups = []
    for c in chars:
        baseline = _glyph_line_position(c)
        if groups and abs(baseline - groups[-1]['baseline']) <= 2.5:
            groups[-1]['chars'].append(c)
        else:
            groups.append({'baseline': baseline, 'chars': [c]})
    out = []
    for g in groups:
        cs = sorted(g['chars'], key=lambda c: c['x0'])
        # 同一行里横向空隙过大 = 其实是两栏（竖排大字 / 资料框 / 正文并排）。
        # 不拆开的话，「姓名：李四光」会和左边竖排的「李/四/光」拼成一行。
        runs = [[cs[0]]]
        for a, b in zip(cs, cs[1:]):
            if b['x0'] - a['x1'] > 18:
                runs.append([b])
            else:
                runs[-1].append(b)
        for run in runs:
            t = ''.join(c['text'] for c in run).strip()
            if not t:
                continue
            out.append({'t': t, 'x0': run[0]['x0'], 'x1': max(c['x1'] for c in run),
                        'top': min(c['top'] for c in run)})
    return out


def _kind_of(t, top, h):
    if top < h * 0.05 or top > h * 0.92:
        return 'header'
    if _CAP_RE.match(t):
        return 'caption'
    return 'body'


def _pdf_bookmarks(pdf):
    """只读取文件自带、指向本 PDF 页面对象的目录书签。"""
    from pdfminer.pdfexceptions import PDFException
    from pdfminer.pdftypes import resolve1

    pages = {page.page_obj.pageid: page.page_number for page in pdf.pages}
    bookmarks = collections.defaultdict(list)
    try:
        for level, title, dest, action, _ in pdf.doc.get_outlines():
            try:
                target = resolve1(dest or action)
                if isinstance(target, dict):
                    target = resolve1(target.get('D'))
                if isinstance(target, (bytes, str)):
                    target = resolve1(pdf.doc.get_dest(target))
                    if isinstance(target, dict):
                        target = resolve1(target.get('D'))
                if not isinstance(target, (list, tuple)) or not target:
                    continue
                page_number = pages.get(getattr(target[0], 'objid', None))
                title = str(title or '').lstrip('\ufeff').strip()
                if page_number and title:
                    bookmarks[page_number].append({'title': title, 'level': level})
            except (PDFException, ValueError, TypeError, KeyError):
                continue
    except PDFException:
        pass
    return bookmarks


def _page_tables(page):
    """把有明确网格的表单独保留，避免单元格在正文里互相粘连。"""
    if len(page.lines) + len(page.rects) < 6:
        return []
    tables = []
    for table in page.find_tables():
        if len(table.cells) < 6 or len(table.rows) < 3:
            continue
        rows = table.extract()
        if sum(sum(bool((cell or '').strip()) for cell in row) >= 2 for row in rows) < 3:
            continue
        tables.append({'bounds': [round(value, 2) for value in table.bbox], 'rows': rows})
    return tables


def _in_table(char, tables):
    x = (char['x0'] + char['x1']) / 2
    y = (char['top'] + char['bottom']) / 2
    return any(left <= x < right and top <= y < bottom
               for left, top, right, bottom in (table['bounds'] for table in tables))


def _has_full_page_picture(page):
    if not page.width or not page.height:
        return False
    left, top, right, bottom = page.bbox
    area = page.width * page.height
    for picture in page.images:
        overlap_w = max(0, min(right, picture['x1']) - max(left, picture['x0']))
        overlap_h = max(0, min(bottom, picture['bottom']) - max(top, picture['top']))
        if overlap_w * overlap_h >= area * .82:
            return True
    return False


def _interleaved_vertical_rows(chars):
    """Detect adjacent single-glyph columns that horizontal extraction interleaves.

    Require repeated, tightly spaced rows with large gaps between glyphs. Ordinary
    horizontal prose (including prose about vertical writing) cannot satisfy this
    geometry. Keep the original lines; this is a review gate, not a reordering guess.
    """
    rows = []
    for char in sorted(chars, key=lambda c: (c['top'], c['x0'])):
        if not str(char.get('text') or '').strip():
            continue
        if rows and abs(char['top'] - rows[-1][0]['top']) <= 2.5:
            rows[-1].append(char)
        else:
            rows.append([char])
    previous, run = None, 0
    for row in rows:
        row.sort(key=lambda c: c['x0'])
        heights = [c.get('bottom', c['top']) - c['top'] for c in row]
        candidate = (2 <= len(row) <= 4 and min(heights) > 0
                     and any(_HAN1.fullmatch(c['text']) for c in row)
                     and all(len(c['text']) == 1 for c in row)
                     and all(b['x0'] - a['x1'] >= .65 * max(a['x1'] - a['x0'], b['x1'] - b['x0'])
                             for a, b in zip(row, row[1:])))
        same = (candidate and previous is not None and len(previous) == len(row)
                and all(abs(a['x0'] - b['x0']) <= 1.5 and
                        .9 * h <= b['top'] - a['top'] <= 1.65 * h
                        for a, b, h in zip(previous, row, heights)))
        run = run + 1 if same else (1 if candidate else 0)
        if run >= 4:
            return True
        previous = row if candidate else None
    return False


def _backmatter_booklist(page, total_pages):
    """A narrow, coordinate-backed series catalogue rule, not a topic classifier."""
    tail = min(8, max(2, (total_pages * 3 + 99) // 100))
    if total_pages < 40 or page['page'] <= total_pages - tail or page.get('bookmarks'):
        return False
    lines = [line for line in page['lines'] if line['k'] == 'body' and line['t'].strip()]
    if not lines or lines[0]['top'] > page['h'] * .30:
        return False
    heading = re.sub(r'\s+', '', lines[0]['t'])
    if not re.fullmatch(r'(?:名家(?:散文|随笔|小说|作品)|(?:本社|系列|推荐|畅销)(?:书目|图书)|.{1,12}(?:丛书|书系)(?:书目|目录)?)', heading):
        return False
    entries = []
    for line in lines[1:]:
        match = re.fullmatch(r'([\u4e00-\u9fff·]{2,8})[：:]([^：:\d。！？!?]{2,35})', line['t'].strip())
        if not match:
            return False
        entries.append((line, match.group(1)))
    if len(entries) < 12 or len({name for _, name in entries}) < 12:
        return False
    columns = []
    for line, _ in sorted(entries, key=lambda item: item[0]['x0']):
        if columns and abs(line['x0'] - columns[-1][0]['x0']) <= 4:
            columns[-1].append(line)
        else:
            columns.append([line])
    return (len(columns) == 2 and min(map(len, columns)) >= 6
            and columns[1][0]['x0'] - columns[0][0]['x0'] >= page['w'] * .25
            and sum(any(abs(a['top'] - b['top']) <= 2.5 for b in columns[1])
                    for a in columns[0]) >= 6)


def layout_pdf(path, on_progress=None, *, page_numbers=None):
    """返回 [{page, w, h, lines:[{t, x0, x1, top, k, col}]}]。

    只读，不落盘；落盘由调用方决定（app 里存 raw/<书名>.layout.jsonl）。
    """
    try:
        import pdfplumber
    except Exception as e:
        raise RuntimeError('服务器未安装 pdfplumber，暂时不能解析 PDF（%s）' % e)
    pages = []
    picture_pages = []
    selected = None if page_numbers is None else set(page_numbers)
    with pdfplumber.open(path) as pdf:
        bookmarks = _pdf_bookmarks(pdf)
        total_pages = len(pdf.pages)
        if on_progress:
            on_progress(0, total_pages)
        for i, page in enumerate(pdf.pages, 1):
            if selected is not None and i not in selected:
                continue
            w, h = page.width, page.height
            chars = page.chars
            tables = _page_tables(page)
            if tables:
                chars = [char for char in chars if not _in_table(char, tables)]
            gut = _detect_gutter(chars, w, h) if chars else None
            cols = {}
            for c in chars:
                col = 0 if (gut is None or (c['x0'] + c['x1']) / 2.0 < gut) else 1
                cols.setdefault(col, []).append(c)
            lines = []
            for col in sorted(cols):
                ref = None
                seq = []
                for ln in _split_lines(cols[col]):
                    # 图注标记和字段标签连在同一行：拆开，别让整条正文被当图注丢掉。
                    if _CAP_RE.match(ln['t']):
                        m = _LABEL_ANY_RE.search(ln['t'])
                        if m and m.start() > 2:
                            cap = dict(ln, t=ln['t'][:m.start()].strip(), k='caption', col=col)
                            body = dict(ln, t=ln['t'][m.start():].strip())
                            seq.extend([cap, body])
                            continue
                    seq.append(ln)
                for ln in seq:
                    flat = ln['t'].replace(' ', '').replace('\u3000', '')
                    # 参考文献区：从「◎参考文献◎」到下一条正文（字段标签或科/属标题）为止。
                    # 不能只按 x 带截：同一个右栏里，参考文献下面还接着下一条物种。
                    if ref is not None:
                        if _BODY_START_RE.match(flat) or _HEADING_RE.search(flat):
                            ref = None
                        else:
                            ln['k'] = 'refe'
                            continue
                    if '参考文献' in flat:
                        ln['k'] = 'refe'
                        ref = ln
                        continue
                    ln['k'] = _kind_of(ln['t'], ln['top'], h)
                    ln['col'] = col
                    lines.append(ln)
            lines.sort(key=lambda x: (x.get('col', 0), x['top']))
            # 竖排标题（封面大字、扉页题记）在文字层里是一个字一行；
            # 切段时会被并进隔壁资料框，变成「良生卒年：—」。整列 ≥3 个单字行就标出来，
            # 只留在版面文件里，不进正文。
            singles = [ln for ln in lines if ln['k'] == 'body'
                       and len(ln['t']) == 1 and _HAN1.match(ln['t'])]
            clusters = []
            for ln in singles:
                for c in clusters:
                    if abs(c[0]['x0'] - ln['x0']) <= 4:
                        c.append(ln)
                        break
                else:
                    clusters.append([ln])
            for c in clusters:
                tops = [x['top'] for x in c]
                # 同一 x 上 ≥3 个单字、纵向跨过两行以上 = 竖排字，不是正文
                if len(c) >= 3 and max(tops) - min(tops) >= 30:
                    for x in c:
                        x['k'] = 'vertical'
            result = {'page': i, 'w': round(w, 1), 'h': round(h, 1),
                      'lines': [{'t': l['t'], 'x0': round(l['x0'], 1),
                                 'x1': round(l['x1'], 1), 'top': round(l['top'], 1),
                                 'k': l['k'], 'col': l.get('col', 0)} for l in lines]}
            if tables:
                result['tables'] = tables
            if _has_full_page_picture(page):
                picture_pages.append(result)
                if len(page.chars) < 320:
                    result['picture_dominant'] = True
            if bookmarks.get(i):
                result['bookmarks'] = bookmarks[i]
            if _interleaved_vertical_rows(chars):
                result['layout_review'] = 'vertical_text_order'
            if _backmatter_booklist(result, total_pages):
                result['non_body'] = 'backmatter_booklist'
            pages.append(result)
            page.flush_cache()
            if on_progress and (i % 5 == 0 or i == total_pages):
                on_progress(i, total_pages)
    # When nearly all pages are picture-led, a page with more dialogue is still picture-led.
    sparse_picture_pages = sum(bool(page.get('picture_dominant')) for page in picture_pages)
    if selected is None and sparse_picture_pages >= len(pages) * .75:
        for page in picture_pages:
            page['picture_dominant'] = True
    return pages


def pages_to_text(pages, mark_pages=False):
    """正文行的阅读顺序文本。图注、页眉、参考文献不进正文（图注在 layout 里留着）。"""
    out = []
    for p in pages:
        if p.get('non_body'):
            continue
        column = None
        for ln in p['lines']:
            if ln['k'] == 'body' and ln['t']:
                # 插入只供程序识别的分隔符，页码仍是 PDF 物理页号。
                if mark_pages and ln.get('col', 0) != column:
                    column = ln.get('col', 0)
                    out.append('<<<PAGE %d>>>' % p['page'])
                out.append(ln['t'])
    return '\n'.join(out)


# ============================================================
# 字段层：正文 → 条目
# （这一段与 demo 的 s2_entries.py 同源，已在该书上验证过 574 条/95%+）
# ============================================================

FIELDS = ["来源", "原植物", "别名", "俗名", "形态特征", "识别要点", "生境", "分布",
          "产地", "采制", "采收加工", "性味功效", "性味功能", "功能主治", "主治用法",
          "用量", "用法用量", "附注", "附方", "化学成分", "药理作用", "贮藏", "炮制", "配伍"]

# 同义字段归并表
CANON = {
    "性味功能": "性味功效",
    "功能主治": "性味功效",
    "采收加工": "采制",
    "用法用量": "用量",
    "产地": "分布",
    "形态特征": "原植物",
}

def norm(s):
    """去掉所有空白，便于标签匹配"""
    return re.sub(r"[\s\u3000\xa0]+", "", s)

# 标签正则：字间允许任意空白
LABEL_PATTERNS = [(f, re.compile(r"[\s\u3000]*".join(list(f)))) for f in
                  sorted(FIELDS, key=len, reverse=True)]

def find_labels(text):
    """在文本中定位所有字段标签，返回 [(pos, field)]，按位置排序，去除重叠"""
    hits = []
    for f, pat in LABEL_PATTERNS:
        for m in pat.finditer(text):
            st = m.start()
            # 排除正文内嵌提及：标签前紧邻「经/用/如/按/参见」等介词，
            # 或标签后紧跟「后/法/时」等字（如「经炮制后」「炮制法」），
            # 这类不是字段边界而是行文
            pre = text[max(0, st - 3):st]
            post = text[m.end():m.end() + 2]
            if re.search(r"[经用如按对按]", pre[-1:] or " ") and f in ("炮制", "配伍", "贮藏"):
                continue
            if re.match(r"^(后|法|时|过的)", post) and f in ("炮制", "配伍", "贮藏"):
                continue
            hits.append((st, m.end(), f))
    hits.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept = []
    last_end = -1
    for st, en, f in hits:
        if st < last_end:
            continue
        kept.append((st, en, f))
        last_end = en
    return kept

def split_fields(body):
    """把一条正文切成 {字段: 文本}"""
    labels = find_labels(body)
    out = collections.OrderedDict()
    pre = body[:labels[0][0]].strip() if labels else body.strip()
    for i, (st, en, f) in enumerate(labels):
        nxt = labels[i + 1][0] if i + 1 < len(labels) else len(body)
        val = body[en:nxt]
        val = re.sub(r"^[\s\u3000\xa0:：]+", "", val)
        val = re.sub(r"[\s\u3000\xa0]+$", "", val)
        val = re.sub(r"[ \t]*\n[ \t]*", "", val)   # 软换行接回
        val = re.sub(r"[\s\u3000\xa0]{2,}", " ", val)
        # 剔除混入的图注片段（▲/▼ 开头的短句）
        val = re.sub(r"[▲▼△▽]\s*\d*\s*[^，。；、\s]{2,20}(?:[（(][^）)]*[）)])?", "", val)
        val = re.sub(r"[\s\u3000\xa0]{2,}", " ", val).strip()
        f = CANON.get(f, f)                          # 同义标签归并
        if f in out:                                # 同字段二次出现则合并
            out[f] = (out[f] + " " + val).strip()
        else:
            out[f] = val
    return out, pre

# ---- 物种身份解析（从「来源」字段） ----
CN_NAME = r"[\u4e00-\u9fa5·]{1,20}"
LATIN = r"[A-Z][a-zA-Z.\-]*(?:\s+[a-z][a-zA-Z.\-]*)*"
# 例: 鳞毛蕨科粗茎鳞毛蕨Dryopteris crassirhizoma Nakai 的根茎
SRC_RE = re.compile(
    r"^(?P<family>" + CN_NAME + r")科"
    r"(?P<cname>" + CN_NAME + r"?)\s*"
    r"(?P<latin>" + LATIN + r")"
)

# 常见属名词干表：用于在「中名直接接拉丁」无分隔时定位拉丁起点
GENUS_STEMS = [
    "Nostoc", "Ulva", "Enteromorpha", "Chorda", "Laminaria", "Undaria", "Pelvetia",
    "Sargassum", "Porphyra", "Gelidium", "Corallina", "Gracilaria", "Chondrus",
    "Ceramium", "Agaricus", "Amanita", "Boletus", "Russula", "Lactarius", "Coprinus",
    "Tremella", "Lycoperdon", "Grifola", "Fomes", "Phellinus", "Trametes", "Lenzites",
    "Piptoporus", "Coriolus", "Xanthochrous", "Schizophyllum", "Pleurotus", "Lentinus",
    "Clitocybe", "Tricholoma", "Armillaria", "Armillariella", "Flammulina", "Pholiota",
    "Hypholoma", "Mycena", "Marasmius", "Lyophyllum", "Panus", "Lentinellus",
    "Clitopilus", "Hypsizigus", "Xeromphalina", "Phaeolepiota", "Stropharia",
    "Pinus", "Larix", "Picea", "Abies", "Sabina", "Juniperus", "Taxus",
    "Betula", "Salix", "Populus", "Quercus", "Ulmus", "Fraxinus", "Acer", "Tilia",
    "Rumex", "Polygonum", "Chenopodium", "Moehringia", "Dianthus", "Stellaria",
    "Ranunculus", "Aconitum", "Pulsatilla", "Anemone", "Cimicifuga", "Thalictrum",
    "Asplenium", "Dryopteris", "Woodsia", "Athyrium", "Polystichum", "Equisetum",
    "Lycopodium", "Selaginella", "Botrychium", "Osmunda", "Adiantum",
    "Artemisia", "Saussurea", "Cirsium", "Taraxacum", "Aster", "Solidago",
    "Gentiana", "Swertia", "Halenia", "Valeriana", "Patrinia", "Dipsacus",
    "Plantago", "Prunella", "Leonurus", "Scutellaria", "Laminum", "Mentha",
    "Angelica", "Bupleurum", "Cnidium", "Ligusticum", "Peucedanum", "Saposhnikovia",
    "Codonopsis", "Platycodon", "Adenophora", "Campanula", "Lobelia",
    "Rosa", "Crataegus", "Rubus", "Sorbus", "Malus", "Prunus", "Spiraea",
    "Vicia", "Astragalus", "Glycyrrhiza", "Lespedeza", "Sophora", "Amorpha",
    "Viola", "Hypericum", "Epilobium", "Circaea", "Oenothera", "Ludwigia",
    "Vaccinium", "Ledum", "Rhododendron", "Pyrola", "Monotropa",
    "Allium", "Lilium", "Polygonatum", "Maianthemum", "Smilax", "Dioscorea",
    "Iris", "Cypripedium", "Platanthera", "Gastrodia", "Epipactis",
]

def split_cname_latin(s):
    """中名与拉丁学名连排时的切分。

    原书排版把「中名+学名」直接连写（如 落叶松Larixgmelinii、偃松Pinuspumilla），
    文本层无分隔。策略：在中名前缀之后寻找拉丁属名词干的出现位置。
    """
    for stem in sorted(GENUS_STEMS, key=len, reverse=True):
        idx = s.find(stem)
        if idx > 0:
            return s[:idx], s[idx:]
    # 兜底：首个大写字母处切（可能把中名里的拉丁字母误切，但极罕见）
    m = re.search(r"[A-Z]", s)
    if m and m.start() > 0:
        return s[:m.start()], s[m.start():]
    return s, ""

def fix_latin(lat):
    """修复学名内部粘连。

    原书三类粘连：
      1) 属名+种加词连排（Armillariamellea）
      2) 种加词+命名人连排（lactucaL.）
      3) 命名人之间 et 连排（Tsenget）
    """
    # 先砍掉误入的正文词
    s = re.sub(r"(的?(子实体|菌盖|菌柄|菌褶|藻体|全草|根茎|块根|叶片|花粉|植株)[。、].*)$", "", lat)
    s = re.sub(r"(子实体|菌盖)$", "", s)
    s = s.strip().rstrip("，。,;；")
    if not s:
        return ""

    AUTHORS = ("L|Fr|DC|Br|Ag|Lam|Miq|Sieb|Bunge|Maxim|Turcz|Pall|Pers|Nakai|Kitag|Kom|"
               "Ledeb|Rupr|Hance|Roxb|Thunb|Hook|Lindl|Mey|Fisch|Regel|Schult|Schaeff|Vahl|"
               "Karst|Sing|Berk|Aresch|Kjellm|Schrmm|Quel|Donk|Peck|Cooke|Pat|Gill|Kick|"
               "Pilat|Bers|Suk|Hara|Ohwi|Cheng|Koidz|Honda|Link|Boid|Boud|Vaucher|Curtis|"
               "Flah|Chang|Ito|Imai|Gray|Gonn|Rabe|Hohnel|Kuhn|Wu|Hsing|Tseng|Yendo|Endl|"
               "Trin|Steud|Walp|Kunth|Roem|Schrad|Spreng|Willd|Wettst|Reichb|Ant|Satake|"
               "Matsum|Hayata|Kaneh|Sasaki|Yamamoto|Liu|Chao|Chien|Fang|Hu|Wang|Hsu|Shen|"
               "Ness|Okam|Tanaka|Sawada|Nagai|Abe|Bieb|Hoffm|Sond|Baill|Planch|Oliv|Hemsl|"
               "Diels|Wilson|Rehd|Bean|Bailey|Britten|Ridl|Rolfe|Holm|Hongo|Moser|Bigelow|"
               "Fayod|Overh|Bres|Schw|Secr|Scop|Bull|Fuhr|Gill|Sacc|Cke|Mass|Berk")

    # ---- 第1步：分离「属名 + 余下」----
    toks = s.split(" ")
    first = toks[0]
    looks_joined = len(toks) == 1 or len(first) > 20
    if looks_joined:
        target = s.replace(" ", "")
        cut = None
        # 1a 属名词表命中（优先最长）
        for stem in sorted(GENUS_STEMS, key=len, reverse=True):
            if target.startswith(stem) and len(target) > len(stem) and target[len(stem)].islower():
                cut = len(stem); break
        # 1b 表里没有：取「大写开头的最长前缀」作为属名，余下须以小写开头且在命名人之前
        if cut is None:
            m = re.match(r"([A-Z][a-z]{4,})([a-z].*)$", target)
            if m:
                cut = len(m.group(1))
        if cut:
            head, rest = target[:cut], target[cut:]
            # 种加词 = 余下部分直到第一个命名人标记（大写+句点 或 括号）
            ma = re.match(r"^([a-z]+)(.*)$", rest)
            if ma:
                s = head + " " + ma.group(1) + (" " + ma.group(2) if ma.group(2) else "")
    # ---- 第2步：种加词与命名人分离 ----
    s = re.sub(r"([a-z])((?:%s))\.?" % AUTHORS, lambda m: m.group(1) + " " + m.group(2) + ".", s)
    # ---- 第3步：命名人内 et / ex 连排 ----
    s = re.sub(r"([A-Za-z\.])\.?(et|ex)([A-Z])", r"\1 \2 \3", s)
    return re.sub(r"\s+", " ", s).strip()

def parse_source(src):
    """解析来源字段 → 科名 / 中名 / 学名 / 药用部位 / 药材名"""
    r = {"family": "", "cname": "", "latin": "", "part": "", "drug_name": ""}
    if not src:
        return r
    s = re.sub(r"[\s\u3000\xa0]+", " ", src).strip()
    # 药用部位：的xxx。
    m = re.search(r"的([^。；]{2,40})[。；]", s)
    if m:
        r["part"] = m.group(1).strip()
    # 入药称"xxx"
    m2 = re.search(r"入药称[\u201c\"]([^\u201d\"]+)[\u201d\"]", s)
    if m2:
        r["drug_name"] = m2.group(1).strip()
    m3 = re.search(r"^(.+?)科", s)
    if m3:
        r["family"] = m3.group(1).strip() + "科"
        rest = s[len(m3.group(1)) + 1:]
    else:
        rest = s
    # 关键：先截到第一个「的」之前，得到「中名+学名」候选区，
    # 否则后面的药用部位中文会被误当作学名的一部分
    head = rest.split("的")[0]
    head_ns = re.sub(r"[\s\u3000]", "", head)
    cn_part, lat_part = split_cname_latin(head_ns)
    if lat_part:
        r["cname"] = cn_part
        r["latin"] = fix_latin(lat_part)
    else:
        m5 = re.match(r"^(" + CN_NAME + r")", head_ns)
        if m5:
            r["cname"] = m5.group(1)
    return r
    s = re.sub(r"[\s\u3000\xa0]+", " ", src).strip()
    # 药用部位：的xxx。
    m = re.search(r"的([^。；]{2,40})[。；]", s)
    if m:
        r["part"] = m.group(1).strip()
    # 入药称"xxx"
    m2 = re.search(r"入药称[“\"]([^”\"]+)[”\"]", s)
    if m2:
        r["drug_name"] = m2.group(1).strip()
    m3 = re.search(r"^(.+?)科", s)
    if m3:
        r["family"] = m3.group(1).strip() + "科"
        rest = s[len(m3.group(1)) + 1:]
    else:
        rest = s
    # 中名 + 拉丁：先按属名词干切出拉丁起点，避免中名被学名首字母污染
    rest_ns = re.sub(r"\s+", "", rest)
    cn_part, lat_part = split_cname_latin(rest_ns)
    if lat_part:
        r["cname"] = cn_part
        r["latin"] = fix_latin(lat_part, cn_part)
    else:
        m4 = re.match(r"^(" + CN_NAME + r")(" + LATIN + r")", rest)
        if m4:
            r["cname"] = m4.group(1)
            r["latin"] = fix_latin(m4.group(2), m4.group(1))
        else:
            m5 = re.match(r"^(" + CN_NAME + r")", rest)
            if m5:
                r["cname"] = m5.group(1)
    return r

def merge_reference_fields(fields):
    """处理【xx】引用式表述。

    原书对个别条目用「其【采制】、【性味功效】、【主治用法】及【用量】同网纹马勃。」
    这种交叉引用写法，字段切分后被拆散成「】、【」之类的残片。
    检测到该模式时，把整句归入「附注」，并清空被污染的字段。
    """
    raw = "".join(v for v in fields.values() if v)
    if "【" not in raw and "】" not in raw:
        return fields
    # 整句引用归入附注：从「其」或第一个【 起，到句末
    ref = ""
    m = re.search(r"其?【[^。]*?同[^。]*。?", raw)
    if m:
        ref = m.group(0)
    else:
        m = re.search(r"【[^。]*?同[^。]*。?", raw)
        if m:
            ref = m.group(0)
    # 引用句替换成可读表述
    if ref:
        names = re.findall(r"同([\u4e00-\u9fa5]+)", ref)
        tgt = names[0] if names else ""
        ref = f"本种各项（采制、性味功效、主治用法、用量）{('同' + tgt) if tgt else '参见同类'}。"
    out = collections.OrderedDict()
    for k, v in fields.items():
        v2 = re.sub(r"其?【[^。]*?同[^。]*。?", "", v)
        v2 = re.sub(r"【[^】]*】", "", v2)
        v2 = re.sub(r"[、，及\s]{2,}", "", v2)
        v2 = v2.strip(" 、，；【】")
        if v2:
            out[k] = v2
    if ref:
        out["附注"] = (out.get("附注", "") + " " + ref.strip()).strip()
    # 收尾：清掉空括号组成的残片（如「其【】、【】、【】及【】同杯伞。」）
    for k in list(out.keys()):
        v = out[k]
        v = re.sub(r"【\s*】", "", v)
        v = re.sub(r"[、，及\s]*其?$", "", v)
        v = re.sub(r"^[、，及\s]*(同[^。]*。?)?$", "", v)
        v = v.strip(" 、，；")
        if v:
            out[k] = v
        else:
            del out[k]
    return out


def _search_limit():
    return 0


# 条目尾部的非正文：下一章的标题/章节小引、下一个科属标题、下一个物种名。
# 这些排在「下一条来源」之前，按「来源」切条时会粘在上一条末尾。
_TAIL_LINE = re.compile(
    r'^(?:第[一二三四五六七八九十百]+[章节]|本章共收录|'
    r'[\u4e00-\u9fa5]{1,8}(?:科|属)\s*[A-Z]|'
    r'[\u4e00-\u9fa5·]{2,12})$')


def _trim_tail(body, title=''):
    lines = body.rstrip().split('\n')
    while len(lines) > 1:
        last = lines[-1].strip()
        if last and not _TAIL_LINE.match(last):
            break
        lines.pop()
    body = '\n'.join(lines)
    if title:
        body = re.sub(r'\s*' + re.escape(title) + r'\s*$', '', body)
    return body


def _cut_entries(full, page_at, title=''):
    """以「来 源」为唯一边界切条目，再按字段标签切字段。"""
    src_pat = re.compile(r'[\s\u3000]*'.join(list('来源')))
    cuts = [m.start() for m in src_pat.finditer(full)]
    entries = []
    for i, st in enumerate(cuts):
        en = cuts[i + 1] if i + 1 < len(cuts) else len(full)
        body = full[st:en]
        body = re.sub(r'［\s*\d{1,3}\s*］.*$', '', body, flags=re.S)
        body = re.sub(r'◎\s*参考文献\s*◎.*$', '', body, flags=re.S)
        body = _trim_tail(body, title)
        # 下一章的小引（「第九章菌类植物…侧耳科…」）常和上一条粘在一起，
        # 且前面还顶着书眉，按行切不掉；只在尾部出现时整段截断。
        _labels = find_labels(body)
        _tail_from = _labels[-1][1] if _labels else 0
        if _tail_from < len(body) * 0.6:
            _tail_from = int(len(body) * 0.6)
        _m = re.search(r'第[一二三四五六七八九十百]+章[\u4e00-\u9fa5、，\s]{0,20}?[科属]\s*[A-Z]',
                       body[_tail_from:])
        if _m:
            body = body[:_tail_from + _m.start()]
        # 尾部参考文献残行（「…出版社.1986:677-679」）
        body = re.sub(r'\n?[^\n]{0,40}\d{4}\s*[:：]\s*\d+[^\n]*$', '', body)
        body = body.rstrip()
        fields, pre = split_fields(body)
        fields = merge_reference_fields(fields)
        nf = len([k for k, v in fields.items() if v.strip()])
        if nf < 3:
            continue
        src = fields.get('来源', '')
        ident = parse_source(src)
        if not ident['cname'] and pre.strip():
            m = re.search(r'([\u4e00-\u9fa5·]{2,20})\s*$', norm(pre))
            if m:
                ident['cname'] = m.group(1)
        entries.append({
            'id': len(entries) + 1,
            'page': page_at(st),
            'family': ident['family'],
            'cname': ident['cname'],
            'latin': ident['latin'],
            'part': ident['part'],
            'drug_name': ident['drug_name'],
            'field_count': nf,
            'fields': dict(fields),
            'text': body.strip(),
        })
    return entries


def entries_from_pages(pages, title=''):
    parts, offs, pos = [], [], 0
    for p in pages:
        if p.get('non_body') or p.get('layout_review'):
            continue
        for ln in p['lines']:
            if ln['k'] != 'body' or not ln['t']:
                continue
            t = ln['t']
            offs.append((pos, pos + len(t), p['page']))
            parts.append(t)
            parts.append('\n')
            pos += len(t) + 1
    full = ''.join(parts)

    def page_at(idx):
        for a, b, pg in offs:
            if a <= idx < b:
                return pg
        return offs[-1][2] if offs else 0

    return _cut_entries(full, page_at, title)


def entries_from_text(text, title=''):
    """没有版面时的兜底：直接按行文本切。多栏书会串行，结果要人工核。"""
    full = text or ''
    return _cut_entries(full, lambda idx: 0, title)


def load_pages(path):
    out = []
    with io.open(path, encoding='utf-8') as fp:
        for line in fp:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_pages(pages, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        for p in pages:
            fp.write(json.dumps(p, ensure_ascii=False) + '\n')
    os.replace(tmp, path)
