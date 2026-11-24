# -*- coding: utf-8 -*-
"""文件型存储层（无 SQLite）。

为什么不用 SQLite：这个平台最终要放到服务器上跑业务。SQLite 是单机文件库，
并发写、备份、迁移都不适合；但第一版又不想把本机演示卡在装 PostgreSQL 上。
所以把「存储」收在这一层：现在写 JSON/JSONL，接口保持简单；以后换
PostgreSQL 只换这一层，API 与前端不动。

数据分两类，职责分开：
  - 引擎产物（只读为主）：platform/out/<code>/、platform/library/*.json(l)
  - 应用状态（可写）：app/data/library.json、jobs/、archives/、trash.json
"""
import datetime
import io
import json
import math as _math
import os
import re
import secrets
import shutil
import tempfile
import threading
from contextlib import contextmanager

import engine_bridge as E
import entity_classify as EC

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(APP_DIR, 'data')
LIBFILE = os.path.join(DATA, 'library.json')
TRASHFILE = os.path.join(DATA, 'trash.json')
OPSFILE = os.path.join(DATA, 'operations.jsonl')
JOBDIR = os.path.join(DATA, 'jobs')
ARCHIVEDIR = os.path.join(DATA, 'archives')
UPLOADDIR = os.path.join(DATA, 'uploads')
FAILEDDIR = os.path.join(DATA, 'failed')
for _d in (DATA, JOBDIR, ARCHIVEDIR, UPLOADDIR, FAILEDDIR,
           os.path.join(E.OUT, '.trash'), E.TRASH_DIR):
    os.makedirs(_d, exist_ok=True)

try:
    import fcntl
except ImportError:          # Windows 本地开发
    fcntl = None


# ── 基础工具 ─────────────────────────────────────────────────────
def now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp-')
    with os.fdopen(fd, 'w', encoding='utf-8') as fp:
        fp.write(text)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        with io.open(path, encoding='utf-8') as fp:
            return json.load(fp)
    except Exception:
        return default if default is not None else {}


def write_json(path, data):
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1))


def read_jsonl(path, limit=None):
    if not os.path.exists(path):
        return []
    out = []
    try:
        with io.open(path, encoding='utf-8', errors='replace') as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
                if limit and len(out) >= limit:
                    break
    except Exception:
        pass
    return out


def iter_jsonl(path):
    if not os.path.exists(path):
        return
    with io.open(path, encoding='utf-8', errors='replace') as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


@contextmanager
def _lock(name):
    """跨进程文件锁。服务端多线程、runner 子进程都会写同一批 JSON。"""
    path = os.path.join(DATA, name + '.lock')
    with io.open(path, 'a+') as fp:
        if fcntl:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


_INVALID = str.maketrans({'/': '／', '\\': '＼', ':': '：', '*': '＊',
                          '?': '？', '"': '＂', '<': '＜', '>': '＞', '|': '｜'})
_EXTS = ('.txt', '.md', '.markdown', '.docx', '.pdf')


def safe_title(name):
    """书名要同时当文件名与锚点前缀，必须去掉路径分隔符与控制字符。"""
    s = os.path.basename(str(name or '')).strip()
    low = s.lower()
    for ext in _EXTS:
        if low.endswith(ext):
            s = s[:-len(ext)]
            break
    s = s.translate(_INVALID)
    s = re.sub(r'[\x00-\x1f\x7f]', '', s)
    s = re.sub(r'\s+', ' ', s).strip(' .')
    return s[:80] or '未命名'


def _code_key(code):
    m = re.match(r'^([A-Za-z]+)(\d+)$', str(code or ''))
    return (m.group(1), int(m.group(2))) if m else (str(code or ''), 0)


def _mtime_iso(path):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path)).astimezone().isoformat(timespec='seconds')
    except Exception:
        return now()


# ── 图书库索引 ───────────────────────────────────────────────────
def _empty_library():
    return {'version': 1, 'updated_at': now(), 'books': {}}


def load_library():
    lib = read_json(LIBFILE, None)
    if not isinstance(lib, dict) or not isinstance(lib.get('books'), dict):
        lib = _empty_library()
    return lib


def save_library(lib):
    lib['updated_at'] = now()
    write_json(LIBFILE, lib)


def sync_library():
    """把引擎 books.json 里新出现的书补进应用索引；已删除的书从索引移除。

    只补「书」，不覆盖应用侧字段（作者、来源、状态、操作记录）。
    """
    books = E.books_json()
    by_code = {}
    for b in books:
        if isinstance(b, dict) and b.get('code') and b.get('book'):
            by_code[b['code']] = b
    with _lock('library'):
        lib = load_library()
        recs = lib['books']
        changed = False
        uploads_in_progress = {job.get('title') for job in list_jobs(500)
                               if job.get('kind') == 'upload' and job.get('status') in ('queued', 'running')
                               } if by_code.keys() - recs.keys() else set()
        for code, b in by_code.items():
            if code not in recs:
                if b['book'] in uploads_in_progress:
                    continue
                bj = os.path.join(E.OUT, code, 'book.json')
                recs[code] = {
                    'code': code,
                    'book': b['book'],
                    'author': '',
                    'publisher': '',
                    'source': 'base',
                    'status': 'ready',
                    'confirmed': False,
                    'type_source': 'machine',
                    'added_at': _mtime_iso(bj),
                    'updated_at': now(),
                }
                changed = True
            else:
                if recs[code].get('book') != b['book']:
                    recs[code]['book'] = b['book']
                    changed = True
        for code in list(recs):
            if code not in by_code:
                del recs[code]
                changed = True
        if changed:
            save_library(lib)
        return lib


def upsert_book(record):
    with _lock('library'):
        lib = load_library()
        old = lib['books'].get(record['code'], {})
        old.update(record)
        old['updated_at'] = now()
        lib['books'][record['code']] = old
        save_library(lib)
        return old


def get_record(code):
    lib = sync_library()
    return lib['books'].get(code)


# ── 统计缓存 ─────────────────────────────────────────────────────
_CARD_CACHE = {}
_TAG_CACHE = {}

_TIERS = ('可直接用', '需人筛', '仅定位器')


# 「人物条目」是 P12 的人物抽取器顺手写的卡，和 people.jsonl 是同一批人。
# 2026-11-17 人物已进专名，这类卡不再算知识条目（数据留在文件里，只在读时跳过）。
# 人物条目 = 一人一条的资料卡，是内容资产，不是重复项。
# （曾经把它当重复项过滤，导致 B59 少 40 条、统计与实际产物对不上；已回退）
_DUP_CARD_TYPES = ()


def _is_dup_card(r):
    return (r.get('类型') or '') in _DUP_CARD_TYPES


def _card_kind(type_name):
    """知识类 = 能当内容用的条目；索引类 = 只能定位（篇目/引书/索引/专名）。
    索引类不算交付资产——「解析能力」页里就是这么定义的，口径必须一致。"""
    t = (type_name or '').strip()
    if re.match(r'^(篇目|引书|索引|专名|目录)', t):
        return '索引'
    return '知识'


def card_counts(code):
    path = os.path.join(E.OUT, code, 'cards.jsonl')
    try:
        mt = os.path.getmtime(path)
    except Exception:
        return {'total': 0, '可直接用': 0, '需人筛': 0, '仅定位器': 0}
    key = (path, mt)
    if key in _CARD_CACHE:
        return _CARD_CACHE[key]
    counts = {'total': 0, '可直接用': 0, '需人筛': 0, '仅定位器': 0, '知识': 0, '索引': 0}
    for r in iter_jsonl(path):
        if _is_dup_card(r):
            continue
        counts['total'] += 1
        tier = r.get('资产性质')
        if tier == '仅为定位器':
            tier = '仅定位器'
        if tier in counts:
            counts[tier] += 1
        counts[_card_kind(r.get('类型'))] += 1
    _CARD_CACHE[key] = counts
    return counts


def tags_index():
    path = os.path.join(E.LIB, 'tags.json')
    try:
        mt = os.path.getmtime(path)
    except Exception:
        return {}
    key = (path, mt)
    if key in _TAG_CACHE:
        return _TAG_CACHE[key]
    data = read_json(path, {}) or {}
    by_code = {}
    for b in data.get('书', []) or []:
        if b.get('码'):
            by_code[b['码']] = b
    _TAG_CACHE[key] = by_code
    return by_code


def tag_counts(code):
    t = tags_index().get(code, {})
    out = {}
    total = 0
    for lv in ('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7'):
        n = len(t.get(lv, []) or [])
        out[lv] = n
        total += n
    out['total'] = total
    return out


def completeness(code, rec=None):
    """四个关键层有没有产出：卡 / 判定 / 专名 / 金句。给列表页用。"""
    base = os.path.join(E.OUT, code)
    und = read_json(os.path.join(base, 'understanding.json'), {}) or {}
    return {
        'cards': bool((rec or {}).get('cards') or 0),
        'judge': os.path.exists(os.path.join(base, 'judge.json')),
        'entities': os.path.exists(os.path.join(base, 'entities.jsonl')),
        'quotes': bool(und.get('quotes')),
        'tagging': os.path.exists(os.path.join(base, '.tagging')),
    }


def _row(code, rec):
    b = E.book_json(code)
    cc = card_counts(code)
    tc = tag_counts(code)
    bj_path = os.path.join(E.OUT, code, 'book.json')
    proto = rec.get('prototype_override') or b.get('原型')
    pname = E.PROTO_NAMES.get(proto) or b.get('原型名') or '待开原型'
    conf = '人工' if rec.get('type_source') == 'manual' else (b.get('置信') or '')
    status = rec.get('status') or 'ready'
    if rec.get('confirmed'):
        status = 'ready'
    elif status == 'ready' and (b.get('拒判') or conf in ('中', '低')):
        status = 'pending'
    return {
        'code': code,
        'book': rec.get('book') or b.get('book') or code,
        'author': rec.get('author') or '',
        'publisher': rec.get('publisher') or '',
        'source': rec.get('source') or 'base',
        'source_format': rec.get('source_format') or '',
        'status': status,
        'confirmed': bool(rec.get('confirmed')),
        'type_source': rec.get('type_source') or 'machine',
        'prototype': proto,
        'prototype_name': pname,
        'clc': b.get('CLC') or {},
        'confidence': conf,
        'stability': b.get('稳定性'),
        'reject': bool(b.get('拒判')),
        'han': b.get('汉字_切段') or 0,
        'segments': b.get('段数') or 0,
        'chapters': b.get('篇数') or 0,
        'retention': b.get('保留率'),
        'cards': cc['total'],
        'knowledge': cc.get('知识', 0),
        'index': cc.get('索引', 0),
        'usable': cc['可直接用'],
        'review': cc['需人筛'],
        'locator': cc['仅定位器'],
        'tags': tc['total'],
        'graph': bool(b.get('可出关系图谱')),
        'added_at': rec.get('added_at') or _mtime_iso(bj_path),
        'updated_at': rec.get('updated_at') or now(),
        'last_job': rec.get('last_job') or '',
        'completeness': completeness(code, {'cards': cc['total']}),
    }


def library_rows():
    lib = sync_library()
    rows = [_row(code, rec) for code, rec in lib['books'].items()
            if os.path.exists(os.path.join(E.OUT, code, 'book.json'))]
    # 新上传的排前面；基准库按书码排。
    rows.sort(key=lambda r: (0 if r['source'] == 'upload' else 1,
                             r['added_at'] if r['source'] == 'upload' else '',
                             _code_key(r['code'])))
    return rows


def global_stats(rows=None):
    rows = rows if rows is not None else library_rows()
    tags_total = sum(r['tags'] for r in rows)
    manifest = read_json(os.path.join(E.LIB, 'manifest.json'), {}) or {}
    confirmed = (manifest.get('规则卡', 0) or 0) + (manifest.get('主题卡', 0) or 0) + (manifest.get('易错对照', 0) or 0)
    groups = []
    for p in E.PROTO_ORDER:
        n = len([r for r in rows if r['prototype'] == p])
        if n:
            groups.append({'key': p, 'name': E.PROTO_NAMES[p], 'count': n})
    return {
        'books': len(rows),
        'han': sum(r['han'] for r in rows),
        'segments': sum(r['segments'] for r in rows),
        'cards': sum(r['cards'] for r in rows),
        'knowledge': sum(r.get('knowledge', 0) for r in rows),
        'index': sum(r.get('index', 0) for r in rows),
        'usable': sum(r['usable'] for r in rows),
        'review': sum(r['review'] for r in rows),
        'locator': sum(r['locator'] for r in rows),
        'tags': tags_total,
        'pending': len([r for r in rows if r['status'] == 'pending']),
        'uploaded': len([r for r in rows if r['source'] == 'upload']),
        'confirmed': confirmed,
    }


# ── 书详情 / 卡片 / 原文 / 标签 ──────────────────────────────────
def _int(v):
    try:
        return int(v or 0)
    except Exception:
        return 0


def set_clc(code, clc_code):
    """人工指定中图分类分类。写入 book.json，来源标「人工」，后续重跑不覆盖。"""
    if not is_code(code):
        return None
    cc = str(clc_code or '').strip().upper()
    try:
        import clc as _CLC
        name = _CLC.NAME.get(cc, '')
    except Exception:
        name = ''
    if not cc or not name:
        return None
    path = os.path.join(E.OUT, code, 'book.json')
    b = read_json(path, {}) or {}
    if not b:
        return None
    got = {'代码': cc, '名称': name, '依据': ['人工指定'],
           '来源': '人工', '置信': ''}
    b['CLC'] = got
    write_json(path, b)
    try:
        import clc as _CLC
        _CLC.set_manual(code, cc)     # 重跑后据此恢复，pipeline 重写 book.json 也不会丢
    except Exception:
        pass
    return got


def card_ke_counts(code):
    """每个科名下有多少条知识条目（只认 字段.科名 精确值）。"""
    if not is_code(code):
        return {}
    out = {}
    for r in read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl')):
        ke = (r.get('字段') or {}).get('科名')
        if ke:
            out[ke] = out.get(ke, 0) + 1
    return out


def get_book_detail(code):
    if not is_code(code):
        return None
    rec = get_record(code)
    if not rec:
        return None
    b = E.book_json(code)
    if not b:
        return None
    catalog = next((c for c in E.catalog_json() if c.get('码') == code), {})
    tags = tags_index().get(code, {})
    # 标签补 seg_id：把「锚点」解析成确定的段 id，前端定位时只认这个字段。
    # tags_index() 的结果按 mtime 缓存、被多线程共享，这里只做幂等赋值。
    seg = _seg_rows(code)
    for lv in ('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7'):
        for it in (tags.get(lv) or []):
            if it.get('锚点'):
                it['seg_id'] = seg_id_of(code, it['锚点'], seg)
    outline = get_outline(code)
    folder = os.path.join(E.OUT, code)
    people = read_jsonl(os.path.join(E.OUT, code, 'people.jsonl'))
    cc = card_counts(code)
    tc = tag_counts(code)
    rows = library_rows()
    row = next((r for r in rows if r['code'] == code), None)
    detail = {
        'record': rec,
        'row': row,
        'book': b,
        'clc': b.get('CLC') or {},
        'cip': b.get('CIP') or {},
        'understanding': read_json(os.path.join(E.OUT, code, 'understanding.json'), {}) or {},
        'publication': read_json(os.path.join(E.OUT, code, 'publication.json'), {}) or {},
        'page_roles': read_json(os.path.join(E.OUT, code, 'page_roles.json'), {}) or {},
        'marketing': read_json(os.path.join(E.OUT, code, 'marketing.json'), {}) or {},
        'deep': read_json(os.path.join(E.OUT, code, 'deep.json'), {}) or {},
        'entity_counts': entity_counts(code),
        'name_processing': (read_json(os.path.join(folder, 'derivative_status.json'), {}) or {}).get('entities') or {},
        'quality': read_json(os.path.join(folder, 'quality.json'), {}) or {},
        'catalog': catalog,
        'tags': tags,
        'outline': outline,
        'people': {'count': len(people),
                   'strong': len([p for p in people if p.get('证据') == '强证据'])},
        # 概览页的人物索引：按出现次数取前 40，带首现锚点（点一下跳原文）
        'people_top': [
            {'人物': p.get('人物') or '', '频次': p.get('频次') or 0,
             '首现': p.get('首现') or '', '首现篇': p.get('首现篇') or ''}
            for p in sorted(people, key=lambda x: -_int(x.get('频次')))[:40]
            if p.get('人物')
        ],
        'cards': cc,
        'ke_counts': card_ke_counts(code),
        'tag_counts': tc,
        'operations': get_ops(code),
        'raw_exists': os.path.exists(os.path.join(E.RAW, rec.get('book', '') + '.txt')),
    }
    from label_coverage import for_book
    detail['tag_coverage'] = for_book(detail)
    return detail


def get_cards(code, tier='', type_='', q='', offset=0, limit=24, ke=''):
    if not is_code(code):
        return {'total': 0, 'offset': 0, 'limit': 0, 'items': [],
                'by_type': {}, 'by_tier': {t: 0 for t in _TIERS}}
    rows = read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl'))
    by_type, by_tier = {}, {t: 0 for t in _TIERS}
    q = (q or '').strip().lower()
    filtered = []
    for r in rows:
        if _is_dup_card(r):
            continue
        t = r.get('资产性质') or ''
        if t == '仅为定位器':
            t = '仅定位器'
        r['资产性质'] = t
        by_tier[t] = by_tier.get(t, 0) + 1
        by_type[r.get('类型') or '未分类'] = by_type.get(r.get('类型') or '未分类', 0) + 1
        if tier and t != tier:
            continue
        if type_ and r.get('类型') != type_:
            continue
        if q:
            hay = ' '.join([str(r.get('原文') or ''), str(r.get('类型') or ''),
                            json.dumps(r.get('字段') or {}, ensure_ascii=False),
                            str(r.get('词条') or '')]).lower()
            if q not in hay:
                continue
        # 按科名精确筛选：只认「字段.科名」，不做全文包含
        # （全文包含会算进正文里顺带提到的科，物种数会偏大）
        if ke and str((r.get('字段') or {}).get('科名') or '') != ke:
            continue
        filtered.append(r)
    total = len(filtered)
    offset = max(0, int(offset or 0))
    limit = min(100, max(1, int(limit or 24)))
    items = filtered[offset:offset + limit]
    seg = _seg_rows(code)
    for r in items:
        r['_excerpt'] = (r.get('原文') or '')[:260]
        # 锚点里存的是段 id，这里解析成确定的 seg_id，前端定位不用再猜编号
        r['seg_id'] = seg_id_of(code, r.get('锚点'), seg)
    return {'total': total, 'offset': offset, 'limit': limit,
            'items': items, 'by_type': by_type, 'by_tier': by_tier}


def list_cards_all(tier='', type_='', book='', q='', kind='', offset=0, limit=50):
    """全库资产清单：一行一条，跨书聚合，给「资产产出」页用。
    口径三分：知识（能当内容用）/ 索引（只能定位）/ 精度（可直接用·需人筛·仅定位器）。
    type_ 支持逗号分隔（如「篇目候选,情节候选」），一种产物可以跨两个类型。"""
    types = [x for x in str(type_ or '').split(',') if x]
    picked = []
    by_type, by_tier, by_kind = {}, {t: 0 for t in _TIERS}, {'知识': 0, '索引': 0}
    q = (q or '').strip().lower()
    for row0 in library_rows():
        code, bname = row0['code'], row0['book']
        if book and code != book:
            continue
        for r in read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl')):
            if _is_dup_card(r):
                continue
            t = r.get('资产性质') or ''
            if t == '仅为定位器':
                t = '仅定位器'
            r['资产性质'] = t
            typ = r.get('类型') or '未分类'
            k = _card_kind(typ)
            by_tier[t] = by_tier.get(t, 0) + 1
            by_type[typ] = by_type.get(typ, 0) + 1
            by_kind[k] += 1
            if tier and t != tier:
                continue
            if types and typ not in types:
                continue
            if kind and k != kind:
                continue
            if q:
                hay = ' '.join([str(r.get('原文') or ''), typ,
                                json.dumps(r.get('字段') or {}, ensure_ascii=False),
                                str(bname)]).lower()
                if q not in hay:
                    continue
            r['书'] = r.get('书') or bname
            r['码'] = r.get('码') or code
            r['类别'] = k
            # 00 篇 = 前置页（目录 / 序 / 作者年表 / 译者简介 / 版权页）。
            # 这里的书名不是这本书的引文，必须标出来，否则会当成书里的引用。
            _ch = str(r.get('锚点') or '').split('-')
            r['_front'] = len(_ch) >= 2 and _ch[1] == '00'
            r['_excerpt'] = (r.get('原文') or '')[:160]
            if typ == '引书候选':
                r['_cite'] = _cite_stats(code, (r.get('字段') or {}).get('书名') or '')
            picked.append(r)
    total = len(picked)
    offset = max(0, int(offset or 0))
    limit = min(100, max(1, int(limit or 50)))
    return {'total': total, 'offset': offset, 'limit': limit,
            'items': picked[offset:offset + limit],
            'by_type': by_type, 'by_tier': by_tier, 'by_kind': by_kind}


# 待补项分两类：抽检 = 机器已经填了、人只需抽样复核；人写 = 机器填不了，必须人写
_TODO_KIND = {
    '图注/图片对位': '缺件',
    '学名与别名抽检': '抽检',
    '照片 / 图注': '缺件',
    '本篇主旨一句话': '人写',
    '引用它做什么（支持/反驳/举例）': '人写',
    '生平时间线': '人写',
    '这一回的实际因果链（需人读）': '人写',
    '事件里谁是主动方': '人写',
}


def card_todo(book=''):
    """待补项汇总：还差哪些字段才能「完整交付」，各多少条、落在哪本书。"""
    groups = {}
    for row0 in library_rows():
        code, bname = row0['code'], row0['book']
        if book and code != book:
            continue
        for r in read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl')):
            if _is_dup_card(r):
                continue
            skip = False
            if (r.get('类型') or '') == '引书候选':
                c = _cite_stats(code, (r.get('字段') or {}).get('书名') or '')
                skip = bool(c) and c['body'] == 0
            for t in (r.get('待补') or []):
                g = groups.get(t)
                if not g:
                    g = groups[t] = {'item': t, 'kind': _TODO_KIND.get(t, '人写'),
                                     'count': 0, 'books': {}, 'types': {}, 'ids': [],
                                     'skipped': 0}
                if skip:
                    # 只在版权页 / 作者作品表里出现过的书名，没有「引用它做什么」可补
                    g['skipped'] += 1
                    continue
                g['count'] += 1
                g['books'][bname] = g['books'].get(bname, 0) + 1
                typ = r.get('类型') or '未分类'
                g['types'][typ] = g['types'].get(typ, 0) + 1
                if len(g['ids']) < 5:
                    g['ids'].append(r.get('id'))
    order = {'人写': 0, '抽检': 1, '缺件': 2}
    items = sorted(groups.values(),
                   key=lambda x: (order.get(x['kind'], 3), -x['count'], x['item']))
    return {'total': sum(x['count'] for x in items), 'items': items}


def card_field_stats(types='', book=''):
    """字段覆盖率：产物里每个字段有多少条填了值，用来看哪个字段是空的（而不是只数总条数）。"""
    want = [x for x in str(types or '').split(',') if x]
    total, cnt = 0, {}
    for row0 in library_rows():
        if book and row0['code'] != book:
            continue
        for r in read_jsonl(os.path.join(E.OUT, row0['code'], 'cards.jsonl')):
            if _is_dup_card(r):
                continue
            if want and (r.get('类型') or '') not in want:
                continue
            total += 1
            for k, v in (r.get('字段') or {}).items():
                if v not in (None, '', '—'):
                    cnt[k] = cnt.get(k, 0) + 1
    fields = [{'name': k, 'count': v, 'miss': total - v} for k, v in cnt.items()]
    fields.sort(key=lambda x: -x['count'])
    return {'total': total, 'fields': fields}


def _cite_stats(code, title, limit=3):
    """书名在原文里到底出现在哪：正文几次、前置页几次，各给一段上下文。

    只数「出现几次」会被前置页骗——版权页、作者作品表、目录里的书名不是这本书
    正文里的引用。小王子那 8 条「引书」全在前置页，其实是出版社列的作者作品单。
    """
    if not title:
        return None
    rows, _, _ = _seg_rows(code)
    front = body = 0
    quotes, front_quotes = [], []
    for seg in rows:
        text = seg.get('文本') or ''
        n = text.count(title)
        if not n:
            continue
        sid = str(seg.get('id') or '')
        i = text.find(title)
        a, b = max(0, i - 40), min(len(text), i + len(title) + 60)
        one = {'seg': sid, '篇': seg.get('篇') or '', '序': seg.get('篇序'),
               'quote': text[a:b].replace('\n', ' ')}
        if sid.split('-')[1:2] == ['00'] or seg.get('篇序') == 0:
            front += n
            if len(front_quotes) < 2:
                front_quotes.append(one)
            continue
        body += n
        if len(quotes) < limit:
            quotes.append(one)
    return {'front': front, 'body': body, 'quotes': quotes,
            'front_quotes': front_quotes}


def get_card(code, cid):
    """单条知识条目：给「条目详情」这类独立页面用，不用把整本卡都拉到前端去筛。"""
    if not is_code(code) or not cid:
        return {'item': None}
    rows = read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl'))
    for r in rows:
        if r.get('id') == cid:
            t = r.get('资产性质') or ''
            if t == '仅为定位器':
                t = '仅定位器'
            r['资产性质'] = t
            r['_excerpt'] = (r.get('原文') or '')[:260]
            r['seg_id'] = seg_id_of(code, r.get('锚点'), _seg_rows(code))
            return {'item': r}
    return {'item': None}


def get_outline(code):
    return read_jsonl(os.path.join(E.OUT, code, 'outline.jsonl'))


def get_segments(code, chapter='', offset=0, limit=20):
    if not is_code(code):
        return {'total': 0, 'offset': 0, 'limit': 0, 'items': []}
    rows = _seg_rows(code)[0]
    if chapter:
        rows = [r for r in rows if r.get('篇') == chapter]
    total = len(rows)
    offset = max(0, int(offset or 0))
    limit = min(100, max(1, int(limit or 20)))
    items = rows[offset:offset + limit]
    return {'total': total, 'offset': offset, 'limit': limit, 'items': items}


# ── 锚点解析：原文定位的唯一入口 ────────────────────────────────
# 一段原文有两个编号，且被不同消费方混用：
#   id   = B01-00-P05     ← cards.jsonl / tags.json 的「锚点」字段存的是这个
#   锚点 = B01·前置·P05    ← 页面展示用，篇名参与
# 直接按「锚点」字段 join 会 0 命中（而且静默），所以读侧统一走 resolve_anchor()。
# 只改解析、不动产物：老数据不用重跑，以后编号怎么改也不会断。
CODE_RE = re.compile(r'^[A-Za-z0-9_-]{1,24}$')
_SEG_CACHE = {}              # code -> (stamp, rows, by_id, by_disp)
_SEG_CACHE_MAX = 8           # 最多缓存 8 本，按最近使用淘汰，避免大库吃内存
_SEG_LOCK = threading.Lock()


def is_code(code):
    """书码要拼进文件路径，只接受字母数字下划线短横，挡掉 ../ 一类注入。"""
    return bool(CODE_RE.match(str(code or '')))


def _seg_rows(code):
    """返回 (rows, by_id, by_disp)。

    按文件 mtime+size 缓存：一段原文在并发请求里只读一次盘。
    返回的行对象被多线程共享，调用方**只能读，不能改**。
    """
    path = os.path.join(E.OUT, code, 'segments.jsonl')
    try:
        st = os.stat(path)
    except OSError:
        return [], {}, {}
    stamp = (st.st_mtime_ns, st.st_size)
    with _SEG_LOCK:
        hit = _SEG_CACHE.get(code)
        if hit and hit[0] == stamp:
            _SEG_CACHE.pop(code, None)          # LRU：命中后挪到队尾
            _SEG_CACHE[code] = hit
            return hit[1], hit[2], hit[3]
    rows = read_jsonl(path)
    by_id, by_disp = {}, {}
    for i, r in enumerate(rows):
        if r.get('id'):
            by_id[r['id']] = i
        if r.get('锚点'):
            by_disp[r['锚点']] = i
    with _SEG_LOCK:
        _SEG_CACHE[code] = (stamp, rows, by_id, by_disp)
        while len(_SEG_CACHE) > _SEG_CACHE_MAX:
            _SEG_CACHE.pop(next(iter(_SEG_CACHE)))
    return rows, by_id, by_disp


def resolve_anchor(code, anchor, seg=None):
    """锚点 → 段下标。返回 (index, how)；解析不了返回 (None, '')。

    how = 'id'（段 id）或 'display'（人类可读锚点）。
    seg 可传入 _seg_rows() 的结果，批量解析时省掉重复取锁。
    """
    a = str(anchor or '').strip()
    if not a or len(a) > 200:
        return None, ''
    rows, by_id, by_disp = seg if seg else _seg_rows(code)
    i = by_id.get(a)
    if i is not None:
        return i, 'id'
    i = by_disp.get(a)
    if i is not None:
        return i, 'display'
    return None, ''


def seg_id_of(code, anchor, seg=None):
    """锚点 → 真实段 id；解析不了返回 ''。卡片/标签统一补这个字段。"""
    rows, _, _ = seg if seg else _seg_rows(code)
    i, _how = resolve_anchor(code, anchor, seg)
    return rows[i].get('id') if i is not None else ''


def get_segment_at(code, anchor, radius=2):
    """单段定位：返回目标段 + 同篇前后各 radius 段 + 篇内位置。

    前端据此跳到原文页签并在正确位置高亮，不需要拉整篇。
    """
    seg = _seg_rows(code)
    rows = seg[0]
    idx, how = resolve_anchor(code, anchor, seg)
    if idx is None:
        return None
    try:
        radius = min(5, max(0, int(radius)))
    except Exception:
        radius = 2
    target = rows[idx]
    chapter = target.get('篇')
    siblings = [i for i, r in enumerate(rows)
                if (r.get('篇序'), r.get('篇')) == (target.get('篇序'), chapter)]
    ch_pos = siblings.index(idx) if idx in siblings else 0
    lo, hi = max(0, idx - radius), min(len(rows), idx + radius + 1)
    items = []
    for i in range(lo, hi):
        r = rows[i]
        items.append({
            'seg_id': r.get('id'), '锚点': r.get('锚点'),
            '篇': r.get('篇'), '篇序': r.get('篇序'), '段': r.get('段'),
            '文本': r.get('文本'), 'hit': i == idx,
            'source_page': r.get('source_page'),
            **{key: r[key] for key in ('source_method', 'source_ocr_status',
                                       'source_layout_suspect', 'source_layout_issue') if key in r},
        })
    return {
        'anchor': str(anchor).strip(), 'found_by': how, 'seg_id': target.get('id'),
        '篇': chapter, '篇序': target.get('篇序'), '段': target.get('段'),
        'source_page': target.get('source_page'),
        **{key: target[key] for key in ('source_method', 'source_ocr_status',
                                       'source_layout_suspect', 'source_layout_issue') if key in target},
        'has_original_pdf': bool(original_pdf(code)),
        'index': idx, 'total': len(rows),
        'chapter_index': ch_pos, 'chapter_total': len(siblings),
        # 前端从这一位移继续「加载更多」，命中段才会出现在正常的篇内顺序里
        'chapter_offset': max(0, ch_pos - radius),
        'radius': radius, 'items': items,
    }


def original_pdf(code):
    if not is_code(code):
        return None
    record = load_library()['books'].get(code)
    if not record or record.get('status') == 'failed' or record.get('source_format') != 'pdf':
        return None

    def find(job_id):
        if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}', str(job_id or '')):
            return None
        path = os.path.join(UPLOADDIR, job_id, 'original.pdf')
        if os.path.islink(path) or not os.path.isfile(path):
            return None
        if os.path.commonpath((os.path.realpath(UPLOADDIR), os.path.realpath(path))) != os.path.realpath(UPLOADDIR):
            return None
        return path

    for key in ('original_job', 'last_job'):
        path = find(record.get(key))
        if path:
            return path
    for summary in list_jobs(500):
        if summary['kind'] != 'upload' or summary['title'] != record.get('book'):
            continue
        job = get_job(summary['id'])
        if job and job.get('book_code') == code and job.get('status') in ('done', 'partial'):
            path = find(job.get('original_job') or job['id'])
            if path:
                return path
    return None




# ── 五类专名 ─────────────────────────────────────────────────────
ENTITY_CATS = [('country', '国家'), ('province', '省份'), ('region', '区域/大区'), ('city', '城市'),
               ('district', '区县'), ('landmark', '道路/地标'), ('nature', '自然地理'),
               ('fossil', '化石/古人类'), ('org', '机构'), ('object', '器物'),
               ('animal', '动物'), ('plant', '植物'), ('taxon', '科属'),
               ('alias', '别名'), ('person', '人物'), ('concept', '概念/术语'),
               ('award', '奖项'), ('event', '事件'), ('dynasty', '朝代'), ('family', '家族'), ('book', '引书')]
# 「卷柏科 / 卷柏属 / 半翅目」是分类阶元，不是机构、也不是一个植物/动物实体。
# 模型常按「…科」猜成机构（像出版社/研究所），这里按后缀改判，历史数据也一起生效。
_TAXON_RE = re.compile(r'(科|属|目|纲|族)$')
# 「非洲南部 / 北部」这类方位词是地名，不是机构
_PLACE_TAIL = re.compile(r'(洲|南部|北部|东部|西部|中部|地区|一带)$')
_ORG_HINT = re.compile(r'(厂|公司|集团|大学|学院|学校|中学|小学|党校|区委|市委|县委|党委|省委|'
                       r'政府|委员会|管委会|出版社|报社|研究所|研究院|科学院|医院|银行|监狱|'
                       r'看守所|军区|法院|检察院|公安局|派出所|大院|办公大楼)')
_LANDMARK_HINT = re.compile(r'(路|街|巷|弄|大道|广场|公园|桥|车站|站|机场|码头|港口|大楼|'
                            r'大厦|宾馆|饭店|招待所|剧场|影院|纪念馆|博物馆|图书馆|寺|庙|宫|'
                            r'陵|堂|楼|馆|场|门|滩|坊|牌坊)$')
DYNASTIES = {'夏','商','周','秦','汉','西汉','东汉','三国','晋','西晋','东晋','南北朝',
             '隋','唐','五代','五代十国','宋','北宋','南宋','辽','金','西夏','元','明','清',
             '民国','先秦','春秋','战国','魏晋'}
# 同一类地名被模型切成多个条目（西伯利亚 / 西伯利亚地区 / 俄罗斯（西伯利亚地区）…），
# 不归一的话每个都指向不同的段，点哪个都像"随机跳"。
_PLACE_ALIAS = {
    '西伯利亚地区': '西伯利亚',
    '东西伯利亚': '西伯利亚',
    '俄罗斯（西伯利亚地区）': '西伯利亚',
    '俄罗斯（西伯利亚及远东地区）': '西伯利亚',
    '俄罗斯（远东和西伯利亚地区）': '西伯利亚',
}
_SEG_TEXT_CACHE = {}


def _seg_texts(code):
    """把 segments 的 id→文本 缓存起来，用于按原文实际出现次数计数。"""
    path = os.path.join(E.OUT, code, 'segments.jsonl')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    hit = _SEG_TEXT_CACHE.get(code)
    if hit and hit[0] == mtime:
        return hit[1]
    d = {}
    for r in read_jsonl(path):
        if r.get('id'):
            d[r['id']] = r.get('文本') or ''
    _SEG_TEXT_CACHE[code] = (mtime, d)
    return d
_SRC_RANK = {'GBIF': 3, '词典': 2, '模型': 1}


# 「拿不准」的第一层：能用上下文自动定的，不交给人
ENTITY_REVIEW = os.path.join(E.PLATFORM, 'config', 'entity_review.json')
_ALIAS_CTX = re.compile(r'(别名|俗名|又名|药名)')
_LATIN = re.compile(r'^[A-Za-z .×()（）&:：\-]+$')
_GENERIC_KW = ('植物', '王朝', '民族', '大类', '门类')


def _auto_other(name, before):
    """按上下文给 OTHER 一个自动归类；返回 category 或 'drop'。"""
    # 原书排版会把「俗  名」拆开，先去空白；别名常是一串（「别名 唐大黄 山大黄 土大黄」），
    # 所以看前 24 字里有没有这个标签，而不是要求紧贴名字
    if _ALIAS_CTX.search(re.sub(r'\s+', '', before or '')[-24:]):
        return 'alias'
    if _LATIN.match(name):
        return 'drop'
    if name in ('关东', '关外', '满洲', '中原', '东北少数民族') or name.endswith(_GENERIC_KW):
        return 'drop'
    return 'other'


def _review_all():
    try:
        with io.open(ENTITY_REVIEW, encoding='utf-8') as fp:
            d = json.load(fp)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _review(code):
    return _review_all().get(code) or {}


def set_entity_review(code, name, cat=None, drop=False):
    """人工确认一条：cat 归入某类，drop=true 忽略。写进配置，读时生效，不重跑模型。"""
    if not is_code(code) or not name:
        return None
    data = _review_all()
    per = data.setdefault(code, {})
    if drop:
        per[name] = {'drop': True}
    else:
        if cat not in dict(ENTITY_CATS):
            return None
        per[name] = {'cat': cat}
    os.makedirs(os.path.dirname(ENTITY_REVIEW), exist_ok=True)
    tmp = ENTITY_REVIEW + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, ENTITY_REVIEW)
    return per[name]


def _entity_rows(code):
    from entities import explicit_name_rows, merge_explicit_names

    rows = read_jsonl(os.path.join(E.OUT, code, 'entities.jsonl'))
    book = E.book_json(code)
    explicit = explicit_name_rows(book.get('book') or '', _seg_rows(code)[0])
    return merge_explicit_names(rows, explicit)


def review_pending(code, limit=200, q='', offset=0):
    """待确认：OTHER 里自动规则也定不了的，且人工还没确认过的。"""
    if not is_code(code):
        return {'count': 0, 'items': []}
    from source_names import review_for, reviews, source_revision

    rows = _entity_rows(code)
    segs = _seg_texts(code)
    ov = _review(code)
    saved = reviews()
    source_version = E.book_json(code).get('source_version')
    q = str(q or '').strip().casefold()[:100]
    ppl = {x.get('人物') for x in read_jsonl(os.path.join(E.OUT, code, 'people.jsonl')) if x.get('人物')}
    agg = {}
    for r in rows:
        name, c = r.get('name'), r.get('cat')
        if not name or c != 'other' or (q and q not in name.casefold()):
            continue
        if name in ppl:
            continue
        sid = r.get('seg') or ''
        t = segs.get(sid) or ''
        i = t.find(name)
        before = t[max(0, i - 24):i] if i >= 0 else ''
        auto = _auto_other(name, before)
        if auto != 'other':
            continue
        if name in ov or not t or (sid in (saved.get(code) or {}) and
                review_for(saved, code, sid, source_revision(source_version, t), name)):
            continue
        it = agg.get(name)
        if not it:
            agg[name] = {'name': name, 'count': 1, 'seg': sid,
                         'snippet': t[max(0, i - 30):i + len(name) + 40] if i >= 0 else t[:70]}
        else:
            it['count'] += 1
    items = sorted(agg.values(), key=lambda x: (-x['count'], x['name']))
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))
    return {'count': len(items), 'items': items[offset:offset + limit], 'offset': offset, 'limit': limit}


def review_pending_all():
    """全库待确认汇总：工作台用。"""
    out = []
    lib = read_json(LIBFILE, {}) or {}
    records = lib.get('books') if isinstance(lib, dict) else (lib or [])
    if isinstance(records, dict):
        records = list(records.values())
    for rec in (records or []):
        if isinstance(rec, str):        # 兼容只存了编号的旧结构
            rec = {'code': rec}
        if not isinstance(rec, dict):
            continue
        code = rec.get('code')
        if not code:
            continue
        try:
            d = review_pending(code, limit=500)
        except Exception:
            continue
        if d.get('count'):
            out.append({'code': code, 'book': rec.get('book') or code, 'count': d['count']})
    return {'total': sum(x['count'] for x in out), 'books': out}


def get_entities(code, cat='', limit=80):
    """读 out/<code>/entities.jsonl，按 (名, 类) 聚合。

    分类统一走 entity_classify（规则+地理词典+上下文），不再在这里写书-specific 规则。
    """
    if not is_code(code):
        return {'counts': {}, 'items': []}
    rows = _entity_rows(code)
    segs = _seg_texts(code)
    ppl = set()
    try:
        ppl = {x.get('人物') for x in read_jsonl(os.path.join(E.OUT, code, 'people.jsonl')) if x.get('人物')}
    except Exception:
        pass
    prepared = []
    for r in rows:
        name, c = r.get('name'), r.get('cat')
        if not name or not c:
            continue
        sid = r.get('seg') or ''
        ctx = segs.get(sid) or ''
        c2 = c if r.get('name_evidence') else EC.classify(name, ctx, hint=c, known_people=ppl)[0]
        prepared.append((r, name, c2))

    # 同名只留一个类别：按出现次数多数，票数相同按优先级。
    # 这样“中国”不会同时出现国家/人物/概念三个条目。
    from collections import Counter, defaultdict
    votes = defaultdict(Counter)
    for r, n, c in prepared:
        if not r.get('name_evidence'):
            votes[n][c] += 1
    PRI = {k: i for i, k in enumerate(
        ('country', 'province', 'region', 'city', 'district', 'landmark', 'nature',
         'fossil', 'org', 'person', 'concept', 'award', 'event', 'dynasty', 'family',
         'object', 'animal', 'plant', 'taxon', 'alias', 'other'))}
    canon = {n: max(cnt.items(), key=lambda kv: (kv[1], -PRI.get(kv[0], 99)))[0]
             for n, cnt in votes.items()}
    prepared = [(r, n, c if r.get('name_evidence') else canon[n]) for r, n, c in prepared]

    places = {n for _r, n, c in prepared if c == 'place'}

    def _norm_place(n):
        n = _PLACE_ALIAS.get(n, n)
        if n.endswith('地区') and n[:-2] in places:
            n = n[:-2]
        return n

    ov = _review(code)
    agg = {}
    for r, name, c in prepared:
        if c == 'place':
            name = _norm_place(name)
        sid = r.get('seg') or ''
        if c == 'other':
            t = segs.get(sid) or ''
            i = t.find(name)
            auto = _auto_other(name, t[max(0, i - 24):i] if i >= 0 else '')
            if auto == 'drop':
                continue
            c = auto
        o = ov.get(name)
        if o:
            if o.get('drop'):
                continue
            if o.get('cat'):
                c = o['cat']
        k = (name, c)
        n = (segs.get(r.get('seg') or '') or '').count(name) or 1
        it = agg.get(k)
        if not it:
            agg[k] = {'name': name, 'cat': c, 'count': n, 'seg': r.get('seg') or '',
                      'src': r.get('src') or '模型', 'sci': r.get('sci') or ''}
        else:
            it['count'] += n
            if _SRC_RANK.get(r.get('src'), 0) > _SRC_RANK.get(it['src'], 0):
                it['src'] = r.get('src')
                it['sci'] = r.get('sci') or it['sci']
    counts = {c: 0 for c, _ in ENTITY_CATS}
    for (_, c) in agg:
        if c in counts:            # OTHER 不进页面统计（拿不准的候选，单独留在数据里）
            counts[c] += 1
    # 指定类目时允许一次取全（专名面板「还有 N 个」要能真展开）；不指定时维持每类 100 上限
    # 专名页要能一次取全（每类最多 2000），默认仍是每类 30
    lim = max(1, min(2000, int(limit or 30)))
    if cat:
        items = sorted([v for v in agg.values() if v['cat'] == cat],
                       key=lambda x: (-x['count'], x['name']))[:lim]
    else:
        # 每类各取前 lim 个，避免地名把动植物挤掉
        items = []
        for c, _ in ENTITY_CATS:
            items += sorted([v for v in agg.values() if v['cat'] == c],
                            key=lambda x: (-x['count'], x['name']))[:lim]
    return {'counts': counts, 'items': items}


def get_entity_occurrences(code, name, limit=30):
    """某个专名在全书出现过的段（带上下文），用于地名/机构的「出现位置」列表。"""
    if not is_code(code) or not name:
        return {'total': 0, 'items': []}
    rows = _entity_rows(code)
    segs = _seg_texts(code)
    places = {r.get('name') for r in rows if r.get('cat') == 'place'}

    def _np(n):
        n = _PLACE_ALIAS.get(n, n)
        if n.endswith('地区') and n[:-2] in places:
            n = n[:-2]
        return n

    seen, items = set(), []
    for r in rows:
        rn = r.get('name') or ''
        if (rn if r.get('cat') != 'place' else _np(rn)) != name:
            continue
        sid = r.get('seg') or ''
        if not sid or sid in seen:
            continue
        t = segs.get(sid) or ''
        i = t.find(name)
        if i < 0:
            continue
        seen.add(sid)
        items.append({'seg': sid, 'chapter': r.get('book') or '',
                      'snippet': t[max(0, i - 28):i + len(name) + 46]})
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 30
    return {'total': len(items), 'items': items[:max(1, min(100, limit))]}


def entity_counts(code):
    try:
        return get_entities(code, limit=1)['counts']
    except Exception:
        return {}


# ── 热点匹配（应用中心 · 营销） ─────────────────────────────────
# 只用已有标签与原文做召回，不依赖模型：
#   1) 热点文本里出现的标签名 → 按 idf 加权
#   2) 书名、人物名直接命中 → 加权
#   3) 原文段落包含关键词 → 计数，并给出可引用段落
# 输出候选书 + 命中理由，供人挑；生成文案留给下一步。

def hotspot_match(text, limit=10):
    text = (text or '').strip()
    if not text:
        return {'keywords': [], 'books': []}
    tags = tags_index() or {}

    # 候选词：标签命中 + 书名/人物命中 + 热点自身的词
    tag_terms = set()
    for code, b in tags.items():
        for lv in ('L7', 'L6', 'L4', 'L5', 'L3'):
            for it in (b.get(lv) or []):
                t = (it.get('标签') or '').strip()
                if len(t) >= 2 and t in text:
                    tag_terms.add(t)
    tokens = set(t for t in re.split(r'[\s,，。；;、:：！!？?"“”()（）]+', text) if 2 <= len(t) <= 12)
    terms = tag_terms | tokens
    if not terms:
        return {'keywords': [], 'books': []}

    codes = list(tags.keys()) or [r['code'] for r in library_rows()]
    rows = []
    for code in codes:
        b = E.book_json(code) or {}
        title = (b.get('book') or code).strip()
        people = [p.get('人物') or '' for p in read_jsonl(os.path.join(E.OUT, code, 'people.jsonl'))]

        kw_hit = [t for t in terms if t == title or (len(t) >= 2 and t in title)]
        pp_hit = [n for n in people if n and n in text]
        seg_hit, seg_count = [], 0
        for r in _seg_rows(code)[0]:
            txt = r.get('文本') or ''
            got = [t for t in terms if t in txt]
            if got:
                seg_count += 1
                if len(seg_hit) < 8:
                    seg_hit.append({'seg_id': r.get('id'), '锚点': r.get('锚点'),
                                    '篇': r.get('篇'), '段': r.get('段'),
                                    'hit': got[:3],
                                    '文本': txt[:160]})
                if seg_count >= 60:
                    break

        score = 0.0
        if title and title in text:
            score += 60
        score += 8.0 * len(set(kw_hit))
        score += 6.0 * min(len(pp_hit), 3)
        score += min(seg_count, 20) * 1.5
        if score <= 0:
            continue
        rows.append({
            'code': code, 'title': title,
            'author': b.get('author') or '', 'publisher': b.get('publisher') or '',
            'prototype': b.get('原型') or '', 'prototype_name': b.get('原型名') or '',
            'score': score, 'matched_tags': kw_hit[:6], 'matched_people': pp_hit[:5],
            'segments': seg_hit[:3], 'seg_hit_count': seg_count,
        })

    rows.sort(key=lambda r: -r['score'])
    rows = rows[:limit]
    top = rows[0]['score'] if rows else 1.0
    for r in rows:
        r['score'] = round(min(100.0, 100.0 * r['score'] / top), 1)
    return {'keywords': sorted(terms)[:15], 'books': rows}


# ── 操作记录 ─────────────────────────────────────────────────────
def append_op(code, event, detail=None):
    row = {'time': now(), 'code': code, 'event': event, 'detail': detail or {}}
    os.makedirs(ARCHIVEDIR, exist_ok=True)
    with _lock('ops'):
        with io.open(os.path.join(ARCHIVEDIR, code + '.jsonl'), 'a', encoding='utf-8') as fp:
            fp.write(json.dumps(row, ensure_ascii=False) + '\n')
        with io.open(OPSFILE, 'a', encoding='utf-8') as fp:
            fp.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


FLAGFILE = os.path.join(DATA, 'marketing_flags.jsonl')
EDITORFILE = os.path.join(DATA, 'editor_flags.jsonl')
_EDITOR_KEYS = ('主旨', '引用判定', '用途')


def marketing_flags(code=None):
    """营销素材的人工采纳记录：id → adopt / reject。最后一条为准。"""
    out = {}
    for r in read_jsonl(FLAGFILE):
        c, i = r.get('code'), r.get('id')
        if not c or not i:
            continue
        if code and c != code:
            continue
        out.setdefault(c, {})[i] = r.get('status') or ''
    return out.get(code, {}) if code else out


def set_marketing_flag(code, item_id, status):
    code = (code or '').strip()
    item_id = (item_id or '').strip()
    if not code or not item_id:
        raise ValueError('code / id 必填')
    status = (status or '').strip()
    if status not in ('adopt', 'reject', ''):
        raise ValueError('status 只能是 adopt / reject / 空')
    rec = {'code': code, 'id': item_id, 'status': status, 'ts': now()}
    with io.open(FLAGFILE, 'a', encoding='utf-8') as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def set_marketing_flags(code, ids, status):
    """批量记录采纳 / 剔除：一次请求写多行，避免前端发几十个请求。"""
    code = (code or '').strip()
    ids = [str(x).strip() for x in (ids or []) if str(x or '').strip()]
    status = (status or '').strip()
    if not code or not ids:
        raise ValueError('code / ids 必填')
    if status not in ('adopt', 'reject', ''):
        raise ValueError('status 只能是 adopt / reject / 空')
    ts = now()
    with io.open(FLAGFILE, 'a', encoding='utf-8') as fp:
        for i in ids:
            fp.write(json.dumps({'code': code, 'id': i, 'status': status, 'ts': ts},
                                ensure_ascii=False) + '\n')
    return len(ids)



def editor_flags(code=None):
    """编校台的人工填写：每章一句话主旨、每条引文是/不是引用、引它做什么。最后一条为准。"""
    out = {}
    for r in read_jsonl(EDITORFILE):
        c, i = r.get('code'), r.get('id')
        if not c or not i:
            continue
        if code and c != code:
            continue
        cur = out.setdefault(c, {}).setdefault(i, {})
        for k in _EDITOR_KEYS:
            if k in r:
                cur[k] = r.get(k) or ''
    return out.get(code, {}) if code else out


def set_editor_flag(code, cid, fields):
    """写一条人工填写。只写传进来的字段，没传的保持原值。"""
    code, cid = (code or '').strip(), (cid or '').strip()
    if not is_code(code):
        raise ValueError('书码不对')
    if not cid:
        raise ValueError('id 必填')
    current = next((r for r in read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl')) if r.get('id') == cid), None)
    if not current:
        raise ValueError('条目不存在或已更新，请刷新后重试')
    rec = {'code': code, 'id': cid, 'ts': now()}
    for k in _EDITOR_KEYS:
        if k not in (fields or {}):
            continue
        v = str(fields[k] or '')[:400]
        if k == '引用判定' and v not in ('', '引用', '非引用'):
            raise ValueError('引用判定 只能是 引用 / 非引用 / 空')
        rec[k] = v
    if len(rec) <= 3:
        raise ValueError('没有要写的字段')
    with io.open(EDITORFILE, 'a', encoding='utf-8') as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def editor_payload(code):
    """编校台：一本书里机器做不了、必须人过的两件事——每章一句话主旨、每条引文的作用。"""
    if not is_code(code):
        return {}
    rec = get_record(code) or {}
    flags = editor_flags(code) or {}
    understanding = read_json(os.path.join(E.OUT, code, 'understanding.json'), {}) or {}
    suggestions = {r.get('篇'): r.get('summary') or '' for r in understanding.get('summaries', [])}
    chapters, cites = [], []
    for r in read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl')):
        if _is_dup_card(r):
            continue
        t = r.get('类型') or ''
        f = r.get('字段') or {}
        fl = flags.get(r.get('id')) or {}
        if t in ('篇目候选', '情节候选'):
            chapters.append({
                'id': r.get('id'), '序': f.get('篇序'),
                '名': f.get('篇名') or f.get('回目') or '',
                '字数': f.get('字数'), '锚点': r.get('锚点'),
                '主旨': fl.get('主旨') or '',
                '建议': suggestions.get(f.get('篇名') or f.get('回目')) or '',
            })
        elif t == '引书候选':
            c = _cite_stats(code, f.get('书名') or '') or {}
            cites.append({
                'id': r.get('id'), '书名': f.get('书名') or '',
                'body': c.get('body') or 0, 'front': c.get('front') or 0,
                'quotes': c.get('quotes') or [], 'front_quotes': c.get('front_quotes') or [],
                '判定': fl.get('引用判定') or '', '用途': fl.get('用途') or '',
            })
    chapters.sort(key=lambda x: (x['序'] is None, x['序'] or 0, x['名']))
    cites.sort(key=lambda x: (-x['body'], -x['front'], x['书名']))
    return {'code': code, 'book': rec.get('book') or '',
            'chapters': chapters, 'cites': cites,
            'stats': {'chapters': len(chapters),
                      'chapters_done': sum(1 for x in chapters if x['主旨'].strip()),
                      'cites': len(cites),
                      'cites_checked': sum(1 for x in cites if x['判定']),
                      'cites_yes': sum(1 for x in cites if x['判定'] == '引用'),
                      'front_only': sum(1 for x in cites if not x['body'])}}


def editor_pending():
    """还有多少条要人过：没写主旨的篇目 + 没核对的引文。给导航徽标和按书排序用。"""
    flags = editor_flags() or {}
    rows = []
    for row0 in library_rows():
        code = row0['code']
        fl = flags.get(code) or {}
        ch = ci = all_ch = all_ci = 0
        for r in read_jsonl(os.path.join(E.OUT, code, 'cards.jsonl')):
            if _is_dup_card(r):
                continue
            t = r.get('类型') or ''
            if t in ('篇目候选', '情节候选'):
                all_ch += 1
                if not (fl.get(r.get('id')) or {}).get('主旨'):
                    ch += 1
            elif t == '引书候选':
                all_ci += 1
                if not (fl.get(r.get('id')) or {}).get('引用判定'):
                    ci += 1
        if all_ch or all_ci:
            rows.append({'code': code, 'book': row0['book'],
                         'chapters': ch, 'cites': ci, 'total': ch + ci,
                         'all_chapters': all_ch, 'all_cites': all_ci,
                         'done': (all_ch + all_ci) - (ch + ci)})
    rows.sort(key=lambda x: (-x['total'], x['book']))
    return {'chapters': sum(x['chapters'] for x in rows),
            'cites': sum(x['cites'] for x in rows),
            'total': sum(x['total'] for x in rows),
            'all': sum(x['all_chapters'] + x['all_cites'] for x in rows),
            'done': sum(x['done'] for x in rows), 'books': rows}



def book_report(code):
    """解析报告：由本书的解析记录和产物生成。"""
    if not is_code(code):
        return None
    base = os.path.join(E.OUT, code)
    b = E.book_json(code) or {}
    rec = get_record(code) or {}
    pub = read_json(os.path.join(base, 'publication.json'), {}) or {}
    pr = read_json(os.path.join(base, 'page_roles.json'), {}) or {}
    und = read_json(os.path.join(base, 'understanding.json'), {}) or {}
    mk = read_json(os.path.join(base, 'marketing.json'), {}) or {}
    cards = read_jsonl(os.path.join(base, 'cards.jsonl'))
    counts = get_entities(code, limit=1).get('counts', {})

    items = pub.get('items') or {}
    ident_found = [{'key': k, 'name': v.get('name') or k} for k, v in items.items()
                   if (v or {}).get('status') == 'found']
    ident_miss = [{'key': k, 'name': v.get('name') or k} for k, v in items.items()
                  if (v or {}).get('status') != 'found']

    roles = pr.get('roles') or []
    role_found = [r.get('name') for r in roles if r.get('status') == 'found']
    role_miss = [r.get('name') for r in roles if r.get('status') != 'found']
    role_unavailable = [r.get('name') for r in roles
                        if r.get('status') != 'found' and
                        ('未检出' in (r.get('note') or '') or '无文字' in (r.get('note') or ''))]

    by_type, by_tier = {}, {}
    for r in cards:
        t = r.get('类型') or '未分类'
        by_type[t] = by_type.get(t, 0) + 1
        q = r.get('资产性质') or ''
        if q == '仅为定位器':
            q = '仅定位器'
        by_tier[q] = by_tier.get(q, 0) + 1

    quotes = und.get('quotes') or []
    themes = und.get('themes') or []
    mk_items = mk.get('items') or mk.get('drafts') or {}
    if isinstance(mk_items, dict):
        mk_count = len(mk_items)
    elif isinstance(mk_items, list):
        mk_count = len(mk_items)
    else:
        mk_count = 0
    stats = und.get('stats') or {}
    pass_rate = ((stats.get('quotes') or {}).get('pass_rate'))
    cip_seg = ((pub.get('source') or {}).get('cip_seg') or '')
    ocr_tried = os.path.exists(os.path.join(base, 'ocr', 'pages.jsonl'))
    if cip_seg:
        identity_note = ''
    elif ocr_tried:
        identity_note = ('本书未检出可读版权页（CIP）；已 OCR 前 10 + 后 10 页仍未发现版权页，'
                         '%d 项不可抽，不是抽取失败。' % len(ident_miss))
    else:
        identity_note = ('本书未检出可读版权页（CIP）；%d 项不可抽，需 OCR 或人工补，'
                         '不是抽取失败。' % len(ident_miss))
    identity_unavailable = len(ident_miss) if not cip_seg else None
    identity_failed = 0 if not cip_seg else None
    structure_note = '缺项分两类：封面/版权页/书名页无文字层；后记/附录/索引等是书里没有该结构。不是统一抽取失败。'
    has_understanding = os.path.exists(os.path.join(base, 'understanding.json'))

    report = {
        'code': code,
        'book': rec.get('book') or b.get('书名') or code,
        'has_original_pdf': bool(original_pdf(code)),
        'identity': {'total': len(items), 'found': ident_found, 'missing': ident_miss,
                     'cip_found': bool(cip_seg), 'note': identity_note,
                     'unavailable': identity_unavailable, 'failed': identity_failed},
        'structure': {'total': len(roles), 'found': role_found, 'missing': role_miss,
                      'note': structure_note, 'unavailable': len(role_unavailable),
                      'failed': 0},
        'content': {
            'total': len(cards), 'by_type': by_type, 'by_tier': by_tier,
            'entity_counts': counts,
            'entity_total': sum(counts.values()) if counts else 0,
            'note': b.get('候选卡构成') or '',
        },
        'usage': {
            'quotes': len(quotes), 'themes': len(themes),
            'marketing': mk_count, 'has_marketing': bool(mk_count),
            'has_understanding': has_understanding,
        },
        'trust': {
            'prototype': b.get('原型') or rec.get('prototype') or '',
            'confidence': b.get('置信') or rec.get('confidence') or '',
            'stability': b.get('稳定性'),
            'pending': (rec.get('status') == 'pending'),
            'reject': bool(b.get('拒判')),
            'pass_rate': pass_rate,
        },
    }
    if type(rec.get('source_pages')) is int and rec['source_pages'] > 0:
        report['source_pages'] = rec['source_pages']
    # 缺少逐页记录的旧书不能当成“检查后没有问题”；新解析的空字典保留。
    if isinstance(rec.get('source_page_issues'), dict):
        issues = rec['source_page_issues']
        report['source_page_issues'] = {
            key: sorted({page for page in issues[key] if type(page) is int and page > 0})
            for key in ('blank', 'no_text', 'review', 'failed', 'unavailable',
                        'layout_review', 'non_body')
            if isinstance(issues.get(key), list)
        }
    return report


def get_ops(code):
    rows = read_jsonl(os.path.join(ARCHIVEDIR, code + '.jsonl'))
    return rows[-50:]


def list_ops(limit=100):
    rows = read_jsonl(OPSFILE)
    return rows[-limit:][::-1]


# ── 任务 ─────────────────────────────────────────────────────────
def job_path(job_id):
    return os.path.join(JOBDIR, job_id + '.json')


def new_job(kind, payload, steps=None):
    jid = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(3)
    job = {
        'id': jid,
        'kind': kind,
        'status': 'queued',
        'created_at': now(),
        'started_at': None,
        'finished_at': None,
        'progress': 0,
        'steps': steps or [],
        'log': [],
        'error': '',
    }
    job.update(payload or {})
    write_json(job_path(jid), job)
    return job


def job_result_view(job):
    # Reflect known historical quality failures without rewriting history.
    if not job or job.get('status') != 'done':
        return job
    failures = [str(line) for line in job.get('log', []) if ('⚠' in str(line) or str(line).startswith('!')) and '失败' in str(line)]
    if not failures:
        return job
    result = dict(job)
    result['status'] = 'partial'
    result['warnings'] = job.get('warnings') or failures
    result['historical_quality_warning'] = True
    result['steps'] = [dict(step, status='failed', detail='历史日志记录了校验失败，请复核产物')
                       if step.get('key') == 'audit' and any('质检' in s for s in failures)
                       else dict(step) for step in job.get('steps', [])]
    return result


def get_job(job_id):
    return job_result_view(read_json(job_path(job_id), None))


def update_job(job_id, **fields):
    with _lock('job-' + job_id):
        job = get_job(job_id)
        if not job:
            return None
        job.update(fields)
        write_json(job_path(job_id), job)
        return job


def append_job_log(job_id, text, limit=120):
    text = str(text or '').strip()
    if not text:
        return
    with _lock('job-' + job_id):
        job = get_job(job_id)
        if not job:
            return
        log = job.get('log') or []
        for line in text.splitlines():
            line = line.rstrip()
            if line:
                log.append(line)
        job['log'] = log[-limit:]
        write_json(job_path(job_id), job)


def delete_job(job_id):
    """删一条任务记录。只删历史，不动图书、产物、上传原件。

    运行中的任务不给删：执行器还在往这条记录里写进度，删了会留下半截状态。
    """
    job = get_job(job_id)
    if not job:
        raise ValueError('任务不存在')
    if job.get('status') in ('queued', 'running'):
        raise ValueError('任务还在运行，结束或失败后再删')
    with _lock('job-' + job_id):
        for path in (job_path(job_id), os.path.join(JOBDIR, job_id + '.log')):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
    return True


def clear_finished_jobs():
    """清空已完成 / 已失败的任务记录，返回删除条数。"""
    n = 0
    for job in list_jobs(limit=5000):
        if job.get('status') in ('done', 'partial', 'failed'):
            try:
                delete_job(job['id'])
                n += 1
            except Exception:
                pass
    return n


def list_jobs(limit=30):
    items = []
    try:
        names = [n for n in os.listdir(JOBDIR) if n.endswith('.json')]
    except Exception:
        return []
    for n in sorted(names, reverse=True)[:limit]:
        j = job_result_view(read_json(os.path.join(JOBDIR, n), None))
        if j:
            items.append({k: j.get(k) for k in
                          ('id', 'kind', 'status', 'progress', 'created_at',
                           'finished_at', 'title', 'error')})
    return items


def recover_jobs(on_interrupted_upload=None):
    """服务重启后，把卡在 running/queued 的任务标失败，避免 UI 永远转圈。"""
    for j in list_jobs(limit=200):
        if j.get('status') in ('queued', 'running'):
            if j.get('kind') == 'upload' and on_interrupted_upload and on_interrupted_upload(get_job(j['id']) or {}):
                continue
            update_job(j['id'], status='failed', finished_at=now(),
                       error='处理因服务重启中断。可以先查看任务有没有「继续处理」或「用原文件重试」。')
    # 回收站里的「恢复中」标记也要清：进程被杀时标记会留着，
    # 之后这条记录永远恢复不了，只能手工改 trash.json。
    try:
        jobs = {j['id']: j for j in list_jobs(limit=500)}
        t = load_trash()
        changed = False
        for r in t['items']:
            jid = r.get('restoring')
            if jid and jobs.get(jid, {}).get('status') not in ('queued', 'running'):
                r.pop('restoring', None)
                changed = True
        if changed:
            save_trash(t)
    except Exception:
        pass


# ── 回收站 ───────────────────────────────────────────────────────
def load_trash():
    t = read_json(TRASHFILE, None)
    if not isinstance(t, dict) or not isinstance(t.get('items'), list):
        t = {'version': 1, 'items': []}
    return t


def save_trash(t):
    write_json(TRASHFILE, t)


def add_trash(record):
    with _lock('trash'):
        t = load_trash()
        t['items'].append(record)
        save_trash(t)
    return record


def list_trash():
    return list(reversed(load_trash()['items']))


def get_trash(trash_id):
    for r in load_trash()['items']:
        if r.get('id') == trash_id:
            return r
    return None


def set_trash_flag(trash_id, key, value):
    """给回收站记录打个临时标记（如 restoring=job_id），防止重复恢复。"""
    with _lock('trash'):
        t = load_trash()
        for r in t['items']:
            if r.get('id') == trash_id:
                if value in (None, ''):
                    r.pop(key, None)
                else:
                    r[key] = value
                save_trash(t)
                return True
    return False


def remove_trash(trash_id):
    with _lock('trash'):
        t = load_trash()
        before = len(t['items'])
        t['items'] = [r for r in t['items'] if r.get('id') != trash_id]
        save_trash(t)
        return before != len(t['items'])


# ── 删除 ─────────────────────────────────────────────────────────
def delete_book(code, confirm_title):
    """软删除：raw 进 书库分类/退库/，out 进 platform/out/.trash/，可恢复。"""
    rec = get_record(code)
    if not rec:
        raise ValueError('书不存在')
    title = rec.get('book') or code
    if (confirm_title or '').strip() != title:
        raise ValueError('书名确认不一致，未删除')
    # 还有任务在跑（改分类 / 恢复）就别删：执行器会在删除之后把产物和记录写回来，
    # 书会“复活”成一份失败记录，或者留下没有记录的 out 目录。
    busy = [j for j in list_jobs(300)
            if j.get('status') in ('queued', 'running')
            and (j.get('code') == code or j.get('title') == title)]
    if busy:
        kinds = '、'.join(sorted({j.get('kind') or '任务' for j in busy}))
        raise ValueError('这本书还有任务在跑（%s），等它结束再删' % kinds)
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    trash_id = '%s-%s' % (code, ts)
    raw_path = os.path.join(E.RAW, title + '.txt')
    out_path = os.path.join(E.OUT, code)
    dest_raw = os.path.join(E.TRASH_DIR, '%s__%s.txt' % (safe_title(title), ts))
    layout_path = os.path.splitext(raw_path)[0] + '.layout.jsonl'
    dest_layout = os.path.join(E.TRASH_DIR, '%s__%s.layout.jsonl' % (safe_title(title), ts))
    dest_out = os.path.join(E.OUT, '.trash', '%s__%s' % (code, ts))
    moved_raw = moved_out = False
    with _lock('library'):
        lib = load_library()
        if code not in lib['books']:
            raise ValueError('书不存在（可能已被另一个请求删除）')
        if os.path.exists(raw_path):
            shutil.move(raw_path, dest_raw)
            moved_raw = True
        moved_layout = False
        if os.path.exists(layout_path):
            shutil.move(layout_path, dest_layout)
            moved_layout = True
        if os.path.isdir(out_path):
            os.makedirs(os.path.dirname(dest_out), exist_ok=True)
            shutil.move(out_path, dest_out)
            moved_out = True
        books = E.books_json()
        books = [b for b in books if b.get('code') != code]
        E.write_json(os.path.join(E.OUT, 'books.json'), books)
        lib['books'].pop(code, None)
        save_library(lib)
    trash_record = {
        'id': trash_id, 'code': code, 'book': title, 'time': now(),
        'raw': dest_raw if moved_raw else '',
        'layout': dest_layout if moved_layout else '',
        'out': dest_out if moved_out else '',
        'record': rec,
    }
    add_trash(trash_record)
    append_op(code, 'delete', {'trash_id': trash_id,
                               'raw_moved': moved_raw, 'out_moved': moved_out})
    rebuild = E.rebuild_assets(include_checks=False)
    # 只回传脚本与返回码，别把整段 stdout 塞进 HTTP 响应。
    rebuild = [{'script': x.get('script'), 'returncode': x.get('returncode')}
               for x in rebuild]
    return {'trash_id': trash_id, 'rebuild': rebuild}


# ── 检索 ─────────────────────────────────────────────────────────
def _clip(s, n=300):
    s = re.sub(r'\s+', ' ', str(s or '')).strip()
    return s[:n] + ('…' if len(s) > n else '')


def _search_excerpt(text, query, length=160):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    match = re.search(re.escape(query), text, re.IGNORECASE)
    if not match:
        return _clip(text, length)
    lo = max(0, match.start() - length // 3)
    hi = min(len(text), max(lo + length, match.end()))
    return ('…' if lo else '') + text[lo:hi] + ('…' if hi < len(text) else '')


def search(q, scope='all', limit=30, offset=0):
    q = (q or '').strip()
    groups = ('books', 'tags', 'cards', 'segments', 'assets')
    out = {'q': q, **{key: [] for key in groups}, 'totals': dict.fromkeys(groups, 0)}
    if not q:
        return out
    ql = q.lower()
    limit = min(100, max(1, int(limit or 30)))
    offset = max(0, int(offset or 0))
    rows = library_rows()
    by_title = {r['book']: r['code'] for r in rows}
    by_code = {r['code']: r['book'] for r in rows}

    def add(group, value):
        count = out['totals'][group]
        if offset <= count < offset + limit:
            out[group].append(value)
        out['totals'][group] = count + 1

    if scope in ('all', 'books'):
        for r in rows:
            hay = ' '.join([r['book'], r['author'], r['publisher'],
                            r['prototype'] or '', r['prototype_name'] or '']).lower()
            if ql in hay:
                add('books', r)
    if scope in ('all', 'tags'):
        for code, b in tags_index().items():
            title = by_code.get(code)
            if not title:
                continue
            for lv in ('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7'):
                for it in b.get(lv, []) or []:
                    tag = it.get('标签') or ''
                    if ql in str(tag).lower() or ql in str(it.get('原文') or '').lower():
                        add('tags', {
                            'code': code, 'book': title, 'layer': lv,
                            'tag': tag, 'source': it.get('来源') or '',
                            'anchor': it.get('锚点') or '',
                            '原文': _search_excerpt(it.get('原文'), q),
                        })
    if scope in ('all', 'cards'):
        path = os.path.join(E.LIB, 'cards_candidate.jsonl')
        for r in iter_jsonl(path):
            hay = ' '.join([str(r.get('原文') or ''), str(r.get('类型') or ''),
                            str(r.get('词条') or ''),
                            json.dumps(r.get('字段') or {}, ensure_ascii=False)]).lower()
            if ql in hay and r.get('码') in by_code:
                add('cards', {
                    'id': r.get('id'), 'code': r.get('码'), 'book': r.get('书'),
                    'type': r.get('类型'), 'tier': r.get('资产性质'),
                    'anchor': r.get('锚点'), '原文': _search_excerpt(r.get('原文'), q),
                })
    if scope in ('all', 'segments'):
        path = os.path.join(E.LIB, 'segments.jsonl')
        for r in iter_jsonl(path):
            book = r.get('书')
            code = r.get('码') or by_title.get(book)
            if code in by_code and ql in str(r.get('文本') or '').lower():
                add('segments', {
                    'code': code, 'book': by_code[code],
                    'anchor': r.get('id') or r.get('锚点'), '篇': r.get('篇'),
                    '原文': _search_excerpt(r.get('文本'), q),
                })
    if scope in ('all', 'assets'):
        import assets_service
        found = assets_service.list_assets(q=q, limit=limit, offset=offset)
        out['assets'] = [dict(a, excerpt=_search_excerpt(a.get('text'), q))
                         for a in found.get('items', [])]
        out['totals']['assets'] = found['total']
    return out


# ── 状态 ─────────────────────────────────────────────────────────
def health():
    rows = library_rows()
    return {'ok': True, 'books': len(rows), 'jobs': len(list_jobs(200)),
            'time': now(), 'root': E.ROOT}
