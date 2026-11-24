# -*- coding: utf-8 -*-
"""页面级路由：原生文字够好就不 OCR，缺字/乱码/指定页才 OCR。

原则：OCR 是补洞。整本无脑 OCR 又贵又把干净文本弄脏。
"""
import re
from typing import Dict, Iterable, List, Optional


def quality(text: str) -> str:
    t = re.sub(r'[\s\u3000\xa0]+', '', text or '')
    if len(t) < 10:
        return 'empty'
    bad = t.count('\ufffd') + len(re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', t))
    if bad / max(1, len(t)) > 0.01:
        return 'bad'
    return 'ok'


def plan(pages: Iterable[int], texts: Dict[int, str],
         force: Optional[Iterable[int]] = None,
         threshold: int = 10) -> List[dict]:
    """返回每页动作：native / ocr。force 里的页无条件 OCR。"""
    force_set = set(force or [])
    out = []
    for pno in pages:
        q = quality(texts.get(pno, ''))
        if pno in force_set:
            action = 'ocr'
            reason = '指定页强制 OCR（封面/书名页/难页）'
        elif q == 'empty':
            action = 'ocr'
            reason = '原生文字层为空'
        elif q == 'bad':
            action = 'ocr'
            reason = '原生文字层乱码/异常字符'
        elif len(re.sub(r'\s+', '', texts.get(pno, ''))) < threshold:
            action = 'ocr'
            reason = '原生文字过短'
        else:
            action = 'native'
            reason = '原生文字可用'
        out.append({'page': pno, 'native_quality': q, 'action': action, 'reason': reason})
    return out
