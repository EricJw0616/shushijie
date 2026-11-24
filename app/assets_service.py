# -*- coding: utf-8 -*-
"""Shared, revision-aware view of visible book assets. Engine files remain source data."""
import copy
import hashlib
import json
import os
import re
from collections import Counter
from urllib.parse import quote, urlencode

import store
import engine_bridge as E

KINDS = {'overview': '内容概览', 'summary': '章节摘要', 'quote': '原文摘录',
         'theme': '主题与观点', 'fact': '事实与案例', 'marketing': '营销线索'}
REVIEW_FILE = os.path.join(store.DATA, 'asset_reviews.json')


class Conflict(ValueError):
    pass


class ReviewBlocked(ValueError):
    def __init__(self, blocked_items):
        super().__init__('有 %d 条营销资料的来源需要处理，本次未确认任何资料。' % len(blocked_items))
        self.blocked_items = blocked_items


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()[:20]


def _norm(s):
    return re.sub(r'\s+', '', str(s or ''))


def _reviews():
    return store.read_json(REVIEW_FILE, {}) or {}


def reference_matches(asset, revision, snapshot=None):
    """Review metadata has its own revision; unchanged material keeps valid references.

    Aliases are derived server-side from the current source and its review audit
    records. Unknown versions stay invalid. Approval/quality checks remain the
    caller's responsibility: compatible content is not an approval decision.
    """
    if not asset or not revision:
        return False
    if asset.get('revision') == revision:
        return not (snapshot and 'relation' in snapshot and snapshot['relation'] != asset.get('relation'))
    if not asset.get('source_revision') or revision not in asset.get('reference_revisions', []):
        return False
    if snapshot:
        # Full project snapshots also retain source versions. Generation inputs
        # from earlier releases retain fewer fields; compare every field present.
        if (snapshot.get('id') or snapshot.get('asset_id')) != asset.get('id'):
            return False
        for key in ('code', 'book', 'kind', 'title', 'text', 'evidence', 'origin',
                    'source_revision', 'source_version', 'explanation', 'basis', 'relation'):
            if key in snapshot and snapshot[key] != asset.get(key):
                return False
    return True


def _reference_revisions(asset, source_text, source_origin, review):
    """Keep optimistic-write tokens separate from equivalent content versions."""
    versions = {asset['revision']}
    if asset['text'] == source_text and asset['origin'] == source_origin:
        versions.add(asset['source_revision'])
    if review:
        for record in [review] + review.get('history', []):
            if not record or record.get('source_revision') != asset['source_revision']:
                continue
            text = record.get('text', source_text)
            origin = '人工修订' if 'text' in record else source_origin
            if record.get('revision') and text == asset['text'] and origin == asset['origin']:
                versions.add(record['revision'])
    return sorted(versions)


def _asset(code, book, kind, key, title, text, evidence, origin='模型归纳', **extra):
    ev = [{'anchor': x.get('anchor') or x.get('seg') or '',
           'quote': x.get('quote') or ''} for x in evidence if isinstance(x, dict)]
    a = {'id': code + ':' + kind + ':' + digest(key), 'code': code, 'book': book,
         'kind': kind, 'kind_label': KINDS[kind], 'title': str(title or '')[:240],
         'text': str(text or ''), 'evidence': ev, 'origin': origin,
         'status': 'review', 'updated_at': '', **extra}
    a['source_revision'] = digest([a['text'], a['title'], ev, a.get('source_version')])
    a['revision'] = a['source_revision']
    return a


def _source_version_rows(segments):
    # Keep legacy material revisions stable. OCR method/status changes must
    # invalidate old approval even when the recognized characters are unchanged.
    from source_review import source_version_entry
    return [source_version_entry(s) for s in segments]


def _ocr_provenance(segment):
    status = segment.get('source_ocr_status')
    if not status:
        return {}
    page = segment.get('source_page')
    location = 'PDF 第 %s 页' % page if page else '原书页面'
    if status == 'body':
        note = '%s的文字由 OCR 识别取得；使用前请对照原书核对人名、数字和标点。' % location
    elif status == 'review':
        note = '%s的 OCR 结果不完整或置信度不足，仅供查看；核对并修复原文后才能确认成果。' % location
    else:
        reason = {'no_text': '未识别出可用正文', 'failed': '识别失败',
                  'unavailable': '识别服务不可用'}.get(status, '识别状态未确认')
        note = '%s的 OCR %s；残留文字仅供查看，请先补齐并核对原文。' % (location, reason)
    fields = {'source_ocr_status': status, 'source_verification_note': note}
    if segment.get('source_method') == 'ocr':
        fields['source_method'] = 'ocr'
    if page is not None:
        fields['source_page'] = page
    return fields


def _attach_source_provenance(asset, by_id):
    sources = []
    for ev in asset['evidence']:
        source = _ocr_provenance(by_id.get(ev['anchor']) or {})
        if source:
            ev.update(source)
            sources.append(source)
    if sources:
        # This label means the evidence includes OCR; individual evidence rows
        # identify which pages used it, including mixed native/OCR excerpts.
        if any(s.get('source_method') == 'ocr' for s in sources):
            asset['source_method'] = 'ocr'
        asset['source_ocr_status'] = next((s['source_ocr_status'] for s in sources
                                           if s['source_ocr_status'] != 'body'), 'body')
        asset['source_verification_note'] = ' '.join(dict.fromkeys(s['source_verification_note'] for s in sources))


def _build_book(row):
    code, title = row['code'], row['book']
    folder = os.path.join(E.OUT, code)
    bj = store.read_json(os.path.join(folder, 'book.json'), {})
    segments = store.read_jsonl(os.path.join(folder, 'segments.jsonl'))
    by_id = {s.get('id'): s for s in segments}
    by_id.update({s.get('锚点'): s for s in segments})
    positions = {s.get('id'): i for i, s in enumerate(segments)}
    def evidence(anchor, quote=''):
        s = by_id.get(anchor) or {}
        first = {'anchor': s.get('id') or anchor or '', 'quote': quote or str(s.get('文本') or '')[:240]}
        if not quote or _norm(quote) in _norm(s.get('文本')):
            return [first]
        # Structured cards can cover several adjacent paragraphs. Verify the whole
        # excerpt and preserve each paragraph boundary rather than faking one anchor.
        start = positions.get(s.get('id'))
        if start is None:
            return [first]
        parts = segments[start:start + 20]
        normalized = [_norm(x.get('文本')) for x in parts]
        hay, needle = ''.join(normalized), _norm(quote)
        begin = hay.find(needle)
        if begin < 0:
            return [first]
        end, cursor, spans = begin + len(needle), 0, []
        for seg, text in zip(parts, normalized):
            lo, hi = max(begin - cursor, 0), min(end - cursor, len(text))
            if lo < hi:
                original = str(seg.get('文本') or '')
                mapping = [i for i, c in enumerate(original) if not c.isspace()]
                spans.append({'anchor': seg['id'], 'quote': original[mapping[lo]:mapping[hi - 1] + 1]})
            cursor += len(text)
            if cursor >= end:
                break
        return spans or [first]
    def valid(ev):
        return bool(ev) and all(x['anchor'] in by_id and _norm(x['quote']) and
                                _norm(x['quote']) in _norm(by_id[x['anchor']].get('文本')) for x in ev)
    chapter_han = Counter()
    for seg in segments:
        chapter_han[seg.get('篇') or ''] += len(re.findall(r'[\u3400-\u9fff]', seg.get('文本') or ''))
    items = []
    intro = '%s；%s 个章节，%s 个内容段。' % (bj.get('原型名') or '内容待分类', bj.get('篇数', 0), len(segments))
    topics = [x.get('议题') for x in bj.get('议题', []) if x.get('议题')]
    if topics:
        intro += ' 可探索主题：' + '、'.join(topics) + '。'
    items.append(_asset(code, title, 'overview', 'overview', title + ' · 内容概览', intro,
                        evidence(segments[0].get('id')) if segments else [], '系统汇总'))
    und = store.read_json(os.path.join(folder, 'understanding.json'), {})
    cards = store.read_jsonl(os.path.join(folder, 'cards.jsonl'))
    flags = store.editor_flags(code)
    human = {}
    for c in cards:
        f = flags.get(c.get('id'), {})
        if f.get('主旨'):
            human[c.get('字段', {}).get('篇名') or c.get('字段', {}).get('回目')] = (c, f['主旨'])
    summaries_seen = set()
    duplicate_headings = Counter(s.get('篇') for s in und.get('summaries', []))
    for s in und.get('summaries', []):
        name = s.get('篇') or '章节摘要'
        h = human.get(name)
        anchor = s.get('seg_from') or ''
        text = h[1] if h else s.get('summary') or ''
        summaries_seen.add(name)
        key = [name, anchor] if duplicate_headings[s.get('篇')] > 1 else name
        source = [ev for aid in (s.get('sample_ids') or [])[:3] for ev in evidence(aid)] if not h else []
        items.append(_asset(code, title, 'summary', key, name, text, source or evidence(anchor),
                            '人工修订' if h else '模型归纳',
                            status='review', legacy_id=h[0]['id'] if h else '',
                            sampled_sections=s.get('sample_ids') or [], section_segments=s.get('section_segments')))
    for name, (c, text) in human.items():
        if name in summaries_seen:
            continue
        items.append(_asset(code, title, 'summary', name or c['id'], name or '章节主旨', text,
                            evidence(c.get('锚点')), '人工修订', status='review', legacy_id=c['id']))
    for q in und.get('quotes', []):
        text = q.get('quote') or ''
        if not text:
            continue
        items.append(_asset(code, title, 'quote', [q.get('seg'), text], text[:48], text,
                            evidence(q.get('seg'), text), '原文提取', explanation=q.get('reason') or ''))
    for q in und.get('themes', []):
        items.append(_asset(code, title, 'theme', [q.get('seg'), q.get('议题')],
                            q.get('议题') or '主题', q.get('理由') or q.get('议题') or '',
                            evidence(q.get('seg'), q.get('quote')), '模型归纳'))
    for c in cards:
        typ = str(c.get('类型') or '').strip()
        # Detector candidates and navigational scaffolding remain engine inputs,
        # not user-facing content assets.
        if typ.endswith('候选') or re.match(r'^(篇目|引书|索引|目录)', typ):
            continue
        fields = c.get('字段') or {}
        text = '\n'.join('%s：%s' % (k, v) for k, v in fields.items() if v not in ('', None, [], {}))
        text = text or c.get('原文') or ''
        label = next((fields[k] for k in ('中名', '人物', '姓名', '词条', '概念', '规则') if fields.get(k)), typ)
        items.append(_asset(code, title, 'fact', c.get('id'), str(label)[:80], text,
                            evidence(c.get('锚点'), c.get('原文') or ''), '原文提取',
                            legacy_id=c.get('id'), source_type=typ))
    try:
        import marketing_state
        for m in marketing_state.raw_rows(code, include_rejected=True):
            items.append(_asset(code, title, 'marketing', m['id'], m.get('main') or m.get('title'),
                                m.get('text') or m.get('main') or '', m.get('evidence') or [],
                                '应用推断' if m.get('basis') == '推断' else '模型归纳',
                                legacy_id=m['id'], marketing_key=m['key'], status=m['status'],
                                explanation=m.get('sub') or '', basis=m.get('basis') or ''))
    except ImportError:
        pass
    source_version = digest(_source_version_rows(segments))
    marketing_meta = store.read_json(os.path.join(folder, 'marketing.json'), {})
    for a in items:
        _attach_source_provenance(a, by_id)
        a['evidence_valid'] = valid(a['evidence'])
        a['source_version'] = source_version
        # A source edit invalidates approval even if a selected excerpt happens to be unchanged.
        a['source_revision'] = digest([a['source_revision'], a['source_version']])
        a['revision'] = a['source_revision']
        a['updated_at'] = und.get('ts') or row.get('updated_at') or ''
        part = {'summary': 'summaries', 'quote': 'quotes', 'theme': 'themes'}.get(a['kind'])
        processing = (und.get('processing') or {}).get(part, {}) if part else {}
        # The file-level flag summarizes all outputs. A successful quote rerun
        # must not remain stale merely because summaries still need regeneration.
        has_part_marker = isinstance(processing, dict) and ('status' in processing or 'source_stale' in processing)
        part_stale = (processing.get('status') == 'stale' or bool(processing.get('source_stale'))) if has_part_marker else bool(und.get('stale'))
        a['stale'] = bool((part and part_stale)
                          or (a['kind'] == 'marketing' and marketing_meta.get('stale')))
        if a['kind'] == 'summary':
            chapter_name = a['title']
            suspicious_title = bool(re.search(r'^(?:[零一二三四五六七八九十百\d]+[.、\s]*)?(?:目\s*录|附录|附記|附记|序言|序章|前言|后记|导读|译序|自序|重刊序|序[：:]|序$)', chapter_name))
            # A short poem is valid content. Only flag very short prose scaffolding
            # whose chapter name itself looks like a front/back-matter heading.
            poetry_exempt = bj.get('原型') == 'P7' and not re.match(r'^(?:目\s*录|附录)', chapter_name)
            if a['origin'] == '模型归纳':
                a['coverage_note'] = '摘要根据章节选段生成，不代表逐段覆盖；使用前请对照相关原文核对'
            a['needs_structure_review'] = bool(suspicious_title and not poetry_exempt and chapter_name in chapter_han and chapter_han[chapter_name] < 30)
            if a['needs_structure_review']:
                a['status'] = 'review'
                a['quality_note'] = '该篇仅 %d 个汉字，标题疑似目录或附录残片；请先修复源结构并重新生成摘要' % chapter_han[chapter_name]
        if any(by_id.get(e['anchor'], {}).get('source_structure_suspect')
               or by_id.get(e['anchor'], {}).get('source_layout_suspect')
               or by_id.get(e['anchor'], {}).get('source_issue') for e in a['evidence']):
            a['needs_structure_review'] = True
            a['status'] = 'review'
            a['quality_note'] = '这处原文的版面或章节需要核对。请先查看原书。'
            if a.get('source_verification_note'):
                a['quality_note'] += a['source_verification_note']
        if a['stale']:
            a['status'] = 'review'
            a['quality_note'] = '来源结构已更新，请重新生成并核对这项成果'
        elif processing.get('status') in ('failed', 'partial'):
            a['quality_note'] = ('最近生成未完整成功，保留上次成果供参考' if processing.get('retained_previous')
                                 else '最近生成未完整成功，当前成果需要核对')
        if not a['evidence_valid'] and a['status'] == 'approved':
            a['status'] = 'review'
            a['quality_note'] = '原文依据需重新核对'
    import source_review
    source_review.mark_invalidated_verifications(segments, items)
    source_review.mark_derivatives_stale(code, segments, items)
    return items


def _apply_review(a, reviews):
    source_text, source_origin = a['text'], a['origin']
    review = reviews.get(a['id'])
    if review:
        if review.get('source_revision') == a['source_revision']:
            if 'text' in review:
                a['text'] = review['text']
                a['origin'] = '人工修订'
            a['status'] = review['status']
            a['revision'] = review['revision']
            a['review_reason'] = review.get('reason', '')
            a['updated_at'] = review['updated_at']
        else:
            a['status'] = 'review'
            a['quality_note'] = '来源已更新，原审核结论需要复核'
            a['previous_review_stale'] = True
    if a['status'] == 'approved' and (a.get('stale') or a.get('needs_structure_review') or not a['evidence_valid']):
        a['status'] = 'review'
    if a.get('relation'):
        a['relation'].update(title=a['title'], body=a['text'])
    a['reference_revisions'] = _reference_revisions(a, source_text, source_origin, review)
    return a


def all_assets(code=''):
    reviews = _reviews()
    out = []
    for row in store.library_rows():
        if code and row['code'] != code:
            continue
        for a in _build_book(row):
            out.append(_apply_review(a, reviews))
    return out


def is_relation_id(asset_id):
    match = re.fullmatch(r'([^:]+):relation:[0-9a-f]{20}', str(asset_id or ''))
    return bool(match and store.is_code(match[1]))


def _relation_asset(asset_id, code):
    """Resolve one requested relationship; never add the graph to search results."""
    import kg_build as KG
    row = next((r for r in store.library_rows() if r['code'] == code), None)
    if not row:
        return None
    graph = KG.load_graph(code)
    if not graph:
        return None
    matches = [edge for edge in graph.get('edges') or []
               if edge.get('id') and KG.relation_asset_id(code, edge['id']) == asset_id]
    if len(matches) != 1:
        return None
    edge = matches[0]
    segments = store.read_jsonl(os.path.join(E.OUT, code, 'segments.jsonl'))
    by_id = {s['id']: s for s in segments}
    nodes = {n['id']: n for n in graph.get('nodes') or []}
    material, _reason = KG.relation_material(code, edge, nodes, by_id)
    if not material:
        return None
    relation = material['relation']
    # Direction, predicate, graph provenance and current source text all own the
    # version. Layout coordinates / degree / other edges do not invalidate it.
    graph_version = digest([relation, edge.get('kind'), edge.get('note'),
                            edge.get('confidence'), (edge.get('evidence') or {}).get('anchor')])
    source_version = digest([_source_version_rows(segments), graph_version])
    a = _asset(code, row['book'], 'fact', edge['id'], relation['title'], relation['body'],
               material['evidence'], material['origin'], id=asset_id, kind_label='关系材料',
               source_type='graph_relation', relation=relation, graph_revision=graph_version,
               source_version=source_version, evidence_valid=True, stale=False,
               explanation='关系由图谱整理；原文可定位不代表关系已核实，请核对方向、含义与适用范围。',
               updated_at=row.get('updated_at') or '')
    # Display provenance separately: adding a basis label must not change an
    # existing material's identity, content version or approval history.
    a.update(KG.relation_basis(code, edge, nodes, by_id))
    _attach_source_provenance(a, by_id)
    return _apply_review(a, _reviews())


def get_asset(asset_id):
    code = str(asset_id or '').split(':')[0]
    if not store.is_code(code):
        return None
    if is_relation_id(asset_id):
        return _relation_asset(asset_id, code)
    return next((a for a in all_assets(code) if a['id'] == asset_id), None)


def cached_asset(asset_id, code, by_code):
    """Reuse existing normal-asset caches and resolve only referenced graph edges."""
    if code not in by_code:
        by_code[code] = {a['id']: a for a in all_assets(code)}
    cache = by_code[code]
    if asset_id not in cache and is_relation_id(asset_id):
        cache[asset_id] = get_asset(asset_id)
    return cache.get(asset_id)


def _approved_summary_snapshot(item, current_assets):
    """Use a saved approval for the exact project text when an intro was regenerated."""
    from source_context import quality_warnings

    snapshot = item.get('snapshot') or {}
    if snapshot.get('kind') != 'marketing' or snapshot.get('marketing_key') != 'summary':
        return None
    code, aid = snapshot['code'], item['asset_id']
    legacy_id, version = snapshot.get('legacy_id'), snapshot.get('source_version')
    if (not legacy_id or aid != snapshot.get('id') or aid != code + ':marketing:' + digest(legacy_id) or
            not version or not any(a and a.get('kind') == 'marketing' and
                                   a.get('marketing_key') == 'summary' and a.get('source_version') == version
                                   for a in current_assets.values())):
        return None
    record = _reviews().get(aid, {})
    if (snapshot.get('status') != 'approved' or record.get('status') != 'approved' or
            not record.get('revision') or item['asset_revision'] != record['revision'] or
            snapshot.get('revision') != record['revision'] or not record.get('source_revision') or
            snapshot.get('source_revision') != record['source_revision'] or
            store.marketing_flags(code).get(legacy_id) == 'reject'):
        return None
    text, evidence = snapshot.get('text') or '', snapshot.get('evidence') or []
    if not text.strip() or not evidence or any(w['severity'] == 'error' for w in quality_warnings(text)):
        return None
    segments = store._seg_rows(code)
    if not segments[0] or digest(_source_version_rows(segments[0])) != version:
        return None
    for quote in evidence:
        index, _ = store.resolve_anchor(code, quote.get('anchor'), segments)
        segment = segments[0][index] if index is not None else {}
        needle = _norm(quote.get('quote'))
        if (not needle or needle not in _norm(segment.get('文本')) or
                any(segment.get(k) for k in ('source_structure_suspect', 'source_layout_suspect', 'source_issue')) or
                segment.get('source_ocr_status') not in (None, '', 'body')):
            return None
    if 'text' in record:
        matches = record['text'] == text and snapshot.get('origin') == '人工修订'
    else:
        spans = [{k: quote[k] for k in ('anchor', 'quote')} for quote in evidence]
        matches = digest([digest([text, snapshot['title'], spans, None]), version]) == record['source_revision']
    if matches:
        return dict(snapshot, evidence_valid=True, stale=False, needs_structure_review=False, archived=True)
    return None


def project_asset(item, by_code):
    """Read a live asset or validate a version already pinned in this project."""
    aid = item['asset_id']
    code = (item.get('snapshot') or {}).get('code') or aid.split(':', 1)[0]
    current = cached_asset(aid, code, by_code)
    return current or _approved_summary_snapshot(item, by_code.get(code, {}))


def list_assets(q='', kind='', code='', status='', limit=40, offset=0):
    rows = all_assets(code)
    words = [w.casefold() for w in re.split(r'\s+', str(q or '').strip()) if w]
    if words:
        rows = [a for a in rows if all(w in (a['book'] + ' ' + a['title'] + ' ' + a['text']).casefold() for w in words)]
    counts = dict(Counter(a['kind'] for a in rows))
    if kind:
        rows = [a for a in rows if a['kind'] == kind]
    statuses = dict(Counter(a['status'] for a in rows))
    if status:
        rows = [a for a in rows if a['status'] == status]
    else:
        rows = [a for a in rows if a['status'] != 'rejected']
    offset, limit = max(0, int(offset)), min(200, max(1, int(limit)))
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'counts': counts,
            'status_counts': statuses, 'offset': offset, 'limit': limit}


def _approval_reasons(a):
    reasons = []
    if a.get('needs_structure_review'):
        reasons.append({'code': 'source_structure', 'message':
                        '这处原文的版面或章节需要核对。请先查看原书。' +
                        (a.get('source_verification_note') or '')})
    if a.get('stale'):
        reasons.append({'code': 'source_stale', 'message': '来源已更新，请先重新生成并核对成果'})
    if not a.get('evidence_valid'):
        reasons.append({'code': 'invalid_evidence', 'message': '原文依据无效，修复依据后才能确认'})
    return reasons


def _review_record(a, body, status, reviews):
    old = reviews.get(a['id']) or {}
    rec = {'source_revision': a['source_revision'], 'status': status,
           'reason': str(body.get('reason') or '')[:2000], 'updated_at': store.now(),
           'actor': '本地编辑', 'revision': digest([a['revision'], status, body.get('text'), store.now()])}
    if 'text' in body:
        text = str(body['text']).strip()
        if not text or len(text) > 30000:
            raise ValueError('修订内容需为 1–30000 字')
        rec['text'] = text
    elif old.get('source_revision') == a['source_revision'] and 'text' in old:
        rec['text'] = old['text']
    rec['history'] = (old.get('history', []) + [{k: v for k, v in old.items() if k != 'history'}])[-30:] if old else []
    return rec


def _blocked_review_item(code, legacy_id, a, reasons, by_anchor, has_pdf):
    report_url = '#/report/' + quote(code, safe='')
    book_text_url = '#/book/' + quote(code, safe='') + '/text'
    sources = []
    for ev in (a or {}).get('evidence') or []:
        anchor = str(ev.get('anchor') or ev.get('seg') or '')
        segment = by_anchor.get(anchor) or {}
        resolved = segment.get('id') or ''
        page = segment.get('source_page')
        page = page if type(page) is int and page > 0 else None
        location = 'PDF 第 %d 页' % page if page else '这处原文'
        source_reasons = []
        if segment.get('source_ocr_status') not in (None, '', 'body'):
            source_reasons.append({'code': 'ocr_review', 'message':
                                   _ocr_provenance(segment).get('source_verification_note') or location + '的识别文字需要核对'})
        if segment.get('source_layout_suspect') and not source_reasons:
            issue = {'vertical_text_order': '竖排或分栏阅读顺序需要核对',
                     'formula_or_encoding': '公式或字符编码需要核对',
                     'ocr_review': '识别文字需要核对'}.get(segment.get('source_layout_issue'), '版面阅读顺序需要核对')
            source_reasons.append({'code': 'source_layout', 'message': location + '的' + issue})
        if segment.get('source_structure_suspect'):
            source_reasons.append({'code': 'source_structure', 'message': location + '的章节归属或内容结构需要核对'})
        if segment.get('source_issue'):
            source_reasons.append({'code': 'source_issue', 'message': str(segment['source_issue'])[:1000]})
        needle = _norm(ev.get('quote'))
        if not segment or not needle or needle not in _norm(segment.get('文本')):
            source_reasons.append({'code': 'invalid_evidence', 'message': '引用片段无法与当前原文匹配，请核对或重新生成资料'})
        sources.append({'anchor': resolved or anchor, 'quote': str(ev.get('quote') or '')[:1000],
                        'text': str(segment.get('文本') or '')[:1800], 'chapter': segment.get('篇') or '',
                        'source_page': page, 'source_method': segment.get('source_method') or '',
                        'source_ocr_status': segment.get('source_ocr_status') or '',
                        'source_layout_issue': segment.get('source_layout_issue') or '',
                        'source_issue': segment.get('source_issue') or '', 'reasons': source_reasons,
                        'source_url': book_text_url + '/' + quote(resolved, safe='') if resolved else '',
                        'pdf_url': '/api/book/source?' + urlencode({'code': code}) + '#page=%d' % page if has_pdf and page else ''})
    # For structure problems, surface the offending pages first rather than
    # sending the editor to an unrelated, valid citation from the same item.
    sources.sort(key=lambda source: not bool(source['reasons']))
    return {'asset_id': (a or {}).get('id') or '', 'legacy_id': legacy_id, 'code': code,
            'title': (a or {}).get('title') or '已更新的营销资料',
            'reasons': reasons, 'anchors': list(dict.fromkeys(s['anchor'] for s in sources if s['anchor'])),
            'pdf_pages': sorted({s['source_page'] for s in sources if s['source_page']}),
            'source_url': next((s['source_url'] for s in sources if s['source_url']), book_text_url),
            'report_url': report_url, 'has_original_pdf': has_pdf, 'sources': sources}


def _blocked_review_details(code, blocked):
    if not blocked:
        return []
    segments = store.read_jsonl(os.path.join(E.OUT, code, 'segments.jsonl'))
    by_anchor = {s.get('id'): s for s in segments if s.get('id')}
    by_anchor.update({s.get('锚点'): s for s in segments if s.get('锚点')})
    has_pdf = bool(store.original_pdf(code))
    return [_blocked_review_item(code, legacy_id, a, reasons, by_anchor, has_pdf)
            for legacy_id, a, reasons in blocked]


def marketing_review_issues(code):
    """Read current pending marketing sources without creating review records."""
    if not store.is_code(code):
        raise ValueError('书码不对')
    pending = [a for a in all_assets(code) if a['kind'] == 'marketing'
               and a['status'] not in ('approved', 'rejected')]
    blocked = [(a.get('legacy_id') or '', a, reasons) for a in pending
               if (reasons := _approval_reasons(a))]
    return {'code': code, 'checked_count': len(pending), 'blocked_count': len(blocked),
            'blocked_items': _blocked_review_details(code, blocked)}


def review_marketing_assets(code, ids, status):
    """Validate the entire selection, then persist its review records together."""
    if status not in ('approved', 'rejected', 'review') or not ids or not isinstance(ids, list):
        raise ValueError('审核状态或素材列表无效')
    if any(not isinstance(value, str) or not value for value in ids):
        raise ValueError('审核状态或素材列表无效')
    ids = list(dict.fromkeys(ids))
    with store._lock('asset-reviews'):
        catalog = {a.get('legacy_id'): a for a in all_assets(code) if a['kind'] == 'marketing'}
        chosen, blocked = [], []
        for legacy_id in ids:
            a = catalog.get(legacy_id)
            reasons = ([{'code': 'asset_missing', 'message': '这条资料已更新或不再存在，请刷新营销资料页后重新选择'}]
                       if a is None else _approval_reasons(a) if status == 'approved' else [])
            if reasons:
                blocked.append((legacy_id, a, reasons))
            else:
                chosen.append(a)
        if blocked:
            raise ReviewBlocked(_blocked_review_details(code, blocked))
        reviews = _reviews()
        for a in chosen:
            reviews[a['id']] = _review_record(a, {}, status, reviews)
        # A single atomic replacement prevents a later blocked item from leaving
        # earlier items silently confirmed. Legacy flags are only a mirror.
        store.write_json(REVIEW_FILE, reviews)
        warnings = []
        try:
            store.set_marketing_flags(code, ids, {'approved': 'adopt', 'rejected': 'reject', 'review': ''}[status])
        except OSError:
            warnings.append('审核已保存，兼容状态暂未同步，请刷新查看当前审核结果。')
    return {'count': len(chosen), 'changed_count': len(chosen), **({'warnings': warnings} if warnings else {})}


def review_asset(body):
    aid = str(body.get('id') or '')
    status = {'adopt': 'approved', 'reject': 'rejected'}.get(body.get('status'), body.get('status'))
    if status not in ('approved', 'rejected', 'review'):
        raise ValueError('审核状态无效')
    with store._lock('asset-reviews'):
        a = get_asset(aid)
        if not a:
            raise ValueError('资产不存在')
        if body.get('revision') != a['revision']:
            raise Conflict('资产已更新，请刷新后重新核对')
        reasons = _approval_reasons(a) if status == 'approved' else []
        if reasons:
            raise ValueError(reasons[0]['message'])
        reviews = _reviews()
        reviews[aid] = _review_record(a, body, status, reviews)
        store.write_json(REVIEW_FILE, reviews)
        if a['kind'] == 'marketing':
            store.set_marketing_flags(a['code'], [a['legacy_id']], {'approved': 'adopt', 'rejected': 'reject', 'review': ''}[status])
    return get_asset(aid)


def overview():
    import projects
    rows = all_assets()
    jobs = store.list_jobs(30)
    ps = projects.list_projects()
    books = store.library_rows()
    backend = {'segments': sum(int(x.get('segments') or 0) for x in books),
               'tags': sum(int(x.get('tags') or 0) for x in books),
               'entities': sum(len(store.read_jsonl(os.path.join(E.OUT, x['code'], 'entities.jsonl'))) for x in books)}
    return {'books': len(books), 'assets': len([a for a in rows if a['status'] != 'rejected']),
            'asset_counts': dict(Counter(a['kind'] for a in rows if a['status'] != 'rejected')),
            'status_counts': dict(Counter(a['status'] for a in rows)), 'projects': len(ps),
            'project_counts': dict(Counter(p['kind'] for p in ps)), 'recent_projects': ps[:4],
            'quality': {'running': sum(j['status'] in ('queued', 'running') for j in jobs),
                        'failed': sum(j['status'] == 'failed' for j in jobs),
                        'partial': sum(j['status'] == 'partial' for j in jobs)},
            'backend': backend, 'recent_jobs': jobs[:5]}
