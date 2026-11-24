# -*- coding: utf-8 -*-
"""上传前预检：选完文件就把书名 / 作者 / 出版社认出来。

为什么要有这一步：
  - 之前只从文件名去扩展名当书名，作者、出版社全靠手打；手打就会把
    「黑龙江科学技术出版社」打成「黑龙江科学科技出版社」。
  - PDF 的封面页其实写着书名、作者、出版社，docx 还有文档属性，
    这些都能在读文件时顺手拿到，没理由让人再抄一遍。
  - 提前显示页数和抽样页的文字情况，方便确认文件是否选对。

只读文件，不写书库，不动引擎。
"""
import os
import re
import unicodedata

import ingest

HAN = ingest.HAN

# 封面页上不是书名、也不该被当成人名/社名的行
_NOISE = ('谨以此书', '献给', '内容简介', '作者简介', '序言', '前言', '目录',
          '图书在版编目', '责任编辑', '封面设计', '定价', 'ISBN', '开本',
          '印张', '字数', '版次', '印次', '书号', '编目数据', '版本说明',
          '版权页', '出版说明', '扉页')

# 「张三 编著」「李四 主编」这类署名
_AUTHOR_RE = re.compile(
    r'^([\u4e00-\u9fa5·]{2,12})\s*(编著|主编|著|编|撰|译|等编著|等主编)$')
# 「作者：张三」「编著 张三」
_AUTHOR_LABEL_RE = re.compile(
    r'^(?:作者|编著|主编|著者)\s*[:：]\s*([\u4e00-\u9fa5·]{2,12})$')
# 出版社：一家出版机构的名字一定以这些词收尾；集团/公司 是「社名」的另一种后缀
_PUB_TOKEN_RE = re.compile(
    r'[\u4e00-\u9fa5A-Za-z·]{2,24}?(?:出版社|出版(?:传媒)?集团|出版公司|书局|印书馆|书店)')
_PUB_LABEL = re.compile(r'^(?:出版发行|出版|发行|出版社)\s*[:：]?')
# 目录页的一行：「小王子 001」「第一章 012」——末尾的数字是页码，不是书名的一部分
_TOC_LINE = re.compile(r'^(.{1,30}?)\s+(\d{1,4})$')
# 章节/杂项标记，不能当书名
_SECTION = re.compile(
    r'^(?:导读|序言?|前言|后记|附录|目录|contents|版权页?|扉页|出版说明|'
    r'译序|引言|正文|正文部分|目次|图书在版编目)\s*\d*$', re.I)
# 「年德文版序言」这类目录行：以「序言/序/目录」收尾的短行
_SECTION_TAIL = re.compile(r'(?:版序言|序言|导言|目\s*录|目\s*次)$')
# 「·石家庄·」「·北京·」这类只标出版地的行
_PLACE_LINE = re.compile(r'^[·•・]\s*[^·•・]{1,12}\s*[·•・]$')
# 尾页（版权页）里提到「根据…译本」的句子，不是本书出版社
_TAIL_SOURCE = re.compile(r'(根据|译出|原版|英译本|法文版|参考|转引|摘自|节选)')
# 文件名里的工序后缀：「小王子-内文.pdf」「XX_终稿.pdf」
_STEM_SUFFIX = re.compile(
    r'(?:[-_—·\s]*(?:内文|正文|印刷文件|印刷|终稿|定稿|校对|排版|文件|'
    r'副本|final|print|copy|v\d+))+$', re.I)
_STEM_JUNK = re.compile(r'(扫描件|未命名|新建文档|document|scan|无标题|untitled|全文)', re.I)
# 版权/扉页的署名行：「〔法〕圣埃克苏佩里 著」「某某 编绘」「某某 译」
# 这些词出现在「书名」候选里，说明它是序言/章节标题，不是书名
_WEAK_TITLE = re.compile(r'(故事|序言|前言|后记|导读|纪念|写在|关于|致读者|出版说明|编后记)')
_CREDIT_RE = re.compile(
    r'^(?:[〔\[（(][^〕\]）)]{0,10}[〕\]）)]\s*)?'
    r'([\u4e00-\u9fa5·]{2,20})\s*(?:著|编著|编绘|主编|编写|译)(?:\s|$)')

# PDF 属性里常见的垃圾值
_META_JUNK = ('untitled', 'microsoft word', 'microsoft powerpoint', 'adobe',
              'indesign', 'document', '无标题', '未命名', '新建')


def _han(s):
    return len(HAN.findall(s or ''))


def _nfkc_han(s):
    """只把兼容汉字/康熙部首（⽂、⾔）换成标准汉字，不碰（）这类全角标点。

    直接 NFKC 会把「（上册）」变成「(上册)」，书名就变了样。
    """
    out = []
    for ch in str(s or ''):
        o = ord(ch)
        if 0x2E80 <= o <= 0x2FDF or 0xF900 <= o <= 0xFAFF:
            out.append(unicodedata.normalize('NFKC', ch))
        else:
            out.append(ch)
    return ''.join(out)


def _clean(s):
    s = re.sub(r'\s+', ' ', str(s or ''))
    s = re.sub(r'^[#>\s]+', '', s)          # markdown 标题 / 引用符
    return s.strip(' 　:：-—_')


def _usable_title(s):
    """PDF 属性里的 Title 常常是 'Microsoft Word - 报告.doc'，这种不能要。"""
    s = _clean(s)
    if not s or len(s) > 60:
        return ''
    low = s.lower()
    if any(j in low for j in _META_JUNK):
        return ''
    if _han(s) < 2:
        return ''
    return s


_JUNK_PERSON = {'administrator', 'admin', 'user', 'owner', 'pc', 'lenovo',
                'dell', 'acer', 'hp', 'windows 用户', '微软用户', 'unknown'}


def _usable_person(s):
    s = _clean(s)
    if not s or len(s) > 40:
        return ''
    low = s.lower()
    if low in _JUNK_PERSON:
        return ''
    if 'administrator' in low or low.startswith(('microsoft', 'adobe', 'wps')):
        return ''
    if any(j in low for j in _META_JUNK):
        return ''
    if re.fullmatch(r'[\w.+-]+@[\w.-]+', s):     # 邮箱当作者
        return ''
    return s


_STEM_ASCII_PAREN = re.compile(
    r'\s*[\(（]\s*(?:z-library|zlibrary|libgen|1|2|3|4|5|副本|copy|'
    r'扫描版|影印版|ocr版?|校对版|试读)\s*[\)）]\s*$', re.I)
_STEM_AUTHOR_PAREN = re.compile(r'^(.{2,40}?)\s*[\(（]([^\)）]{2,24})[\)）]\s*$')
# 「河北廉洁故事-郭忠.pdf」：短横线后面如果是 2~4 个汉字且不是「本/版/卷…」，当作者
_STEM_DASH_AUTHOR = re.compile(r'^(.{2,30}?)\s*[-—_]+\s*([\u4e00-\u9fa5·]{2,4})$')
_TITLE_SUFFIX_STOP = re.compile(r'(本|版|卷|册|集|篇|部|稿|校|注|释|译|编|著|文|选|全)$')


def _clean_stem(stem):
    """文件名 → 书名候选。

    去掉「-内文」「_终稿」「(1)」「(Z-Library)」「（马克思，恩格斯）」这类后缀；
    最后一个括号如果是人名（含逗号顿号、或以「等」收尾），交给调用方当作者。
    """
    s = _nfkc_han(str(stem or '')).strip()
    for _ in range(3):
        t = _STEM_ASCII_PAREN.sub('', s)
        m = _STEM_AUTHOR_PAREN.match(t)
        if m and _han(m.group(1)) >= 2 and (
                re.search(r'[，,、]', m.group(2)) or m.group(2).endswith('等')):
            t = m.group(1)
        if t == s:
            break
        s = t
    s = _STEM_SUFFIX.sub('', s)
    m = _STEM_DASH_AUTHOR.match(s)
    if m and not _TITLE_SUFFIX_STOP.search(m.group(2)):
        s = m.group(1)
    return s.strip(' -_—·')


def _stem_author(stem):
    """从文件名的作者括注里取作者：「共产党宣言 (马克思，恩格斯)」。"""
    s = _nfkc_han(str(stem or '')).strip()
    for _ in range(3):
        s2 = _STEM_ASCII_PAREN.sub('', s)
        if s2 == s:
            break
        s = s2
    m = _STEM_AUTHOR_PAREN.match(s)
    if m and _han(m.group(1)) >= 2 and (
            re.search(r'[，,、]', m.group(2)) or m.group(2).endswith('等')):
        return m.group(2).strip()
    m = _STEM_DASH_AUTHOR.match(s)
    if m and not _TITLE_SUFFIX_STOP.search(m.group(2)):
        return m.group(2).strip()
    return ''


def _strip_suffix(s):
    return re.sub(r'\.(txt|md|markdown|docx|pdf)$', '', str(s or ''), flags=re.I)


def _collapse_doubled(s):
    """方正飞翔做「加粗」时会把每个字画两遍：「浙浙江江少少年…」。

    逐对检查，80% 以上成对重复才合并，避免误伤「人人」「一一」这类正常词。
    """
    s = str(s or '')
    if len(s) < 6:
        return s
    pairs = [(s[i], s[i + 1]) for i in range(0, len(s) - 1, 2)]
    if pairs and sum(1 for a, b in pairs if a == b) >= len(pairs) * 0.8:
        return s[::2]
    return s


def _prep_lines(text):
    """清洗 + 去叠字 + 竖排合并。

    竖排页（封面、扉页）每个字单独一行：陈/晋/主/编/俞/静/波…
    连续 3 行以上的单字先拼回一行，作者、社名才认得出来。
    """
    raw = [_clean(x) for x in _nfkc_han(text or '').splitlines()]
    raw = [_collapse_doubled(x) for x in raw if x]
    out, buf = [], []
    for s in raw:
        if len(s) == 1 and _han(s) == 1:
            buf.append(s)
            continue
        if len(buf) >= 3:
            out.append(''.join(buf))
        elif buf:
            out.extend(buf)
        buf = []
        out.append(s)
    if len(buf) >= 3:
        out.append(''.join(buf))
    elif buf:
        out.extend(buf)
    return out


_PUB_STOP = re.compile(
    r'^(?:全国|国家|全省|全市|本|该)?(?:优秀|百佳|先进|一级|二级|十佳)?出版社$')


def _norm_pub(t):
    t = re.sub(r'(?:股份有限公司|有限责任公司|有限公司)$', '', str(t or '').strip())
    return t.strip(' 　:：-—·')


def _pub_tokens(line):
    """一行里所有像出版社的名字。"""
    return [_norm_pub(m.group(0)) for m in _PUB_TOKEN_RE.finditer(line or '')]


def _accept_pub_line(line, tail=False):
    """这行的出版社名可不可信。

    正文里也会出现「某某出版社」：「法国著名的伽利玛出版社在…」。
    只有当这一行本身像版权页时才收：
      行首就是社名 / 以「出版发行」开头 / 含 ISBN、--、社名+地址 / 社名后跟年份。
    """
    t = line.strip()
    if not t:
        return False
    if _TAIL_SOURCE.search(t):
        return False
    toks = [x for x in _pub_tokens(t) if '的' not in x]
    if not toks:
        return False
    if re.search(r'[。！？；]', t):        # 句子，不是版权页
        return False
    if t.endswith(('在', '的', '了', '是', '中', '上', '下', '与', '和', '及', '等', '为', '对')):
        return False
    # 行首（允许「出版发行」这类标签）就是社名。
    # 版权页常排成「出 版 天津人民出版社」「出 版 人 刘 庆」，字间有空格，先压掉空格再判。
    head = _PUB_LABEL.sub('', re.sub(r'[ \t\u3000]+', '', t)).strip()
    if any(head.startswith(x) for x in toks):
        return True
    if re.search(r'出版发行|ISBN|\bISBN\b', t):
        return True
    if re.search(r'出版社\s*[（(]', t):
        return True
    if re.search(r'出版社\s*[，,]\s*\d{4}', t):
        return True
    if re.search(r'(?:--|—|－)\s*[^，。]{0,20}[：:]', t):
        return True
    return False


_CIP_AUTHOR_RE = re.compile(
    r'([\u4e00-\u9fa5·]{2,20}(?:[，、][\u4e00-\u9fa5·]{2,20})*)'
    r'(?:[（(][^）)]{0,30}[）)])?\s*(?:著|编著|主编)')


def _find_cip_author(text):
    """版权页/在版编目里的作者：「(英) 罗伯特·戴博德著」「（法）圣埃克苏佩里著」。"""
    for raw in (text or '').splitlines():
        s = _clean(raw)
        if not s or len(s) > 60:
            continue
        m = _CIP_AUTHOR_RE.search(s)
        if not m:
            continue
        name = m.group(1).strip(' 　，、')
        if 2 <= _han(name) <= 24:
            return name
    return ''


_CIP_PUB_RE = re.compile(r'出版(?:发行)?\s*[:：]?\s*([\u4e00-\u9fa5A-Za-z·]{2,24}?出版社)')
_CIP_PUB_RE2 = re.compile(r'([\u4e00-\u9fa5A-Za-z·]{2,24}?出版社)\s*[,，]\s*(?:19|20)\d{2}')


def _cip_publisher(text):
    """版权页里的出版社：兼容「出 版 天津人民出版社」「天津:天津人民出版社,2022.5」。

    版权页的社名经常被排版拆行（「天津人\n民出版社, 2022.5」），所以先压掉空白再匹配。
    """
    flat = re.sub(r'[ \t\u3000]+', '', text or '')
    for pat in (_CIP_PUB_RE, _CIP_PUB_RE2):
        for m in pat.finditer(flat):
            name = _norm_pub(m.group(1))
            if 2 <= len(name) <= 30 and name.endswith('出版社'):
                return name
    return ''


def _find_publisher(text, tail=False):
    """从一段文字里找出版社。出版社（社）优先于出版集团（集团）。"""
    shi, grp = [], []
    for s in _prep_lines(text):
        if not s or len(s) > 80:
            continue
        if not _accept_pub_line(s, tail):
            continue
        for t in _pub_tokens(s):
            if _PUB_STOP.match(t):
                continue
            if t.endswith('出版社'):
                shi.append(t)
            else:
                grp.append(t)
    if shi:
        return shi[0]
    return grp[0] if grp else ''


def _guess_from_text(text):
    """从封面页/首页文字里认书名/作者/出版社。认不出就留空。"""
    title = author = ''
    toc_title = ''
    lines = _prep_lines(text)
    for s in lines[:60]:
        flat = s.replace(' ', '')
        if _PLACE_LINE.match(s):
            continue
        if _SECTION.match(flat):
            continue
        if len(s) <= 16 and _SECTION_TAIL.search(flat):
            continue
        m = _TOC_LINE.match(s)
        if m:
            # 封面是图片时，目录页往往是唯一有字的地方：「小王子 001」
            left = m.group(1).strip()
            if (not toc_title and _han(left) >= 2
                    and not _SECTION.match(left.replace(' ', ''))):
                toc_title = left
            continue
        # 竖排合并出来的署名行：「陈晋主编俞静波等编写」
        if not author:
            # 竖排合并行才走这条：短、无标点。「少膑副主编.--石家庄…」是版权页，
            # 句子里也有「主编」两字，不能当署名。
            m = re.match(r'^([\u4e00-\u9fa5]{2,4})(?:等)?(?:主编|编著|编写|著)', s)
            if m and len(s) <= 24 and not re.search(r'[，。；：、,.;:（）()\[\]—\-]', s):
                author = m.group(1)
                continue
        # 署名行：这是作者，不是书名
        if not author:
            m = _CREDIT_RE.match(s)
            if m:
                author = m.group(1)
                continue
        if not author:
            m = _AUTHOR_RE.match(s)
            if m:
                author = m.group(1)
                continue
            m = _AUTHOR_LABEL_RE.match(s)
            if m:
                author = m.group(1)
                continue
        if not title and len(s) <= 60:
            if any(s.startswith(n) for n in _NOISE):
                continue
            if re.search(r'出品|策划|监制|责任编辑|装帧|印刷|出版发行|版权', s):
                continue
            if re.search(r'CIP|核字|ISBN|版本馆|数据核字', s):
                continue
            if _AUTHOR_RE.match(s) or _CREDIT_RE.match(s) or _pub_tokens(s):
                continue
            # 正文句子不是书名：带逗号/句号的长行一律跳过。
            # 封面是图片时，翻到第 4、5 页就是正文；不拦会把正文首句当书名。
            if len(s) > 40 or re.search(r'[，。；！？,;!?]', s):
                continue
            if re.search(r'[〔\[（(]', s):
                continue
            # 纯编号、纯英文、纯标点的不当书名
            if _han(s) < 2:
                continue
            title = s.strip('《》「」『』')
    publisher = _find_publisher('\n'.join(lines[:60]))
    return title, author, publisher, toc_title


def _read_pdf(path, head_pages=5):
    """只读前几页 + 抽样几页，不做全文抽取。

    500 MB 的图册整本抽一次要一两分钟；预检必须几秒内出结果。
    """
    try:
        import pdfplumber
    except Exception as e:
        raise ingest.IngestError('服务器未安装 pdfplumber，暂时不能预检 PDF（%s）。' % e)
    info = {'pages': 0, 'meta': {}, 'text': '', 'head_text': '', 'front_text': '',
            'tail_text': '', 'sampled': 0, 'sample_han': [], 'sample_chars': []}
    try:
        with pdfplumber.open(path) as pdf:
            n = len(pdf.pages)
            info['pages'] = n
            md = pdf.metadata or {}
            info['meta'] = {k: (md.get(k) or '') for k in
                            ('Title', 'Author', 'Subject', 'Creator', 'Producer')}
            idx = list(range(min(head_pages, n)))
            # 再抽 10% / 50% / 90% 三页，判断「只有封面有字」的假文本型 PDF
            if n > 12:
                for p in (0.1, 0.5, 0.9):
                    i = int(n * p)
                    if i not in idx:
                        idx.append(i)
            texts = []
            head, front = [], []
            for i in idx:
                t = pdf.pages[i].extract_text() or ''
                if i < 3:            # 封面/扉页/目录：只用来认书名
                    head.append(t)
                if i < head_pages:
                    texts.append(t)
            info['text'] = '\n'.join(texts)
            info['head_text'] = '\n'.join(head)
            for i in range(min(8, n)):      # 扉页/版权页常在第 4~8 页
                try:
                    front.append(pdf.pages[i].extract_text() or '')
                except Exception:
                    pass
            info['front_text'] = '\n'.join(front)
            # 版权页通常在最后两页：书店/网店版 PDF 常把 CIP 放在末尾
            tail = []
            for i in range(max(0, n - 2), n):
                try:
                    tail.append(pdf.pages[i].extract_text() or '')
                except Exception:
                    pass
            info['tail_text'] = '\n'.join(tail)
            for i in idx:
                t = pdf.pages[i].extract_text() or ''
                info['sample_han'].append(_han(t))
                info['sample_chars'].append(len(t.strip()))
            info['sampled'] = len(idx)
    except Exception as e:
        raise ingest.IngestError('PDF 打不开：%s' % e)
    return info


def _read_docx(path):
    try:
        from docx import Document
    except Exception as e:
        raise ingest.IngestError('服务器未安装 python-docx，暂时不能预检 docx（%s）。' % e)
    try:
        doc = Document(path)
    except Exception as e:
        raise ingest.IngestError('docx 打不开：%s' % e)
    cp = doc.core_properties
    paras = []
    for p in doc.paragraphs[:60]:
        t = p.text.strip()
        if t:
            paras.append(t)
    return {'pages': 0,
            'meta': {'Title': cp.title or '', 'Author': cp.author or '',
                     'Subject': cp.subject or ''},
            'text': '\n'.join(paras[:25])}


def _read_text(path, limit=65536):
    with open(path, 'rb') as fp:
        raw = fp.read(limit)
    try:
        text = ingest._decode_bytes(raw)
    except Exception:
        text = raw.decode('utf-8', 'replace')
    return {'pages': 0, 'meta': {}, 'text': text}


def _pick_title(fmt, stem, p_title, toc_title, meta_title, first_src):
    """书名优先级：封面标题 → 文件名 → 目录页 → 文档属性。

    封面页经常是整页图片（抽不到字），或者只抽到「导读 01」这种目录条目；
    这时文件名反而更准（小王子-内文.pdf → 小王子）。
    """
    cover_ok = bool(p_title) and _han(p_title) >= 2
    stem_ok = (bool(stem) and 2 <= _han(stem) <= 40
               and not _STEM_JUNK.search(stem))
    # 封面抽到的若是「…创作故事」「序言」这类小标题，可信度低
    cover_weak = cover_ok and bool(_WEAK_TITLE.search(p_title))

    def _core(t):
        return re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', t)[:4]

    if fmt in ('txt', 'md'):
        if stem_ok:
            return stem, '文件名'
        if p_title:
            return p_title, first_src
        if meta_title:
            return meta_title, '文档属性'
        return '', ''

    if cover_ok and not cover_weak:
        # 文件名与封面指向同一本书（共享前四个字）时，用文件名——它常带分卷/版次
        if (stem_ok and _core(p_title) and _core(p_title) in stem
                and len(p_title) < len(stem) <= len(p_title) + 16):
            return stem, '文件名（补全分卷）'
        return p_title, first_src
    if stem_ok:
        return stem, '文件名'
    if cover_ok:
        return p_title, first_src
    if stem_ok:
        return stem, '文件名'
    if toc_title:
        return toc_title, '目录页'
    if meta_title:
        return meta_title, 'PDF 属性'
    if p_title:
        return p_title, first_src
    return '', ''


def probe_file(path, fmt, filename):
    """返回预检结果。字段缺失一律给空串，前端据此决定填不填。"""
    size = os.path.getsize(path)
    max_mb = ingest.MAX_BYTES // 1024 // 1024
    stem = _strip_suffix(os.path.basename(filename or ''))

    pages = 0
    meta = {}
    text = ''
    scanned = False
    warnings = []

    if fmt == 'pdf':
        raw = _read_pdf(path)
        pages, meta, text = raw['pages'], raw['meta'], raw['text']
        sample = raw.get('sample_han') or []
        if sample and sum(1 for h in sample if h < 10) == len(sample):
            scanned = True
            warnings.append('抽样页读到的中文很少，可能含扫描页。入库时会尝试识别读不到文字的页面。使用前请对照原页。')
        elif sample and 2 * sum(1 for h in sample if h < 10) > len(sample):
            warnings.append('多数抽样页读到的中文很少，正文可能夹着扫描页。入库结果可在任务记录查看。')
        if pages and size / max(1, pages) > 600 * 1024:
            warnings.append('文件平均每页 %.1f MB，处理大图页可能需要更多时间。'
                            % (size / 1024 / 1024 / pages))
    elif fmt == 'docx':
        raw = _read_docx(path)
        meta, text = raw['meta'], raw['text']
    else:
        raw = _read_text(path)
        meta, text = raw['meta'], raw['text']

    first_src = '封面页' if fmt in ('pdf', 'docx') else '文首'
    head_text = raw.get('head_text') or text
    p_title, _pa, _pp, toc_title = _guess_from_text(head_text)
    # 作者与出版社再看宽一点（前 8 页）：扉页、版权页常在第 4~8 页
    _, p_author, p_publisher, _ = _guess_from_text(raw.get('front_text') or head_text)
    if not p_author:
        p_author = _pa
    # 来源标注：只在前 3 页找到的叫封面页，4~8 页找到的叫扉页
    p_author_src = first_src if p_author == _pa else '扉页'
    p_pub_src = first_src if p_publisher == _pp else '扉页'
    meta_title = _usable_title(meta.get('Title'))
    meta_author = _usable_person(meta.get('Author'))
    stem_clean = _clean_stem(stem)
    stem_author = _stem_author(stem)
    # 封面/版权页都没写社名时，再翻最后两页（CIP 数据常在末尾）
    p_tail_author = ''
    if raw.get('tail_text'):
        if not p_publisher:
            p_publisher = _find_publisher(raw['tail_text'], tail=True)
            p_pub_src = '版权页'
        elif not p_publisher.endswith('出版社'):
            tail_pub = _find_publisher(raw['tail_text'], tail=True)
            if tail_pub.endswith('出版社'):
                p_publisher, p_pub_src = tail_pub, '版权页'
        if not p_publisher:
            cip_pub = _cip_publisher(raw['tail_text'])
            if cip_pub:
                p_publisher, p_pub_src = cip_pub, '版权页'
        elif not p_publisher.endswith('出版社'):
            cip_pub = _cip_publisher(raw['tail_text'])
            if cip_pub:
                p_publisher, p_pub_src = cip_pub, '版权页'
        p_tail_author = _find_cip_author(raw['tail_text'])

    title, title_src = _pick_title(fmt, stem_clean, p_title, toc_title, meta_title, first_src)

    author, author_src = '', ''
    if p_author:
        author, author_src = p_author, p_author_src
    elif stem_author:
        author, author_src = stem_author, '文件名'
    elif p_tail_author:
        author, author_src = p_tail_author, '版权页'
    elif meta_author:
        author, author_src = meta_author, 'PDF 属性'

    publisher, publisher_src = '', ''
    if p_publisher:
        publisher, publisher_src = p_publisher, p_pub_src

    text_info = {'chars': len(text), 'han': _han(text)}
    if fmt == 'pdf' and not scanned:
        est = 0
        if raw.get('sample_chars'):
            est = int(sum(raw['sample_chars']) / max(1, len(raw['sample_chars'])) * pages)
        text_info['est_chars'] = est

    if size > 100 * 1024 * 1024:
        warnings.append('文件 %.0f MB，上传和读取可能需要一些时间。' % (size / 1024 / 1024))

    return {
        'ok': True,
        'format': fmt,
        'bytes': size,
        'max_mb': max_mb,
        'pages': pages,
        'title': title, 'title_source': title_src,
        'author': author, 'author_source': author_src,
        'publisher': publisher, 'publisher_source': publisher_src,
        'scanned': scanned,
        'text': text_info,
        'warnings': warnings,
    }
