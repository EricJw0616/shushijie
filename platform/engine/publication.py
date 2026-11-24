# -*- coding: utf-8 -*-
"""第 1 期：出版信息抽取（19 项）。

设计原则（和标签规范一致）：
  1. 只抽原文明确写出的，不猜、不补、不跨段拼。
  2. 每个值都带证据（段号 + 原文片段）；没有证据就不落值。
  3. 书上没有的，记 not_found，不显示、不导出；不拿 PDF 物理页数冒充版权页页数。
  4. 优先版权页；没有版权页再用书名页/封面/封底；最后才用出版社元数据导入。
  5. 大模型不在这条线里：出版信息是“抄”，不是“写”。

用法：
    python3 publication.py B58 B60
    python3 publication.py --all --library ../../app/data/library.json
    python3 publication.py B58 --print
"""
import io
import json
import os
import re
import sys

import paths as P

# 19 项：key -> (编号, 名称, 标签ID)
TAGS = {
    'book_title':        ('001', '书名', 'BT-71ccb069-a77e-45de-a4b4-3c2322eaf1a9'),
    'author':            ('002', '作者', 'BT-62ce941f-6d46-4a26-8696-618c71f14437'),
    'publisher':         ('003', '出版社', 'BT-11fb3350-eba7-4253-a7d5-5efbd14c2629'),
    'impression':        ('004', '印次', 'BT-3525ecdd-d79d-44a7-99eb-25bb5cb37a10'),
    'editor_in_charge':  ('005', '责任编辑', 'BT-a2f36062-578b-40e6-901a-0870a5328049'),
    'subtitle':          ('006', '副书名', 'BT-7756af62-fecd-4450-9237-fe48eda29805'),
    'cip_number':        ('007', 'CIP核字号', 'BT-06ef352d-72f6-46cf-94c5-965d62869bc0'),
    'translators':       ('008', '翻译相关人员', 'BT-e46bd50e-4e3c-4bf9-a2a3-ac4f8dd6b0d2'),
    'publication_date':  ('009', '出版时间', 'BT-12d035f3-47da-4b25-a385-f5eb662d059d'),
    'edition':           ('010', '版次', 'BT-1fceec86-f27c-4254-a328-824981c408de'),
    'binding':           ('011', '装帧形式', 'BT-ac0546a6-85cc-4f60-a846-1ee1a7cc75c3'),
    'book_format':       ('012', '开本', 'BT-2e11e387-92ea-4b77-bd20-4f27d5325b23'),
    'pages':             ('013', '页数', 'BT-a949d63a-c652-49c7-884a-398c2199f5ca'),
    'word_count':        ('014', '字数', 'BT-0b7898fd-c10c-4909-90e5-322b277988e4'),
    'price':             ('015', '定价', 'BT-c6ef9e8b-4f2e-48f3-8f37-00281e0cc05f'),
    'series':            ('016', '丛书名', 'BT-cbaf86d6-3715-4919-affc-6c7bdc429898'),
    'author_bio':        ('017', '作者简介', 'BT-af5034cd-64a4-44bf-aae6-acf37f277781'),
    'classification':    ('027', '分类信息', 'BT-PUBMETA-f9e3ea05-90ed-4831-9866-73b4ff95a3b6'),
    'isbn':              ('081', '书号', 'BT-SEED-ea709b09-b1fa-437f-b586-8c7e89ef9efe'),
}

PACK = {'id': 'publishing_dataset_foundation', 'version': '1.7.0', 'revision': 1}

# 版权页里常见的下一个字段名，用来截断取值
NEXT_LABEL = re.compile(
    r'责任校对|美术编辑|封面设计|装帧设计|插图|插页|出版发行|印\s*刷|开\s*本|印\s*张|'
    r'印\s*数|字\s*数|版\s*次|印\s*次|书\s*号|定\s*价|版权所有|出版人|地\s*址|'
    r'邮政编码|邮购电话|网\s*址|电子信箱|产品经理|责任编辑|媒介推广|出品人|'
    r'主\s*编|副\s*主\s*编|编\s*委|序\s*言|前\s*言|目\s*录'
)

BINDING_WORDS = re.compile(r'精装|平装|线装|胶装|骑马订|锁线精装|裸脊|活页')


def _rows(code):
    p = os.path.join(P.OUT, code, 'segments.jsonl')
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]


def _book(code):
    p = os.path.join(P.OUT, code, 'book.json')
    if not os.path.exists(p):
        return {}
    return json.load(io.open(p, encoding='utf-8'))


def _library(path):
    if not path or not os.path.exists(path):
        return {}
    d = json.load(io.open(path, encoding='utf-8'))
    return d.get('books') or {}


def _ocr_fields(code):
    p = os.path.join(P.OUT, code, 'ocr', 'fields.json')
    if not os.path.exists(p):
        return {}
    try:
        return json.load(io.open(p, encoding='utf-8')).get('fields') or {}
    except Exception:
        return {}


def _ocr_pub(code):
    p = os.path.join(P.OUT, code, 'ocr', 'publication.json')
    if not os.path.exists(p):
        return {}
    try:
        return json.load(io.open(p, encoding='utf-8'))
    except Exception:
        return {}


def _apply_ocr(items, code):
    """OCR 版权页补洞：只补 not_found，不覆盖已有规则/导入值。"""
    pub = _ocr_pub(code)
    fields = pub.get('fields') or {}
    if not fields:
        return
    for key, meta in fields.items():
        if key not in items or items[key].get('status') != 'not_found':
            continue
        v = meta.get('value')
        if v in (None, ''):
            continue
        ev = [{'page': meta.get('page'), 'quote': meta.get('quote') or str(v),
               'source': 'ocr'}]
        note = 'OCR 版权页识别（第 %s 页）' % meta.get('page')
        if key == 'author':
            val = {'raw': str(v), 'people': []}
            note += '；角色未拆'
        elif key == 'isbn':
            val = [{'type': 'ISBN-13' if len(re.sub(r'\D', '', str(v))) == 13 else '其他书号',
                    'value': str(v), 'valid': isbn13_ok(str(v))}]
        elif key == 'cip_number':
            val = {'number': str(v), 'raw': str(v)}
        elif key == 'book_format':
            val = split_format(str(v))
        elif key == 'word_count':
            val = {'raw': str(v), 'normalized': int(re.sub(r'\D', '', str(v)) or 0), 'unit': ''}
        elif key == 'price':
            val = {'raw': str(v), 'amount': float(re.sub(r'[^\d.]', '', str(v)) or 0),
                   'currency': 'CNY'}
        elif key == 'classification':
            codec = str(v)
            name = ''
            try:
                import clc
                name = clc.NAME.get(re.match(r'([A-Z]+)', codec).group(1), '')
            except Exception:
                pass
            val = [{'system': '中图法', 'version': '', 'code': codec, 'name': name,
                    'source': '版权页OCR', 'note': ''}]
        else:
            val = str(v)
        items[key] = _item(key, val, 'found', 'ocr', 0.8, ev, note)


def _cut(s):
    """截到下一个字段名之前。"""
    s = (s or '').strip(' ：:')
    m = NEXT_LABEL.search(s)
    if m:
        s = s[:m.start()]
    return s.strip(' ：:，,；;。')


def _ev(seg, quote):
    return {'seg': seg.get('id', ''), 'quote': (quote or '').strip()[:300]}


_RUNNING_HEAD = re.compile(r'\d{1,4}\s*[▏|]')


def _find_import_evidence(rows, value):
    """书目库导入值 → 原文段 + 逐字引文。

    只认「能在这段文字里连续找到」的值；找不到返回空，不拿书眉/页码头冒充。
    带卷次括号的书名（如「（上册）」）先试全串，再试主书名。
    """
    if isinstance(value, dict):
        value = value.get('raw') or ''
    s = str(value or '').strip()
    if not s:
        return []
    cands = [s]
    m = re.match(r'^(.*?)[（(][^）)]*[）)]\s*$', s)
    if m and m.group(1).strip():
        cands.append(m.group(1).strip())
    for cand in cands:
        if len(cand) < 2:
            continue
        for r in rows:
            t = r.get('文本') or ''
            i = t.find(cand)
            if i < 0:
                continue
            ctx = t[max(0, i - 12):i + len(cand) + 12]
            if _RUNNING_HEAD.search(ctx):
                continue
            return [{'seg': r.get('id', ''), 'quote': cand}]
    return []


def _item(key, value=None, status='not_found', method='', confidence=None,
          evidence=None, note=''):
    no, name, tid = TAGS[key]
    return {
        'no': no, 'name': name, 'tag_id': tid, 'field': key,
        'value': value, 'status': status, 'method': method,
        'confidence': confidence, 'evidence': evidence or [], 'note': note,
    }


# ---------- 书号 ----------

def isbn13_ok(s):
    d = re.sub(r'\D', '', s or '')
    if len(d) != 13:
        return False
    total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(d[:12]))
    return (10 - total % 10) % 10 == int(d[12])


def isbn10_ok(s):
    d = re.sub(r'[^0-9Xx]', '', s or '').upper()
    if len(d) != 10:
        return False
    total = 0
    for i, c in enumerate(d):
        v = 10 if c == 'X' else int(c)
        total += (10 - i) * v
    return total % 11 == 0


# ---------- 角色拆分 ----------

ROLE = re.compile(r'(副主编|主编|编著|著|编|译|绘)\s*$')
COUNTRY = re.compile(r'^[（(][^）)]{1,6}[）)]')


def _clean_name(n):
    n = (n or '').strip(' .．,，、；;')
    n = COUNTRY.sub('', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _split_top(raw):
    """按顶层分隔符切分，括号里的点/逗号不切（外国人名 Exupery,S.）。"""
    parts, buf, depth = [], [], 0
    for ch in raw:
        if ch in '（(':
            depth += 1
        elif ch in '）)':
            depth = max(0, depth - 1)
        if depth == 0 and ch in '；;。':
            parts.append(''.join(buf)); buf = []
        elif depth == 0 and ch == '.':
            parts.append(''.join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf))
    return [p.strip() for p in parts if p.strip()]


def parse_roles(raw):
    """从“赵云旺，李世乾主编；齐春荣、康少膑副主编”拆出 [{name, role}]。"""
    raw = re.sub(r'\s+', ' ', raw or '').strip()
    out = []
    for part in _split_top(raw):
        part = part.strip()
        if not part:
            continue
        m = ROLE.search(part)
        if not m:
            continue
        role = m.group(1)
        names = part[:m.start()].strip(' ，,、')
        # 外国人名带括号/逗号时整体保留；中文名按逗号顿号拆
        chunks = [names] if re.search(r'[A-Za-z]', names) else re.split(r'[，,、]', names)
        for c in chunks:
            n = _clean_name(c)
            if len(re.sub(r'[^\u4e00-\u9fa5A-Za-z]', '', n)) < 2:
                continue
            if n and all(x['name'] != n for x in out):
                out.append({'name': n, 'role': role})
    return out


def _author_value(people):
    if not people:
        return ''
    return '、'.join('%s（%s）' % (p['name'], p['role']) for p in people)


# ---------- 版权页 ----------

def find_cip(rows):
    for r in rows:
        t = r.get('文本') or ''
        if '图书在版编目' in t or 'CIP数据' in t or 'CIP）数据' in t:
            return r
    return None


def parse_cip(seg):
    t = (seg.get('文本') or '').replace('\u3000', ' ')
    # 从“图书在版编目/CIP数据”截起，避免抓到前面的网址、广告语
    for marker in ('图书在版编目', 'CIP数据', 'CIP）数据'):
        i = t.find(marker)
        if i >= 0:
            t = t[i:]
            break
    out = {'_seg': seg}

    m = re.search(r'(?:CIP[)）]?\s*数据|数据)\s*([^/／]{2,50}?)\s*[/／]', t)
    if not m:
        m = re.search(r'图书在版编目[^数]{0,20}数据\s*([^/／]{2,50}?)\s*[/／]', t)
    if m:
        out['title'] = _cut(m.group(1))

    m = re.search(r'[/／]\s*(.{2,160}?)\s*(?:\.\s*-{1,2}|\.--|--)', t)
    if m:
        out['author_raw'] = m.group(1).strip()
        out['people'] = parse_roles(out['author_raw'])

    m = re.search(r'(?:\.\s*-{1,2}|\.--)\s*([\u4e00-\u9fa5]{2,8})\s*[：:]', t)
    if m:
        out['publisher_city'] = m.group(1)

    m = re.search(r'([\u4e00-\u9fa5]{2,20}出版社)', t)
    if m:
        out['publisher'] = m.group(1)

    m = re.search(r'([12]\d{3})\s*[年.]\s*(\d{1,2})', t)
    if m:
        out['date'] = '%s年%s月' % (m.group(1), m.group(2))
        out['date_quote'] = m.group(0)

    m = re.search(r'ISBN[\s:：]*([0-9][0-9\-\s]{9,20})', t)
    if m:
        out['isbn_raw'] = m.group(1).strip()

    m = re.search(r'核字\s*([^\n]{0,40}?号)', t)
    if m:
        out['cip_raw'] = '核字' + m.group(1).strip()
        out['cip_number'] = m.group(1).strip()

    codes = []
    for m in re.finditer(r'[ⅠⅡⅢⅣIV]{1,3}\s*[.．]\s*(?:[①-⑳]|[0-9]{1,2})?\s*'
                         r'([A-Z][0-9]{0,3}(?:\.[0-9]+)?(?:-[0-9]+)?)', t):
        c = m.group(1)
        if c not in codes:
            codes.append(c)
    if codes:
        out['class_codes'] = codes

    m = re.search(r'责任编辑[\s:：]*([^\n]{2,20})', t)
    if m:
        v = _cut(m.group(1))
        v = re.sub(r'[│|｜\s]+', '', v)
        if 2 <= len(v) <= 6:
            out['editor'] = v
            out['editor_quote'] = m.group(0)[:40]

    m = re.search(r'开\s*本\s*([^\n]{0,45})', t)
    if m:
        out['format_raw'] = _cut(m.group(1))

    m = re.search(r'字\s*数\s*([\d,，\s]+)\s*(千字|万字)?', t)
    if m:
        out['words_num'] = m.group(1).strip()
        out['words_unit'] = m.group(2) or ''
        out['words_raw'] = (out['words_num'] + out['words_unit']).strip()

    m = re.search(r'定\s*价\s*([\d.]+\s*元?)', t)
    if m:
        out['price_raw'] = m.group(1).strip()

    m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*第\s*(\d+)\s*版', t)
    if m:
        out['edition_date'] = '%s年%s月' % (m.group(1), m.group(2))
        out['edition'] = '第%s版' % m.group(3)

    m = re.search(r'第\s*(\d+)\s*次印刷', t)
    if m:
        out['impression'] = '第%s次印刷' % m.group(1)

    m = re.search(r'(\d{1,4})\s*页', t)
    if m:
        out['pages'] = m.group(1) + '页'

    m = BINDING_WORDS.search(t)
    if m:
        out['binding'] = m.group(0)

    m = re.search(r'([\u4e00-\u9fa5A-Za-z0-9·\-—]{2,24}(?:丛书|文库|书系))', t)
    if m:
        out['series'] = m.group(1)

    return out


# ---------- 书名页/封面/封底 ----------

def parse_front(rows):
    """没有版权页时，从正文前几段找作者署名、作者简介。

    只在有明确“主编：/编著：”标签时采信；没有标签不猜（避免把书名末字并进人名）。
    出版社不从这里取：封面文字常粘连，交给书目库导入更稳。
    """
    out = {}
    front = [r for r in rows if str(r.get('篇序')) == '0'][:10] or rows[:10]
    for r in front:
        t = (r.get('文本') or '').replace('\u3000', ' ')
        if 'people' not in out:
            ppl = []
            for m in re.finditer(r'(副\s*主\s*编|主\s*编|编\s*著)\s*[：:]\s*([^\n]{2,40}?)'
                                 r'(?=副\s*主\s*编|主\s*编|编\s*著|编\s*委|序\s*言|前\s*言|目\s*录|$)', t):
                role = re.sub(r'\s+', '', m.group(1))
                val = m.group(2)
                for n in re.split(r'[、，,\s]+', val):
                    n = _clean_name(n)
                    if len(n) >= 2 and all(x['name'] != n for x in ppl):
                        ppl.append({'name': n, 'role': role})
            if ppl:
                out['people'] = ppl
                out['author_seg'] = r
                first = re.search(r'(副\s*主\s*编|主\s*编|编\s*著)\s*[：:]', t)
                last = None
                for mm in re.finditer(r'(副\s*主\s*编|主\s*编|编\s*著)\s*[：:]\s*([^\n]{2,40}?)'
                                      r'(?=副\s*主\s*编|主\s*编|编\s*著|编\s*委|序\s*言|前\s*言|目\s*录|$)', t):
                    last = mm
                if first and last:
                    out['author_quote'] = t[first.start():last.end()]
    for r in rows:
        t = (r.get('文本') or '').replace('\u3000', ' ')
        m = re.search(r'作者简介|作者介绍|作者小传', t)
        if m:
            body = t[m.end():]
            body = re.split(r'前\s*言|目\s*录|序\s*言|第[一二三四五六七八九十]+章', body)[0]
            body = body.strip(' ：:，,。.')
            if len(body) >= 40:
                out['author_bio'] = body[:1200]
                out['author_bio_seg'] = r
            break
    return out


# ---------- 开本 ----------

def split_format(raw):
    raw = (raw or '').strip()
    if not raw:
        return []
    out = []
    size = re.search(r'(\d{2,4}\s*(?:毫米)?\s*[×xX*]\s*\d{2,4}\s*毫米)', raw)
    if size:
        out.append({'type': '成品尺寸', 'value': re.sub(r'\s+', '', size.group(1))})
    fmt = re.search(r'(\d+\s*/\s*\d+|\d{1,2}\s*开)', raw)
    if fmt:
        out.append({'type': '开数', 'value': re.sub(r'\s+', '', fmt.group(1))})
    if not out:
        out.append({'type': '原文', 'value': raw})
    return out


# ---------- 主流程 ----------

def build(code, library=None):
    rows = _rows(code)
    book = _book(code)
    lib = (library or {}).get(code) or {}
    cip = find_cip(rows)
    c = parse_cip(cip) if cip else {}
    f = parse_front(rows) if rows else {}

    items = {}

    # 001 书名
    cip_title = c.get('title') or ''
    bad_title = (len(cip_title) > 30 or '()' in cip_title or '（）' in cip_title
                 or '著' in cip_title or '绘' in cip_title)
    if cip_title and not bad_title:
        items['book_title'] = _item('book_title', cip_title, 'found', 'rule', 0.98,
                                    [_ev(cip, cip_title)])
    elif lib.get('book'):
        ev = _find_import_evidence(rows, lib['book'])
        note = '书目库导入' + ('' if ev else '；原文文字层未找到可连续定位的书名')
        if ev and lib['book'] != (ev[0].get('quote') or '') and ('（' in lib['book'] or '(' in lib['book']):
            note += '；书名锚到原文主书名，括号内卷次不在文字层'
        items['book_title'] = _item('book_title', lib['book'], 'found', 'import', 0.9,
                                    ev, note)
    else:
        items['book_title'] = _item('book_title')

    # 002 作者
    people = c.get('people') or f.get('people') or []
    if people:
        items['author'] = _item('author', {'raw': c.get('author_raw') or _author_value(people),
                                           'people': people},
                                'found', 'rule', 0.92 if c.get('people') else 0.85,
                                [_ev(cip if c.get('people') else f.get('author_seg'),
                                     c.get('author_raw') or f.get('author_quote') or _author_value(people))],
                                '' if c.get('people') else '作者取自书名页/封面署名，建议复核')
    elif lib.get('author'):
        ev = _find_import_evidence(rows, lib['author'])
        items['author'] = _item('author', {'raw': lib['author'], 'people': []},
                                'found', 'import', 0.7, ev,
                                '书目库导入，未拆角色' + ('' if ev else '；原文未找到可定位署名'))
    else:
        items['author'] = _item('author')

    # 003 出版社
    cip_pub = c.get('publisher') or ''
    lib_pub = lib.get('publisher') or ''
    if cip_pub and lib_pub and cip_pub in lib_pub and len(lib_pub) > len(cip_pub):
        ev = _find_import_evidence(rows, lib_pub)
        note = '版权页出版社名被截断，采用书目库全称'
        if ev:
            note += '；原文可定位到全称'
        else:
            ev = [_ev(cip, cip_pub)]
            note += '；原文证据只到前缀'
        items['publisher'] = _item('publisher', lib_pub, 'found', 'import', 0.9, ev, note)
    elif cip_pub:
        items['publisher'] = _item('publisher', cip_pub, 'found', 'rule', 0.97,
                                   [_ev(cip, cip_pub)])
    elif lib.get('publisher'):
        ev = _find_import_evidence(rows, lib['publisher'])
        items['publisher'] = _item('publisher', lib['publisher'], 'found', 'import', 0.8,
                                   ev, '书目库导入' + ('' if ev else '；原文未找到可定位出版社名'))
    else:
        items['publisher'] = _item('publisher')

    # 004 印次
    if c.get('impression'):
        items['impression'] = _item('impression', c['impression'], 'found', 'rule', 0.97,
                                    [_ev(cip, c['impression'])])
    else:
        items['impression'] = _item('impression')

    # 005 责任编辑
    if c.get('editor'):
        items['editor_in_charge'] = _item('editor_in_charge', c['editor'], 'found', 'rule', 0.95,
                                          [_ev(cip, c.get('editor_quote') or c['editor'])])
    else:
        items['editor_in_charge'] = _item('editor_in_charge')

    # 006 副书名
    title = c.get('title') or ''
    m = re.match(r'^(.{2,40}?)\s*[：:—]{1,2}\s*(.{2,40})$', title)
    if m:
        items['subtitle'] = _item('subtitle', {'main': m.group(1).strip(), 'sub': m.group(2).strip()},
                                  'needs_review', 'rule', 0.6, [_ev(cip, title)],
                                  '按标题分隔符切分，需人工确认')
    else:
        items['subtitle'] = _item('subtitle')

    # 007 CIP 核字号
    if c.get('cip_number'):
        items['cip_number'] = _item('cip_number', {'number': c['cip_number'], 'raw': c.get('cip_raw')},
                                    'found', 'rule', 0.98, [_ev(cip, c.get('cip_raw') or c['cip_number'])])
    else:
        items['cip_number'] = _item('cip_number')

    # 008 翻译相关人员
    trans = [p for p in people if '译' in p['role']]
    if trans:
        items['translators'] = _item('translators', trans, 'found', 'rule', 0.9,
                                     [_ev(cip if c.get('people') else f.get('author_seg'),
                                          c.get('author_raw') or _author_value(people))])
    else:
        items['translators'] = _item('translators')

    # 009 出版时间
    date = c.get('edition_date') or c.get('date')
    if date:
        items['publication_date'] = _item('publication_date', date, 'found', 'rule', 0.93,
                                          [_ev(cip, c.get('date_quote') or date)])
    else:
        items['publication_date'] = _item('publication_date')

    # 010 版次
    if c.get('edition'):
        items['edition'] = _item('edition', c['edition'], 'found', 'rule', 0.97,
                                 [_ev(cip, c['edition'])])
    else:
        items['edition'] = _item('edition')

    # 011 装帧形式
    if c.get('binding'):
        items['binding'] = _item('binding', c['binding'], 'found', 'rule', 0.9,
                                 [_ev(cip, c['binding'])])
    else:
        items['binding'] = _item('binding')

    # 012 开本
    if c.get('format_raw'):
        vals = split_format(c['format_raw'])
        items['book_format'] = _item('book_format', vals, 'found', 'rule',
                                     0.9 if len(vals) > 1 else 0.75,
                                     [_ev(cip, c['format_raw'])],
                                     '' if len(vals) > 1 else '只识别到一类，未推算另一类')
    else:
        items['book_format'] = _item('book_format')

    # 013 页数（绝不用 PDF 页数）
    if c.get('pages'):
        items['pages'] = _item('pages', c['pages'], 'found', 'rule', 0.9,
                               [_ev(cip, c['pages'])])
    else:
        items['pages'] = _item('pages', note='版权页未印页数；不使用 PDF 物理页数')

    # 014 字数
    if c.get('words_raw'):
        num = float(re.sub(r'[^\d.]', '', c.get('words_num') or '0') or 0)
        unit = c.get('words_unit') or ''
        norm = None
        if unit == '千字':
            norm = int(num * 1000)
        elif unit == '万字':
            norm = int(num * 10000)
        elif re.search(r'\s', c.get('words_num') or ''):
            norm = int(num)
        status = 'found' if norm is not None else 'needs_review'
        items['word_count'] = _item('word_count',
                                    {'raw': c['words_raw'], 'normalized': norm, 'unit': unit},
                                    status, 'rule', 0.9, [_ev(cip, c['words_raw'])],
                                    '' if norm is not None else '原文无单位，按数字原样保留')
    else:
        items['word_count'] = _item('word_count')

    # 015 定价
    if c.get('price_raw'):
        amount = re.search(r'[\d.]+', c['price_raw'])
        items['price'] = _item('price',
                               {'raw': c['price_raw'], 'amount': float(amount.group(0)) if amount else None,
                                'currency': 'CNY'},
                               'found', 'rule', 0.95, [_ev(cip, c['price_raw'])])
    else:
        items['price'] = _item('price')

    # 016 丛书名
    if c.get('series'):
        items['series'] = _item('series', c['series'], 'found', 'rule', 0.8,
                                [_ev(cip, c['series'])])
    else:
        items['series'] = _item('series')

    # 017 作者简介
    if f.get('author_bio'):
        items['author_bio'] = _item('author_bio', f['author_bio'], 'found', 'rule', 0.85,
                                    [_ev(f['author_bio_seg'], f['author_bio'][:120])],
                                    '抽取现成简介，未改写')
    else:
        items['author_bio'] = _item('author_bio')

    # 027 分类信息
    recs = []
    for code_ in (c.get('class_codes') or []):
        m2 = re.match(r'([A-Z]+)', code_)
        name = ''
        try:
            import clc
            name = clc.NAME.get(m2.group(1), '') if m2 else ''
        except Exception:
            name = ''
        recs.append({'system': '中图法', 'version': '', 'code': code_, 'name': name,
                     'source': '版权页',
                     'note': '类目名仅到一级' if name and len(code_) > 2 else ''})
    if not recs and book.get('CLC', {}).get('代码'):
        cl = book['CLC']
        recs.append({'system': '中图法', 'version': '', 'code': cl.get('细分号') or cl.get('代码'),
                     'name': cl.get('名称', ''), 'source': cl.get('来源', '')})
    src_cip = bool(c.get('class_codes'))
    if recs and src_cip:
        items['classification'] = _item('classification', recs,
                                        'found', 'rule', 0.95,
                                        [_ev(cip, recs[0]['code'])],
                                        '')
    elif recs:
        # 规则建议没有原文分类号：不导出，不用规则结果冒充原文标注
        sug = '；'.join('%s %s' % (x.get('code') or '', x.get('name') or '') for x in recs)
        items['classification'] = _item('classification', None, 'not_found', 'rule', None, [],
                                        '原文无中图法分类号；规则建议 %s 未导出，需人工确认' % sug)
    else:
        items['classification'] = _item('classification')

    # 081 书号
    ids = []
    if c.get('isbn_raw'):
        raw = c['isbn_raw']
        digits = re.sub(r'\D', '', raw)
        kind = 'ISBN-13' if len(digits) == 13 else ('ISBN-10' if len(digits) == 10 else '其他书号')
        valid = isbn13_ok(raw) if len(digits) == 13 else (isbn10_ok(raw) if len(digits) == 10 else None)
        ids.append({'type': kind, 'value': raw, 'valid': valid})
    if ids:
        items['isbn'] = _item('isbn', ids, 'found' if ids[0]['valid'] else 'needs_review', 'rule',
                              0.98 if ids[0]['valid'] else 0.6, [_ev(cip, c['isbn_raw'])],
                              '' if ids[0]['valid'] else '校验位不通过，需人工核对')
    else:
        items['isbn'] = _item('isbn')

    # OCR 补洞：原生文字层没有书名时，用封面/书名页 OCR + 书目库交叉校验
    ocr_title = (_ocr_fields(code).get('book_title') or {})
    if (ocr_title.get('value') and ocr_title.get('status') in ('A', 'B')
            and not (items['book_title'].get('evidence'))):
        items['book_title'] = _item('book_title', ocr_title['value'], 'found', 'ocr',
                                    ocr_title.get('confidence'),
                                    ocr_title.get('evidence') or [],
                                    ocr_title.get('note') or 'OCR 封面识别')

    _apply_ocr(items, code)

    stats = {'found': 0, 'not_found': 0, 'needs_review': 0, 'not_applicable': 0}
    for it in items.values():
        stats[it['status']] = stats.get(it['status'], 0) + 1

    rec = {
        'code': code,
        'book': book.get('book') or lib.get('book') or '',
        'pack': PACK,
        'generated_at': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        'source': {'format': lib.get('source_format', ''),
                   'pages': lib.get('source_pages'),
                   'cip_seg': cip.get('id') if cip else ''},
        'items': items,
        'stats': stats,
    }
    return rec


def write(rec):
    d = os.path.join(P.OUT, rec['code'])
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, 'publication.json')
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(rec, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def main(argv):
    lib_path = ''
    show = False
    codes = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == '--all':
            codes = sorted([d for d in os.listdir(P.OUT)
                            if os.path.isdir(os.path.join(P.OUT, d)) and re.match(r'^[A-Z][A-Z0-9]{0,3}$', d)])
        elif a == '--library':
            i += 1
            lib_path = argv[i]
        elif a == '--print':
            show = True
        elif a.startswith('-'):
            print('unknown option', a)
            return 2
        else:
            codes.append(a)
        i += 1
    if not codes:
        print(__doc__)
        return 2
    lib = _library(lib_path)
    for code in codes:
        rec = build(code, lib)
        path = write(rec)
        s = rec['stats']
        print('%s %-28s found=%2d not_found=%2d review=%d -> %s'
              % (code, rec['book'][:26], s['found'], s['not_found'], s['needs_review'], path))
        if show:
            print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
