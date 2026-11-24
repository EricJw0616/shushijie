# -*- coding: utf-8 -*-
"""标签抽取器：把已提取的内容成果压成可筛选、可解释的标签。

设计原则（三条，缺一条就变成假标签）：
  1. 每个标签必须带 **来源**，只有三种取值：
       实测 — 程序从正文数出来的（字数、段数、R/D/A/Q 密度、篇数）
       抽取 — 正则从正文抽出来的（《书名》、称谓、曲牌），可回查锚点
       判断 — 需要人来定性的（原型、能否出图谱）；这类一律标「待确认」
     不允许出现第四种「大模型说的」——那是最不靠谱的一层。
  2. 每个标签必须带 **验证方式**，告诉人怎么自己核。
  3. 算不出来的标「未做」或 None，**不填默认值**。
     标签表的公信力全靠这条：宁可缺一格，不能假一格。
"""
import re, json, io, os
from functools import lru_cache
import paths as P
from cards import content_evidence_segment
from library import book_name_signals, name_evidence_segment

HAN = re.compile('[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\U00020000-\U0002FA1F]')

# 编次式篇名：作者没给标题，只有序号，不含内容信息，不能当标签
RE_ORDINAL = re.compile(
    r'(?:第[一二三四五六七八九十百零〇0-9]+[章回节篇出卷集课]|'
    r'卷[一二三四五六七八九十百零〇0-9]+|'
    r'[〔【]?(?:正宫|中吕|双调|越调|南吕|仙吕|黄钟|商角|大石调)[〕】]?|'
    r'[一二三四五六七八九十0-9]+)[：:、.]?')

# 篇名里出现这些 → 是排版垃圾行（出版信息、演职员表），不是标题
RE_JUNK_TITLE = re.compile(
    r'刊于|载于|原载|出场人物|地点[:：]|人物[:：]|时间[:：]|第\s*期|卷\s*期|星期特刊')


@lru_cache(maxsize=16)
def _read_segments(path, version):
    with io.open(path, encoding='utf-8') as fp:
        return tuple(json.loads(line) for line in fp if line.strip())


def segments(code):
    path = os.path.join(P.OUT, code, 'segments.jsonl')
    try:
        stat = os.stat(path)
    except OSError:
        return ()
    return _read_segments(path, (stat.st_ino, stat.st_mtime_ns, stat.st_size))


def _code_of(anchor):
    return anchor.split('-')[0] if anchor else ''


def _ctx(code, word, width=60):
    """在正文里找该词的**第一处实际出现**，返回带上下文的片段。

    不能直接用 names.jsonl 的「首现」锚点 —— 那是按 segments 顺序取的第一处，
    往往落在前置/目录页（《山海经》就被取到了目录行）。
    这里直接扫正文，跳过篇序 0 的前置页，取真正出现在句子里的那一处。
    """
    rows = segments(code)
    has_chapters = any(row.get('篇序') for row in rows)
    for row in rows:
        if (has_chapters and not row.get('篇序')) or not content_evidence_segment(row):
            continue
        txt = row.get('文本') or ''
        i = txt.find(word)
        if i < 0:
            continue
        a = max(0, i - width)
        b = min(len(txt), i + len(word) + width)
        return row['id'], txt[a:b]
    return '', ''


def _norm(s):
    return re.sub(r'[\s\u3000\xa0]+', '', s or '')


def is_content_title(t):
    """篇名本身是否构成一条内容标签。"""
    t = _norm(t)
    if not t or len(t) < 2:
        return False
    if RE_ORDINAL.fullmatch(t):
        return False
    if RE_JUNK_TITLE.search(t):
        return False
    # 纯汉字/书名号/间隔号，至少 2 个汉字
    if len(HAN.findall(t)) < 2:
        return False
    return True


def content_titles(outline, max_n=14):
    """取有信息量的篇名。按篇长降序取前 N（长文才是主干），保持原顺序输出。"""
    rows = []
    for i, r in enumerate(outline):
        nm = r.get('篇') or r.get('名') or ''
        if not is_content_title(nm):
            continue
        rows.append((i, _norm(nm), r.get('字数') or r.get('段数') or 1, r.get('首锚点') or ''))
    if not rows:
        return []
    keep = sorted(rows, key=lambda x: -x[2])[:max_n]
    keep.sort(key=lambda x: x[0])
    return [{'标签': nm, '类': '篇名', '来源': '抽取',
             '验证': '原文篇标题', '锚点': anc, '权': w}
            for _i, nm, w, anc in keep]


# ---------- 引用书目：《书名》 ----------

# 这些不是真实书名，是排版或泛称
BOOK_STOP = {
    '谱', '诗', '史', '汉', '韶', '荆', '刘', '拜', '杀', '易', '诗云', '书云',
    '上', '下', '前', '后', '左', '右', '一', '二', '三',
}


def cited_books(names, min_freq=2, max_n=10):
    """书里引用了哪些别的书。这是最能说明「这本书在跟谁对话」的标签。

    只收 names.jsonl 里 类=书名篇名 的条目，且：
      - 《》内汉字 ≥2（排除《谱》《诗》这种单字简称）
      - 频次 ≥ min_freq
      - 不是本书自己（自己书名出现在封面页，不是引用）
    """
    rows = [r for r in names if r.get('类') == '书名篇名']
    out = []
    for r in rows:
        w = _norm(r['词']).strip('《》')
        if len(HAN.findall(w)) < 2:
            continue
        if w in BOOK_STOP:
            continue
        key = r.get('证据锚点')
        source = r.get('证据原文') or ''
        anchor, quote = '', ''
        if key and any(_norm(name) == w and signal == 'citation'
                       for name, _, signal in book_name_signals(source)):
            proof = next((row for row in segments(_code_of(key)) if row.get('id') == key), {})
            if name_evidence_segment(proof) and source in (proof.get('文本') or ''):
                anchor, quote = key, source
        if not anchor and r.get('频次', 0) >= min_freq:
            anchor, quote = _ctx(_code_of(r.get('首现', '')), '《' + w + '》')
        if not anchor:
            continue
        out.append({'标签': w, '类': '引用书目', '来源': '抽取',
                    '验证': '可查看正文引用位置',
                    '锚点': anchor, '权': r.get('频次', 0), '原文': quote})
    out.sort(key=lambda x: -x['权'])
    return out[:max_n]


# ---------- 称谓 / 人物名 ----------

# 称谓类里的垃圾：以这些开头的不是人名
BAD_PERSON_HEAD = ('有', '这', '那', '一', '两', '三', '几', '众', '每', '各', '其', '此')


def person_names(names, people, max_n=12):
    """人物名。**这一层是全程最不可靠的一层，处置方式必须最保守。**

    实测教训：姓氏法把「关/应/于/从/身/方/和」都当姓，
    于是「关于」「应当」「后面」「从他」「和善」全被判成「强证据」人物。
    这是方法的硬上限，不是调参能解决的——中文人名与常用词同形，
    没有词性标注和前文语境，纯统计分不开。

    因此本函数只在 names.jsonl 的「称谓」类里取，并且要求：
      1. 末尾是典型称谓字（先生/太太/小姐/老爷/姑娘/君/氏/公/母/儿）
         或首字在《百家姓》高频段且后接单/双字名（形态像人名）
      2. 不是虚词、不是方位词、不是抽象名词
    宁可一个人物都不出，也不出一张假的名单。
    """
    out, seen = [], set()
    # 只有以这些字结尾的称谓，才几乎确定是人
    SURNAME_TAIL = ('先生', '太太', '小姐', '老爷', '夫人', '姑娘', '君',
                    '氏', '公', '母', '太太', '老板', '掌柜', '教授', '博士')
    # 抽象名词/方位/虚词的尾字：出现即排除
    BAD_TAIL = set('的了着过是在有和与从对向于后面前边里外上下间中处'
                   '该应当能可要会得地白亮楚信望力福好善害怕欢喜怒乐忙')

    for r in names:
        if r.get('类') != '称谓':
            continue
        nm = _norm(r['词'])
        if nm in seen or not (2 <= len(nm) <= 5):
            continue
        if nm.startswith(BAD_PERSON_HEAD):
            continue
        if any(c in nm for c in BAD_TAIL):
            continue
        if r.get('频次', 0) < 3:
            continue
        # 必须带称谓后缀，或是「姓+名」形态（靠 names 抽取时已要求连续汉字）
        has_tail = any(nm.endswith(t) for t in SURNAME_TAIL)
        if not has_tail:
            continue
        anchor, quote = _ctx(_code_of(r.get('首现', '')), nm)
        if not anchor:
            continue
        seen.add(nm)
        out.append({'标签': nm, '类': '人物', '来源': '抽取',
                    '验证': '按正文中的称谓找到，请核对所指人物',
                    '锚点': anchor, '权': r.get('频次', 0),
                    '状态': '待核对', '原文': quote})
        if len(out) >= max_n:
            break
    out.sort(key=lambda x: -x['权'])
    return out


# ---------- 戏曲：曲牌 / 科介 ----------

def drama_marks(qupai, kejie, max_n=8):
    out = []
    for r in sorted(qupai, key=lambda x: -x.get('频次', 0))[:max_n]:
        out.append({'标签': r['曲牌'], '类': '曲牌', '来源': '抽取',
                    '验证': f"正文可查 {r.get('频次')} 次", '权': r.get('频次', 0)})
    return out


# ---------- 语体标签：把六轴翻译成人能读的话 ----------

def style_tags(feat):
    """六轴 → 人读得懂的语体描述。阈值来自 22 本实测分布，不是拍脑袋。"""
    tags = []
    R, D, A, Q = feat.get('R', 0), feat.get('D', 0), feat.get('A', 0), feat.get('Q', 0)
    wen, savg = feat.get('wen', 0), feat.get('savg', 0)

    if wen >= 50:
        tags.append({'标签': '文言为主', '值': f'{wen}%', '来源': '实测',
                     '验证': '文言虚词占比（每千汉字）'})
    elif wen >= 20:
        tags.append({'标签': '文白夹杂', '值': f'{wen}%', '来源': '实测',
                     '验证': '文言虚词占比'})
    else:
        tags.append({'标签': '白话', '值': f'{wen}%', '来源': '实测',
                     '验证': '文言虚词占比'})

    if R >= 15:
        tags.append({'标签': '强规范', '值': f'R{R}', '来源': '实测',
                     '验证': '「必/不可/切忌」等规范词每千字'})
    elif R >= 8:
        tags.append({'标签': '含规范', '值': f'R{R}', '来源': '实测',
                     '验证': '规范词密度'})

    if D >= 15:
        tags.append({'标签': '多定义', '值': f'D{D}', '来源': '实测',
                     '验证': '「者/所谓/即是」等定义句式每千字'})
    elif D >= 8:
        tags.append({'标签': '有定义', '值': f'D{D}', '来源': '实测',
                     '验证': '定义句式密度'})

    if Q >= 30:
        tags.append({'标签': '对白主导', '值': f'{Q}%', '来源': '实测',
                     '验证': '引号内字数占比'})
    elif Q >= 12:
        tags.append({'标签': '有对白', '值': f'{Q}%', '来源': '实测',
                     '验证': '引号内字数占比'})

    # 句长：22 本实测 12–30，分三档
    if savg >= 26:
        tags.append({'标签': '长句', '值': f'{savg}字', '来源': '实测',
                     '验证': '平均句长（按句末标点切）'})
    elif savg <= 18:
        tags.append({'标签': '短句', '值': f'{savg}字', '来源': '实测',
                     '验证': '平均句长'})
    return tags


# ---------- 能力标签：这本书能拿出什么 ----------

CAP_NAME = {
    'segments': '全文可检索',
    'outline': '篇目结构',
    'names': '专名索引',
    'people': '人物候选',
    'qupai': '曲牌索引',
    'kejie': '科介索引',
    'rules': '规则卡',
    'topics': '主题卡',
    'entries': '物种条目卡',
}

CAP_VERIFY = {
    'segments': '段落已切分且带锚点',
    'outline': '篇目已切出',
    'names': '《书名》与称谓已索引',
    'people': '强证据人物 ≥6 人才算有',
    'qupai': '在书中找到曲牌写法，可回原文核对',
    'kejie': '在书中找到舞台动作提示，可回原文核对',
    'rules': '卡片原文已逐字回查通过',
    'topics': '卡片原文已逐字回查通过',
    'entries': '每条按「来源」切分，原文逐字回查通过',
}


def capability_tags(done, has_cards):
    out = []
    for k, cn in CAP_NAME.items():
        if done.get(k):
            out.append({'标签': cn, '来源': '实测', '验证': CAP_VERIFY[k]})
    return out
