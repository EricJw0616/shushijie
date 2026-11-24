"""Readable, portable download names shared by document exporters."""

import re
import unicodedata


def _part(value):
    if not isinstance(value, str):
        return ''
    value = unicodedata.normalize('NFC', value)
    value = ''.join('-' if unicodedata.category(char).startswith('C') else char for char in value)
    value = re.sub(r'[\\/:*?"<>|]', '-', value)
    return re.sub(r'\s+', ' ', value).strip(' .-')


def document_filename(title, document_type, extension='pdf', *, old=False):
    """Use a recognizable title, leaving repeated-download suffixes to the browser."""
    if not re.fullmatch(r'[a-z0-9]{1,10}', extension):
        raise ValueError('下载文件扩展名无效')
    title = _part(title) or '未命名项目'
    if re.match(r'^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])\.', title, re.IGNORECASE):
        title = '项目-' + title
    kind = _part(document_type) or '文档'
    # Stay below common 255-byte filename limits, with room for browser '(1)'.
    kind = kind.encode('utf-8')[:60].decode('utf-8', errors='ignore').rstrip(' .-')
    prefix, suffix = ('旧版-' if old else ''), '_' + kind + '.' + extension
    budget = 220 - len((prefix + suffix).encode('utf-8'))
    title = title.encode('utf-8')[:budget].decode('utf-8', errors='ignore').rstrip(' .-')
    return prefix + title + suffix


def production_filename(run, presentation, *, old=False):
    """Name a saved package after the project it was made for, never today's draft."""
    snapshot = run.get('snapshot') or {}
    brief = snapshot.get('brief') or {}
    marketing = snapshot.get('marketing') or {}
    books = marketing.get('target_books') if isinstance(marketing, dict) else None
    book_title = '、'.join(_part(book.get('book')) for book in books
                          if isinstance(book, dict) and _part(book.get('book'))) if isinstance(books, list) else ''
    candidates = [snapshot.get('title'), brief.get('topic') if isinstance(brief, dict) else '', book_title]
    title = next((_part(value) for value in candidates if _part(value)), '未命名项目')
    kind = {'image': '图片制作包', 'video': '视频制作包'}[presentation]
    return document_filename(title, kind, old=old)
