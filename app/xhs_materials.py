"""Bounded book excerpts and uploaded text for the Xiaohongshu editor."""

import io
import os
import zipfile

import ingest
import store
from understanding import supported_source


MAX_UPLOAD = 40 * 1024 * 1024
MAX_MATERIALS = 16000
BOOK_EXCERPT_LIMIT = 6400


def _preview(parts, limit=MAX_MATERIALS):
    """Use the same length unit as the browser's textarea maxlength."""
    result = []
    used = 0
    for part in parts:
        cleaned = ingest._normalize(part).strip()
        if not cleaned:
            continue
        if result:
            used += 2
        data = cleaned.encode('utf-16-le')
        remaining = limit - used
        if len(data) > 2 * remaining:
            if remaining > 0:
                result.append(data[:2 * remaining].decode('utf-16-le', errors='ignore').rstrip())
            return '\n\n'.join(result), True
        result.append(cleaned)
        used += len(data) // 2
    return '\n\n'.join(result), False


def from_book(code):
    if not store.is_code(code):
        raise ValueError('请选择有效的书库图书。')
    record = store.get_record(code)
    if not record or record.get('status') == 'failed':
        return None
    book = store.E.book_json(code)
    title = record.get('book') or book.get('书名') or book.get('book') or code

    def parts():
        metadata = [(key, record.get(field)) for key, field in (('作者', 'author'), ('出版社', 'publisher'))]
        yield '\n'.join('%s：%s' % (key, value) for key, value in metadata if value)
        for row in store._seg_rows(code)[0]:
            if supported_source(row) and isinstance(row.get('文本'), str):
                yield row['文本']

    materials, truncated = _preview(parts(), BOOK_EXCERPT_LIMIT)
    return {'title': title, 'materials': materials, 'truncated': truncated, 'cover_url': ''}


def _pdf_pages(source):
    import pdfplumber

    with pdfplumber.open(source) as document:
        for page in document.pages:
            text = ingest._clean_pdf_lines(page.extract_text() or '')
            page.close()
            yield text


def from_upload(filename, data):
    filename = os.path.basename(filename.replace('\\', '/'))
    if not data:
        raise ValueError('上传的文件是空的。')
    fmt = ingest.fmt_of(filename)
    source = io.BytesIO(data)
    if fmt == 'docx':
        try:
            with zipfile.ZipFile(source) as archive:
                if sum(item.file_size for item in archive.infolist()) > 128 * 1024 * 1024:
                    raise ValueError('Word 文件解压后过大，请选取相关章节或另存为 TXT。')
        except zipfile.BadZipFile as error:
            raise ValueError('这份 Word 文件打不开，请另存为 .docx 再上传。') from error
        source.seek(0)
        text, truncated = _preview([ingest._docx_text(source)])
    elif fmt == 'pdf':
        try:
            # Close the document even when the preview fills before the last page.
            with_pdf = _pdf_pages(source)
            try:
                text, truncated = _preview(with_pdf)
            finally:
                with_pdf.close()
        except Exception as error:
            raise ValueError('这份 PDF 无法读取，请检查文件是否加密或损坏。') from error
        if not text:
            raise ValueError('PDF 没有可提取的文字。扫描件请先 OCR，或上传 Word、TXT。')
    else:
        try:
            encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            decoded = ingest._decode_bytes(data)
        if '\0' in decoded:
            raise ValueError('文件包含二进制数据，请另存为普通文本。')
        text, truncated = _preview([ingest._md_to_text(decoded) if fmt == 'md' else decoded])
    if not text:
        raise ValueError('没有读到可用的内文，请检查文件内容。')
    return {'text': text, 'filename': filename, 'truncated': truncated}
