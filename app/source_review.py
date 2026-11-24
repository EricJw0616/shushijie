"""Explicit, versioned proofreading of one paragraph against its original PDF."""
import copy
import hashlib
import json
import os
import re
import secrets
from urllib.parse import quote, urlencode

import engine_bridge as E
import store


class SourceChanged(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _verification_fingerprint(segment):
    return _hash({k: v for k, v in segment.items()
                  if k not in ('source_review', 'source_review_invalidations')})


def valid_verification(segment):
    review = segment.get('source_review') or {}
    return bool(review.get('id') and review.get('verified_fingerprint') == _verification_fingerprint(segment))


def mark_invalidated_verifications(segments, assets):
    changed = {anchor for s in segments if s.get('source_review') and not valid_verification(s)
               for anchor in (s.get('id'), s.get('锚点')) if anchor}
    for asset in assets:
        if any(ev.get('anchor') in changed for ev in asset.get('evidence') or []):
            asset.update(needs_structure_review=True, status='review',
                         source_verification_note='原文在上次核对后已变化，请重新对照原版核对当前段落。',
                         quality_note='原文核对记录已过期，请重新核对当前段落')


def source_version_entry(segment):
    """Proofreading without text edits must not invalidate unrelated approvals."""
    review = segment.get('source_review') or {}
    if valid_verification(segment):
        method, status = review.get('version_source_method'), review.get('version_ocr_status')
    else:
        method, status = segment.get('source_method'), segment.get('source_ocr_status')
    return ((segment.get('id'), segment.get('文本'), method, status) if status
            else (segment.get('id'), segment.get('文本')))


def _file_hash(path):
    try:
        with open(path, 'rb') as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ''


def _generation(path):
    if path.endswith('marketing.json'):
        return (store.read_json(path, {}) or {}).get('generated_at')
    if path.endswith('understanding.json'):
        return (store.read_json(path, {}) or {}).get('ts')
    return None


def mark_derivatives_stale(code, segments, assets):
    markers = {}
    for segment in segments:
        for aid, marker in (segment.get('source_review_invalidations') or {}).items():
            markers.setdefault(aid, []).append(marker)
    versions = {}
    for a in assets:
        for marker in markers.get(a['id'], []):
            if marker.get('file') not in ('marketing.json', 'understanding.json', 'cards.jsonl'):
                continue
            filename = marker['file']
            if filename not in versions:
                path = os.path.join(E.OUT, code, filename)
                versions[filename] = (_file_hash(path), _generation(path))
            digest, generation = versions[filename]
            if (marker.get('version') and digest == marker['version'] or
                    marker.get('generation') is not None and generation == marker['generation']):
                a.update(stale=True, status='review', source_corrected=True,
                         quality_note='所引用的原文已人工修正，请重新生成这项成果后核对；旧引文不能直接沿用')
                break


def _load(code):
    if not isinstance(code, str) or not store.is_code(code) or not store.get_record(code):
        raise ValueError('找不到这本书。')
    path = os.path.join(E.OUT, code, 'segments.jsonl')
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
        lines = raw.decode('utf-8').splitlines(keepends=True)
        rows = [(index, json.loads(line)) for index, line in enumerate(lines) if line.strip()]
    except (OSError, ValueError, UnicodeError):
        raise ValueError('原文段落无法完整读取，请先处理图书来源。')
    return path, raw, lines, rows


def _pdf(code):
    path = store.original_pdf(code)
    if not path or not os.path.isfile(path):
        return None
    try:
        import pypdfium2
        from pdf_source_preview import _RENDER_LOCK
        with _RENDER_LOCK:
            document = pypdfium2.PdfDocument(path)
            try:
                pages = len(document)
            finally:
                document.close()
        stat = os.stat(path)
        return {'pages': pages, 'stamp': [stat.st_size, stat.st_mtime_ns], 'path': path}
    except Exception:
        return None


def _eligibility(segment, pdf):
    if not pdf:
        return '原始 PDF 不可用，暂不能对照确认。可跳过这条资料或将其停用。'
    page = segment.get('source_page')
    if type(page) is not int or not 1 <= page <= pdf['pages']:
        return '这段原文没有有效的原版页码，暂不能对照确认。可跳过或停用资料。'
    if not isinstance(segment.get('文本'), str) or not segment['文本'].strip():
        return '这段原文缺少文字，不能用确认操作补成正文。请跳过或停用资料。'
    if (segment.get('source_kind') in ('blank', 'non_body', 'missing', 'no_text') or
            segment.get('source_ocr_status') in ('blank', 'non_body', 'no_text', 'failed', 'unavailable')):
        return '来源为空白、缺失或未成功识别，不能通过本步骤确认为正文。请跳过或停用资料。'
    if segment.get('source_structure_suspect') or segment.get('source_issue'):
        return '这段原文存在章节结构或归属问题，文字核对不能解除。请跳过或停用资料，另行处理来源结构。'
    issue = segment.get('source_layout_issue')
    if segment.get('source_layout_suspect') and issue not in ('ocr_review', 'vertical_text_order', 'formula_or_encoding'):
        return '此处版面问题不能通过单段文字确认解决。请跳过或停用资料，另行处理来源结构。'
    return ''


def _revision(segment, pdf):
    return _hash([segment, pdf['stamp'] if pdf else None])


def _public_segment(code, segment, pdf):
    reason = _eligibility(segment, pdf)
    page = segment.get('source_page')
    issues = []
    if segment.get('source_ocr_status') not in (None, '', 'body'):
        issues.append('识别文字待核对')
    if segment.get('source_layout_suspect'):
        issues.append('版面文字与阅读顺序待核对')
    if segment.get('source_structure_suspect') or segment.get('source_issue'):
        issues.append('章节结构或归属待处理')
    if segment.get('source_review') and not valid_verification(segment):
        issues.append('原文在上次核对后已变化')
    review = segment.get('source_review') if valid_verification(segment) else None
    return {'anchor': segment['id'], 'revision': _revision(segment, pdf), 'text': segment.get('文本') or '',
            'chapter': segment.get('篇') or '', 'source_page': page,
            'source_url': '#/book/' + quote(code, safe='') + '/text/' + quote(segment['id'], safe=''),
            'pdf_url': ('/api/book/source?' + urlencode({'code': code}) + '#page=%d' % page
                        if pdf and type(page) is int and 1 <= page <= pdf['pages'] else ''),
            'preview_url': ('/api/book/source-page?' + urlencode({'code': code, 'page': page})
                            if pdf and type(page) is int and 1 <= page <= pdf['pages'] else ''),
            'can_verify': not reason, 'blocked_reason': reason, 'issues': issues, 'has_issue': bool(issues),
            'review': {k: review[k] for k in ('id', 'at', 'action')} if review else None}


def get_context(code, asset_id):
    import assets_service as assets
    _, _, _, rows = _load(code)
    asset = assets.get_asset(asset_id)
    if not asset or asset.get('code') != code or asset.get('kind') != 'marketing':
        raise ValueError('营销资料已更新，请重新选择。')
    by_id = {s['id']: s for _, s in rows if s.get('id')}
    by_id.update({s['锚点']: s for _, s in rows if s.get('锚点')})
    pdf = _pdf(code)
    seen, segments, missing, evidence = set(), [], [], []
    for ev in asset.get('evidence') or []:
        anchor = ev.get('anchor') or ev.get('seg') or ''
        segment = by_id.get(anchor)
        if not segment:
            missing.append(anchor)
        else:
            evidence.append({'anchor': segment['id'], 'quote': ev.get('quote') or '',
                             'chapter': segment.get('篇') or '', 'source_page': segment.get('source_page'),
                             'text': segment.get('文本') or ''})
            if segment['id'] not in seen:
                seen.add(segment['id'])
                public = _public_segment(code, segment, pdf)
                if asset['status'] == 'rejected':
                    public.update(can_verify=False, blocked_reason='这条营销资料已停用，当前仅供回顾处理记录。')
                if public['issues'] or public['review']:
                    segments.append(public)
    segments.sort(key=lambda s: (not bool(s['issues']), s['source_page'] or 0))
    reasons = assets._approval_reasons(asset)
    return {'code': code, 'asset_id': asset['id'], 'revision': asset['revision'], 'title': asset['title'], 'text': asset['text'],
            'reason': asset.get('explanation') or '', 'basis': asset.get('basis') or '',
            'legacy_id': asset.get('legacy_id') or '', 'status': asset['status'],
            'segments': segments, 'evidence': evidence, 'missing_anchors': missing, 'has_original_pdf': bool(pdf),
            'pending_segments': [s for s in segments if s['has_issue']],
            'pending_count': sum(s['has_issue'] for s in segments) + len(missing),
            'report_url': '#/report/' + quote(code, safe=''),
            'requires_regeneration': bool(asset.get('stale')),
            'can_proceed': asset['status'] != 'rejected' and not reasons and not missing, 'blocked_reasons': reasons,
            'message': '逐段对照原版核对文字。完成原文核对后，仍需单独确认营销资料。'}


def verify(body):
    import assets_service as assets
    if not isinstance(body, dict) or body.get('confirmed') is not True:
        raise ValueError('请明确勾选已对照原版核对这段文字。')
    code, anchor = body.get('code'), body.get('anchor')
    if not isinstance(code, str) or not store.is_code(code) or not isinstance(anchor, str) or len(anchor) > 200:
        raise ValueError('原文定位无效，请重新打开核对步骤。')
    with store._lock('source-review-' + code), store._lock('asset-reviews'):
        path, raw, lines, rows = _load(code)
        hits = [(index, s) for index, s in rows if s.get('id') == anchor]
        if len(hits) != 1:
            raise ValueError('原文段落已变化或无法唯一定位，请重新打开核对步骤。')
        index, original = hits[0]
        if body.get('asset_id'):
            asset = assets.get_asset(body['asset_id'])
            if (not asset or asset['code'] != code or asset['kind'] != 'marketing' or asset['status'] == 'rejected' or
                    not any(ev.get('anchor') in (anchor, original.get('锚点')) for ev in asset['evidence'])):
                raise ValueError('这段原文不属于当前营销资料，请重新打开核对步骤。')
        pdf = _pdf(code)
        if body.get('revision') != _revision(original, pdf):
            raise SourceChanged('原文或底本已变化，请重新打开当前段落核对，之前的操作未保存。')
        reason = _eligibility(original, pdf)
        if reason:
            raise ValueError(reason)
        text = body.get('text', original['文本'])
        if not isinstance(text, str) or not text.strip() or len(text) > 100000 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
            raise ValueError('请填写完整且有效的单段文字，不能保存空白或控制字符。')
        changed = text != original['文本']
        updated = copy.deepcopy(original)
        invalidated = []
        if changed:
            files = {'marketing': 'marketing.json', 'summary': 'understanding.json',
                     'quote': 'understanding.json', 'theme': 'understanding.json', 'fact': 'cards.jsonl'}
            markers = updated.setdefault('source_review_invalidations', {})
            for asset in assets.all_assets(code):
                if asset['kind'] in files and any(ev.get('anchor') in (anchor, original.get('锚点')) for ev in asset['evidence']):
                    filename = files[asset['kind']]
                    artifact_path = os.path.join(E.OUT, code, filename)
                    markers[asset['id']] = {'file': filename, 'version': _file_hash(artifact_path),
                                            'generation': _generation(artifact_path)}
                    invalidated.append(asset['id'])
            updated.update(文本=text, 字数=len(re.findall(r'[\u3400-\u9fff]', text)))
        updated.pop('source_layout_suspect', None)
        updated.pop('source_layout_issue', None)
        if updated.get('source_ocr_status'):
            updated['source_ocr_status'] = 'body'
        old_review = original.get('source_review') if valid_verification(original) else {}
        rid, at = 'sr-' + secrets.token_hex(12), store.now()
        review = {'id': rid, 'at': at, 'action': 'corrected' if changed else 'verified',
                  'actor': '本地编辑', 'confirmed': True,
                  'version_source_method': (old_review or {}).get('version_source_method', original.get('source_method')),
                  'version_ocr_status': (old_review or {}).get('version_ocr_status', original.get('source_ocr_status'))}
        review['verified_fingerprint'] = _verification_fingerprint(updated)
        updated['source_review'] = review
        # The audit record contains the complete previous paragraph. The commit
        # marker in segments.jsonl distinguishes applied records from interrupted
        # attempts without requiring a second post-commit write.
        audit = {'id': rid, 'code': code, 'anchor': anchor, 'at': at, 'action': review['action'],
                 'actor': review['actor'], 'confirmed': True, 'before': original, 'after': updated,
                 'source_revision': body['revision'], 'pdf_stamp': pdf['stamp'],
                 'invalidated_asset_ids': invalidated}
        store.write_json(os.path.join(store.DATA, 'source_reviews', code, rid + '.json'), audit)
        if _file_hash(path) != hashlib.sha256(raw).hexdigest():
            raise SourceChanged('保存前发现原文已更新，请重新打开核对步骤；此次未改写原文。')
        newline = '\r\n' if lines[index].endswith('\r\n') else '\n' if lines[index].endswith('\n') else ''
        lines[index] = json.dumps(updated, ensure_ascii=False) + newline
        store._atomic_write(path, ''.join(lines))
    return {'code': code, 'anchor': anchor, 'revision': _revision(updated, pdf), 'changed': changed,
            'review': {k: review[k] for k in ('id', 'at', 'action')},
            'requires_regeneration': changed, 'invalidated_asset_ids': invalidated,
            'segment': _public_segment(code, updated, pdf),
            'message': ('原文修正已保存。请重新生成受影响的营销资料后核对；当前旧资料尚未确认。' if changed else
                        '这段原文的核对已保存。其他异常段仍需逐段处理，之后再确认营销资料。')}
