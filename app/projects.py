# -*- coding: utf-8 -*-
"""Persistent publishing/marketing workspaces with pinned asset revisions and exports."""
import copy
import json
import os
import re
import secrets
import tempfile

import store
import assets_service as assets
import marketing_tasks
import marketing_delivery
import marketing_context
from source_context import quality_warnings

DIR = os.path.join(store.DATA, 'projects')
STATUSES = ('draft', 'active', 'review', 'approved', 'delivered', 'used', 'paused')
BRIEF_KEYS = ('audience', 'topic', 'goal', 'channel', 'source_code', 'new_book_brief')
CITATION_MARKER = re.compile(r'\[(S[1-9]\d*)\]')


def _path(pid):
    if not re.fullmatch(r'prj-[a-f0-9]{16}', str(pid)):
        raise ValueError('项目编号无效')
    return os.path.join(DIR, pid + '.json')


def _read(pid):
    p = store.read_json(_path(pid), None)
    if not p or p.get('deleted'):
        raise ValueError('项目不存在')
    return p


def _brief(value):
    if not isinstance(value, dict):
        raise ValueError('项目说明格式无效')
    brief = {k: str(value.get(k) or '')[:10000 if k == 'new_book_brief' else 2000] for k in BRIEF_KEYS}
    if 'writing_notes' in value:
        brief['writing_notes'] = str(value.get('writing_notes') or '')[:4000]
    brief.update(marketing_context.normalize(value))
    if any(k in value for k in ('marketing_task', 'target_codes', 'channels')):
        brief.update(marketing_tasks.normalize(value))
    return brief


def create_project(body):
    kind = body.get('kind') or 'editorial'
    if kind not in ('editorial', 'marketing'):
        raise ValueError('项目类型无效')
    title = str(body.get('title') or '').strip()[:160]
    if not title:
        raise ValueError('请填写项目名称')
    p = {'id': 'prj-' + secrets.token_hex(8), 'kind': kind, 'title': title,
         'brief': _brief(body.get('brief') or {}), 'status': 'draft', 'items': [],
         'draft': '', 'draft_asset_ids': [], 'draft_asset_revisions': {}, 'draft_review': None, 'feedback': [],
         'exports': [], 'created_at': store.now(), 'updated_at': store.now(), 'revision': 1}
    if 'marketing_asset_id' in body:
        return _create_with_marketing_material(p, body)
    if body.get('relation_asset_id'):
        asset_id = body['relation_asset_id']
        if not assets.is_relation_id(asset_id):
            raise ValueError('请选择一条书中关系')
        p['items'].append(_collected_item(asset_id))
    store.write_json(_path(p['id']), p)
    return p


def _create_with_marketing_material(p, body):
    """Save a new marketing task and its collected material in one write."""
    if p['kind'] != 'marketing' or body.get('relation_asset_id'):
        raise ValueError('营销资料只能带入新的营销项目，请单独选择一条资料')
    aid = body.get('marketing_asset_id')
    if not isinstance(aid, str) or not aid:
        raise ValueError('请选择一条营销资料')
    request_id = body.get('request_id')
    if request_id is not None:
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id):
            raise ValueError('创建请求编号无效，请重新打开新建项目')
        # The project itself is the idempotency record: retries cannot leave a
        # second empty task or require a separate index to be written atomically.
        p['id'] = 'prj-' + assets.digest(['marketing-material-create', request_id])[:16]
        p['creation_request'] = {'id': request_id,
                                 'fingerprint': assets.digest([p['kind'], p['title'], p['brief'], aid])}
    with store._lock('projects'):
        if request_id is not None and os.path.exists(_path(p['id'])):
            existing = store.read_json(_path(p['id']), {})
            if (existing.get('deleted') or
                    existing.get('creation_request') != p['creation_request']):
                raise assets.Conflict('这次创建请求已处理且内容不同，请刷新后重新创建')
            return existing
        item = _collected_item(aid)
        if item['snapshot']['kind'] != 'marketing':
            raise ValueError('请选择一条营销资料')
        config = marketing_tasks.normalize(p['brief'])
        targets = (config['target_codes'] if config['marketing_task'] in ('theme', 'channel')
                   else [p['brief'].get('source_code')])
        if item['snapshot']['code'] not in targets:
            raise ValueError('请将这条资料所属图书选为本项目的推广图书')
        p['items'].append(item)
        store.write_json(_path(p['id']), p)
    return p


def _collected_item(asset_id, note=''):
    asset = assets.get_asset(asset_id)
    if not asset or asset['status'] == 'rejected':
        raise ValueError('材料已失效，请重新查找')
    if asset.get('source_type') == 'graph_relation' and not asset.get('evidence_valid'):
        raise ValueError('这条关系的原文出处无法核对，请重新查找')
    return {'asset_id': asset['id'], 'asset_revision': asset['revision'], 'snapshot': asset,
            'note': str(note or '')[:4000], 'status': 'selected', 'added_at': store.now()}


def list_projects(kind=''):
    if not os.path.isdir(DIR):
        return []
    rows = []
    for n in os.listdir(DIR):
        if not re.fullmatch(r'prj-[a-f0-9]{16}\.json', n):
            continue
        p = store.read_json(os.path.join(DIR, n), {})
        if not p or p.get('deleted') or (kind and p.get('kind') != kind):
            continue
        rows.append({k: p.get(k) for k in ('id', 'kind', 'title', 'brief', 'status', 'created_at', 'updated_at', 'revision')} |
                    {'item_count': len(p.get('items', [])), 'adopted_count': sum(i['status'] == 'adopted' for i in p.get('items', [])),
                     'export_count': len(p.get('exports', [])), 'feedback_count': len(p.get('feedback', []))})
    return sorted(rows, key=lambda p: p['updated_at'], reverse=True)


def reuse_project(pid, body):
    """Copy a task definition and optional current materials, never its approvals."""
    if not isinstance(body.get('copy_materials', False), bool):
        raise ValueError('请选择是否带入材料')
    with store._lock('projects'):
        original = _read(pid)
        if body.get('revision') != original['revision']:
            raise assets.Conflict('原项目已更新，请刷新后重新复用')
        title = str(body.get('title') or '').strip()
        if not title:
            raise ValueError('请填写新项目名称')
        fresh = create_project({'kind': original['kind'], 'title': title, 'brief': original['brief']})
        fresh['reused_from'] = {'project_id': pid, 'title': original['title'], 'revision': original['revision']}
        skipped, cache = [], {}
        if body.get('copy_materials'):
            for old in original['items']:
                if old['status'] == 'not_fit':
                    continue
                code = old['snapshot']['code']
                a = assets.cached_asset(old['asset_id'], code, cache)
                if not a or a['status'] == 'rejected':
                    skipped.append(old['snapshot']['title'])
                    continue
                fresh['items'].append({'asset_id': a['id'], 'asset_revision': a['revision'], 'snapshot': a,
                                       'note': ('原项目备注（请按新任务重新判断）：' + old['note']) if old.get('note') else '',
                                       'status': 'selected', 'added_at': store.now()})
        fresh['reuse_skipped'] = skipped
        store.write_json(_path(fresh['id']), fresh)
    return _decorate(fresh)


def _explicit_draft_scope(p):
    return bool(p.get('draft_refs_confirmed') or (p.get('draft_generation') or {}).get('topic_angle_title'))


def _draft_scope(p):
    cited = p.get('draft_asset_ids') or []
    if _explicit_draft_scope(p):
        return list(dict.fromkeys(cited))
    adopted = [i['asset_id'] for i in p['items'] if i['status'] == 'adopted']
    return list(dict.fromkeys(cited + adopted))


def _draft_display_labels(p):
    draft = p.get('draft') or ''
    if not draft.strip():
        return {}
    adopted = {item['asset_id'] for item in p['items'] if item['status'] == 'adopted'}
    cited = [aid for aid in p.get('draft_asset_ids') or [] if aid in adopted]
    cited_set = set(cited)
    labels = (p.get('draft_generation') or {}).get('source_labels') or {}
    by_label = {label: aid for aid, label in labels.items()}
    in_text = (by_label.get(label) for label in CITATION_MARKER.findall(draft))
    ordered = dict.fromkeys([aid for aid in in_text if aid in cited_set] + cited)
    return {aid: 'S%d' % number for number, aid in enumerate(ordered, 1)}


def _draft_marker_issues(p, draft, asset_ids, *, require_known=False):
    labels = (p.get('draft_generation') or {}).get('source_labels') or {}
    by_label = {label: aid for aid, label in labels.items()}
    titles = {i['asset_id']: i['snapshot']['title'] for i in p['items']}
    cited = set(asset_ids)
    # Labels from a generation refer to fixed sources, even after removal.
    markers = dict.fromkeys(CITATION_MARKER.findall(draft))
    for label in markers:
        aid = by_label.get(label)
        if aid and aid not in cited:
            yield {'asset_id': aid, 'title': titles.get(aid, '已移除材料'), 'kind': 'marker',
                   'reason': '正文仍有 [%s]，请删除或调整对应段落与出处。' % label}
        elif not aid and require_known:
            yield {'asset_id': '', 'title': '[%s]' % label, 'kind': 'marker',
                   'reason': '正文中的 [%s] 没有对应的来源，请核对并移除此标记。' % label}


def _draft_reference_issues(p):
    if not p.get('draft', '').strip():
        return []
    items = {i['asset_id']: i for i in p['items']}
    versions = p.get('draft_asset_revisions') or {}
    issues = []
    for aid in _draft_scope(p):
        item = items.get(aid)
        title = item['snapshot']['title'] if item else '已移除材料'
        if not item or item['status'] != 'adopted':
            issue = ('not_adopted', '当前稿仍登记了已取消采用或已移除的材料，请核对对应正文和出处。')
        elif item['stale'] or item['current_status'] == 'rejected' or not item['evidence_valid'] or item['quality_issues']:
            issue = ('source_changed', '来源已变化或出处需要处理，请核对材料后确认稿件引用。')
        elif versions.get(aid) != item['asset_revision']:
            issue = ('version_changed', '当前稿未核对这一版材料，请确认是否纳入正文。')
        else:
            continue
        issues.append({'asset_id': aid, 'title': title, 'kind': issue[0], 'reason': issue[1]})
    issues.extend(_draft_marker_issues(p, p['draft'], p.get('draft_asset_ids') or [],
                                       require_known=_explicit_draft_scope(p)))
    return issues


def _newer_summary(snapshot, book_assets):
    if snapshot.get('kind') != 'marketing' or snapshot.get('marketing_key') != 'summary':
        return None
    candidates = [asset for asset in book_assets.values() if asset and
                  asset['id'] != snapshot['id'] and asset['code'] == snapshot['code'] and
                  asset['kind'] == 'marketing' and asset.get('marketing_key') == 'summary']
    if len(candidates) != 1:
        return None
    current = candidates[0]
    if (current['status'] != 'approved' or current.get('stale') or not current.get('evidence_valid') or
            current.get('needs_structure_review') or
            any(w['severity'] == 'error' for w in quality_warnings(current['text']))):
        return None
    return {'id': current['id'], 'title': '图书简介', 'book': current['book'],
            'status': current['status']}


def _decorate(p, assets_by_code=None):
    p = copy.deepcopy(p)
    warnings = []
    # A queue can share this read-only lookup across all project references.
    by_code = assets_by_code if assets_by_code is not None else {}
    for i in p['items']:
        aid = i['asset_id']
        code = i['snapshot']['code']
        a = assets.project_asset(i, by_code)
        i['stale'] = not assets.reference_matches(a, i['asset_revision'], i['snapshot']) or bool(a and a.get('stale'))
        i['current_revision'] = a['revision'] if a else None
        i['current_status'] = a['status'] if a else 'missing'
        i['evidence_valid'] = bool(a and a['evidence_valid'])
        i['quality_issues'] = [w for w in quality_warnings((a or {}).get('text')) if w['severity'] == 'error']
        if a and a.get('archived'):
            i['archived'] = True
        replacement = _newer_summary(i['snapshot'], by_code.get(code, {})) if not a or i.get('archived') else None
        if replacement:
            i['replacement'] = replacement
        if a and a.get('needs_structure_review'):
            i['quality_issues'].append({'code': 'source_structure', 'severity': 'error',
                                        'message': '来源结构异常，请修复后重新核对'})
        if i['status'] != 'not_fit' and (i['stale'] or i['current_status'] == 'rejected'):
            warnings.append({'asset_id': aid, 'title': i['snapshot']['title'],
                             'reason': '引用版本已更新或内容已失效，请重新核对'})
        if i['status'] != 'not_fit' and i['quality_issues']:
            warnings.append({'asset_id': aid, 'title': i['snapshot']['title'],
                             'reason': '；'.join(w['message'] for w in i['quality_issues'])})
    p['draft_reference_issues'] = _draft_reference_issues(p)
    p['draft_display_labels'] = _draft_display_labels(p)
    p['draft_outdated'] = bool(p['draft_reference_issues'])
    if p['draft_outdated']:
        warnings.append({'asset_id': '', 'title': '项目正文', 'reason': '稿件的引用待核对，请确认正文和出处后再审核'})
    p['warnings'] = warnings
    return p


def get_project(pid):
    return _decorate(_read(pid))


def review_queue():
    """Use current draft references for marketing and selected material for editorial work."""
    grouped, projects_with_work, by_code = {}, set(), {}
    for summary in list_projects():
        if summary['status'] in ('paused', 'delivered', 'used'):
            continue
        project = _read(summary['id'])
        marketing_draft_scope = None
        if project['kind'] == 'marketing':
            if not (project.get('draft') or '').strip():
                continue
            marketing_draft_scope = set(_draft_scope(project))
        p = _decorate(project, by_code)
        draft_issues = {issue['asset_id']: issue for issue in p['draft_reference_issues']
                        if issue['kind'] in ('not_adopted', 'version_changed')} if marketing_draft_scope is not None else {}
        for item in p['items']:
            aid, snapshot = item['asset_id'], item['snapshot']
            draft_issue = draft_issues.get(aid)
            if marketing_draft_scope is not None and aid not in marketing_draft_scope:
                continue
            if not draft_issue and item['status'] not in ('selected', 'adopted'):
                continue
            if (not draft_issue and item['current_status'] == 'approved' and not item['stale']
                    and item['evidence_valid'] and not item['quality_issues']):
                continue
            a = snapshot if item.get('archived') else by_code.get(snapshot['code'], {}).get(aid)
            reasons = [draft_issue['reason']] if draft_issue else []
            if not a:
                reasons.append('原成果已不存在，请回项目调整稿件引用或更换素材')
            else:
                if a.get('stale'):
                    reasons.append('源内容已更新，需要重新生成并核对成果')
                if a['status'] == 'rejected':
                    reasons.append('成果已停用，请核查原因或更换材料')
                elif a['status'] != 'approved':
                    reasons.append('这条成果尚未核对确认')
                if not item['evidence_valid']:
                    reasons.append('原文依据无效，请先修复或更换材料')
                if not assets.reference_matches(a, item['asset_revision'], snapshot):
                    reasons.append('项目引用的是旧版本，需要核对并更新引用')
                reasons.extend(w['message'] for w in item['quality_issues'])
            if (not a or a.get('stale') or item['current_status'] == 'rejected' or
                    not item['evidence_valid'] or item['quality_issues'] or
                    (draft_issue and draft_issue['kind'] == 'not_adopted')):
                action = 'replace_asset'
            elif item['stale'] or (draft_issue and item['current_status'] == 'approved'):
                action = 'refresh_reference'
            else:
                action = 'review_asset'
            if aid not in grouped:
                display = a or snapshot
                grouped[aid] = {
                    'asset_id': aid,
                    'title': '图书简介' if not a and display.get('marketing_key') == 'summary'
                    else display.get('title') or '内容成果',
                    'book': display.get('book') or '', 'code': snapshot['code'],
                    'kind': display.get('kind') or '', 'status': item['current_status'],
                    'evidence_valid': item['evidence_valid'], 'stale': False,
                    'asset_exists': bool(a), 'current_revision': item['current_revision'],
                    'quality_note': (a or {}).get('quality_note') or '',
                    'action': action, 'reasons': [], 'projects': [],
                }
                if display.get('marketing_key'):
                    grouped[aid]['marketing_key'] = display['marketing_key']
            entry = grouped[aid]
            if action == 'replace_asset' or (action == 'refresh_reference' and entry['action'] == 'review_asset'):
                entry['action'] = action
            entry['stale'] = entry['stale'] or item['stale']
            entry['reasons'] += [r for r in reasons if r not in entry['reasons']]
            entry['reason'] = '；'.join(entry['reasons'])
            entry['projects'].append({
                'id': p['id'], 'title': p['title'], 'kind': p['kind'],
                'brief': {k: p['brief'].get(k) or '' for k in ('topic', 'goal')},
                'item_status': item['status'], 'stale': item['stale'],
                'reason': '；'.join(reasons),
            })
            projects_with_work.add(p['id'])
    return {'items': list(grouped.values()), 'total': len(grouped),
            'project_count': len(projects_with_work)}


def get_export(pid, export_id):
    p = _read(pid)
    if not re.fullmatch(r'export-[a-f0-9]{16}', str(export_id)):
        raise ValueError('交付记录编号无效')
    if not any(e['id'] == export_id for e in p.get('exports', [])):
        raise ValueError('该项目没有这份交付记录')
    export = store.read_json(os.path.join(DIR, 'exports', export_id + '.json'), None)
    if not export or 'text' not in export:
        raise ValueError('交付快照不存在')
    filename = export.get('filename') or (pid + '_' + export_id + '.md')
    return {'filename': filename, 'text': export['text'],
            'export': {k: v for k, v in export.items() if k != 'text'}}


def get_export_download(pid, export_id, file_format):
    if file_format not in ('md', 'pdf'):
        raise ValueError('导出格式仅支持 Markdown 或 PDF')
    snapshot = get_export(pid, export_id)
    filename = os.path.splitext(snapshot['filename'])[0] + '.' + file_format
    if file_format == 'md':
        return filename, snapshot['text'].encode('utf-8'), 'text/markdown; charset=utf-8'

    # Generate once from the stored export, independent of the live draft.
    path = os.path.join(DIR, 'exports', export_id + '.pdf')
    with store._lock('project-export-pdf'):
        if os.path.isfile(path):
            with open(path, 'rb') as fp:
                return filename, fp.read(), 'application/pdf'
        try:
            from manuscript_pdf import render_export_pdf
            content = render_export_pdf(snapshot)
        except ImportError as err:
            raise ValueError('PDF 排版组件未加载，请检查服务运行环境后重试。Markdown 仍可下载。') from err
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.pdf-')
        try:
            with os.fdopen(fd, 'wb') as fp:
                fp.write(content)
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    return filename, content, 'application/pdf'


def _invalidate(p):
    p['draft_review'] = None
    p['status'] = 'draft'


def _invalidate_material_change(p, aid):
    if not _explicit_draft_scope(p) or aid in (p.get('draft_asset_ids') or []):
        _invalidate(p)


def _reconcile_draft_refs(p, body):
    ids = body.get('asset_ids')
    if not isinstance(ids, list) or not all(isinstance(aid, str) for aid in ids):
        raise ValueError('请确认当前稿引用的材料清单')
    ids = list(dict.fromkeys(ids))
    draft = body.get('draft', p.get('draft', ''))
    if not isinstance(draft, str) or not draft.strip() or len(draft) > 100000:
        raise ValueError('请填写 1–100000 字的稿件正文')
    marker_issue = next(_draft_marker_issues(p, draft, ids, require_known=True), None)
    if marker_issue:
        raise ValueError(marker_issue['reason'])

    decorated = _decorate(p)
    items = {i['asset_id']: i for i in decorated['items']}
    versions = {}
    for aid in ids:
        item = items.get(aid)
        if not item or item['status'] != 'adopted':
            raise ValueError('当前稿只能引用本项目采用的材料，请核对后重试')
        if item['stale'] or item['current_status'] == 'rejected' or not item['evidence_valid'] or item['quality_issues']:
            raise ValueError('「%s」的来源或出处需要处理，请先核对项目材料。' % item['snapshot']['title'])
        versions[aid] = item['asset_revision']
    if (draft != p['draft'] or ids != p.get('draft_asset_ids', []) or
            versions != p.get('draft_asset_revisions', {}) or set(ids) != set(_draft_scope(p))):
        _invalidate(p)
    p.update(draft=draft, draft_asset_ids=ids, draft_asset_revisions=versions, draft_refs_confirmed=True)


def _confirm_asset_content(asset):
    from source_context import quality_warnings

    if asset['status'] == 'rejected' or asset.get('stale'):
        raise assets.Conflict('材料已停用或来源已更新，请重新核对')
    if not asset['evidence_valid'] or asset.get('needs_structure_review') or any(
        w['severity'] == 'error' for w in quality_warnings(asset.get('text'))
    ):
        raise ValueError('材料内容或出处有待修正，请打开内容成果处理后再确认')
    if asset['status'] == 'approved':
        return asset, False
    checked = assets.review_asset({'id': asset['id'], 'revision': asset['revision'], 'status': 'approved'})
    if not assets.reference_matches(checked, asset['revision'], asset) or checked['status'] != 'approved':
        raise assets.Conflict('材料状态已变化，请重新打开详情核对')
    return checked, True


def _include_in_topic_angle(p, aid):
    angle = p.get('topic_angle')
    if angle and aid not in angle['asset_ids']:
        angle['asset_ids'].append(aid)


def _adopt_asset(p, asset, item, note):
    aid = asset['id']
    if item:
        item['status'] = 'adopted'
        if note not in item.get('note', ''):
            item['note'] = '\n\n'.join(filter(None, (item.get('note'), note)))[:4000]
    else:
        p['items'].append({'asset_id': aid, 'asset_revision': asset['revision'], 'snapshot': asset,
                           'note': note[:4000], 'status': 'adopted', 'added_at': store.now()})
    _invalidate_material_change(p, aid)


def _adopt_recommendation(p, body):
    from project_assist import recommendation_for_adoption

    confirm = body.get('confirm_content', False)
    if not isinstance(confirm, bool):
        raise ValueError('请选择是否已经核对内容与出处')
    aid = body.get('asset_id')
    asset, suggestion = recommendation_for_adoption(p['id'], body.get('run_id'), aid)
    item = next((i for i in p['items'] if i['asset_id'] == aid), None)
    if item and not assets.reference_matches(asset, item['asset_revision'], item['snapshot']):
        raise assets.Conflict('项目里引用的是旧版本，请先到「已收集」更新引用再核对')
    note = '推荐理由：' + suggestion['reason'] + '\n建议用法：' + suggestion['proposed_use']

    confirmed_now = False
    if confirm:
        asset, confirmed_now = _confirm_asset_content(asset)

    if item and item['status'] == 'adopted':
        return confirmed_now
    _adopt_asset(p, asset, item, note)
    _include_in_topic_angle(p, aid)
    return confirmed_now


def _adopt_topic_angle(p, body):
    from project_assist import topic_angle_for_adoption

    run_id, index = body.get('run_id'), body.get('angle_index')
    angle, sources = topic_angle_for_adoption(p, run_id, index)
    current = p.get('topic_angle') or {}
    if current.get('run_id') == run_id and current.get('angle_index') == index:
        return
    by_id = {i['asset_id']: i for i in p['items']}
    for source in sources:
        item = by_id.get(source['id'])
        if item and item['status'] == 'not_fit':
            raise assets.Conflict('「%s」已设为本项目不采用，请调整材料决定或重新分析' % source['title'])
        if item and not assets.reference_matches(source, item['asset_revision'], item['snapshot']):
            raise assets.Conflict('「%s」在本项目中使用旧版本，请先更新引用' % source['title'])
    for source in sources:
        item = by_id.get(source['id'])
        if not item or item['status'] != 'adopted':
            _adopt_asset(p, source, item, '用于选题切口「%s」' % angle['title'])
    p['topic_angle'] = {k: angle[k] for k in ('title', 'summary', 'supported_scope', 'gap')}
    p['topic_angle'].update(run_id=run_id, angle_index=index, asset_ids=[a['id'] for a in sources],
                            chosen_at=store.now())


def _approved_items(p):
    scope = set(_draft_scope(p))
    adopted = [i for i in p['items'] if i['status'] == 'adopted' and i['asset_id'] in scope]
    if not adopted:
        if _explicit_draft_scope(p):
            raise ValueError('请先为当前稿确认至少一条引用材料')
        raise ValueError('请先采用至少一条材料')
    if any(i['quality_issues'] for i in adopted):
        raise ValueError('已采纳材料存在文本残缺或结构异常，请修订材料或标为本项目不采用后再交付')
    bad = [i for i in adopted if i['stale'] or i['current_status'] != 'approved' or not i['evidence_valid']]
    if bad:
        raise ValueError('已采纳材料中有待审、失效或过期内容，请核对后再交付')
    return adopted


def _reviewable(p):
    if not p.get('draft', '').strip():
        raise ValueError('请先生成或填写资料包正文')
    if p['kind'] == 'marketing':
        marketing = marketing_tasks.context(p['brief'], {r['code']: r for r in store.library_rows()})
    decorated = _decorate(p)
    issues = decorated['draft_reference_issues']
    conflict = next((i for i in issues if i['kind'] in ('not_adopted', 'marker')), None)
    if conflict:
        raise ValueError('请先核对当前稿引用：「%s」%s' % (conflict['title'], conflict['reason']))
    adopted = _approved_items(decorated)
    if p['kind'] == 'marketing':
        marketing_tasks.require_evidence(marketing, [i['snapshot'] for i in adopted])
    if issues:
        raise ValueError('正文引用版本已过期，请核对当前稿引用后再审核')
    return adopted


def _markdown(p, items, mode, draft_issues=()):
    config = marketing_tasks.normalize(p.get('brief') or {}) if p['kind'] == 'marketing' else {}
    if config.get('marketing_task') == 'channel':
        document = marketing_delivery.channel_document(
            p.get('draft'), config['channels'], (p.get('draft_generation') or {}).get('source_labels') or {}, p['title'])
        if mode == 'review' and draft_issues:
            return '> 审阅稿：引用尚待核对，确认后再使用。\n\n' + document['text']
        return document['text']
    if (p['kind'] == 'marketing' and
            (p.get('draft_generation') or {}).get('plan_delivery_version') == '1.0'):
        # This marker is set when applying a new plan. Export the current edited
        # manuscript; never replace its contents with the original model result.
        text = marketing_delivery.clean_markers(p.get('draft') or '',
                   (p.get('draft_generation') or {}).get('source_labels') or {}).strip()
        if not text:
            raise ValueError('请先填写方案正文，再下载。')
        if mode == 'review' and draft_issues:
            text = '> 审阅稿：引用尚待核对，确认后再使用。\n\n' + text
        return text
    lines = ['# ' + p['title'], '', '版本：%s · %s' % (p['revision'], '已审核交付稿' if mode == 'approved' else '审阅稿，含待核内容'), '',
             '## 任务说明', '']
    labels = {'topic': '主题', 'audience': '目标读者', 'goal': '目标', 'channel': '渠道', 'new_book_brief': '新书资料', 'writing_notes': '补充写作要求'}
    for k, label in labels.items():
        if p['brief'].get(k):
            lines.append('- %s：%s' % (label, p['brief'][k]))
    if p['kind'] == 'marketing':
        config = marketing_tasks.normalize(p['brief'])
        lines.append('- 营销任务：' + marketing_tasks.TASKS[config['marketing_task']])
        codes = config['target_codes'] if config['marketing_task'] in ('theme', 'channel') else [p['brief'].get('source_code')]
        books = {i['snapshot']['code']: i['snapshot']['book'] for i in items}
        if any(codes):
            lines.append('- 推广图书：' + '、'.join(books.get(c, c) for c in codes if c))
        if config['channels']:
            lines.append('- 制作渠道：' + '、'.join(config['channels']))
    lines += ['', '## 正文', '']
    if draft_issues:
        def clarify_original_number(text):
            return CITATION_MARKER.sub(lambda match: '原编号 ' + match[1], text)
        lines += ['> 当前稿引用待核对，本版本供内部审阅。'] + [
            '> %s：%s' % (clarify_original_number(issue['title']), clarify_original_number(issue['reason']))
            for issue in draft_issues
        ] + ['']
    labels = _draft_display_labels(p)
    original_labels = (p.get('draft_generation') or {}).get('source_labels') or {}
    by_label = {label: aid for aid, label in original_labels.items()}

    def display_marker(match):
        aid = by_label.get(match[1])
        if aid in labels:
            return '[%s]' % labels[aid]
        if aid:
            return '〔旧出处，待核对〕'
        return '〔出处待核对〕' if _explicit_draft_scope(p) else match[0]

    draft = CITATION_MARKER.sub(display_marker, p.get('draft') or '尚未编写正文')
    lines += [draft, '', '## 材料与来源', '']
    order = {aid: index for index, aid in enumerate(labels)}
    for i in sorted(items, key=lambda item: order.get(item['asset_id'], len(order))):
        a = i['snapshot']
        source_label = '[%s] ' % labels[i['asset_id']] if i['asset_id'] in labels else ''
        lines += ['### ' + source_label + a['title'], '', a['text'], '', '来源：《%s》· %s · 资产版本 %s' % (a['book'], a['code'], i['asset_revision'])]
        if mode == 'review':
            lines.append('项目决定：%s；资产状态：%s%s' % (i['status'], i.get('current_status', a['status']), '；引用已过期' if i.get('stale') else ''))
            for warning in i.get('quality_issues') or []:
                lines.append('待核问题：' + warning['message'])
        for e in a.get('evidence', []):
            lines += ['> ' + e['quote'].replace('\n', '\n> '), '> 原文位置：' + e['anchor']]
        if i.get('note'):
            lines += ['采用理由／备注：' + i['note']]
        lines.append('')
    lines += ['## 待补与使用记录', '', '请结合本项目任务核对材料适用性；使用记录保留在项目中。']
    return '\n'.join(lines)


def update_project(pid, body):
    result = {}
    confirmed_now = False
    with store._lock('projects'):
        p = _read(pid)
        if body.get('revision') != p['revision']:
            raise assets.Conflict('项目已更新，请刷新后重试')
        action = body.get('action') or 'save'
        if action == 'save':
            changed = False
            draft_changed = False
            initial_draft = not (p['draft'] or p.get('draft_asset_revisions') or p.get('draft_refs_confirmed'))
            rebuild = body.get('rebuild_draft', False)
            if 'title' in body:
                title = str(body['title']).strip()[:160]
                if not title:
                    raise ValueError('项目名称不能为空')
                changed |= title != p['title']
                p['title'] = title
            if 'brief' in body:
                b = _brief(body['brief'])
                if b != p['brief']:
                    p.pop('topic_angle', None)
                    changed = True
                p['brief'] = b
            if 'draft' in body:
                d = str(body['draft'])[:100000]; draft_changed = d != p['draft']; changed |= draft_changed; p['draft'] = d
            if 'draft_asset_ids' in body:
                ids = body['draft_asset_ids']
                if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
                    raise ValueError('正文引用列表无效')
                if ids != p.get('draft_asset_ids', []) and not (initial_draft or rebuild):
                    raise ValueError('请使用「核对当前稿引用」调整现稿的来源清单')
                changed |= ids != p.get('draft_asset_ids', []); p['draft_asset_ids'] = ids
            # Typing in the manuscript does not verify a newer source version.
            if rebuild or (initial_draft and draft_changed):
                p.pop('draft_refs_confirmed', None)
                if rebuild and p.get('draft_generation'):
                    p['draft_generation'].pop('topic_angle_title', None)
                refs = {i['asset_id']: i['asset_revision'] for i in p['items']}
                if not p.get('draft_asset_ids'):
                    p['draft_asset_ids'] = [i['asset_id'] for i in p['items'] if i['status'] == 'adopted']
                p['draft_asset_revisions'] = {aid: refs.get(aid) for aid in _draft_scope(p)}
                changed = True
            if changed:
                _invalidate(p)
            if 'status' in body:
                status = body['status']
                if status not in STATUSES:
                    raise ValueError('项目状态无效')
                if status in ('approved', 'delivered', 'used'):
                    raise ValueError('请通过审核、导出和使用反馈更新该状态')
                p['status'] = status
        elif action == 'reconcile_draft_refs':
            _reconcile_draft_refs(p, body)
        elif action == 'adopt_recommendation':
            confirmed_now = _adopt_recommendation(p, body)
        elif action == 'adopt_topic_angle':
            _adopt_topic_angle(p, body)
        elif action == 'confirm_collected_material':
            aid = body.get('asset_id')
            item = next((i for i in p['items'] if i['asset_id'] == aid), None)
            if not item:
                raise ValueError('项目材料不存在')
            asset = assets.get_asset(aid)
            if (body.get('asset_revision') != item['asset_revision'] or
                    not assets.reference_matches(asset, item['asset_revision'], item['snapshot'])):
                raise assets.Conflict('引用的内容或出处已变化，请刷新项目，核对并更新引用后再确认')
            _confirm_asset_content(asset)
            return {'project': _decorate(p)}
        elif action == 'add_asset':
            item = _collected_item(body.get('asset_id'), body.get('note'))
            if any(i['asset_id'] == item['asset_id'] for i in p['items']):
                raise ValueError('该材料已在项目中')
            p['items'].append(item)
            # Collection is not adoption: a new relationship or marketing profile
            # candidate is not yet part of an existing manuscript or its review.
            collect_only = (item['snapshot'].get('source_type') == 'graph_relation' or
                            (p['kind'] == 'marketing' and item['snapshot']['kind'] == 'marketing'))
            if not collect_only:
                _invalidate_material_change(p, item['asset_id'])
        elif action in ('remove_asset', 'update_item', 'refresh_asset'):
            i = next((i for i in p['items'] if i['asset_id'] == body.get('asset_id')), None)
            if not i:
                raise ValueError('项目材料不存在')
            if action == 'remove_asset':
                p['items'].remove(i)
            elif action == 'refresh_asset':
                a = assets.get_asset(i['asset_id'])
                if not a or a['status'] == 'rejected':
                    raise ValueError('资产已失效，无法替换引用')
                i.update(snapshot=a, asset_revision=a['revision'], status='selected')
            else:
                if 'status' in body:
                    if body['status'] not in ('selected', 'adopted', 'not_fit'):
                        raise ValueError('材料决定无效')
                    i['status'] = body['status']
                    if i['status'] == 'adopted':
                        _include_in_topic_angle(p, i['asset_id'])
                if 'note' in body:
                    i['note'] = str(body['note'])[:4000]
            _invalidate_material_change(p, i['asset_id'])
        elif action == 'apply_generation':
            import project_assist
            project_assist.apply_to_project(p, body.get('run_id'))
            p.pop('draft_refs_confirmed', None)
            _invalidate(p)
        elif action == 'review':
            if body.get('approved', True):
                items = _reviewable(p)
                p['draft_review'] = {'id': 'review-' + secrets.token_hex(8), 'draft_hash': assets.digest(p['draft']), 'at': store.now(), 'actor': '本地编辑',
                                     'assets': {i['asset_id']: i['asset_revision'] for i in items}}
                p['status'] = 'approved'
            else:
                _invalidate(p)
        elif action == 'export':
            mode = body.get('mode') or 'review'
            if mode not in ('review', 'approved'):
                raise ValueError('导出类型无效')
            draft_issues = ()
            if mode == 'approved':
                items = _reviewable(p)
                review = p.get('draft_review') or {}
                if review.get('draft_hash') != assets.digest(p['draft']) or review.get('assets') != {i['asset_id']: i['asset_revision'] for i in items}:
                    raise ValueError('正文或材料尚未审核，请先完成审核')
            else:
                decorated = _decorate(p)
                scope = set(_draft_scope(p)) if _explicit_draft_scope(p) else None
                items = [i for i in decorated['items'] if i['status'] != 'not_fit' and
                         (scope is None or i['asset_id'] in scope)]
                draft_issues = decorated['draft_reference_issues']
            text = _markdown(p, items, mode, draft_issues)
            export_id = 'export-' + secrets.token_hex(8)
            filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', p['title']) + ('_交付稿.md' if mode == 'approved' else '_审阅稿.md')
            export = {'id': export_id, 'project_id': p['id'], 'filename': filename, 'mode': mode,
                      'review_id': (p.get('draft_review') or {}).get('id') if mode == 'approved' else None,
                      'draft_hash': assets.digest(p['draft']),
                      'project_revision': p['revision'], 'created_at': store.now(),
                      'asset_revisions': {i['asset_id']: i['asset_revision'] for i in items}, 'text': text}
            config = marketing_tasks.normalize(p.get('brief') or {}) if p['kind'] == 'marketing' else {}
            if config.get('marketing_task') == 'channel':
                export.update(content_kind='channel_content', channels=config['channels'])
            elif p['kind'] == 'marketing' and (p.get('draft_generation') or {}).get('plan_delivery_version') == '1.0':
                export.update(content_kind='marketing_plan')
            store.write_json(os.path.join(DIR, 'exports', export_id + '.json'), export)
            p['exports'].append({k: v for k, v in export.items() if k != 'text'})
            if mode == 'approved':
                p['status'] = 'delivered'
            result.update(filename=filename, text=text, export=p['exports'][-1])
        elif action == 'feedback':
            outcome = body.get('outcome')
            if outcome not in ('used', 'not_used', 'needs_revision'):
                raise ValueError('请说明实际使用结果')
            if outcome == 'used' and not any(e['mode'] == 'approved' for e in p['exports']):
                raise ValueError('请先导出已审核交付稿，再记录实际使用')
            if outcome == 'used' and not body.get('export_id'):
                raise ValueError('请选择实际使用的已审核交付版本')
            eligible = [e for e in p['exports'] if outcome != 'used' or e['mode'] == 'approved']
            chosen = next((e for e in eligible if e['id'] == body.get('export_id')), None) if body.get('export_id') else (eligible[-1] if eligible else None)
            if body.get('export_id') and chosen is None:
                raise ValueError('交付版本不存在或不符合使用条件')
            current_review = p.get('draft_review') or {}
            current_export = bool(chosen and chosen.get('review_id') and chosen.get('review_id') == current_review.get('id')
                                  and chosen.get('draft_hash') == assets.digest(p['draft']))
            if current_export:
                try:
                    _reviewable(p)
                except ValueError:
                    current_export = False
            p['feedback'].append({'outcome': outcome, 'note': str(body.get('note') or '')[:4000],
                                  'channel': str(body.get('channel') or '')[:300], 'created_at': store.now(),
                                  'export_id': chosen['id'] if chosen else None, 'applies_to_current_draft': current_export})
            if current_export or (chosen is None and outcome != 'used'):
                p['status'] = 'used' if outcome == 'used' else ('draft' if outcome == 'needs_revision' else 'paused')
                if outcome == 'needs_revision':
                    p['draft_review'] = None
        else:
            raise ValueError('项目操作无效')
        p['revision'] += 1
        p['updated_at'] = store.now()
        try:
            store.write_json(_path(pid), p)
        except OSError as err:
            if confirmed_now:
                raise ValueError('内容已确认，项目选择暂未保存。请刷新后重试。') from err
            raise
    result['project'] = _decorate(p)
    return result
