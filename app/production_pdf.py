"""Readable handoff pages for saved image and video instructions.

Only presentation happens here: prompts and narration come from the frozen
generation, never from the current project or another generation request.
"""

import math
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import ActionFlowable, HRFlowable, KeepTogether, Paragraph


INK = '#24334D'
BLUE = '#294D79'
MUTED = '#62738B'
RULE = '#D9E3EF'
WASH = '#F4F7FC'
_PROMPT_LABELS = re.compile(
    r'^(最终观众|统一视觉风格|受众表达安排|书内对象或观点|呈现性质|空间安排|'
    r'画面要求|参考素材要求|参考要求|衔接方式|衔接|运镜|主体|构图|风格|画幅|'
    r'\d+(?:\.\d+)?\s*[–—~～-]\s*\d+(?:\.\d+)?\s*秒)[：:]')


class SectionPageBreak(ActionFlowable):
    """Set the running label before a forced page break, including continuations."""
    def __init__(self, title):
        super().__init__(())
        self.title = title

    def apply(self, doc):
        doc.production_section = self.title
        doc.production_section_first_page = doc.page + 1
        doc.handle_pageBreak()


class RunningSection(ActionFlowable):
    """Name a short closing section without spending a page only on a few steps."""
    def __init__(self, title):
        super().__init__(())
        self.title = title

    def apply(self, doc):
        doc.production_section = self.title
        doc.production_section_first_page = None


def valid_document(document):
    """Do not replace a readable legacy document with a partial structured one."""
    return (isinstance(document, dict) and document.get('presentation_mode') in ('image', 'video')
            and isinstance(document.get('shots'), list) and bool(document['shots'])
            and all(isinstance(shot, dict) and isinstance(shot.get('prompt'), str)
                    and bool(shot['prompt'].strip()) for shot in document['shots']))


def font_text(document):
    """Include structured-only characters in the existing font coverage check."""
    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    return '\n'.join(strings(document)) + '\n口播稿 画面风格 画面提示词 图片制作包 视频制作包 参考图 制作顺序 对应口播 后期文字 图片 视频 观众 画幅 全片位置 时长 按顺序制作画面，再配口播和字幕。完整录制一次。用于第张镜共段续。'


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _plain(value):
    # Prompts are executable text, not Markdown to reinterpret. Escaping also
    # protects ReportLab's XML parser from model/user supplied angle brackets.
    return escape(str(value)).replace('\n', '<br/>')


def _paragraphs(value, style, labels=False):
    result = []
    for block in re.split(r'\n[ \t]*\n', value):
        if not block.strip():
            continue
        safe = _plain(block)
        if labels:
            match = _PROMPT_LABELS.match(block)
            if match:
                safe = '<b>' + _plain(match[0]) + '</b>' + _plain(block[match.end():])
        result.append(Paragraph(safe, style))
    return result


def _seconds(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return '%g' % value
    return ''


def story(document, font, bold, width):
    body = ParagraphStyle('ProductionBody', fontName=font, fontSize=11, leading=18.5,
                          wordWrap='CJK', textColor=INK, spaceAfter=8,
                          allowWidows=0, allowOrphans=0,
                          rightIndent=12)  # Keep CJK hanging punctuation within the printable column.
    title = ParagraphStyle('ProductionTitle', parent=body, fontName=bold, textColor=BLUE,
                           fontSize=23, leading=32, spaceAfter=13, keepWithNext=True)
    section = ParagraphStyle('ProductionSection', parent=body, fontName=bold, textColor=BLUE,
                             fontSize=17, leading=25, spaceBefore=17, spaceAfter=9,
                             keepWithNext=True)
    shot_title = ParagraphStyle('ProductionShotTitle', parent=title, fontSize=20,
                                leading=28, spaceAfter=13)
    small = ParagraphStyle('ProductionSmall', parent=body, fontSize=9.7, leading=15.5,
                           textColor=MUTED, spaceAfter=7)
    kicker = ParagraphStyle('ProductionKicker', parent=small, fontName=bold,
                            textColor=BLUE, spaceAfter=6, keepWithNext=True)
    label = ParagraphStyle('ProductionLabel', parent=body, fontName=bold, textColor=BLUE,
                           fontSize=10.3, leading=16, spaceBefore=10, spaceAfter=5,
                           keepWithNext=True)
    prompt = ParagraphStyle('ProductionPrompt', parent=body, fontSize=10.5, leading=17.2,
                            spaceAfter=8)
    quoted = ParagraphStyle('ProductionNarrationExcerpt', parent=small, textColor=INK,
                            leftIndent=9, rightIndent=9, backColor=WASH,
                            borderPadding=7, spaceBefore=4, spaceAfter=12)
    narration = ParagraphStyle('ProductionNarration', parent=body, leftIndent=25,
                               bulletIndent=0, spaceAfter=9, leading=19.5)
    numbered = ParagraphStyle('ProductionStep', parent=body, leftIndent=18,
                              bulletIndent=0, spaceAfter=9)
    result = []

    def heading(text, style, key=None):
        p = Paragraph(_plain(text), style)
        if key:
            p.production_bookmark = (key, text)
        result.append(p)

    mode = document['presentation_mode']
    unit = '张' if mode == 'image' else '镜'
    package_title = _text(document.get('title')) or ('图片制作包' if mode == 'image' else '视频制作包')
    topic = _text(document.get('topic'))
    if topic:
        heading(package_title, kicker)
        heading(topic, title, 'production-overview')
    else:
        heading(package_title, title, 'production-overview')
    book_titles = [s for s in map(_text, document.get('book_titles') or []) if s]
    if book_titles:
        result.append(Paragraph(_plain('、'.join('《%s》' % s.strip('《》') for s in book_titles)), small))
    metadata = []
    if _text(document.get('audience')):
        metadata.append('观众：' + document['audience'])
    if _text(document.get('aspect_ratio')):
        metadata.append('画幅：' + document['aspect_ratio'])
    metadata.append('%d %s画面' % (len(document['shots']), unit))
    result.append(Paragraph(_plain('  /  '.join(metadata)), small))
    result.append(HRFlowable(width=width, thickness=0.6, color=colors.HexColor(RULE),
                             spaceBefore=4, spaceAfter=12))
    rows = document.get('narration') or []
    result.append(Paragraph('按顺序制作画面，再配口播和字幕。' if rows else '按顺序制作画面。', small))
    if _text(document.get('visual_style')):
        heading('画面风格', label)
        result.extend(_paragraphs(document['visual_style'], body))
    if rows:
        heading('口播稿', section, 'production-narration')
        result.append(Paragraph('完整录制一次。', small))
        for row in rows:
            if not isinstance(row, dict) or not _text(row.get('text')):
                continue
            number = row.get('number')
            result.append(Paragraph(_plain(row['text']), narration,
                                    bulletText=str(number).zfill(2) if number is not None else None))

    for index, shot in enumerate(document['shots'], 1):
        number = shot.get('number', index)
        result.append(SectionPageBreak('第 %s %s' % (number, unit)))
        heading('第 %s %s / 共 %s %s' % (number, unit, len(document['shots']), unit), kicker)
        shot_name = _text(shot.get('title'))
        # A legacy label such as “第 1 段” does not describe a shot. Its number
        # remains in the kicker rather than being presented as a second title.
        if not shot_name or re.fullmatch(r'第\s*\d+\s*[段张镜]', shot_name):
            shot_name = '图片提示词' if mode == 'image' else '视频提示词'
        heading(shot_name, shot_title, 'production-shot-%s' % index)
        result[-1].production_bookmark = ('production-shot-%s' % index,
                                          '第 %s %s · %s' % (number, unit, shot_name))
        timing = shot.get('timing') or {}
        timing_meta = []
        duration = _seconds(shot.get('duration_seconds'))
        start, end = _seconds(timing.get('global_start_seconds')), _seconds(timing.get('global_end_seconds'))
        if mode == 'video':
            if duration:
                timing_meta.append('时长：%s 秒' % duration)
            if start and end:
                timing_meta.append('全片位置：%s-%s 秒' % (start, end))
        if timing_meta:
            result.append(Paragraph(_plain('  /  '.join(timing_meta)), small))
        source_numbers = shot.get('source_numbers') or []
        excerpt = _text(shot.get('source_text'))
        if excerpt or source_numbers:
            heading('对应口播' + (' · 第 %s 段' % '、'.join(map(str, source_numbers)) if source_numbers else ''), label)
            if excerpt:
                result.extend(_paragraphs(excerpt, quoted))
        if _text(shot.get('overlay_text')):
            result.append(Paragraph('<b>后期文字：</b>' + _plain(shot['overlay_text']), small))
        heading('画面提示词', label)
        result.extend(_paragraphs(shot['prompt'], prompt, labels=True))

    references, steps = document.get('references') or [], document.get('steps') or []
    if references:
        result.append(SectionPageBreak('参考图'))
        heading('参考图', title, 'production-handoff')
        for ref in references:
            name = _text(ref.get('name'))
            if name:
                heading(name, label)
            numbers = ref.get('shot_numbers') or []
            if numbers:
                result.append(Paragraph(_plain('用于第 %s %s' % ('、'.join(map(str, numbers)), unit)), small))
            if _text(ref.get('requirement')):
                result.extend(_paragraphs(ref['requirement'], body))
    if steps:
        result.append(RunningSection('制作顺序'))
        block = [HRFlowable(width=width, thickness=0.6, color=colors.HexColor(RULE),
                            spaceBefore=12, spaceAfter=4)] if not references else []
        p = Paragraph('制作顺序', section)
        p.production_bookmark = ('production-steps', '制作顺序')
        block.append(p)
        for i, step in enumerate(steps, 1):
            block.append(Paragraph(_plain(step), numbered, bulletText='%d.' % i))
        result.append(KeepTogether(block))
    return result
