"""Track active Xiaohongshu jobs and retain the finished drafts for the editor."""

import secrets
import threading
import time

import xhs_writing


_LOCK = threading.Lock()
_JOBS = {}
_ACTIVE = ('queued', 'running')
_TTL = 2 * 3600
_MAX_ACTIVE = 2
_MAX_FINISHED = 48


class Busy(Exception):
    pass


def _public(job):
    return {key: value for key, value in job.items() if key != 'updated'}


def _prune(now):
    finished = sorted((job['updated'], jid) for jid, job in _JOBS.items() if job['status'] not in _ACTIVE)
    for index, (updated, jid) in enumerate(finished):
        if now - updated > _TTL or len(finished) - index > _MAX_FINISHED:
            del _JOBS[jid]


def get(jid):
    with _LOCK:
        _prune(time.monotonic())
        job = _JOBS.get(jid)
        return _public(job) if job else None


def enqueue(body):
    prepared = xhs_writing.validate_generation(body)
    jid = secrets.token_hex(16)
    with _LOCK:
        now = time.monotonic()
        _prune(now)
        if sum(job['status'] in _ACTIVE for job in _JOBS.values()) >= _MAX_ACTIVE:
            raise Busy('已有小红书任务正在生成，请稍后重试。')
        job = {'id': jid, 'status': 'queued', 'count': prepared['count'], 'completed': 0,
               'notes': [], 'failures': [], 'vision': {'status': 'not_requested', 'message': ''},
               'updated': now}
        _JOBS[jid] = job
        result = _public(job)

    def report(update, **extra):
        with _LOCK:
            job.update(update, **extra, updated=time.monotonic())

    def run():
        report({}, status='running')
        try:
            outcome = xhs_writing.run_generation(prepared, on_progress=report)
            size = len(outcome.get('notes', []))
            report(outcome, status='done' if size == job['count'] else 'partial' if size else 'failed')
        except (xhs_writing.WritingUnavailable, xhs_writing.InvalidModelOutput) as error:
            report({}, status='partial' if job['notes'] else 'failed', error=str(error))
        except Exception:
            report({}, status='partial' if job['notes'] else 'failed', error='批量生成中断，请稍后重试。')

    try:
        threading.Thread(target=run, daemon=True, name='xhs-writing').start()
    except RuntimeError as error:
        with _LOCK:
            del _JOBS[jid]
        raise Busy('暂时无法启动生成任务，请稍后重试。') from error
    return result
