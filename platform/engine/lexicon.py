# -*- coding: utf-8 -*-
"""预设查询库：五类专名的词表与匹配。

目录：<项目>/lexicon/
  place.jsonl    地名（现代行政区 + 历史地名）
  org.jsonl      机构（官署、学校、出版社、科学院）
  object.jsonl   器物（礼器、农具、家具、器物名）
  animal.jsonl   动物
  plant.jsonl    植物

每行：{"name":"翰林院","src":"manual|admin|corpus","note":""}

匹配顺序永远是：词典命中 > 模型判断。词典命中记 source=词典，否则 source=模型。
词典会随用法增长（add 落盘），但**只收经过逐字校验的真名**。
"""
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, 'lexicon')
CATS = ('country', 'province', 'region', 'city', 'district', 'landmark', 'nature',
        'org', 'object', 'animal', 'plant')
CN = {'country': '国家', 'province': '省份', 'region': '区域/大区', 'city': '城市',
      'district': '区县', 'landmark': '道路/地标', 'nature': '自然地理', 'org': '机构',
      'object': '器物', 'animal': '动物', 'plant': '植物'}

_CACHE = {}


def _path(cat):
    return os.path.join(DIR, cat + '.jsonl')


def load(cat, refresh=False):
    if not refresh and cat in _CACHE:
        return _CACHE[cat]
    words = {}
    try:
        with io.open(_path(cat), encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get('name'):
                    words[o['name']] = o
    except Exception:
        pass
    _CACHE[cat] = words
    return words


def all_words():
    out = {}
    for c in CATS:
        out.update(load(c))
    return out


def match(name, cats=None):
    """返回命中的类别（优先按传入顺序）；没命中返回 None。
    繁体名先归一成简体再查——古籍输出是繁体，词表是简体。"""
    name = (name or '').strip()
    if not name:
        return None
    cands = [name]
    try:
        import zh
        s = zh.to_simplified(name)
        if s != name:
            cands.append(s)
    except Exception:
        pass
    for c in (cats or CATS):
        words = load(c)
        for n in cands:
            if n in words:
                return c
    return None


def add(cat, name, src='corpus', note=''):
    name = (name or '').strip()
    if not name or cat not in CATS:
        return False
    words = load(cat)
    if name in words:
        return False
    words[name] = {'name': name, 'src': src, 'note': note}
    os.makedirs(DIR, exist_ok=True)
    with io.open(_path(cat), 'a', encoding='utf-8') as fp:
        fp.write(json.dumps(words[name], ensure_ascii=False) + '\n')
    return True


def stats():
    return {CN[c]: len(load(c)) for c in CATS}


if __name__ == '__main__':
    print(stats())
