# -*- coding: utf-8 -*-
"""结构探测器：从 PDF 抽取的脏文本中找出篇/章/出/条级骨架。
只做探测，不改文本。输出「结构方案」，供清洗与切段使用。

设计原则：
  1. 先找目录（TOC 最可靠，书名页码一一对应）
  2. 目录不可用时退到正则（回/章/出/折/条/篇）
  3. 都不行再退到「孤立短行 + 单调序号」启发式
  4. 探不到就是探不到，报 unknown，绝不硬凑
"""
import json
import os
import re
import unicodedata
import paths as P

PAGE = re.compile(r'<<<PAGE (\d+)>>>')

# 章回体 / 戏曲 / 条款
# 判据不是长度，是「标题行没有句读」。
# 不加约束时，正文里以「第X回」开头的句子会被当成标题，篇序整本错位：
#   实测《红楼梦》「第四回中既將薛家母子…此回則暫不能寫矣．」
#   与「第二回了．你怎么嘗不出來？」都曾被判成回目。
# 长度约束不适用：真回目可长到 32 字（「第一百二十回　甄士隱詳說…」），
# 而伪标题只有 26 字。句读才是分水岭 —— 标题只有空白与间隔号，
# 正文必有逗号句号。允许回目里的「·」与全角空格。
#
# 分隔符要放开：三国志演义写「第一回：宴桃園豪傑三結義，斬黃巾…」，
# 中间既有冒号又有逗号。把冒号逗号一律排除会让整本书篇数掉到 0。
# 折中做法：冒号只允许出现在回号紧接着的位置（作为编号与回目的分隔），
# 回目内部允许逗号 —— 因为回目本身就是对句，必带标点。
# 排除真正的句子：以「第X回」开头后紧跟虚词/代词接续（了．/中既/的下…），
# 这是正文叙述在引用回次，不是标题。
RE_HUI   = re.compile(r'^第\s*[一二三四五六七八九十百零〇0-9]{1,4}\s*[回章卷节篇部]'
                      r'[：:　 \u3000]?'
                      r'(?![了的中既又再上下里内])'
                      r'[^。；！？．;!?]{0,44}$')

# 序号与篇名分列：第一　始计篇。要求空白分隔、短标题及连续编号。
RE_PIAN_LEAD = re.compile(r'^第([一二三四五六七八九十百零〇0-9]{1,4})[\s　]+([^。；！？，、：:;!?]{1,20}[篇章])$')

RE_HUI_U = re.compile(r'^第\s*[一二三四五六七八九十百零〇0-9]{1,4}\s*([回章卷节篇部])')


def _dominant_hui_unit(lines):
    """RE_HUI 同时匹配回/章/卷/节/篇/部，单位取实际命中的众数。"""
    cnt = {}
    for _, s in lines:
        m = RE_HUI_U.match(s)
        if m:
            u = m.group(1)
            cnt[u] = cnt.get(u, 0) + 1
    if not cnt:
        return '回'
    return max(cnt.items(), key=lambda kv: kv[1])[0]


RE_CHU   = re.compile(r'^第\s*[一二三四五六七八九十百零〇0-9]{1,4}\s*[出折幕]'
                      r'[：:　 \u3000]?'
                      r'(?![了的中既又再上下里内])'
                      r'[^。；！？．;!?]{0,44}$')
RE_TIAO  = re.compile(r'^第\s*[一二三四五六七八九十百零〇0-9]{1,4}\s*条')
RE_JUAN  = re.compile(r'^卷\s*[一二三四五六七八九十]{1,3}(?:\s|$)')
# 「卷之一梁惠王上」体例（孟子译解体）。
# 与 RE_JUAN 的区别：卷号后**紧接篇名，中间无空格**。
# RE_JUAN 要求卷号后是空白或行尾，所以这种一行都匹配不到，
# 整本孟子退化到 numeral 模式，64 段全叫「第N章」，真篇名（梁惠王上/公孫丑上）全丢。
# 篇名限 1~8 字，避免把「卷之一」后面接的正文长句当篇名。
RE_JUAN_NAME = re.compile(r'^卷之[一二三四五六七八九十]{1,2}[\u4e00-\u9fff]{1,8}$')
# 「第 一 卦」体例（易经）：序号与量词之间插了空格。
# 这类底本把「第 一 卦」每个字都当独立排版单位，中间夹空格，
# 上三条正则都因 require 紧邻而匹配不到，整本书判成 flat（易经 64 卦全丢）。
# 量词表里补「卦」——六十四卦是书名自带的结构，不是通用章节单位。
RE_GUA   = re.compile(r'^第\s*[一二三四五六七八九十百零〇0-9]{1,4}\s*卦'
                      r'[：:　 \u3000]?[^。；！？．;!?]{0,20}$')
# 后置序数篇题：古籍最常用的体例，「耕田第一」「牧民第一」「度訓第一」。
# 为什么必须单独一条正则：这是**篇名在前、序数在后**，RE_HUI 要求序数在前，
# 一条都不匹配。实测齐民要术 100+ 篇、管子 86 篇、孔子家语 44 篇、逸周书 60 篇
# 全用这个体例，结果全部被判成 flat（篇数 0、锚点全落「前置」），
# 后续按篇索引、按篇出卡片的能力直接失效 —— 书是好的，是切不开。
# 约束「序数后必须结束」，避免把正文里「…第一」的句子当成标题。
# 结尾允许带一个句末标点：白文古籍会被自动补断句（segmenter），
# 「耕田第一」→「耕田第一。」，若不允许标点则整本书切不开（篇数全为 0）。
# 排除「…卷第一」「…出第一」这类卷级/出级标题，它们是上级单位，
# 混进篇列表会让篇序错位（实测齐民要术 127 个命中里 20 个是卷标题）。
RE_PIAN_AFTER = re.compile(
    r'^(?![^\n]*[卷出折回])[\u4e00-\u9fff]{1,8}[第][一二三四五六七八九十百]{1,3}[。！？]?$')
# 前置序数短篇题：「一之源」「二之具」（茶经体例）。
# 与 RE_PIAN_AFTER 是镜像：序数在前、篇名在后，且总长极短。
# 必须限死 3~6 字，否则正文里「一切众生」这类词会被当成标题。
RE_PIAN_PRE = re.compile(
    r'^[一二三四五六七八九十]{1,2}(?:之|、)[\u4e00-\u9fff]{1,3}[。！？]?$')
# 符号体例条目：●卷一 / ○三易 / ○重卦不始文王（日知录、梦溪笔谈）。
# 只认行首的 ●○◯◎，且符号后内容不超过 16 字 —— 长的是正文里的圈点。
RE_CIRC_ENTRY = re.compile(
    r'^[●○◯◎◇◆]\s*[\u4e00-\u9fff][^\n]{0,15}[。！？]?$')

# ── 三种「书名把标题括起来了」的标记 ────────────────────────────────
# 这三种此前都没接进 probe，导致 14 本书切不开或切错层级。
# 共同点：**底本用书名号/尖括号把标题括起来**，是最强的标题信号，
# 比「孤立短行」可靠得多（短行启发式会把诗句、对话都当标题）。
#
# 判据来自实测，不是猜：
#   〈〉聊斋志异 224 个，去重 223 = 100% 是篇名（考城隍/耳中人/屍變）
#   【】汉书 93 个 100% 是篇名（高帝紀第一/惠帝紀第二）
#        梦溪笔谈 26 个 100% 是卷名（卷一  故事一）
#        牡丹亭 20 个 50% 是曲牌（前腔/尹令），**不可当篇名** → 须排除
#   《》古文观止 49 个 96%（楚辞/左传）是**被引书名**，不是篇名 → 不可用
#        国语 21 个 95%（周語中/魯語上）**是篇名** → 可用
#        随园诗话 26 个 100% 是卷名（卷一/卷二）
# 所以不能「见到括号就切」，要按内容判定：卷X = 卷级；曲牌词 = 排除。

# 尖括号篇名（聊斋体例）。篇名天然短、无句读。
RE_TITLE_ANGLE = re.compile(r'^〈([^〉\n]{2,24})〉$')
# 方头括号标题（汉书/梦溪笔谈体例）。只认「像标题」的：短、无句读。
RE_TITLE_BRACK = re.compile(r'^【([^】\n]{2,24})】$')
# 书名号标题（国语体例：周語中/魯語上）。同样只认短标题。
RE_TITLE_BOOK = re.compile(r'^《([^》\n]{2,24})》$')

# 曲牌用字：这些字结尾/含有的不可能是篇章标题，是戏曲的曲牌名。
# 牡丹亭 20 个【】里 10 个是「前腔」「尹令」「北尾」这类曲牌，
# 若当篇名会把一出戏切碎成十几个碎片，正文全丢。
QUPAI_WORDS = ('前腔', '前腔换头', '尾声', '煞尾', '尾犯序', '北尾', '南尾',
               '尹令', '么篇', '幺篇', '集贤宾', '懒画眉', '江儿水', '川拨棹',
               '园林好', '忒忒令', '玉交枝', '五供养', '浆水令', '豆叶黄',
               '画眉序', '滴溜子', '鲍老催', '双声子', '啄木儿', '三段子',
               '归朝欢', '念奴娇', '好事近', '哭相思', '尾声', '红衲袄')


def _is_qupai(s):
    """是不是曲牌名（不能当篇名）。"""
    s = s.strip()
    if s in QUPAI_WORDS:
        return True
    if len(s) <= 5 and (s.endswith('令') or s.endswith('序') or s.endswith('尾')):
        return True
    return False


def _tail_concentrated(pos, n_lines, frac=0.85, thr=0.6):
    """命中位置是否集中在文件尾部（= 那是书末索引，不是正文标题）。

    为什么需要这条：同一个符号在不同书里指不同的东西，光数个数区分不出来。
    实测《古文观止》49 个「《书名》」行有 96% 落在后 15%（「本书选篇出处索引」），
    照 49 个就切，会把整本书切成 47 段引自别的书的索引条目，正文全丢。
    而《国语》21 个「《周語中》」只有 10% 在尾部，是真篇名。
    两者个数相近，只能靠位置区分。

    《史记》同理：17 个「秦本紀第五。」全在 97% 处，
    它们是太史公自序里的「作秦本紀第五。」，是篇目总结，不是正文标题。
    """
    if not pos or n_lines <= 0:
        return False
    tail = sum(1 for i in pos if i > n_lines * frac)
    return tail / len(pos) >= thr
# 目录行：篇名 + 页码（_008 / …591 / 空格 + 3位数字）
RE_TOC   = re.compile(r'^(\d{1,3})\s*[_…\.·\s]*\s*([^\d_…\n]{2,24}?)\s*$|^([^\d_…\n]{2,24}?)\s*[_…\.·]{1,}\s*(\d{1,4})\s*$')
# 纯序号行（四世同堂式）
RE_NUM   = re.compile(r'^[一二三四五六七八九十百]{1,3}$')

# 卷内「条」编号：一 / 二 … / 一O / 一一 / 一二。
# 与 RE_NUM 的区别是允许 O〇 结尾（随园诗话的 10 写作「一O」）
# 与「〇」打头的写法（「〇三易」式的符号条目是另一回事，见 RE_CIRC_ENTRY）。
# 随园诗话 1898 条，每条是一则独立诗话，是这本书真正的原子单元；
# 按「卷」切会得到 26 个 1000+ 字的巨块，检索时完全不可用。
RE_TIAO_NUM = re.compile(r'^[一二三四五六七八九十]{1,3}[O〇]?$')

# 「篇名 + [朝代]作者」体例（唐宋传奇集、古籍整理本）。
# 判据不是「短行」，是「短行 + 下一行是署名」这一对。
# 单独用短行会误伤（正文里全是短句）；加署名行做锚，误判率极低。
# 实测唐宋传奇集 56 对，篇名全对（古镜记/柳毅传/霍小玉传）。
RE_SIGN = re.compile(r'^\[?(?:唐|宋|明|清|元|漢|魏|晉|南朝|北朝|五代)\]?\s*'
                     r'[\u4e00-\u9fff·]{1,12}(?:\u2003|\s)?(?:撰|著|記)?$')
RE_NAME_LINE = re.compile(r'^[\u4e00-\u9fff·]{2,8}$')

# 曲牌起头的单元行：〔黄钟〕人月圆 卜居外家东园 / 〔双调〕骤雨打新荷。
# 这是散曲集真正的单元边界 —— 一支曲子一个单元。
# 元曲三百首 343 行，而 RE_CIRC_ENTRY 认的 273 个「○清泾浊渭：泾河水清」
# 全是句下注释，不是条目。此前误把注释当条目，切出 270 个注释片段，
# 正文与曲文全丢。
RE_QUPAI_HEAD = re.compile(r'^〔[^〕]{1,6}〕')


def _qupai_units(lines, min_n=60):
    """按〔曲牌〕起头行切单元。返回 [(篇名, 行下标)] 或 []。

    散曲/戏曲集的原子单元是一支曲子，标记就是曲牌。
    成立条件：≥60 行、去重后 ≥30% —— 同牌曲连排是常态，不能要求全不重复。
    """
    out, seen = [], set()
    for i, (_, s) in enumerate(lines):
        t = s.strip()
        if RE_QUPAI_HEAD.match(t):
            if t in seen:
                continue
            seen.add(t)
            out.append((t, i))
    if len(out) < min_n:
        return []
    if len(seen) / len(out) < 0.3:
        return []
    return out


def _title_sign_pairs(lines, min_n=15):
    """「篇名 + 署名行」成对出现的切分。返回 [(篇名, 行下标)] 或 []。"""
    out = []
    for i in range(len(lines) - 1):
        s = lines[i][1].strip()
        nx = lines[i + 1][1].strip()
        if RE_NAME_LINE.match(s) and RE_SIGN.match(nx):
            out.append((s, i))
    if len(out) < min_n:
        return []
    if len({nm for nm, _ in out}) / len(out) < 0.9:
        return []
    return out


def _numeral_unit(lines, min_units=80, min_per=2.0):
    """卷内中文序号切分。返回 [(篇名, 行下标)] 或 []。

    成立条件：
      1. 纯数字行 ≥ min_units（太少说明只是个位数的小节标记）
      2. 序号连续（允许 O/〇 混用），且每号后面至少 min_per 行正文
    为什么必须要求「连续」：正文里偶尔会有一行只写「一」的引文，
    单独出现不构成序列；连号才是排印者的编号。

    为什么不复用 numeral 模式：那个模式要求「最长递增且 ≥5」，
    但随园的编号在每卷开头重新从「一」开始，链条会断，
    且它只在全库找不到结构时才作为退路 —— 随园会先被 RE_TITLE_BOOK 截走，
    得到 26 个卷名当篇名（每卷 1000+ 字），检索粒度粗得没法用。
    """
    hits, vals = [], []
    for i, (_, s) in enumerate(lines):
        if RE_TIAO_NUM.match(s):
            v = cn2int(s.replace('O', '零').replace('〇', '零'))
            if v is None:
                continue
            hits.append((i, s, v))
            vals.append(v)
    if len(hits) < min_units:
        return []

    # 连号率：相邻两号相差 1 或「回到 1」（新卷开始）
    ok = sum(1 for a, b in zip(vals, vals[1:])
             if b == a + 1 or b == 1)
    if ok / max(1, len(vals) - 1) < 0.6:
        return []

    # 每号后面要有正文，否则是目录页的编号列
    gaps = [b[0] - a[0] for a, b in zip(hits, hits[1:])]
    if not gaps or sum(gaps) / len(gaps) < min_per:
        return []

    return [(f'第{v}条', i) for i, _, v in hits]

# 三位数字编号行（001/002/…）。
# 这是排印本给「最小独立单元」编的号，是全书最强的结构信号，
# 但**不同书的编号后跟着不同的东西**，不能一律当篇名：
#   唐诗三百首 320 个，99% 下一行就是诗题（感遇/春思/望岳）→ 真标题
#   元曲三百首 305 个，62% 是曲牌+曲题（〔黄钟〕人月圆）→ 真标题
#   神曲 223 个，只有 30% 像标题（其余是但丁原文行号）→ 不可用
#   牡丹亭 242 个，只 7% → 是行号，不可用
# 所以判据不是「有没有编号」，是「编号后面那一行像不像标题」。
RE_3DIGIT = re.compile(r'^(\d{3})$')

# 「像标题」的判据：2~30 字、不含句读（。；！？）、不像正文长句。
_TITLE_PUNCT = re.compile(r'[。；！？；]')


def _three_digit_titles(lines):
    """按三位编号切，返回 [(篇名, 行下标)]；不成立则返回 []。

    成立条件（三条同时满足，缺一不可）：
      1. 编号 ≥ 60 个 —— 少于这个数不足以当全书结构
      2. 编号后紧邻那行「像标题」的比例 ≥ 0.75 —— 低于此说明编号是行号
      3. 标题去重后数量 ≥ 编号数的一半 —— 全重复说明是曲牌内部标记

    判据 3 用「≥50%」而不是「≥85%」：元曲三百首的同牌曲会连排
    （001 与 002 都是「〔黄钟〕人月圆 卜居外家东园」），
    卡 85% 会把整本元曲判成不可切。而牡丹亭的「前腔」重复率超 90%，
    用 50% 仍能挡住。这个阈值是实测定的，不是拍的。
    """
    marks = []
    for i, (_, s) in enumerate(lines):
        m = RE_3DIGIT.match(s)
        if not m:
            continue
        j = i + 1
        while j < len(lines) and not lines[j][1].strip():
            j += 1
        if j >= len(lines):
            continue
        marks.append((m.group(1), lines[j][1].strip(), j))
    if len(marks) < 60:
        return []

    def like_title(t):
        if not (2 <= len(t) <= 30):
            return False
        if _TITLE_PUNCT.search(t):
            return False
        # 曲牌用〔〕起头，是标题不是正文；其它行带逗号即判正文
        if t.startswith('〔'):
            return True
        return '，' not in t

    good = sum(1 for _, t, _ in marks if like_title(t))
    if good / len(marks) < 0.75:
        return []
    uniq = len({t for _, t, _ in marks})
    if uniq / len(marks) < 0.5:
        return []

    return [(t, j) for _, t, j in marks if like_title(t)]

CN = '零一二三四五六七八九'


def cn2int(s):
    """中文数字转整数，覆盖 1-999，兼容底本里的三种写法。

    三种都要支持，不是冗余 —— 同一本《红楼梦》在清洗前后就有三种写法混用：
      规范式    一百一十八 → 118
      逐位式    一一八     → 118
      零位式    第一零零回 / 第一零一回 / 第一一二回  → 100 / 101 / 112
    只支持规范式时，「一一八」会累加成 8、第 100~120 回全部丢失，
    且因回号撞车被判成重复 —— 表现是「122 篇但只有 100 个回号」。
    """
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    s = s.replace('〇', '零').replace('○', '零')
    # 逐位读法：出现「零」或连续数字（无进位词）→ 按位读
    if all(ch in CN for ch in s) and ('零' in s or len(s) > 1):
        # 但「二十」「十五」这种是规范式，不能按位读
        if any(ch in '十百' for ch in s):
            pass
        else:
            v = 0
            for ch in s:
                v = v * 10 + CN.index(ch)
            return v
    total, section, num = 0, 0, 0
    for ch in s:
        if ch in CN:
            num = CN.index(ch)
        elif ch == '十':
            section += (num or 1) * 10
            num = 0
        elif ch == '百':
            section += (num or 1) * 100
            num = 0
        else:
            return None
    return total + section + num


def norm(s):
    """归一化：去所有空白（含全角），用于标题匹配。"""
    return re.sub(r'[\s\u3000\xa0]+', '', s)


def pages_of(text):
    """切成 [(页码, 文本)]。若无页标记则当作单页。"""
    parts = PAGE.split(text)
    if len(parts) < 3:
        return [(1, text)]
    return [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]


# 断字碎片：单字行，或「第」「十」「 回」这种被 PDF 抽散的编号片段。
# 实测《儒林外史》的「第十五回」在底本里是 5 行：
#   '第' / ' 十' / ' ' / '五' / ' 回'
# 若不在行层修好，RE_HUI 一条都匹配不到，整本书篇数变 56 个「第X回」空壳，
# 篇名全丢、回目只剩编号 —— 书是好的，是切不开。
_ONECHAR = re.compile(r'^[\u4e00-\u9fff、，。；：！？]{1,2}$')


def _join_broken(lins):
    """把被 PDF 抽散的单字碎行合并回整行。

    只合并「连续 3 行以上全是 1~2 字碎片」的块，且合并后总长 ≤ 40 字。
    这条约束很关键：不加它就等于把正常的短句、诗句也粘成一坨。
    实测《儒林外史》碎片块合并后正好还原成「第十五回」「葬神仙马秀才送丧」。
    """
    out, i, n = [], 0, len(lins)
    while i < n:
        pno, s = lins[i]
        if not _ONECHAR.match(s):
            out.append((pno, s))
            i += 1
            continue
        # 向前探，收集连续的碎行（允许中间夹空行，空行在 lines_of 已剔除）
        j, chunks = i, []
        while j < n and _ONECHAR.match(lins[j][1]) and sum(map(len, chunks)) < 40:
            chunks.append(lins[j][1])
            j += 1
        if len(chunks) >= 3:
            merged = ''.join(x.strip() for x in chunks)
            out.append((pno, merged))
            i = j
        else:
            out.append((pno, s))
            i += 1
    return out


def _has_digit_run(lines, need=60, maxval=999):
    """文件里有没有「001,002,003…」这样的排印单元编号序列。

    为什么必须先判这个再决定要不要保留纯数字行：
    lines_of 会把纯数字行当页码丢掉，这原本是对的 ——
    但排印本给每个最小单元编的号（唐诗 001~320、元曲 001~305）
    也被一起丢了，于是「按编号切」这条最强的结构信号根本到不了 probe。
    反过来，如果无脑保留所有数字行，页码就会混进正文。

    判据用「密度」不用「连续」：元曲的编号是跳号的
    （001…010, 012…015, 017…024，因为同牌曲合并了编号），
    最长连续只有 26，卡「连续 ≥60」会漏掉整本书。
    改用「满量程密度」：在 [1, maxval] 上实际出现 ≥ need 个不同编号，
    且最大值 ≥ 3×need。页码不会呈现这种形态（页码通常上千且更连续）。
    """
    nums = set()
    for _, s in lines:
        if re.fullmatch(r'\d{3}', s):
            nums.add(int(s))
    if len(nums) < need:
        return False
    mx = max(nums)
    if mx < need * 2:
        return False
    # 编号应从低位起排（001 起），页码式的大数字不算
    low = sum(1 for v in nums if v <= mx * 0.1)
    return low >= 5


def source_lines(text):
    """返回 (PDF 页号, 正文行, 连续块号)。同一 PDF 页可以有多个块。

    例外：存在长递增三位编号时保留这些编号行（见 _has_digit_run）。
    保留下来的编号行不会进入正文 —— join_to_paras 会把它们滤掉。
    """
    raw_lines = []
    for block, (pno, ptxt) in enumerate(pages_of(text)):
        page_lines = []
        for raw in ptxt.split('\n'):
            s = raw.strip()
            if s:
                page_lines.append((pno, s))
        raw_lines.extend((pno, s, block) for pno, s in _join_broken(page_lines))

    # 先判「原始行里有没有长递增三位编号」，再决定要不要保留。
    # 顺序不能反：若先滤掉数字行再判，永远判不出来（这里踩过一次）。
    keep_digit = _has_digit_run((pno, s) for pno, s, _ in raw_lines)

    out = []
    for pno, s, block in raw_lines:
        if re.fullmatch(r'\d{3}', s):
            if keep_digit:
                out.append((pno, s, block))
            continue
        if re.fullmatch(r'\d{1,4}', s):        # 书内页码 / 纯数字行
            continue
        out.append((pno, s, block))
    return out


def lines_of(text):
    """保留旧接口，篇界下标仍与切段共用。"""
    return [(number, line) for number, line, _ in source_lines(text)]


_FRONT_BOOKMARKS = re.compile(r'^(?:封面|封底|扉页|书名页|版权页|护封|出版说明|序|序言|前言|译序|导读|目录|目录页|封勒)$')
_DIGIT_CHAPTER_TITLE = re.compile(r'^第\s*(\d{1,4})\s*章\s+([^。！？]{1,80})$')


def _title_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value) if c.isalnum())


def _matches_page_title(page_lines, offset, key, max_lines):
    _, head, block = page_lines[offset]
    if not head or not key.startswith(head[:len(key)]):
        return False
    combined = ''
    for _, part, line_block in page_lines[offset:offset + max_lines]:
        if line_block != block:
            break
        combined += part
        if combined == key:
            return True
        suffix = combined[len(key):]
        if combined.startswith(key) and suffix.isdigit() and len(suffix) <= 2:
            return True  # Some printed headings carry a trailing note number.
        if not key.startswith(combined):
            break
    return False


def _fill_numbered_bookmark_gap(result, source):
    """Only fill a small gap between consecutive confirmed bookmarks with unique printed headings."""
    revised = [result[0]]
    for first, second in zip(result, result[1:]):
        left = _DIGIT_CHAPTER_TITLE.fullmatch(first[0])
        right = _DIGIT_CHAPTER_TITLE.fullmatch(second[0])
        if left and right and first[2] < second[2] - 1:
            low, high = int(left[1]), int(right[1])
            if 1 < high - low <= 3:
                candidates = {}
                for index in range(first[1] + 1, second[1]):
                    page, title, _ = source[index]
                    heading = _DIGIT_CHAPTER_TITLE.fullmatch(title)
                    if heading and first[2] < page < second[2] and low < int(heading[1]) < high:
                        candidates.setdefault(int(heading[1]), []).append((title, index, page))
                matches = [candidates.get(n, []) for n in range(low + 1, high)]
                if all(len(items) == 1 for items in matches):
                    additions = [items[0] for items in matches]
                    if additions == sorted(additions, key=lambda entry: entry[1]):
                        revised.extend(additions)
        revised.append(second)
    return revised


def _pdf_outline(text, layout_path):
    """目录书签还须对上目标页实际的标题，保留同名节的上级标题。"""
    if not layout_path or not PAGE.search(text) or not os.path.isfile(layout_path):
        return []
    bookmarks = []
    try:
        with open(layout_path, encoding='utf-8') as source:
            for line in source:
                if not line.strip():
                    continue
                page = json.loads(line)
                bookmarks.extend((page['page'], entry) for entry in page.get('bookmarks', []))
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if not bookmarks:
        return []
    by_page = {}
    source = source_lines(text)
    for i, (pno, content, block) in enumerate(source):
        by_page.setdefault(pno, []).append((i, _title_key(content), block))

    result, stack = [], []
    previous = -1
    expected = 0
    for number, entry in bookmarks:
        title = str(entry.get('title') or '').strip()
        level = entry.get('level')
        if not title or not isinstance(level, int) or _FRONT_BOOKMARKS.fullmatch(title):
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        key = _title_key(title)
        if not key:
            continue
        expected += 1
        page_lines = by_page.get(number, [])
        for offset, (i, _, _) in enumerate(page_lines):
            if i <= previous:
                continue
            if _matches_page_title(page_lines, offset, key, 3):
                parents = [name for _, name in stack if name != title]
                result.append((' · '.join(parents + [title]), i, number))
                previous = i
                break
        stack.append((level, title))
    # 书签与原页正文大多对不上时，保留原来的结构识别。
    if len(result) >= 2 and len(result) * 2 >= expected:
        return _fill_numbered_bookmark_gap(result, source)
    return []


_SLASH_TOC_ENTRY = re.compile(r'^([一二三四五六七八九十]+)\s+(.+?)\s*[/／]\s*(\d{1,4})$')


def _printed_outline(text):
    """Locate project headings from a printed directory, then confirm their physical pages."""
    if not PAGE.search(text):
        return []
    source = source_lines(text)
    final_page = max((pno for pno, _, _ in source), default=0)
    toc_page = next((pno for pno, line, _ in source
                     if pno <= max(12, final_page * .15) and _title_key(line) in ('目录', 'Contents')), None)
    if toc_page is None:
        return []
    entries = []
    toc_end = toc_page
    for pno, content, _ in source:
        if not toc_page <= pno <= toc_page + 2:
            continue
        match = _SLASH_TOC_ENTRY.fullmatch(content)
        if match:
            numeral, title, printed_page = match.groups()
            entries.append((cn2int(numeral), int(printed_page), ' '.join((numeral, *title.split()))))
            toc_end = pno
    if len(entries) < 3:
        return []
    numbers, printed_pages, _ = zip(*entries)
    if list(numbers) != list(range(1, len(entries) + 1)) or sorted(set(printed_pages)) != list(printed_pages):
        return []

    candidates = [(i, _title_key(content), block) for i, (pno, content, block) in enumerate(source)
                  if pno > toc_end]
    result = []
    offset = 0
    for _, _, title in entries:
        key = _title_key(title)
        while offset < len(candidates):
            index, _, _ = candidates[offset]
            matched = _matches_page_title(candidates, offset, key, 5)
            offset += 1
            if matched:
                result.append((title, index, source[index][0]))
                break
        else:
            return []
    return result


def find_toc(lines, scan=400):
    """在开头区段找目录。返回 [(篇名, 书内页码)]。
    识别依据：连续 ≥4 行带页码引用，且页码单调递增。"""
    hits = []
    for i, (pno, s) in enumerate(lines[:scan]):
        m = RE_TOC.match(s)
        if not m:
            continue
        if m.group(2):                      # 形式：008 篇名
            pg, nm = int(m.group(1)), m.group(2)
        else:                               # 形式：篇名……008
            nm, pg = m.group(3), int(m.group(4))
        nm = nm.strip(' _…·.')
        if 2 <= len(nm) <= 24:
            hits.append((i, nm, pg))
    if len(hits) < 4:
        return []
    # 取最长的一段页码递增序列
    best, cur = [], [hits[0]]
    for a, b in zip(hits, hits[1:]):
        if b[2] > a[2] and b[0] - a[0] <= 6:
            cur.append(b)
        else:
            if len(cur) > len(best):
                best = cur
            cur = [b]
    if len(cur) > len(best):
        best = cur
    if len(best) < 4:
        return []
    return [(nm, pg) for _, nm, pg in best]


def find_toc_inline(lines, scan=600):
    """连排目录：'003小引 _ 005狗·猫·鼠 _ 014阿长与《山海经》'
    一行内多条，用 _ 分隔，每条以页码开头。"""
    out = []
    for i, (pno, s) in enumerate(lines[:scan]):
        # 一行里至少 2 个「数字+篇名」片段
        ms = re.findall(r'(\d{2,4})\s*([^\d_]{2,26}?)\s*(?=_|$)', s)
        if len(ms) < 2:
            continue
        for pg, nm in ms:
            nm = nm.strip(' _…·.')
            if 2 <= len(nm) <= 26:
                out.append((nm, int(pg)))
    return out


# 人物资料框的字段行（姓名：/生卒年：/籍贯：/身份：/主要成就：）不是篇名。
# 这类行在同一本书里会重复出现（很多「物理学家、中国科学院院士」），
# 旧逻辑把它当「目录回声」，于是切出「身份：物理学家…」这种假篇名。
_BOX_FIELD = re.compile(r'^(?:姓名|生卒年|籍贯|身份|主要成就|院士语录|毕业院校|'
                        r'出生|逝世|出生地)[：:]')


def find_titles_by_echo(lines, mindist=80):
    """标题行检测（不依赖目录）：短行、无句末标点、且全文出现 2 次以上、
    两次出现的距离 > mindist。目录一次 + 正文一次，误判率极低。"""
    from collections import defaultdict
    HAN = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF]')
    pos = defaultdict(list)
    for i, (pno, s) in enumerate(lines):
        t = s.strip()
        if _BOX_FIELD.match(t):
            continue
        if not (2 <= len(t) <= 30):
            continue
        if t[-1] in '。！？；，、：）」』”…—':
            continue
        if re.search(r'[，。！？；]', t):
            continue
        # 纯汉字率过滤：排除拼音注音行（zhài / bì）、数字行、外文行
        han = len(HAN.findall(t))
        if han < 1 or han / len(t) < 0.5:
            continue
        # 排除注音标记行（音皮 / 音义）
        if re.match(r'^音[^\s]{1,4}$', t):
            continue
        pos[t].append(i)
    cand = []
    for t, idxs in pos.items():
        if len(idxs) < 2:
            continue
        # 首末距离够远才认（目录→正文）
        if idxs[-1] - idxs[0] < mindist:
            continue
        cand.append((idxs[0], t))
    cand.sort()
    return [t for _, t in cand]


def find_titles_standalone(lines, scan_head=120):
    """目录连排（无法逐条切分）时的替代方案：正文区的「孤立标题行」。

    判据（全部满足才认，宁可少认不可错认）：
      1. 行长度 2-12 字，纯汉字（≥90%）
      2. 无任何标点
      3. 前后都是长正文行
      4. 与上一标题之间至少 6 个正文行（篇不会只有几行）
      5. 全文出现次数 ≤ 3（排除「注释」这类高频行）

    纯数字行（001/002…）一律跳过 —— 它们是排印编号，不是正文，
    若让它们参与「前后是长正文行」的判断，标题会全部判不成（野草曾因此退化为 flat）。
    """
    HAN = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF]')
    from collections import Counter
    cnt = Counter(norm(s) for _, s in lines)

    def _near(i, step):
        """找 i 前后最近的一个非数字行。"""
        j = i + step
        while 0 <= j < len(lines):
            if not re.fullmatch(r'\d{1,4}', lines[j][1].strip()):
                return j
            j += step
        return None

    out = []
    last = scan_head
    for i, (pno, s) in enumerate(lines):
        if i < scan_head:
            continue
        if re.fullmatch(r'\d{1,4}', s.strip()):
            continue
        t = norm(s)
        if _BOX_FIELD.match(t):
            continue
        if not (2 <= len(t) <= 12):
            continue
        if len(HAN.findall(t)) / len(t) < 0.9:
            continue
        if re.search(r'[^\u3400-\u4DBF\u4E00-\u9FFF]', t):
            continue
        if cnt[t] > 3:
            continue
        if i - last < 6:
            continue
        pi, ni = _near(i, -1), _near(i, 1)
        prev_len = len(lines[pi][1]) if pi is not None else 0
        next_len = len(lines[ni][1]) if ni is not None else 0
        if prev_len < 20 or next_len < 20:
            continue
        out.append((t, i))
        last = i
    return out


def probe(text, name='', layout_path=None):
    """返回结构方案 dict。"""
    pdf_outline = _pdf_outline(text, layout_path)
    if pdf_outline:
        return {'mode': 'pdf_outline', 'unit': '篇', 'pdf_outline': pdf_outline,
                'pattern': 'pdf_bookmarks', 'titles': [name for name, _, _ in pdf_outline],
                'toc': [], 'toc_n': 0, 'marks': {}}
    printed_outline = _printed_outline(text)
    if printed_outline:
        return {'mode': 'pdf_outline', 'unit': '篇', 'pdf_outline': printed_outline,
                'pattern': 'printed_contents', 'titles': [name for name, _, _ in printed_outline],
                'toc': [], 'toc_n': 0, 'marks': {}}
    lines = lines_of(text)
    toc = find_toc(lines)
    inline = find_toc_inline(lines)
    if len(inline) > len(toc):
        toc = inline
        _src = 'inline'
    else:
        _src = 'page'
    n = len(lines)

    # --- 各级标记统计 ---
    stat = {'hui': 0, 'chu': 0, 'tiao': 0, 'juan': 0, 'pian': 0,
            'pianpre': 0, 'circ': 0, 'angle': 0, 'brack': 0, 'bookt': 0,
            'gua': 0}
    for _, s in lines:
        if RE_CHU.match(s):
            stat['chu'] += 1
        elif RE_HUI.match(s):
            stat['hui'] += 1
        elif RE_GUA.match(s):
            stat['gua'] += 1
        elif RE_TIAO.match(s):
            stat['tiao'] += 1
        elif RE_JUAN.match(s):
            stat['juan'] += 1
        elif RE_JUAN_NAME.match(s):
            stat['juan'] += 1
        elif RE_PIAN_AFTER.match(s):
            stat['pian'] += 1
        elif RE_PIAN_PRE.match(s):
            stat['pianpre'] += 1
        elif RE_CIRC_ENTRY.match(s):
            stat['circ'] += 1
        else:
            m = RE_TITLE_ANGLE.match(s)
            if m:
                stat['angle'] += 1
                continue
            m = RE_TITLE_BRACK.match(s)
            if m and not _is_qupai(m.group(1)):
                stat['brack'] += 1
                continue
            m = RE_TITLE_BOOK.match(s)
            if m and not _is_qupai(m.group(1)):
                stat['bookt'] += 1

    plan = {'lines': n, 'toc_n': len(toc), 'toc': toc[:400], 'toc_src': _src,
            'marks': stat, 'mode': None, 'unit': None}

    # 标题序号连续且至少三篇才接受，避免正文中的孤立编号短句。
    leading = [(i, s, RE_PIAN_LEAD.match(s)) for i, (_, s) in enumerate(lines) if RE_PIAN_LEAD.match(s)]
    numbers = [cn2int(m.group(1)) for _, _, m in leading]
    if len(numbers) >= 3 and numbers == list(range(1, len(numbers) + 1)):
        plan.update(mode='regex', unit='篇', pattern='pianlead')
        return plan

    # --- 括号类标题：最可靠的一类标记，优先于所有启发式 ---
    # 为什么放在 toc 之前：目录可能被底本撕坏（唐诗的目录就是「作者：X」），
    # 而括号是排印时人工加的，不会错。宁可相信括号，不相信目录。
    #
    # 但**必须排除「书末索引」**：同一个符号在不同书里指不同的东西。
    # 古文观止 49 个《》有 96% 落在文件尾部（「本书选篇出处索引」），
    # 若照切，全书会变成 47 段引自它书的索引条目，正文一段不剩。
    # 判据用位置集中度，不用个数 —— 两者个数相近，只有位置能分开。
    def _pos_of(pattern):
        return [i for i, (_, s) in enumerate(lines) if pattern.match(s)]

    _pa, _pb, _pk = _pos_of(RE_TITLE_ANGLE), _pos_of(RE_TITLE_BRACK), _pos_of(RE_TITLE_BOOK)

    if stat['angle'] >= 20 and not _tail_concentrated(_pa, n):
        plan['mode'] = 'regex'
        plan['unit'] = '篇'
        plan['pattern'] = 'angle'
        return plan

    if stat['brack'] >= 20 and not _tail_concentrated(_pb, n):
        plan['mode'] = 'regex'
        plan['unit'] = '篇'
        plan['pattern'] = 'brack'
        return plan

    if stat['bookt'] >= 15 and not _tail_concentrated(_pk, n):
        # 书名号若只是「卷X」（随园诗话 26 个《卷一》），说明这是卷级标记，
        # 卷内还有更细的条编号。先看卷内有没有中文序号链，有就用条级。
        _nm = _numeral_unit(lines)
        if _nm:
            plan['mode'] = 'regex'
            plan['unit'] = '条'
            plan['pattern'] = 'numunit'
            plan['numunit'] = _nm
            return plan
        plan['mode'] = 'regex'
        plan['unit'] = '篇'
        plan['pattern'] = 'bookt'
        return plan

    # --- 三位数字编号（排印本的最小单元编号）---
    # 判据在 _three_digit_titles 里：不是「有没有编号」，是「编号后那行像不像标题」。
    # 唐诗 99% 成立（编号后是诗题），牡丹亭 7% 不成立（编号是行号）。
    _td = _three_digit_titles(lines)
    if _td:
        plan['mode'] = 'regex'
        plan['unit'] = '篇'
        plan['pattern'] = 'digit3'
        plan['digit3'] = _td
        return plan

    # --- 「篇名 + 署名」成对（唐宋传奇集体例）---
    _ts = _title_sign_pairs(lines)
    if _ts:
        plan['mode'] = 'regex'
        plan['unit'] = '篇'
        plan['pattern'] = 'namepair'
        plan['namepair'] = _ts
        return plan

    # --- 判定结构模式 ---
    # 「X第一 / X第二」后置序数篇题优先于目录：
    # 论语的目录区被底本撕坏（19 条「目录」全是正文句，页码是行内序号），
    # 而正文里有 20 个真篇名（學而第一 … 堯曰第二十）。
    # 若让 toc 优先，整本论语会被切成 19 段引文，篇名全丢。
    #
    # 但**不能无条件优先**：闲情偶寄目录有 163 条（部—节两级），
    # 正文里的「科诨第五」只是二级小标题 20 个，若让 pian 抢先，
    # 全书粒度从 162 节掉到 20 部，检索粒度粗了 8 倍。
    # 判据用「目录是否明显更细」：目录 ≥ pian×3 时认为目录才是主结构。
    if stat['pian'] >= 5 and len(toc) < stat['pian'] * 3:
        _pp = _pos_of(RE_PIAN_AFTER)
        if not _tail_concentrated(_pp, n):
            plan['mode'] = 'regex'
            plan['unit'] = '篇'
            plan['pattern'] = 'pian'
            return plan

    if len(toc) >= 8:
        plan['mode'] = 'toc'
        plan['unit'] = '篇'
        return plan

    if stat['chu'] >= 8:
        plan['mode'] = 'regex'
        plan['unit'] = '出'
        plan['pattern'] = 'chu'
        return plan

    # 「第 一 卦」体例（易经）。放在 chu 之后：折/出比卦更常见，
    # 且卦名只出现在易经类书里，不会误伤。
    if stat['gua'] >= 8:
        plan['mode'] = 'regex'
        plan['unit'] = '卦'
        plan['pattern'] = 'gua'
        return plan

    if stat['hui'] >= 8:
        plan['mode'] = 'regex'
        # RE_HUI 同时匹配「第X回/章/卷/节/篇/部」。以前一律写成「回」，
        # 于是《图志》（第X章）也显示「按回切」。改成按实际命中的字取众数。
        plan['unit'] = _dominant_hui_unit(lines)
        plan['pattern'] = 'hui'
        return plan

    if stat['tiao'] >= 8:
        plan['mode'] = 'regex'
        plan['unit'] = '条'
        plan['pattern'] = 'tiao'
        return plan

    if stat['juan'] >= 6:
        plan['mode'] = 'regex'
        plan['unit'] = '卷'
        plan['pattern'] = 'juan'
        return plan

    # 后置序数篇题已在 toc 之前处理（见上），此处不再重复。

    # 前置序数短篇题（茶经「一之源」体例）。这类书篇数少但篇名极其规整，
    # 阈值取 3：茶经只有 10 篇，但短书可能只 3~4 篇。
    if stat['pianpre'] >= 3:
        plan['mode'] = 'regex'
        plan['unit'] = '篇'
        plan['pattern'] = 'pianpre'
        return plan

    # 符号体例条目（日知录 ●卷一 / ○三易、梦溪笔谈 ○条）。
    # 放在篇题之后：有明确篇名的书优先按篇切，符号条目是次选。
    # 阈值 8：这类符号偶尔出现在引文里，太少不足以当结构。
    # --- 符号体例条目 ---
    # 曲牌优先于 circ：元曲三百首的「○清泾浊渭：泾河水清」是句下注释 273 条，
    # 而〔黄钟〕人月圆… 才是 343 个真单元。若让 circ 抢先，
    # 全书会切成 270 段注释，曲文与正文全丢。
    _qp = _qupai_units(lines)
    if _qp:
        plan['mode'] = 'regex'
        plan['unit'] = '支'
        plan['pattern'] = 'qupaihead'
        plan['qupaihead'] = _qp
        return plan

    if stat['circ'] >= 8:
        plan['mode'] = 'regex'
        plan['unit'] = '条'
        plan['pattern'] = 'circ'
        return plan

    # --- 退到「孤立序号行」启发式：找最长单调递增的纯序号段 ---
    # 注意：多卷本的第 2/3 部不从「一」开始（四世同堂中册起于三十六），
    # 因此起点不限，只要求严格 +1 递增，且段长 ≥5。
    # 章节标题之间自然夹着正文，因此只在遇到「另一个序号」时判定断链，
    # 不因正文行而重置（否则第一章之后就再连不上）。
    best, cur = [], []
    nums = []
    for i, (pno, s) in enumerate(lines[:4000]):
        if RE_NUM.match(s):
            v = cn2int(s)
            if v is not None:
                nums.append((i, s, v))
    for cell in nums:
        if cur and cell[2] == cur[-1][2] + 1:
            cur.append(cell)
        else:
            if len(cur) > len(best):
                best = cur
            cur = [cell]
    if len(cur) > len(best):
        best = cur
    if len(cur) > len(best):
        best = cur
    runs = best if len(best) >= 5 else []
    if runs:
        plan['mode'] = 'numeral'
        plan['unit'] = '章'
        plan['seq'] = [(s, v) for _, s, v in runs]
        return plan

    # --- 退路一：目录回声法（标题在目录与正文各出现一次） ---
    echo = find_titles_by_echo(lines)
    if len(echo) >= 5:
        plan['mode'] = 'echo'
        plan['unit'] = '篇'
        plan['titles'] = echo
        return plan

    # --- 退路二：正文孤立标题行（目录连排、切不开时） ---
    solo = find_titles_standalone(lines)
    if len(solo) >= 4:
        plan['mode'] = 'solo'
        plan['unit'] = '篇'
        plan['titles'] = [t for t, _ in solo]
        plan['solo_idx'] = [i for _, i in solo]
        return plan

    plan['mode'] = 'flat'
    plan['unit'] = '部'
    return plan


# 回目对句行：篇名被拆成「第X回」+ 两句对仗。
# 实测《儒林外史》每回是：
#   '第十五回' / '葬神仙马秀才送丧' / '思父母匡童生尽孝'
# 只取标题行会得到 57 个「第X回」空壳，篇名信息全丢。
# 判据不是「下一行是什么」，而是「下一行像不像回目」：
# 纯中文（可含全角空格与间隔号）8~34 字、不含句末标点、不是标题。
# 长度上限放到 34 是实测值：红楼梦「賈雨村夤緣复舊職　林黛玉拋父進京都」是 16 字（含全角空格），
# 「甄士隱夢幻識通靈　賈雨村風塵怀閨秀」也是 16 字；三国回目最长达 20 字。
_REPAIR_LINE = re.compile(r'^[\u4e00-\u9fff、，·　\u3000]{5,34}$')
_HEAD_LINE = re.compile(r'^第[一二三四五六七八九十百零〇0-9]{1,4}[回章节卷篇出折幕]')


def _merge_title(lines, i, head, max_extra=2):
    """把「第X回」与紧邻的回目对句合并成一个篇名。

    只动 head 本身，不改行下标 —— 行下标是切段依据，
    改了索引就错位（这是本项目踩过的坑：索引只能有一个数据源）。
    所以这里只返回「更好的篇名」，i 原样传出。
    """
    parts = [head]
    for k in range(1, max_extra + 1):
        if i + k >= len(lines):
            break
        nxt = lines[i + k][1]
        if _HEAD_LINE.match(nxt) or not _REPAIR_LINE.match(nxt):
            break
        # 对句一般成双；合并到够长就停
        parts.append(nxt)
        if len(''.join(parts)) >= 20:
            break
    return '　'.join(parts)


_REPHEAD = re.compile(r'^(第[一二三四五六七八九十百零〇0-9]{1,4}[回章卷篇部节])')


def _drop_phantom(heads):
    """同号重复时去掉「后面没有正文」的那一个。

    heads: [(篇名, 行下标, 页码)]，需已按行下标升序。
    判据：一个真章节到下一个章节之间应有实际内容；
    假标题常出现在目录区，紧跟着就是下一个标题。
    """
    if not heads:
        return heads
    # 同号分组（只对带「第X回」形态的篇名做，符号体例不参与）
    groups = {}
    for k, (nm, i, p) in enumerate(heads):
        m = _REPHEAD.match(nm)
        if not m:
            continue
        groups.setdefault(m.group(1), []).append(k)
    drop = set()
    for key, ks in groups.items():
        if len(ks) < 2:
            continue
        # 每个候选到「下一个不同标题」的行距
        spans = []
        for k in ks:
            nxt = heads[k + 1][1] if k + 1 < len(heads) else None
            spans.append((-(nxt - heads[k][1]) if nxt else -10**9, k))
        # 间距最大的保留，其余丢弃（只丢前 len(ks)-1 个，保留一个）
        spans.sort()
        for _, k in spans[:-1]:
            drop.add(k)
    return [h for k, h in enumerate(heads) if k not in drop]


def outline(text, plan):
    """按方案返回 [(篇名, 起始行下标, PDF 文件页码)]。"""
    mode = plan['mode']
    if mode == 'pdf_outline':
        return plan['pdf_outline']
    lines = lines_of(text)

    if mode == 'regex':
        # 三位编号是预计算好的位置表，不走通用匹配
        if plan.get('pattern') == 'digit3':
            return [(nm, i, lines[i][0]) for nm, i in plan.get('digit3', [])]
        if plan.get('pattern') == 'namepair':
            return [(nm, i, lines[i][0]) for nm, i in plan.get('namepair', [])]
        if plan.get('pattern') == 'qupaihead':
            return [(nm, i, lines[i][0]) for nm, i in plan.get('qupaihead', [])]
        # 卷内条编号：篇名要带卷名，否则 26 个卷各有「第1条」会撞车
        if plan.get('pattern') == 'numunit':
            cur_juan = ''
            out = []
            jmap = {i: s for i, (_, s) in enumerate(lines)
                    if RE_TITLE_BOOK.match(s) or RE_JUAN.match(s)}
            for nm, i in plan.get('numunit', []):
                for j in range(i, -1, -1):
                    if j in jmap:
                        cur_juan = jmap[j]
                        break
                out.append((f'{cur_juan}·{nm}' if cur_juan else nm, i, lines[i][0]))
            return out
        pat = {'chu': RE_CHU, 'hui': RE_HUI, 'tiao': RE_TIAO,
               'juan': RE_JUAN, 'pian': RE_PIAN_AFTER,
               'pianpre': RE_PIAN_PRE, 'pianlead': RE_PIAN_LEAD, 'circ': RE_CIRC_ENTRY,
               'angle': RE_TITLE_ANGLE, 'brack': RE_TITLE_BRACK,
               'bookt': RE_TITLE_BOOK, 'gua': RE_GUA}.get(plan.get('pattern'))
        # 「卷之一梁惠王上」用专属正则；它比 RE_JUAN 更具体，二者互斥
        if plan.get('pattern') == 'juan':
            pat = re.compile(r'^(?:卷[一二三四五六七八九十]{1,3}(?:\s|$)|'
                             r'卷之[一二三四五六七八九十]{1,2}[\u4e00-\u9fff]{1,8}$)')
        out, seen = [], set()
        has_pages = bool(PAGE.search(text))
        for i, (pno, s) in enumerate(lines):
            if not pat or not pat.match(s):
                continue
            # 括号类：篇名取括号内的字，去掉符号本身
            if plan.get('pattern') in ('angle', 'brack', 'bookt'):
                nm = pat.match(s).group(1).strip()
                if plan.get('pattern') == 'brack' and _is_qupai(nm):
                    continue
                if nm in seen:
                    continue
                seen.add(nm)
                out.append((nm, i, pno))
                continue
            if s not in seen:
                seen.add(s)
                prefix = _REPHEAD.match(s)
                full_heading = bool(has_pages and prefix and len(s[prefix.end():].strip()) > 1)
                out.append((s if full_heading else _merge_title(lines, i, s), i, pno))
        # 同号重复去伪：目录区被底本撕坏时会出现「假标题」。
        # 实测《儒林外史》第 13 回，底本把回目撕成两行挂在目录区（行 78），
        # 正文里（行 1411）又完整出现一次。两处都被收 → 57 篇里有 1 个重复。
        # 判据不用位置猜，用「后面还有多少正文」：
        # 真章节后面跟着整回内容，假标题后面紧跟下一个标题。
        # 因此同号重复时保留「到下一个标题间距更大」的那次。
        if plan.get('pattern') in ('hui', 'chu', 'juan'):
            out = _drop_phantom(heads=out)
        return out

    if mode == 'numeral':
        want = {v for _, v in plan['seq']}
        out = []
        for i, (pno, s) in enumerate(lines):
            if RE_NUM.match(s):
                v = cn2int(s)
                if v in want:
                    out.append((f'第{v}章', i, pno))
        # 去重保序
        ded, seen = [], set()
        for nm, i, p in out:
            key = cn2int(nm[1:-1])
            if key in seen:
                continue
            seen.add(key)
            ded.append((nm, i, p))
        return ded

    if mode == 'toc':
        # 用目录名去正文里找第一个「整行等于篇名」的位置
        idx_by_name = {}
        for i, (pno, s) in enumerate(lines):
            idx_by_name.setdefault(norm(s), i)
        out = []
        for nm, pg in plan['toc']:
            i = idx_by_name.get(norm(nm))
            if i is None:                     # 容忍带编号前缀
                for j, (pno, s) in enumerate(lines):
                    ns = norm(s)
                    if ns.endswith(norm(nm)) and len(ns) <= len(norm(nm)) + 8:
                        i = j
                        break
            if i is not None:
                out.append((nm, i, lines[i][0]))
        out.sort(key=lambda x: x[1])
        # 去重（同名只留第一次出现）
        ded, seen = [], set()
        for nm, i, p in out:
            if nm in seen:
                continue
            seen.add(nm)
            ded.append((nm, i, p))
        return ded

    if mode == 'solo':
        out = []
        for nm, i in zip(plan['titles'], plan['solo_idx']):
            out.append((nm, i, lines[i][0]))
        return out

    if mode == 'echo':
        # 标题的首次出现是目录，第二次才是正文；取第 2 次起
        from collections import defaultdict
        pos = defaultdict(list)
        for i, (pno, s) in enumerate(lines):
            pos[norm(s)].append(i)
        out = []
        for nm in plan['titles']:
            idxs = pos.get(norm(nm), [])
            if len(idxs) >= 2:
                out.append((nm, idxs[1], lines[idxs[1]][0]))
        out.sort(key=lambda x: x[1])
        return out

    return []


if __name__ == '__main__':
    import io, glob, os, json
    RAW = P.RAW
    for f in sorted(glob.glob(RAW + '/*.txt')):
        b = os.path.basename(f)[:-4]
        if b.startswith('_'):
            continue
        t = io.open(f, encoding='utf-8', errors='replace').read()
        p = probe(t, b)
        o = outline(t, p)
        print(f"{b[:22]:24s} mode={p['mode']:<8s} unit={p['unit']:<3s} "
              f"toc={p['toc_n']:>3d} hui={p['marks']['hui']:>3d} chu={p['marks']['chu']:>3d} "
              f"tiao={p['marks']['tiao']:>2d} → 骨架 {len(o):>3d} 个")
        if o:
            print(f"    {' | '.join(x[0] for x in o[:6])}")
