# -*- coding: utf-8 -*-
"""可部署的 OCR 子系统（RapidOCR / PP-OCR，ONNX Runtime）。"""
from .pipeline import run
from .rapid_provider import RapidOCRProvider

__all__ = ['run', 'RapidOCRProvider']
