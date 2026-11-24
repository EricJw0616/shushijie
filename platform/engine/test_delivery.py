# -*- coding: utf-8 -*-
"""47 项交付台账的回归测试（不调模型）。"""
import sys

import delivery as D

FAILED = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond:
        FAILED.append(msg)


def test_books():
    for c in ('B56', 'B58', 'B59', 'B60'):
        rec = D.build(c)
        k = rec['counts']
        check(k['total'] == 47, '%s 47 项' % c)
        check(k['found'] + k['needs_review'] + k['missing'] == 47, '%s 状态和=47' % c)
        check(k['exported'] == k['found'] + k['needs_review'], '%s 导出=有值+待确认' % c)
        keys = [v['tag_key'] for v in rec['items'].values()]
        check(len(keys) == len(set(keys)), '%s 编号不重复' % c)
        check(all(v['tag_id'] for v in rec['items'].values()), '%s 都有标签ID' % c)


def test_flatten():
    for c in ('B56', 'B58', 'B59', 'B60'):
        rec = D.build(c)
        rows = D.flatten(rec)
        check(all(r['status'] != 'not_found' for r in rows), '%s 长表无缺项' % c)
        check(len(rows) >= rec['counts']['exported'], '%s 长表展开' % c)
        check(any(r['pack_code'] == 'P03' and r['status'] == 'needs_review' for r in rows),
              '%s 营销草稿待确认' % c)
        for r in rows:
            if r['status'] == 'found':
                ok = bool(r.get('evidence'))
                check(ok, '%s/%s 有证据' % (c, r['tag_key']))


def test_evidence():
    print('证据逐字校验')
    for c in ('B56', 'B58', 'B59', 'B60'):
        seg = D._segmap(c)
        rec = D.build(c)
        bad = []
        for r in D.flatten(rec):
            for ev in r.get('evidence') or []:
                q = ev.get('quote') or ''
                sid = ev.get('seg')
                if q and sid and q not in (seg.get(sid) or ''):
                    bad.append((r['tag_key'], sid))
        check(not bad, '%s 引文逐字存在%s' % (c, ('（坏 %s）' % bad) if bad else ''))


def test_export():
    print('导出文件')
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix='delivery-test-')
    try:
        outdir, books, anns, manifest = D.export_all(['B58', 'B60'], outdir=tmp)
        check(len(books) == 2, '两本')
        check(manifest['scope']['total'] == 47, '清单写 47')
        check(manifest['annotations'] == len(anns), '长表行数一致')
        check(len(anns) > 47, '长表有展开')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    test_books()
    test_flatten()
    test_evidence()
    test_export()
    print('\n%s' % ('全部通过' if not FAILED else '失败 %d 项：%s' % (len(FAILED), FAILED)))
    sys.exit(1 if FAILED else 0)
