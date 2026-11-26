import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

import backfill_source_pages as backfill


def write_pdf(path, pages):
    pdf = Canvas(str(path))
    for lines in pages:
        for index, line in enumerate(lines):
            pdf.drawString(50, 730 - index * 25, line)
        pdf.showPage()
    pdf.save()


def row(segment_id, text, **fields):
    return {'id': segment_id, '文本': text, **fields}


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        store = backfill.store
        self.data = base / 'app-data'
        self.data.mkdir()
        uploads = self.data / 'uploads'
        jobs = self.data / 'jobs'
        jobs.mkdir()
        out = base / 'out'
        book = out / 'B42'
        book.mkdir(parents=True)
        upload = uploads / '20261125-100000-f01234'
        upload.mkdir(parents=True)
        self.pdf = upload / 'original.pdf'
        self.segments = book / 'segments.jsonl'
        for owner, name, value in (
                (store, 'DATA', str(self.data)), (store, 'JOBDIR', str(jobs)),
                (store, 'UPLOADDIR', str(uploads)), (store, 'LIBFILE', str(self.data / 'library.json')),
                (store.E, 'OUT', str(out))):
            change = patch.object(owner, name, value)
            change.start()
            self.addCleanup(change.stop)
        self.record = {'book': 'Native PDF', 'source_format': 'pdf', 'status': 'ready',
                       'original_job': upload.name}
        store.write_json(store.LIBFILE, {'books': {'B42': self.record}})

    def write_segments(self, *segments):
        self.segments.write_bytes(b'\r\n\r\n'.join(
            json.dumps(s, ensure_ascii=False).encode('utf-8') for s in segments))
        self.segments.chmod(0o640)

    def test_dry_run_and_apply_only_write_the_unique_complete_physical_page(self):
        write_pdf(self.pdf, [[], ['A unique native segment.', 'Repeat passage.', 'Audited text.',
                                 'Already reviewed.', 'Duplicate segment text.', 'Cross page left'],
                            ['right part.', 'Repeat passage.', 'Original punctuation.', 'Existing location.']])
        lines = [
            row('unique', 'A unique native\nsegment.', source_page=None, metadata={'a': 1}),
            row('ambiguous', 'Repeat passage.'), row('journal', 'Audited text.'),
            row('reviewed', 'Already reviewed.', source_review={'id': 'already-reviewed'}),
            row('duplicate-a', 'Duplicate segment text.'), row('duplicate-b', 'Duplicate segment text.'),
            row('cross-page', 'Cross page left right part.'),
            row('altered', 'Original punctuation!'),
            row('existing', 'Existing location.', source_page=20),
        ]
        self.write_segments(*lines)
        original = self.segments.read_bytes()
        review_dir = self.data / 'source_reviews' / 'B42'
        review_dir.mkdir(parents=True)
        (review_dir / 'audit.json').write_text('{"anchor":"journal"}', encoding='utf-8')
        (review_dir / 'pages.json').write_text('{"2":{"status":"reviewed"}}', encoding='utf-8')
        (review_dir / 'ignored-quality.json').write_text('{"ignored":{"revision":"test"}}', encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(backfill.main(['B42']), 0)
        audit = json.loads(output.getvalue())
        self.assertEqual(audit['mode'], 'dry_run')
        report = audit['books'][0]
        self.assertEqual(report['original_sha256'], hashlib.sha256(self.pdf.read_bytes()).hexdigest())
        self.assertEqual(report['fillable'], 1)
        self.assertEqual(report['physical_pages'], 3)
        self.assertEqual(report['skips'], {'has_page': 1, 'cross_page_match': 1,
                                         'no_exact_match': 1, 'duplicate_segment': 2,
                                         'multiple_pdf_matches': 1, 'reviewed_segment': 2})
        self.assertEqual(self.segments.read_bytes(), original)
        self.assertFalse((self.data / 'source-page-backfill-backups').exists())
        result = backfill.run(['B42'], True)[0]
        self.assertEqual(result['applied'], 1)
        first, rest = self.segments.read_bytes().split(b'\r\n', 1)
        self.assertEqual(json.loads(first), dict(lines[0], source_page=2))
        self.assertEqual(rest, original.split(b'\r\n', 1)[1])
        backup = Path(result['backup'])
        self.assertEqual(backup.read_bytes(), original)
        manifest = json.loads((backup.parent / 'manifest.json').read_text())
        self.assertEqual(manifest['changes'], [{'segment_id': 'unique', 'source_page': 2}])
        self.assertEqual(stat.S_IMODE(self.segments.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o640)
        self.assertEqual(backfill.run(['B42'], True)[0]['applied'], 0)

    def test_apply_rechecks_original_and_segments_and_review_records(self):
        write_pdf(self.pdf, [['Match exactly.']])
        self.write_segments(row('target', 'Match exactly.'))
        original = self.segments.read_bytes()
        backup = self.data / 'backup'
        backup.mkdir()
        plan = backfill.plan_book('B42', self.record, {})
        write_pdf(self.pdf, [['Match exactly.', 'Original PDF changed.']])
        with self.assertRaisesRegex(backfill.SkipBook, 'original_changed'):
            backfill.apply_book('B42', plan, backup)
        plan = backfill.plan_book('B42', self.record, {})
        self.segments.write_bytes(original + b'\n')
        with self.assertRaisesRegex(backfill.SkipBook, 'segments_changed'):
            backfill.apply_book('B42', plan, backup)
        self.segments.write_bytes(original)
        review_dir = self.data / 'source_reviews' / 'B42'
        review_dir.mkdir(parents=True)
        (review_dir / 'audit.json').write_text('{"anchor":"target"}', encoding='utf-8')
        with self.assertRaisesRegex(backfill.SkipBook, 'review_history_changed'):
            backfill.apply_book('B42', plan, backup)
        self.assertEqual(list(backup.iterdir()), [])
        self.assertEqual(self.segments.read_bytes(), original)

    def test_busy_book_and_unreadable_or_missing_pdf_are_reported_as_skips(self):
        write_pdf(self.pdf, [['Match exactly.']])
        self.write_segments(row('target', 'Match exactly.'))
        plan = backfill.plan_book('B42', self.record, {})
        backup = self.data / 'backup'
        backup.mkdir()
        store = backfill.store
        job = store.new_job('upload', {'resume_code': 'B42', 'title': 'an earlier title'})
        self.assertEqual(backfill.run(['B42'], False)[0]['reason'], 'active_book_job')
        with self.assertRaisesRegex(backfill.SkipBook, 'active_book_job'):
            backfill.apply_book('B42', plan, backup)
        store.update_job(job['id'], status='done')
        self.pdf.write_bytes(b'not a PDF')
        self.assertEqual(backfill.run(['B42'], False)[0]['reason'], 'unreadable_original_pdf')
        self.pdf.unlink()
        self.assertEqual(backfill.run(['B42'], False)[0]['reason'], 'missing_original_pdf')

    def test_duplicate_or_overlapping_native_occurrences_are_never_assigned(self):
        write_pdf(self.pdf, [['aaaa', 'An independently visible ID.']])
        self.write_segments(row('id-a', 'aaa'), row('id-b', 'An independently visible ID.', 锚点='id-a'))
        result = backfill.run(['B42'], False)[0]
        self.assertEqual(result['skips'], {'duplicate_segment': 2})
        self.assertEqual(backfill.unique_page('aaa', 'aaaa', [4]), (None, 'multiple_pdf_matches'))

    def test_mixed_pdf_matches_native_page_and_reports_unreadable_scan(self):
        document = Canvas(str(self.pdf))
        document.drawString(50, 730, 'A native exact passage.')
        document.drawString(50, 710, 'Text before scan')
        document.showPage()
        document.drawImage(ImageReader(Image.new('RGB', (24, 24), (120, 0, 0))), 20, 80, 530, 680)
        document.drawString(50, 40, '11')
        document.showPage()
        document.drawString(50, 730, 'Text after scan')
        document.showPage()
        document.save()
        self.write_segments(row('certain', 'A native exact passage.'),
                            row('wrong_join', 'Text before scan Text after scan'),
                            row('printed_number', '11'))
        report = backfill.run(['B42'], False)[0]
        self.assertEqual(report['physical_pages'], 3)
        self.assertEqual(report['unreadable_pdf_pages'], [2])
        self.assertEqual(report['fillable'], 1)
        self.assertEqual(report['skips'], {'no_exact_match': 2})


if __name__ == '__main__':
    unittest.main()
