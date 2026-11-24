# -*- coding: utf-8 -*-
"""理解层：金句 / 议题 / 章节摘要。

三条铁律：
1. 只选不改——引文必须能在原文段里逐字查到，查不到直接丢弃；
2. 每条带锚点（段 id）；
3. 失败不写半成品：整批失败就整批不落，标 last_error。

产物：out/<code>/understanding.json
用法：
    python3 understanding.py quotes B58 B60
    python3 understanding.py themes B60
    python3 understanding.py summaries B60
"""
import io
import json
import os
import re
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P      # noqa: E402
import llm             # noqa: E402

from product_language import PRODUCT_LANGUAGE

OUT = P.OUT
PROMPT_VERSION = 'understanding-v1.2'
CHUNK = 40
_AUXILIARY = re.compile(r'^(?:目录|版权页|封面|扉页|编者的话|前言|序言|导读|后记|参考文献|索引)(?:$|[：:\s])')
_NO_SUMMARY = re.compile(r'^(?:NONE\b|无法(?:生成|提炼|概括)|不能(?:生成|概括)|原文(?:缺失|不足)|(?:提供的|所提供的|给出的)(?:原文|段落).{0,24}(?:乱码|不足))', re.I)
_NUMBERS = re.compile(r'(?<!\d)[+−-]?\d+(?:\.\d+)?')
_SENTENCE_END = re.compile(r"""(?:[。！？!?]+|\.(?=\s|$))[”’」』》）】)'"…]*""")
_SECTION_NUMBER = re.compile(r'^第[一二三四五六七八九十百零\d]+[章回节]')


def rows_of(code):
    with io.open(os.path.join(OUT, code, 'segments.jsonl'), encoding='utf-8') as fp:
        return [json.loads(l) for l in fp if l.strip()]


def supported_source(row):
    role = str(row.get('source_role') or row.get('source_kind') or '')
    chapter = str(row.get('篇') or '').strip()
    return (not row.get('source_structure_suspect')
            and not row.get('source_layout_suspect')
            and not row.get('source_issue')
            and role not in ('toc', 'table', 'cover', 'copyright', 'header', 'caption', 'vertical', 'refe', 'front_matter')
            and not _AUXILIARY.match(chapter))


def _source_rows(code, key):
    original = rows_of(code)
    rows = [row for row in original if supported_source(row)]
    if not rows and original:
        stats = {'kept': 0, 'blocked': 1, 'source_stale': True,
                 'last_error': '暂时找不到可核对的正文，请先检查版面和章节。'}
        return rows, (_save(code, key, [], stats).get(key, []), stats)
    return rows, None


def norm(s):
    return re.sub(r'\s+', '', s or '')


def verify(quote, seg_text, min_len=8):
    """逐字校验：去掉空白后必须是原文子串。这是唯一能挡住模型改字的闸。"""
    q = norm(quote)
    if len(q) < min_len:
        return False
    return q in norm(seg_text)


def parse_blocks(text):
    """Parse numbered selections, with support for the earlier SEG/QUOTE format."""
    items, cur = [], {}
    for raw in (text or '').splitlines():
        line = raw.strip()
        if line == '---':
            if 'sentence' in cur or cur.get('seg'):
                items.append(cur)
            cur = {}
            continue
        up = line.upper()
        if up.startswith(('SEG:', 'SENTENCE:')):
            field = 'sentence' if up.startswith('SENTENCE:') else 'seg'
            if field in cur or cur.get('seg') or 'sentence' in cur:
                items.append(cur)
            cur = {field: line.split(':', 1)[1].strip()}
        elif up.startswith('QUOTE:'):
            cur['quote'] = line.split(':', 1)[1].strip()
        elif up.startswith('WHY:'):
            cur['why'] = line.split(':', 1)[1].strip()
        elif up.startswith('THEME:'):
            cur['theme'] = line.split(':', 1)[1].strip()
        elif up.startswith('SUMMARY:'):
            cur['summary'] = line.split(':', 1)[1].strip()
        elif cur.get('quote') is not None and line.strip() and 'why' not in cur:
            cur['quote'] += line.strip()
    if 'sentence' in cur or cur.get('seg'):
        items.append(cur)
    return items


def _checked_blocks(text):
    """An empty selection must be explicit, not a transport/protocol failure."""
    text = str(text or '').strip()
    blocks = parse_blocks(text)
    if blocks:
        return blocks
    clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I).strip()
    if clean.upper() == 'NONE' or clean == '[]':
        return []
    try:
        if json.loads(clean) == {'items': []}:
            return []
    except (ValueError, TypeError):
        pass
    raise ValueError('模型未返回约定的内容格式或明确的空结果')


def _numbered_sentences(rows, limit, budget):
    """Return the exact source value for each numbered sentence sent to the model."""
    sentences = {}
    display = []
    for row in rows:
        text = row.get('文本') or ''
        if not row.get('id'):
            continue
        start = used = 0
        for end in _SENTENCE_END.finditer(text):
            sentence = text[start:end.end()].strip()
            start = end.end()
            size = len(norm(sentence))
            if not 12 <= size <= limit or _SECTION_NUMBER.match(sentence):
                continue
            if used + len(sentence) > budget:
                break
            used += len(sentence)
            number = str(len(sentences) + 1)
            sentences[number] = (row['id'], sentence)
            display.append('【%s】%s' % (number, sentence))
    return sentences, '\n'.join(display)


def _selected_evidence(block, sentences, by_id):
    if 'sentence' in block:
        return sentences.get(block['sentence'])
    seg = str(block.get('seg') or '')
    quote = str(block.get('quote') or '').strip()
    row = by_id.get(seg)
    if row and verify(quote, row.get('文本') or ''):
        return seg, quote
    return None


def _json(text):
    t = re.sub(r'^```(?:json)?|```$', '', (text or '').strip(), flags=re.M).strip()
    i, j = t.find('{'), t.rfind('}')
    if i < 0 or j <= i:
        raise ValueError('没有 JSON')
    return json.loads(t[i:j + 1])


def _save(code, key, items, stats, model=None, error=None, retain_prior=False):
    path = os.path.join(OUT, code, 'understanding.json')
    data = {}
    if os.path.exists(path):
        with io.open(path, encoding='utf-8') as fp:
            data = json.load(fp)
    # Older files may only have a book-wide stale marker. Materialize it before
    # updating one product so a successful quote run cannot clear stale summaries.
    if data.get('stale'):
        processing = data.setdefault('processing', {})
        for part in ('quotes', 'themes', 'summaries'):
            if part in data and part not in processing:
                processing[part] = {'status': 'stale'}
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S')
    blocked = int(stats.get('blocked') or 0)
    failure = error or stats.get('last_error') or ''
    attempt = dict(stats, ts=timestamp, status=('partial' if items else 'failed') if blocked else 'done')
    if key in ('quotes', 'themes'):
        attempt['prompt'] = PROMPT_VERSION
    if failure:
        attempt['error'] = failure
    previous_attempt = (data.get('processing') or {}).get(key) or {}
    if blocked and key in data and (previous_attempt.get('status') == 'stale' or previous_attempt.get('source_stale')):
        attempt['source_stale'] = True
    data.setdefault('processing', {})[key] = attempt
    data.setdefault('code', code)
    data.setdefault('prompt', PROMPT_VERSION)
    data['ts'] = timestamp
    # 失败批次不覆盖上一份完整成果，最新失败单独记录供作业和前端显示。
    if blocked and key in data:
        attempt['retained_previous'] = True
    else:
        if retain_prior and data.get(key) and not (previous_attempt.get('status') == 'stale' or previous_attempt.get('source_stale')):
            source = {row['id']: row.get('文本') for row in rows_of(code) if supported_source(row) and row.get('id')}
            previous = [item for item in data[key] if verify(item.get('quote'), source.get(item.get('seg')))]
            combined = {}
            for item in previous + items:
                identity = (item.get('seg'), norm(item.get('quote')), item.get('议题'))
                combined.setdefault(identity, item)
            items = list(combined.values())
        data[key] = items
        data.setdefault('stats', {})[key] = stats
        if model:
            data['model'] = model
    data['stale'] = any(v.get('status') == 'stale' or v.get('source_stale') for v in data['processing'].values())
    if failure:
        data['last_error'] = failure
    elif not any(x.get('status') in ('partial', 'failed') for x in data['processing'].values()):
        data.pop('last_error', None)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.understanding-', dir=os.path.dirname(path))
    with os.fdopen(fd, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return data


SYS_QUOTE = ('你是出版社编辑。从给出的原文句子里选出可以独立引用的句子。'
             '只返回所选句子的编号，无需抄写原文。'
             '按用户指定的行式协议输出；没有合适的内容就只输出 NONE，不要凑数。')

SYS_THEME = ('你是图书编辑。判断这些原文能对上哪些现代议题。'
             '每个议题选择一句直接支持它的原文，只填编号。'
             '按用户指定的行式协议输出；没有合适的议题就只输出 NONE。')

SYS_SUM = ('你是图书编辑。为这一篇写 1-3 句内容摘要，只允许使用给出的段落信息，不得补充外部知识。'
           '按用户指定的 SUMMARY: 行式协议输出。')


def quotes(code, chunk=CHUNK, timeout=60, on_progress=None, retain_prior=False):
    rows, stopped = _source_rows(code, 'quotes')
    if stopped:
        return stopped
    picked, dropped, model = [], 0, None
    blocked, err = 0, ''
    total = (len(rows) + chunk - 1) // chunk
    for completed, i in enumerate(range(0, len(rows), chunk), 1):
        part = rows[i:i + chunk]
        sentences, body = _numbered_sentences(part, limit=80, budget=700)
        cap = max(3, len(part) // 10)
        prompt = ('挑出可以独立引用的原句，最多 %d 条。用数字填写 SENTENCE。'
                  '每组之间用单独一行 --- 分隔。没有合适的句子就输出 NONE。\n'
                  'SENTENCE: 句子编号\nWHY: 一句话理由\n---\n\n' % cap) + body
        try:
            if not sentences:
                continue
            res = llm.chat([{'role': 'system', 'content': SYS_QUOTE + PRODUCT_LANGUAGE},
                            {'role': 'user', 'content': prompt}], max_tokens=1600, timeout=timeout)
            blocks = _checked_blocks(res['text'])
            model = res.get('model')
        except Exception as e:
            blocked += 1
            err = str(e)[:120]
            continue
        finally:
            if on_progress:
                on_progress(completed, total)
        by_id = {r.get('id'): r for r in part}
        selected = set()
        for block in blocks:
            evidence = _selected_evidence(block, sentences, by_id)
            if not evidence:
                dropped += 1
                continue
            seg, q = evidence
            if not 12 <= len(norm(q)) <= 80 or _SECTION_NUMBER.match(q):
                dropped += 1
                continue
            if seg in selected:
                continue
            picked.append({'seg': seg, 'quote': q, 'reason': str(block.get('why') or '')[:80]})
            selected.add(seg)
            if len(selected) >= cap:
                break
        if blocks and not selected:
            blocked += 1
            err = '本批模型结果未通过原文证据核验'
    stats = {'kept': len(picked), 'dropped': dropped, 'blocked': blocked,
             'pass_rate': round(len(picked) / max(len(picked) + dropped, 1), 3)}
    if err:
        stats['last_error'] = err
    saved = _save(code, 'quotes', picked, stats, model, retain_prior=retain_prior)
    return saved.get('quotes', []), stats


def themes(code, per_book=5, timeout=60, on_progress=None, retain_prior=False):
    all_rows, stopped = _source_rows(code, 'themes')
    if stopped:
        return stopped
    step = max(1, (len(all_rows) + 119) // 120)
    rows = all_rows[::step]
    sentences, body = _numbered_sentences(rows, limit=240, budget=500)
    prompt = ('提炼最多 %d 个有原文支持的现代议题。用数字填写 SENTENCE，写明这句话怎样支持议题。'
              '每组之间用单独一行 --- 分隔。没有直接依据就输出 NONE。\n'
              'SENTENCE: 句子编号\nTHEME: 议题\nWHY: 一句话理由\n---\n\n' % per_book) + body
    try:
        res = llm.chat([{'role': 'system', 'content': SYS_THEME + PRODUCT_LANGUAGE},
                        {'role': 'user', 'content': prompt}], max_tokens=1500, timeout=timeout) if sentences else {}
        blocks = _checked_blocks(res['text']) if sentences else []
    except Exception as e:
        stats = {'kept': 0, 'blocked': 1, 'last_error': str(e)[:120]}
        saved = _save(code, 'themes', [], stats)
        return saved.get('themes', []), stats
    finally:
        if on_progress:
            on_progress(1, 1)
    by_id = {r.get('id'): r for r in rows}
    kept, dropped = [], 0
    for it in blocks[:per_book]:
        evidence = _selected_evidence(it, sentences, by_id)
        if evidence and it.get('theme'):
            seg, q = evidence
            kept.append({'议题': str(it.get('theme') or '')[:20], 'seg': seg,
                         'quote': q, '理由': str(it.get('why') or '')[:60]})
        else:
            dropped += 1
    stats = {'kept': len(kept), 'dropped': dropped}
    if blocks and not kept:
        stats.update(blocked=1, last_error='模型结果未通过原文证据核验')
    saved = _save(code, 'themes', kept, stats, res.get('model'), retain_prior=retain_prior)
    return saved.get('themes', []), stats


def summaries(code):
    from tocclean import is_parent_heading

    op = os.path.join(OUT, code, 'outline.jsonl')
    if not os.path.exists(op):
        outline = []
    else:
        with io.open(op, encoding='utf-8') as fp:
            outline = [json.loads(l) for l in fp if l.strip()]
    if not outline:
        stats = {'kept': 0, 'blocked': 1, 'source_stale': True,
                 'last_error': '没有可用篇目录，请先修复章节结构再生成摘要'}
        saved = _save(code, 'summaries', [], stats)
        return saved.get('summaries', []), stats
    rows, stopped = _source_rows(code, 'summaries')
    if stopped:
        return stopped
    by_pian = {}
    for r in rows:
        key = (r.get('篇序'), r.get('篇'))
        by_pian.setdefault(key, []).append(r)
    kept, blocked, skipped = [], 0, 0
    last_error = ''
    for index, o in enumerate(outline):
        name = o.get('篇')
        order = o.get('篇序')
        if order is None:
            part = [row for (index, heading), group in by_pian.items() if heading == name for row in group]
        else:
            part = by_pian.get((order, name)) or []
        if not part or sum(len(norm(r.get('文本') or '')) for r in part) < 30:
            next_title = outline[index + 1].get('篇') if index + 1 < len(outline) else ''
            if _AUXILIARY.match(str(name or '').strip()) or is_parent_heading(name, next_title):
                continue
            skipped += 1
            continue
        sample = part if len(part) <= 8 else [part[round(i * (len(part)-1) / 7)] for i in range(8)]
        body = '\n'.join('【段 %s】%s' % (r.get('id'), (r.get('文本') or '')[:400]) for r in sample)
        prompt = ('篇名：%s\n为这一篇写 1-3 句摘要，只能使用给出的段落信息。\n'
                  '严格按下面格式输出，不要 JSON：\nSUMMARY: 摘要正文\n\n' % name) + body
        try:
            res = llm.chat([{'role': 'system', 'content': SYS_SUM + PRODUCT_LANGUAGE},
                            {'role': 'user', 'content': prompt}], max_tokens=500)
            blocks = parse_blocks(res['text'])
            txt = (blocks[0].get('summary') if blocks else '') or ''
            if not txt:
                for line in (res['text'] or '').splitlines():
                    if line.upper().startswith('SUMMARY:'):
                        txt = line.split(':', 1)[1].strip()
        except Exception as e:
            blocked += 1
            last_error = str(e)[:120]
            continue
        if not txt.strip() or _NO_SUMMARY.match(txt.strip()):
            blocked += 1
            last_error = '这部分没有生成可核对的摘要。'
            continue
        numeric_basis = {n for r in sample for n in _NUMBERS.findall(str(r.get('文本') or '')[:400])}
        numeric_basis.update(_NUMBERS.findall(str(name or '')))
        if set(_NUMBERS.findall(txt)) - numeric_basis:
            blocked += 1
            last_error = '摘要里有数字无法在所用原文中核对。'
            continue
        kept.append({'篇': name, 'summary': str(txt)[:300],
                     'seg_from': str(part[0].get('id') or ''), 'seg_to': str(part[-1].get('id') or ''),
                     'sample_ids': [r['id'] for r in sample if r.get('id')], 'section_segments': len(part)})
    stats = {'kept': len(kept), 'blocked': blocked + skipped, 'skipped': skipped}
    if skipped and not last_error:
        last_error = '有 %d 章的正文尚不完整，已暂缓生成摘要。' % skipped
    if not kept and not blocked and skipped:
        stats.update(blocked=1, source_stale=True)
        last_error = '目录条目没有足够的正文，请先核对章节结构'
    if last_error:
        stats['last_error'] = last_error
    saved = _save(code, 'summaries', kept, stats)
    return saved.get('summaries', []), stats


if __name__ == '__main__':
    cap = sys.argv[1] if len(sys.argv) > 1 else 'quotes'
    codes = sys.argv[2:] or ['B58', 'B60']
    fn = {'quotes': quotes, 'themes': themes, 'summaries': summaries}[cap]
    for c in codes:
        t0 = time.time()
        items, stats = fn(c)
        print('%s %s：%d 条（丢弃 %s）%.1fs' % (c, cap, len(items), stats.get('dropped', '-'), time.time() - t0))
        for it in items[:3]:
            print('   ·', (it.get('quote') or it.get('summary') or '')[:60])
