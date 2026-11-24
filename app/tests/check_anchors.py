# -*- coding: utf-8 -*-
"""锚点自检：卡片与标签的锚点必须 100% 解析到原文段。

背景：一段原文有两个编号——`id`（B01-00-P05）与人类可读的 `锚点`（B01·前置·P05），
而 cards / tags 的「锚点」字段里存的是 `id`。按「锚点」字段直接 join 段会 0 命中，
而且不报错（静默丢内容）。这里把「必须能解析」固化成断言，改数据或改解析逻辑后跑一遍。

用法：
    python3 app/tests/check_anchors.py
    退出码 0 = 全部解析成功；1 = 有锚点解析不了（会打印前 10 条）。
"""
import json
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

import store  # noqa: E402


def iter_books():
    lib = store.sync_library()
    return sorted(lib.get('books', {}))


def check_cards(fail):
    path = os.path.join(store.E.LIB, 'cards_candidate.jsonl')
    total = ok = 0
    display_hits = 0
    if not os.path.exists(path):
        return total, ok, display_hits
    with open(path, encoding='utf-8') as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            total += 1
            code, anchor = row.get('码') or '', row.get('锚点') or ''
            if not code or not anchor:
                fail.append(('卡片缺码或锚点', row.get('id') or '?'))
                continue
            rows, by_id, by_disp = store._seg_rows(code)
            i, how = store.resolve_anchor(code, anchor, (rows, by_id, by_disp))
            if i is None:
                fail.append(('卡片锚点解析失败', '%s %s' % (row.get('id') or '?', anchor)))
            else:
                ok += 1
                if how == 'display':
                    display_hits += 1
    return total, ok, display_hits


def check_tags(fail):
    total = anchored = ok = 0
    for code, book in sorted(store.tags_index().items()):
        seg = store._seg_rows(code)
        for lv in ('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7'):
            for it in (book.get(lv) or []):
                total += 1
                anchor = it.get('锚点')
                if not anchor:
                    continue          # L0/L1/L2 多是全书统计量，本来就没有单段锚点
                anchored += 1
                i, _how = store.resolve_anchor(code, anchor, seg)
                if i is None:
                    fail.append(('标签锚点解析失败', '%s %s %s' % (code, lv, anchor)))
                else:
                    ok += 1
    return total, anchored, ok


def check_locate(sample=50):
    """随机抽卡片走一次“单段定位”，确认命中段就是被引用的那一段。"""
    path = os.path.join(store.E.LIB, 'cards_candidate.jsonl')
    anchors = []
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fp:
            for line in fp:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get('码') and row.get('锚点'):
                    anchors.append((row['码'], row['锚点']))
                if len(anchors) >= 4000:
                    break
    step = max(1, len(anchors) // max(1, sample))
    bad = []
    tested = 0
    for code, anchor in anchors[::step][:sample]:
        d = store.get_segment_at(code, anchor, 2)
        tested += 1
        if not d:
            bad.append((code, anchor, '无返回'))
            continue
        hit = [it for it in d['items'] if it['hit']]
        if len(hit) != 1 or hit[0]['seg_id'] != d['seg_id']:
            bad.append((code, anchor, '命中段不唯一'))
    return tested, bad


def main():
    fail = []
    books = iter_books()
    segments = 0
    for code in books:
        segments += len(store._seg_rows(code)[0])

    c_total, c_ok, c_display = check_cards(fail)
    t_total, t_anchored, t_ok = check_tags(fail)
    tested, locate_bad = check_locate()
    fail.extend(locate_bad)

    print('书 %d 本 / 原文 %d 段' % (len(books), segments))
    print('卡片 %d 条，锚点解析成功 %d 条（其中靠人类可读锚点兜底 %d 条）'
          % (c_total, c_ok, c_display))
    print('标签 %d 个，带锚点 %d 个，解析成功 %d 个' % (t_total, t_anchored, t_ok))
    print('单段定位抽检 %d 条，异常 %d 条' % (tested, len(locate_bad)))
    if fail:
        print('\n失败 %d 项，前 10 项：' % len(fail))
        for kind, detail in fail[:10]:
            print('  - %s：%s' % (kind, detail))
        return 1
    print('\nOK：所有锚点都能解析到原文段。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
