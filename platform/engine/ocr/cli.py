# -*- coding: utf-8 -*-
"""OCR CLI。

示例：
  python -m ocr.cli --code B59 \
    --pdf ../uploads/.../original.pdf \
    --pages 5 --force \
    --library ../../app/data/library.json \
    --outdir ../out/B59/ocr
"""
import argparse
import json
import sys

from .pipeline import run


def parse_pages(s: str):
    pages = set()
    for part in str(s or '').split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    return sorted(pages)


def main(argv=None):
    ap = argparse.ArgumentParser(description='OCR a PDF page range and extract cover fields')
    ap.add_argument('--code', required=True, help='book code, e.g. B59')
    ap.add_argument('--pdf', required=True, help='PDF path')
    ap.add_argument('--pages', default='1', help='1,3,5-8')
    ap.add_argument('--force', action='store_true', help='force OCR on the given pages')
    ap.add_argument('--library', default='', help='library.json')
    ap.add_argument('--outdir', default='', help='output dir; default platform/out/<code>/ocr')
    ap.add_argument('--dpi', type=int, default=300)
    args = ap.parse_args(argv)

    library = {}
    if args.library:
        with open(args.library, encoding='utf-8') as fp:
            data = json.load(fp)
        library = (data.get('books') or {}).get(args.code) or {}
    pages = parse_pages(args.pages)
    result = run(args.code, args.pdf, pages, library=library,
                 outdir=args.outdir or None, dpi=args.dpi,
                 force=pages if args.force else None)
    print(json.dumps({
        'book_code': result['book_code'],
        'ocr_pages': result['ocr_pages'],
        'engine': result['engine'],
        'engine_version': result['engine_version'],
        'fields': {k: {'value': v.get('value'), 'status': v.get('status'),
                       'confidence': v.get('confidence'), 'note': v.get('note')}
                   for k, v in (result.get('fields') or {}).items()},
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
