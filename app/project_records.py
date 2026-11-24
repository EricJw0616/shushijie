# -*- coding: utf-8 -*-
"""Compact, read-only project activity index for the records page.

Read each project/run once. Do not build assets, validate source snapshots or
load a model here: those belong to the selected project's detail page.
"""
import datetime
import os
import re

import projects
import project_assist
import marketing_tasks
import store


def _text(value):
    return value if isinstance(value, str) else ''


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _marketing_scenes(project, brief):
    if project['kind'] != 'marketing':
        return []
    if brief.get('marketing_task') != 'channel':
        return ['planning']
    channels = brief.get('channels')
    if not isinstance(channels, list):
        return []
    return list(dict.fromkeys(c for c in channels if isinstance(c, str) and c in marketing_tasks.CHANNELS))


def _files(directory, pattern):
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if re.fullmatch(pattern, name):
            value = store.read_json(os.path.join(directory, name), {})
            if isinstance(value, dict) and value.get('id') == name[:-5]:
                yield value


def _time(value):
    """Compare valid timestamps across offsets; ignore malformed history dates."""
    try:
        date = datetime.datetime.fromisoformat(_text(value).replace('Z', '+00:00'))
        if date.tzinfo is None:
            date = date.replace(tzinfo=datetime.timezone.utc)
        return date.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return float('-inf')


def _latest_time(values):
    valid = [v for v in values if _time(v) != float('-inf')]
    return max(valid, key=_time) if valid else ''


def _run_summary(run, jobs):
    status = run.get('status')
    activity_at = _latest_time([run.get(k) for k in ('created_at', 'started_at', 'finished_at')])
    if status in ('queued', 'running'):
        jid = _text(run.get('job_id'))
        if jid not in jobs:
            try:
                jobs[jid] = store.get_job(jid) if jid else None
            except (ValueError, TypeError, AttributeError, OSError):
                jobs[jid] = None
        job = jobs[jid]
        # A finished/missing job cannot keep an unfinished result running forever.
        if not isinstance(job, dict) or job.get('status') not in ('queued', 'running'):
            status = 'failed'
        else:
            status = job['status']
        if isinstance(job, dict):
            activity_at = _latest_time([activity_at, job.get('started_at'), job.get('finished_at')])
    if status not in ('queued', 'running', 'done', 'partial', 'failed'):
        status = 'failed'
    return {'id': run['id'], 'status': status, 'result_status': _text(run.get('result_status')),
            'capability': run['capability'],
            'created_at': _text(run.get('created_at'))}, activity_at


def _page_number(value, name, default, minimum, maximum=None):
    if value is None or value == '':
        return default
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(name + '必须是整数')
    if number < minimum:
        raise ValueError(name + '不能小于' + str(minimum))
    return min(number, maximum) if maximum is not None else number


def list_records(q='', kind='', limit=20, offset=0, scene=''):
    """One compact row per non-deleted project, including projects without output."""
    if kind not in ('', 'editorial', 'marketing'):
        raise ValueError('项目类型无效')
    if scene not in ('', 'planning', *marketing_tasks.CHANNELS):
        raise ValueError('营销场景无效，请选择公众号、小红书、短视频、达人讲书、书店活动或整体策划')
    limit = _page_number(limit, '每页数量', 20, 1, 100)
    offset = _page_number(offset, '起始位置', 0, 0)
    query = _text(q).strip().casefold()
    current = {p['id']: p for p in _files(projects.DIR, r'prj-[a-f0-9]{16}\.json')
               if not p.get('deleted') and p.get('kind') in ('editorial', 'marketing')}
    counts = {'total': len(current),
              'editorial': sum(p['kind'] == 'editorial' for p in current.values()),
              'marketing': sum(p['kind'] == 'marketing' for p in current.values())}
    grouped = {}
    for run in _files(project_assist.DIR, r'assist-[a-f0-9]{16}\.json'):
        pid = _text(run.get('project_id'))
        if pid not in current or run.get('capability') not in ('recommend', 'draft', 'video_prompts'):
            continue
        # Discard model inputs/results immediately; the index only needs metadata.
        summary = {key: run.get(key) for key in
                   ('id', 'status', 'capability', 'job_id', 'created_at', 'started_at', 'finished_at', 'sequence')}
        result = run.get('result') if isinstance(run.get('result'), dict) else {}
        summary['result_status'] = _text(result.get('status'))
        grouped.setdefault(pid, []).append(summary)
    result, jobs = [], {}
    for pid, project in current.items():
        if kind and project['kind'] != kind:
            continue
        brief = project.get('brief') if isinstance(project.get('brief'), dict) else {}
        scenes = _marketing_scenes(project, brief)
        if scene and scene not in scenes:
            continue
        brief = {key: _text(brief.get(key)) for key in ('topic', 'audience', 'goal')}
        items, exports, feedback = [_rows(project.get(key)) for key in ('items', 'exports', 'feedback')]
        books = []
        for item in items:
            snapshot = item.get('snapshot') if isinstance(item.get('snapshot'), dict) else {}
            book = _text(snapshot.get('book')).strip()
            if book and book not in books:
                books.append(book)
        title = _text(project.get('title')) or '未命名项目'
        searchable = ' '.join([title, *brief.values(), *books]).casefold()
        if query and query not in searchable:
            continue
        runs = grouped.get(pid, [])
        runs.sort(key=lambda r: (_time(r.get('created_at')),
                                r.get('sequence') if isinstance(r.get('sequence'), (int, float)) else 0,
                                r['id']), reverse=True)
        activity = [project.get('created_at'), project.get('updated_at')]
        activity += [entry.get('created_at') or entry.get('ts') for entry in exports + feedback]
        latest_run = None
        for index, run in enumerate(runs):
            summary, at = _run_summary(run, jobs)
            activity.append(at)
            if index == 0:
                latest_run = summary
        valid_feedback = [f for f in feedback if f.get('outcome') in ('used', 'not_used', 'needs_revision')]
        # Python's max preserves the first occurrence, so reverse append order
        # breaks equal/missing timestamp ties in favor of the newest feedback.
        last_feedback = max(reversed(valid_feedback), key=lambda f: _time(f.get('created_at') or f.get('ts')), default={})
        result.append({'id': pid, 'title': title, 'kind': project['kind'],
                       'status': _text(project.get('status')) or 'draft', 'brief': brief,
                       'marketing_scenes': scenes,
                       'item_count': len(items), 'adopted_count': sum(i.get('status') == 'adopted' for i in items),
                       'export_count': len(exports), 'feedback_count': len(feedback), 'run_count': len(runs),
                       'latest_run': latest_run, 'has_draft': bool(_text(project.get('draft')).strip()),
                       'last_activity_at': _latest_time(activity), 'last_outcome': last_feedback.get('outcome'),
                       'source_books': books})
    result.sort(key=lambda row: (_time(row['last_activity_at']), row['id']), reverse=True)
    return {'items': result[offset:offset + limit], 'total': len(result),
            'limit': limit, 'offset': offset, 'counts': counts}
