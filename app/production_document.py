"""A reading layout for saved production instructions, without rewriting prompts.

Only canonical, structured packages use this layout. Other historical documents
retain their saved Markdown so an unrecognized note cannot disappear on export.
"""

import math
import re


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _numbers(value):
    return [n for n in value if type(n) is int and n > 0] if isinstance(value, list) else []


def _narration(pack, snapshot):
    rows = pack.get('confirmed_outline') or snapshot.get('confirmed_outline') or []
    if isinstance(rows, list) and rows and all(
            isinstance(row, dict) and type(row.get('number')) is int and
            _text(row.get('source_text')) for row in rows):
        original = _text(pack.get('confirmed_narration'))
        # A conflicting saved full text remains authoritative; never reassemble
        # it from an unrelated outline just to add paragraph numbers.
        if not original or re.sub(r'\s+', '', original) == re.sub(
                r'\s+', '', ''.join(row['source_text'] for row in rows)):
            return [{'number': row['number'], 'text': row['source_text']} for row in rows]
    original = _text(pack.get('confirmed_narration'))
    return [{'number': None, 'text': original}] if original else []


def _book_titles(snapshot):
    marketing = snapshot.get('marketing') or {}
    books = marketing.get('target_books') if isinstance(marketing, dict) else None
    if not isinstance(books, list) or not books:
        # Material titles are frozen with this run, unlike today's library.
        books = snapshot.get('materials') or []
    if not isinstance(books, list):
        return []
    return list(dict.fromkeys(_text(row.get('book')) for row in books
                              if isinstance(row, dict) and _text(row.get('book'))))


def build_production_document(run):
    """Return display fields from the same frozen run, or None for plain fallback."""
    from video_prompts import production_steps, render

    result = run.get('result') or {}
    if not isinstance(result, dict):
        return None
    pack = result.get('video_prompts')
    snapshot = run.get('snapshot') or {}
    if not isinstance(pack, dict) or not isinstance(snapshot, dict):
        return None
    mode = pack.get('presentation_mode')
    shots = pack.get('shots')
    if mode not in ('image', 'video') or not isinstance(shots, list) or not shots:
        return None
    if any(not isinstance(shot, dict) or not _text(shot.get('prompt')) or
           type(shot.get('number')) is not int for shot in shots):
        return None
    if 'references' in pack and not isinstance(pack['references'], list):
        return None
    try:
        # Protect customized and unrecognized old Markdown from lossy rebuilding.
        if render(result).strip() != _text(run.get('markdown')):
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None

    narration = _narration(pack, snapshot)
    paragraphs = {row['number']: row['text'] for row in narration if row['number'] is not None}
    display_shots = []
    for shot in shots:
        source_numbers = _numbers(shot.get('source_numbers'))
        if not source_numbers and paragraphs.get(shot['number']) == shot.get('source_text'):
            source_numbers = [shot['number']]
        if narration and not all(n in paragraphs for n in source_numbers):
            source_numbers = []
        title = _text(shot.get('title'))
        if re.fullmatch(r'第\s*\d+\s*(?:段|镜|张|镜头|张图|幅画面)', title):
            title = ''  # The layout already supplies a prominent image/shot number.
        timing = shot.get('production_timing') or {}
        if not isinstance(timing, dict) or not all(_number(timing.get(k)) for k in (
                'global_start_seconds', 'global_end_seconds')):
            timing = None
        display_shots.append({
            'number': shot['number'], 'title': title, 'prompt': shot['prompt'],
            'source_numbers': source_numbers,
            'source_text': '' if narration and not paragraphs else _text(shot.get('source_text')),
            'overlay_text': _text(shot.get('overlay_text')),
            'duration_seconds': shot.get('duration_seconds') if _number(shot.get('duration_seconds')) else None,
            'timing': timing,
        })

    references = []
    for ref in pack.get('references') or []:
        if not isinstance(ref, dict) or not _text(ref.get('requirement')):
            continue
        # Remove only a leading workflow status, not the actual visual requirement.
        requirement = re.sub(r'^待(?:提供|制作)\s*[：:]?\s*', '', ref['requirement'].strip(), count=1)
        references.append({'name': _text(ref.get('name')), 'requirement': requirement,
                           'shot_numbers': _numbers(ref.get('shot_numbers'))})

    # These short instructions address the operator. The saved prompts, including
    # all audience, style and reference conditions, remain verbatim above.
    has_unlisted_references = 'references' not in pack
    if mode == 'image':
        first = ('在生图工具中上传对应参考图，再逐张使用提示词。' if references or has_unlisted_references else
                 '将每张图的提示词分别粘贴到生图工具中，生成后核对画面。')
        last = '将图片、配音和字幕按顺序合成视频，按录音调整每张图的停留时间。'
    else:
        first = ('在视频工具中上传提示词要求的参考图或静帧，再逐镜制作片段。' if references or has_unlisted_references else
                 '将每镜的提示词分别粘贴到视频工具中，按标注时长制作片段。')
        first += '只生成画面，不生成口播或对白。'
        last = '将片段按顺序剪辑，统一加入完整配音和字幕，按录音调整镜头时长。'
    steps = [first]
    if narration:
        steps += ['完整口播录制一次，字幕和标题在剪辑时添加。', last]
    original_steps = pack.get('production_steps')
    canonical_steps = production_steps(mode)
    # Keep this known saved version exact; do not infer that arbitrary steps
    # containing similar words are system defaults and discard their details.
    previous_steps = ['逐项准备所列参考素材；准确对象或真实人物先核对参考。',
                      '在外部制作工具中上传各条提示词所需的参考图，再按顺序复制提示词生成画面，核对对象、结构和文字留白。',
                      ('完整口播录制一次；把核对后的图片按顺序与口播、字幕剪辑成配图讲解视频，按实际录音调整每张图的停留时间。' if mode == 'image' else
                       '完整口播录制一次；将片段按计划顺序剪辑，配上完整录音、字幕，再按实际录音调整时长。')]
    # Compact only the known system boilerplate. Preserve a saved, customized
    # procedure if it carries instructions not represented in these defaults.
    if isinstance(original_steps, list) and original_steps and original_steps not in (canonical_steps, previous_steps):
        if not all(isinstance(step, str) and step.strip() for step in original_steps):
            return None
        steps = list(original_steps)
    return {'title': '图片制作包' if mode == 'image' else '视频制作包',
            'presentation_mode': mode, 'topic': _text(snapshot.get('title')),
            'book_titles': _book_titles(snapshot), 'audience': _text(pack.get('audience')),
            'visual_style': _text(pack.get('visual_style')), 'aspect_ratio': _text(pack.get('aspect_ratio')),
            'narration': narration, 'shots': display_shots, 'references': references, 'steps': steps}
