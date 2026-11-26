#!/usr/bin/env python3
"""Inspect stored book sources and emit a JSON repair plan.

Use --verify-numbers to additionally compare individual candidate pages with the
original PDF. This may take time on a large library. Chapter and paragraph
proposals are for review: an unchanged ID can point at different text after a
chapter rebuild. Inspection is read-only by default. --apply-numbers applies
only the numeric candidates through the application's audited source writer.
"""
import argparse
import bisect
import collections
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'platform' / 'engine'))

import atlas
import pipeline
import structure
import tocclean
import wash


def read_rows(path):
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def compact(value):
    return ''.join(value.split())


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def original_pdf(record, app_data):
    if record.get('source_format') != 'pdf':
        return None
    for name in ('original_job', 'last_job'):
        job = str(record.get(name) or '')
        if re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}', job):
            path = app_data / 'uploads' / job / 'original.pdf'
            if path.is_file():
                return path
    return None


def numerical_pages(layout):
    """Loose exposure screen; a standalone number can still be a footer."""
    mentions = collections.Counter()
    for page in layout:
        height = page.get('h') or 0
        if page.get('non_body') or not height:
            continue
        for line in page.get('lines', []):
            if (re.fullmatch(r'[0-9]{1,16}', line['t'].strip())
                    and height * .09 < line['top'] < height * .89
                    and line['k'] in ('body', 'header')):
                mentions[page['page']] += 1
    return mentions


def _page_body(page):
    text = atlas.pages_to_text([page], mark_pages=True)
    return compact(''.join(line for _, line in structure.lines_of(text)))


def _numeric_insertions(before, after):
    """Return only numeric insertions between exact matching source contexts."""
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    ops = matcher.get_opcodes()
    stable = [index for index, (kind, start, end, _, _) in enumerate(ops)
              if kind == 'equal' and (end - start >= 6 or index in (0, len(ops) - 1))]
    for left_index, right_index in zip(stable, stable[1:]):
        left, right = ops[left_index], ops[right_index]
        begin, end = left[2], right[1]
        before_start, before_end = max(left[1], begin - 18), min(right[2], end + 18)
        minimum = 12 if left_index == 0 or right_index == len(ops) - 1 else 18
        if begin - before_start < 2 or before_end - end < 2 or before_end - before_start < minimum:
            continue
        operations = []
        for kind, start, _, new_start, new_end in ops[left_index + 1:right_index]:
            if kind == 'equal':
                continue
            value = after[new_start:new_end]
            if kind != 'insert' or not re.fullmatch(r'[0-9]{1,16}', value):
                operations.clear()
                break
            operations.append((start - before_start, value))
        if operations:
            original = before[before_start:before_end]
            edited = original
            for offset, value in reversed(operations):
                edited = edited[:offset] + value + edited[offset:]
            yield original, edited, operations


def _locate_numeric_edits(rows, page, sequences):
    """Locate exact paired context against persisted text with unique anchors."""
    normalized = [compact(row['文本']) for row in rows]
    text = ''.join(normalized)
    starts = [0]
    for value in normalized:
        starts.append(starts[-1] + len(value))
    edits = collections.defaultdict(list)
    unavailable = collections.Counter()
    for key, source, operations in sequences:
        start = text.find(key)
        if start < 0:
            # The old chapter cut can omit a printed heading from the segment
            # corpus. Keep the original PDF context in the report, but allow
            # a shorter unique match after the heading when enough remains.
            trim = max(0, operations[0][0] - 4)
            if len(key) - trim >= 22:
                key = key[trim:]
                operations = [(offset - trim, value) for offset, value in operations]
                start = text.find(key)
        if start < 0:
            unavailable['context_missing'] += 1
            continue
        if text.find(key, start + 1) >= 0:
            unavailable['context_ambiguous'] += 1
            continue
        for relative, value in operations:
            position = start + relative
            index = bisect.bisect_right(starts, position) - 1
            row = rows[index]
            if row.get('source_page') not in (None, page):
                unavailable['page_mismatch'] += 1
                continue
            if row.get('source_review'):
                unavailable['existing_manual_review'] += 1
                continue
            offsets = [i for i, char in enumerate(row['文本']) if not char.isspace()]
            offset = offsets[position - starts[index]]
            edits[index].append((offset, value, source))
    proposals = []
    for index, operations in sorted(edits.items()):
        row = rows[index]
        counts = collections.Counter(offset for offset, _, _ in operations)
        if any(count > 1 for count in counts.values()):
            unavailable['conflicting_insertions'] += len(operations)
            continue
        proposed = row['文本']
        for offset, value, _ in sorted(operations, reverse=True):
            proposed = proposed[:offset] + value + proposed[offset:]
        proposals.append({'anchor': row['id'], 'page': page, 'current_page': row.get('source_page'),
                          'before': row['文本'], 'after': proposed,
                          'source_contexts': list(dict.fromkeys(source for _, _, source in operations))})
    return proposals, unavailable


def verify_numeric_pages(path, layout, page_numbers, rows):
    by_page = {page['page']: page for page in layout}
    proposals, reasons = [], collections.Counter()
    source_hash = file_sha256(path)
    fresh_layout = atlas.layout_pdf(path, page_numbers=page_numbers)
    for page in fresh_layout:
        before, after = _page_body(by_page[page['page']]), _page_body(page)
        found, unavailable = _locate_numeric_edits(rows, page['page'], _numeric_insertions(before, after))
        proposals.extend(found)
        reasons.update(unavailable)
    if len(fresh_layout) != len(page_numbers) or file_sha256(path) != source_hash:
        raise ValueError('The original PDF changed or a selected page could not be read')
    counts = collections.Counter(item['anchor'] for item in proposals)
    reasons['anchor_claimed_by_multiple_pages'] += sum(n for n in counts.values() if n > 1)
    return {'pages_checked': len(fresh_layout), 'source_pdf_sha256': source_hash, 'skipped': dict(reasons),
            'candidate_corrections': [item for item in proposals if counts[item['anchor']] == 1]}


def plan_book(folder, raw_folder, app_data, record, verify=False, max_pages=30, selected_pages=None):
    book = json.loads((folder / 'book.json').read_text(encoding='utf-8'))
    segment_file = folder / 'segments.jsonl'
    segment_hash = file_sha256(segment_file)
    old_rows = read_rows(segment_file)
    if file_sha256(segment_file) != segment_hash:
        raise ValueError('The stored segments changed during inspection')
    old_outline = read_rows(folder / 'outline.jsonl')
    result = {'code': folder.name, 'title': book.get('book') or record.get('book') or '',
              'stored_segments_sha256': segment_hash,
              'stored_segments': len(old_rows), 'stored_chapters': len(old_outline)}
    filename = Path(book.get('源文件') or '').name
    path = raw_folder / filename
    if not filename or not path.is_file():
        result['reason'] = 'cached_source_unavailable'
        return result
    layout_path = path.with_suffix('.layout.jsonl')
    source, supplied_punctuation = wash.load_ex(str(path))
    cleaned, removed = tocclean.clean(source)
    chapter_plan = structure.probe(cleaned, layout_path=str(layout_path))
    if chapter_plan['mode'] != 'pdf_outline':
        _, _, people, _ = pipeline.content_sources(str(path), cleaned)
        if people:
            chapter_plan = pipeline._people_plan(cleaned, people) or chapter_plan
    new_outline = structure.outline(cleaned, chapter_plan)
    continuous = (not new_outline and not supplied_punctuation and not removed['删除行数']
                  and structure.continuous_short_body(cleaned))
    staged, _ = wash.build(cleaned, folder.name, [(title, index) for title, index, _ in new_outline],
                           layout_path=str(layout_path), continuous_body=continuous)
    old = {row['id']: (row['篇'], row['文本'], row.get('source_page')) for row in old_rows}
    new = {row['id']: (row['篇'], row['文本'], row.get('source_page')) for row in staged}
    chapter_audit = tocclean.audit(old_rows, old_outline, source)
    affected = [anchor for anchor, data in old.items() if anchor not in new or new[anchor][:2] != data[:2]]
    old_titles = [row['篇'] for row in old_outline]
    new_titles = [title for title, _, _ in new_outline]
    structure_review = chapter_audit['结构待复核'] or old_titles != new_titles or continuous
    result['chapters'] = {'current_audit': chapter_audit, 'staged_count': len(new_outline),
                          'staged_short_body': continuous, 'needs_structure_review': bool(structure_review),
                          'added_titles': [title for title in new_titles if title not in old_titles],
                          'removed_titles': [title for title in old_titles if title not in new_titles],
                          'stored_anchors_changed_or_removed': len(affected),
                          'affected_anchor_examples': affected[:8]}
    if not layout_path.is_file():
        result['numbers'] = {'reason': 'cached_pdf_layout_unavailable'}
        return result
    layout = read_rows(layout_path)
    pages = numerical_pages(layout)
    result['numbers'] = {'layout_pages': len(layout), 'candidate_pages': len(pages),
                         'candidate_lines': sum(pages.values())}
    if not pages and not selected_pages:
        result['numbers']['reason'] = 'no_matching_numeric_layout_pattern'
    elif not verify:
        result['numbers']['reason'] = 'original_pdf_not_checked'
    else:
        pdf = original_pdf(record, app_data)
        if pdf is None:
            result['numbers']['reason'] = 'original_pdf_unavailable'
        else:
            selected = selected_pages or sorted(pages, key=lambda number: (-pages[number], number))[:max_pages]
            available = {page['page'] for page in layout}
            if not all(page in available for page in selected):
                raise ValueError('Selected page is not in the cached layout')
            result['numbers'].update(verify_numeric_pages(pdf, layout, selected, old_rows))
            result['numbers']['pages_unchecked'] = len(set(pages) - set(selected))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=REPO)
    parser.add_argument('--raw', type=Path, help='Override the directory containing TXT and layout JSONL.')
    parser.add_argument('--out', type=Path, help='Override the directory containing the book outputs.')
    parser.add_argument('--app-data', type=Path, help='Override the directory containing library.json and uploads.')
    parser.add_argument('--book', action='append', help='Optional book code. Repeat to limit scope.')
    parser.add_argument('--verify-numbers', action='store_true', help='Compare candidate text with native PDF glyphs.')
    parser.add_argument('--apply-numbers', action='store_true',
                        help='Apply verified numeric candidates to explicitly selected books through the source writer.')
    parser.add_argument('--max-pages-per-book', type=int, default=30)
    parser.add_argument('--page', action='append', type=int, help='Select a physical PDF page with one --book.')
    args = parser.parse_args()
    if args.max_pages_per_book < 1:
        parser.error('--max-pages-per-book must be positive')
    if args.page and (not args.verify_numbers or len(args.book or []) != 1 or min(args.page) < 1):
        parser.error('--page requires one --book, --verify-numbers and positive physical page numbers')
    if args.apply_numbers and (not args.verify_numbers or not args.book):
        parser.error('--apply-numbers requires --verify-numbers and explicit --book selections')
    raw = args.raw or args.root / '书库分类' / 'raw'
    out = args.out or args.root / 'platform' / 'out'
    app_data = args.app_data or args.root / 'app' / 'data'
    if args.apply_numbers:
        if args.root.resolve() != REPO or args.raw or args.out or args.app_data:
            parser.error('--apply-numbers uses the current application paths; path overrides are read-only')
        sys.path.insert(0, str(REPO / 'app'))
        import engine_bridge
        import source_review
        import store

        active = engine_bridge.RAW, engine_bridge.OUT, store.DATA
        if tuple(Path(path).resolve() for path in active) != tuple(path.resolve() for path in (raw, out, app_data)):
            parser.error('--apply-numbers paths differ from the current application data paths')
    registry = app_data / 'library.json'
    books = json.loads(registry.read_text(encoding='utf-8')).get('books', {}) if registry.is_file() else {}
    reports = []
    codes = set(args.book or books)
    if not codes:
        codes = {p.parent.name for p in out.glob('*/book.json')}
    for code in sorted(codes):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', code):
            parser.error(f'invalid book code: {code}')
        try:
            reports.append(plan_book(out / code, raw, app_data, books.get(code, {}), args.verify_numbers,
                                     args.max_pages_per_book, sorted(set(args.page or []))))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reports.append({'code': code, 'reason': 'cannot_inspect_book', 'error': str(exc)})
    if args.apply_numbers:
        for report in reports:
            numbers = report.get('numbers') or {}
            candidates = numbers.get('candidate_corrections') or []
            if not numbers.get('source_pdf_sha256') or not candidates:
                report['application'] = {'status': 'skipped', 'reason': numbers.get('reason', 'no_verified_candidates')}
                continue
            try:
                report['application'] = {'status': 'applied', 'result': source_review.apply_number_repairs(
                    report['code'], report['stored_segments_sha256'], numbers['source_pdf_sha256'], candidates)}
            except (OSError, ValueError) as exc:
                report['application'] = {'status': 'blocked', 'reason': str(exc)}
    print(json.dumps({'read_only': not args.apply_numbers, 'books': reports}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
