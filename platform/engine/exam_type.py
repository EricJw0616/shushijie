# -*- coding: utf-8 -*-
"""判型闭卷考（直接选类型版）：只看指纹，让模型从 P1–P11 里选一个。

与 exam.py 的区别：exam.py 是「逐列判定 → 由列反推类型」；这里是直接让模型选类型。
两个数放在一起，才知道问题出在列判定还是派生规则。
"""
import argparse
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm      # noqa: E402

TYPES = {
 'P1': '规范型：法规、标准、制度条文，条条框框',
 'P2': '知识型：讲原理、工艺、做法，有定义和步骤',
 'P3': '论说型：议论、说理、主张，作者在论证',
 'P4': '叙事型：讲故事、有情节人物对白',
 'P5': '戏曲型：剧本、曲牌、科介、舞台提示',
 'P6': '散文型：抒情、随笔、第一人称',
 'P7': '韵文集型：诗、词、曲、赋等韵文为主',
 'P8': '条目型：辞书、训诂、地理志条目体',
 'P9': '选集笺注型：选本 + 注/评/笺',
 'P10': '笔记志书型：笔记、志书、条目式记录',
 'P11': '图鉴型：物种图鉴、图谱，条目+字段',
}

SYS = ('你是图书类型判定员。只根据给出的书名、目录、统计和抽样段落判断，不要推测。'
       '从 P1–P11 里选一个最接近的；都不像就填 P0。输出严格 JSON。')


def fingerprint(root, code):
    rows = [json.loads(l) for l in io.open(os.path.join(root, code, 'segments.jsonl'), encoding='utf-8') if l.strip()]
    op = os.path.join(root, code, 'outline.jsonl')
    outline = [json.loads(l) for l in io.open(op, encoding='utf-8') if l.strip()] if os.path.exists(op) else []
    book = json.load(io.open(os.path.join(root, code, 'book.json'), encoding='utf-8'))
    txt = '\n'.join((r.get('文本') or '') for r in rows)
    han = len(re.findall(r'[\u4e00-\u9fff]', txt)) or 1
    quotes = sum(len(q) for q in re.findall(r'[“"]([^”"]{4,})[”"]', txt))
    picks = [rows[0]] if rows else []
    if len(rows) > 20:
        picks.append(rows[len(rows) // 2])
    return book, outline, picks, {'段': len(rows), '篇': len(outline),
                                  '对白率': round(quotes / han, 3),
                                  '平均段长': round(han / max(len(rows), 1), 1)}


def run(root, code):
    book, outline, picks, st = fingerprint(root, code)
    lines = ['书名：%s' % (book.get('book') or ''),
             '统计：%d 段 / %d 篇 / 对白率 %.1f%% / 平均段长 %d 字'
             % (st['段'], st['篇'], st['对白率'] * 100, st['平均段长'])]
    if outline:
        lines.append('篇名：' + '；'.join((o.get('篇') or '')[:20] for o in outline[:15]))
    lines.append('抽样段落：')
    for r in picks:
        lines.append('【%s】%s' % (r.get('id'), (r.get('文本') or '')[:500]))
    lines.append('')
    lines.append('可选类型：')
    for k, v in TYPES.items():
        lines.append('%s %s' % (k, v))
    lines.append('输出 {"type":"P?","confidence":0-1,"reason":"一句话"}')
    res = llm.chat([{'role': 'system', 'content': SYS}, {'role': 'user', 'content': '\n'.join(lines)}],
                   max_tokens=300, temperature=0, json_mode=True)
    try:
        d = json.loads(res['text'])
    except Exception:
        d = {}
    return {'code': code, 'book': book.get('book'), 'true': book.get('原型') or '拒判',
            'pred': (d.get('type') or '').strip(), 'conf': d.get('confidence'),
            'reason': d.get('reason'), 'tokens': (res.get('usage') or {}).get('total_tokens')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    codes = [n for n in sorted(os.listdir(a.root))
             if os.path.exists(os.path.join(a.root, n, 'book.json'))
             and os.path.exists(os.path.join(a.root, n, 'segments.jsonl'))
             and (json.load(io.open(os.path.join(a.root, n, 'book.json'), encoding='utf-8')).get('原型'))]
    if a.limit:
        codes = codes[:a.limit]
    print('参加考试', len(codes), '本', flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        out = list(ex.map(lambda c: run(a.root, c), codes))
    ok = sum(1 for r in out if r['pred'] == r['true'])
    print('直接判型 top-1：%d/%d = %.1f%%' % (ok, len(out), 100.0 * ok / max(len(out), 1)))
    from collections import Counter
    print('混淆：', Counter((r['true'], r['pred']) for r in out if r['pred'] != r['true']).most_common(6))
    dest = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'eval_sets', '判型考试_直选.json')
    with io.open(dest, 'w', encoding='utf-8') as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)
    print('结果写入', dest)


if __name__ == '__main__':
    main()
