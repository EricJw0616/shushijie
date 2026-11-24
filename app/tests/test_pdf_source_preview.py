"""Physical page previews are bounded, read-only, and reject invalid requests."""
import hashlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from reportlab.pdfgen import canvas

import pdf_source_preview as preview


class PdfSourcePreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'original.pdf')
        pdf = canvas.Canvas(self.path, pagesize=(3000, 1000))
        pdf.setFillColorRGB(1, 0, 0)
        pdf.rect(0, 0, 3000, 1000, fill=1, stroke=0)
        pdf.showPage()
        pdf.setPageSize((400, 800))
        pdf.setFillColorRGB(0, 0, 1)
        pdf.rect(0, 0, 400, 800, fill=1, stroke=0)
        pdf.showPage()
        pdf.save()
        original = patch.object(preview.store, 'original_pdf', return_value=self.path)
        self.original = original.start()
        self.addCleanup(original.stop)

    def test_real_physical_pages_keep_orientation_and_limit_dimensions(self):
        for number, landscape, color in [(1, True, (255, 0, 0)), ('2', False, (0, 0, 255))]:
            with self.subTest(page=number):
                result = preview.render('B69', number)
                self.assertTrue(result.startswith(b'\x89PNG\r\n\x1a\n'))
                with Image.open(io.BytesIO(result)) as image:
                    self.assertLessEqual(max(image.size), preview.MAX_EDGE)
                    self.assertEqual(image.width > image.height, landscape)
                    self.assertEqual(image.convert('RGB').getpixel((image.width // 2, image.height // 2)), color)
        self.original.assert_called_with('B69')

    def test_preview_never_changes_pdf_or_writes_sidecar_files(self):
        with open(self.path, 'rb') as source:
            before = hashlib.sha256(source.read()).digest()
        preview.render('B69', 1)
        with open(self.path, 'rb') as source:
            self.assertEqual(hashlib.sha256(source.read()).digest(), before)
        self.assertEqual(os.listdir(self.tmp.name), ['original.pdf'])

    def test_invalid_numbers_are_rejected_before_resolving_pdf(self):
        for number in [0, -1, '0', '-1', '01', '1.0', 1.0, True, False, None, '',
                       ' 1', '1 ', {}, [], '1e2', '١', 10 ** 10]:
            with self.subTest(page=number), self.assertRaisesRegex(ValueError, '页码'):
                preview.render('B69', number)
        self.original.assert_not_called()

    def test_missing_original_and_invalid_book_have_clear_errors(self):
        self.original.return_value = None
        with self.assertRaisesRegex(FileNotFoundError, '原件'):
            preview.render('B69', 1)
        with self.assertRaisesRegex(ValueError, '编号'):
            preview.render('../B69', 1)
        self.original.return_value = os.path.join(self.tmp.name, 'missing.pdf')
        with self.assertRaises(FileNotFoundError):
            preview.render('B69', 1)

    def test_page_beyond_actual_pdf_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '共 2 页'):
            preview.render('B69', 3)

    def test_corrupt_pdf_reports_a_recoverable_preview_error(self):
        with open(self.path, 'wb') as target:
            target.write(b'not a PDF')
        with self.assertRaisesRegex(RuntimeError, '无法读取'):
            preview.render('B69', 1)


if __name__ == '__main__':
    unittest.main()
