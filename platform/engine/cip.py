# -*- coding: utf-8 -*-
"""版权页（CIP）解析：元数据能读就不猜。

输入是一本书的前置文本（segments 前几段拼接），输出结构化字段。
读不到就返回空字段 + 原因，由上层标「待核」，不许猜。
"""
import re
import unicodedata

FIELDS = ['书名', '著者', '出版社', '出版地', '出版年月', 'ISBN', 'CIP核字号',
          '中图法', '开本', '印张', '字数', '定价', '版次', '印次']

def norm(t):
    """全角转半角、去多余空白，保留换行。"""
    t = unicodedata.normalize('NFKC', t or '')
    t = re.sub(r'[ \t\u3000]+', ' ', t)
    return t

def _num(s):
    return re.sub(r'[^\d.]', '', s or '')

def parse(text, title=''):
    raw = text or ''
    t = norm(text)
    out = {'_found': False, '_reason': ''}
    if '图书在版编目' not in t and 'CIP' not in t.upper():
        out['_reason'] = '没有版权页（CIP）'
        return out
    out['_found'] = True
    i = t.find('图书在版编目')
    if i < 0:
        i = t.upper().find('CIP')
    block = t[i:i + 1200]
    j = raw.find('图书在版编目')
    if j < 0:
        j = raw.upper().find('CIP')
    rblock = raw[j:j + 1200] if j >= 0 else ''

    m = re.search(r'ISBN[\s:：]*([0-9][0-9\-\s]{9,20})', block)
    if m:
        out['ISBN'] = re.sub(r'[^\dXx-]', '', m.group(1)).strip('-')

    m = re.search(r'核字\s*第?\s*([0-9]{4}[A-Za-z]{0,3}[0-9]+)', block)
    if m:
        out['CIP核字号'] = m.group(1)

    # 分类号：形如 "Ⅰ. D630.9-49" / "Ⅳ. I247.5"（OCR 常把 Ⅳ 认成 Ⅰ）
    for m in re.finditer(r'[ⅠⅡⅢⅣIV]{1,3}\s*[.．]\s*(?:[①-⑳]|[0-9]{1,2})?\s*([A-Z][0-9]{0,3}(?:\.[0-9]+)?(?:-[0-9]+)?)', rblock or block):
        out['中图法'] = m.group(1)
        break

    m = re.search(r'开\s*本\s*([^\n，,。；]{0,40})', block)
    if m:
        seg = m.group(1)
        size = re.search(r'([0-9]{2,4}\s*(?:毫米)?\s*[×xX*]\s*[0-9]{2,4}\s*毫米)', seg)
        fmt = re.search(r'([0-9]+\s*/\s*[0-9]+)', seg)
        parts = [re.sub(r'\s+', '', x.group(1)) for x in (size, fmt) if x]
        if parts:
            out['开本'] = ' '.join(parts)

    m = re.search(r'印\s*张\s*([0-9.]+)', block)
    if m:
        out['印张'] = _num(m.group(1))

    m = re.search(r'字\s*数\s*([0-9,，\s]+)\s*(千字|万字)?', block)
    if m:
        v = float(_num(m.group(1)) or 0)
        unit = m.group(2) or ''
        if unit == '千字':
            v *= 1000
        elif unit == '万字':
            v *= 10000
        out['字数'] = str(int(v))

    m = re.search(r'定\s*价\s*([0-9.]+)\s*元', block)
    if m:
        out['定价'] = _num(m.group(1))

    m = re.search(r'(\d{4}\s*年\s*\d{1,2}\s*月)\s*第\s*(\d+)\s*版', block)
    if m:
        out['出版年月'] = m.group(1).replace(' ', '')
        out['版次'] = '第%s版' % m.group(2)

    m = re.search(r'第\s*(\d+)\s*次印刷', block)
    if m:
        out['印次'] = '第%s次印刷' % m.group(1)

    # 出版地 / 出版社：常见 "石家庄：河北人民出版社，2024.10" 或 "河北人民出版社"
    m = re.search(r'([\u4e00-\u9fa5]{2,6})\s*[：:]\s*([\u4e00-\u9fa5]{2,20}出版社)', block)
    if m:
        out['出版地'], out['出版社'] = m.group(1), m.group(2)
    else:
        m = re.search(r'([\u4e00-\u9fa5]{2,20}出版社)', block)
        if m:
            out['出版社'] = m.group(1)

    # 著者：书名与出版地之间那段，取"主编/编著/著/译"前的人名
    m = re.search(r'([\u4e00-\u9fa5、，, ]{2,40}?)\s*(主编|编著|著|译|编)(?![\u4e00-\u9fa5])', block)
    if m:
        out['著者'] = (m.group(1).strip(' ，,、') + m.group(2))

    # 书名 / 著者 / 出版地：CIP 正文的常见排法「书名 / 著者. -- 出版地 : 出版社」
    m = re.search(r'数据\s*([\u4e00-\u9fa5A-Za-z0-9（）()·—\-\s]{2,40}?)\s*[/／]\s*([^/／]{2,120}?)\s*\.?\s*-{1,2}\s*([\u4e00-\u9fa5]{2,10})?', block)
    if m:
        out['书名'] = m.group(1).strip()
        zz = re.sub(r'\s+', '', m.group(2))
        zz = re.sub(r'^[（(][^）)]{0,10}[）)]', '', zz)   # 去掉国别
        roles = []
        for name, role in re.findall(r'([\u4e00-\u9fa5A-Za-z（()）.,·、]{2,30}?)(副主编|主编|编著|著|编|译|绘)(?=[.。；;]|$)', zz):
            name = name.strip('.,、')
            if re.match(r'^(著|编|译|绘)', name) or len(name) < 2:
                continue
            if '(' in name or '（' in name:
                parts = [name]          # 含括号的（如 Exupery,S.）不拆
            else:
                parts = re.split(r'[，,、；;]', name)
            for one in parts:
                one = one.strip()
                if len(one) >= 2:
                    roles.append('%s（%s）' % (one, role))
        out['著者'] = '、'.join(roles) if roles else zz[:40]
        if m.group(3):
            out['出版地'] = m.group(3)
    elif title:
        out['书名'] = title

    if not any(out.get(k) for k in FIELDS):
        out['_found'] = False
        out['_reason'] = '有版权页但没解析出字段'
    return out


def isbn_ok(isbn):
    """ISBN-13 校验位。返回 True/False；位数不对返回 None。"""
    d = re.sub(r'\D', '', isbn or '')
    if len(d) != 13:
        return None
    s = sum((1 if i % 2 == 0 else 3) * int(ch) for i, ch in enumerate(d[:12]))
    return (10 - s % 10) % 10 == int(d[12])


def annotate(code, seg_path=None):
    """解析版权页，写 book.json 的 CIP；有分类号时同时写 CLC（来源=版权页）。"""
    import json as _json
    import os as _os
    import paths as P
    bpath = _os.path.join(P.OUT, code, 'book.json')
    spath = seg_path or _os.path.join(P.OUT, code, 'segments.jsonl')
    try:
        with open(bpath, encoding='utf-8') as fp:
            book = _json.load(fp)
    except Exception:
        return None
    try:
        rows = [_json.loads(l) for l in open(spath, encoding='utf-8') if l.strip()]
    except Exception:
        rows = []
    head = '\n'.join((r.get('文本') or '') for r in rows)
    got = parse(head, book.get('book') or '')
    got['ISBN校验'] = isbn_ok(got.get('ISBN'))
    book['CIP'] = got

    # 版权页分类号优先于规则建议；人工值另存 overrides，由 clc.annotate 恢复
    c = got.get('中图法') or ''
    if c:
        m = re.match(r'([A-Z]+)', c)
        if m:
            try:
                import clc as _CLC
                nm = _CLC.NAME.get(m.group(1), '')
            except Exception:
                nm = ''
            book['CLC'] = {'代码': m.group(1), '名称': nm, '细分号': c,
                           '依据': ['版权页 CIP：%s' % c],
                           '来源': '版权页', '置信': ''}
    tmp = bpath + '.tmp-cip'
    with open(tmp, 'w', encoding='utf-8') as fp:
        _json.dump(book, fp, ensure_ascii=False, indent=1)
    _os.replace(tmp, bpath)
    return got


if __name__ == '__main__':
    import io, json, sys
    p = sys.argv[1]
    rows = [json.loads(l) for l in io.open(p, encoding='utf-8') if l.strip()]
    head = '\n'.join((r.get('文本') or '') for r in rows)
    print(json.dumps(parse(head), ensure_ascii=False, indent=1))
