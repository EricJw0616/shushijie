# -*- coding: utf-8 -*-
"""Bounded, source-linked context for any book asset; never a fact-check claim."""
import copy
import math
import os
import re
from collections import Counter

import store
import engine_bridge as E


_MISSING_NUMBER = [
    r'(?:仅|历时|长达|超过|耗时|时隔)\s*(?:天|个月|小时|分钟|年)(?=[，。；、\s的后就即]|$)',
    r'(?:将|捐出|捐赠|捐了|捐献|投入|花费|耗资|金额为)\s*(?:万元|亿元|元)(?=[，。；、\s存给用的]|$)',
    r'(?:培养了|培育了|任教了|共有|共计|包括了)\s*(?:名|位|个)(?=[\u3400-\u9fff])',
    r'(?:获|获得)\s*年度(?:国家|国际|省|市)',
]
_NUMBER_RE = re.compile('|'.join(_MISSING_NUMBER))
_NOISE_RE = re.compile(r'(?:生卒年[：:]\s*[—\-～~]+|年月日[，。]|(?<!\d)年，(?:已经)?岁|\\\\|★)')


def quality_warnings(text, context=False):
    """Conservative text-integrity signals, separate from historical truth."""
    text = str(text or '')
    found = []
    hit = _NUMBER_RE.search(text)
    if hit:
        found.append({'code': 'missing_number', 'severity': 'warning' if context else 'error',
                      'message': '疑似缺失数字：' + hit.group(0) + '；请回查底本，不宜直接补数'})
    if context and _NOISE_RE.search(text):
        found.append({'code': 'source_noise', 'severity': 'warning',
                      'message': '原文片段可能含缺失信息或版面残留；定位匹配不等于事实已核验'})
    return found


def _terms(text):
    chunks = re.findall(r'[\u3400-\u9fff]+|[A-Za-z0-9]+', str(text or '').casefold())
    out = []
    for chunk in chunks:
        if re.search(r'[\u3400-\u9fff]', chunk):
            out.extend(chunk[i:i + 2] for i in range(max(0, len(chunk) - 1)))
        else:
            out.append(chunk)
    return set(out)


def _window(text, query, limit, preferred=''):
    if len(text) <= limit:
        return text
    at = text.find(preferred) if preferred else -1
    if at < 0:
        # Pick a bounded window with most query overlap, rather than always the profile header.
        step = max(100, limit // 2)
        choices = [(len(_terms(text[i:i + limit]) & query), -i, i)
                   for i in range(0, len(text), step)]
        at = max(choices)[2]
    else:
        at = max(0, at - 60)
    at = min(at, max(0, len(text) - limit))
    return text[at:at + limit]


def enrich_asset(asset, max_chars=1600, segments=None):
    """Return a new asset object with exact bounded excerpts and integrity warnings.

    The original asset, its evidence, revision, and review status are unchanged.
    Source text is reference data; callers must never place it in a system prompt.
    """
    a = copy.deepcopy(asset)
    max_chars = max(240, min(6000, int(max_chars)))
    warnings = quality_warnings(a.get('text'))
    blocked = a.get('status') == 'rejected' or a.get('stale') or a.get('needs_structure_review') or not a.get('evidence_valid')
    if blocked:
        warnings.append({'code': 'unusable_source', 'severity': 'error',
                         'message': '来源已停用、过期、存在结构异常或原文依据无效'})
    if segments is None:
        code = a.get('code') or ''
        segments = store.read_jsonl(os.path.join(E.OUT, code, 'segments.jsonl')) if store.is_code(code) else []
    by_id = {s.get('id'): s for s in segments if s.get('id')}
    by_id.update({s.get('锚点'): s for s in segments if s.get('锚点')})
    evs = a.get('evidence') or []
    original = [by_id.get(e.get('anchor') or e.get('seg')) for e in evs]
    original = [s for s in original if s]
    query = _terms(a.get('title', '') + ' ' + a.get('text', ''))
    if a.get('kind') == 'summary' and a.get('sampled_sections') and original:
        chosen = original[:3]
        coverage = '生成摘要时使用的原文选段，核对时可查看整章。'
    elif a.get('kind') == 'summary' and original:
        chapter = original[0].get('篇')
        chapter_index = original[0].get('篇序')
        candidates = [s for s in segments if chapter and s.get('篇') == chapter
                      and s.get('篇序') == chapter_index and not s.get('source_structure_suspect')
                      and not s.get('source_layout_suspect') and not s.get('source_issue')]
        freq = Counter(t for s in candidates for t in _terms(s.get('文本')))
        def rank(s):
            ts = _terms(s.get('文本'))
            return sum(math.log(1 + len(candidates) / (1 + freq[t])) for t in ts & query)
        chosen = sorted(candidates, key=rank, reverse=True)[:3]
        coverage = '按摘要内容定位的章节选段；不代表覆盖全章或完成事实核查'
    else:
        chosen = original[:3]
        coverage = '已定位的原文选段；不代表完成事实核查'
    context, remaining = [], max_chars
    seen = set()
    per_excerpt = max(160, max_chars // max(1, len(chosen)))
    for s in chosen:
        anchor = s.get('id')
        if not anchor or anchor in seen or remaining <= 0:
            continue
        seen.add(anchor)
        preferred = next((e.get('quote') or '' for e in evs if (e.get('anchor') or e.get('seg')) in (anchor, s.get('锚点'))), '')
        raw = str(s.get('文本') or '')
        quote = _window(raw, query, min(per_excerpt, remaining), preferred if a.get('kind') != 'summary' else '')
        if not quote:
            continue
        context.append({'anchor': anchor, 'quote': quote, 'chapter': s.get('篇') or '', 'is_excerpt': len(quote) < len(raw)})
        remaining -= len(quote)
        warnings.extend(quality_warnings(quote, context=True))
    if not context:
        # Isolated adapters can supply verified evidence without raw-file access.
        for ev in evs[:3]:
            text = str(ev.get('quote') or '')[:remaining]
            anchor = ev.get('anchor') or ev.get('seg')
            if text and anchor:
                context.append({'anchor': anchor, 'quote': text, 'chapter': '', 'is_excerpt': True})
                remaining -= len(text)
            if remaining <= 0:
                break
    if a.get('kind') == 'summary':
        warnings.append({'code': 'sampled_summary', 'severity': 'info',
                         'message': '摘要由选段归纳，具体表述仍需对照相应原文核对'})
    unique = {}
    severity = {'info': 0, 'warning': 1, 'error': 2}
    for warning in warnings:
        key = (warning['code'], warning['message'])
        if key not in unique or severity[warning['severity']] > severity[unique[key]['severity']]:
            unique[key] = warning
    a['source_context'] = context
    a['context_coverage'] = coverage
    a['quality_warnings'] = list(unique.values())
    a['source_quality'] = ('blocked' if any(w['severity'] == 'error' for w in warnings) else
                           'needs_review' if any(w['severity'] == 'warning' for w in warnings) else 'usable')
    return a
