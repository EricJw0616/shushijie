# -*- coding: utf-8 -*-
"""P12 纪事型：从「人物资料框」抽人物条目。

为什么单独一层：人物故事集（院士传记、廉洁故事）的正文是叙事，
但真正的结构化数据不在正文里，在每一篇开头那个资料框：

    姓名：李四光
    生卒年：—
    籍贯：湖北黄冈
    身份：地质学家、中国科学院院士
    主要成就：早年从事古生物研究……
    院士语录：……

资料框在版面上是单独一栏（x 约 150），左边还有竖排的大字姓名和一句
竖排题记。按纯文本读会把竖排字混进资料框（「气象学家、地理学是家」），
所以这一步读版面坐标，只取资料框那一栏。

没有版面文件时退回按文本切，质量会差一些，但不会不出。
"""
import re

FIELD_KEYS = ('姓名', '生卒年', '籍贯', '身份', '主要成就', '院士语录',
              '毕业院校', '出生', '逝世', '出生地')

# 资料框在版面上的横向位置（pt）。这本书正文左边距 79/102，资料框在 150。
BOX_X_MIN = 130
BOX_X_MAX = 340

_LABEL_RE = re.compile(r'^(%s)[：:]\s*(.*)$' % '|'.join(FIELD_KEYS))
_NOISE_RE = re.compile(r'^[①-⑳\d\s.．\-—]+$')


def _parse_fields(lines):
    fields = {}
    key = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = _LABEL_RE.match(line)
        if m:
            key = m.group(1)
            fields[key] = m.group(2).strip()
        elif key:
            fields[key] = (fields.get(key, '') + line).strip()
    # 版面里的装饰星号会混进字段值
    return {k: v.replace('★', '').strip() for k, v in fields.items()}


def people_from_pages(pages):
    """版面页 → [{name, page, fields}]。一个资料框一页，不跨页收集。"""
    out = []
    for p in pages or []:
        box = [l for l in (p.get('lines') or [])
               if l.get('k') == 'body' and BOX_X_MIN <= l.get('x0', 0) <= BOX_X_MAX]
        if not box:
            continue
        box.sort(key=lambda l: l.get('top', 0))
        lines = []
        for l in box:
            t = (l.get('t') or '').strip()
            if t and not _NOISE_RE.match(t):
                lines.append(t)
        if not any(re.match(r'^姓名[：:]', t) for t in lines):
            continue
        fields = _parse_fields(lines)
        name = (fields.pop('姓名', '') or '').strip()
        if not name or len(name) > 20:
            continue
        out.append({'name': name, 'page': p.get('page') or 0, 'fields': fields})
    # 同一人只留第一次（目录页也可能出现「姓名：」）
    seen, uniq = set(), []
    for x in out:
        if x['name'] in seen:
            continue
        seen.add(x['name'])
        uniq.append(x)
    return uniq


def people_from_text(text):
    """没有版面时的兜底：按「姓名：」切段，字段按行标签收。"""
    out = []
    cur = None
    for raw in (text or '').splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r'^姓名[：:]\s*(.+)$', s)
        if m:
            if cur:
                out.append(cur)
            cur = {'name': m.group(1).strip(), 'page': 0, 'lines': [s]}
            continue
        if cur is not None and len(cur['lines']) < 40:
            cur['lines'].append(s)
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    res = []
    for x in out:
        f = _parse_fields(x['lines'])
        name = (f.pop('姓名', '') or x['name']).strip()
        if not name or len(name) > 20:
            continue
        res.append({'name': name, 'page': 0, 'fields': f})
    return res
