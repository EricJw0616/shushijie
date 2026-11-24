"""Editorial notes about what a name refers to in one source paragraph."""
import hashlib
import os
import re
from collections import defaultdict
from functools import lru_cache

import engine_bridge as E
import store


_TITLES = re.compile('太祖|高祖|世祖|太宗|高宗|中宗|仁宗|宣宗|文宗|武宗|德宗|英宗|穆宗|神宗|光宗')
_DYNASTY = re.compile(r'(?:夏|商|周|秦|汉|晉|晋|魏|隋|唐|宋|遼|辽|金|元|明|清)(?:朝|代|末|初)?$')
_CITED_TITLE = re.compile(r'实录|實錄|本纪|本紀|会要|會要')
_GEO = {'place', 'country', 'province', 'region', 'city', 'district', 'landmark', 'nature'}
_MARKER_GROUP = re.compile(r'\[(S[1-9]\d*)\]')
_MARKER_RUN = re.compile(r'\[S[1-9]\d*\](?:[ \t]*\[S[1-9]\d*\])*')


class SourceChanged(ValueError):
    pass


def _path():
    return os.path.join(store.DATA, 'source_name_reviews.json')


def reviews():
    return store.read_json(_path(), {}) or {}


def _compact(text):
    return ''.join(str(text or '').split())


def source_revision(version, text):
    return hashlib.sha256((str(version or '') + '\0' + text).encode()).hexdigest()


def _segment(code, anchor):
    if not store.is_code(code) or not isinstance(anchor, str) or len(anchor) > 150:
        return None
    rows = store._seg_rows(code)
    index, _ = store.resolve_anchor(code, anchor, rows)
    return rows[0][index] if index is not None else None


def review_for(saved, code, anchor, revision, name):
    item = (saved.get(code) or {}).get(anchor) or {}
    return (item.get('names') or {}).get(_compact(name)) if item.get('revision') == revision else None


def get_check(code, anchor, name, saved=None):
    if not store.is_code(code) or not store.get_record(code):
        raise ValueError('找不到这本书。')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 64 or re.search(r'[\x00-\x1f]', name):
        raise ValueError('请选择要核对的名称。')
    name = name.strip()
    segment = _segment(code, anchor)
    text = (segment or {}).get('文本') or ''
    if not text or _compact(name) not in _compact(text):
        raise ValueError('这段原文里找不到这个名称，请重新定位。')
    anchor = segment['id']
    revision = source_revision(E.book_json(code).get('source_version'), text)
    return {'code': code, 'anchor': anchor, 'name': name, 'revision': revision, 'text': text,
            'review': review_for(reviews() if saved is None else saved, code, anchor, revision, name)}


def save_check(body):
    note = body.get('note', '')
    cat = body.get('cat', '')
    if not isinstance(note, str) or len(note) > 240 or not isinstance(cat, str):
        raise ValueError('核对说明请控制在 240 字以内。')
    note = note.strip()
    if cat and cat not in {*dict(store.ENTITY_CATS), 'book', 'ignore'}:
        raise ValueError('请选择合适的名称类别。')
    if not note and not cat:
        raise ValueError('请填写这段原文里的名称指什么。')
    with store._lock('source-name-reviews'):
        saved = reviews()
        item = get_check(body.get('code'), body.get('anchor'), body.get('name'), saved)
        if body.get('revision') != item['revision']:
            raise SourceChanged('原文已变化，请打开当前段落重新核对。')
        anchors = saved.setdefault(item['code'], {})
        old = anchors.get(item['anchor']) or {}
        names = dict(old.get('names') or {}) if old.get('revision') == item['revision'] else {}
        item['review'] = {'note': note, 'cat': cat, 'updated_at': store.now()}
        names[_compact(item['name'])] = item['review']
        anchors[item['anchor']] = {'revision': item['revision'], 'names': names}
        store.write_json(_path(), saved)
    return item


def _ambiguous_titles(text):
    text = _compact(text)
    names = set()
    for match in _TITLES.finditer(text):
        i, j = match.span()
        if _DYNASTY.search(text[max(0, i - 3):i]) or _CITED_TITLE.match(text[j:]) or text[j:j+1] in ('父', '母'):
            continue
        if text.rfind('《', 0, i) > text.rfind('》', 0, i) and '》' in text[j:]:
            continue
        names.add(match.group())
    return names


@lru_cache(maxsize=8)
def _conflicting_names(path, stamp):
    categories = defaultdict(set)
    mentions = defaultdict(set)
    for row in store.read_jsonl(path):
        name, cat, anchor = row.get('name'), row.get('cat'), row.get('seg')
        if not name or not anchor:
            continue
        group = 'place' if cat in _GEO else cat
        confidence = row.get('conf')
        if group in ('place', 'person', 'org') and isinstance(confidence, (int, float)) and confidence >= .85:
            categories[name].add(group)
        mentions[name].add(anchor)
    by_anchor = defaultdict(set)
    for name, kinds in categories.items():
        if len(kinds) > 1:
            for anchor in mentions[name]:
                by_anchor[anchor].add(name)
    return by_anchor


def _conflicts(code):
    path = os.path.join(E.OUT, code, 'entities.jsonl')
    try:
        stat = os.stat(path)
    except OSError:
        return {}
    return _conflicting_names(path, (stat.st_mtime_ns, stat.st_size))


def _draft_passages(draft):
    by_label = defaultdict(list)
    for paragraph in re.split(r'\n\s*\n', draft):
        start = 0
        for markers in _MARKER_RUN.finditer(paragraph):
            for label in _MARKER_GROUP.findall(markers.group()):
                by_label[label].append(paragraph[start:markers.start()])
            start = markers.end()
    return by_label


def project_checks(project, asset_id=''):
    """Advisory checks on explicitly registered sources used in the saved manuscript."""
    draft = project.get('draft') or ''
    cited = set(project.get('draft_asset_ids') or [])
    if not draft.strip() or not cited:
        return []
    labels = (project.get('draft_generation') or {}).get('source_labels') or {}
    passages = _draft_passages(draft)
    saved = reviews()
    versions, matches = {}, []
    for item in project.get('items') or []:
        aid = item['asset_id']
        if (aid not in cited or (asset_id and aid != asset_id) or item.get('status') != 'adopted'
                or item.get('stale') or item.get('current_status') in ('missing', 'rejected')
                or not item.get('evidence_valid') or item.get('quality_issues')):
            continue
        label = labels.get(aid)
        if label in passages:
            used_text = _compact('\n'.join(passages[label]))
        elif passages:
            continue
        else:
            used_text = _compact(draft)
        used_titles = _ambiguous_titles(used_text)
        asset = item['snapshot']
        code = asset.get('code')
        if not store.is_code(code):
            continue
        if code not in versions:
            versions[code] = (E.book_json(code).get('source_version'), _conflicts(code))
        version, conflicts = versions[code]
        seen = set()
        for evidence in asset.get('evidence') or []:
            segment = _segment(code, evidence.get('anchor') or evidence.get('seg'))
            quote = evidence.get('quote') or ''
            if not segment or not quote or _compact(quote) not in _compact(segment.get('文本')):
                continue
            anchor = segment['id']
            quoted = _compact(quote)
            uncertain = (_ambiguous_titles(quote) & used_titles) | {
                name for name in conflicts.get(anchor, ()) if _compact(name) in quoted}
            revision = source_revision(version, segment.get('文本') or '')
            for name in sorted(uncertain):
                if (anchor, name) in seen or _compact(name) not in used_text:
                    continue
                seen.add((anchor, name))
                matches.append({'asset_id': aid, 'title': asset.get('title') or '项目材料',
                                'code': code, 'anchor': anchor, 'name': name, 'quote': quote[:480], 'revision': revision,
                                'review': review_for(saved, code, anchor, revision, name)})
                if len(matches) >= 30:
                    return matches
    return matches
