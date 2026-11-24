# -*- coding: utf-8 -*-
"""OCR 数据类型。

这些结构是「OCR 层」唯一对外的形状：页面、行、坐标、置信度。
上层字段抽取、证据落库、校验都只认这里，不认具体引擎。
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class OCRLine:
    text: str
    score: float
    box: List[List[float]]          # 4 点坐标，引擎原始值
    bbox: List[float]               # [x0, y0, x1, y1]，统一后的轴对齐框
    page: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'text': self.text,
            'score': round(float(self.score), 4),
            'box': [[round(float(x), 1), round(float(y), 1)] for x, y in self.box],
            'bbox': [round(float(v), 1) for v in self.bbox],
            'page': self.page,
        }


@dataclass
class OCRPage:
    page: int
    width: int
    height: int
    lines: List[OCRLine] = field(default_factory=list)
    engine: str = ''
    engine_version: str = ''
    elapsed: float = 0.0

    @property
    def text(self) -> str:
        return ' '.join(x.text for x in self.lines if x.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'page': self.page,
            'width': self.width,
            'height': self.height,
            'text': self.text,
            'lines': [x.to_dict() for x in self.lines],
            'engine': self.engine,
            'engine_version': self.engine_version,
            'elapsed': round(float(self.elapsed), 3),
        }
