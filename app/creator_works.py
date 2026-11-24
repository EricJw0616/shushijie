"""Store work evidence entered for Douyin creators without resolving source links."""

import hashlib
import json
import re
import threading
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import store


WORKS_FILE = Path(store.DATA) / 'creator_works.json'
BUNDLED_FILE = Path(__file__).resolve().parent / 'resources' / 'creator_works.jsonl'
MANUAL_PROVENANCE = '运营录入'
BUNDLED_PROVENANCE = '公开作品核对'
MAX_BATCH = 20
MAX_PER_CREATOR = 100
_WRITE_LOCK = threading.Lock()


class WorksUnavailable(Exception):
    """The work repository could not be read or updated."""


def parse_handle(handle):
    if not isinstance(handle, str):
        raise ValueError('达人账号应为文字。')
    handle = handle.strip()
    if not 1 <= len(handle) <= 128 or any(c.isspace() or not c.isprintable() for c in handle):
        raise ValueError('请输入有效的达人账号。')
    return handle


def _text(entry, key, label, limit):
    value = entry.get(key, '')
    if not isinstance(value, str):
        raise ValueError(f'{label}应为文字。')
    value = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if len(value) > limit:
        raise ValueError(f'{label}最多 {limit} 个字符。')
    if any(unicodedata.category(c) in ('Cc', 'Cs') and c not in '\n\t' for c in value):
        raise ValueError(f'{label}包含无效字符。')
    return value


def _source_url(value):
    if not value:
        return ''
    try:
        url = urlsplit(value)
        port = url.port
        if (url.scheme != 'https' or not url.hostname or url.username is not None or
                url.password is not None or port == 0 or any(c.isspace() or c in '\\<>"' for c in value)):
            raise ValueError()
        return urlunsplit((url.scheme, url.netloc.lower(), url.path, url.query, url.fragment))
    except ValueError:
        raise ValueError('来源链接应为有效的 HTTPS 网址。') from None


def _url_key(value):
    url = urlsplit(value)
    query = [(key, item) for key, item in parse_qsl(url.query, keep_blank_values=True)
             if not key.casefold().startswith('utm_')]
    return urlunsplit((url.scheme, url.netloc, url.path.rstrip('/'), urlencode(sorted(query)), ''))


def _title_key(title):
    return unicodedata.normalize('NFKC', title).casefold()


def _normalize_work(handle, entry, *, bundled=False):
    if not isinstance(entry, dict):
        raise ValueError('每条作品应包含标题及可选的正文、链接、发布日期。')
    title = ' '.join(_text(entry, 'title', '作品标题', 180).split())
    if not title:
        raise ValueError('请填写作品标题。')
    text = _text(entry, 'text', '作品正文', 5000)
    url = _source_url(_text(entry, 'url', '来源链接', 1200))
    if bundled and not url:
        raise ValueError('内置作品需要来源链接。')
    published = _text(entry, 'published', '发布日期', 10)
    if published:
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', published):
                raise ValueError()
            date.fromisoformat(published)
        except ValueError:
            raise ValueError('发布日期应为有效日期，格式为 YYYY-MM-DD。') from None

    provenance = MANUAL_PROVENANCE
    if bundled:
        provenance = _text(entry, 'provenance', '来源说明', 80) or BUNDLED_PROVENANCE
    key = _url_key(url) if url else f'{_title_key(title)}\n{published}'
    work_id = hashlib.sha256(f'{handle}\n{key}'.encode('utf-8')).hexdigest()[:24]
    return {'id': work_id, 'handle': handle, 'title': title, 'text': text, 'url': url,
            'published': published, 'provenance': provenance}


def _same_work(first, second):
    if first['url'] and second['url']:
        return _url_key(first['url']) == _url_key(second['url'])
    if _title_key(first['title']) != _title_key(second['title']):
        return False
    return (not first['published'] or not second['published'] or
            first['published'] == second['published'])


def _sort_works(works):
    return sorted(works, key=lambda item: item['published'], reverse=True)


def _read_bundle():
    bundled = {}
    try:
        with BUNDLED_FILE.open(encoding='utf-8') as source:
            for line in source:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    raise ValueError('内置作品格式无效。')
                handle = parse_handle(entry.get('handle'))
                work = _normalize_work(handle, entry, bundled=True)
                works = bundled.setdefault(handle, [])
                if not any(_same_work(existing, work) for existing in works):
                    works.append(work)
    except FileNotFoundError:
        pass
    return bundled


def _read_manual():
    try:
        with WORKS_FILE.open(encoding='utf-8') as source:
            data = json.load(source)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('works'), dict):
        raise ValueError('已录入作品格式无效。')
    works = {}
    for handle, entries in data['works'].items():
        handle = parse_handle(handle)
        if not isinstance(entries, list):
            raise ValueError('已录入作品格式无效。')
        works[handle] = [_normalize_work(handle, entry) for entry in entries]
        # Keep an assigned ID stable as optional metadata is filled in over time.
        for entry, normalized in zip(entries, works[handle]):
            if isinstance(entry.get('id'), str) and re.fullmatch(r'[0-9a-f]{24}', entry['id']):
                normalized['id'] = entry['id']
    return works


def read_works():
    """Return normalized works keyed by the original, text-valued creator account."""
    try:
        bundled, manual = _read_bundle(), _read_manual()
    except (OSError, ValueError, TypeError) as error:
        raise WorksUnavailable('暂时无法读取达人作品。') from error
    for handle, works in manual.items():
        existing = bundled.setdefault(handle, [])
        for work in works:
            if not any(_same_work(item, work) for item in existing):
                existing.append(work)
    return {handle: _sort_works(works) for handle, works in bundled.items()}


def merge_works(handle, entries):
    """Validate the batch, then merge it into the persistent repository once."""
    handle = parse_handle(handle)
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_BATCH:
        raise ValueError(f'每次请提交 1 至 {MAX_BATCH} 条作品。')
    incoming = [_normalize_work(handle, entry) for entry in entries]
    with _WRITE_LOCK, store._lock('creator_works'):
        try:
            manual = _read_manual()
            bundled = _read_bundle().get(handle, [])
        except (OSError, ValueError, TypeError) as error:
            raise WorksUnavailable('暂时无法读取达人作品。') from error

        previous = manual.get(handle, [])
        updated = list(previous)
        for work in incoming:
            if any(_same_work(existing, work) for existing in bundled):
                continue
            position = next((i for i, existing in enumerate(updated) if _same_work(existing, work)), None)
            if position is None:
                updated.append(work)
            else:
                existing = updated[position]
                updated[position] = {**existing, **{key: work[key] for key in ('title', 'text', 'url', 'published')
                                                    if work[key]}}
        if len(updated) > MAX_PER_CREATOR:
            raise ValueError(f'同一达人最多录入 {MAX_PER_CREATOR} 条作品。')
        if updated != previous:
            manual[handle] = updated
            try:
                store.write_json(str(WORKS_FILE), {'version': 1, 'works': manual})
            except OSError as error:
                raise WorksUnavailable('暂时无法保存达人作品。') from error
        visible = [item for item in updated if not any(_same_work(work, item) for work in bundled)]
        return _sort_works(bundled + visible)
