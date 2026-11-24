# -*- coding: utf-8 -*-
"""OCR 引擎接口。

商用上不把任何一家引擎写死：
  - RapidOCR / PP-OCR：默认生产引擎，Linux/CPU/GPU 都能跑，Apache-2.0；
  - PaddleOCR 原生、云 OCR：以后按同一接口接；
  - macOS Vision 只允许在开发机上做验证，不得作为生产依赖。
"""
from abc import ABC, abstractmethod
from typing import List

from .types import OCRLine


class OCRProvider(ABC):
    name = 'base'
    version = ''

    @abstractmethod
    def recognize(self, image_path: str, page: int = 0) -> List[OCRLine]:
        """识别一张页面图，返回行级文本 + 坐标 + 置信度。"""
        raise NotImplementedError
