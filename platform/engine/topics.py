# -*- coding: utf-8 -*-
"""主题卡校验 + 数字填充。

硬条件（任一不过就不出库）：
  1. 每层「引」必须逐字可回查
  2. 每层「锚点」必须有效
  3. 「对照」两侧锚点必须有效
  4. 依据段数、跨度、篇数由锚点实测算出，禁止手写

数字纪律（此前栽过跟头的地方）：
  - 依据段数 = 全部锚点（含对照）去重后的段数
  - 跨度 = 最大全局段序 - 最小全局段序（不是篇数，不是句数）
  - 篇数 = 锚点覆盖的篇数
  三者必须分开表述，页面上的数字必须能互相对上。
"""
import re, json, io, sys, os
import paths as P
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rules as R


def build_index(segs):
    """全局段序：按出现顺序编号，用于算跨度。"""
    idx = {}
    for i, s in enumerate(segs):
        idx[s['id']] = i
    return idx


def verify_topic(t, segs, idx):
    """返回 (问题列表, 统计)。统计里三个数分开算。"""
    probs = []
    anchors = []
    for k, layer in enumerate(t.get('层', []), 1):
        a = layer.get('锚点')
        if a not in idx:
            probs.append(f'层{k} 锚点无效 {a}')
        else:
            anchors.append(a)
        q = layer.get('引', '').strip()
        if q:
            good, _ = R.locate_quote(q, segs)
            if not good:
                probs.append(f'层{k} 引文不可回查')
    for j, c in enumerate(t.get('对照', []), 1):
        for side in ('甲锚', '乙锚'):
            a = c.get(side)
            if a not in idx:
                probs.append(f'对照{j} {side} 无效 {a}')
            else:
                anchors.append(a)

    uniq = sorted(set(anchors), key=lambda x: idx[x])
    span = (idx[uniq[-1]] - idx[uniq[0]]) if uniq else 0
    pian = len({segs[idx[a]]['篇'] for a in uniq}) if uniq else 0
    return probs, {'nseg': len(uniq), 'span': span, 'npian': pian,
                   'anchors': uniq}


def fill(t, stat, total_seg, total_pian):
    """把实测数字写回卡片，供页面直接渲染。"""
    t['依据段数'] = stat['nseg']
    t['跨度'] = stat['span']
    t['覆盖篇数'] = stat['npian']
    t['全书段数'] = total_seg
    t['全书篇数'] = total_pian
    # 覆盖率按段算，不按篇算——篇有大有小，按篇会夸大
    t['覆盖段比'] = round(stat['nseg'] * 100.0 / max(1, total_seg), 1)
    return t


def main(code, topic_file):
    base = P.OUT
    segs = [json.loads(l) for l in io.open(f'{base}/{code}/segments.jsonl',
                                           encoding='utf-8')]
    body = [s for s in segs if s['篇序'] > 0]
    idx = build_index(segs)
    topics = json.load(io.open(topic_file, encoding='utf-8'))
    out, allok = [], True
    for t in topics:
        probs, stat = verify_topic(t, segs, idx)
        if probs:
            allok = False
            print(f"✗ {t['id']} {t['主题'][:20]}")
            for p in probs:
                print('   ', p)
        else:
            t = fill(t, stat, len(body), len({s['篇'] for s in body}))
            print(f"✓ {t['id']} 依据{t['依据段数']}段 "
                  f"跨{t['覆盖篇数']}篇 跨度{t['跨度']} 覆盖{t['覆盖段比']}%")
            print(f"  {t['主题']}")
        out.append(t)
    # 写回带实测数字的版本
    dest = topic_file.replace('.json', '.verified.json')
    json.dump(out, io.open(dest, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"\n{'全部通过' if allok else '有失败项'} → {dest}")
    return allok


if __name__ == '__main__':
    ok = main(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)