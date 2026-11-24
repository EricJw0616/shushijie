# -*- coding: utf-8 -*-
"""RapidOCR（PP-OCR 模型，ONNX Runtime）生产适配器。

选它的原因：
  1. Linux / Windows / macOS 都能跑，不依赖 macOS 框架；
  2. ONNX Runtime，CPU 可部署；换 onnxruntime-gpu 即可上 GPU；
  3. 模型就是 PP-OCR 系列，中文/竖排/艺术字比 Tesseract 稳；
  4. Apache-2.0，商用友好；模型随包分发，不依赖外网。
"""
import importlib.metadata
from typing import List

from .provider import OCRProvider
from .types import OCRLine


def _version() -> str:
    for pkg in ('rapidocr-onnxruntime', 'rapidocr_onnxruntime'):
        try:
            return importlib.metadata.version(pkg)
        except Exception:
            continue
    return 'unknown'


class RapidOCRProvider(OCRProvider):
    name = 'rapidocr'

    def __init__(self, **kwargs):
        self.version = _version()
        self._kwargs = kwargs
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            # 默认参数就是 PP-OCR 检测 + 方向分类 + 识别。
            # 需要 GPU 时把 onnxruntime 换成 onnxruntime-gpu，并在这里传 providers。
            self._engine = RapidOCR(**self._kwargs)
        return self._engine

    def recognize(self, image_path: str, page: int = 0) -> List[OCRLine]:
        engine = self._get_engine()
        result = engine(str(image_path))
        if isinstance(result, tuple):
            result = result[0]
        lines: List[OCRLine] = []
        for item in result or []:
            if len(item) < 3:
                continue
            box, text, score = item[0], item[1], item[2]
            text = str(text or '').strip()
            if not text:
                continue
            pts = [[float(p[0]), float(p[1])] for p in box]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            lines.append(OCRLine(
                text=text,
                score=float(score),
                box=pts,
                bbox=[min(xs), min(ys), max(xs), max(ys)],
                page=page,
            ))
        return lines
