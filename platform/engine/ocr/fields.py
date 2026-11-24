# -*- coding: utf-8 -*-
"""封面/书名页字段抽取 + A/B/C 验收。

只做「识别 + 选块 + 交叉校验」，不做理解扩写：
  A：OCR 置信度够 + 与书目库/CIP 一致 -> 自动采用
  B：OCR 置信度够 + 没有独立源 -> 采用，标 source=ocr，抽样复核
  C：低置信 / 冲突 / 选不出 -> 进入人工
"""
import re
import unicodedata
from typing import Dict, List, Optional

from .types import OCRLine

SKIP_TITLE = ('出版社', '编著', '主编', '项目组', '基金', 'ISBN', '定价',
              '责任', '编委', '著', '译', '出版发行')


def norm_match(s: str) -> str:
    """匹配用归一：去空白、去标点、统一横线；只用于比对，不改展示值。"""
    s = unicodedata.normalize('NFKC', s or '')
    s = re.sub(r'[\s\u3000\xa0]+', '', s)
    s = re.sub(r'[—–―‐\-－·•“”‘’"\'（）()《》〈〉:：,，.。;；!！?？]', '', s)
    return s


def clean_text(s: str) -> str:
    s = re.sub(r'[\s\u3000\xa0]+', '', s or '')
    return s.strip('，,。；;：:·—-–_')


def is_vertical(line: OCRLine) -> bool:
    x0, y0, x1, y1 = line.bbox
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    return h >= w * 1.8 and h >= 60


def _union(boxes: List[List[float]]) -> List[float]:
    if not boxes:
        return []
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _title_candidates(lines: List[OCRLine]) -> List[OCRLine]:
    vertical = [x for x in lines if is_vertical(x) and x.score >= 0.3]
    cands = [x for x in vertical if not any(k in x.text for k in SKIP_TITLE)]
    if cands:
        # 竖排从右往左读：先按右边界降序，再按上边界升序
        cands.sort(key=lambda x: (-x.bbox[2], x.bbox[1]))
        return cands[:3]
    # 横排封面兜底：按字高（大字号）取，排除出版社/作者行
    cands = [x for x in lines if not any(k in x.text for k in SKIP_TITLE)
             and not ('出版社' in x.text)]
    cands.sort(key=lambda x: (-(x.bbox[3] - x.bbox[1]), x.bbox[1]))
    return cands[:3]


def _publisher(lines: List[OCRLine], library: Dict) -> Optional[OCRLine]:
    cands = [x for x in lines if '出版社' in x.text and not is_vertical(x)]
    if not cands:
        return None
    lib = (library or {}).get('publisher') or ''
    if lib:
        matched = [x for x in cands if norm_match(lib) == norm_match(x.text)
                   or norm_match(x.text) in norm_match(lib)]
        if matched:
            return max(matched, key=lambda x: x.score)
    # 没有书目库时：优先“...出版社”结尾、较长的行，避免“全国优秀出版社”这种宣传语
    cands.sort(key=lambda x: (not clean_text(x.text).endswith('出版社'),
                              -len(clean_text(x.text)), -x.score))
    return cands[0]


def _author(lines: List[OCRLine]) -> Optional[OCRLine]:
    cands = [x for x in lines if any(k in x.text for k in ('编著', '主编', '著', '译'))
             and '出版社' not in x.text]
    if not cands:
        return None
    cands.sort(key=lambda x: -x.score)
    return cands[0]


def extract(lines: List[OCRLine], page: int, library: Dict,
            engine: str = 'rapidocr', engine_version: str = '') -> Dict:
    """从一页 OCR 行里抽书名/出版社/作者；书名给 A/B/C 状态。"""
    title_lines = _title_candidates(lines)
    parts = [clean_text(x.text) for x in title_lines if clean_text(x.text)]
    title = '——'.join(parts) if len(parts) > 1 else (parts[0] if parts else '')
    conf = min([x.score for x in title_lines], default=0.0)
    pub = _publisher(lines, library or {})
    author = _author(lines)
    lib_title = (library or {}).get('book') or ''
    matched = bool(lib_title and title and (norm_match(title) == norm_match(lib_title)
                                           or norm_match(title) in norm_match(lib_title)
                                           or norm_match(lib_title) in norm_match(title)))
    if not title:
        status = 'C'
        note = 'OCR 未选出书名块'
    elif matched and conf >= 0.5:
        status = 'A'
        note = 'OCR 封面；与书目库书名一致（A 类自动采用）'
    elif conf >= 0.85:
        status = 'B'
        note = 'OCR 封面；无书目库一致项，按 OCR 置信度采用（B 类抽样复核）'
    else:
        status = 'C'
        note = 'OCR 封面；置信度低或与书目库不一致（C 类人工）'

    evidence = []
    if title:
        evidence.append({
            'page': page,
            'quote': title,
            'parts': parts,
            'source': 'ocr',
            'engine': engine,
            'engine_version': engine_version,
            'confidence': round(float(conf), 4),
            'bbox': _union([x.bbox for x in title_lines]),
            'cross_check': 'library' if matched else 'none',
            'accept': status,
        })

    fields = {
        'book_title': {
            'value': title,
            'status': status,
            'confidence': round(float(conf), 4),
            'note': note,
            'evidence': evidence,
        }
    }
    if pub:
        fields['publisher'] = {
            'value': clean_text(pub.text),
            'status': 'A' if (library or {}).get('publisher') and
                      norm_match(pub.text) == norm_match(library.get('publisher', '')) else 'B',
            'confidence': round(float(pub.score), 4),
            'note': 'OCR 版权/封面页',
            'evidence': [{'page': page, 'quote': clean_text(pub.text), 'parts': [clean_text(pub.text)],
                          'source': 'ocr', 'engine': engine, 'engine_version': engine_version,
                          'confidence': round(float(pub.score), 4), 'bbox': pub.bbox}],
        }
    if author:
        fields['author'] = {
            'value': clean_text(author.text),
            'status': 'B',
            'confidence': round(float(author.score), 4),
            'note': 'OCR 封面署名，未拆角色',
            'evidence': [{'page': page, 'quote': clean_text(author.text), 'parts': [clean_text(author.text)],
                          'source': 'ocr', 'engine': engine, 'engine_version': engine_version,
                          'confidence': round(float(author.score), 4), 'bbox': author.bbox}],
        }
    return fields
