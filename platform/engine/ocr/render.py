# -*- coding: utf-8 -*-
"""PDF 页面渲染与原生文字层读取。

用 pypdfium2（PDFium，Apache-2.0/BSD 系）而不是 PyMuPDF：
  - PyMuPDF 是 AGPL-3.0，商用 SaaS/私有化交付要另外买商业许可；
  - PDFium 跨平台、无外部进程、Linux 容器里稳定。
"""
import os
from typing import Dict, Iterable, List

import pypdfium2 as pdfium


def page_count(pdf_path: str) -> int:
    doc = pdfium.PdfDocument(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def _page_size(page) -> tuple:
    try:
        w, h = page.get_size()
    except Exception:
        box = page.get_mediabox()
        w, h = box[2] - box[0], box[3] - box[1]
    return int(w), int(h)


def native_text(pdf_path: str, page_no: int) -> str:
    """读 PDF 原生文字层；没有文字层时返回空串。"""
    doc = pdfium.PdfDocument(pdf_path)
    try:
        page = doc[page_no - 1]
        textpage = page.get_textpage()
        try:
            return textpage.get_text_range() or ''
        finally:
            textpage.close()
    finally:
        doc.close()


def native_texts(pdf_path: str, pages: Iterable[int]) -> Dict[int, str]:
    doc = pdfium.PdfDocument(pdf_path)
    out: Dict[int, str] = {}
    try:
        for pno in pages:
            page = doc[pno - 1]
            textpage = page.get_textpage()
            try:
                out[pno] = textpage.get_text_range() or ''
            finally:
                textpage.close()
    finally:
        doc.close()
    return out


def render_pages(pdf_path: str, pages: Iterable[int], outdir: str,
                 dpi: int = 300) -> List[dict]:
    """把指定页渲染成 PNG。返回 [{page,path,width,height}]。"""
    os.makedirs(outdir, exist_ok=True)
    scale = float(dpi) / 72.0
    doc = pdfium.PdfDocument(pdf_path)
    out = []
    try:
        total = len(doc)
        for pno in pages:
            if pno < 1 or pno > total:
                continue
            page = doc[pno - 1]
            bitmap = page.render(scale=scale)
            try:
                pil = bitmap.to_pil()
                path = os.path.join(outdir, 'p%03d.png' % pno)
                pil.save(path, format='PNG')
                w, h = pil.size
                out.append({'page': pno, 'path': path, 'width': w, 'height': h})
            finally:
                bitmap.close()
    finally:
        doc.close()
    return out
