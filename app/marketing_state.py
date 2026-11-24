"""One review-aware view of marketing material for UI and application consumers."""
import hashlib
import json
import os
import re

import store


def _hash(text):
    value = 5381
    # Match JavaScript's UTF-16 based legacy IDs, including non-BMP characters.
    data = str(text).encode('utf-16-le')
    for i in range(0, len(data), 2):
        value = ((value * 33) + int.from_bytes(data[i:i + 2], 'little')) & 0xffffffff
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    out = ''
    while value:
        value, rest = divmod(value, 36)
        out = chars[rest] + out
    return out or '0'


def raw_rows(code, include_rejected=False, approved_only=False):
    data = store.read_json(os.path.join(store.E.OUT, code, 'marketing.json'), {})
    flags = store.marketing_flags(code)
    result = []
    items = data.get('items') or {}
    for key in ['summary', 'keywords', 'audience', 'scenarios', 'gains', 'emotions', 'leads']:
        item = items.get(key) or {}
        value = item.get('value')
        values = [value] if key == 'summary' and isinstance(value, dict) else value
        if not isinstance(values, list):
            continue
        for val in values:
            if not isinstance(val, dict):
                continue
            main = val.get('keyword') if key == 'keywords' else val.get('text')
            main = str(main or '')
            sub = '' if key == 'summary' else str(val.get('reason') or '')
            if not main and not sub:
                continue
            evidence = (item.get('evidence') if key == 'summary' else val.get('evidence')) or []
            row_id = key + ':' + _hash(main + '|' + sub)
            basis = str(val.get('basis') or '')
            revision = hashlib.sha256(json.dumps([main, sub, basis, evidence], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            decision = flags.get(row_id)
            # Legacy flags have no content revision. Only revisioned asset reviews can approve.
            state = 'rejected' if decision == 'reject' else 'review'
            if state == 'rejected' and not include_rejected:
                continue
            if approved_only and state != 'approved':
                continue
            result.append({'id': row_id, 'code': code, 'key': key,
                           'title': item.get('name') or key, 'main': main,
                           'text': main, 'sub': sub, 'basis': basis,
                           'evidence': evidence, 'revision': revision,
                           'status': state})
    return result


def rows(code, include_rejected=False, approved_only=False):
    import assets_service
    originals = {r['id']: r for r in raw_rows(code, include_rejected=True)}
    output = []
    for a in assets_service.all_assets(code):
        if a['kind'] != 'marketing':
            continue
        row = dict(originals.get(a.get('legacy_id'), {}))
        if not row:
            continue
        row.update(text=a['text'], main=a['text'], status=a['status'],
                   revision=a['revision'], asset_id=a['id'],
                   evidence=[{'seg': e['anchor'], 'quote': e['quote']} for e in a['evidence']])
        if row['status'] == 'rejected' and not include_rejected:
            continue
        if approved_only and row['status'] != 'approved':
            continue
        output.append(row)
    return output


def export(code, mode='approved', fmt='md'):
    if mode not in ('approved', 'review') or fmt not in ('md', 'csv'):
        raise ValueError('导出模式或格式不正确')
    selected = rows(code, approved_only=(mode == 'approved'))
    if not selected:
        raise ValueError('没有符合条件的素材，请先确认需要采用的内容')
    label = '已采纳稿' if mode == 'approved' else '审阅稿'
    if fmt == 'csv':
        import csv
        import io
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['分类', '素材', '说明', '性质', '状态', '原文锚点', '证据原文'])
        def cell(v):
            s = str(v or '')
            return "'" + s if s.startswith(('=', '+', '-', '@', '\t', '\r')) else s
        for r in selected:
            ev = (r['evidence'] or [{}])[0]
            writer.writerow([cell(v) for v in [r['title'], r['main'], r['sub'], r['basis'], r['status'], ev.get('seg'), ev.get('quote')]])
        text = stream.getvalue()
    else:
        lines = ['# 营销素材 · %s · %s' % (code, label), '']
        for r in selected:
            lines.append('## %s' % r['title'])
            lines.append(('[待确认] ' if r['status'] != 'approved' else '') + r['main'])
            if r['sub']:
                lines.append(r['sub'])
            for ev in r['evidence']:
                lines.append('> %s（%s）' % (ev.get('quote') or '', ev.get('seg') or '出处待补'))
            lines.append('')
        text = '\n'.join(lines)
    return {'filename': '%s_营销素材_%s.%s' % (code, label, fmt), 'text': text, 'count': len(selected)}
