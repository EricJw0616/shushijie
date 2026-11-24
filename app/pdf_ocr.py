"""Use the installed PDF OCR worker only where the native text is inadequate."""
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading


PLATFORM = Path(__file__).resolve().parent.parent
BAD_GLYPHS = re.compile(r'\(cid:\d+\)|[\ufffd\u25a1\ue000-\uf8ff]')
PRINTED = re.compile(r'[\u3400-\u9fff\uf900-\ufaffA-Za-z]')
CHINESE = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')


def worker_python():
    if os.environ.get('BOOKDISTILL_PDF_OCR') == '0':
        return None
    configured = os.environ.get('BOOKDISTILL_OCR_PYTHON')
    if configured:
        return configured if Path(configured).is_file() else None
    local = PLATFORM / '.venv-ocr' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if local.is_file():
        return str(local)
    if all(importlib.util.find_spec(name) for name in ('rapidocr_onnxruntime', 'pypdfium2')):
        return sys.executable
    return None


def needs_ocr(page):
    if page.get('tables') or page.get('non_body'):
        return False
    native = ''.join(line['t'] for line in page['lines'] if line['k'] in ('body', 'refe', 'vertical'))
    plain = BAD_GLYPHS.sub('', native)
    compact = re.sub(r'\s+', '', native)
    return len(PRINTED.findall(plain)) < (22 if page.get('picture_dominant') else 8) or (
        len(native) - len(plain) >= max(3, len(compact) * .06))


def _read_worker(path, page_numbers, interpreter):
    messages = queue.Queue(maxsize=2)
    stopped = threading.Event()
    with subprocess.Popen([interpreter, '-u', '-m', 'ocr.pdf_worker', os.path.abspath(path)],
                          cwd=PLATFORM / 'platform' / 'engine', stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, encoding='utf-8') as child:
        def read():
            for line in child.stdout:
                while not stopped.is_set():
                    try:
                        messages.put(line, timeout=.25)
                        break
                    except queue.Full:
                        continue
            while not stopped.is_set():
                try:
                    messages.put(None, timeout=.25)
                    return
                except queue.Full:
                    continue

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            json.dump(page_numbers, child.stdin)
            child.stdin.close()
            for _ in page_numbers:
                try:
                    line = messages.get(timeout=60)
                except queue.Empty:
                    return
                if line is None:
                    return
                yield json.loads(line)
        finally:
            stopped.set()
            if child.poll() is None:
                child.kill()
            reader.join(timeout=2)


def _apply(page, result, atlas):
    if result.get('failed'):
        page['ocr'] = {'status': 'failed'}
        return
    if result.get('blank'):
        page['lines'] = []
        page['ocr'] = {'status': 'blank'}
        return
    width, height = page['w'], page['h']
    lines = []
    for row in result.get('lines') or []:
        text, score = row['text'], row['score']
        x0, y0, x1, y1 = row['box']
        # Keep wide text lines. Vertical text stays flagged for visual review.
        if score < .72 or not PRINTED.search(text):
            continue
        x0, top, x1, bottom = x0 * width, y0 * height, x1 * width, y1 * height
        kind = atlas._kind_of(text, top, height)
        vertical = bottom-top > 2.0*(x1-x0)
        lines.append({'t': text, 'x0': round(x0, 1), 'x1': round(x1, 1),
                      'top': round(top, 1), 'k': 'vertical' if vertical else kind,
                      'col': 0, 'ocr_score': round(score, 3)})
    body = [line for line in lines if line['k'] == 'body']
    han = sum(len(CHINESE.findall(line['t'])) for line in body)
    confident = [line for line in body if line['ocr_score'] >= .85]
    if han < 20 or len(body) < 2:
        page['ocr'] = {'status': 'no_text'}
        return
    # Detect clear columns using line boxes, without splitting individual lines.
    left = [line for line in body if line['x1'] <= width * .51]
    right = [line for line in body if line['x0'] >= width * .49]
    columns = len(left) >= 4 and len(right) >= 4 and len(left)+len(right) >= len(body)*.85
    if columns:
        for line in lines:
            line['col'] = int(line['x0'] >= width*.49)
    wide = sum(line['x1'] - line['x0'] >= width * (.23 if columns else .30) for line in confident)
    accepted = han >= 100 and wide >= 5 and len(confident) * 4 >= len(body) * 3
    page['lines'] = sorted(lines, key=lambda row: (row['col'], row['top'], row['x0']))
    page['ocr'] = {'status': 'body' if accepted else 'review', 'engine': 'rapidocr', 'han': han}


def recover_pages(path, pages, atlas, on_progress=None):
    wanted = {page['page']: page for page in pages if needs_ocr(page)}
    if not wanted:
        return {}
    interpreter = worker_python()
    if not interpreter:
        for page in wanted.values():
            page['ocr'] = {'status': 'unavailable'}
        return {'unavailable': len(wanted)}
    pending = dict(wanted)
    if on_progress:
        on_progress(0, len(wanted))
    for _ in range(2):
        if not pending:
            break
        try:
            for result in _read_worker(path, list(pending), interpreter):
                number = result['page']
                page = pending.get(number)
                if page is None:
                    continue
                _apply(page, result, atlas)
                if page['ocr']['status'] != 'failed':
                    pending.pop(number)
                    if on_progress:
                        on_progress(len(wanted) - len(pending), len(wanted))
        except (OSError, ValueError, KeyError):
            pass
    for page in pending.values():
        page['ocr'] = {'status': 'failed'}
    if pending and on_progress:
        on_progress(len(wanted), len(wanted))
    counts = {}
    for page in wanted.values():
        status = (page.get('ocr') or {}).get('status', 'failed')
        counts[status] = counts.get(status, 0) + 1
    return counts
