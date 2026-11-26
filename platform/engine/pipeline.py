# -*- coding: utf-8 -*-
"""主流水线：raw 文本 → 判型 → 稳定层资产 → 报告。

用法：
    python pipeline.py                 # 跑全库
    python pipeline.py 朝花夕拾 牡丹亭    # 只跑指定书

设计原则（决定这套东西能不能持续用）：
  1. 每条结论都带实测数字，不写死。数字由脚本填充。
  2. 判型只出「建议」，不硬拦截。低置信度明确标出来。
  3. 产物按「能力等级」分层：稳定层（零判断）/ 半稳定层（需复核）。
  4. 每本书写出独立目录，可单独更新，互不影响。
"""
import os, sys, io, json, re, glob, hashlib, shutil, time
import paths as P

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import structure as ST
import wash as W
import measure as M
import library as LIB
import cards as CD
import concepts as CC
import bridge as BG
import tocclean as TC

RAW = P.RAW
OUT = P.OUT


def code_of(name):
    """书名 → 稳定短码，用作锚点前缀。沿用既有习惯：SZ=孙子。"""
    fixes = {'孙子兵法': 'SZ', '朝花夕拾': 'ZHS', '牡丹亭': 'MDT',
             '呐喊': 'NH', '野草': 'YC', '儒林外史': 'RLWS',
             '山海经': 'SHJ', '小窗幽记': 'XCYJ'}
    if name in fixes:
        return fixes[name]
    # 其余用拼音首字母近似：取书名里每个汉字段的第一个字母无从得知，
    # 改为稳定短码 BK + 序号，并写进 book.json 供人改。
    return None


# ── 书码注册表：书码必须跨次运行稳定 ──────────────────────────────
# 旧实现用「本次筛选后的列表序号」生成书码：单本跑新书时序号从 1 开始，
# 于是新书永远拿 B01，直接覆盖 B01《2018版闲情偶寄》的 out 目录 —— 静默数据损坏。
# 现在书码单独落在 library/book_codes.json：同一本书永远同一个码，新书取全库最大码 +1。
CODES_PATH = os.path.join(P.LIB, 'book_codes.json')


def _read_json(path, default):
    try:
        with io.open(path, encoding='utf-8') as fp:
            return json.load(fp)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_codes():
    """读取书码注册表。首次运行从 books.json 回填，保证既有 55 本码不变。"""
    codes = _read_json(CODES_PATH, {})
    if not isinstance(codes, dict):
        codes = {}
    codes = {str(k): str(v) for k, v in codes.items() if k and v}
    changed = False
    books = _read_json(os.path.join(OUT, 'books.json'), [])
    if isinstance(books, list):
        for b in books:
            if not isinstance(b, dict):
                continue
            name, code = b.get('book'), b.get('code')
            if name and code and name not in codes:
                codes[name] = code
                changed = True
    if changed or not os.path.exists(CODES_PATH):
        _write_json(CODES_PATH, codes)
    return codes


def alloc_code(name, codes):
    """给一本书分配稳定书码，并立即落盘。"""
    if codes.get(name):
        return codes[name]
    fixed = code_of(name)
    used = set(codes.values())
    if fixed and fixed not in used:
        code = fixed
    else:
        nums = [int(c[1:]) for c in used if re.fullmatch(r'B\d{2,}', c)]
        n = (max(nums) + 1) if nums else 1
        while 'B%02d' % n in used:
            n += 1
        code = 'B%02d' % n
    codes[name] = code
    _write_json(CODES_PATH, codes)
    return code


# ── 篇名质量：引用层能不能「按篇回溯」的前提 ──────────────────────
# 为什么这项必须单列：检索出的一段文本，用户要能顺着「书名 + 篇名」找到位置。
# 篇名若是「第3章」这种占位符，回溯路径等于没有，但页面若只显示「篇数 34」，
# 看起来和真篇名一模一样 —— 这是最容易虚报的一格。
_PNAME_BAD = [
    (re.compile(r'^第\d+章$'), '占位符'),
    (re.compile(r'^作者[:：]'), '元数据'),
    (re.compile(r'^卷[一二三四五六七八九十]+$'), '仅卷名'),
    (re.compile(r'[。！？]$'), '正文句'),
]


def _pname_quality(segs, structure=''):
    """返回 {可用率, 可用数, 正文段数, 坏法, 性质, 说明}。

    性质分两种，不许混：
      '书无篇名'   —— 原作者只分节未写标题（四世同堂按「一/二」分节），
                      这不是缺陷，是书的体例；引用层只能用节次定位。
      '抽取失败'   —— 书里有篇名，我们没认出来，属工程缺陷，须修。
    """
    body = [s for s in segs if s.get('篇序', 0) > 0]
    if not body:
        if structure == 'body_only':
            return {'可用率': None, '正文段数': len(segs), '性质': '按段定位',
                    '说明': '短材料未检测到章节标题，可按原文段落核对和引用。'}
        # 两种零段的成因完全不同，必须分开报：
        #   '无正文'    —— 文件本身没有可切正文（空文件、纯目录、解码失败）
        #   '切不开'    —— 有正文，但底本没有任何可用的结构标记，全落进前置段。
        #                  这是工程能力的边界，不是书的问题，也不是数据缺。
        # 曾把 flat 一律写成「无正文」，读者会以为这些书没有内容 —— 事实是
        # 周礼 4.9 万字、西厢记 3.7 万字、诗品 5771 字都在，只是切不开。
        if structure == 'flat':
            return {'可用率': None, '正文段数': 0, '性质': '切不开',
                    '说明': ('当前切分器未能定位篇界；请核对目录和标题格式。'
                             '这不代表原书没有章节，当前只能按段落定位')}
        return {'可用率': None, '正文段数': 0, '性质': '无正文',
                '说明': '全书未切出正文段'}
    bad = {}
    for s in body:
        nm = s.get('篇', '') or ''
        for pat, lab in _PNAME_BAD:
            if pat.search(nm):
                bad[lab] = bad.get(lab, 0) + 1
                break
    ok = len(body) - sum(bad.values())
    rate = round(ok * 100.0 / len(body), 1)
    if rate >= 95:
        nature, note = '篇名可用', '可直接按篇回溯原文'
    elif set(bad) == {'占位符'}:
        nature = '书无篇名'
        note = ('底本只有节次编号，无篇题（原作者体例如此），'
                '不是抽取失败；引用层只能按节次定位')
    elif '仅卷名' in bad:
        nature = '仅到卷级'
        note = ('底本卷内条目未单独成行（如条目连排），'
                '只能定位到卷，卷内位置须人工')
    elif '正文句' in bad:
        nature = '抽取失败'
        note = '正文句被当成篇名，须修切分器'
    else:
        nature = '部分缺失'
        note = '部分篇名未识别'
    return {'可用率': rate, '可用数': ok, '正文段数': len(body),
            '坏法': bad, '性质': nature, '说明': note}


def _atlas_entries(path, text, title=''):
    """图鉴的条目：优先用上传时落盘的版面文件，没有版面就退回纯文本切。"""
    try:
        import atlas as AT
        lp = os.path.splitext(path)[0] + '.layout.jsonl'
        if os.path.exists(lp):
            return AT.entries_from_pages(AT.load_pages(lp), title), '版面还原'
        return AT.entries_from_text(text, title), '纯文本兜底（多栏可能串行）'
    except Exception as e:
        return [], '失败：%s' % e


def _story_people(path, text):
    """P12 纪事型：优先从版面页的资料框取人，没有版面再按文本切。"""
    try:
        import story as SP
        lp = os.path.splitext(path)[0] + '.layout.jsonl'
        if os.path.exists(lp):
            import atlas as AT
            return SP.people_from_pages(AT.load_pages(lp)), '版面资料框'
        return SP.people_from_text(text), '纯文本兜底'
    except Exception as e:
        return [], '失败：%s' % e


def content_sources(path, text, title=''):
    """Detect specialised source blocks from the document, independently of genre."""
    normalized = re.sub(r'\s+', '', text)
    entries, entry_source, people, people_source = [], '', [], ''
    fields = ('来源', '生境', '分布', '学名', '原植物', '识别要点')
    if normalized.count('来源') >= 2 and sum(normalized.count(field) >= 2 for field in fields) >= 3:
        entries, entry_source = _atlas_entries(path, text, title)
        entries = [row for row in entries if (row.get('cname') or row.get('latin'))
                   and len(set(row.get('fields') or {}) & {'来源', '原植物', '生境', '分布'}) >= 3]
        if len(entries) < 2:
            entries, entry_source = [], ''
    if len(re.findall(r'姓名[：:]', normalized)) >= 2:
        people, people_source = _story_people(path, text)
        people = [row for row in people if len(row.get('fields') or {}) >= 2]
    return entries, entry_source, people, people_source


def _people_plan(text, people):
    """把「资料框里的姓名」变成篇界：一人一篇，篇名就是人名。

    structure 的 echo/solo 会把资料框里的「中国科学院院士」这类重复行当篇名，
    切出「身份：物理学家…」这种假篇。纪事型直接按人物切。
    """
    # 必须用 structure 自己的行表来定位：它和 outline() 用的是同一份 lines，
    # 自己 split('\n') 会因为空行/页标记错位，把篇界挪到别的段上。
    lines = ST.source_lines(text)
    has_pages = bool(ST.PAGE.search(text))
    found, seen = [], set()
    for person in people:
        name = person.get('name') or ''
        if not name or name in seen:
            continue
        key = ST.norm(name)
        for i, (pno, line, block) in enumerate(lines):
            if has_pages and person.get('page') and pno != person['page']:
                continue
            label = re.fullmatch(r'姓名[：:]\s*(.*)', ST.norm(line))
            if not label:
                continue
            value = label[1]
            if not value and i + 1 < len(lines) and lines[i + 1][2] == block:
                value = ST.norm(lines[i + 1][1])
            if value == key:
                seen.add(name)
                found.append((i, name))
                break
    if len(found) < 3:
        return None
    found.sort()
    return {'mode': 'solo', 'unit': '人',
            'titles': [n for _, n in found],
            'solo_idx': [i for i, _ in found]}


def run_one(path, code, proto_override=None):
    name = os.path.basename(path)[:-4]
    # 必须用 load_ex 拿 algo_punct 标记：白文古籍会被自动补句读，
    # 补出来的句号会伪造「句短且等长」的韵文特征。
    # 踩过的坑：run.py 只调 W.load，标记丢失，于是《逸周书》在盲测脚本里
    # 正确拒判、在真实流水线里却判成 P7 韵文集 —— 测的和跑的不是同一条路。
    text, algo_punct = W.load_ex(path)
    raw_text = text
    source_version = hashlib.sha256(raw_text.encode('utf-8')).hexdigest()
    # 目录/索引页清洗：只在检测到成块目录时改动文本；普通书原样返回。
    text, toc_info = TC.clean(text)

    # ---------- 1 判型 ----------
    r = M.analyze(text, algo_punct=algo_punct)

    # 人工改判：保留六轴实测值，但原型、产物清单、置信度按人工指定。
    # 为什么不在 judge 里改：判型规则是全书共用的，单本改判只该影响这一本；
    # 六轴数字仍要落盘，否则以后看不出「人为什么改」。
    if proto_override:
        if proto_override not in M.ARCH:
            raise SystemExit('未知原型：%s' % proto_override)
        arch, outputs = M.ARCH[proto_override]
        r['code'] = proto_override
        r['arch'] = arch
        r['outputs'] = outputs
        r['conf'] = '人工'
        r['ev'] = ['人工改判：按 %s %s 重跑（六轴实测值保留，仅改判定）'
                   % (proto_override, arch)]
        r['stability'] = None
        r['mixed'] = []
        r['fit'] = None
        r['reject_kind'] = None

    # ---------- 2 结构探测 ----------
    atlas_entries, atlas_src, story_people, story_src = content_sources(path, text, name)
    layout_path = os.path.splitext(path)[0] + '.layout.jsonl'
    plan = ST.probe(text, name, layout_path=layout_path)
    if story_people and plan.get('mode') != 'pdf_outline':
        ppl_plan = _people_plan(text, story_people)
        if ppl_plan:
            plan = ppl_plan
    outline = ST.outline(text, plan)
    continuous_body = (not outline and not algo_punct and not toc_info['删除行数']
                       and ST.continuous_short_body(text))

    # ---------- 3 清洗切段 ----------
    segs, wst = W.build(text, code, [(nm, i) for nm, i, _ in outline], layout_path=layout_path,
                        continuous_body=continuous_body)
    for sg in segs:
        sg['锚点'] = f"{code}·{sg['篇']}·P{sg['段']:02d}"
        sg['书'] = name

    # ---------- 4 稳定层 ----------
    idx = LIB.outline_index(segs)
    nm_tab = LIB.names(segs)
    qp, kj = LIB.qupai_kejie(segs)
    # P12 纪事型：资料框里已经写明了这本书写的是谁，直接以这 33 个人为准。
    # 通用姓氏法在人物故事里会抽出「办公室/师傅/双手」这类假人名（首字恰好是姓）。
    if story_people:
        ppl, pollute = LIB.people(segs, cand=[p['name'] for p in story_people])
    else:
        ppl, pollute = LIB.people(segs)
    # 版权页著者补进人物表：学术书作者常在正文里被反复引用，但不对白。
    try:
        import cip as _CIP
        _cip = _CIP.parse(text, name)
        _au = (_cip.get('著者') or '').strip()
        _m = re.match(r'([\u4e00-\u9fa5]{2,4})', _au)
        _an = _m.group(1) if _m else ''
        if _an and _an not in {p.get('人物') for p in ppl}:
            _hits = [x for x in segs if _an in x['文本']]
            if _hits:
                ppl.append({'人物': _an, '通名': False,
                            '频次': sum(x['文本'].count(_an) for x in _hits),
                            '首现': _hits[0]['id'], '首现篇': _hits[0]['篇'],
                            '分布篇数': len({x['篇'] for x in _hits}),
                            '姓氏法': 0, '对白归属': 0,
                            '来源': '版权页著者', '证据': '强证据'})
    except Exception:
        pass
    ready, why, gmet = LIB.graph_ready(segs, ppl, pollute)
    st = LIB.stats(segs)

    # ---------- 4.4 结构审计（只读，落盘给页面/全库报告）----------
    struct_audit = TC.audit(segs, outline, text)
    affected_chapters = set(struct_audit.get('受影响篇序') or [])
    for sg in segs:
        if sg['篇序'] in affected_chapters:
            sg['source_structure_suspect'] = True

    # ---------- 4.5 概念层（论断段定位）----------
    # 用途：热点来了先按论断段召回候选段落，再交人挑。
    # 这是「定位器」，不是主题标签 —— 概念本身机器抽不准（见 concepts.py 里
    # 记录的五条失败路径），因此本层只负责「哪一段在讲道理」。
    cc = CC.build(segs)

    # ---------- 4.6 议题桥接层（接引用层的热点匹配）----------
    # 上面 L6 只解决「哪一段在讲道理」，回答不了「这段讲的是哪个议题」。
    # 议题词本身机器抽不出（见 bridge.py：现代议题词在古籍里命中 0，
    # 古文能跨书复用的 17 个词全是语词层面，没有一个是议题），
    # 因此这一层走「人给义类归属、机器批量执行 + 逐条回查」。
    # 每条都带整句原文与锚点，落到 pages 时能被读者一眼看回原书。
    _argu_anchors = {r['锚点'] for r in cc['论断段']}
    bg = BG.match_book(segs, _argu_anchors)

    # ---------- 5 卡片层候选 ----------
    card_rows, content_checks, card_drop = CD.extract_by_content(
        {'book': name, 'code': code},
        segs, r['code'], algo_punct, atlas_entries=atlas_entries,
        story_people=story_people, layout_plan=plan)

    book = {
        'book': name, 'code': code,
        '原型': r['code'], '原型名': r['arch'],
        '置信': r['conf'], '依据': r['ev'], '混合': r['mixed'],
        '稳定性': r['stability'],
        # 分块吻合度：主判在 10 个分块中占多少比例。
        # 这是「整本属于这一类」这句话的可信程度，比 mixed 更硬。
        # 《四月天·文学卷》只有 40%，页面必须把这个数字摆出来。
        '吻合': r.get('fit'),
        # 合集构成：书里自己写明了几种文体时，如实报占比，不用一个类概括整本。
        '合集': r.get('anthology') or [],
        # 拒判时明确记录原因与性质，页面据此显示「本类书暂未支持」
        # reject_kind: 'data'=文本不可用（补数据重试） / 'unknown'=疑似第十类
        '拒判': r['code'] is None,
        '拒判性质': r.get('reject_kind'),
        '人工改判': bool(proto_override),
        '结构审计': struct_audit,
        '特征': r['m'],
        # 算法补句读标记。必须在 book.json 里留痕：
        # 它为 True 时，这本书的句读是我们算的，不是原文的，
        # 后续任何引文产物都不得使用补出来的标点（等于伪造底本）。
        '算法断句': algo_punct,
        '结构模式': plan['mode'], '结构样式': plan.get('pattern') or '', '结构单位': plan['unit'],
        # 篇名质量：这三项决定了这本书能不能被「按篇回溯」。
        # 引用层检索出的一段，用户要能顺着篇名找到原文的位置；
        # 若篇名是「第3章」占位符，等于没有回溯路径。
        # 必须把「书本身没篇名」与「我们没抽到篇名」分开报 ——
        # 前者是书的属性（四世同堂原作者只分节不写标题），后者是工程缺陷。
        '篇名质量': _pname_quality(segs, 'body_only' if continuous_body else plan.get('mode', '')),
        '篇数': wst['npian'], '段数': wst['nseg'],
        '汉字_原文': wst['src_han'], '汉字_切段': wst['seg_han'],
        '保留率': wst['retention'],
        '通名污染率': pollute,
        '可出关系图谱': ready,
        '图谱判定': why,
        # 准入指标的原始值必须落盘：页面上要能显示「稳定配对 406 对」，
        # 而不是只显示一句「可出图谱」。数字可复算是本项目所有结论的前提。
        '图谱指标': gmet,
        # 人物表的**能力边界**必须落盘：让页面能说清「这本书为什么没有人物表」。
        # 「这本书没有人物关系」与「我们抽不出人物」是两回事，
        # 写成同一句话就是把能力缺陷冒充成关于书的结论。
        '人物抽取边界': LIB.LAST_ABILITY,
        '强证据人物数': len([x for x in ppl if x.get('证据') == '强证据']),
        '人物表性质': '自动候选，须人工/模型确认后方可用于图谱',
        '声明的产物': r['outputs'],
        # 卡片层候选：如实记数量与抽取构成，页面据此区分「有卡」与「有候选」。
        # 候选卡**不算**已确认卡片，不与 237 条人工卡混算。
        '候选卡数': len(card_rows),
        # 议题标签：供引用层做「热点 → 书」匹配。
        # 与 L4 的区别：L4 是书里出现的专名（客观），L7 是议题归属（今用判断）。
        '议题': [{'议题': g['议题'], '代号': g['代号'],
                  '情绪词': g['情绪词'], '受众词': g['受众词'],
                  '锚点': g['锚点'], '原文': g['原文'],
                  '证据': g['证据'], '依据': g['依据'],
                  '性质': g['性质'], '命中数': g['命中数'],
                  '论断段数': g.get('论断段数', 0)} for g in bg],
        '内容检查': content_checks,
        '候选卡构成': '；'.join(f"{key} {item['count']} 条" for key, item in content_checks.items() if item['count']),
        '候选卡丢弃': card_drop,
        # 图鉴专用：条目数与条目抽取路径（版面/纯文本），页面据此说明来源。
        '条目数': len(atlas_entries or []),
        '条目来源': atlas_src,
        '人物条目数': len(story_people or []),
        '人物条目来源': story_src,
        # 概念层：只出论断段定位器。数量与边界都必须落盘，
        # 页面要能说清「这一层是什么、不是什么」。
        '论断段数': len(cc['论断段']),
        '概念层性质': cc['性质'],
        '概念层边界': cc['边界'],
        '概念层缺口': CC.gap_note(len(cc['论断段'])),
    }

    if toc_info.get('删除行数'):
        book['目录清洗'] = dict(toc_info,
            **{'原文汉字': len(W.HAN.findall(raw_text)),
               '清理后汉字': len(W.HAN.findall(text))})

    d = os.path.join(OUT, code)
    os.makedirs(d, exist_ok=True)
    # 源文件路径只写相对路径，避免换机器失效
    book['源文件'] = f'书库分类/raw/{name}.txt'

    def dump(fn, rows):
        with io.open(os.path.join(d, fn), 'w', encoding='utf-8') as fp:
            for x in rows:
                fp.write(json.dumps(x, ensure_ascii=False) + '\n')

    book['source_version'] = source_version
    book['segment_version'] = hashlib.sha256(json.dumps(segs, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    old_segments = os.path.join(d, 'segments.jsonl')
    if os.path.exists(old_segments):
        with io.open(old_segments, encoding='utf-8') as fp:
            previous_segments = [json.loads(line) for line in fp if line.strip()]
        old_hash = hashlib.sha256(json.dumps(previous_segments, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        if old_hash != book['segment_version']:
            history = os.path.join(d, '.history', old_hash[:16])
            os.makedirs(history, exist_ok=True)
            for original in ('book.json', 'segments.jsonl', 'outline.jsonl', 'cards.jsonl'):
                old_path = os.path.join(d, original)
                if os.path.exists(old_path):
                    shutil.copy2(old_path, os.path.join(history, original))
            derivatives = {}
            for filename in ('understanding.json', 'marketing.json', 'entities.jsonl', 'judge.json'):
                source = os.path.join(d, filename)
                if not os.path.exists(source):
                    continue
                shutil.copy2(source, os.path.join(history, filename))
                derivatives[filename.split('.')[0]] = {'status': 'stale', 'reason': '原文或章节结构已更新',
                                                       'source_version': old_hash, 'target_version': book['segment_version']}
                if filename in ('understanding.json', 'marketing.json'):
                    with io.open(source, encoding='utf-8') as fp:
                        data = json.load(fp)
                    data['stale'] = True
                    if filename == 'understanding.json':
                        for key in ('quotes', 'themes', 'summaries'):
                            if key in data:
                                data.setdefault('processing', {})[key] = {'status': 'stale', 'reason': '原文或章节结构已更新'}
                    _write_json(source, data)
            _write_json(os.path.join(d, 'derivative_status.json'), derivatives)
    dump('segments.jsonl', segs)
    dump('outline.jsonl', idx)
    dump('names.jsonl', nm_tab)
    dump('people.jsonl', ppl)
    CD.save_identity_registry(code, card_rows)
    dump('cards.jsonl', card_rows)
    dump('argu.jsonl', cc['论断段'])
    dump('qupai.jsonl', qp)
    dump('kejie.jsonl', kj)
    # 重跑是整本重写 book.json，会把应用侧/判定层的字段冲掉：CIP（版权页解析）、
    # CLC（分类号，含人工改判）。这两类不是流水线算出来的，必须原样带过去。
    bpath = os.path.join(d, 'book.json')
    keep = {}
    if os.path.exists(bpath):
        try:
            with io.open(bpath, encoding='utf-8') as fp:
                old = json.load(fp)
            keep = {k: old[k] for k in ('CIP', 'CLC') if k in old}
        except Exception:
            keep = {}
    book.update(keep)
    with io.open(bpath, 'w', encoding='utf-8') as fp:
        json.dump(book, fp, ensure_ascii=False, indent=1)

    return book


def main():
    want = sys.argv[1:]
    files = sorted(glob.glob(RAW + '/*.txt'))
    files = [f for f in files if not os.path.basename(f).startswith('_')]
    if want:
        # 精确按文件名（去掉 .txt）匹配。旧实现用子串，跑「三国」会把
        # 所有文件名含「三国」的书一起跑；上传入口不能接受这种误伤。
        stems = {os.path.splitext(os.path.basename(f))[0]: f for f in files}
        missing = [w for w in want if w not in stems]
        if missing:
            print('未找到书名：%s' % '、'.join(missing))
            print('当前可跑 %d 本；书名必须与 书库分类/raw/<书名>.txt 完全一致。'
                  % len(stems))
            print('可用书名（前 20）：%s' % '、'.join(sorted(stems)[:20]))
            sys.exit(2)
        files = [stems[w] for w in want]

    # 人工改判只允许单本跑：否则一次改判会把同一原型套到全库。
    proto_override = os.environ.get('BOOKDISTILL_PROTO') or None
    if proto_override:
        if len(files) != 1:
            print('人工改判一次只能跑一本，本次选中 %d 本。' % len(files))
            sys.exit(2)
        if proto_override not in M.ARCH:
            print('未知原型：%s（可用 %s）' % (proto_override, '、'.join(M.ARCH)))
            sys.exit(2)

    os.makedirs(OUT, exist_ok=True)
    codes = load_codes()
    books = []
    for i, f in enumerate(files, 1):
        name = os.path.splitext(os.path.basename(f))[0]
        b = run_one(f, alloc_code(name, codes), proto_override)
        books.append(b)
        print(f"[{i:>2}/{len(files)}] {b['book'][:18]:<20} "
              f"{(b['原型'] or '待开'):<4} {b['原型名']:<6}"
              f" 篇{b['篇数']:>3} 段{b['段数']:>4} {b['汉字_切段']:>7}字 "
              f"保留{b['保留率']:>5.1f}% 人物{b['强证据人物数']:>3}"
              f" 图谱{'✓' if b['可出关系图谱'] else '×'}"
              f" 卡{b['候选卡数']:>3}"
              + (f"  ⚠{b['依据'][0][:28]}" if b['拒判'] else ''))

    # 指定书名时**必须合并**，不能整体覆盖。
    #
    # 为什么：run.py 传进来的书名只是「本次要重跑的书」，下游 export/board/tagboard
    # 全部以 books.json 为唯一数据源。若单本跑就把 books.json 改写成只有这一本，
    # 页面会从「56 本实测」塌成「1 本实测」——实测过，看板 byte 从 406485 掉到 107800。
    # 这是「按书名跑一次就毁掉全库看板」的坑，比判型错更致命，因为它静默发生。
    bp = os.path.join(OUT, 'books.json')
    if want:
        old = []
        if os.path.exists(bp):
            try:
                old = json.load(io.open(bp, encoding='utf-8'))
            except Exception:
                old = []
        # 本次重跑的按书名为准覆盖旧记录，其余原样保留，新增的书追加到末尾
        fresh = {b['book']: b for b in books}
        nrun = len(fresh)
        merged = [fresh.pop(o['book'], o) for o in old]
        nadd = len(fresh)
        merged.extend(fresh.values())
        books = merged
        print(f"\n合并写入：重跑 {nrun} 本（新增 {nadd} 本），库内共 {len(books)} 本")

    # 原子写：books.json 是应用层读的唯一书单。若直接 open('w')，
    # 并发请求可能读到半截 JSON，store.sync_library() 会把它当成空库。
    tmp_bp = bp + '.tmp'
    with io.open(tmp_bp, 'w', encoding='utf-8') as fp:
        json.dump(books, fp, ensure_ascii=False, indent=1)
    os.replace(tmp_bp, bp)
    print(f"\n完成 {len(books)} 本，输出目录 {OUT}")


if __name__ == '__main__':
    main()
