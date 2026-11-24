from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))

import ingest
import pdf_ocr


PROSE = '这段扫描正文需要保留清楚的原书页码，以便编辑回到原页核对。'


def native_page(number, text, **metadata):
    return dict(page=number, w=600, h=800, lines=[{'t': text, 'k': 'body', 'col': 0}], **metadata)


def ocr_lines(count, score=.96, width=.72):
    return [{'text': PROSE, 'score': score,
             'box': [.10, .15 + i*.08, .10 + width, .18 + i*.08]} for i in range(count)]


class PdfOcrTests(unittest.TestCase):
    def test_scanned_and_corrupt_pages_use_ocr_and_keep_original_pagination(self):
        pages = [native_page(1, PROSE*8), native_page(2, '', picture_dominant=True),
                 native_page(3, '(cid:123)'*25), native_page(4, '', tables=[{'label': '表格'}])]
        native = list(pages[0]['lines'])
        atlas = ingest._atlas()
        progress = []
        with tempfile.NamedTemporaryFile() as source:
            source.write(b'%PDF-1.4')
            source.flush()
            with patch.object(atlas, 'layout_pdf', return_value=pages), \
                 patch.object(pdf_ocr, 'worker_python', return_value='fake-python'), \
                 patch.object(pdf_ocr, '_read_worker', return_value=iter([
                     {'page': 2, 'lines': ocr_lines(6)}, {'page': 3, 'lines': ocr_lines(3, .80)},
                 ])) as worker:
                result = ingest.extract(source.name, 'pdf', lambda done, total: progress.append((done, total)))
        worker.assert_called_once_with(source.name, [2, 3], 'fake-python')
        self.assertEqual(result['ocr'], {'body': 1, 'review': 1})
        self.assertIn('<<<PAGE 2>>>', result['text'])
        self.assertNotIn('(cid:123)', result['text'])
        self.assertEqual(result['layout'][0]['lines'], native)
        self.assertEqual(result['layout'][1]['page'], 2)
        self.assertEqual(progress, [(0, 2), (1, 2), (2, 2)])
        self.assertIn('1 页扫描文字待核对', result['note'])
        self.assertEqual(result['page_issues'], {'review': [3]})

    def test_high_scores_on_small_fragments_are_not_treated_as_body(self):
        page = native_page(6, '', picture_dominant=True)
        fragments = [{'text': '画面小字', 'score': .99, 'box': [.10, .15, .22, .18]}] * 4
        pdf_ocr._apply(page, {'lines': fragments}, ingest._atlas())
        self.assertEqual(page['ocr']['status'], 'no_text')
        self.assertEqual(page['lines'][0]['t'], '')

    def test_missing_worker_can_retry_saved_scan(self):
        atlas = ingest._atlas()
        with tempfile.NamedTemporaryFile() as source:
            source.write(b'%PDF-1.4')
            source.flush()
            with patch.object(atlas, 'layout_pdf', return_value=[native_page(1, '', picture_dominant=True)]), \
                 patch.object(pdf_ocr, 'worker_python', return_value=None):
                with self.assertRaisesRegex(ingest.OCRProcessingError, '原文件重试'):
                    ingest.extract(source.name, 'pdf')

    def test_blank_pages_are_separate_from_missing_text_and_retries(self):
        pages = [native_page(i, '') for i in range(1, 4)]
        with patch.object(pdf_ocr, 'worker_python', return_value='fake-python'), \
             patch.object(pdf_ocr, '_read_worker', side_effect=[
                 iter([{'page': 1, 'blank': True}, {'page': 2, 'lines': []}, {'page': 3, 'failed': True}]),
                 iter([{'page': 3, 'lines': ocr_lines(6)}]),
             ]) as worker:
            result = pdf_ocr.recover_pages('test.pdf', pages, ingest._atlas())
        self.assertEqual(worker.call_args_list[1].args[1], [3])
        self.assertEqual(result, {'blank': 1, 'no_text': 1, 'body': 1})
        self.assertEqual(ingest._pdf_page_issues(pages), {'blank': [1], 'no_text': [2]})


if __name__ == '__main__':
    unittest.main()
