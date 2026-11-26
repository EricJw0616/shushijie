"""Backfill missing PDF physical pages from exact, unique native-text matches.

Run with no flags to audit the registered library, or pass one or more book
codes. --apply rechecks each original and segment file before updating it.
The report includes physical pages with unavailable native text.
Run apply in a maintenance window with manual imports and rebuilds stopped.
"""
import argparse
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

import store
from ingest import _clean_pdf_lines


class SkipBook(ValueError):
    pass


def normalize(text):
    return re.sub(r'\s+', '', text)


def stream_sha(handle):
    digest = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def pdf_sha(path):
    with path.open('rb') as handle:
        return stream_sha(handle)


def native_pages(path):
    import pdfplumber

    with path.open('rb') as handle:
        fingerprint = stream_sha(handle)
        handle.seek(0)
        pages = []
        with pdfplumber.open(handle) as pdf:
            for page in pdf.pages:
                try:
                    text = page.extract_text(expand_ligatures=False) or ''
                    native = normalize(text)
                    unreadable = (not native and any(page.objects.values()) or
                                  re.search(r'\(cid:\d+\)|[\x00\ufffd]', native) or
                                  page.images and not normalize(_clean_pdf_lines(text)))
                    pages.append(None if unreadable else native)
                except Exception:
                    pages.append(None)
                finally:
                    page.flush_cache()
        handle.seek(0)
        if stream_sha(handle) != fingerprint:
            raise SkipBook('original_changed')
    return pages, fingerprint


def reviewed_anchors(code):
    folder = Path(store.DATA) / 'source_reviews' / code
    anchors = set()
    if not folder.exists():
        return anchors
    try:
        for path in folder.iterdir():
            if path.suffix != '.json':
                continue
            record = json.loads(path.read_bytes())
            if not isinstance(record, dict):
                raise SkipBook('unreadable_source_reviews')
            if path.name == 'pages.json':
                if any(not key.isdecimal() or not isinstance(value, dict) for key, value in record.items()):
                    raise SkipBook('unreadable_source_reviews')
            elif path.name == 'ignored-quality.json':
                if any(not isinstance(value, dict) for value in record.values()):
                    raise SkipBook('unreadable_source_reviews')
                anchors.update(record)
            elif isinstance(record.get('anchor'), str):
                anchors.add(record['anchor'])
            else:
                raise SkipBook('unreadable_source_reviews')
    except (OSError, ValueError) as exc:
        raise SkipBook('unreadable_source_reviews') from exc
    return anchors


def active_book_job(code, title):
    for path in Path(store.JOBDIR).iterdir():
        if path.suffix != '.json':
            continue
        job = store.get_job(path.stem)
        if job is None and not path.exists():
            continue
        if not isinstance(job, dict) or 'status' not in job:
            raise SkipBook('unreadable_job_state')
        if job.get('status') not in ('queued', 'running'):
            continue
        if code in (job.get('code'), job.get('book_code'), job.get('resume_code')):
            return True
        if title and job.get('title') == title:
            return True
        trash = re.fullmatch(r'(.+)-\d{8}-\d{6}', str(job.get('trash_id') or ''))
        if trash and trash[1] == code:
            return True
    return False


def is_reviewed(row, anchors):
    return (bool(row.get('source_review') or row.get('source_review_invalidations')) or
            any(anchor in anchors for anchor in segment_anchors(row)))


def segment_anchors(row):
    return {key for key in (row.get('id'), row.get('锚点')) if isinstance(key, str) and key}


def unique_page(text, pages_text, page_ends):
    start = pages_text.find(text)
    if start == -1:
        return None, 'no_exact_match'
    if pages_text.find(text, start + 1) != -1:
        return None, 'multiple_pdf_matches'
    page = bisect_right(page_ends, start)
    if start + len(text) > page_ends[page]:
        return None, 'cross_page_match'
    return page + 1, ''


def unique_keys(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError('duplicate JSON keys')
    return obj


@dataclass
class Plan:
    path: Path
    pdf: Path
    raw: bytes
    original_sha: str
    changes: list
    updated: bytes


def plan_book(code, record, report):
    if record.get('status') in ('deleted', 'failed') or record.get('source_format') != 'pdf':
        raise SkipBook('no_registered_pdf')
    if active_book_job(code, record.get('book')):
        raise SkipBook('active_book_job')
    source = store.original_pdf(code)
    if not source:
        raise SkipBook('missing_original_pdf')
    pdf = Path(source)
    directory = Path(store.E.OUT).resolve()
    path = directory / code / 'segments.jsonl'
    if path.parent.resolve() != path.parent or path.is_symlink() or not path.is_file():
        raise SkipBook('missing_or_unsafe_segments')
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    try:
        rows = [(index, json.loads(line.decode('utf-8'), object_pairs_hook=unique_keys))
                for index, line in enumerate(lines) if line.strip()]
        if any(not isinstance(row, dict) for _, row in rows):
            raise ValueError('segment must be an object')
    except (ValueError, UnicodeError) as exc:
        raise SkipBook('unreadable_segments') from exc
    report['segments'] = len(rows)
    if all(row.get('source_page') not in (None, '') for _, row in rows):
        report['skips'] = {'has_page': len(rows)} if rows else {}
        return None
    anchors = reviewed_anchors(code)
    anchor_counts = Counter(anchor for _, row in rows for anchor in segment_anchors(row))
    texts = Counter(normalize(row['文本']) for _, row in rows if isinstance(row.get('文本'), str))
    candidates = []
    skips = Counter()
    for index, row in rows:
        text = normalize(row['文本']) if isinstance(row.get('文本'), str) else ''
        if row.get('source_page') not in (None, ''):
            skips['has_page'] += 1
        elif not isinstance(row.get('id'), str) or not row['id'].strip():
            skips['missing_segment_id'] += 1
        elif is_reviewed(row, anchors):
            skips['reviewed_segment'] += 1
        elif row.get('source_method') == 'ocr' or row.get('source_ocr_status'):
            skips['ocr_segment'] += 1
        elif not text:
            skips['empty_segment_text'] += 1
        elif '\x00' in text:
            skips['unreadable_segment_text'] += 1
        elif any(anchor_counts[anchor] > 1 for anchor in segment_anchors(row)) or texts[text] > 1:
            skips['duplicate_segment'] += 1
        else:
            candidates.append((index, row, text))
    report['skips'] = skips
    if not candidates:
        return None
    try:
        pages, original_sha = native_pages(pdf)
    except SkipBook:
        raise
    except Exception as exc:
        raise SkipBook('unreadable_original_pdf') from exc
    unreadable = [index for index, page in enumerate(pages, 1) if page is None]
    report.update(physical_pages=len(pages), unreadable_pdf_pages=unreadable,
                  original_sha256=original_sha,
                  segments_sha256=hashlib.sha256(raw).hexdigest())
    if not any(pages):
        raise SkipBook('no_native_pdf_text')
    # A non-text page has unknown contents; it supplies no matches and prevents
    # stitching its two native-text neighbours into a false occurrence.
    pages = [page if page is not None else '\x00' for page in pages]
    page_ends = []
    total = 0
    for page in pages:
        total += len(page)
        page_ends.append(total)
    pages_text = ''.join(pages)
    changes = []
    for index, row, text in candidates:
        page, reason = unique_page(text, pages_text, page_ends)
        if page is None:
            skips[reason] += 1
            continue
        newline = b'\r\n' if lines[index].endswith(b'\r\n') else b'\n' if lines[index].endswith(b'\n') else b''
        lines[index] = json.dumps(dict(row, source_page=page), ensure_ascii=False).encode('utf-8') + newline
        changes.append((row['id'], segment_anchors(row), page))
    report['fillable'] = len(changes)
    return Plan(path, pdf, raw, original_sha, changes, b''.join(lines)) if changes else None


def replace_segments(path, content, original_stat):
    fd, temp = tempfile.mkstemp(prefix='.source-page-backfill-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            staged = os.fstat(handle.fileno())
            if (staged.st_uid, staged.st_gid) != (original_stat.st_uid, original_stat.st_gid):
                os.fchown(handle.fileno(), original_stat.st_uid, original_stat.st_gid)
            os.fchmod(handle.fileno(), stat.S_IMODE(original_stat.st_mode))
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def file_identity(info):
    return info.st_dev, info.st_ino, info.st_ctime_ns


def apply_book(code, plan, backup_root):
    with store._lock('enqueue-book-job'), store._lock('source-review-' + code), store._lock('library'):
        record = store.load_library()['books'].get(code) or {}
        if active_book_job(code, record.get('book')):
            raise SkipBook('active_book_job')
        original = store.original_pdf(code)
        if not original or Path(original) != plan.pdf:
            raise SkipBook('original_changed')
        pdf_identity = file_identity(plan.pdf.lstat())
        if pdf_sha(plan.pdf) != plan.original_sha or file_identity(plan.pdf.lstat()) != pdf_identity:
            raise SkipBook('original_changed')
        original_stat = plan.path.lstat()
        if (not stat.S_ISREG(original_stat.st_mode) or plan.path.parent.resolve() != plan.path.parent or
                plan.path.read_bytes() != plan.raw):
            raise SkipBook('segments_changed')
        anchors = reviewed_anchors(code)
        if any(keys & anchors for _, keys, _ in plan.changes):
            raise SkipBook('review_history_changed')

        folder = backup_root / code
        folder.mkdir(mode=0o700)
        backup = folder / 'segments.jsonl'
        replace_segments(backup, plan.raw, original_stat)
        store.write_json(str(folder / 'manifest.json'), {
            'original_sha256': plan.original_sha, 'segments_sha256': hashlib.sha256(plan.raw).hexdigest(),
            'changes': [{'segment_id': anchor, 'source_page': page} for anchor, _, page in plan.changes]})
        if active_book_job(code, record.get('book')):
            raise SkipBook('active_book_job')
        if file_identity(plan.pdf.lstat()) != pdf_identity:
            raise SkipBook('original_changed')
        if (file_identity(plan.path.lstat()) != file_identity(original_stat) or
                plan.path.read_bytes() != plan.raw):
            raise SkipBook('changed_before_replace')
        replace_segments(plan.path, plan.updated, original_stat)
    return str(backup)


def run(codes, apply):
    records = store.load_library()['books']
    backup_root = None
    reports = []
    for code in codes or sorted(records):
        record = records.get(code) or {}
        report = {'code': code, 'book': record.get('book', ''), 'segments': 0,
                  'fillable': 0, 'applied': 0, 'skips': {}, 'status': 'skip'}
        reports.append(report)
        try:
            if not store.CODE_RE.fullmatch(code) or not record:
                raise SkipBook('unknown_book')
            plan = plan_book(code, record, report)
            if plan is None:
                continue
            report['status'] = 'fillable'
            if apply:
                if backup_root is None:
                    base = Path(store.DATA) / 'source-page-backfill-backups'
                    base.mkdir(mode=0o700, exist_ok=True)
                    backup_root = Path(tempfile.mkdtemp(prefix='run-', dir=base))
                report['backup'] = apply_book(code, plan, backup_root)
                report.update(status='applied', applied=len(plan.changes))
        except SkipBook as exc:
            report.update(status='skip', reason=str(exc))
        except (OSError, ValueError) as exc:
            report.update(status='error', reason=type(exc).__name__)
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('books', nargs='*', metavar='BOOK', help='图书编号。留空时检查全部已登记图书。')
    parser.add_argument('--apply', action='store_true', help='备份后写入。默认只检查。')
    args = parser.parse_args(argv)
    reports = run(dict.fromkeys(args.books), args.apply)
    print(json.dumps({
        'mode': 'apply' if args.apply else 'dry_run',
        'totals': {'books': len(reports), 'fillable': sum(r['fillable'] for r in reports),
                   'applied': sum(r['applied'] for r in reports),
                   'errors': sum(r['status'] == 'error' for r in reports)},
        'books': reports,
    }, ensure_ascii=False, indent=2))
    return int(any(r['status'] == 'error' for r in reports))


if __name__ == '__main__':
    raise SystemExit(main())
