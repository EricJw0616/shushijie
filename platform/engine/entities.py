# -*- coding: utf-8 -*-
"""五类专名抽取：地名 / 机构 / 器物 / 动物 / 植物。

与「名物」的区别：不再混成一个列。五类各自独立，因为它们的查询库、校验方式、
下游用途都不同（地名进地理索引、机构进图谱、动植物进物种卡）。

流程：
  模型按段列名 → 逐字校验 → 排除《书名》/人名 → 词典校正类别 → 落 entities.jsonl

用法：
  python3 entities.py B60
  python3 entities.py B60 --batch 20
"""
import argparse
import io
import urllib.parse
import urllib.request
import json
import os
import re
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P      # noqa: E402
import llm             # noqa: E402
import lexicon         # noqa: E402
import geo             # noqa: E402
import library         # noqa: E402
from entity_classify import classify as ec_classify  # noqa: E402
from zh import to_simplified

OUT = P.OUT
PROMPT_VERSION = 'entities-v1'
# 分类阶元不是机构/动植物实体：卷柏科、卷柏属、半翅目。
TAXON_RE = re.compile(r'(科|属|目|纲|族)$')
PLACE_TAIL = re.compile(r'(洲|南部|北部|东部|西部|中部|地区|一带)$')
# 地名 vs 机构：这些后缀即使模型/词典说“地名”，也必须是机构。
ORG_TAIL = re.compile(r'(厂|公司|集团|大学|学院|学校|中学|小学|党校|区委|市委|县委|党委|'
                      r'政府|委员会|管委会|管理委员会|出版社|报社|研究所|研究院|科学院|'
                      r'医院|银行|监狱|看守所|大厦|大楼|办公大楼|纪念馆|博物馆|图书馆)$')
ORG_ABBR = {'北大', '清华', '复旦', '南开', '二中', '一中', '三中', '四中', '五中'}
# 不是具体地名的泛称，直接不标。
PLACE_GENERIC = {'首都', '市区', '县城', '郊区', '城市', '农村', '城乡', '国内', '国外',
                 '南方', '北方', '地方', '境内', '城外', '全国'}
# 同一地名的不同写法要并成一条，否则每个都指向不同段
PLACE_ALIAS = {
    '西伯利亚地区': '西伯利亚',
    '东西伯利亚': '西伯利亚',
    '俄罗斯（西伯利亚地区）': '西伯利亚',
    '俄罗斯（西伯利亚及远东地区）': '西伯利亚',
    '俄罗斯（远东和西伯利亚地区）': '西伯利亚',
}
KEYMAP = {'PLACE': 'place', 'ORG': 'org', 'OBJECT': 'object',
          'ANIMAL': 'animal', 'PLANT': 'plant', 'TAXON': 'taxon', 'OTHER': 'other'}

# 泛称不是专名：牲畜/禽畜/粮食/种子 这类词进索引没有检索价值，反而稀释精度
STOP = {
    'animal': {'牲畜', '禽畜', '家畜', '牲口', '野兽', '名马', '战马', '马匹', '飞禽', '走兽', '动物',
               '腊鸭', '腊肉', '肉', '鱼干'},
    'plant': {'粮食', '种子', '菜蔬', '蔬菜', '草料', '秋粮', '庄稼', '作物', '植物', '树木',
              '丝绸', '丝绵', '棉布', '麻布', '牛皮', '羊皮', '木材', '竹子', '纸张', '稻草'},
    'object': {'东西', '物品', '器物', '家具', '行李', '包袱'},
    'org': {'朝廷', '书院', '衙门', '官府', '义学', '县衙',
            # 官名不是机构：它们是职位，进图谱该走「职官」类，先不混进 org
            '御史中丞', '御史', '知县', '知府', '知州', '巡抚', '总督', '尚书', '侍郎',
            '郎中', '员外郎', '主事', '给事中', '太守', '县令', '刺史', '丞相', '宰相',
            '大学士', '学士', '编修', '检讨', '主簿', '县丞', '教谕', '训导', '巡检',
            '提举', '转运使', '按察使', '布政使', '参政', '参议', '同知', '通判', '推官'},
    'place': {'京城', '地方', '境内', '城外'},
}

SYS = ('你是图书专名标注员。只标原文里逐字出现的名字，不推测、不改写、不补全。\n'
       '注意：民族、政权、朝代、材料、泛称、动作短语都不是专名，不要标。\n'
       '界定不清的放进 OTHER，不要硬塞进五类。')


ROOT = OUT


def source_readable(row):
    return not any(row.get(key) for key in ('source_layout_suspect', 'source_structure_suspect', 'source_issue'))


def _rows(code):
    with io.open(os.path.join(ROOT, code, 'segments.jsonl'), encoding='utf-8') as fp:
        rows = [json.loads(line) for line in fp if line.strip()]
    return [row for row in rows if source_readable(row)]


def _people(code):
    p = os.path.join(ROOT, code, 'people.jsonl')
    if not os.path.exists(p):
        return set()
    return {json.loads(l).get('人物') for l in io.open(p, encoding='utf-8') if l.strip()}


def explicit_name_rows(title, segments):
    """Add only names whose type can be traced to a concrete place in this book."""
    seen = set()
    own_title = re.sub(r'\s+', '', str(title or '')).strip('《》')
    out = []

    def add(name, cat, quote, signal, row):
        key = (name, cat, row.get('id'))
        if not key[2] or key in seen:
            return
        seen.add(key)
        reason = {'title_subject': '书名及人物资料与该处正文一致',
                  'printed_title': '原文以书名号标注',
                  'citation': '原文明确写出引用的名称'}[signal]
        out.append({'name': name, 'name_s': to_simplified(name), 'cat': cat, 'seg': row['id'],
                    'book': row.get('篇') or '', 'src': '原文', 'ver': PROMPT_VERSION,
                    'conf': 0.95, 'why': reason, 'name_evidence': signal, 'quote': quote})

    for name, quote, row in library.title_subject_mentions(title, segments):
        add(name, 'person', quote, 'title_subject', row)
    for row in segments:
        if not library.name_evidence_segment(row):
            continue
        for name, quote, signal in library.book_name_signals(row.get('文本') or ''):
            if re.sub(r'\s+', '', name) != own_title:
                add(name, 'book', quote, signal, row)
    return out


def merge_explicit_names(previous, evidence):
    """A stronger occurrence can displace a local guess without changing other occurrences."""
    verified = {}
    for row in evidence:
        key = (row['name'], row['seg'])
        verified.setdefault(key, {})[row['cat']] = row
    manual = {(row.get('name'), row.get('seg')) for row in previous
              if str(row.get('src') or '').startswith('人工')}
    for key in manual:
        verified.pop(key, None)
    rows = []
    for row in previous:
        key = (row.get('name'), row.get('seg'))
        matches = verified.get(key, {})
        cat = row.get('cat')
        if str(row.get('src') or '').startswith('人工'):
            rows.append(row)
        elif row.get('name_evidence'):
            # A prior evidence row is reconstructed from today's source. If its
            # anchor changed after reparse, it cannot be republished unchanged.
            continue
        elif matches and (cat in matches or cat in ('concept', 'other')):
            continue
        else:
            rows.append(row)
    rows.extend(row for matches in verified.values() for row in matches.values())
    return rows


def _parse(text):
    cur, out = {}, []
    for raw in (text or '').splitlines():
        line = raw.strip()
        if line == '---':
            if cur.get('seg'):
                out.append(cur)
            cur = {}
            continue
        m = re.match(r'(SEG|PLACE|ORG|OBJECT|ANIMAL|PLANT|TAXON|OTHER)\s*[:：]\s*(.+)', line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip().strip('，。；、')
        if key == 'SEG':
            if cur.get('seg'):
                out.append(cur)
            cur = {'seg': val}
        else:
            cur.setdefault(KEYMAP[key], []).append(val)
    if cur.get('seg'):
        out.append(cur)
    return out


SPECIES_CACHE = os.path.join(lexicon.DIR, 'species_cache.json')


def _cache():
    try:
        return json.load(io.open(SPECIES_CACHE, encoding='utf-8'))
    except Exception:
        return {}


def _latin_batch(names):
    """中文名 → 拉丁学名，一次调用；不确定的留空。"""
    cache = _cache()
    todo = [n for n in names if n not in cache]
    for i in range(0, len(todo), 40):
        part = todo[i:i + 40]
        prompt = ('给出下列中文名的拉丁学名（属名+种加词），只输出 JSON：'
                  '{"牡丹":"Paeonia suffruticosa", ...}。不确定的写空字符串。\n' + '、'.join(part))
        try:
            res = llm.chat([{'role': 'user', 'content': prompt}], max_tokens=1600, json_mode=True)
            got = json.loads(res['text'])
        except Exception:
            got = {}
        for n in part:
            cache[n] = (got.get(n) or '').strip()
        try:
            json.dump(cache, io.open(SPECIES_CACHE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        except Exception:
            pass
    return {n: cache.get(n, '') for n in names}


def _get_json(url, timeout=6):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _gbif(latin):
    """学名核验：先精确匹配，再宽松匹配，最后用 search 找接受名（含异名）。"""
    if not latin:
        return None
    d = _get_json('https://api.gbif.org/v1/species/match?name=' + urllib.parse.quote(latin))
    if d and d.get('matchType') == 'EXACT' and d.get('scientificName'):
        return d['scientificName']
    d = _get_json('https://api.gbif.org/v1/species/match?name=' + urllib.parse.quote(latin) + '&strict=false')
    if d and d.get('matchType') in ('EXACT', 'FUZZY') and d.get('scientificName'):
        return d['scientificName']
    s = _get_json('https://api.gbif.org/v1/species/search?q=' + urllib.parse.quote(latin) + '&rank=SPECIES&limit=3')
    genus = (latin.split()[0] if latin.split() else '').replace('×', '').lower()
    for r in ((s or {}).get('results') or []):
        if r.get('rank') != 'SPECIES':
            continue
        # 属名必须对得上，否则搜索会把任意物种当结果返回
        sn = (r.get('scientificName') or '').replace('×', '').lower()
        if genus and not sn.startswith(genus):
            continue
        if not r.get('synonym'):
            return r.get('scientificName')
        acc = r.get('acceptedNameUsage') or r.get('accepted')
        if acc:
            return acc
        key = r.get('acceptedKey') or r.get('nubKey')
        if key:
            a = _get_json('https://api.gbif.org/v1/species/%s' % key)
            if a and a.get('scientificName'):
                return a['scientificName']
    return None


# ============================================================
# 提示词规则：规则集中在这里，跨书复用，不为某本书改提示词
# ============================================================
PROMPT_VERSION = 'entities-v2'
CAT_RULES = [
    ('PLACE', '地名', '国家/省/市/县/区/镇/村/山/河/湖/海/岛/地区。朝代、政权、民族不算。'),
    ('ORG', '机构', '出版社/报社/研究所/大学/学院/医院/图书馆/博物馆/公司/工厂/'
                    '电视台/政府机关/政协/协会。官名、职位、品牌名不算。'),
    ('OBJECT', '器物', '具体的工具、器物、器械、服饰、车辆、建筑部件。'
                       '材料（牛皮/丝绢）、泛称（行李/东西）不算。'),
    ('ANIMAL', '动物', '具体的动物物种或俗称（山蝉/蚯蚓）。「动物/牲畜」这类泛称不算。'),
    ('PLANT', '植物', '具体的植物物种、药材名（红松/人参/五味子）。'
                      '「植物/树木/蔬菜」这类泛称不算。'),
    ('TAXON', '科属', '分类阶元名：以 科/属/目/纲/门/族 结尾（毛茛科/卷柏属/半翅目）。'
                      '它不是物种，必须单列，不要塞进植物或动物。'),
    ('OTHER', '其他', '拿不准的放这里，不要硬塞进上面六类。'),
]
RULES_TEXT = '\n'.join('- %s %s：%s' % (k, cn, d) for k, cn, d in CAT_RULES)

EXAMPLES = """示例（植物志）：
SEG: B56-14-P01
PLACE: 黑龙江 | 吉林
TAXON: 毛茛科
PLANT: 红松 | 人参
ORG: 黑龙江科学技术出版社

示例（史书）：
SEG: S03-P07
PLACE: 洛阳 | 关中
ORG: 御史台
OBJECT: 铜壶

示例（小说）：
SEG: N12-P03
PLACE: 上海
OBJECT: 黄包车
ANIMAL: 黄狗
"""


def _prompt(part):
    body = '\n'.join('【段 %s】%s' % (r.get('id'), (r.get('文本') or '')[:400]) for r in part)
    return ('从下面每段里找出六类专名，按类别归位。\n' + RULES_TEXT +
            '\n规则：\n'
            '1) 名字必须在原文逐字出现，不改写、不翻译、不补全、不把别名当正名；\n'
            '2) 人名、《书名》里的字不标；\n'
            '3) 民族/朝代/政权（蒙古、明朝、突厥）哪类都不算；\n'
            '4) 同一段同一名字只写一次；没有该类就省略该行；\n'
            '5) 严格按格式输出，一段一组，用 --- 分隔：\n'
            'SEG: 段号\nPLACE: 名称1 | 名称2\nORG: ...\n\n' + EXAMPLES + '\n\n' + body)


def _done_path(code):
    return os.path.join(ROOT, code, '.entities_done.json')


def refused_path(code):
    return os.path.join(ROOT, code, '.entities_refused.json')


def _partial_path(code):
    return os.path.join(ROOT, code, 'entities.partial.jsonl')


def _load_json(path, default):
    try:
        with io.open(path, encoding='utf-8') as fp:
            return json.load(fp)
    except Exception:
        return default


def _append_rows(path, rows):
    with io.open(path, 'a', encoding='utf-8') as fp:
        for g in rows:
            fp.write(json.dumps(g, ensure_ascii=False) + '\n')


def _write_checkpoint(path, value, lines=False):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=os.path.dirname(path), delete=False) as fp:
        pending = fp.name
        try:
            if lines:
                for item in value:
                    fp.write(json.dumps(item, ensure_ascii=False) + '\n')
            else:
                json.dump(value, fp, ensure_ascii=False)
            fp.close()
            os.replace(pending, path)
        finally:
            if os.path.exists(pending):
                os.unlink(pending)


def _accept(part, text, people):
    """模型输出 → 通过逐字校验的候选（类别纠正在这里做，不靠提示词）。"""
    out = []
    by_id = {r.get('id'): r for r in part}
    for blk in _parse(text):
        seg = blk.get('seg')
        r = by_id.get(seg)
        if not r:
            continue
        body = r.get('文本') or ''
        unmarked = re.sub(r'《[^《》\n]*》', ' ', body)
        for cat in ('place', 'org', 'object', 'animal', 'plant', 'taxon', 'other'):
            for raw_name in blk.get(cat, []):
                for name in re.split(r'[、，,；;|]', raw_name):
                    name = name.strip()
                    name_s = to_simplified(name)
                    if len(name) < 2 or name in people or name_s in people \
                            or name in STOP.get(cat, ()) or name_s in STOP.get(cat, ()):
                        continue
                    if name not in unmarked:
                        continue
                    if re.search(r'(网|网页|新闻网|版权|客户端|公众号|微博|APP|网站)', name):
                        continue
                    c2, conf, why = ec_classify(name, body, hint=cat,
                                                known_people=people)
                    if c2 == 'org' and conf < 0.8:
                        c2, conf, why = 'other', 0.3, '原文出现了这个名称，类别仍需核对'
                    if c2 in ('plant', 'animal') and name.endswith(('酸', '酸盐', '溶液', '试剂', '粉末')):
                        continue
                    out.append({'name': name, 'name_s': name_s,
                                'cat': c2, 'seg': seg,
                                'book': r.get('篇') or '',
                                'src': '分类器' if c2 != 'other' else '待人工',
                                'ver': PROMPT_VERSION,
                                'conf': conf, 'why': why})
    return out


def extract(code, batch=8, grow=True, redo=False, max_batches=None, no_gbif=False,
            require_complete=False, on_progress=None):
    """按段抽专名。支持断点续跑：已处理的段记录在 .entities_done.json，不重复花钱。"""
    rows = _rows(code)
    people = _people(code)
    dp, pp, refused_file = _done_path(code), _partial_path(code), refused_path(code)
    done = set() if redo else set(_load_json(dp, []))
    refused = set() if redo else set(_load_json(refused_file, []))
    if redo:
        for x in (dp, pp, refused_file):
            if os.path.exists(x):
                os.remove(x)
    # 第一次跑新版：把旧的 entities.jsonl 当种子，不覆盖已有成果
    old_ent = os.path.join(ROOT, code, 'entities.jsonl')
    if not os.path.exists(pp) and not redo and os.path.exists(old_ent):
        import shutil
        shutil.copyfile(old_ent, pp)
    got = []
    valid_ids = {row.get('id') for row in rows}
    if os.path.exists(pp):
        with io.open(pp, encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        if item.get('seg') in valid_ids:
                            got.append(item)
                    except Exception:
                        pass
    if not done:
        done = {g.get('seg') for g in got if g.get('seg')}
    todo = [r for r in rows if r.get('id') not in done and r.get('id') not in refused]
    total_batches = (len(todo) + batch - 1) // batch
    consecutive_errors = 0
    if on_progress:
        on_progress(0, total_batches)
    for i in range(0, len(todo), batch):
        if max_batches is not None and i // batch >= max_batches:
            print('  已到 --max-batches 上限，停在 %d/%d 批' % (i // batch, total_batches))
            break
        part = todo[i:i + batch]
        current_batch = i // batch + 1
        try:
            res = llm.chat([{'role': 'system', 'content': SYS},
                            {'role': 'user', 'content': _prompt(part)}], max_tokens=3000, timeout=60, retries=1)
        except llm.SourceRefusedError:
            consecutive_errors = 0
            refused.update(r['id'] for r in part)
            _write_checkpoint(refused_file, sorted(refused))
        except Exception as e:
            consecutive_errors += 1
            print('  批 %d/%d 失败：%s' % (current_batch, total_batches, e))
        else:
            consecutive_errors = 0
            new = _accept(part, res.get('text') or '', people)
            if new:
                _append_rows(pp, new)
                got.extend(new)
            done.update(r.get('id') for r in part)
            _write_checkpoint(dp, sorted(done))
            print('  批 %d/%d：+%d 条，已处理 %d/%d 段' % (
                current_batch, total_batches, len(new), len(done), len(rows)), flush=True)
        if on_progress:
            on_progress(current_batch, total_batches)
        if consecutive_errors >= 3:
            break

    if require_complete and not valid_ids.issubset(done | refused):
        return got

    # 动植物：中文名 → 拉丁学名 → GBIF 校验，通过的上调为 GBIF
    species = [g for g in got if g['cat'] in ('animal', 'plant')]
    if species and not no_gbif:
        names = sorted({g['name'] for g in species})
        latin = _latin_batch(names)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as ex:
            sci_map = dict(ex.map(lambda n: (n, _gbif(latin.get(n) or '')), names))
        for g in species:
            sci = sci_map.get(g['name']) or ''
            if sci:
                g['src'] = 'GBIF'
                g['sci'] = sci

    # 地名归一：别名合并 +「X地区」并入「X」
    places = {g['name'] for g in got if g['cat'] == 'place'}

    def _np(n):
        n = PLACE_ALIAS.get(n, n)
        if n.endswith('地区') and n[:-2] in places:
            n = n[:-2]
        return n

    for g in got:
        if g['cat'] == 'place':
            g['name'] = _np(g['name'])
            g['name_s'] = g['name']

    book = _load_json(os.path.join(ROOT, code, 'book.json'), {}) or {}
    title = book.get('book') or next((r['书'] for r in rows if r.get('书')), '')
    got = merge_explicit_names(got, explicit_name_rows(title, rows))

    # 去重（同名同段同一类），按出现次数排序
    seen, out = set(), []
    for g in got:
        k = (g['name'], g['cat'], g['seg'])
        if k in seen:
            continue
        seen.add(k)
        out.append(g)
    occurrences = Counter(item['name'] for item in out)
    out.sort(key=lambda item: (-occurrences[item['name']], item['cat']))

    path = os.path.join(ROOT, code, 'entities.jsonl')
    _write_checkpoint(path, out, lines=True)

    # 默认不把模型结果写进词典：模型错一次，词典会把它变成“永久正确”。
    # 只有人工/审核后的词典才允许增长；确需自动增长时显式设环境变量。
    if grow and os.environ.get('BOOKDISTILL_LEXICON_GROW') == '1':
        cnt = Counter((g['name'], g['cat']) for g in out if not g.get('name_evidence'))
        for (name, cat), n in cnt.items():
            if n >= 2 and not lexicon.match(name):
                lexicon.add(cat, name, src='corpus', note='%s ×%d' % (code, n))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('code')
    ap.add_argument('--batch', type=int, default=8)
    ap.add_argument('--no-grow', action='store_true')
    ap.add_argument('--redo', action='store_true', help='忽略断点，全部重抽')
    ap.add_argument('--max-batches', type=int, default=None, help='只跑前 N 批（试跑用）')
    ap.add_argument('--no-gbif', action='store_true', help='跳过 GBIF 学名核验（网络慢时用）')
    ap.add_argument('--root', default=None)
    a = ap.parse_args()
    if a.root:
        globals()['ROOT'] = a.root
    rows = extract(a.code, a.batch, grow=not a.no_grow, redo=a.redo,
                   max_batches=a.max_batches, no_gbif=a.no_gbif)
    from collections import Counter
    print('%s：%d 条' % (a.code, len(rows)), dict(Counter(r['cat'] for r in rows)))
    for r in rows[:8]:
        print('   %-6s %-8s %s' % (r['cat'], r['name'], r['seg']))
    print('词典：', lexicon.stats())
