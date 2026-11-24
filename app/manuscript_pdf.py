"""Typeset a frozen project export as a printable Chinese A4 manuscript."""

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import re
from threading import Lock
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import textsplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, TableStyle
from reportlab.platypus import paragraph as paragraph_layout


# ReportLab's CJK list is Japanese-oriented and omits several Chinese closing
# marks. Both its plain and rich-text wrapping paths need the same extension.
_CHINESE_LINE_END_MARKS = '，。；：？！、）》】〕〉”’％'
for _layout in (textsplit, paragraph_layout):
    _layout.ALL_CANNOT_START += ''.join(
        mark for mark in _CHINESE_LINE_END_MARKS if mark not in _layout.ALL_CANNOT_START)


_FONT_LOCK = Lock()
_FONT_DIR = Path(__file__).resolve().parent / 'fonts'
_INK = '#24334D'
_BLUE = '#294D79'
_MUTED = '#50647E'
_RULE = '#D9E3EF'
_WASH = '#F1F5FA'
_HEADING = re.compile(r'^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$')
_LIST = re.compile(r'^( *)([-+*]|\d+[.)])[ \t]+(.+)$')
_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})')
_INLINE = re.compile(r'\*\*([^*]+)\*\*|`([^`]+)`|\[(S[1-9]\d*)\]|\[([^\]]+)\]\((https?://[^\s)]+)\)')


@lru_cache(maxsize=16)
def _load_font(path, index):
    name = 'ProjectPDF-' + sha256(f'{path}:{index}'.encode()).hexdigest()[:12]
    with _FONT_LOCK:
        try:
            return pdfmetrics.getFont(name)
        except KeyError:
            font = TTFont(name, path, subfontIndex=index)
            pdfmetrics.registerFont(font)
            return font


def _typefaces(text):
    custom = os.environ.get('BOOKDISTILL_PDF_FONT')
    # Embed the same bundled, openly licensed fonts on every operating system.
    # Never depend on a developer's home directory or an OS font installation.
    candidates = [(str(_FONT_DIR / 'NotoSansSC-Regular.ttf'), 0,
                   str(_FONT_DIR / 'NotoSansSC-Bold.ttf'))]
    if custom:
        candidates.insert(0, (os.path.expanduser(custom), 0, None))
    required = {ord(char) for char in text if char.isprintable()}
    fewest_missing = required
    for path, index, bold_path in candidates:
        if not Path(path).is_file():
            continue
        try:
            face = _load_font(path, index)
        except (OSError, TTFError):
            continue
        missing = required.difference(face.face.charToGlyph)
        if len(missing) < len(fewest_missing):
            fewest_missing = missing
        if missing:
            continue
        bold = face
        if bold_path and Path(bold_path).is_file():
            try:
                alternate = _load_font(bold_path, index)
                if required.issubset(alternate.face.charToGlyph):
                    bold = alternate
            except (OSError, TTFError):
                pass
        with _FONT_LOCK:
            pdfmetrics.registerFontFamily(face.fontName, normal=face.fontName, bold=bold.fontName)
        return face.fontName, bold.fontName
    if fewest_missing != required:
        examples = ' '.join(map(chr, sorted(fewest_missing)[:6]))
        raise ValueError('PDF 字体缺少稿件中的字形（例如 %s）。请配置覆盖这些字符的 TrueType 字体。' % examples)
    raise ValueError('PDF 缺少项目内置中文字体。请补齐 app/fonts 中的字体文件，或配置 BOOKDISTILL_PDF_FONT。')


def _inline(text):
    parts = []
    end = 0
    for match in _INLINE.finditer(text):
        parts.append(escape(text[end:match.start()]))
        bold, code, citation, label, url = match.groups()
        if bold:
            parts.append('<b>' + _inline(bold) + '</b>')
        elif code:
            parts.append(escape(code))
        elif citation:
            parts.append('<font color="%s">[%s]</font>' % (_BLUE, citation))
        else:
            safe_url = escape(url, {'"': '&quot;'})
            parts.append('<link href="%s" color="%s">%s</link>（%s）' %
                         (safe_url, _BLUE, escape(label), escape(url)))
        end = match.end()
    parts.append(escape(text[end:]))
    return ''.join(parts)


def _split_table_row(line):
    return [cell.strip().replace(r'\|', '|') for cell in re.split(r'(?<!\\)\|', line.strip().strip('|'))]


def _table_at(lines, index):
    if index + 1 >= len(lines) or '|' not in lines[index]:
        return None
    cells = _split_table_row(lines[index])
    rules = _split_table_row(lines[index + 1])
    if len(cells) < 2 or len(cells) != len(rules) or not all(re.fullmatch(r':?-{3,}:?', rule) for rule in rules):
        return None
    rows = [cells]
    end = index + 2
    while end < len(lines) and '|' in lines[end]:
        row = _split_table_row(lines[end])
        if len(row) != len(cells):
            break
        rows.append(row)
        end += 1
    return rows, end


def _table_flowables(rows, width, body, bold):
    if len(rows[0]) > 6 or any(len(cell) > 1200 for row in rows for cell in row):
        return [Paragraph('<b>%s</b>：%s' % (_inline(key), _inline(value)), body)
                for row in rows[1:] for key, value in zip(rows[0], row)] or [
                    Paragraph(' / '.join(map(_inline, rows[0])), body)]
    cell = ParagraphStyle('ProjectPdfCell', parent=body, fontSize=9.5, leading=15, spaceAfter=0)
    head = ParagraphStyle('ProjectPdfCellHeading', parent=cell, fontName=bold, textColor=_BLUE)
    values = [[Paragraph(_inline(value), head if i == 0 else cell) for value in row] for i, row in enumerate(rows)]
    # Split at the page boundary first; splitting whole rows first can repeat a
    # header again at the bottom of the same page when the remainder is retried.
    table = LongTable(values, colWidths=[width / len(rows[0])] * len(rows[0]), repeatRows=1,
                      splitByRow=0, splitInRow=1,
                      hAlign='LEFT', spaceBefore=4, spaceAfter=11)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(_WASH)),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFD')]),
        ('GRID', (0, 0), (-1, -1), 0.45, colors.HexColor(_RULE)),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return [table]


def _story(text, font, bold, width):
    body = ParagraphStyle('ProjectPdfBody', fontName=font, fontSize=10.8, leading=18, wordWrap='CJK',
                          textColor=_INK, spaceAfter=7, allowWidows=0, allowOrphans=0,
                          rightIndent=12)  # Reserve room for CJK hanging punctuation inside the frame.
    title = ParagraphStyle('ProjectPdfTitle', parent=body, fontName=bold, textColor=_BLUE,
                           fontSize=23, leading=32, spaceAfter=12, keepWithNext=True)
    headings = [ParagraphStyle('ProjectPdfHeading%d' % level, parent=body, fontName=bold, textColor=_BLUE,
                               fontSize=size, leading=size + 8, spaceBefore=before, spaceAfter=5,
                               keepWithNext=True)
                for level, (size, before) in enumerate([(18, 16), (16, 14), (13, 9), (11.5, 7), (11, 6), (11, 6)])]
    quote = ParagraphStyle('ProjectPdfQuote', parent=body, fontSize=10, leading=16, textColor=_MUTED,
                           leftIndent=12, rightIndent=5, backColor=_WASH, borderPadding=5,
                           spaceBefore=3, spaceAfter=10)
    meta = ParagraphStyle('ProjectPdfMetadata', parent=body, fontSize=9.5, textColor=_MUTED)
    listing = [ParagraphStyle('ProjectPdfList%d' % i, parent=body, leftIndent=15 + i * 13,
                              bulletIndent=i * 13, spaceAfter=4) for i in range(4)]
    lines = text.expandtabs(4).splitlines()
    story = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip():
            continue
        heading, item, fence = _HEADING.match(line), _LIST.match(line), _FENCE.match(line)
        if heading:
            level = len(heading[1])
            story.append(Paragraph(_inline(heading[2]), title if not story and level == 1 else headings[level - 1]))
        elif item:
            bullet = '•' if item[2] in '-+*' else item[2]
            story.append(Paragraph(_inline(item[3]), listing[min(3, len(item[1]) // 2)], bulletText=bullet))
        elif fence:
            block = []
            while i < len(lines):
                close = _FENCE.match(lines[i])
                if close and close[1].startswith(fence[1]) and not lines[i][close.end():].strip():
                    i += 1
                    break
                block.append(escape(lines[i]).replace(' ', '&#160;') or '&#160;')
                i += 1
            if block:
                story.append(Paragraph('<br/>'.join(block), quote))
        elif line.startswith('>'):
            quoted = [line[1:].removeprefix(' ')]
            while i < len(lines) and lines[i].startswith('>'):
                quoted.append(lines[i][1:].removeprefix(' '))
                i += 1
            story.append(Paragraph('<br/>'.join(_inline(part) or '&#160;' for part in quoted), quote))
        elif line.startswith('版本：') and len(story) == 1:
            story.append(Paragraph(_inline(line), meta))
        else:
            table = _table_at(lines, i - 1)
            if table:
                rows, i = table
                story.extend(_table_flowables(rows, width, body, bold))
                continue
            paragraph = [_inline(line)]
            while (i < len(lines) and lines[i].strip() and not lines[i].startswith('>') and
                   not _HEADING.match(lines[i]) and not _LIST.match(lines[i]) and
                   not _FENCE.match(lines[i]) and not _table_at(lines, i)):
                paragraph.append(_inline(lines[i]))
                i += 1
            story.append(Paragraph('<br/>'.join(paragraph), body))
    return story


def _social_note_story(text, font, bold, width):
    from marketing_delivery import headings

    sections = headings(text)
    production = next((h for h in sections if h['level'] == 4 and h['title'] == '配图制作'), None)
    if not production:
        return _story(text, font, bold, width)
    cards = [h['start'] for h in sections if h['start'] >= production['body_start'] and
             h['level'] == 5 and re.match(r'第 \d+ 张 · ', h['title'])]
    if not cards:
        return _story(text, font, bold, width)
    # Keep each card's instructions with its heading when it fits on a page.
    starts = [production['start'], *cards[1:], len(text)]
    return _story(text[:starts[0]], font, bold, width) + [
        KeepTogether(_story(text[start:end], font, bold, width))
        for start, end in zip(starts, starts[1:])]


def _booktalk_story(text, font, bold, width):
    from marketing_delivery import headings

    sections = [h for h in headings(text) if h['level'] == 4 and h['title'] in ('讲述正文', '提词与翻页')]
    if [h['title'] for h in sections] != ['讲述正文', '提词与翻页']:
        return _story(text, font, bold, width)
    divider = sections[1]['start']
    return _story(text[:divider], font, bold, width) + [KeepTogether(_story(text[divider:], font, bold, width))]


def render_export_pdf(snapshot):
    """Render frozen text and its display metadata without looking up live project state."""
    text = snapshot.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('稿件快照没有可导出的正文。')
    info = snapshot.get('export') or {}
    production = None
    if info.get('content_kind') == 'visual_production':
        import production_pdf
        candidate = snapshot.get('production_document')
        if production_pdf.valid_document(candidate):
            production = candidate
    mode = '已审核交付稿' if info.get('mode') == 'approved' else '审阅稿'
    revision = info.get('project_revision')
    stamp = str(info.get('created_at') or '').replace('T', ' ')[:16]
    details = ' · '.join(filter(None, (f'项目版本 {revision}' if revision is not None else '', stamp)))
    brand = '书世界 · 项目稿件'
    if info.get('content_kind') == 'channel_content':
        channel_names = {'公众号': '公众号文章', '短视频': '短视频脚本', '小红书': '小红书笔记',
                         '达人讲书': '讲书稿', '书店活动': '活动方案'}
        channels = info.get('channels') or []
        mode = channel_names.get(channels[0], '营销内容') if len(channels) == 1 else '营销内容'
        if info.get('mode') != 'approved':
            mode += ' · 待审核'
        details, brand = stamp, '书世界'
    if info.get('content_kind') == 'marketing_plan':
        mode = '营销方案' + (' · 待审核' if info.get('mode') != 'approved' else '')
        details, brand = stamp, '书世界'
    if info.get('content_kind') == 'visual_production':
        presentation = {'image': '图片展示', 'video': '视频展示'}.get(info.get('presentation_mode'), '画面制作')
        mode = ('旧版 · ' if info.get('stale') else '') + presentation + '-制作包'
        if production:
            mode = ('旧版 · ' if info.get('stale') else '') + (production.get('title') or '画面制作包')
        details, brand = stamp, '书世界'
    font_check = production_pdf.font_text(production) if production else text
    font, bold = _typefaces('\n'.join((font_check, mode, details, brand, '• 第 0123456789 页 （）：/')))

    buffer = BytesIO()
    title = str(snapshot.get('filename') or '项目稿件').removesuffix('.md')
    class ProductionDocTemplate(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            bookmark = getattr(flowable, 'production_bookmark', None)
            if bookmark:
                key, label = bookmark
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(label, key, level=0, closed=False)

    template = ProductionDocTemplate if production else SimpleDocTemplate
    doc = template(buffer, pagesize=A4, leftMargin=53, rightMargin=53, topMargin=64,
                            bottomMargin=60, title=title, author='书世界', subject=mode, invariant=1)
    doc.production_section = '口播稿' if production and production.get('narration') else ''
    doc.production_section_first_page = 1

    def page_frame(canvas, page_doc):
        left, right = page_doc.leftMargin + 6, A4[0] - page_doc.rightMargin - 6
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor(_RULE))
        canvas.setLineWidth(0.6)
        canvas.line(left, A4[1] - 44, right, A4[1] - 44)
        canvas.line(left, 43, right, 43)
        canvas.setFillColor(colors.HexColor(_MUTED))
        canvas.setFont(font, 9)
        page_brand = brand
        if production and getattr(page_doc, 'production_section', None):
            page_brand += ' · ' + page_doc.production_section
            if (page_doc.production_section_first_page is not None and
                    page_doc.page > page_doc.production_section_first_page):
                page_brand += ' · 续'
        canvas.drawString(left, A4[1] - 34, page_brand)
        canvas.setFont(bold, 9)
        canvas.setFillColor(colors.HexColor(_BLUE if info.get('mode') == 'approved' or
                                            info.get('content_kind') == 'visual_production' and not info.get('stale') else '#80591E'))
        canvas.drawRightString(right, A4[1] - 34, mode)
        canvas.setFont(font, 8.5)
        canvas.setFillColor(colors.HexColor(_MUTED))
        canvas.drawString(left, 29, details)
        canvas.drawRightString(right, 29, '第 %d 页' % page_doc.page)
        canvas.restoreState()

    if production:
        story = production_pdf.story(production, font, bold, doc.width - 12)
    elif info.get('content_kind') == 'channel_content' and info.get('channels') == ['小红书']:
        story = _social_note_story(text, font, bold, doc.width - 12)
    elif info.get('content_kind') == 'channel_content' and info.get('channels') == ['达人讲书']:
        story = _booktalk_story(text, font, bold, doc.width - 12)
    else:
        story = _story(text, font, bold, doc.width - 12)
    doc.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return buffer.getvalue()
