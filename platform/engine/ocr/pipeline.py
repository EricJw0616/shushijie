# -*- coding: utf-8 -*-
"""OCR 流水线：页面路由 -> 渲染 -> 识别 -> 字段抽取 -> 落盘。

产物（可直接被 delivery/publication 读取）：
  out/<code>/ocr/plan.json       每页动作（native/ocr）与原因
  out/<code>/ocr/pages.jsonl     每页识别文本 + 行 + bbox + 置信度
  out/<code>/ocr/fields.json     封面/书名页字段 + A/B/C 验收 + 证据
  out/<code>/ocr/manifest.json   引擎、版本、DPI、页范围
"""
import datetime
import json
import os
from typing import Dict, Iterable, List, Optional

from .fields import extract
from . import pubfields
from .provider import OCRProvider
from .rapid_provider import RapidOCRProvider
from .render import native_texts, render_pages
from .router import plan as plan_pages
from .types import OCRPage

DEFAULT_OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'out'))


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _write_jsonl(path: str, rows: Iterable[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def run(code: str, pdf_path: str, pages: List[int],
        library: Optional[Dict] = None,
        outdir: Optional[str] = None,
        dpi: int = 300,
        provider: Optional[OCRProvider] = None,
        force: Optional[Iterable[int]] = None) -> Dict:
    provider = provider or RapidOCRProvider()
    outdir = outdir or os.path.join(DEFAULT_OUT, code, 'ocr')
    os.makedirs(outdir, exist_ok=True)

    native = native_texts(pdf_path, pages)
    plan = plan_pages(pages, native, force=force)
    ocr_pages = [x['page'] for x in plan if x['action'] == 'ocr']
    rendered = {x['page']: x for x in render_pages(pdf_path, ocr_pages,
                                                   os.path.join(outdir, 'images'), dpi=dpi)}

    page_rows = []
    fields = {}
    for pno in ocr_pages:
        img = rendered.get(pno)
        if not img:
            continue
        lines = provider.recognize(img['path'], page=pno)
        page = OCRPage(page=pno, width=img['width'], height=img['height'], lines=lines,
                       engine=provider.name, engine_version=provider.version)
        page_rows.append(page.to_dict())
        if not fields:
            got = extract(lines, pno, library or {}, provider.name, provider.version)
            if got.get('book_title', {}).get('value'):
                fields = got

    _write_json(os.path.join(outdir, 'plan.json'), plan)
    pub = pubfields.write(page_rows, outdir)
    _write_jsonl(os.path.join(outdir, 'pages.jsonl'), page_rows)
    result = {
        'book_code': code,
        'pdf': os.path.abspath(pdf_path),
        'pages': pages,
        'ocr_pages': ocr_pages,
        'dpi': dpi,
        'engine': provider.name,
        'engine_version': provider.version,
        'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'fields': fields,
        'publication': pub,
    }
    _write_json(os.path.join(outdir, 'fields.json'), result)
    _write_json(os.path.join(outdir, 'manifest.json'), {
        k: result[k] for k in ('book_code', 'pdf', 'pages', 'ocr_pages', 'dpi',
                               'engine', 'engine_version', 'generated_at')
    })
    return result
