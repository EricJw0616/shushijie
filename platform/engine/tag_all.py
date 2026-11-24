# -*- coding: utf-8 -*-
"""把一批书的标签层一次跑齐：版权页 → 中图法 → 逐列判定 → 知识条目 → 专名
→ 金句 → 议题 → 章节摘要 → 营销。

每一层都是全体通用的，不允许某一本单独打补丁：书缺什么就是缺什么（not_found/空），
不编、不补、不拿别处的数据代填。

每一步单独 try，失败记进报告，不阻断后面的步骤。
用法：
  python3 tag_all.py B56 B58 ...
  python3 tag_all.py --all
"""
import argparse
import io
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P      # noqa: E402
import cip             # noqa: E402
import clc             # noqa: E402
import judge           # noqa: E402
import entities        # noqa: E402
import understanding   # noqa: E402
import cards as CD     # noqa: E402
import pipeline as PL  # noqa: E402
import marketing as MK  # noqa: E402


def _jsonl(code, fn):
    p = os.path.join(P.OUT, code, fn)
    if not os.path.exists(p):
        return []
    with io.open(p, encoding='utf-8') as fp:
        return [json.loads(l) for l in fp if l.strip()]


def _json(path, default=None):
    try:
        with io.open(path, encoding='utf-8') as fp:
            return json.load(fp)
    except Exception:
        return default


def build_marketing(code):
    """Publish only a nonempty, evidenced result; empty model JSON is a failure."""
    rec = MK.build(code)
    usable, categories = 0, 0
    for key, item in (rec.get('items') or {}).items():
        value = item.get('value')
        values = [value] if isinstance(value, dict) else (value if isinstance(value, list) else [])
        found = 0
        for val in values:
            if not isinstance(val, dict):
                continue
            evidence = item.get('evidence') if key == 'summary' else val.get('evidence')
            if (val.get('keyword') or val.get('text') or '').strip() and evidence:
                found += 1
        usable += found
        categories += bool(found)
    if not usable:
        raise RuntimeError('模型未生成有原文依据的营销素材，原成果保留')
    rec.setdefault('stats', {}).update(usable_items=usable, available_categories=categories)
    rec['source_version'] = (_json(os.path.join(P.OUT, code, 'book.json'), {}) or {}).get('source_version')
    MK.write(rec)
    return rec


def build_cards(code):
    """补做有原文支持的内容标签，沿用图书入库的抽取规则。"""
    book = _json(os.path.join(P.OUT, code, 'book.json'), {}) or {}
    if not book:
        raise RuntimeError('图书尚未完成解析')
    segs = _jsonl(code, 'segments.jsonl')
    if not segs:
        raise RuntimeError('没有可用的原文段落')
    path = os.path.join(P.ROOT, book.get('源文件') or '')
    text = ''
    if os.path.isfile(path):
        with io.open(path, encoding='utf-8') as fp:
            text = fp.read()
    else:
        text = '\n'.join(s.get('文本') or '' for s in segs)
    atlas, atlas_src, story_people, people_src = PL.content_sources(path, text, book.get('book') or '')
    plan = {'pattern': book.get('结构样式') or book.get('结构模式')}
    rows, checks, dropped = CD.extract_by_content(
        {'book': book.get('book') or code, 'code': code},
        segs, book.get('原型'), bool(book.get('算法断句')),
        atlas_entries=atlas, story_people=story_people, layout_plan=plan)
    CD.save_identity_registry(code, rows)
    dst = os.path.join(P.OUT, code, 'cards.jsonl')
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=os.path.dirname(dst), delete=False) as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + '\n')
        temporary = fp.name
    os.replace(temporary, dst)
    book['候选卡数'] = len(rows)
    book['候选卡丢弃'] = dropped
    book['内容检查'] = checks
    book['候选卡构成'] = '；'.join(f"{name} {check['count']} 条" for name, check in checks.items() if check['count'])
    book['条目数'], book['条目来源'] = len(atlas), atlas_src
    book['人物条目数'], book['人物条目来源'] = len(story_people), people_src
    PL._write_json(os.path.join(P.OUT, code, 'book.json'), book)
    index_path = os.path.join(P.OUT, 'books.json')
    index = _json(index_path, []) or []
    index = [book if b.get('code') == code else b for b in index]
    PL._write_json(index_path, index)
    return {'cards': len(rows), 'dropped': dropped, 'atlas': atlas_src}


class NamesNeedReview(RuntimeError):
    pass


def build_entities(code, on_progress=None):
    """断点绑定当前段落版本；失败保留已发布成果，未完成批次可续跑。"""
    folder = os.path.join(P.OUT, code)
    status_path = os.path.join(folder, 'derivative_status.json')
    states = _json(status_path, {}) or {}
    redo = (states.get('entities') or {}).get('status') == 'stale'
    path = os.path.join(folder, 'entities.jsonl')
    had_published = os.path.exists(path)
    rows = entities.extract(code, redo=redo, no_gbif=os.environ.get('BOOKDISTILL_LOOKUP_SPECIES') != '1',
                            require_complete=True, on_progress=on_progress)
    done = set(_json(os.path.join(folder, '.entities_done.json'), []) or [])
    refused = set(_json(entities.refused_path(code), []) or [])
    source = _jsonl(code, 'segments.jsonl')
    skipped = sum(1 for row in source if not entities.source_readable(row))
    readable = {row['id'] for row in source if entities.source_readable(row) and row.get('id')}
    refused &= readable
    missing = len(readable - done - refused)
    state = 'partial' if missing else 'blocked' if refused else 'done'
    states['entities'] = {'status': state, 'missing_segments': missing, 'refused_segments': len(refused),
                          'refused_anchor': min(refused) if refused else '',
                          'unreadable_segments': skipped,
                          'retained_previous': bool(missing and had_published)}
    PL._write_json(status_path, states)
    if missing:
        raise RuntimeError('专名还有%d段未处理成功，已有成果保留，可继续补跑' % missing)
    if refused:
        raise NamesNeedReview('有 %d 段原文未能自动整理名称，可查看原文核对。' % len(refused))
    return rows


def run_one(code, include_marketing=True):
    rep = {'code': code, 'steps': {}, 'errors': []}
    t0 = time.time()

    def step(name, fn):
        t = time.time()
        try:
            rep['steps'][name] = {'ok': True, 'result': fn(), 'sec': round(time.time() - t, 1)}
        except Exception as e:
            rep['steps'][name] = {'ok': False, 'error': '%s: %s' % (type(e).__name__, e),
                                  'sec': round(time.time() - t, 1)}
            rep['errors'].append(name)
            traceback.print_exc()

    def do_cip():
        got = cip.annotate(code) or {}
        return {'found': bool(got.get('_found')), 'isbn': got.get('ISBN') or '',
                'clc': got.get('中图法') or ''}

    def do_clc():
        got = clc.annotate(code) or {}
        return {'code': got.get('代码') or '', 'src': got.get('来源') or ''}

    def do_judge():
        cols, usage = judge.judge(code)
        jp = os.path.join(P.OUT, code, 'judge.json')
        result = _json(jp, {}) or {}
        result['source_version'] = (_json(os.path.join(P.OUT, code, 'book.json'), {}) or {}).get('source_version')
        PL._write_json(jp, result)
        return {'适用': len([k for k, v in cols.items() if v.get('适用')]),
                'tokens': (usage or {}).get('total_tokens')}

    def do_entities():
        from collections import Counter
        return dict(Counter(r['cat'] for r in build_entities(code)))

    def do_cards():
        return build_cards(code)

    def do_quotes():
        items, st = understanding.quotes(code)
        if st.get('blocked'):
            raise RuntimeError('金句有失败批次，已保留上一份成功成果')
        return {'kept': len(items), 'dropped': st.get('dropped')}

    def do_themes():
        items, st = understanding.themes(code)
        if st.get('blocked'):
            raise RuntimeError('议题生成失败，已保留上一份成功成果')
        return {'kept': len(items)}

    def do_summaries():
        items, st = understanding.summaries(code)
        if st.get('blocked'):
            raise RuntimeError('章节摘要有失败批次，已保留上一份成功成果')
        return {'kept': len(items)}

    def do_marketing():
        rec = build_marketing(code)
        return {'items': len(rec.get('items') or {}),
                'dropped': (rec.get('stats') or {}).get('dropped')}

    step('cip', do_cip)
    step('clc', do_clc)
    if os.environ.get('BOOKDISTILL_EXTENDED_JUDGE') == '1':
        step('judge', do_judge)
    step('cards', do_cards)
    step('entities', do_entities)
    step('quotes', do_quotes)
    step('themes', do_themes)
    step('summaries', do_summaries)
    if include_marketing:
        step('marketing', do_marketing)
    rep['sec'] = round(time.time() - t0, 1)
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('codes', nargs='*')
    ap.add_argument('--all', action='store_true')
    a = ap.parse_args()
    if a.all or not a.codes:
        codes = sorted(d for d in os.listdir(P.OUT)
                       if os.path.isfile(os.path.join(P.OUT, d, 'book.json'))
                       and not d.startswith('.'))
    else:
        codes = a.codes
    print('本次处理 %d 本：%s' % (len(codes), ' '.join(codes)), flush=True)
    reps = []
    for i, c in enumerate(codes, 1):
        print('\n[%d/%d] %s ...' % (i, len(codes), c), flush=True)
        rep = run_one(c)
        reps.append(rep)
        parts = []
        for k in ('cip', 'clc', 'judge', 'entities', 'quotes', 'themes'):
            s = rep['steps'].get(k, {})
            parts.append('%s%s' % (k, '✓' if s.get('ok') else '✗'))
        print('  %s  %.1fs  %s' % (' '.join(parts), rep['sec'],
                                   ('错误: ' + ','.join(rep['errors'])) if rep['errors'] else ''), flush=True)
    import importlib
    importlib.import_module('export').main()
    importlib.import_module('taglib').main()
    sys.path.insert(0, os.path.join(P.ROOT, 'app'))
    import kg_build
    for c in codes:
        try:
            kg_build.auto_build(c, force=True)
        except Exception as e:
            print('图谱更新失败 %s: %s' % (c, e), flush=True)
    for c in codes:
        mk = os.path.join(P.OUT, c, '.tagging')
        if os.path.exists(mk):
            os.remove(mk)
    dest = os.path.join(P.OUT, 'tag_report.json')
    with io.open(dest, 'w', encoding='utf-8') as fp:
        json.dump(reps, fp, ensure_ascii=False, indent=1)
    print('\n报告写入', dest, flush=True)


if __name__ == '__main__':
    main()
