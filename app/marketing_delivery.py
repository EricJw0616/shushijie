"""Extract deliverable copy from the current channel manuscript, without rewriting it."""
import re
import video_production

CHANNELS = ('公众号', '短视频', '小红书', '达人讲书', '书店活动')
WRAPPER = '渠道素材初稿'
INTERNAL_HEADINGS = {
    '传播角度与受众价值', '渠道内容与表达安排', '各书在专题中的作用',
    '材料怎样复用', '下一步验证', '资料缺口', '需要补充', '本次未使用的材料', '来源索引',
}
LEGACY_TAIL = ('材料怎样复用', '下一步验证', '资料缺口', '需要补充', '本次未使用的材料', '来源索引')
ERROR = '暂时无法区分当前稿中的文章与策划说明，请返回稿件，按各场景整理标题和正文后再下载。'


def headings(source):
    """Read structural headings only; code samples never delimit a manuscript."""
    found, offset, fence = [], 0, None
    for line in source.splitlines(keepends=True):
        match = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match[1]
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not line[match.end():].strip():
                fence = None
        elif fence is None:
            match = re.match(r'^(#{1,6})[ \t]+(.+?)\s*$', line)
            if match:
                found.append({'level': len(match[1]), 'title': match[2],
                              'start': offset, 'body_start': offset + len(line)})
        offset += len(line)
    return found


def clean_markers(source, source_labels):
    """Remove our source markers only, retaining links, footnotes and code."""
    labels = set(source_labels.values())
    if not labels:
        return source
    definitions, code_fence = set(), None
    for line in source.splitlines():
        fence_match = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence_match:
            token = fence_match[1]
            if code_fence is None:
                code_fence = token
            elif token[0] == code_fence[0] and len(token) >= len(code_fence) and not line[fence_match.end():].strip():
                code_fence = None
        elif code_fence is None:
            definition = re.match(r'^ {0,3}\[([^\]]+)\]:[ \t]*\S', line)
            if definition:
                definitions.add(' '.join(definition[1].split()).casefold())
    marker = re.compile(r'(?<!\\)\[(S[1-9]\d*)\]')
    def strip_known(value):
        def replace(match):
            after = value[match.end():]
            # Adjacent reference links are different from our space-separated
            # citation list, e.g. "[S1] [S2]" at a generated scene heading.
            reference = re.match(r'[ \t]+\[([^\]]+)\]', after)
            linked = (match[1].casefold() in definitions or after.startswith('[') or re.match(r'[ \t]*[(:]', after) or
                      (reference and (reference[1] not in labels or reference[1].casefold() in definitions)))
            return '' if match[1] in labels and not linked else match[0]
        return marker.sub(replace, value)
    fence, output = None, []
    for line in source.splitlines(keepends=True):
        match = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if match:
            token = match[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line[match.end():].strip():
                fence = None
            output.append(line)
        elif fence is not None or line.startswith(('    ', '\t')):
            output.append(line)
        else:
            # Matching backtick runs protect Markdown inline code, including literal backticks.
            parts, position = [], 0
            for code in re.finditer(r'(?P<ticks>`+)(?!`)(.*?)(?<!`)(?P=ticks)(?!`)', line):
                parts += [strip_known(line[position:code.start()]), code[0]]
                position = code.end()
            parts.append(strip_known(line[position:]))
            output.append(''.join(parts))
    return ''.join(output)


def spoken_video_copy(source, keep_title=True):
    """Project a recognised production manuscript to its exact spoken copy."""
    if not video_production.validate_manuscript(source):
        return source
    structure = headings(source)
    recording = next(h for h in structure if h['level'] == 4 and h['title'] == '配音稿')
    timeline = next(h for h in structure if h['level'] == 4 and h['title'] == '镜头脚本')
    copy = source[recording['body_start']:timeline['start']].strip()
    title = next((h for h in structure if h['level'] == 1 and h['start'] < recording['start']), None)
    if keep_title and title:
        copy = '# ' + title['title'] + '\n\n' + copy
    return copy


def channel_document(source, channels, source_labels=None, fallback_title='', *, include_video_production=False):
    """Return title/body copy from saved text, or reject ambiguous structure.

    A handwritten single-channel document is already the user's deliverable.
    Legacy discussion documents are recognised by their exact section structure.
    No generation record is read, and the input is never modified.
    """
    source = str(source or '').strip()
    source_labels = source_labels or {}
    channels = list(channels)
    if not source:
        raise ValueError('请先填写稿件正文，再下载。')
    if not channels or len(channels) != len(set(channels)) or any(c not in CHANNELS for c in channels):
        raise ValueError(ERROR)
    sections = headings(source)
    wrappers = [h for h in sections if h['level'] == 2 and h['title'] == WRAPPER]
    if not wrappers:
        # A broken legacy wrapper is not a handwritten article: do not leak its process notes.
        if len(channels) != 1 or sum(h['level'] == 2 and h['title'] in INTERNAL_HEADINGS for h in sections) >= 2:
            raise ValueError(ERROR)
        text = clean_markers(source, source_labels).strip()
        if channels == ['短视频']:
            if include_video_production:
                video_production.validate_manuscript(text)
            else:
                text = spoken_video_copy(text)
        if not any(h['level'] == 1 for h in sections) and fallback_title:
            text = '# ' + fallback_title + '\n\n' + text
        return {'text': text, 'channels': channels, 'structured': False}
    if len(wrappers) != 1:
        raise ValueError(ERROR)
    wrapper = wrappers[0]
    legacy = any(h['start'] < wrapper['start'] and h['level'] == 2 and h['title'] in INTERNAL_HEADINGS
                 for h in sections)
    if source[:wrapper['start']].strip() and not legacy:
        raise ValueError(ERROR)
    end = len(source)
    if legacy:
        candidates = [h for h in sections if h['start'] > wrapper['start'] and
                      h['level'] <= 2 and h['title'] in INTERNAL_HEADINGS]
        if candidates:
            # The old serializer always began its appendix with reuse and ended
            # with sources. An identically named heading inside edited copy can
            # otherwise silently truncate the article, so refuse ambiguous tails.
            end = candidates[0]['start']
            tail = [h for h in sections if h['start'] >= end and h['level'] <= 2]
            names = [h['title'] for h in tail]
            if (names[0] != LEGACY_TAIL[0] or names[-1] != LEGACY_TAIL[-1] or
                    len(names) != len(set(names)) or any(h['level'] != 2 for h in tail) or
                    any(name not in LEGACY_TAIL for name in names) or
                    [LEGACY_TAIL.index(name) for name in names] != sorted(LEGACY_TAIL.index(name) for name in names)):
                raise ValueError(ERROR)
            if any(h['start'] >= end and h['level'] == 3 and
                   re.match(r'^(?:' + '|'.join(CHANNELS) + r')[：:]', h['title']) for h in sections):
                raise ValueError(ERROR)
    scenes = []
    for heading in sections:
        if not wrapper['body_start'] <= heading['start'] < end or heading['level'] != 3:
            continue
        match = re.match(r'^([^：:]+)[：:]\s*(.+)$', heading['title'])
        if match and match[1] in CHANNELS:
            scenes.append({**heading, 'channel': match[1], 'article_title': match[2]})
    if (not scenes or source[wrapper['body_start']:scenes[0]['start']].strip() or
            len(scenes) != len(channels) or {h['channel'] for h in scenes} != set(channels)):
        raise ValueError(ERROR)
    pieces = []
    for index, scene in enumerate(scenes):
        finish = scenes[index + 1]['start'] if index + 1 < len(scenes) else end
        title = clean_markers(scene['article_title'], source_labels).strip()
        body = source[scene['body_start']:finish].strip()
        if legacy:
            # The old serializer appended exactly one CTA paragraph after the copy.
            paragraphs = re.split(r'\n[ \t]*\n', body)
            paragraphs[-1] = re.sub(r'^行动引导[：:][ \t]*', '', paragraphs[-1], count=1)
            body = '\n\n'.join(paragraphs)
        body = clean_markers(body, source_labels).strip()
        if scene['channel'] == '短视频':
            if include_video_production:
                video_production.validate_manuscript(body)
            else:
                body = spoken_video_copy(body, keep_title=False)
        if not title or not body:
            raise ValueError(ERROR)
        heading = title if len(scenes) == 1 else scene['channel'] + '：' + title
        pieces.append('# ' + heading + '\n\n' + body)
    return {'text': '\n\n'.join(pieces), 'channels': [s['channel'] for s in scenes], 'structured': True}
