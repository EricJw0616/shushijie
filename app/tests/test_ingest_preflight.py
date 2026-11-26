from pathlib import Path
import sys
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ingest
import probe


class PreflightTests(unittest.TestCase):
    def test_valid_unicode_text_does_not_become_garbled_chinese(self):
        body = 'Les médicaments coûtent cher. Études et résultats.'
        self.assertEqual(ingest._decode_bytes(body.encode('utf-8')), body)
        self.assertEqual(ingest._decode_bytes(body.encode('utf-16')), body)
        with self.assertRaisesRegex(ingest.IngestError, '编码'):
            ingest._decode_bytes(bytes(range(32)) * 30)

    def test_preflight_and_ingest_agree_for_complete_text_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'book.txt'
            path.write_text('This book is written in English. ' * 15, encoding='utf-8')
            for read in (lambda: probe.probe_file(path, 'txt', path.name), lambda: ingest.extract(path, 'txt')):
                with self.assertRaisesRegex(ingest.IngestError, '至少 25%'):
                    read()
            path.write_text('中文正文的每一句都保存原始文字和结尾标点。' * 20, encoding='utf-8')
            self.assertTrue(probe.probe_file(path, 'txt', path.name)['ok'])
            self.assertGreaterEqual(ingest.extract(path, 'txt')['han'], ingest.MIN_HAN_CHARS)

    def test_partial_sample_uses_incremental_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'book.txt'
            path.write_bytes('中文'.encode())
            sample = probe._read_text(path, limit=5)
        self.assertEqual(sample['text'], '中')
        self.assertFalse(sample['complete_body'])

    def test_scans_and_foreign_text_are_reported_separately(self):
        warnings = []
        self.assertTrue(probe._check_pdf_sample({'pages': 8, 'sample_chars': [0, 1],
                                                 'sample_han': [0, 1]}, warnings))
        self.assertIn('扫描件', warnings[0])
        warnings = []
        self.assertFalse(probe._check_pdf_sample({'pages': 9, 'sample_chars': [300, 300],
                                                  'sample_han': [0, 0]}, warnings))
        self.assertIn('非中文', warnings[0])
        with self.assertRaisesRegex(ingest.IngestError, '非中文'):
            probe._check_pdf_sample({'pages': 2, 'sample_chars': [300, 300],
                                     'sample_han': [0, 0]}, [])

    def test_word_body_preflight_uses_same_table_text_as_ingest(self):
        from docx import Document

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'book.docx'
            doc = Document()
            doc.add_paragraph('Sample')
            table = doc.add_table(rows=1, cols=1)
            table.cell(0, 0).text = '这是中文正文，内容包含书中真实句子。' * 20
            doc.save(path)
            self.assertTrue(probe.probe_file(path, 'docx', path.name)['ok'])
            self.assertGreaterEqual(ingest.extract(path, 'docx')['han'], ingest.MIN_HAN_CHARS)
