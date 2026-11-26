# -*- coding: utf-8 -*-
"""清洗器：PDF 抽取文本 → 可切段的干净文本 → 带锚点的片段。

处理顺序（每一步都可复核）：
  1. 去页标记、去书眉页码、去分隔线
  2. 拼硬折行（PDF 抽取通病：80% 行尾断在句中）
  3. 按篇界切篇（前置的封面/序/目录单独存为「前置」，不丢）
  4. 按句子聚合成段（120-300 字，不截断句子）
  5. 打锚点 CODE-Pnn-Pmm

硬规则：不做任何改写。只做「拼接 + 去掉非正文行」。
出口条件：正文保留率 ≥ 95%，前置内容单列可查。
"""
import re, io, json, os, sys
from itertools import groupby
import paths as P
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import structure as ST

HAN = re.compile('[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0002FA1F]')
SENT_END = '。！？；…'
CLOSERS = '」』”’）】》'
UNRELIABLE_PDF_TEXT = re.compile(r'[×÷]\s*10\s*[-－﹣−]\s*\d|\(cid:\d+\)|\ufffd{3,}')

JUNK = [
    re.compile(r'^<<<PAGE \d+>>>$'),
    re.compile(r'^\d{1,4}$'),                       # 纯页码
    re.compile(r'^[│|·—\-\s]{2,}$'),               # 分隔线
    re.compile(r'^果麦文化\s*出品$'),
]


def load_ex(path, punctuate_bare=True):
    """返回 (可测文本, 是否算法断句)。判型入口应该用这个，不要用 load。

    为什么必须把标记显式传出来：试过用测量值反推「标点是不是算出来的」，
    57 本真人标点与 7 本算法断句在 punct/savg/smed 三轴上完全重叠，
    无法区分（详见 measure.py 中 algo_punct 的注释）。
    这是来源属性，只能由数据流携带。
    """
    with io.open(path, encoding='utf-8', errors='replace') as source:
        t = source.read()
    if re.search(r'Project Gutenberg|START OF THE PROJECT|\*\*\*\s*START OF', t, re.I):
        import gclean
        t = gclean.clean(t)
    algo = False
    if punctuate_bare:
        import segmenter
        ok, _rate = segmenter.has_punct(t)
        if not ok:
            t = segmenter.punctuate(t)
            algo = True
    return t, algo


def load(path, punctuate_bare=True):
    """读文本。做两级清洗：

    一、古腾堡页眉页脚 + 78 字节硬折行（gclean）
    为什么必须在这里接：gclean 写了却没被调用过，导致 raw2 的 34 本公开样本
    全部带着几千字的英文版权页进测量。后果不是「精确度略降」，而是灾难性的：
    论语汉字率被稀释到 41%、尔雅 34%、唐诗三百首 52%，
    全部被 gate 判成「非中文文本」直接拒判 —— 书本身没有任何问题。

    关键约束：只在**检测到古腾堡标记**时才清洗。
    旧 22 本无标记，走原路径，判型与 md5 完全不受影响（已验证）。
    无条件 unwrap 会改动所有旧书的行结构，让「零变动」这个出口条件失效。

    二、白文古籍补断句（segmenter）
    Kanripo 等底本是白文无标点。不补则全书 0 个句号，savg = 汉字数，
    必然被判「句读缺失」而整类古代典籍无法测。
    但补断句会改变句长分布，判型侧必须知道标点是算出来的，
    因此判型请用 load_ex() 拿标记。
    """
    return load_ex(path, punctuate_bare)[0]


def load_raw(path):
    """只做古腾堡清洗，**不补断句**。产物与引文必须用这个。
    理由：引文必须逐字可回查。补出来的句号不是原文的一部分，
    写进卡片等于伪造底本（这是硬红线，不许为了指标好看而犯）。"""
    return load(path, punctuate_bare=False)


def clean_lines(text):
    """去页标记与垃圾行。返回 (行列表, 被丢弃行数)。
    与 structure.lines_of 共用同一口径，保证下标可对齐。"""
    out = [s for _pno, s in ST.lines_of(text)]
    n_all = len([l for l in re.sub(r'<<<PAGE \d+>>>', '\n', text).split('\n') if l.strip()])
    return out, n_all - len(out)


def is_sent_end(s):
    """行尾是否可断段：句末标点，允许后接右引号/括号。"""
    s = s.rstrip()
    while s and s[-1] in CLOSERS:
        s = s[:-1]
    return bool(s) and s[-1] in SENT_END


def join_to_paras(lines):
    """拼硬折行 → 段。段界 = 行尾是句末标点。

    纯数字行（001/002…）是排印本的单元编号，不是正文，
    必须丢弃 —— 否则每个片段开头都会带上一个「001」，污染原文与引文。
    """
    paras, buf = [], ''
    for s in lines:
        if re.fullmatch(r'\d{1,4}', s.strip()):
            continue
        buf += s
        if is_sent_end(s):
            paras.append(buf)
            buf = ''
    if buf.strip():
        paras.append(buf)
    return paras


def split_sents(t):
    out, cur = [], ''
    for ch in t:
        cur += ch
        if ch in SENT_END:
            out.append(cur)
            cur = ''
    if cur.strip():
        out.append(cur)
    return [x for x in out if x.strip()]


def segment(paras, lo=120, hi=320):
    """把段聚合成 120-320 字的片段，不截断句子。"""
    segs, buf = [], ''
    for p in paras:
        if not buf:
            buf = p
        elif len(HAN.findall(buf)) + len(HAN.findall(p)) <= hi:
            buf += p
        else:
            segs.append(buf)
            buf = p
    if buf:
        segs.append(buf)
    merged = []
    for s in segs:
        if merged and len(HAN.findall(s)) < lo // 2:
            merged[-1] += s
        else:
            merged.append(s)
    return merged


def _source_pages(layout_path):
    if not layout_path or not os.path.isfile(layout_path):
        return {}
    try:
        with open(layout_path, encoding='utf-8') as infile:
            pages = (json.loads(line) for line in infile if line.strip())
            return {page['page']: page for page in pages}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def build(text, book_code, outline, layout_path=None, *, continuous_body=False):
    """text: 原文；outline: [(篇名, 起始行下标)]，下标基于 clean_lines 口径。
    返回 (segments, stats)。"""
    lines = ST.source_lines(text)
    has_pages = bool(ST.PAGE.search(text))
    source_pages = _source_pages(layout_path) if has_pages else {}
    raw_lines = len([line for line in ST.PAGE.sub('\n', text).split('\n') if line.strip()])
    drop = raw_lines - len(lines)

    # 篇界：outline 的下标与 clean_lines 完全同源（都走 structure.lines_of），
    # 直接使用，不做二次匹配——二次匹配只会引入错位。
    marks, last = [], -1
    for nm, li in outline:
        if li is None or li <= last or li >= len(lines):
            continue
        marks.append((li, nm))
        last = li

    segs = []

    def add_segments(chapter, number, source):
        index = 0
        for _, rows in groupby(source, key=lambda row: row[2]):
            block = list(rows)
            page = source_pages.get(block[0][0], {})
            if page.get('non_body'):
                continue
            paras = join_to_paras([line for _, line, _ in block])
            for txt in segment(paras):
                index += 1
                result = {'id': f'{book_code}-{number:02d}-P{index:02d}', '篇': chapter,
                          '篇序': number, '段': index, '字数': len(HAN.findall(txt)), '文本': txt}
                if continuous_body and not marks:
                    result['source_kind'] = 'body'
                if has_pages:
                    result['source_page'] = block[0][0]
                    if number == 0 and marks:
                        result['source_kind'] = 'front_matter'
                    ocr = page.get('ocr')
                    ocr_status = None
                    if isinstance(ocr, dict):
                        ocr_status = str(ocr.get('status') or 'review')
                        result['source_ocr_status'] = ocr_status
                        if ocr_status in ('body', 'review'):
                            result['source_method'] = 'ocr'
                    # OCR may recover prose from an image-dominant page. Only
                    # accepted body text clears that particular layout gate;
                    # partial/failed OCR and formula/encoding checks stay closed.
                    if page.get('layout_review'):
                        result['source_layout_suspect'] = True
                        result['source_layout_issue'] = str(page['layout_review'])
                    elif ocr_status is not None and ocr_status != 'body':
                        result['source_layout_suspect'] = True
                        result['source_layout_issue'] = 'ocr_' + str(ocr_status)
                    elif page.get('picture_dominant') and ocr_status != 'body':
                        result['source_layout_suspect'] = True
                        result['source_layout_issue'] = 'picture_dominant'
                    elif UNRELIABLE_PDF_TEXT.search(txt):
                        result['source_layout_suspect'] = True
                        result['source_layout_issue'] = 'formula_or_encoding'
                segs.append(result)

    # 前置内容（封面、序、目录）：第一个篇界之前
    head_end = marks[0][0] if marks else len(lines)
    if head_end > 0:
        add_segments('正文' if continuous_body and not marks else '前置', 0, lines[:head_end])

    for k, (start, nm) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        add_segments(nm, k + 1, lines[start + 1:end])

    total = sum(s['字数'] for s in segs)
    src = len(HAN.findall(text))
    body = sum(s['字数'] for s in segs if s['篇'] != '前置')
    npian = len({s['篇序'] for s in segs if s['篇序'] > 0})
    return segs, {'src_han': src, 'seg_han': total, 'body_han': body,
                  'retention': round(total * 100.0 / max(1, src), 1),
                  'nseg': len(segs), 'npian': npian, 'drop_lines': drop}


if __name__ == '__main__':
    import glob, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import structure as ST
    RAW = P.RAW
    rows = []
    for f in sorted(glob.glob(RAW + '/*.txt')):
        b = os.path.basename(f)[:-4]
        if b.startswith('_'):
            continue
        t = load(f)
        p = ST.probe(t, b)
        o = ST.outline(t, p)
        # outline 下标 → clean_lines 下标：两边都去空行、都去纯页码行，仅 JUNK 略不同
        segs, st = build(t, 'BK', [(nm, i) for nm, i, _pg in o])
        rows.append((b, st))
    print(f"{'书':<24}{'原文':>8}{'切段后':>8}{'保留':>7}{'篇':>4}{'段':>5}{'均字':>5}  状态")
    print('-' * 80)
    bad = 0
    for b, st in rows:
        ok = st['retention'] >= 95
        if not ok:
            bad += 1
        print(f"{b[:22]:<24}{st['src_han']:>8d}{st['seg_han']:>8d}"
              f"{st['retention']:>6.1f}%{st['npian']:>4d}{st['nseg']:>5d}"
              f"{st['seg_han']//max(1,st['nseg']):>5d}  {'OK' if ok else '!! 偏低'}")
    print(f"\n合计 {len(rows)} 本，保留率 <95% 的 {bad} 本")
