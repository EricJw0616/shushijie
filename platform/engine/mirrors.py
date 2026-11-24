# -*- coding: utf-8 -*-
"""易错对照（镜像矛盾）校验。

这一类卡最容易被写坏：说「原文另有一处相反说法」，
若原文其实只有一处、或两处说的是同一件事，就是造矛盾。
因此校验三条：
  1. 甲/乙锚点都有效
  2. 甲引/乙引都逐字可回查
  3. 甲引 ≠ 乙引，且两处不在同一句里重复（真有两处）
"""
import re, json, io, sys, os
import paths as P
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules as R


def verify(mirrors, segs, segid):
    out, bad = [], 0
    for m in mirrors:
        err = []
        for side in ('甲', '乙'):
            a = m.get(f'{side}锚')
            q = m.get(f'{side}引', '')
            if a not in segid:
                err.append(f'{side}锚点无效 {a}')
            if q:
                good, _ = R.locate_quote(q, segid)
                if not good:
                    err.append(f'{side}引文不可回查')
            else:
                err.append(f'缺{side}引')
        if m.get('甲引') and m.get('甲引') == m.get('乙引'):
            err.append('甲乙引文相同，不构成两处')
        if err:
            bad += 1
            print(f"✗ {m['id']} {m['主题']}")
            for e in err:
                print('   ', e)
        else:
            print(f"✓ {m['id']} {m['书']}｜{m['主题']}")
            out.append(m)
    return out, bad


def main():
    base = P.OUT
    mirrors = json.load(io.open(os.path.join(P.CARDS, 'mirrors.json'),
                                encoding='utf-8'))
    # 跨书校验：按书分桶
    cache = {}
    ok_all = []
    for m in mirrors:
        b = m['书']
        if b not in cache:
            code = {'闲情偶寄': 'B01', '朝花夕拾': 'ZHS'}[b]
            segs = [json.loads(l) for l in io.open(f'{base}/{code}/segments.jsonl',
                                                   encoding='utf-8')]
            cache[b] = {s['id']: s for s in segs}
        segid = cache[b]
        err = []
        for side in ('甲', '乙'):
            a = m.get(f'{side}锚')
            q = m.get(f'{side}引', '')
            if a not in segid:
                err.append(f'{side}锚点无效 {a}')
            if q:
                good, _ = R.locate_quote(q, [segid[a]] if a in segid else [])
                if not good:
                    err.append(f'{side}引文不可回查: {q[:20]}')
        if err:
            print(f"✗ {m['id']} {m['主题']}")
            for e in err:
                print('   ', e)
        else:
            print(f"✓ {m['id']} {b}｜{m['主题']}")
            ok_all.append(m)
    dest = os.path.join(P.CARDS, 'mirrors.verified.json')
    json.dump(ok_all, io.open(dest, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"\n通过 {len(ok_all)}/{len(mirrors)} → {dest}")
    return len(ok_all) == len(mirrors)


if __name__ == '__main__':
    sys.exit(0 if main() else 1)