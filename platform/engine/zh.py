# -*- coding: utf-8 -*-
"""繁简归一：古籍输出是繁体，词表和停用词是简体，不归一就全对不上。

用 OpenCC 的 TSCharacters.txt（单字表），只做逐字转换，不处理词组歧义。
目的不是排版，是让「尚書省」能匹配到「尚书省」。
"""
import io
import os

_TABLE = None


def _load():
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        'lexicon', 'ts_characters.txt')
    table = {}
    try:
        with io.open(path, encoding='utf-8') as fp:
            for line in fp:
                if line.startswith('#') or '\t' not in line:
                    continue
                k, v = line.rstrip('\n').split('\t', 1)
                if k and v:
                    table[k] = v.split()[0]
    except Exception:
        pass
    _TABLE = table
    return table


def to_simplified(s):
    t = _load()
    return ''.join(t.get(ch, ch) for ch in (s or ''))
