# -*- coding: utf-8 -*-
"""Versioned project-assistance runs. Generation never edits a project draft."""
import copy
import json
import os
import re
import secrets

import assets_service as assets
import store
import marketing_context
from download_names import production_filename

DIR = os.path.join(store.DATA, 'project_assists')
CAPABILITIES = ('recommend', 'draft', 'video_prompts')


def _engine():
    import project_intelligence
    return project_intelligence


def _path(run_id):
    if not re.fullmatch(r'assist-[a-f0-9]{16}', str(run_id or '')):
        raise ValueError('生成记录编号无效')
    return os.path.join(DIR, run_id + '.json')


def _read(pid, run_id):
    run = store.read_json(_path(run_id), None)
    if not run or run.get('project_id') != pid:
        raise ValueError('该项目没有这份生成记录')
    return run


def _record_failure_diagnostics(run, error):
    """Private local troubleshooting only; never attach traces to public runs/jobs."""
    diagnostic = getattr(error, 'diagnostics', None)
    if not isinstance(diagnostic, dict):
        return
    record = {'schema_version': 1, 'run_id': run['id'], 'project_id': run['project_id'],
              'capability': run['capability'], 'created_at': store.now(), 'diagnostics': diagnostic}
    serialized = json.dumps(record, ensure_ascii=False)
    if len(serialized.encode('utf-8')) > 512000:
        record['diagnostics'] = {'stage': str(diagnostic.get('stage') or '')[:120],
                                 'truncated': True, 'trace_excerpt': serialized[:50000]}
    directory = os.path.join(DIR, '.diagnostics')
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        # store.write_json writes atomically through mkstemp (owner-only on POSIX).
        store.write_json(os.path.join(directory, os.path.basename(_path(run['id']))), record)
    except (OSError, TypeError, ValueError):
        # A diagnostic disk failure must not replace the original task failure.
        pass


def _effective(run):
    run = copy.deepcopy(run)
    if run.get('status') in ('queued', 'running'):
        job = store.get_job(run['job_id'])
        if not job or job.get('status') == 'failed':
            run.update(status='failed', error=(job or {}).get('error') or '任务记录已丢失，请重新生成',
                       finished_at=(job or {}).get('finished_at') or '')
    return run


def _source_issue(run, ids=None, cache=None, project=None):
    from source_context import quality_warnings
    cache = cache if cache is not None else {}
    refs = run['snapshot'].get('input_asset_revisions') or {}
    materials = {m.get('asset_id') or m.get('id'): m for m in run['snapshot'].get('materials', [])}
    pinned = {item['asset_id']: item for item in (project or {}).get('items', [])}
    for aid in ids if ids is not None else refs:
        code = aid.split(':')[0]
        a = assets.project_asset(pinned[aid], cache) if aid in pinned else assets.cached_asset(aid, code, cache)
        if not assets.reference_matches(a, refs.get(aid), materials.get(aid)):
            return '来源材料已更新或不存在，请重新生成'
        if a['status'] == 'rejected' or a.get('stale') or a.get('needs_structure_review') or not a.get('evidence_valid'):
            return '来源材料已失效或依据异常，请重新选择材料'
        issues = [w for w in quality_warnings(a.get('text')) if w['severity'] == 'error']
        if issues:
            return '来源材料存在文本残缺，请先核对并修订：' + issues[0]['message']
    return ''


def _context_hash(project):
    """Track task/material changes separately from applying the resulting draft."""
    context = copy.deepcopy(project)
    context['draft'] = ''
    return _engine().fingerprint(context)


def _topic_angle_task_issue(run, project):
    if project.get('kind') != 'editorial' or (project.get('brief') or {}) != (run['snapshot'].get('brief') or {}):
        return '选题说明已修改，请根据当前主题重新分析'
    return ''


def _public(run, project, cache=None):
    run = _effective(run)
    applied = (project.get('applied_generations') or {}).get(run['id']) or {}
    source_reason = _source_issue(run, cache=cache, project=project) or marketing_context.stale_reason(run['snapshot'])
    is_current_draft = bool(applied and
        (project.get('draft_generation') or {}).get('run_id') == run['id'] and
        assets.digest(project.get('draft') or '') == assets.digest(run.get('markdown') or '') and
        _context_hash(project) == run['snapshot'].get('project_context_hash'))
    reason = ''
    if not is_current_draft and _engine().fingerprint(project) != run['input_hash']:
        reason = ('应用后项目已有修订，本记录保留原生成版本' if applied else
                  '项目说明、材料选择或正文已修改，请基于当前项目重新生成')
    reason = source_reason or reason
    run.update(stale=bool(reason), stale_reason=reason, applied=bool(applied),
               is_current_draft=is_current_draft, source_stale=bool(source_reason),
               source_stale_reason=source_reason, **applied)
    if (run.get('result') or {}).get('topic_angles'):
        issue = _topic_angle_task_issue(run, project)
        run.update(topic_angle_choices_stale=bool(issue), topic_angle_choices_stale_reason=issue)
    pack = (run.get('result') or {}).get('video_prompts')
    if run.get('capability') == 'video_prompts' and run.get('status') == 'done' and isinstance(pack, dict):
        presentation = pack.get('presentation_mode') or run['snapshot'].get('presentation_mode')
        if presentation in ('image', 'video'):
            run['download_filename'] = production_filename(run, presentation, old=bool(reason))
    return run


def get_run(pid, run_id):
    import projects
    return _public(_read(pid, run_id), projects._read(pid))


def get_run_download(pid, run_id, file_format='pdf', allow_stale=False):
    """Typeset existing visual instructions in memory; never create an export or update a run."""
    if file_format != 'pdf':
        raise ValueError('制作包下载格式仅支持 PDF')
    if type(allow_stale) is not bool:
        raise ValueError('旧版下载选项无效')
    run = get_run(pid, run_id)
    pack = (run.get('result') or {}).get('video_prompts')
    if run.get('capability') != 'video_prompts' or run.get('status') != 'done' or not isinstance(pack, dict):
        raise ValueError('请选择已完成的图片或视频制作包')
    text = run.get('markdown')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('这份记录没有完整制作包，请返回提示词逐条复制。')
    presentation = pack.get('presentation_mode') or (run.get('snapshot') or {}).get('presentation_mode')
    if presentation not in ('image', 'video'):
        raise ValueError('这份记录的制作方式不明确，请返回提示词查看。')
    old = bool(run.get('stale') or run.get('source_stale'))
    if old and not allow_stale:
        raise assets.Conflict('制作内容已变化，请确认旧版后再下载。')
    try:
        from manuscript_pdf import render_export_pdf
    except ImportError as err:
        raise ValueError('PDF 排版组件未加载，请检查服务运行环境后重试。仍可复制制作包文字。') from err
    from production_document import build_production_document
    document = build_production_document(run)

    def render(is_old):
        filename = production_filename(run, presentation, old=is_old)
        snapshot = {'filename': filename.removesuffix('.pdf') + '.md', 'text': text,
                    'export': {'content_kind': 'visual_production', 'presentation_mode': presentation,
                               'stale': is_old, 'created_at': run.get('finished_at') or run.get('created_at')}}
        if document:
            snapshot['production_document'] = document
        return filename, render_export_pdf(snapshot), 'application/pdf'

    result = render(old)
    # A project/source may change while typesetting. A successful preflight GET
    # is not permission to silently deliver a now-old version.
    latest = get_run(pid, run_id)
    now_old = bool(latest.get('stale') or latest.get('source_stale'))
    if now_old and not allow_stale:
        raise assets.Conflict('制作内容已变化，请确认旧版后再下载。')
    if now_old and not old:
        result = render(True)
    return result


def recommendation_for_adoption(pid, run_id, asset_id):
    run = _read(pid, run_id)
    if run['capability'] != 'recommend' or run['status'] != 'done':
        raise ValueError('请从已生成的推荐中选择材料')
    suggestion = next((s for s in run['result']['suggestions'] if s['asset_id'] == asset_id), None)
    if not suggestion:
        raise ValueError('该材料不在本次推荐中')
    asset = assets.get_asset(asset_id)
    if not asset:
        raise assets.Conflict('这条材料已不存在，请重新选材')
    issue = _source_issue(run, ids=[asset_id], cache={asset['code']: {asset_id: asset}})
    if issue:
        raise assets.Conflict(issue)
    return asset, suggestion


def topic_angle_for_adoption(project, run_id, index):
    run = _read(project['id'], run_id)
    angles = (run.get('result') or {}).get('topic_angles') or []
    if (run['capability'] != 'recommend' or run['status'] != 'done' or
            type(index) is not int or not 0 <= index < len(angles)):
        raise ValueError('请选择已完成分析的切口')
    issue = _topic_angle_task_issue(run, project)
    if issue:
        raise assets.Conflict(issue)
    angle = angles[index]
    ids = list(dict.fromkeys(angle['asset_ids']))
    if not ids:
        raise ValueError('这个切口缺少可组稿的材料')
    by_code = {code: {a['id']: a for a in assets.all_assets(code)}
               for code in dict.fromkeys(aid.split(':')[0] for aid in ids)}
    issue = _source_issue(run, ids=ids, cache=by_code)
    if issue:
        raise assets.Conflict(issue)
    return angle, [by_code[aid.split(':')[0]][aid] for aid in ids]


def list_runs(pid):
    import projects
    p = projects._read(pid)
    runs, cache = [], {}
    if os.path.isdir(DIR):
        for name in os.listdir(DIR):
            if not re.fullmatch(r'assist-[a-f0-9]{16}\.json', name):
                continue
            r = store.read_json(os.path.join(DIR, name), {})
            if r.get('project_id') == pid:
                runs.append(_public(r, p, cache))
    return sorted(runs, key=lambda r: (r['created_at'], r.get('sequence', 0)), reverse=True)


def enqueue(pid, body):
    import projects
    engine = _engine()
    capability = body.get('capability')
    if capability not in CAPABILITIES:
        raise ValueError('请选择有效的生成操作')
    book_codes = body.get('book_codes') or []
    if not isinstance(book_codes, list) or not all(isinstance(c, str) for c in book_codes):
        raise ValueError('图书范围格式无效')
    known_codes = {r['code'] for r in store.library_rows()}
    if set(book_codes) - known_codes:
        raise ValueError('所选图书不在当前书库')
    with store._lock('projects'):
        p = projects._read(pid)
        if body.get('revision') != p['revision']:
            raise assets.Conflict('项目已更新，请保存并刷新后重新生成')
        if capability == 'video_prompts':
            if body.get('confirmed') is not True or not str(p.get('draft') or '').strip():
                raise ValueError('请先保存口播稿，并确认后再生成提示词。')
            if body.get('confirmed_draft') != p['draft']:
                raise assets.Conflict('确认的口播稿与已保存内容不一致，请保存后重新确认。')
            if body.get('presentation_mode') not in ('image', 'video'):
                raise ValueError('请选择图片展示或视频展示。')
        for old in list_runs(pid):
            if old['capability'] == capability and old['status'] in ('queued', 'running'):
                if old['input_hash'] != engine.fingerprint(p) or old.get('source_stale'):
                    continue
                if capability == 'recommend' and sorted(old['snapshot'].get('request_book_codes',
                        old['snapshot'].get('book_codes') or [])) != sorted(set(book_codes)):
                    continue
                if capability == 'video_prompts' and old['snapshot'].get('presentation_mode') != body['presentation_mode']:
                    continue
                return {'running': True, 'job': store.get_job(old['job_id']), 'run': old}
        if capability == 'video_prompts':
            snapshot = engine.build_video_prompts_input(copy.deepcopy(p), body['presentation_mode'])
            snapshot['confirmed_at'] = store.now()
        else:
            snapshot = engine.build_input(copy.deepcopy(p), capability, book_codes=book_codes)
        snapshot.update(project_id=pid, capability=capability)
        snapshot['request_book_codes'] = sorted(set(book_codes))
        snapshot.setdefault('profile_version', engine.PROFILE_VERSION)
        input_hash = engine.fingerprint(p)
        snapshot['input_hash'] = input_hash
        snapshot['project_context_hash'] = _context_hash(p)
        run_id = 'assist-' + secrets.token_hex(8)
        job = store.new_job('project_assist', {'project_id': pid, 'project_kind': p['kind'], 'run_id': run_id,
                            'title': p['title'], 'capability': capability,
                            **({'presentation_mode': body['presentation_mode']} if capability == 'video_prompts' else {})})
        run = {'id': run_id, 'project_id': pid, 'capability': capability, 'status': 'queued',
               'job_id': job['id'], 'input_hash': input_hash, 'project_revision': p['revision'],
               'profile_version': snapshot['profile_version'], 'created_at': store.now(),
               'sequence': __import__('time').time_ns(), 'started_at': None, 'finished_at': None,
               'error': '', 'snapshot': snapshot, 'result': None, 'markdown': ''}
        store.write_json(_path(run_id), run)
    return {'started': True, 'job': job, 'run': _public(run, p)}


def execute_job(job_id):
    """Called by the runner process; only writes this run and its task log."""
    job = store.get_job(job_id)
    if not job:
        raise ValueError('任务不存在')
    run = _read(job.get('project_id'), job.get('run_id'))
    if run['status'] == 'done':
        store.update_job(job_id, status='done', progress=100, finished_at=run['finished_at'])
        return
    label = {'recommend': '发现可用材料', 'draft': '生成项目讨论稿', 'video_prompts': '根据已确认口播生成提示词'}[run['capability']]
    steps = [{'key': 'prepare', 'label': '读取固定版本的任务与材料', 'status': 'done', 'progress': 10},
             {'key': 'generate', 'label': label, 'status': 'running', 'progress': 85},
             {'key': 'validate', 'label': '验证引用并保存生成记录', 'status': 'pending', 'progress': 100}]
    run.update(status='running', started_at=store.now())
    store.write_json(_path(run['id']), run)
    store.update_job(job_id, status='running', started_at=run['started_at'], progress=10, steps=steps)
    def progress(percent, detail):
        store.update_job(job_id, progress=max(10, min(90, int(percent))))
        if detail:
            store.append_job_log(job_id, str(detail)[:800])
    try:
        engine = _engine()
        result = engine.execute(run['snapshot'], progress=progress)
        if not isinstance(result, dict):
            raise ValueError('生成结果格式无效')
        ids = result.get('asset_ids') or result.get('cited_asset_ids') or []
        if not isinstance(ids, list) or any(i not in (run['snapshot'].get('input_asset_revisions') or {}) for i in ids):
            raise ValueError('生成结果引用了任务范围外的材料')
        if run['capability'] in ('draft', 'video_prompts') and not ids:
            raise ValueError('生成结果缺少可回查的材料依据')
        markdown = engine.render_markdown(result, run['snapshot']) if run['capability'] in ('draft', 'video_prompts') else ''
        if run['capability'] in ('draft', 'video_prompts') and not str(markdown).strip():
            raise ValueError('生成内容为空')
        run.update(status='done', finished_at=store.now(), result=result, markdown=markdown)
        store.write_json(_path(run['id']), run)
        for step in steps:
            step['status'] = 'done'
        store.update_job(job_id, status='done', finished_at=run['finished_at'], progress=100, steps=steps,
                         result={'project_id': run['project_id'], 'run_id': run['id'], 'capability': run['capability']})
    except Exception as exc:
        _record_failure_diagnostics(run, exc)
        run.update(status='failed', finished_at=store.now(), error=str(exc)[:1500])
        store.write_json(_path(run['id']), run)
        steps[1]['status'] = 'failed'
        steps[2]['status'] = 'skipped'
        store.update_job(job_id, status='failed', finished_at=run['finished_at'], error=run['error'], steps=steps)
        store.append_job_log(job_id, '生成失败，原项目正文及历史结果保留：' + run['error'])


def apply_to_project(project, run_id):
    """Mutates only the locked project supplied by projects.update_project."""
    run = _effective(_read(project['id'], run_id))
    if run['capability'] != 'draft' or run['status'] != 'done':
        raise ValueError('只能应用已成功生成的讨论稿')
    if _engine().fingerprint(project) != run['input_hash']:
        raise assets.Conflict('项目已修改，不能覆盖当前正文，请重新生成')
    ids = run['result'].get('asset_ids') or run['result'].get('cited_asset_ids') or []
    refs = {i['asset_id']: i for i in project['items'] if i['status'] == 'adopted'}
    if not ids or any(aid not in refs for aid in ids):
        raise assets.Conflict('生成稿引用的材料已不在采用清单中，请重新生成')
    # Every supplied source can influence the model, including those it did not
    # ultimately cite. An excluded source is absent from this snapshot already.
    reason = _source_issue(run, project=project)
    reason = reason or marketing_context.stale_reason(run['snapshot'])
    if reason:
        raise assets.Conflict(reason)
    project['draft'] = run['markdown']
    project['draft_asset_ids'] = list(dict.fromkeys(ids))
    scoped = bool(run['snapshot'].get('topic_angle'))
    # A focused draft tracks its own sources. General drafts keep their existing adopted baseline.
    project['draft_asset_revisions'] = {aid: item['asset_revision'] for aid, item in refs.items()
                                        if not scoped or aid in ids}
    project['draft_generation'] = {'run_id': run['id'], 'profile_version': run['profile_version'],
                                   'generated_at': run['finished_at'], 'draft_hash': assets.digest(run['markdown']),
                                   'source_labels': run['result'].get('source_labels') or
                                       {aid: 'S%d' % (i + 1) for i, aid in enumerate(ids)}}
    if run['snapshot'].get('plan_delivery_version') == '1.0':
        project['draft_generation']['plan_delivery_version'] = '1.0'
    if scoped:
        project['draft_generation']['topic_angle_title'] = run['snapshot']['topic_angle']['title']
    applied = project.setdefault('applied_generations', {})
    applied[run['id']] = {'applied_at': store.now(), 'applied_project_revision': project['revision'] + 1}
    return project
