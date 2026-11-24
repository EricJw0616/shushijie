# -*- coding: utf-8 -*-
"""全库结构审计：目录污染、章号顺序、重复篇名。

只读，不改任何产物。输出：
  platform/结构审计报告.md
  platform/结构审计报告.json

用法：python3 engine/audit_structure.py
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P
import tocclean as TC


def jl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in io.open(path, encoding='utf-8', errors='replace')
            if l.strip()]


def main():
    canonical = {b.get('code') for b in
                 (json.load(io.open(os.path.join(P.OUT, 'books.json'), encoding='utf-8'))
                  if os.path.exists(os.path.join(P.OUT, 'books.json')) else [])}
    rows = []
    for d in sorted(os.listdir(P.OUT)):
        if d.startswith('.'):
            continue
        dp = os.path.join(P.OUT, d)
        if not os.path.isdir(dp) or d not in canonical:
            continue
        bj = os.path.join(dp, 'book.json')
        if not os.path.exists(bj):
            continue
        b = json.load(io.open(bj, encoding='utf-8'))
        segs = jl(os.path.join(dp, 'segments.jsonl'))
        out = jl(os.path.join(dp, 'outline.jsonl'))
        audit = b.get('结构审计') or TC.audit(segs, out)
        clean = b.get('目录清洗') or {}
        rows.append({
            '书码': b.get('code') or d,
            '书名': b.get('book') or d,
            '原型': b.get('原型'),
            '原型名': b.get('原型名'),
            '篇数': b.get('篇数'),
            '段数': b.get('段数'),
            '异常': bool(audit.get('异常')),
            '章号顺序异常': bool(audit.get('章号顺序异常')),
            '目录残留段': len(audit.get('目录残留段') or []),
            '重复篇名数': len(audit.get('重复篇名') or []),
            '章号序列': audit.get('章号序列') or [],
            '说明': audit.get('说明') or '',
            '目录清洗': clean,
        })
    abnormal = [r for r in rows if r['异常']]
    cleaned = [r for r in rows if (r['目录清洗'] or {}).get('删除行数')]
    dup = [r for r in rows if r['重复篇名数']]
    payload = {
        '生成时间': __import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'),
        '书数': len(rows),
        '异常书数': len(abnormal),
        '目录清洗书数': len(cleaned),
        '重复篇名书数': len(dup),
        '书': rows,
    }
    with io.open(os.path.join(P.PLATFORM, '结构审计报告.json'), 'w', encoding='utf-8') as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=1)

    L = []
    L.append('# 全库结构审计报告')
    L.append('')
    L.append('> 只读体检，不改产物。用于发现「目录被当成正文」「章号顺序错乱」「重复篇名」等问题。')
    L.append('')
    L.append('- 书数：**%d**' % len(rows))
    L.append('- 结构异常：**%d 本**' % len(abnormal))
    L.append('- 做过目录清洗：**%d 本**' % len(cleaned))
    L.append('- 有重复篇名：**%d 本**（同名诗/条目可能正常，需人工判断）' % len(dup))
    L.append('')
    L.append('## 结构异常')
    L.append('')
    if abnormal:
        L.append('| 书码 | 书名 | 异常 | 说明 |')
        L.append('|---|---|---|---|')
        for r in abnormal:
            L.append('| %s | %s | 目录残留 %d 段 / 章号异常 %s | %s |' % (
                r['书码'], r['书名'], r['目录残留段'],
                '是' if r['章号顺序异常'] else '否', r['说明']))
    else:
        L.append('没有发现结构异常。')
    L.append('')
    L.append('## 目录清洗记录')
    L.append('')
    if cleaned:
        L.append('| 书码 | 书名 | 删除行数 | 删除汉字 | 区块 | 清理后章节 |')
        L.append('|---|---|---:|---:|---|---|')
        for r in cleaned:
            c = r['目录清洗']
            blocks = '；'.join('%s–%s' % (x.get('起行'), x.get('止行'))
                               for x in (c.get('区块') or []))
            L.append('| %s | %s | %s | %s | %s | %s |' % (
                r['书码'], r['书名'], c.get('删除行数', 0), c.get('删除汉字', 0),
                blocks, ' → '.join(str(x) for x in (r['章号序列'] or [])[:4])))
    else:
        L.append('没有书触发目录清洗。')
    L.append('')
    L.append('## 重复篇名（需人工判断）')
    L.append('')
    if dup:
        L.append('| 书码 | 书名 | 重复篇名数 | 说明 |')
        L.append('|---|---|---:|---|')
        for r in dup:
            L.append('| %s | %s | %d | %s |' % (
                r['书码'], r['书名'], r['重复篇名数'], r['说明']))
    else:
        L.append('没有重复篇名。')
    L.append('')
    L.append('## 全部图书')
    L.append('')
    L.append('| 书码 | 书名 | 原型 | 篇 | 段 | 结构异常 | 目录清洗 |')
    L.append('|---|---|---|---:|---:|---|---|')
    for r in rows:
        c = r['目录清洗'] or {}
        L.append('| %s | %s | %s %s | %s | %s | %s | %s |' % (
            r['书码'], r['书名'], r['原型'] or '', r['原型名'] or '',
            r['篇数'], r['段数'], '异常' if r['异常'] else '正常',
            ('删 %s 行' % c.get('删除行数')) if c.get('删除行数') else '—'))
    with io.open(os.path.join(P.PLATFORM, '结构审计报告.md'), 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(L) + '\n')
    print('书数 %d；异常 %d；目录清洗 %d；重复篇名 %d' %
          (len(rows), len(abnormal), len(cleaned), len(dup)))
    print('写出 platform/结构审计报告.md / .json')


if __name__ == '__main__':
    main()
