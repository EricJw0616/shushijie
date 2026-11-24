# -*- coding: utf-8 -*-
"""Read uploaded books, preserving PDF page numbers and recognition sources."""
import io
import os
import re

import pdf_ocr

HAN = re.compile('[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF'
                 '\U00020000-\U0002FA1F]')

ALLOWED = {'.txt': 'txt', '.md': 'md', '.markdown': 'md',
           '.docx': 'docx', '.pdf': 'pdf'}
# 单本图册动辄 500 MB+，100 MB 的老上限挡掉的是真实书稿。
# 上限可用环境变量改；解析是本机顺序读，不按文件大小吃内存的只有上传那一段
# （server 边收边写盘），抽文字时内存约为文件的 2～3 倍。
MAX_BYTES = int(os.environ.get('BOOKDISTILL_MAX_UPLOAD_MB', '1024')) * 1024 * 1024
_PDF_TEXT_HELP = '请上传清晰的 PDF、Word（.docx）或 TXT。'


class IngestError(ValueError):
    def __init__(self, message, *, page_issues=None):
        super().__init__(message)
        self.page_issues = page_issues


class OCRProcessingError(IngestError):
    """The original PDF can be reused when local recognition becomes available."""


def fmt_of(filename):
    ext = os.path.splitext(str(filename or ''))[1].lower()
    if ext not in ALLOWED:
        raise IngestError('暂不支持这种文件格式（%s）。%s' % (ext or '没有文件后缀', _PDF_TEXT_HELP))
    return ALLOWED[ext]


def han_count(text):
    return len(HAN.findall(text or ''))


def _score_text(s):
    if not s:
        return -1
    h = han_count(s)
    bad = s.count('\ufffd')
    return h - bad * 50


def _decode_bytes(data):
    """中文书常见 UTF-8 / GB18030。按「汉字数 - 替换符」选最优，不盲信第一个。"""
    best, best_score = '', -1
    for enc in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'big5', 'utf-16'):
        try:
            s = data.decode(enc)
        except Exception:
            continue
        score = _score_text(s)
        if score > best_score:
            best, best_score = s, score
    if best_score < 0:
        raise IngestError('这份文本打不开。请用文本编辑器打开后，另存为 UTF-8 的 TXT 再上传。')
    return best


def _normalize(text):
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\u3000', ' ').replace('\ufeff', '')
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', ' ', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    return text.strip() + '\n'


def _md_to_text(text):
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'~~~.*?~~~', '', text, flags=re.S)
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'^\s{0,3}#{1,6}\s*', '', text, flags=re.M)
    text = re.sub(r'^\s{0,3}>\s?', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*_]{3,}\s*$', '', text, flags=re.M)
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    return text


def _docx_text(path):
    try:
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception as e:
        raise IngestError('暂时无法读取 Word 文件。请稍后重试，或将正文另存为 TXT 上传。') from e
    try:
        doc = Document(path)
    except Exception as e:
        raise IngestError('这份 Word 文件打不开。请确认能正常打开，再另存为 .docx 后上传。') from e
    parts = []
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag == qn('w:p'):
            t = Paragraph(child, doc).text.strip()
            if t:
                parts.append(t)
        elif child.tag == qn('w:tbl'):
            table = Table(child, doc)
            for row in table.rows:
                cells = [c.text.strip().replace('\n', ' ') for c in row.cells]
                line = ' | '.join([c for c in cells if c])
                if line:
                    parts.append(line)
    return '\n'.join(parts)


def _clean_pdf_lines(text):
    out = []
    for line in (text or '').splitlines():
        s = line.strip()
        if not s:
            out.append('')
            continue
        if re.match(r'^[-—–\s]*\d{1,4}[-—–\s]*$', s):
            continue
        if re.match(r'^第\s*\d+\s*页(\s*[/／]\s*共?\s*\d+\s*页)?$', s):
            continue
        if re.match(r'^Page\s+\d+(\s+of\s+\d+)?$', s, re.I):
            continue
        # cupsfilter / 一些 PDF 导出器会插页标记，不能当正文。
        if re.match(r'^<<<\s*PAGE\s+\d+\s*>>>$', s, re.I):
            continue
        if re.match(r'^\[\[?\s*PAGE\s+\d+\s*\]?\]?$', s, re.I):
            continue
        out.append(line)
    return '\n'.join(out)


def _atlas():
    """引擎里的版面模块。ingest 要在服务器进程里也能用，所以按路径找，不靠包名。"""
    import sys as _sys
    here = os.path.dirname(os.path.abspath(__file__))
    eng = os.path.join(os.path.dirname(here), 'platform', 'engine')
    if eng not in _sys.path:
        _sys.path.insert(0, eng)
    import atlas as AT
    return AT


def _pdf_pages(path):
    try:
        import pdfplumber
    except Exception as e:
        raise IngestError('暂时无法读取 PDF。请稍后重试，或改用 Word（.docx）或 TXT。') from e
    pages = []
    try:
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                try:
                    native = page.extract_text_lines(return_chars=False)
                except Exception:
                    native = []
                pages.append({'page': number, 'w': page.width, 'h': page.height,
                              'lines': [{'t': line['text'], 'k': 'body', 'col': 0,
                                         'x0': line['x0'], 'x1': line['x1'], 'top': line['top']}
                                        for line in native if _clean_pdf_lines(line['text']).strip()]})
                page.flush_cache()
    except Exception as e:
        raise IngestError('这份 PDF 打不开。请确认文件完整、没有密码，再上传。') from e
    if not pages:
        raise IngestError('PDF 没有页面。')
    return pages


def _pdf_page_issues(pages):
    issues = {}
    for page in pages:
        status = (page.get('ocr') or {}).get('status')
        if status and status != 'body':
            issues.setdefault(status, []).append(page['page'])
        for key in ('layout_review', 'non_body'):
            if page.get(key):
                issues.setdefault(key, []).append(page['page'])
    return issues


def extract(path, fmt, on_progress=None, on_layout_progress=None):
    """返回 {text, pages, chars, format, note}。"""
    try:
        size = os.path.getsize(path)
    except Exception:
        raise IngestError('文件不存在或不可读。')
    if size <= 0:
        raise IngestError('空文件。')
    if size > MAX_BYTES:
        raise IngestError('文件超过 %d MB 上限。' % (MAX_BYTES // 1024 // 1024))
    pages = 0
    layout = None
    layout_note = ''
    ocr = {}
    page_issues = None
    if fmt in ('txt', 'md'):
        with io.open(path, 'rb') as fp:
            raw = fp.read()
        text = _decode_bytes(raw)
        if fmt == 'md':
            text = _md_to_text(text)
    elif fmt == 'docx':
        text = _docx_text(path)
    elif fmt == 'pdf':
        AT = _atlas()
        try:
            layout = AT.layout_pdf(path, on_progress=on_layout_progress)
        except Exception:
            layout = _pdf_pages(path)
            layout_note = '，版面读取采用整页文字，复杂页面请核对原文'
        if not layout:
            raise IngestError('PDF 没有页面。')
        pages = len(layout)
        ocr = pdf_ocr.recover_pages(path, layout, AT, on_progress)
        page_issues = _pdf_page_issues(layout)
        text = AT.pages_to_text(layout, mark_pages=True)
        if not ocr and han_count(text) < 200 and not layout_note:
            text = AT.pages_to_text(_pdf_pages(path), mark_pages=True)
            layout_note = '，版面读取采用整页文字，复杂页面请核对原文'
            layout = []
        tables = sum(len(page.get('tables') or []) for page in layout)
        layout_note += '，保留 PDF 页码'
        if tables:
            layout_note += '，另外保存 %d 个表格' % tables
        labels = {'no_text': '未读到可用文字', 'review': '扫描文字待核对', 'layout_review': '阅读顺序待核对',
                  'failed': '扫描识别未完成', 'unavailable': '扫描识别暂不可用',
                  'blank': '为空白页', 'non_body': '归入卷末书目等非正文'}
        summary = ['%d 页%s' % (len(page_issues[key]), label) for key, label in labels.items()
                   if page_issues.get(key)]
        if summary:
            layout_note += '。' + '，'.join(summary)
        elif not ocr:
            layout_note += '。本次使用 PDF 原有文字'
    else:
        raise IngestError('未知格式：%s' % fmt)
    text = _normalize(text)
    body = re.sub(r'^<<<PAGE \d+>>>\s*$', '', text, flags=re.M) if fmt == 'pdf' else text
    h = han_count(body)
    body_chars = len(re.sub(r'\s', '', body))
    if h < 200 and ocr.get('unavailable'):
        raise OCRProcessingError('PDF 需要识别图中的文字，本机识别暂不可用。恢复后可以用原文件重试。',
                                 page_issues=page_issues)
    if h < 200 and ocr.get('failed'):
        raise OCRProcessingError('PDF 的图片文字没有识别完，可以用原文件重试。', page_issues=page_issues)
    if body_chars >= 200 and h / body_chars < 0.25:
        raise IngestError('这份文件读到的中文正文太少，暂时无法生成标签。以外文为主的文件可以先上传中文正文。',
                          page_issues=page_issues)
    if h < 200:
        if ocr.get('blank') == pages:
            raise IngestError('PDF 的页面都是空白，请核对并上传包含正文的文件。', page_issues=page_issues)
        if ocr:
            raise IngestError('PDF 中读到的中文正文少于 200 字，无法生成标签。请上传画面清楚、正文完整的版本。',
                              page_issues=page_issues)
        raise IngestError('读到的中文正文少于 200 字，暂时无法生成标签。请上传包含完整正文的版本。',
                          page_issues=page_issues)
    # 句读缺失：PDF 抽丢标点的典型症状；这种文本判型与引文都不可信。
    ends = len(re.findall(r'[。！？!?]', body))
    if ends == 0:
        raise IngestError('没有读到分隔句子的标点，无法准确生成标签。请上传带标点的正文。', page_issues=page_issues)
    if len(body) / max(1, ends) > 150:
        raise IngestError('读取后的句子异常长，标点可能在排版中丢失了。请核对原书，或改用 Word（.docx）或 TXT 上传。',
                          page_issues=page_issues)
    note = (f'已检查 PDF {pages:,} 页{layout_note}。' if fmt == 'pdf'
            else f'读取 {h:,} 个汉字。')
    return {'text': text, 'pages': pages, 'chars': len(body),
            'han': h, 'format': fmt, 'note': note, 'layout': layout, 'ocr': ocr, 'page_issues': page_issues}


def write_layout(path, pages):
    """保留 PDF 的文字位置、目录书签和单独识别出的表格。"""
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = __import__('tempfile').mkstemp(dir=os.path.dirname(path), prefix='.tmp-')
    with os.fdopen(fd, 'w', encoding='utf-8') as fp:
        for p in pages:
            fp.write(json.dumps(p, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = __import__('tempfile').mkstemp(dir=os.path.dirname(path), prefix='.tmp-')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(text)
    os.replace(tmp, path)
