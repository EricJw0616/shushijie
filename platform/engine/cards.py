# -*- coding: utf-8 -*-
"""卡片层候选抽取器：机器铺底稿，人只做确认。

## 为什么要有这一层

此前 237 条卡片**全部人工整理**，52 本书停在检索层。瓶颈不是「抽不出来」，
而是「抽出来的东西不敢用」——纯正则捞「X者，Y也」，一半词条是
「此五」「如此」「不出」这类指代短语，混进资产库就是污染。

本模块的定位因此不是「自动出卡」，而是**自动出候选 + 自动校验 + 标清缺口**：

  机器做（可复现、零判断）
    1. 从原文定位候选，带上逐字原文与锚点
    2. 自动过滤明显噪音（虚词首尾、停用词、全书只出现一两次的短语）
    3. 校验原文是否真能在正文逐字查到——查不到直接丢弃
    4. 逐条列出「这条卡还缺哪几个字段」

  人做（不可替代）
    1. 判定候选是不是真概念（机器只能判形态，判不了语义）
    2. 补白话定义、要点、易混淆、规则边界

## 卡片分级的硬定义（下游据此区分能不能当引文）

  `可回查: true`   ——「原文」「定义」都是逐字截取，可直接引用
  `可回查: false`  ——含二次加工文字，只能作阅读材料，不能当引文

候选卡一律 `状态: '候选'`。进 library 时单独成表，不与已确认卡混算。

## 算法断句的处置

`algo_punct=True` 的书，句读是算出来的。候选卡的「原文」若来自补出来的
句号切分，**不得作为引文**——等于伪造底本。因此这类书的候选卡
`可回查` 一律置 False，并在 `限制` 字段写明原因。
"""
import re, io, json, os, sys, hashlib, tempfile, shutil
import paths as P
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HAN = re.compile('[\\u3400-\\u4DBF\\u4E00-\\u9FFF\\uF900-\\uFAFF'
                 '\\U00020000-\\U0002FA1F]')

# ---------- 定义句抽取的过滤词表 ----------
# 这些是「X者，Y也」句法上成立、语义上不是概念的典型噪音。
# 全部来自实测（56 本书跑完后人工看前 200 条候选逐一记录），不是凭想象列的。
STOP_TAIL = set('者也矣乎而之其以所则於于為为与與及')
STOP_LEAD = set('者也矣乎而之其以所则於于是故若夫且盖蓋但惟唯')
STOPWORD = {
    '是故', '所以', '然而', '何以', '不然', '可见', '反之', '然则', '若夫',
    '由此', '大抵', '总之', '要之', '是以', '因此', '于是', '然後', '然后',
    '故曰', '所謂', '所谓', '如此', '如彼', '若是', '若是其', '此其',
}
# 指代词打头的一律不是概念：「此五」「此三」「知此」「有天下」
PRONOUN_LEAD = re.compile(r'^(?:此|是|彼|其|何|孰|若|如|知|有|無|无|不|未|莫|'
                          r'凡|諸|诸|所|故|今|古|夫|且|或|亦|皆|各|每|一|二|三|四|五|六|七|八|九|十)')

STRONG = re.compile('切忌|最忌|切不可|断不可|斷不可|万不可|萬不可|务须|務須|务必|務必|'
                    '必须|必須|必先|须先|須先|不得|不可|不宜|勿|毋|莫|忌')


def sents_of(t):
    """按句末标点切句，保留标点。"""
    out, cur = [], ''
    for ch in t:
        cur += ch
        if ch in '。！？；':
            out.append(cur)
            cur = ''
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out if x.strip()]


def han(t):
    return len(HAN.findall(t))


def _blank(t):
    """段内文本压成一行，去掉 PDF 抽取残留的断行。"""
    return re.sub(r'\s+', '', str(t))


def _first_line(t):
    """取正文的第一联（到第一个句末标点为止）。

    用途：作品候选的「原文」字段。要求是**单段之内的连续文字**，
    因为 verify() 是拿它去比对某一段的正文；而一首诗可能跨段，
    整首拼起来在单段里查不到。首联一定在起首那一段内，恒可回查。
    """
    m = re.match(r'^([\s\S]{4,40}?[。！？；])', t)
    if m:
        return m.group(1)
    m = re.match(r'^([\s\S]{4,30}?)[，、]', t)
    return (m.group(1) + '，') if m else t[:30]


def _clean_name(t):
    """清洗专名：去掉行内注音与断行。

    《山海经》底本形如「猨\\n同猿\\n翼之山」——注音「同猿」夹在山名中间，
    直接把换行去掉会得到「猨同猿翼之山」，既不是原文的山名也无法检索。
    规则：先按行拆，丢掉以「音/同/一作」开头的注音行，再拼。
    """
    parts = [p.strip() for p in str(t).split('\n') if p.strip()]
    keep = [p for p in parts
            if not re.match(r'^(?:音|同|一作|当作|俗作|本作|或作)', p)]
    return ''.join(keep) if keep else ''.join(parts)


# ============================================================
# 各类原型的抽取器
# ============================================================
# 统一返回结构（下游 export/board 只认这几个键）：
#   id / 书 / 码 / 类型 / 置信 / 锚点 / 原文 / 可回查 / 字段 / 待补 / 依据
# ============================================================


def _mk(code, seq, kind, conf, anchor, quote, fields, todo, why,
        requote=True, limit='', verify_mode='body'):
    """构造一条候选卡。

    verify_mode 决定 verify() 用哪条路核对：
      'body'  原文必须能在 segments 的**正文文本**里逐字查到（默认，绝大多数卡）
      'title' 原文是篇名/回目，只能在该篇的「篇」字段上查到，正文里没有。
              情节卡必须走这条：回目「甄士隱夢幻識通靈　賈雨村風塵怀閨秀」
              不在任何一段正文里，用 body 模式核对会 100% 被判不可回查。
    """
    return {
        'id': f'{code}-C{seq:03d}',
        '类型': kind, '置信': conf,
        '锚点': anchor, '原文': quote,
        # 每一句原文都必须真的能在 segments 里查到，由 verify() 统一复核；
        # 这里先声明「我认为可回查」，验不过就整条丢弃。
        '可回查': bool(requote),
        '字段': fields, '待补': todo, '依据': why,
        '限制': limit,
        '核对路': verify_mode,
        '状态': '候选',
    }


def _def_candidates(segs, code, limit_n=40):
    """定义句候选：「X者，Y也」。P1/P2/P3/P10 共用。

    精度控制靠四道过滤，缺一道就会出「此五」「如此」这类噪音：
      1. 词条 2-6 字，首尾不含虚词
      2. 词条不是指代词打头
      3. 词条全书出现 >=3 次（真概念会反复出现，一次性短语不是概念）
      4. 定义里不再出现词条本身（出现说明这句在举例，不是在下定义）
    """
    flat = ''.join(_blank(s['文本']) for s in segs)
    pat = re.compile(r'^(?:.{0,8}[，：])?([\u4e00-\u9fff]{2,6})者[，、]'
                     r'(.{4,80}?)(?:也|矣)[。；]?$')
    out, seen = [], set()
    for s in segs:
        for sent in sents_of(_blank(s['文本'])):
            m = pat.match(sent)
            if not m:
                continue
            w, d = m.group(1), m.group(2)
            if han(d) < 4 or w in seen:
                continue
            if w[0] in STOP_LEAD or w[-1] in STOP_TAIL or w in STOPWORD:
                continue
            if PRONOUN_LEAD.match(w):
                continue
            if flat.count(w) < 3:
                continue
            if w in d:
                continue
            seen.add(w)
            out.append((w, d, sent, s['id'], flat.count(w)))
    out.sort(key=lambda x: -x[4])
    rows = []
    for i, (w, d, sent, anc, n) in enumerate(out[:limit_n], 1):
        rows.append(_mk(code, i, '概念候选', '中', anc, sent,
                        {'词条': w, '定义': d, '全书频次': n},
                        ['白话定义', '要点', '易混淆'],
                        f'「X者Y也」定义句 + 全书出现 {n} 次'))
    return rows


def _rule_candidates(segs, code, min_strong=2, limit_n=None):
    """规则候选：强规范信号 ≥2 次的段。P1/P3 用。

    机器只能定位到「这段在讲该怎么做」，抽不出 if→then 的干净结构，
    更写不了「边界」——边界要求知道这条规则在什么前提下失效、用错会怎样，
    这是判断，不是抽取。因此 `待补` 里「边界」排第一位。
    """
    rows, seq = [], 0
    for s in segs:
        t = _blank(s['文本'])
        n = len(STRONG.findall(t))
        if n < min_strong:
            continue
        seq += 1
        rows.append(_mk(code, seq, '规则候选', '低', s['id'], t,
                        {'强规范信号数': n},
                        ['条件', '动作', '边界'],
                        f'强规范信号 {n} 次（不得/必须/切忌…）',
                        # ★ 这里**不能**传 requote=False。
                        # 原文就是整段逐字截取，回查得了。问题不是「查不到」，
                        # 而是「整段不能当一句引文用」——那是用途问题，
                        # 靠 `限制` 字段表达，不能拿回查标记去顶替。
                        # 曾经传 False，导致 563 条规则卡全被标成
                        # 可回查=false，而实测 514 条明明能逐字查到。
                        requote=True,
                        limit='原文是整段截取，可逐字回查；但段内含多个分句，'
                              '单独引用会断章取义，须连同上下文一起读'))
        if limit_n and seq >= limit_n:
            break
    return rows


def _enum_candidates(segs, code, limit_n=40):
    """枚举候选：「一曰X，二曰Y…」连续 ≥3 项。P1/P2/P8/P10 用。

    这是本模块**精度最高**的抽取器：形态完全确定，机器抽出来就是对的，
    不需要人再判断是不是概念。周礼一本能抽出 20+ 组完整名单。
    """
    flat = ''.join(f'{_blank(s["文本"])}\x00{s["id"]}' for s in segs)
    ex = re.compile(r'([一二三四五六七八九十]+)曰([^，。；、\x00]{1,12})[，、]')
    hits = list(ex.finditer(flat))
    groups, cur = [], []
    for h in hits:
        gap = h.start() - cur[-1].end() if cur else 999
        if cur and gap < 24:
            cur.append(h)
        else:
            if len(cur) >= 3:
                groups.append(cur)
            cur = [h]
    if len(cur) >= 3:
        groups.append(cur)

    rows = []
    for i, g in enumerate(groups[:limit_n], 1):
        items = [(a.group(1), _clean_name(a.group(2))) for a in g]
        start, end = g[0].start(), g[-1].end()
        quote = flat[start:end].replace('\x00', '')
        # 锚点：枚举串起点所在段。flat 里每段文本后跟一个 \x00ID，
        # 因此取「起点之前最后一个 \x00」后面那个 ID，就是起点所属的段。
        head = flat[:start]
        pos = head.rfind('\x00')
        anc = flat[pos + 1:].split('\x00')[0].strip() if pos >= 0 else '?'
        if anc not in {s['id'] for s in segs}:
            # 兜底：按第一项文字反查
            anc = next((s['id'] for s in segs
                        if _clean_name(items[0][1]) in _blank(s['文本'])), '?')
        rows.append(_mk(code, i, '枚举候选', '高', anc, quote,
                        {'名单': [{'序': a, '项': b} for a, b in items],
                         '项数': len(items)},
                        ['这组名单是什么的名单'],
                        f'「一曰…二曰…」连续 {len(items)} 项，形态确定'))
    return rows


def _terrain_candidates(segs, code, limit_n=120):
    """地形条目候选：《山海经》式「又东三百里，曰X之山」。P8 专用。

    这是「条目型」的核心资产：把叙述性文字转成可查的属性表
    （方位 + 距离 + 名称）。距离用中文数字解析成数值，
    解析失败就留原文串，不猜。
    """
    CN = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7,
          '八': 8, '九': 9, '十': 10}

    def cn2num(s):
        s = s.replace('里', '').strip()
        try:
            if '千' in s:
                a, _, b = s.partition('千')
                return (CN.get(a, 1) if a else 1) * 1000 + cn2num(b) if b else \
                       (CN.get(a, 1) if a else 1) * 1000
            if '百' in s:
                a, _, b = s.partition('百')
                v = (CN.get(a, 1) if a else 1) * 100
                if not b:
                    return v
                if '十' in b:
                    c, _, d = b.partition('十')
                    return v + (CN.get(c, 1) if c else 1) * 10 + CN.get(d, 0)
                return v + CN.get(b, 0)
            if '十' in s:
                a, _, b = s.partition('十')
                return (CN.get(a, 1) if a else 1) * 10 + CN.get(b, 0)
            return CN.get(s, 0)
        except Exception:
            return 0

    pat = re.compile(r'又([东南西北])([一二三四五六七八九十百千]+里)[，,]\s*'
                     r'曰([^，。]{1,16}?(?:之山|之山也|水|之木))')
    rows, seq = [], 0
    for s in segs:
        raw = s['文本']
        text = raw.replace('\n', '\x01')
        for m in pat.finditer(text):
            seq += 1
            d = m.group(1)
            dist_raw = m.group(2)
            nm = _clean_name(m.group(3)).replace('\x01', '')
            rows.append(_mk(code, seq, '条目候选', '高', s['id'],
                            _blank(m.group(0).replace('\x01', '')),
                            {'方位': d, '距离原文': dist_raw,
                             '距离里': cn2num(dist_raw), '名称': nm},
                            ['该条目下的物产/神异'],
                            '「又X若干里，曰X」地形句式，形态确定'))
            if seq >= limit_n:
                break
        if seq >= limit_n:
            break
    return rows


def _xunshi_candidates(segs, code, limit_n=None):
    """训释条候选：《尔雅》式「初，哉，首，基…始也。」。P8 专用。

    ## 为什么必须有
    P8 原来只配了「地形」（山海经式）与「枚举」，套到《尔雅》上只能出 1 张卡。
    但《尔雅》是词典，它的核心资产恰恰是**词条**：每条把一串同义词
    归到同一个训释字下。抽不出来不是书没内容，是抽取器只认地理体例。

    ## 体例（实测）
        「初，哉，首，基，肇，祖，元，胎，俶，落，權，輿，始也。」
    结构是：被训释词（多个，逗号分隔）+ 「X也。」收尾。
    被训释词 = 逗号前那一串；训释 = 「也」前那一字（或数字）。

    ## 边界（必须写明，否则会被误用）
    · 只认「短词连缀 + 以也收尾」这一种。尔雅另有大量「X謂之Y」式
      （如「山有穴為岫」），本抽取器不管，那是另一体裁。
    · 训释字取「也。」前最后一个字，这是尔雅的主流写法；
      但存在「…，始也」与「…，大也」这类单字训释，
      也有「…，言其大也」这类多字训释 —— 多字时整串保留，不截断。
    · **不做同义合并**。两个训释字相近（如「始也/初也」）是否该合并，
      属训诂判断，机器不做。
    """
    # 尔雅结构（实测）：「A，B，C…，X也。」——被训释词以逗号分隔，末尾单字训释。
    # 注意「釋詁初，哉，首」这种篇名粘在第一词前，是底本排印问题，
    # 所以首词只取「，」之后那段，避免把篇名带进词条。
    pat = re.compile(r'([^，。！？；\n]{1,8}(?:[，、][^，。！？；\n]{1,8})+)[，、]'
                     r'([^，。！？；\n]{1,8})也。')
    rows, seq = [], 0
    for s in segs:
        raw = s['文本']
        for m in pat.finditer(raw):
            words_raw, gloss = m.group(1), m.group(2).strip()
            words = [x.strip() for x in re.split(r'[，、]', words_raw) if x.strip()]
            if len(words) < 2 or not gloss:
                continue          # 至少 2 个被训释词，否则不是「同义词连缀」
            if len(gloss) > 8:
                continue          # 训释超 8 字基本是把上条正文吃进来了
            seq += 1
            rows.append(_mk(code, seq, '训释候选', '高', s['id'],
                            _blank(m.group(0)),
                            {'训释': gloss, '被训释词': words,
                             '词数': len(words)},
                            ['这组同义词彼此差在哪（训诂判断，机器不做）'],
                            '「A，B，C…，X也。」训释句式，形态确定；'
                            '同义是否该合并需人判断，本卡不合并'))
            if limit_n and seq >= limit_n:
                return rows
    return rows


def _poem_candidates(segs, code, limit_n=None):
    """诗/曲单元候选：从「标题 + 作者：X + 正文」切出单首作品。P7 专用。

    这是 P7 韵集型**唯一能自动出的真资产**。此前 P7 只配了引书与篇目，
    知识型产出为 0 —— 不是诗集没有知识单元，是没给它配抽取器。

    ## 核心难点：作者名与正文之间没有分隔符

    底本排印是「感遇（四首之一）作者：張九齡孤鴻海上來…」，
    「孤」是正文首字，却紧贴作者名。若按固定 3 字切，会切出「張九齡孤」；
    按姓氏表切，唐诗 289 处里能对 259 处（89.6%）—— 剩下的是姓氏表未收录
    的冷门诗人（邱為、綦毋潛、陳子昂、駱賓王、司空曙…）。

    ## 解法：用「诗句字数」反推作者名长度

    近体诗句长恒为 5 或 7 字（古体略宽，但绝大多数仍落在 4-9）。
    对候选切分长度 L∈{2,3} 分别试切，取「切完后按标点分句、句长落在 5 或 7
    的比例」最高者。实测唐诗三百首 289 处**全部可切**（平均分 0.85，最低 >0.5），
    不依赖姓氏表，因此对任何诗总集都适用。

    ## 边界

    - 只对带有「作者：」这类硬标记的底本有效。没有作者标记的诗集
      （如《元曲三百首》部分底本）切不出，会返回空——这是数据边界，不是缺陷。
    - 词（长短句）句长不固定，本判据会退化。词总集须另做判据。
    """
    flat = ''.join(f'{_blank(s["文本"])}\x00{s["id"]}' for s in segs)

    # 「标题作者：」是常见排印；标题取紧邻「作者：」之前的 2-20 个非标点字。
    # 注意：有的底本作「作者:」（半角），一并收。
    pat = re.compile(r'([\u4e00-\u9fff（）〈〉《》·、一二三四五六七八九十]{2,24}?)'
                     r'作者[:：]')

    def line_score(body):
        """切掉作者名后，正文按标点分句，句长落在 5 或 7 的比例。"""
        parts = [p for p in re.split(r'[，。；！？、,]', body[:160]) if p.strip()]
        if not parts:
            return -1.0
        return sum(1 for p in parts if len(p) in (5, 7)) / len(parts)

    rows = []
    for m in pat.finditer(flat):
        title = _clean_name(m.group(1))
        # 去掉标题里混入的上一个作品的尾巴：标题若超过 12 字，取最后一个
        # 以「）」「》」结尾的片段之后的部分（「唐詩三百首感遇（四首之一）」→「感遇（四首之一）」）
        if len(title) > 12:
            cut = max(title.rfind('）'), title.rfind('》'), title.rfind('」'))
            if cut >= 0:
                title = title[cut + 1:]
        if not title:
            continue
        best = None
        for L in (2, 3):
            nm = flat[m.end():m.end() + L]
            body = flat[m.end() + L:m.end() + L + 160]
            if not nm or '\x00' in nm:
                continue
            sc = line_score(body)
            if best is None or sc > best[0]:
                best = (sc, nm, L)
        if not best or best[0] < 0.5:
            continue
        sc, author, L = best
        # 正文取到下一个「作者：」之前，最多 400 字（避免跨首吞并）
        nxt = pat.search(flat, m.end())
        end = min(nxt.start() if nxt else len(flat), m.end() + L + 400)
        body = flat[m.end() + L:end]
        # 切掉尾部混入的下一首标题。
        # 底本排印：「…談笑無還期。臨洞庭上張丞相作者：孟浩然…」——
        # 下一首的标题紧贴在本首最后一个句号之后，没有分隔符。
        # 判据：句号之后那段**不含任何标点**且 ≤12 字，才是标题。
        # ⚠ 原来写成 `[^。！？]{1,12}$`，会把「興來美獨往，勝事空自知。行到水窮處…」
        #   这类整段后半吞掉——因为它匹配的是最后一个句号之后，而最后一句
        #   恰好很短。必须**从第一个句号开始逐句找**，遇到第一个「无标点短串」就切。
        # ⚠ 必须先剥掉 \x00段ID 再取正文。
        # segments 是一段一条，而**一首诗可能跨两段**——底本按页/按栏切，
        # 「終南別業」前四句在 P04、后四句在 P05，中间夹着 \x00B15-14-P04。
        # 若先 split('\x00')[0]，后半首诗会被整段丢掉，
        # 只留下「中歲頗好道，晚家南山陲。」（实测 278 首里有大量此类）。
        # ⚠ 剥 \x00段ID 时**不能用 \w** —— Python 的 \w 默认匹配 Unicode 汉字，
        # 于是 `\x00[\w\-]+` 会把「\x00B15-14-P04興來美獨往」整串吃掉，
        # 半句诗直接消失（表现为「…南山陲。，勝事空自知。」双标点 + 丢句）。
        # 必须用显式的 [A-Za-z0-9\-]，因为段ID只由这两类组成。
        body = re.sub(r'\x00[A-Za-z0-9\-]+', '', body)
        body = body.replace('\x00', '').strip()
        m2 = re.match(r'^([\s\S]*?[。！？])([^。！？，、；：\s]{1,12})$', body)
        if m2:
            body = m2.group(1)
        if len(body) < 8:
            continue
        # 锚点：起点所在段
        head = flat[:m.start()]
        pos = head.rfind('\x00')
        anc = flat[pos + 1:].split('\x00')[0].strip() if pos >= 0 else '?'
        if anc not in {s['id'] for s in segs}:
            anc = next((s['id'] for s in segs if title and title in _blank(s['文本'])), '?')
        rows.append(_mk(code, len(rows) + 1, '作品候选', '高', anc,
                        # 「原文」必须是**单段之内**的连续文字，否则跨段回查必失败。
                        # 全诗可能跨段（见上），所以原文只取首联，完整正文放字段里。
                        # 这里不为了「看起来完整」把拼接后的全诗当原文——
                        # 那会让可回查校验通过而实际是拼接产物，比失败更糟。
                        _first_line(body),
                        {'标题': title, '作者': author, '正文': body,
                         '行数': len([x for x in re.split(r'[，。；！？]', body) if x.strip()]),
                         '句长吻合': round(sc, 2), '体裁': '诗'},
                        ['这一首写了什么（一句话）', '名句是哪一句'],
                        f'「标题+作者：+正文」三段式，按诗句字数（5/7）反推作者名切成，'
                        f'句长吻合度 {sc:.2f}'))
        if limit_n and len(rows) >= limit_n:
            break
    return rows


def _gloss_candidates(segs, code, limit_n=None):
    """释义对候选：类书的「X，曰Y」「X谓之Y」「X曰Y」。P7 类书分支专用。

    幼学琼林这类蒙学类书的知识单元是「词条 → 释义」，
    不是诗，也不是论说。此前它与诗总集一起被判成 P7，只配了引书篇目，
    于是知识型产出为 0。

    形态：「望人包容，曰海涵」「無系累者，曰江湖散人」「饋物致敬，曰敢效獻曝之忱」。
    四道过滤（沿用 `_def_candidates` 的教训）：
      1. 词条首尾不得是虚词、指代（此/其/是/若/夫…）
      2. 释义不得含词条自身（自指定义）
      3. 词条 2-8 字、释义 2-14 字
      4. 词条在全书出现 ≥2 次（只出现一次的多半是行文碎片）
    """
    VAGUE = set('此其是若夫蓋盖故然則则而也矣乎哉之其以於于与與所求')
    flat_pairs = []
    for s in segs:
        t = _blank(s['文本'])
        for m in re.finditer(r'([\u4e00-\u9fff]{2,8})[，,](?:曰|謂之|谓之|稱為|称为)'
                             r'([\u4e00-\u9fff]{1,14})', t):
            flat_pairs.append((m.group(1), m.group(2), s['id'], m.group(0)))

    rows, seen = [], set()
    for a, b, anc, quote in flat_pairs:
        if a in seen:
            continue
        if a[0] in VAGUE or a[-1] in VAGUE:
            continue
        if a in b or len(a) < 2 or not b:
            continue
        # ⚠ 这里**不能**用「全书频次 ≥2」过滤。
        # 那条规则来自 `_def_candidates`（论说书里「X者Y也」只出现一次多半是
        # 行文举例），照搬到类书是灾难：**类书本身就是词典，每个词条天然只出现一次**。
        # 实测幼学琼林 220 条释义对全部频次=1，加上这条过滤后归零。
        # 类书的正确过滤器是「同段内是否还有别的释义对」——词典条目成串出现。
        seen.add(a)
        rows.append(_mk(code, len(rows) + 1, '释义候选', '高', anc, quote,
                        {'词条': a, '释义': b},
                        ['这条释义今天怎么讲'],
                        '「X，曰Y」释义句式（类书条目，天然每条只出现一次）'))
        if limit_n and len(rows) >= limit_n:
            break
    return rows


def _quote_candidates(segs, code, limit_n=None):
    """引书候选：《X》在正文里被引用的位置。P6 散文型/P10 笔记用。

    这是「引书谱」的原料——一本书在跟哪些书对话。
    有偏斜（古典书引得多、现代小说几乎不引），横向比书会错判。

    ⚠ 这里**不能设条数上限**。原来写死 limit_n=40，结果全库
    十几本书的引书候选都恰好是 40 条 —— 那个数字是截断的产物，
    不是实测。实测红楼梦引用 159 种书、朝花夕拾 199 种，
    取前 40 等于丢掉四分之三，而「引书谱」的价值恰恰在全量分布上。
    截断唯一该用的地方是「全书只提过一次」的偶然提及，用 n≥2 挡掉。
    """
    from library import book_name_signals, name_evidence_segment

    # 自指不算引用：B58《小王子》9 条引书里第 1 条是它自己，B60 13 条里也有 1 条是本书名
    book_title = (segs[0].get('书') if segs else '') or ''
    cnt, first, direct = Counter(), {}, {}
    for s in segs:
        for w in re.findall(r'《[^》]{1,24}》', _blank(s['文本'])):
            if book_title and (book_title in w or w.strip('《》') in book_title):
                continue
            cnt[w] += 1
            first.setdefault(w, s['id'])
        if not name_evidence_segment(s):
            continue
        for name, quote, signal in book_name_signals(s['文本']):
            if signal == 'citation' and name not in book_title:
                w = '《' + name + '》'
                direct.setdefault(w, (s['id'], quote))
                cnt[w] += 1
    rows = []
    for w, n in cnt.most_common():
        if n < 2 and w not in direct:    # 明确写出引用出处时，一处即足以进索引
            continue
        anchor, quote = direct[w] if w in direct else (first[w], w)
        rows.append(_mk(code, len(rows) + 1, '引书候选', '高', anchor, quote,
                        {'书名': w, '引用次数': n},
                        ['引用它做什么（支持/反驳/举例）'],
                        '原文明确写出引用的名称' if w in direct else f'全书出现 {n} 次'))
        if limit_n and len(rows) >= limit_n:
            break
    return rows


def _qupai_candidates(segs, code, limit_n=60):
    """曲牌 / 科介候选。P5 戏曲型专用。

    实测两种底本写法完全不同，必须都认：
      牡丹亭（【曲牌】+ [泪介] 方括号）
      西厢记（半角 [末雲] [紅唱] [下] [末上雲]，无【】）
    只写【】会把西厢记抽成 0 条 —— 那是漏，不是这本书没有。
    """
    q, qf = Counter(), {}
    k, kf = Counter(), {}
    qsurf, ksurf = {}, {}          # 记录底本实际用的括号形态，引文必须照抄
    for s in segs:
        t = _blank(s['文本'])
        for m in re.finditer(r'【([^】]{1,10})】', t):
            w = m.group(1)
            q[w] += 1
            qf.setdefault(w, s['id'])
            qsurf.setdefault(w, m.group(0))
        for m in re.finditer(r'\[([^\]\n]{1,14})\]', t):
            w = m.group(1)
            if re.search(r'介$|科$|下$|上$|雲$|云$|唱$|白$|見$|见$', w):
                k[w] += 1
                kf.setdefault(w, s['id'])
                ksurf.setdefault(w, m.group(0))
            elif re.match(r'^[一二三四五六七八九十]?\S{1,6}(?:牌|調|调|腔)$', w):
                q[w] += 1
                qf.setdefault(w, s['id'])
                qsurf.setdefault(w, m.group(0))
    rows = []
    for i, (w, n) in enumerate(q.most_common(limit_n), 1):
        rows.append(_mk(code, i, '曲牌候选', '高', qf[w], qsurf.get(w, f'【{w}】'),
                        {'曲牌': w, '出现次数': n},
                        ['所属宫调', '句式格律'],
                        f'全书出现 {n} 次'))
    for i, (w, n) in enumerate(k.most_common(limit_n), len(rows) + 1):
        # 舞台指示的原文按底本原样写，不强行套［］——
        # 西厢记底本用 [末雲]，写成［末雲］就是改了底本。
        rows.append(_mk(code, i, '科介候选', '高', kf[w], ksurf.get(w, f'[{w}]'),
                        {'科介': w, '出现次数': n},
                        ['表演动作释义'],
                        f'全书出现 {n} 次'))
    return rows


def _fan_candidates(segs, code, limit_n=60):
    """「凡」式条目候选：P2 知识型（技术专著）专用。

    走过的弯路（勿再试）：拿 2-4 字高频词当术语。
    结果抽出「这个」（52 次）、「徽因」（70 次）、「中国建」（74 次）——
    这不是术语，是高频词的左右邻字碎片。
    记忆里记过的「左右邻字熵抽词」同理：选出的全是虚词，
    因为虚词的左右邻字分布最自由。

    改为抽「凡…」开头的断定句。这是技术专著的真实骨架：
    《天工开物》348 条「凡稻種最多。」「凡秧田一畝所生秧，供移栽二十五畝。」
    一条就是一条可操作的工艺参数，形态确定、不需要判断。
    """
    pat = re.compile(r'凡[^。\n]{2,30}[。：]')
    # 「凡此」「凡是」「凡有」打头的都是连词性用法，不是工艺条目。
    # 实测：建筑卷 40 条候选里 6 条抽样全是这种（凡此种种/凡是有水的地方），
    # 天工开物的真条目没有一条这样开头。这一条过滤是必须的。
    BAD_LEAD = re.compile(r'^(?:凡此|凡是|凡有|凡在|凡属|凡其|凡所|凡与|凡如|凡若)')
    cnt, first = Counter(), {}
    for s in segs:
        if s['篇序'] == 0:
            continue
        for m in pat.finditer(_blank(s['文本'])):
            w = m.group(0)
            if BAD_LEAD.match(w):
                continue
            cnt[w] += 1
            first.setdefault(w, s['id'])
    rows = []
    for w, n in cnt.most_common(limit_n * 2):
        if len(rows) >= limit_n:
            break
        # 太短的「凡禽獸骨。」没有信息量
        if han(w) < 6:
            continue
        rows.append(_mk(code, len(rows) + 1, '凡式候选', '高', first[w], w,
                        {'工艺条目': w.rstrip('。：')},
                        ['属于哪道工序', '关键参数'],
                        f'「凡…」断定句，全书出现 {n} 次'))
    return rows


def _entry_candidates(segs, code, limit_n=100):
    """条目候选：P10 笔记志书专用。

    「笔记志书」的真正资产不是概念，是**条目**——一条一物/一地/一事。
    实测这类书的条目形态是「短行标题 + 长段正文」：
      东京梦华录  第一卷 / 東都外城 / 舊京城 / 河道
      陶庵梦忆    鐘　山 / 報　恩　塔 / 天台牡丹
      梦溪笔谈    【卷一  故事一】

    只抽「定义句」会得到 0 条（这类书不写「X者Y也」），
    只抽「引书」会退化成引书谱。必须单独抽条目。

    关键约束：条目的「原文」取**正文首句**，不取篇名。
    篇名是结构标签，不是句子；把篇名当「原文」写进卡，
    回查校验会失败（篇名常被 structure 去掉标点单独成行），
    而且它也不是可引用的原文。
    """
    rows, seen = [], set()
    for s in segs:
        if s['篇序'] == 0:
            continue
        key = s['id']
        if key in seen:
            continue
        seen.add(key)
        body = _blank(s['文本'])
        nm = re.sub(r'^第[一二三四五六七八九十百千]+[卷章节][\s\u3000]*', '', s['篇']).strip()
        # 条目标题在底本里的两种真实形态（实测东京梦华录、陶庵梦忆、梦溪笔谈）：
        #   ① 标题重复：「東都外城東都外城，方圓四十餘里」——标题与正文首句连写，
        #      排印时标题重复了一次。全书 90 段里有 40+ 段是这种。
        #   ② 标题带冒号/空格：「外諸司外諸司：左右金吾街仗司…」
        # 不剥掉的后果有两层：
        #   - 条目名取不到（篇名只有「第一卷」这种卷次，不是条目名）
        #   - 「原文」里混进标题，「可回查」校验能过，但人看到的是拼接产物，
        #     不是原书的句子 —— 这比校验失败更糟，因为它不报错。
        m_dup = re.match(r'^([\u4e00-\u9fff]{2,10})\1', body)
        if m_dup:
            nm = m_dup.group(1)
            body = body[len(nm):]
        else:
            # 形态②：行首 2~10 字 + 冒号，且该词在全段里只出现这一次
            m_col = re.match(r'^([\u4e00-\u9fff]{2,10})[：:]\s*', body)
            if m_col and body.count(m_col.group(1)) == 1:
                nm, body = m_col.group(1), body[m_col.end():]
            # 形态③「标题不加任何标记、直接接正文」（「御街坊巷御街，自宣德樓…」）
            # **刻意不做**。试过两种判法：
            #   ① 首句前两段（标题+正文起句）共享 2~3 字核心词 ——
            #      把「東角樓街巷」切成「街巷」，标题取成「東角樓」；
            #      把「大內前州橋之東，臨汴河大街」切成「東街巷」；
            #   ② 首句第一个逗号前全取 —— 把「民俗凡百所賣飲食之人」整句当标题。
            # 剥错比不剥更糟：错标题会让读者按错的关键词检索，
            # 而且在页面上看不出错。这类条目一律标「非首段」跳过。
            elif s['段'] != 1:
                continue
            else:
                nm = s['篇']
        if han(body) < 12:
            continue
        # 校注文字不是条目：「宣德注：「德」誤刻「和」。」整段是一条校记。
        # 这类段落如果当条目入卡，书名下会出现一堆「宣德注」这种条目名。
        if re.match(r'^配?注$|注$|校$|案$|按$', nm) and '誤' in body[:20] \
                or body.startswith('「') or '誤刻' in body[:20] or '當作' in body[:20]:
            continue
        # 卷次级的段落（篇名本身就是「第二卷」）不是条目，
        # 条目名不能填成「第二卷」—— 那是结构标签，不是条目。
        if re.fullmatch(r'第[一二三四五六七八九十百千\d]+[卷章节]', nm):
            continue
        # 原文取首句（到第一个句末标点），这是真能回查的文字
        first = sents_of(body)
        quote = first[0] if first else body[:60]
        if han(quote) < 6:
            # 首句太短（多半是残留的标题行），取下一句
            quote = ''.join(first[:2])[:120] if first else body[:120]
        rows.append(_mk(code, len(rows) + 1, '条目候选', '高',
                        s['id'], quote,
                        {'条目名': nm, '所属卷': s['篇'], '字数': s['字数']},
                        ['本条讲什么（一句话）'],
                        '条目首段（标题已剥离）'))
        if len(rows) >= limit_n:
            break
    return rows


def _place_candidates(segs, code, limit_n=60):
    """名物/处所候选：P10 用。带「XX院/寺/桥/门/楼」形态的专名。

    走过且失败的路（勿再试）：只按后缀抽。初版用
    `[\\u4e00-\\u9fff]{2,4}(?:山|水|门|寺…)` 直接抽，抽样 10 条里 7 条是
    「其處山」「又逾嶺」「入東門」「蓋此山」—— 这是把动词短语和指示词
    连着后缀一起切了。这和记忆里记过的「左右邻字熵抽词」是同一个坑：
    只看形态不看词性，抽出来的必然是虚词碎片。

    改为三重约束，宁可少抽：
      1. 不以虚词/动词/方位词打头（其/又/盖/入/越/而/此/是…）
      2. 不以方位词收尾（上/下/内/外/东/西/南/北/前/后）
      3. 全书出现 ≥4 次（专名会反复出现，偶发短语不会）
    """
    SUF = '院|寺|桥|橋|门|門|楼|樓|阁|閣|亭|台|臺|塔|观|觀|宫|宮|殿|园|園|街|巷|坊|仓|倉'
    pat = re.compile(r'([\u4e00-\u9fff]{2,4}(?:' + SUF + r'))')
    # 实测剩下的噪声全是以动词/介词打头的动宾短语：
    # 「由洞門」「渡石橋」「有小橋」「有亭橋」——后缀对，但整串不是名字。
    BAD_LEAD = re.compile(r'^(?:其|又|盖|蓋|入|越|逾|而|此|是|乃|则|則|故|凡|自|'
                          r'从|從|至|过|過|上|下|东|東|西|南|北|前|后|後|'
                          r'由|渡|有|無|无|見|见|望|抵|經|经|出|进|進|'
                          r'一|二|三|四|五|六|七|八|九|十|半|数|數)')
    BAD_TAIL = re.compile(r'[上下内外東西南北前后後中]')
    # 地名语境：前面有「在/至/入/到/于/距/自/从/过/经」，或后面跟「之/以/内/外/东南西北中」
    CTX = re.compile(r'(?:在|至|入|到|于|於|距|自|從|从|過|过|經|经|望|抵|臨|临)\s*$')
    CTX_TAIL = re.compile(r'^(?:之|以|內|内|外|東|东|西|南|北|中)')
    cnt, first = Counter(), {}
    for s in segs:
        txt = _blank(s['文本'])
        for m in pat.finditer(txt):
            w = m.group(1)
            if BAD_LEAD.match(w) or BAD_TAIL.search(w[-1]):
                continue
            pre = txt[:m.start()][-2:]
            post = txt[m.end():m.end() + 1]
            if not (CTX.search(pre) or CTX_TAIL.match(post)):
                continue
            cnt[w] += 1
            first.setdefault(w, s['id'])
    rows = []
    for w, n in cnt.most_common(limit_n * 4):
        if len(rows) >= limit_n:
            break
        if n < 4:
            continue
        rows.append(_mk(code, len(rows) + 1, '名物候选', '中', first[w], w,
                        {'名称': w, '出现次数': n},
                        ['它是什么、在哪'],
                        f'全书出现 {n} 次'))
    return rows


def _chapter_candidates(segs, code, limit_n=None):
    """篇目候选：篇名 + 该篇首段的**第一句**（不是整段）。

    为什么只要第一句：整段首段动辄 200-300 字，塞进「原文」字段里
    回查虽然过得去，但作为「篇目索引」的一行太长，页面上一屏放不下三条。
    第一句足够定位，短且必然是正文。

    要注意这里产出的是**结构索引**，不是知识卡。它回答「这本书有哪些篇」，
    不回答「这一篇讲什么」——后者要人读完才能写，`待补` 里已标出。
    """
    rows = []
    for s in segs:
        if s['篇序'] == 0 or s['段'] != 1:
            continue
        body = _blank(s['文本'])
        ss = sents_of(body)
        quote = ss[0] if ss else body[:60]
        if han(quote) < 8 and len(ss) > 1:
            quote = (ss[0] + ss[1])[:120]
        rows.append(_mk(code, len(rows) + 1, '篇目候选', '高', s['id'],
                        quote,
                        {'篇名': s['篇'], '篇序': s['篇序'],
                         '字数': s['字数'], '段数': None},
                        ['本篇主旨一句话'],
                        '篇首段首句，可作篇目索引'))
        if limit_n and len(rows) >= limit_n:
            break
    return rows


EVENT_VERB = re.compile(
    r'(逢|遇|戰|战|殺|杀|取|奪|夺|救|嫁|亡|走|歸|归|入|出|見|见|說|说|騙|骗|偷|斬|斩|燒|烧|'
    r'破|降|封|貶|贬|逐|娶|訪|访|拜|刺|劫|會|会|聚|散|逃|追|擒|捉|打|鬥|斗|爭|争|讓|让|'
    r'請|请|求|告|訴|诉|問|问|答|罵|骂|笑|哭|死|生|病|醫|医|葬|祭|修|建|造|毀|毁|焚|沉|'
    r'溺|墜|坠|落|升|遷|迁|謫|谪|革|復|复|任|辭|辞|隱|隐|還|还|赴|奔|襲|袭|伏|誘|诱|'
    r'誤|误|認|认|記|记|題|题|賦|赋|吟|詠|咏|宴|飲|饮|醉|別|送|迎|寄|贈|赠|和|答)')


def _is_event_title(title):
    """回目是不是「事件」，还是只是一个主题词/标签。

    实测：B60「第一章 勤政爱民」、B59「国之脊梁——中国院士的科学人生百年」都被当成情节，
    但它们是标签不是事件。判据：对句（≥2 段且每段 ≥4 字）或含明确动作词。
    """
    body = re.sub(r'^第[一二三四五六七八九十百零〇0-9]{1,4}[回章卷篇部节][：:、\s]*', '', title or '')
    parts = [p for p in re.split(r'[\u3000\t ，,、；;]+', body) if han(p) >= 2]
    if len(parts) >= 2:
        # 对句：每一段都要有动作词，否则只是「第一章 勤政爱民」这种标签
        return all(han(p) >= 4 and EVENT_VERB.search(p) for p in parts)
    # 单句标题（「史記秦始皇本紀」「感遇四首之一」「〔双调〕骤雨打新荷」）不认作事件：
    # 它们分别是卷名、诗题、曲牌，不是「谁做了什么」。宁可漏，不可错。
    return False


def _plot_candidates(segs, code, limit_n=200):
    """情节候选：P4 叙事型唯一能自动出的真资产。

    来源不是正文理解，而是**作者自己写的回目**。
    回目是对句，前半句与后半句各是一个事件：
      「甄士隱夢幻識通靈　賈雨村風塵怀閨秀」→ 事件1 通灵 / 事件2 闺秀
      「薄命女偏逢薄命郎　葫蘆僧亂判葫蘆案」→ 事件1 偏逢 / 事件2 乱判
    这不是「读懂了小说」，而是把作者已经压缩好的摘要拆开、配上来回人物，
    串成可点的情节链。它能回答「这本书讲了哪些事」，回答不了「为什么」。

    刻意不做的事：不从正文抽「谁做了什么」。
    实测正文里「却说…」「只见…」抽出来的全是场景描写，不是事件；
    要真做情节抽取必须上模型逐段理解，那是另一个量级的工作。

    可回查性：原文用回目原文（能逐字在 segments 的篇名里查到），
    不用正文句子——回目本身不在正文段落里，只在「篇」字段上。
    """
    rows = []
    for s in segs:
        if s['篇序'] == 0 or s['段'] != 1:
            continue
        title = s['篇']
        if not _is_event_title(title):
            continue
        # 拆回目：按全角空格/制表符切两半。
        # 三国的回目用中文逗号分隔（「宴桃園豪傑三結義，斬黃巾英雄首立功」），
        # 而不是空格 —— 只按空格切会得到 1 个事件，把对句当成一句话。
        # 两种分隔都试，取切得更多的那种。
        parts = [p for p in re.split(r'[\u3000\t ]+', title) if p]
        if len(parts) < 2:
            parts = [p for p in re.split(r'[，,]', title) if p]
        # 去掉「第X回」这类前缀
        parts = [re.sub(r'^第[一二三四五六七八九十百零〇0-9]{1,4}[回章卷篇部节][：:]?', '', p)
                 for p in parts]
        parts = [p.strip('　 ') for p in parts if han(p.strip('　 ')) >= 2]
        if not parts:
            continue
        # 该回体量：用段数与字数量化，比「重要程度」这种主观词可靠
        same = [x for x in segs if x['篇序'] == s['篇序']]
        rows.append(_mk(code, len(rows) + 1, '情节候选', '中', s['id'],
                        title,
                        {'回目': title,
                         '事件': parts,
                         '字数': sum(x['字数'] for x in same),
                         '段数': len(same)},
                        ['这一回的实际因果链（需人读）',
                         '事件里谁是主动方'],
                        '取自作者自写的回目，不是正文理解',
                        verify_mode='title'))
        if len(rows) >= limit_n:
            break
    return rows


# 原型 → 抽取器组合。这张表就是「每一类图书到底能给到什么结果」的实现。
#
# 注意分级：抽取器本身有精度差异，标在 CONFIRM 里。
#   '高'  形态确定，机器抽出来基本可直接用（枚举/曲牌/科介/条目/引书）
#   '中'  需要人扫一遍筛（概念/名物/凡式/情节）
#   '低'  只是定位器，不是资产（规则：只知道这段在讲该怎么做）
# 页面与 skill 必须按这个分级说话，不许把「低」当成「有了」。
# ============================================================
# P11 图鉴型：条目 → 物种卡
# ============================================================
# 图鉴的一条正文 = 一个物种条目，条内按排印字段标签切成「生境/分布/采制…」。
# 抽取不靠句子形态，靠版面：条目边界是每个「来 源」，字段边界是标签。
# 因此这里不读 segs 的文本结构，只用 segs 把条目落回锚点（原文可回查）。

def _atlas_candidates(segs, code, entries=None):
    """entries 由 atlas.py 从版面抽出；没有版面时返回空（不硬造卡）。"""
    if not entries:
        return []
    idx = [(s['id'], _blank(s.get('文本') or '')) for s in segs]
    rows = []
    for e in entries:
        quote = (e.get('text') or '').strip()
        if not quote:
            continue
        head = _blank(quote)[:40]
        anchor = ''
        for sid, body in idx:
            if head and head in body:
                anchor = sid
                break
        if not anchor:
            # 条目跨段时，用「来源」句的前 30 字再找一次
            head2 = _blank(e.get('fields', {}).get('来源', ''))[:30]
            for sid, body in idx:
                if head2 and head2 in body:
                    anchor = sid
                    break
        fields = {}
        for k, v in (('中名', e.get('cname')), ('学名', e.get('latin')),
                     ('科名', e.get('family')), ('药用部位', e.get('part')),
                     ('药材名', e.get('drug_name'))):
            if v:
                fields[k] = v
        for k, v in (e.get('fields') or {}).items():
            if str(v or '').strip():
                fields[k] = v
        rows.append(_mk(
            code, 0, '物种条目', '高', anchor, quote, dict(fields),
            ['图注/图片对位', '学名与别名抽检'],
            f'第{e.get("page") or 0}页；以「来源」切条，{e.get("field_count") or 0} 个字段',
            requote=bool(anchor), verify_mode='atlas'))
    return rows


# ============================================================
# P12 纪事型：资料框 → 人物条目
# ============================================================
# 人物故事集的结构化数据不在正文里，在每篇开头的资料框：
# 姓名 / 生卒年 / 籍贯 / 身份 / 主要成就 / 院士语录。
# 这里只负责把 story.py 抽好的人物落成卡片（原文逐字回查）。

def _person_candidates(segs, code, people=None):
    if not people:
        return []
    idx = [(s['id'], s['文本'] or '', _blank(s['文本'] or ''), s.get('篇') or '')
           for s in segs]
    rows = []
    for p in people:
        name = (p.get('name') or '').strip()
        if not name:
            continue
        key = _blank('姓名：' + name)
        anchor, quote = '', ''
        for sid, raw, body, pian in idx:
            if key in body:
                anchor = sid
                quote = '姓名：' + name
                break
        if not anchor:
            # 篇界正好切在「姓名：」这一行时，这一行会被当成篇名从正文里摘掉。
            # 退回到以这个人为篇名的那一段（篇名本身就是人名）。
            for sid, raw, body, pian in idx:
                if pian == name:
                    anchor = sid
                    quote = (raw or '').strip()[:160]
                    break
        if not anchor:
            continue
        fields = {'姓名': name}
        for k in ('生卒年', '籍贯', '身份', '主要成就', '院士语录', '毕业院校'):
            v = (p.get('fields') or {}).get(k)
            if v:
                fields[k] = v
        rows.append(_mk(
            code, 0, '人物条目', '高', anchor, quote.strip(), fields,
            ['生平时间线', '照片 / 图注'],
            '第%s页资料框；%d 个字段' % (p.get('page') or 0, len(fields)),
            requote=True))
    return rows


DEFAULT_PLAN = {
    'P1': [('定义', _def_candidates), ('枚举', _enum_candidates),
           ('规则', _rule_candidates)],
    'P2': [('凡式', _fan_candidates), ('定义', _def_candidates),
           ('枚举', _enum_candidates)],
    'P3': [('规则', _rule_candidates), ('定义', _def_candidates)],
    # P4 加情节：这是叙事型唯一能自动出的真资产。
    # 回目本身就是作者写的事件摘要（「甄士隱夢幻識通靈　賈雨村風塵怀閨秀」），
    # 拆成两句就是两个事件节点，串起来就是情节链。
    # 这比「篇目索引」高一个层级：篇目只说「有这一回」，情节说「这一回发生了什么」。
    'P4': [('情节', _plot_candidates), ('篇目', _chapter_candidates),
           ('引书', _quote_candidates)],
    'P5': [('曲牌科介', _qupai_candidates), ('篇目', _chapter_candidates)],
    'P6': [('引书', _quote_candidates), ('篇目', _chapter_candidates)],
    # P7 原来只有引书 + 篇目，于是 5 本书 367 条卡全是元数据，知识型产出 = 0。
    # 实测这 5 本根本不是一类（见产出规格文档）：
    #   唐诗三百首  诗总集   → 作品候选（作者：标记，289 处可切）
    #   元曲三百首  散曲集   → 作品候选（缺作者标记，切不出，如实返回空）
    #   人间词话    词话     → 概念候选
    #   小窗幽记    清言集   → 概念候选
    #   幼学琼林    蒙学类书 → 释义候选（「X，曰Y」148 条）
    # 三类抽取器都挂上，由各自的形态判据决定谁出得来，不出就返回空。
    'P7': [('作品', _poem_candidates), ('释义', _gloss_candidates),
           ('定义', _def_candidates), ('引书', _quote_candidates),
           ('篇目', _chapter_candidates)],
    # P8 条目型有两种体例，抽取器必须分开配：
    #   · 山海经式地理条目（又X里，曰X之山）→ 地形
    #   · 尔雅式训释条目（A，B，C…，X也）  → 训释
    # 2026-11-08 前只配了地形，导致《尔雅》判对类型后仍只出 1 张卡。
    'P8': [('训释', _xunshi_candidates), ('地形', _terrain_candidates),
           ('枚举', _enum_candidates)],
    'P9': [('篇目', _chapter_candidates), ('引书', _quote_candidates)],
    # 2026-11-16：「名物」下线。它按建筑后缀抓词，金瓶梅里把人名「西門」当地点，
    # 抽出来是「這西門 / 走出門」。五类专名（地名/机构/器物/动物/植物）改由 entities.py
    # 统一抽，全类型共用，不再按书型单列。
    'P10': [('条目', _entry_candidates), ('定义', _def_candidates),
            ('引书', _quote_candidates)],
    # P11 图鉴：条目由版面层切（atlas.py），不走句子形态抽取器。
    'P11': [('物种条目', _atlas_candidates)],
    # P12 纪事型：人物资料框 + 篇目 + 引书
    'P12': [('人物', _person_candidates), ('篇目', _chapter_candidates),
            ('引书', _quote_candidates)],
}

# 每种候选的精度分级与「算不算资产」的判定。
# 这张表是给人和页面看的，不是给程序用的——程序不做这个判断。
CONFIRM = {
    '枚举候选': ('中', '需人筛', '可查看原文中的列举，核对各项是否属于同一组'),
    '曲牌候选': ('中', '需人筛', '请核对曲牌和所在章节'),
    '科介候选': ('中', '需人筛', '请核对舞台提示和所在章节'),
    '条目候选': ('中', '需人筛', '请核对条目名称和正文范围'),
    '地形候选': ('中', '需人筛', '请核对原文中的地点、方向和距离'),
    '训释候选': ('中', '需人筛', '根据原文中的训释格式整理，请核对词义'),
    '引书候选': ('中', '需人筛', '从正文的书名号内提取，请核对是否为书目引用'),
    '作品候选': ('中', '需人筛', '根据篇名、作者和正文整理，请核对作品范围'),
    '释义候选': ('中', '需人筛', '根据原书的释义句整理，请核对词条和解释'),
    '情节候选': ('中', '需人筛', '根据回目整理，请核对事件与正文是否相符'),
    '凡式候选': ('中', '需人筛', '请核对原文中的规定及其适用范围'),
    '概念候选': ('中', '需人筛', '根据原书的定义句整理，请核对词条和解释'),
    '名物候选': ('中', '需人筛', '请回原文核对名称和所指对象'),
    '篇目候选': ('高', '仅为定位器', '点开查看这篇的开头'),
    '规则候选': ('低', '仅为定位器', '可查看讲解做法的原文，请核对适用条件'),
    '人物条目': ('高', '可直接用', '按书中人物资料框整理，空缺字段保留为空'),
    '物种条目': ('高', '可直接用', '按书中的物种条目整理，请核对名称和各字段的归属'),
}

CARD_KINDS = {
    '定义': ('概念候选',), '枚举': ('枚举候选',), '规则': ('规则候选',),
    '凡式': ('凡式候选',), '情节': ('情节候选',), '篇目': ('篇目候选',),
    '引书': ('引书候选',), '曲牌科介': ('曲牌候选', '科介候选'), '作品': ('作品候选',),
    '释义': ('释义候选',), '训释': ('训释候选',), '地形': ('地形候选', '条目候选'),
    '条目': ('条目候选',), '物种条目': ('物种条目',), '人物': ('人物条目',),
}

# Wording and relationships may still need editorial review even when the passage is exact.
REVIEW_CONTENT = {'定义', '枚举', '规则', '凡式', '引书', '曲牌科介', '作品',
                  '释义', '训释', '地形', '条目', '情节'}

# ── 能力配置：后台可改「每类书启用哪些抽取器」 ──────────────────
# 默认值仍是上面这张 DEFAULT_PLAN；config/capabilities.json 只做覆盖。
# 为什么放在文件里：改能力不该改代码；引擎每次新起进程都会重新读。
# 覆盖规则：某原型缺键 → 用默认；显式给 [] → 该原型一张卡也不抽。
ALL_LABELS = []
_EXTRACTORS = {}
for _items in DEFAULT_PLAN.values():
    for _label, _fn in _items:
        if _label not in _EXTRACTORS:
            ALL_LABELS.append(_label)
        _EXTRACTORS[_label] = _fn

CAP_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'config', 'capabilities.json')


def load_plan(path=None):
    cfg = {}
    try:
        with io.open(path or CAP_CONFIG, encoding='utf-8') as fp:
            cfg = json.load(fp)
    except Exception:
        cfg = {}
    plan_cfg = cfg.get('plan') if isinstance(cfg, dict) else None
    out = {}
    for proto, defaults in DEFAULT_PLAN.items():
        default_labels = [l for l, _ in defaults]
        labels = plan_cfg.get(proto) if isinstance(plan_cfg, dict) else None
        if labels is None:
            labels = default_labels
        if not isinstance(labels, list):
            labels = default_labels
        seen, clean = set(), []
        for label in labels:
            if isinstance(label, str) and label in _EXTRACTORS and label not in seen:
                seen.add(label)
                clean.append(label)
        out[proto] = [(label, _EXTRACTORS[label]) for label in clean]
    return out


PLAN = load_plan()


def enabled_labels(path=None):
    """Use global settings first; older profiles can still disable a rule everywhere."""
    path = path or CAP_CONFIG
    try:
        with io.open(path, encoding='utf-8') as fp:
            cfg = json.load(fp)
    except (OSError, ValueError):
        cfg = {}
    labels = cfg.get('content_labels') if isinstance(cfg, dict) else None
    if isinstance(labels, list):
        return set(ALL_LABELS).intersection(x for x in labels if isinstance(x, str))
    return {label for entries in load_plan(path).values() for label, _ in entries}


def card_fingerprint(row):
    """内容身份不依赖列表序号或段落编号；正文、类型或实质字段变化产生新身份。"""
    fields = {k: v for k, v in (row.get('字段') or {}).items() if k not in ('篇序',)}
    value = {'type': row.get('类型'), 'quote': _blank(row.get('原文') or ''), 'fields': fields}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def _identity_state(code):
    folder = os.path.join(P.OUT, code)
    path = os.path.join(folder, '.card-identities.json')
    reg = {'ids': {}, 'high_water': 0}
    if os.path.exists(path):
        with io.open(path, encoding='utf-8') as fp:
            reg.update(json.load(fp))
    previous = {}
    used = Counter()
    old = os.path.join(folder, 'cards.jsonl')
    if os.path.exists(old):
        with io.open(old, encoding='utf-8') as fp:
            for line in fp:
                if not line.strip():
                    continue
                row = json.loads(line)
                digest = card_fingerprint(row)
                used[digest] += 1
                key = digest + ':' + str(used[digest])
                cid = row.get('id') or ''
                reg['ids'][key] = cid
                previous[cid] = row
                m = re.fullmatch(re.escape(code) + r'-C(\d+)', cid)
                if m:
                    reg['high_water'] = max(reg['high_water'], int(m.group(1)))
    return reg, previous


def stable_card_ids(rows, code):
    reg, previous = _identity_state(code)
    seen = Counter()
    for row in rows:
        digest = card_fingerprint(row)
        seen[digest] += 1
        key = digest + ':' + str(seen[digest])
        cid = reg['ids'].get(key)
        if not cid:
            reg['high_water'] += 1
            cid = '%s-C%03d' % (code, reg['high_water'])
            reg['ids'][key] = cid
        row['id'] = cid
        row['asset_fingerprint'] = digest
        row['revision'] = (previous.get(cid) or {}).get('revision', 1)
    return rows


def save_identity_registry(code, rows):
    """只有真正保存抽取产物时更新账本，保留已移除内容的编号以防旧意见错挂。"""
    reg, previous = _identity_state(code)
    old_path = os.path.join(P.OUT, code, 'cards.jsonl')
    previous_keys = {cid: card_fingerprint(row) for cid, row in previous.items()}
    current_keys = {row['id']: card_fingerprint(row) for row in rows}
    if previous_keys and previous_keys != current_keys and os.path.exists(old_path):
        digest = hashlib.sha256(json.dumps(previous_keys, sort_keys=True).encode('utf-8')).hexdigest()[:16]
        history = os.path.join(P.OUT, code, '.history', 'cards-' + digest)
        os.makedirs(history, exist_ok=True)
        shutil.copy2(old_path, os.path.join(history, 'cards.jsonl'))
    seen = Counter()
    for row in rows:
        digest = card_fingerprint(row)
        seen[digest] += 1
        reg['ids'][digest + ':' + str(seen[digest])] = row['id']
        m = re.fullmatch(re.escape(code) + r'-C(\d+)', row['id'])
        if m:
            reg['high_water'] = max(reg['high_water'], int(m.group(1)))
    folder = os.path.join(P.OUT, code)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.identities-', dir=folder)
    with os.fdopen(fd, 'w', encoding='utf-8') as fp:
        json.dump(reg, fp, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(folder, '.card-identities.json'))


def extract(book, segs, proto, algo_punct=False, atlas_entries=None, allow=None,
            story_people=None):
    """按原型抽候选卡。返回 (候选列表, 说明)。

    拒判（proto 为 None）的书不出候选——连该抽什么都不知道，
    硬抽只会产出与书类型错位的资产。
    """
    code = book.get('code') or 'BK'
    rows, notes = [], []
    if not proto or proto not in PLAN:
        # 类型未定时不出一整本空白：只放行「不依赖类型」的低风险产物。
        # 引书（《书名》出现）和篇目（目录结构）对任何书都成立，
        # 规则/情节这类依赖文体的产物必须等类型确认，避免把台词当规则。
        for label in ('引书', '篇目'):
            fn = _EXTRACTORS.get(label)
            if not fn:
                continue
            try:
                got = fn(segs, code)
            except Exception as e:
                notes.append('%s抽取失败: %s' % (label, e))
                continue
            notes.append('%s %d 条' % (label, len(got)))
            for r in got:
                r['未编目'] = True
            rows.extend(got)
        stable_card_ids(rows, code)
        for r in rows:
            r['书'] = book.get('book')
            r['码'] = code
            lv, _kind, why = CONFIRM.get(r['类型'], ('低', '仅定位器', ''))
            r['精度'] = lv
            r['资产性质'] = '仅定位器'
            r['精度说明'] = '未编目：类型未定，只出定位类产物；确认类型后可产出完整资产'
        return rows, '；'.join(notes) + '（未编目，仅低风险产物）'
    if proto == 'P12':
        plan = PLAN.get(proto) or []
        if allow is not None:
            plan = [(label, fn) for label, fn in plan if label in allow]
        for label, fn in plan:
            if label == '篇目' and story_people:
                continue          # 人物条目已经是一条一人，篇目卡重复
            try:
                if label == '人物':
                    got = _person_candidates(segs, code, story_people)
                else:
                    got = fn(segs, code)
            except Exception as e:
                notes.append(f'{label}抽取失败: {e}')
                continue
            notes.append(f'{label} {len(got)} 条')
            rows.extend(got)
    elif proto == 'P11':
        if not PLAN.get(proto):
            notes.append('物种条目抽取器已在后台关闭')
        else:
            rows = _atlas_candidates(segs, code, atlas_entries)
            notes.append(f'物种条目 {len(rows)} 条'
                         + ('' if atlas_entries else '（无版面数据）'))
    else:
        if allow is not None:
            # 判定层为主：判定说适用的列就跑，不再被类型套餐卡住。
            # 类型套餐只在没有判定结果时兜底——否则「P2 的书被判出情节/引书」会一张卡都出不来。
            labels = set(allow)
            if proto == 'P12':
                labels.add('人物')      # 人物不在判定列里，P12 必须带上
            plan = [(label, _EXTRACTORS[label]) for label in ALL_LABELS if label in labels]
            skipped = [label for label in labels if label not in _EXTRACTORS]
            if skipped:
                notes.append('判定列无抽取器：%s' % '、'.join(sorted(skipped)))
        else:
            plan = PLAN[proto]
        for label, fn in plan:
            try:
                got = fn(segs, code)
            except Exception as e:
                notes.append(f'{label}抽取失败: {e}')
                continue
            notes.append(f'{label} {len(got)} 条')
            rows.extend(got)
    # 保留同内容身份，列表变动不能让旧人工意见落到另一条内容。
    stable_card_ids(rows, code)
    for r in rows:
        r['书'] = book.get('book')
        r['码'] = code
        r['原型'] = proto
        lv, kind, why = CONFIRM.get(r['类型'], ('中', '需人筛', ''))
        r['精度'] = lv
        r['资产性质'] = kind
        r['精度说明'] = why
        if algo_punct:
            r['可回查'] = False
            r['限制'] = ('本句读为算法补出（底本无标点），'
                         '只能用于检索定位，不得作为引文')
    return rows, '；'.join(notes)


_TITLE_DOMAINS = {
    '规则': re.compile(r'规[章程定则]|操作(?:规程|指南|要求|步骤)|使用(?:指南|说明)|安全(?:须知|要求)|注意事项'),
    '条目': re.compile(r'^(?:条目|术语|词条|名录|辞条|釋名|释名)|^(?:[卷](?:[一二三四五六七八九十百0-9]+).{0,15})?(?:条目|词条|名录)$'),
    '训释': re.compile(r'训释|訓釋|訓詁|训诂|釋詁|释诂|釋言|释言|釋訓|释训'),
}
_SOURCE_NOISE = re.compile(
    r'^(?:版权页|图书在版编目\(?CIP\)?数据|版权所有|责任编辑[：:]|出版发行[：:]|'
    r'目录[.·…\d]*$|(?:表|续表)\s*[\d.]+|参考文献[.·…\d]*$)')
_NON_CONTENT_PARTS = re.compile(r'^(?:版权页|封面|扉页|目录|目錄|CONTENTS|参考文献|參考文獻)(?:$|[\s：:])', re.I)
_NON_CONTENT_ROLES = {'toc', 'cover', 'copyright', 'header', 'footer', 'table', 'caption', 'reference'}
_DRAMA_ACTION = re.compile(r'[\[［（(]([^\]］）)\n]{2,32})[\]］）)]')
_DRAMA_DIRECTION = re.compile(r'(?:[上下来退出进]场|幕[启啓落闭閉]|黑场|灯光|走[进出向过上]|转[向过身]|'
                              r'叹气|跪下|喝酒|拔剑|落泪|笑|握住|捂住|抱住|坐[下着]|[哭泪舞唱醉]介|'
                              r'^(?:生|旦|净|末|丑|外|贴|红|紅)[下上吟哭唱白見见介科雲云]+$)')
_DRAMA_SPEAKERS = re.compile(r'(?m)^(?:[\u3400-\u9fff]{2,6})[：:]\s*[^。]{2,}')
_CHAPTER_EVENT = re.compile(r'^第[一二三四五六七八九十百千零〇0-9]+[回齣出][：:、\s]*')
_GLOSS_PAIR = re.compile(r'[\u3400-\u9fff]{2,8}[，,](?:曰|謂之|谓之)[\u3400-\u9fff]{2,14}')
_RULE_SENTENCE = re.compile(r'(?:^|[。；])\s*(?:须先|應先|应先|务必|务须|切忌|不得|必须)')
_MODERN_DEFINITION = re.compile(
    r'^([\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z0-9·]{1,29})[，,]?(是指|指的是|是)'
    r'([^，。！？；!?；:：]{5,100})(?:[，,。；]|$)')
_DEFINITION_KIND = re.compile(r'(?:技术|过程|方式|方法|设备|体系|领域|系统|能力|学科|原理|现象|工具|材料|算法|机制|模型|单位|数据|图纸|图形|标准)$')
_NAMED_DEFINITION = re.compile(
    r'(?:^|[，,])((?:即|也就是)([^，。！？；!?]{5,60})[，,](?:称为|叫作|称作)'
    r'([\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z0-9·]{1,15}))(?=[，,。；]|$)')
_DEFINITION_HEAD = re.compile(r'^(?:(?:所谓|基础知识|科学链接|知识链接|知识拓展|科普链接|拓展阅读))+')


def content_evidence_segment(row):
    """The shared evidence filter permits plain text when no layout role is available."""
    return (not row.get('source_issue') and not row.get('source_layout_suspect')
            and row.get('source_role') not in _NON_CONTENT_ROLES
            and not _NON_CONTENT_PARTS.match(str(row.get('篇') or '').strip())
            and not _SOURCE_NOISE.match(_blank(row.get('文本') or '')))


def _modern_definitions(segs, code):
    rows = []
    seen = set()
    for s in segs:
        for sent in sents_of(_blank(s.get('文本') or '')):
            match = _MODERN_DEFINITION.match(sent)
            named = _NAMED_DEFINITION.search(sent)
            if named:
                quote, meaning, term = named.groups()
            elif match:
                raw_term, verb, meaning = match.groups()
                term = _DEFINITION_HEAD.sub('', raw_term)
                repeated = re.search(r'(.{2,})\1$', term)
                if repeated:
                    term = repeated.group(1)
                if verb == '是' and not ('一种' in meaning and _DEFINITION_KIND.search(meaning)):
                    continue
                offset = match.end(1) - len(term)
                quote = sent[offset:]
                meaning = sent[match.start(3):].rstrip('。！？；')
            else:
                continue
            if (not 2 <= len(term) <= 16 or term in seen or term in meaning
                    or PRONOUN_LEAD.match(term)
                    or term.startswith(('什么', '为什么', '如何', '本书', '我们', '他们', '它们', '你', '他', '她'))
                    or len(quote) > 180):
                continue
            seen.add(term)
            rows.append(_mk(code, 0, '概念候选', '中', s['id'], quote,
                            {'词条': term, '定义': meaning}, [], '从原文的定义句提取，适用范围请核对'))
    return rows


def _content_rules(by_chapter, book, layout_plan):
    """Choose sections with stronger signals before invoking broad legacy extractors."""
    selected = {name: [] for name in ('规则', '情节', '曲牌科介', '作品', '训释', '条目', '释义')}
    profile = str((layout_plan or {}).get('pattern') or '')
    for chapter, rows in by_chapter.items():
        valid_head = [s for s in rows if not s.get('source_structure_suspect')]
        if valid_head:
            for name, pattern in _TITLE_DOMAINS.items():
                if pattern.search(chapter.strip()):
                    selected[name].extend(valid_head)
            if _CHAPTER_EVENT.match(chapter):
                selected['情节'].extend(valid_head)
            if profile == 'namepair' and re.search(r'詩|诗|詞|词|曲|韵|韻|选集', book.get('book') or ''):
                selected['作品'].extend(valid_head)
        dialogue, directions, overt_drama, glosses = [], [], [], []
        rule_title = _TITLE_DOMAINS['规则'].search(chapter)
        gloss_title = re.search(r'艺文|詞義|词义|释义|釋義|训释|訓釋|訓詁|训诂|類書|类书|蒙学|蒙學', chapter)
        for row in rows:
            text = row.get('文本') or ''
            if not rule_title and _RULE_SENTENCE.search(text):
                selected['规则'].append(row)
            pairs = len(_GLOSS_PAIR.findall(text))
            if pairs:
                glosses.append((row, pairs))
            if re.search(r'(?:^|\n)作\s*者\s*[：:]', text):
                selected['作品'].append(row)
            if _DRAMA_SPEAKERS.search(text):
                dialogue.append(row)
            if any(_DRAMA_DIRECTION.search(m.group(1)) for m in _DRAMA_ACTION.finditer(text)):
                directions.append(row)
            if re.search(r'曲牌[：:【]|剧终|劇終|舞台提示|劇中人物|剧中人物|[\[［][生旦淨净末丑外貼贴紅红][上唱下白介科雲云][\]］]', text):
                overt_drama.append(row)
        if (directions and (dialogue or len(overt_drama) >= 1)
                or len(overt_drama) >= 2 or 'qupai' in profile and directions):
            selected['曲牌科介'].extend(directions + overt_drama)
        if gloss_title or sum(pairs for _, pairs in glosses) >= 3:
            selected['释义'].extend(row for row, _ in glosses)
    return {name: list({r['id']: r for r in rows}.values()) for name, rows in selected.items()}


def extract_by_content(book, segs, proto=None, algo_punct=False, atlas_entries=None,
                       story_people=None, layout_plan=None, enabled=None):
    """Collect evidenced candidates without making the book's genre a routing gate."""
    code = book.get('code') or 'BK'
    enabled = enabled_labels() if enabled is None else set(enabled)
    body = [s for s in segs if content_evidence_segment(s)]
    by_anchor = {row['id']: row for row in body}
    by_chapter = {}
    for row in body:
        by_chapter.setdefault(str(row.get('篇') or ''), []).append(row)
    routed = _content_rules(by_chapter, book, layout_plan)
    routed['篇目'] = [s for s in body if not s.get('source_structure_suspect')]
    rows, checks, raw_hits = [], {}, {}
    for name in ALL_LABELS:
        if name not in enabled:
            checks[name] = {'status': 'disabled', 'count': 0, 'reason': '此项已在设置中关闭'}
            continue
        candidates, failure = [], ''
        try:
            extractor = _EXTRACTORS[name]
            if name == '人物':
                candidates = extractor(body, code, story_people) if story_people else []
            elif name == '物种条目':
                candidates = extractor(body, code, atlas_entries) if atlas_entries else []
            elif name == '曲牌科介':
                for s in routed[name]:
                    for m in _DRAMA_ACTION.finditer(s['文本']):
                        cue = m.group(1)
                        if _DRAMA_DIRECTION.search(cue):
                            candidates.append(_mk(code, 0, '科介候选', '中', s['id'], m.group(0),
                                                  {'科介': cue}, [], '原文舞台动作，请核对所属场次'))
                for s in routed[name]:
                    for m in re.finditer(r'曲牌\s*(?:[：:]\s*)?【([^】]{1,10})】', s['文本']):
                        candidates.append(_mk(code, 0, '曲牌候选', '中', s['id'], m.group(0),
                                              {'曲牌': m.group(1)}, [], '原文注明曲牌'))
                if 'qupai' in str((layout_plan or {}).get('pattern') or ''):
                    candidates.extend(extractor(routed[name], code))
            else:
                candidates = extractor(routed.get(name, body), code)
                if name == '定义':
                    candidates.extend(_modern_definitions(body, code))
                elif name == '释义':
                    candidates = [c for c in candidates if _GLOSS_PAIR.fullmatch(c['原文'])]
                elif name == '引书':
                    own = _blank(book.get('book') or '').split('：')[0].split(':')[0].strip('《》')
                    candidates = [c for c in candidates if c['字段'].get('书名') != own]
                elif name == '凡式':
                    candidates = [c for c in candidates if any(
                        sent.startswith(c['原文']) for sent in sents_of(
                            _blank(by_anchor.get(c['锚点'], {}).get('文本', ''))))]
                elif name == '条目':
                    candidates = [c for c in candidates if not re.search(
                        r'第.{1,10}(?:章|节|课|单元)|任务|练习|表\d|续表|评价|小结', c['字段'].get('条目名', ''))]
                elif name == '地形':
                    for c in candidates:
                        c['类型'] = '地形候选'
        except (KeyError, ValueError, TypeError, OSError):
            failure = '本次提取未完成，可以补做'
        unique = {}
        for c in candidates:
            c['抽取项'] = name
            # The same text can form a distinct occurrence in another chapter.
            unique.setdefault((c['锚点'], c['类型'], c['原文']), c)
        raw_hits[name] = len(unique)
        rows.extend(unique.values())
        if failure:
            checks[name] = {'status': 'failed', 'count': 0, 'reason': failure}

    rows, dropped, _ = verify(rows, body, strict_anchors=True)
    confirmed = Counter(r['抽取项'] for r in rows)
    damaged_source = any(s.get('source_issue') or s.get('source_layout_suspect') for s in segs)
    suspect_structure = any(s.get('source_structure_suspect') for s in segs)
    for name in ALL_LABELS:
        if name in checks:
            continue
        n = confirmed[name]
        if algo_punct and n:
            checks[name] = {'status': 'needs_review', 'count': n, 'reason': '原文标点由程序补出，引用前请核对'}
        elif name in ('篇目', '情节', '条目') and suspect_structure:
            checks[name] = {'status': 'needs_review', 'count': n, 'reason': '部分章节还需要回原书核对'}
        elif n and (name in REVIEW_CONTENT or damaged_source):
            checks[name] = {'status': 'needs_review', 'count': n, 'reason': '有原文依据，使用前请核对这项内容'}
        elif n:
            checks[name] = {'status': 'extracted', 'count': n, 'reason': '已找到可回原文的候选'}
        elif raw_hits.get(name):
            checks[name] = {'status': 'needs_review', 'count': 0, 'reason': '找到线索，出处暂未核对通过'}
        elif not body or damaged_source:
            checks[name] = {'status': 'needs_review', 'count': 0, 'reason': '请先核对正文和章节'}
        else:
            checks[name] = {'status': 'not_found', 'count': 0, 'reason': '本次未找到可确认的依据'}
    stable_card_ids(rows, code)
    for row in rows:
        row.update({'书': book.get('book'), '码': code, '原型': proto})
        level, asset_kind, note = CONFIRM.get(row['类型'], ('中', '需人筛', '请核对内容和出处'))
        row.update({'精度': level, '资产性质': asset_kind, '精度说明': note})
        if algo_punct:
            row.update({'可回查': False, '限制': '原文标点由程序补出，只能用于检索定位'})
    return rows, checks, dropped


def verify(rows, segs, strict_anchors=False):
    """硬校验：每条候选的原文必须能在 segments 里逐字查到。

    这是整个卡片层的出口条件。查不到就丢弃——不是降级保留，
    因为一条无法回查的原文，在资产库里等于一句无法核实的断言。
    返回 (通过列表, 丢弃数, 丢弃原因样例)。

    两条核对路：
      body  原文在该段正文里（绝大多数卡）
      title 原文是该篇的篇名（情节卡）—— 回目不在正文里，
            只能在「篇」字段上逐字比对，等价严格，不是放宽。
    """
    body = {s['id']: _blank(s['文本']) for s in segs}
    atlas_index = None
    # 篇名 → 该篇所有段的锚点集合（情节卡按篇名核对时用）
    titles = {}
    for s in segs:
        if s['篇序'] > 0:
            titles.setdefault(s['篇'], set()).add(s['id'])
    ok, dropped, whys = [], 0, []
    for r in rows:
        q = _blank(r.get('原文', ''))
        a = r.get('锚点')
        hit = False
        if r.get('核对路') == 'atlas':
            if atlas_index is None:
                from bisect import bisect_right
                offsets, ids, ranges = [], [], {}
                pos = 0
                for sid, text in body.items():
                    if not text:
                        continue
                    offsets.append(pos)
                    ids.append(sid)
                    ranges[sid] = (pos, pos + len(text))
                    pos += len(text)
                atlas_index = ''.join(body.values()), offsets, ids, ranges
            blob, offsets, ids, ranges = atlas_index
            bounds = ranges.get(a)
            start = blob.find(q, bounds[0] if bounds else 0) if q else -1
            if bounds and (start < 0 or start >= bounds[1]):
                start = blob.find(q) if q else -1
            if start >= 0:
                r['锚点'] = ids[bisect_right(offsets, start) - 1]
                r['可回查'] = True
                ok.append(r)
            else:
                dropped += 1
                if len(whys) < 3:
                    whys.append(f"{r['id']} [条目不可回查] {q[:24]}")
            continue
        if r.get('核对路') == 'title':
            # 篇名核对：原文必须等于某篇的篇名（逐字），且锚点在该篇内
            for tname, ids in titles.items():
                if _blank(tname) == q:
                    hit = True
                    if a not in ids:
                        r['锚点'] = sorted(ids)[0]
                    break
            if not hit:
                dropped += 1
                if len(whys) < 3:
                    whys.append(f"{r['id']} [篇名核对失败] {q[:24]}")
                continue
        if hit:
            # 篇名核对通过 —— 这也是真回查，只是走 title 路。
            # 曾经这里直接 continue，`可回查` 停留在 _mk 传进来的初值，
            # 于是情节卡即使核对成功也标 false。
            r['可回查'] = True
            ok.append(r)
            continue
        if a in body and q and q in body[a]:
            hit = True
        elif not strict_anchors and q and any(q in t for t in body.values()):
            # 锚点不准但原文确实在书里：保留，但把锚点改正到实际所在段
            hit = True
            for sid, t in body.items():
                if q in t:
                    r['锚点'] = sid
                    break
        if hit:
            # ★ 关键：verify 是「可回查」的唯一裁断者。
            # _mk 里的 bool(requote) 只是抽取器的**自述**，不是结论。
            # 规则卡传的是 requote=False（它只敢说「这段在讲该怎么做」），
            # 但原文本身就是整段截取，逐字能查 —— 事实是能回查的。
            # 曾经 verify 通过后不改这个字段，导致 563 条规则卡全部
            # 落盘成 可回查=false，而实测 514 条明明能在正文里逐字找到。
            # 这是「报告与实际不一致」，比校验失败更糟：它不报错。
            r['可回查'] = True
            ok.append(r)
        else:
            dropped += 1
            if len(whys) < 3:
                whys.append(f"{r['id']} {q[:24]}")
    return ok, dropped, whys
