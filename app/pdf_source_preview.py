"""Read-only, bounded previews of physical pages in a book's original PDF."""
from contextlib import closing
import io
import math
import os
import re
import threading

import store


MAX_EDGE = 2200
# PDFium must not be called concurrently within this process.
_RENDER_LOCK = threading.Lock()


def render(code, page):
    """Return a PNG for one 1-based physical PDF page, without writing files.

    ValueError: invalid book code/page number or page outside the original PDF.
    FileNotFoundError: no accessible original PDF.
    RuntimeError: preview dependency unavailable or PDF cannot be rendered.
    """
    if not store.is_code(code):
        raise ValueError('图书编号无效。')
    if isinstance(page, bool) or not isinstance(page, (str, int)):
        raise ValueError('PDF 页码必须是从 1 开始的整数。')
    page_text = str(page)
    if not re.fullmatch(r'[1-9][0-9]{0,8}', page_text):
        raise ValueError('PDF 页码必须是从 1 开始的整数。')
    number = int(page_text)
    path = store.original_pdf(code)
    if not path or not os.path.isfile(path):
        raise FileNotFoundError('这本书没有可查看的 PDF 原件，或原件已移走。')

    try:
        import pypdfium2 as pdfium
    except ImportError as error:
        raise RuntimeError('原版页面预览暂不可用，请打开原版 PDF 核对。') from error

    with _RENDER_LOCK:
        try:
            document = pdfium.PdfDocument(path)
        except Exception as error:
            if not os.path.isfile(path):
                raise FileNotFoundError('这本书的 PDF 原件已移走。') from error
            raise RuntimeError('原版 PDF 无法读取，请打开原件检查文件是否完整或受密码保护。') from error
        with closing(document):
            if number > len(document):
                raise ValueError('PDF 共 %s 页，无法查看第 %s 页。' % (len(document), number))
            try:
                with closing(document[number - 1]) as source_page:
                    width, height = source_page.get_size()
                    if not all(math.isfinite(size) and size > 0 for size in (width, height)):
                        raise RuntimeError('原版 PDF 页面尺寸无效，请打开原件检查。')
                    scale = min(200 / 72, MAX_EDGE / max(width, height))
                    with closing(source_page.render(scale=scale)) as bitmap:
                        with bitmap.to_pil() as image:
                            # Rounding in the PDF renderer can add one pixel.
                            if max(image.size) > MAX_EDGE:
                                image.thumbnail((MAX_EDGE, MAX_EDGE))
                            with io.BytesIO() as output:
                                image.save(output, format='PNG')
                                return output.getvalue()
            except Exception as error:
                raise RuntimeError('原版第 %s 页预览失败，请打开原版 PDF 核对。' % number) from error
