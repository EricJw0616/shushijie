# -*- coding: utf-8 -*-
"""解析任务执行器。

服务端只负责收文件、建 job；真正跑引擎的是这个子进程。
好处：引擎崩了不会带崩 Web 服务；任务日志与进度都能落盘，刷新页面还能接着看。

用法：python3 runner.py <job_id>
"""
import os
import shutil
import sys
import traceback

import engine_bridge as E
import ingest
import store
import kg_build as KG


UPLOAD_STEPS = [
    {'key': 'parse', 'label': '读取原书和版面', 'progress': 15},
    {'key': 'judge', 'label': '识别章节和可用内容', 'progress': 42},
    {'key': 'metadata', 'label': '整理出版信息', 'progress': 47},
    {'key': 'entities', 'label': '整理人名、地名等名称', 'progress': 70},
    {'key': 'quotes', 'label': '查找可引用的原句', 'progress': 81},
    {'key': 'themes', 'label': '整理有出处的主题', 'progress': 85},
    {'key': 'marketing', 'label': '整理营销资料', 'progress': 87},
    {'key': 'audit', 'label': '检查章节和出处', 'progress': 90},
    {'key': 'export', 'label': '更新内容成果和搜索', 'progress': 95},
    {'key': 'pages', 'label': '更新图书档案', 'progress': 98},
    {'key': 'kg', 'label': '生成关系图谱索引', 'progress': 99},
    {'key': 'store', 'label': '保存到图书库', 'progress': 100},
]

RESTORE_STEPS = [
    {'key': 'restore_files', 'label': '还原底本与产物', 'progress': 15},
    {'key': 'judge', 'label': '重跑判型 / 切段 / 候选卡', 'progress': 55},
    {'key': 'export', 'label': '重建汇总资产库', 'progress': 82},
    {'key': 'store', 'label': '恢复图书库记录', 'progress': 100},
]


def _steps_with_status(steps):
    return [dict(s, status='pending', detail='') for s in steps]


def _set_step(job_id, key, status, detail='', fraction=None):
    job = store.get_job(job_id)
    if not job:
        return
    steps = job.get('steps') or []
    progress = job.get('progress') or 0
    for index, s in enumerate(steps):
        if s.get('key') == key:
            s['status'] = status
            if detail:
                s['detail'] = str(detail)[:800]
            if status in ('done', 'partial', 'skipped'):
                progress = max(progress, s.get('progress') or progress)
            elif status == 'running' and fraction is not None:
                start = steps[index - 1]['progress'] if index else 0
                progress = max(progress, start + int((s['progress'] - start - 1) * fraction))
            store.update_job(job_id, steps=steps, progress=progress)
            return


def _batch_progress(job_id, key):
    def report(completed, total):
        if total and completed < total:
            detail = f'正在检查第 {completed + 1} 批，共 {total} 批。'
        else:
            detail = '正在核对并保存结果。'
        _set_step(job_id, key, 'running', detail, completed / total if total else 0)
    return report


def _log(job_id, text):
    store.append_job_log(job_id, text)
    if str(text).startswith(('⚠', '! ')):
        job = store.get_job(job_id) or {}
        warnings = list(job.get('warnings') or [])
        if text not in warnings:
            warnings.append(str(text)[:800])
            store.update_job(job_id, warnings=warnings)



def _tail(out, err, n=8):
    lines = []
    for block in (out or '', err or ''):
        lines += [x for x in block.strip().splitlines() if x.strip()]
    return '\n'.join(lines[-n:])


def _run(job_id, script, args=None, soft=False, label=''):
    rc, out, err = E.run_script(script, args)
    if out or err:
        _log(job_id, '%s\n%s' % (label or script, _tail(out, err)))
    if rc != 0:
        msg = (label or '处理这本书') + '未完成。'
        if soft:
            _log(job_id, '⚠ ' + msg + '其他步骤可以继续。')
            return False
        raise RuntimeError(msg)
    return True


def _finish(job_id, **fields):
    job = store.get_job(job_id) or {}
    warnings = job.get('warnings') or []
    store.update_job(job_id, status='partial' if warnings else 'done', progress=100,
                     finished_at=store.now(), **fields)


def _quality(job_id, code):
    """只检查本次图书，不再执行固定历史样书的质检脚本。"""
    import cards
    import tocclean
    folder = os.path.join(E.OUT, code)
    segs = store.read_jsonl(os.path.join(folder, 'segments.jsonl'))
    outline = store.read_jsonl(os.path.join(folder, 'outline.jsonl'))
    rows = store.read_jsonl(os.path.join(folder, 'cards.jsonl'))
    _, dropped, why = cards.verify(rows, segs)
    audit = tocclean.audit(segs, outline)
    issues = []
    if not segs:
        issues.append('没有可核验的正文段落')
    if dropped:
        issues.append('%d 条候选不能定位到原文：%s' % (dropped, '；'.join(map(str, why[:3]))))
    if audit.get('异常') or audit.get('结构待复核'):
        issues.append(audit.get('说明') or '结构需要复核')
    report = {'code': code, 'checked_at': store.now(), 'status': 'needs_review' if issues else 'passed',
              'segments': len(segs), 'cards': len(rows), 'invalid_anchors': dropped,
              'structure': audit, 'issues': issues}
    store.write_json(os.path.join(folder, 'quality.json'), report)
    book = E.book_json(code)
    if book:
        book['结构审计'] = audit
        book['质量状态'] = report['status']
        store.write_json(os.path.join(folder, 'book.json'), book)
    if issues:
        _log(job_id, '⚠ 本书质量待复核：' + '；'.join(issues))
    return report


def _refresh(job_id, code, rebuild_cards=False):
    if rebuild_cards:
        import tag_all
        tag_all.build_cards(code)
    _run(job_id, 'export.py', label='更新统一资产')
    _run(job_id, 'taglib.py', label='更新检索标签')
    if os.environ.get('BOOKDISTILL_AUTO_GRAPH') == '1' or os.path.isfile(os.path.join(store.DATA, 'kg', code + '.json')):
        try:
            KG.auto_build(code, force=True)
        except Exception as e:
            _log(job_id, '⚠ 关系图更新没完成：%s' % e)


def _book_by_title(title):
    return next((b for b in E.books_json() if b.get('book') == title), None)


def _title_exists(title):
    for r in store.library_rows():
        if r.get('book') == title:
            return True
    return os.path.exists(os.path.join(E.RAW, title + '.txt'))


def _status_for(book):
    audit = book.get('结构审计') or {}
    return 'pending' if audit.get('异常') or audit.get('结构待复核') else 'ready'


def _fail(job_id, msg, title='', raw_created=False):
    _log(job_id, '✗ ' + str(msg))
    job = store.get_job(job_id) or {}
    # 如果还没有进 books.json，把 raw 移到 failed，避免下次全库重跑捡到半本书。
    b = _book_by_title(title) if title and raw_created else None
    code = (b or {}).get('code')
    if code:
        # 流水线已经写进 books.json，但后续步骤失败：补一条失败记录，
        # 让书架能看到它并允许删除，而不是下次 sync 把它冒充成基准库。
        rec = store.get_record(code) or {}
        rec.update({'code': code, 'book': title, 'source': 'upload',
                    'source_format': job.get('source_format'), 'original_job': job.get('original_job') or job_id,
                    'status': 'failed', 'error': str(msg),
                    'updated_at': store.now(), 'last_job': job_id})
        store.upsert_book(rec)
    if raw_created and title and not b:
        src = os.path.join(E.RAW, title + '.txt')
        if os.path.exists(src):
            dst_dir = os.path.join(store.FAILEDDIR, job_id)
            os.makedirs(dst_dir, exist_ok=True)
            try:
                shutil.move(src, os.path.join(dst_dir, title + '.txt'))
                layout = os.path.splitext(src)[0] + '.layout.jsonl'
                if os.path.exists(layout):
                    shutil.move(layout, os.path.join(dst_dir, os.path.basename(layout)))
                _log(job_id, '已留存读取结果，可以继续处理。')
            except Exception:
                pass
    steps = job.get('steps') or []
    for step in steps:
        if step.get('status') == 'running':
            step.update(status='failed', detail=str(msg))
    store.update_job(job_id, status='failed', error=str(msg), steps=steps,
                     finished_at=store.now(), book_code=code or '')
    return code


def recover_upload(job):
    title = job.get('title') or ''
    raw_path = os.path.join(E.RAW, title + '.txt')
    if not title or job.get('raw_path') != raw_path or not os.path.isfile(raw_path):
        return False
    _fail(job['id'], '处理因服务重启中断，已保留文件。', title=title, raw_created=True)
    return True


def _annotate_clc(job_id, code):
    """中图分类只是展示分类，判错不影响产物，所以失败也不阻断入库。"""
    try:
        import cip as CIP
        CIP.annotate(code)          # 版权页优先；无版权页则原样保留
        import clc as CLC
        sug = CLC.annotate(code)
        if sug and sug.get('代码'):
            _log(job_id, '中图分类建议：%s %s（%s）' % (sug['代码'], sug.get('名称') or '', sug.get('置信') or '-'))
        return sug
    except Exception as e:
        _log(job_id, '⚠ 中图分类建议失败（不影响入库）：%s' % e)
        return None


def _judge(job_id, code):
    """判定层：逐列适用性。没配模型或调用失败都不影响入库。"""
    try:
        import llm
        if not llm.ready():
            _log(job_id, '未配置模型，跳过逐列判定')
            return
        import judge
        cols, usage = judge.judge(code)
        judge_path = os.path.join(E.OUT, code, 'judge.json')
        result = store.read_json(judge_path, {})
        result['source_version'] = E.book_json(code).get('source_version')
        store.write_json(judge_path, result)
        on = [k for k, v in cols.items() if v.get('适用')]
        _log(job_id, '逐列判定 %d/%d 适用：%s（tokens %s）'
             % (len(on), len(cols), '、'.join(on), usage.get('total_tokens')))
        return True
    except Exception as e:
        _log(job_id, '⚠ 逐列判定失败（不影响入库）：%s' % e)


def _understanding(job_id, code):
    """理解层默认生成金句与议题；设 BOOKDISTILL_UNDERSTANDING=0 可关闭。"""
    if os.environ.get('BOOKDISTILL_UNDERSTANDING') == '0':
        for key in ('quotes', 'themes'):
            _set_step(job_id, key, 'skipped', '本次未安排。')
        return 'not_requested'
    import understanding
    job = store.get_job(job_id) or {}
    saved = store.read_json(os.path.join(E.OUT, code, 'understanding.json'), {}) or {}
    status = 'done'
    for key, label, collect in (('quotes', '摘录', understanding.quotes), ('themes', '主题', understanding.themes)):
        if job.get('retry_of') and (saved.get('processing', {}).get(key) or {}).get('status') == 'done':
            _set_step(job_id, key, 'done', f'沿用已整理的 {len(saved.get(key) or [])} 条{label}。')
            continue
        _set_step(job_id, key, 'running')
        try:
            items, stats = collect(code, on_progress=_batch_progress(job_id, key), retain_prior=bool(job.get('retry_of')))
        except Exception:
            items, stats = saved.get(key) or [], {'blocked': 1}
            traceback.print_exc()
        detail = f'目前有 {len(items)} 条可回查原文的{label}。'
        if stats.get('blocked'):
            _log(job_id, f'⚠ 部分{label}没通过核对或未能整理，{detail}')
            _set_step(job_id, key, 'partial', detail)
            status = 'partial'
        else:
            _set_step(job_id, key, 'done', detail if items else f'本次未找到有充分依据的{label}。')
    return status


def _entities(job_id, code):
    """五类专名：入库就跑；设 BOOKDISTILL_ENTITIES=0 可关。失败不影响入库。"""
    if os.environ.get('BOOKDISTILL_ENTITIES') == '0':
        return 'not_requested'
    import tag_all
    try:
        rows = tag_all.build_entities(code, on_progress=_batch_progress(job_id, 'entities'))
        from collections import Counter
        c = Counter(r['cat'] for r in rows)
        _log(job_id, '五类专名 %d 条：地名 %d / 机构 %d / 器物 %d / 动物 %d / 植物 %d'
             % (len(rows), c.get('place', 0), c.get('org', 0), c.get('object', 0),
                c.get('animal', 0), c.get('plant', 0)))
        return 'done'
    except tag_all.NamesNeedReview as error:
        _log(job_id, '⚠ ' + str(error))
        return 'blocked'
    except Exception as e:
        _log(job_id, '⚠ 有些名称还没整理完成，可以稍后补查。')
        traceback.print_exc()
        return 'failed'


def _marketing(job_id, code):
    """营销 7 项：默认不跑（要花模型钱）；显式设 BOOKDISTILL_MARKETING=1 才跑。"""
    if os.environ.get('BOOKDISTILL_MARKETING') != '1':
        return 'not_requested'
    try:
        import tag_all
        rec = tag_all.build_marketing(code)
        s = rec.get('stats') or {}
        _log(job_id, '营销草稿：%d 类、%d 条素材，证据 %d 条，丢弃 %d'
             % (s.get('available_categories', 0), s.get('usable_items', 0), s.get('evidence', 0), s.get('dropped', 0)))
        return 'done'
    except Exception as e:
        _log(job_id, '⚠ 营销草稿失败（不影响入库）：%s' % e)
        return 'failed'


def _page_roles(job_id, code):
    """第 2 期：页面结构 12 项。失败不阻断入库。"""
    try:
        import pages as PG
        rec = PG.build(code)
        PG.write(rec)
        s = rec.get('stats') or {}
        _log(job_id, '页面结构：%d/12 项，正文 %s-%s，标题 %s 条'
             % (s.get('found', 0), s.get('body_from'), s.get('body_to'), s.get('headings', 0)))
    except Exception as e:
        _log(job_id, '⚠ 页面结构识别失败（不影响入库）：%s' % e)


def _publication(job_id, code, title='', author='', publisher=''):
    """第 1 期：出版信息 19 项。失败不阻断入库。"""
    try:
        import publication as PUB
        lib = {code: {'book': title, 'author': author, 'publisher': publisher}}
        rec = PUB.build(code, lib)
        PUB.write(rec)
        s = rec['stats']
        _log(job_id, '出版信息：有值 %d / 未找到 %d / 待复核 %d（共 19 项）'
             % (s['found'], s['not_found'], s['needs_review']))
    except Exception as e:
        _log(job_id, '⚠ 出版信息抽取失败（不影响入库）：%s' % e)


def _ocr_cover(job_id, code, src, title='', author='', publisher='', total_pages=0):
    """上传后对封面/前 10 页做 OCR，补原生文字层缺失的书名。

    默认关闭：设 BOOKDISTILL_OCR=1 才跑。OCR 依赖不塞进 Web 进程时，
    生产上应改为调用独立 OCR worker；这里保留同镜像私有化的最短路径。
    """
    if os.environ.get('BOOKDISTILL_OCR', '').lower() not in ('1', 'true', 'yes', 'on'):
        return
    if not src or not src.lower().endswith('.pdf'):
        return
    libpath = os.path.join(E.OUT, '.ocr-lib-%s.json' % code)
    try:
        import json
        import subprocess
        with open(libpath, 'w', encoding='utf-8') as fp:
            json.dump({'books': {code: {'book': title, 'author': author,
                                        'publisher': publisher}}},
                      fp, ensure_ascii=False)
        outdir = os.path.join(E.OUT, code, 'ocr')
        # 版权页可能在前，也可能在书末：前 10 + 后 10 一起扫。
        try:
            total = int(total_pages or 0)
        except Exception:
            total = 0
        pages = '1-10' if total <= 0 else ('1-%d' % min(10, total))
        if total > 10:
            start = max(11, total - 9)
            pages += ',%d-%d' % (start, total)
        cmd = [sys.executable, '-m', 'ocr.cli', '--code', code, '--pdf', src,
               '--pages', pages, '--force', '--library', libpath, '--outdir', outdir,
               '--dpi', '200']
        p = subprocess.run(cmd, cwd=E.ENGINE, capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            _log(job_id, '⚠ OCR 失败（不影响入库）：%s' % (p.stderr or p.stdout or '')[-300:])
            return
        try:
            with open(os.path.join(outdir, 'fields.json'), encoding='utf-8') as fp:
                f = (json.load(fp).get('fields') or {}).get('book_title') or {}
            if f.get('value'):
                _log(job_id, 'OCR：书名「%s」%s（%s）'
                     % (f.get('value'), f.get('status') or '', f.get('note') or ''))
        except Exception:
            pass
    except Exception as e:
        _log(job_id, '⚠ OCR 失败（不影响入库）：%s' % e)
    finally:
        try:
            os.remove(libpath)
        except OSError:
            pass


def _soft_pages(job_id):
    for script, label in (('cardboard.py', '候选卡资产库'),
                          ('board.py', '书库平台看板'),
                          ('tagboard.py', '图书标签数据库')):
        try:
            _run(job_id, script, soft=True, label=label)
        except Exception as e:
            _log(job_id, '⚠ 页面重建失败（不影响入库）：%s' % e)


def _upload_graph(job_id, code, segments):
    if os.environ.get('BOOKDISTILL_AUTO_GRAPH', '1') != '1':
        _set_step(job_id, 'kg', 'skipped', '当前设置已关闭自动建图。')
        return
    if not segments:
        _set_step(job_id, 'kg', 'skipped', '没有可用于建图的正文段落。')
        return
    _set_step(job_id, 'kg', 'running')
    try:
        graph = KG.auto_build(code)
        meta = graph['meta']
        _set_step(job_id, 'kg', 'done', '已整理「%s」，可在关系图谱中选择这本书。' % meta['form'])
    except (Exception, SystemExit) as exc:
        _set_step(job_id, 'kg', 'partial', '关系图谱生成失败，已保留解析结果。')
        _log(job_id, '⚠ 关系图谱生成未完成：%s' % exc)


def _scan_progress(job_id, checked, total):
    label = ('正在识别扫描页（OCR），已处理 %d/%d 页。' % (checked, total)
             if checked < total else '已检查 %d 页，正在合并识别结果。' % total)
    _set_step(job_id, 'parse', 'running', label, .25 + .75 * checked / total)


def _layout_progress(job_id, checked, total):
    if total:
        _set_step(job_id, 'parse', 'running', '正在读取 PDF 原有文字，已检查 %d/%d 页。' % (checked, total),
                  .25 * checked / total)


def run_upload(job_id):
    job = store.get_job(job_id)
    if not job:
        return
    title = job.get('title') or ''
    fmt = job.get('source_format') or ''
    src = job.get('source_path') or ''
    store.update_job(job_id, status='running', started_at=store.now(), steps=_steps_with_status(UPLOAD_STEPS))
    raw_created = False
    try:
        raw_path = os.path.join(E.RAW, title + '.txt')
        code = job.get('resume_code')
        data = {'pages': job.get('source_pages'), 'chars': job.get('source_chars'),
                'note': job.get('source_note'), 'ocr': job.get('source_ocr') or {},
                'page_issues': job.get('source_page_issues')}
        _set_step(job_id, 'parse', 'running')
        if code:
            record = store.get_record(code) or {}
            if record.get('last_job') != job.get('retry_of') or record.get('book') != title or not os.path.isfile(raw_path):
                raise RuntimeError('图书已更新，请打开当前档案继续。')
            raw_created = True
        else:
            if _title_exists(title):
                raise RuntimeError('库里已有《%s》。如果是不同版次，请在书名里注明版次。' % title)
            store.update_job(job_id, raw_path=raw_path)
            saved = os.path.join(store.FAILEDDIR, job.get('retry_of') or '', title + '.txt')
            layout_path = os.path.splitext(raw_path)[0] + '.layout.jsonl'
            if job.get('retry_of') and os.path.isfile(saved):
                shutil.copyfile(saved, raw_path)
                raw_created = True
                saved_layout = os.path.splitext(saved)[0] + '.layout.jsonl'
                if os.path.isfile(saved_layout):
                    shutil.copyfile(saved_layout, layout_path)
            else:
                data = ingest.extract(src, fmt,
                                      on_progress=lambda done, total: _scan_progress(job_id, done, total),
                                      on_layout_progress=lambda done, total: _layout_progress(job_id, done, total))
                ingest.write_text(raw_path, data['text'])
                raw_created = True
                if data.get('layout'):
                    ingest.write_layout(layout_path, data['layout'])
                store.update_job(job_id, source_han=data['han'])
            store.update_job(job_id, raw_path=raw_path, source_note=data.get('note'),
                             source_pages=data.get('pages'), source_chars=data.get('chars'),
                             source_ocr=data.get('ocr'), source_page_issues=data.get('page_issues'))
        _set_step(job_id, 'parse', 'done', data.get('note') or '已读取原书。')
        unread = (data['ocr'].get('failed') or 0) + (data['ocr'].get('unavailable') or 0)
        if unread:
            _log(job_id, '⚠ 有 %d 页的图片文字未能识别，建议对照 PDF 原页检查。' % unread)
        _set_step(job_id, 'judge', 'running')
        if not code:
            _run(job_id, 'pipeline.py', [title], label='识别章节和可用内容')
            code = (_book_by_title(title) or {}).get('code')
        if not code or not E.book_json(code):
            raise RuntimeError('章节整理没完成，可以用原文件重试。')
        bj = E.book_json(code)
        store.update_job(job_id, book_code=code, book_title=title)
        _set_step(job_id, 'judge', 'done', '识别了 %s 章、%s 段，找到 %s 条待核对内容。' %
                  (bj.get('篇数', 0), bj.get('段数', 0), bj.get('候选卡数', 0)))

        _set_step(job_id, 'metadata', 'running')
        _annotate_clc(job_id, code)
        if os.environ.get('BOOKDISTILL_EXTENDED_JUDGE') == '1':
            _judge(job_id, code)
        _page_roles(job_id, code)
        _ocr_cover(job_id, code, src, title, job.get('author') or '', job.get('publisher') or '',
                   data.get('pages') or 0)
        _publication(job_id, code, title, job.get('author') or '', job.get('publisher') or '')
        _set_step(job_id, 'metadata', 'done')
        outputs = dict(job.get('outputs') or {})
        for key, generate in (('entities', _entities), ('understanding', _understanding), ('marketing', _marketing)):
            if outputs.get(key) not in ('done', 'not_requested', 'blocked'):
                outputs[key] = _run_optional(job_id, code, key, generate)
                store.update_job(job_id, outputs=outputs)
            else:
                keys = ('quotes', 'themes') if key == 'understanding' else (key,)
                for step_key in keys:
                    state = {'done': 'done', 'not_requested': 'skipped', 'blocked': 'partial'}[outputs[key]]
                    _set_step(job_id, step_key, state, '沿用上次处理结果。')

        _set_step(job_id, 'audit', 'running')
        quality = _quality(job_id, code)
        _set_step(job_id, 'audit', 'partial' if quality['issues'] else 'done',
                  '；'.join(quality['issues']) or '已检查章节和出处。')
        _set_step(job_id, 'export', 'running')
        _run(job_id, 'export.py', label='更新图书和内容清单')
        _run(job_id, 'taglib.py', label='更新搜索标签')
        _set_step(job_id, 'export', 'done')

        _set_step(job_id, 'pages', 'running')
        page_warnings = len((store.get_job(job_id) or {}).get('warnings') or [])
        _soft_pages(job_id)
        _set_step(job_id, 'pages', 'partial' if len((store.get_job(job_id) or {}).get('warnings') or []) > page_warnings else 'done')
        _upload_graph(job_id, code, quality['segments'])

        _set_step(job_id, 'store', 'running')
        bj = E.book_json(code)
        status = _status_for(bj)
        previous = (store.get_record(code) or {}) if job.get('resume_code') else {}
        record = {'code': code, 'book': title, 'author': job.get('author') or '',
                  'publisher': job.get('publisher') or '', 'source': 'upload', 'status': status,
                  'confirmed': bool(previous.get('confirmed')), 'type_source': previous.get('type_source') or 'machine',
                  'added_at': previous.get('added_at') or store.now(), 'updated_at': store.now(),
                  'source_format': fmt, 'original_filename': job.get('original_filename') or '',
                  'original_job': job.get('original_job') or job_id,
                  'source_pages': data.get('pages') or 0, 'source_chars': data.get('chars') or 0,
                  'source_note': data.get('note') or '', 'last_job': job_id, 'error': ''}
        if data['ocr']:
            record['source_ocr'] = data['ocr']
        if data['page_issues'] is not None:
            record['source_page_issues'] = data['page_issues']
        store.upsert_book(record)
        store.append_op(code, 'upload', {'title': title, 'format': fmt, 'job': job_id, 'status': status,
                        'confidence': bj.get('置信'), 'prototype': bj.get('原型'), 'cards': bj.get('候选卡数')})
        _set_step(job_id, 'store', 'done', '已保存，部分内容待核对。' if status == 'pending' else '已保存。')
        _finish(job_id, result={'code': code, 'title': title, 'status': status,
                               'prototype': bj.get('原型'), 'prototype_name': bj.get('原型名'),
                               'confidence': bj.get('置信')})
        _log(job_id, '已入库：%s' % title)
    except ingest.IngestError as e:
        if not isinstance(e, ingest.OCRProcessingError):
            store.update_job(job_id, error_kind='source')
        if e.page_issues is not None:
            store.update_job(job_id, source_page_issues=e.page_issues)
        _fail(job_id, str(e), title=title, raw_created=raw_created)
    except Exception as e:
        traceback.print_exc()
        _fail(job_id, str(e), title=title, raw_created=raw_created)


def _run_optional(job_id, code, key, generate):
    if key == 'understanding':
        return generate(job_id, code)
    _set_step(job_id, key, 'running')
    status = generate(job_id, code)
    step_status, detail = {
        'done': ('done', '结果已保存。'),
        'not_requested': ('skipped', '本次未安排。'),
        'blocked': ('partial', '可以打开原文核对。'),
        'partial': ('partial', '已保留成果，可以继续处理。'),
        'failed': ('partial', '本次未完成，可以继续处理。'),
    }[status]
    _set_step(job_id, key, step_status, detail)
    return status


def run_upload_supplement(job_id):
    job = store.get_job(job_id)
    if not job:
        return
    code = job.get('book_code')
    stages = {'entities': _entities, 'understanding': _understanding, 'marketing': _marketing}
    selected = [key for key in stages if key in (job.get('parts') or [])]
    relevant = [step for step in UPLOAD_STEPS if step['key'] in selected
                or ('understanding' in selected and step['key'] in ('quotes', 'themes'))]
    steps = [dict(step, progress=round(90 * (i + 1) / len(relevant))) for i, step in enumerate(relevant)]
    steps.append({'key': 'export', 'label': '更新搜索和内容成果', 'progress': 100})
    store.update_job(job_id, status='running', started_at=store.now(), steps=_steps_with_status(steps))
    try:
        if not E.book_json(code):
            raise ValueError('没有可补做的内容。')
        outputs = {}
        for key in selected:
            status = _run_optional(job_id, code, key, stages[key])
            outputs[key] = status
            store.update_job(job_id, outputs=outputs)
        _set_step(job_id, 'export', 'running')
        _run(job_id, 'taglib.py', label='更新搜索标签')
        _set_step(job_id, 'export', 'done')
        _finish(job_id, book_code=code, result={'code': code})
    except Exception as e:
        traceback.print_exc()
        store.update_job(job_id, status='failed', finished_at=store.now(), error=str(e))


def run_restore(job_id):
    job = store.get_job(job_id)
    if not job:
        return
    trash_id = job.get('trash_id')
    tr = store.get_trash(trash_id) if trash_id else None
    store.update_job(job_id, status='running', started_at=store.now(),
                     steps=_steps_with_status(RESTORE_STEPS))
    if not tr:
        _fail(job_id, '回收站记录不存在')
        return
    title = tr.get('book') or ''
    try:
        _set_step(job_id, 'restore_files', 'running')
        raw_dest = os.path.join(E.RAW, title + '.txt')
        lay_dest = os.path.splitext(raw_dest)[0] + '.layout.jsonl'
        out_dest = os.path.join(E.OUT, tr.get('code'))
        # 先做完全部冲突检查再搬文件。旧写法是边搬边查：raw 已经搬回来，
        # 到 out 这一步才发现同码目录已存在，于是库里没书、raw 却在 raw/ 里，
        # 再点一次恢复又会因「同名文件」被拒。
        if not (tr.get('raw') and os.path.exists(tr['raw'])):
            raise RuntimeError('回收站里没有这本书的底本，无法恢复；只能重新上传。')
        if os.path.exists(raw_dest):
            raise RuntimeError('raw 目录里已经有同名文件，未覆盖。')
        if tr.get('out') and os.path.isdir(tr['out']) and os.path.isdir(out_dest):
            raise RuntimeError('out 目录里已经有同码目录，未覆盖。')
        if store.get_record(tr.get('code')):
            raise RuntimeError('同码图书已经在库，不能重复恢复。')
        if tr.get('raw') and os.path.exists(tr['raw']):
            shutil.move(tr['raw'], raw_dest)
        if tr.get('layout') and os.path.exists(tr['layout']) and not os.path.exists(lay_dest):
            shutil.move(tr['layout'], lay_dest)
        if tr.get('out') and os.path.isdir(tr['out']):
            shutil.move(tr['out'], out_dest)
        _set_step(job_id, 'restore_files', 'done')

        _set_step(job_id, 'judge', 'running')
        _run(job_id, 'pipeline.py', [title], label='恢复重跑')
        _set_step(job_id, 'judge', 'done')

        _set_step(job_id, 'export', 'running')
        _run(job_id, 'export.py', label='导出资产库')
        _run(job_id, 'taglib.py', label='生成标签库')
        _annotate_clc(job_id, tr.get('code'))
        if _judge(job_id, tr.get('code')):
            _refresh(job_id, tr.get('code'), rebuild_cards=True)
        _entities(job_id, tr.get('code'))
        _quality(job_id, tr.get('code'))
        _refresh(job_id, tr.get('code'))
        _soft_pages(job_id)
        _set_step(job_id, 'export', 'done')

        rec = tr.get('record') or {}
        rec.update({'code': tr.get('code'), 'book': title,
                    'updated_at': store.now(), 'last_job': job_id})
        store.upsert_book(rec)
        store.remove_trash(trash_id)
        store.append_op(tr.get('code'), 'restore', {'trash_id': trash_id, 'job': job_id})
        _set_step(job_id, 'store', 'done', '已恢复 %s' % title)
        _finish(job_id, book_code=tr.get('code'),
                         result={'code': tr.get('code'), 'title': title, 'status': 'restored'})
        _log(job_id, '✓ 已恢复：%s' % title)
    except Exception as e:
        traceback.print_exc()
        if trash_id:
            store.set_trash_flag(trash_id, 'restoring', None)
        _fail(job_id, str(e), title=title)


def run_retype(job_id):
    job = store.get_job(job_id)
    if not job:
        return
    title = job.get('title') or ''
    proto = job.get('prototype') or ''
    steps = [{'key': 'judge', 'label': '按人工判型重跑', 'progress': 55},
             {'key': 'export', 'label': '重建汇总资产库', 'progress': 85},
             {'key': 'store', 'label': '更新档案', 'progress': 100}]
    store.update_job(job_id, status='running', started_at=store.now(),
                     steps=_steps_with_status(steps))
    try:
        _set_step(job_id, 'judge', 'running')
        rc, out, err = E.run_script('pipeline.py', [title],
                                    env_extra={'BOOKDISTILL_PROTO': proto})
        _log(job_id, _tail(out, err))
        if rc != 0:
            raise RuntimeError('按 %s 重跑失败：%s' % (proto, _tail(out, err, 4)))
        b = _book_by_title(title)
        if not b:
            raise RuntimeError('重跑后 books.json 未找到这本书')
        code = b.get('code')
        _set_step(job_id, 'judge', 'done', '原型 %s %s' % (proto, E.PROTO_NAMES.get(proto, '')))
        _set_step(job_id, 'export', 'running')
        _annotate_clc(job_id, code)
        if os.environ.get('BOOKDISTILL_EXTENDED_JUDGE') == '1':
            _judge(job_id, code)
        _entities(job_id, code)
        _quality(job_id, code)
        _refresh(job_id, code)
        _soft_pages(job_id)
        _set_step(job_id, 'export', 'done')
        _set_step(job_id, 'store', 'running')
        rec = store.get_record(code) or {}
        rec.update({'code': code, 'book': title, 'prototype_override': proto,
                    'type_source': 'manual', 'status': _status_for(E.book_json(code)),
                    'confirmed': True, 'updated_at': store.now(),
                    'last_job': job_id})
        store.upsert_book(rec)
        store.append_op(code, 'retype', {'title': title, 'prototype': proto, 'job': job_id})
        _set_step(job_id, 'store', 'done', '人工判型：%s %s' % (proto, E.PROTO_NAMES.get(proto, '')))
        _finish(job_id, book_code=code,
                         result={'code': code, 'title': title, 'prototype': proto})
        _log(job_id, '✓ 已按 %s 重跑并入库' % proto)
    except Exception as e:
        traceback.print_exc()
        _fail(job_id, str(e), title=title)


def run_marketing(job_id):
    job = store.get_job(job_id) or {}
    code = job.get('book_code') or ''
    steps = [{'key': 'marketing', 'label': '生成营销草稿', 'progress': 90},
             {'key': 'store', 'label': '保存可追溯成果', 'progress': 100}]
    store.update_job(job_id, status='running', started_at=store.now(), steps=_steps_with_status(steps))
    try:
        if not code or not E.book_json(code):
            raise ValueError('图书不存在')
        import tag_all
        _set_step(job_id, 'marketing', 'running')
        # build失败时不写盘；原成果继续保留。
        rec = tag_all.build_marketing(code)
        stats = rec.get('stats') or {}
        _set_step(job_id, 'marketing', 'done', '已生成%d类、%d条营销素材，需按用途审核' %
                  (stats.get('available_categories', 0), stats.get('usable_items', 0)))
        _set_step(job_id, 'store', 'done')
        store.append_op(code, 'marketing_generate', {'job': job_id, 'stats': rec.get('stats') or {}})
        _finish(job_id, book_code=code, result={'code': code, 'stats': rec.get('stats') or {}})
    except Exception as e:
        _set_step(job_id, 'marketing', 'failed', str(e))
        _log(job_id, '✗ 营销生成失败，原成果保留：%s' % e)
        store.update_job(job_id, status='failed', finished_at=store.now(), error=str(e), book_code=code)


def run_summaries(job_id):
    """Generate chapter summaries only when explicitly requested by the editor."""
    job = store.get_job(job_id) or {}
    code = job.get('book_code') or ''
    steps = [{'key': 'summaries', 'label': '生成章节摘要', 'progress': 90},
             {'key': 'store', 'label': '保存成果与生成状态', 'progress': 100}]
    store.update_job(job_id, status='running', started_at=store.now(), steps=_steps_with_status(steps))
    try:
        if not code or not E.book_json(code):
            raise ValueError('图书不存在')
        import understanding
        _set_step(job_id, 'summaries', 'running')
        items, stats = understanding.summaries(code)
        blocked, kept = int(stats.get('blocked') or 0), int(stats.get('kept') or 0)
        status = ('partial' if kept else 'failed') if blocked else 'done'
        data = store.read_json(os.path.join(E.OUT, code, 'understanding.json'), {})
        attempt = (data.get('processing') or {}).get('summaries') or {}
        output = dict(stats, status=status, available=len(items),
                      retained_previous=bool(attempt.get('retained_previous')),
                      source_stale=bool(attempt.get('source_stale')))
        detail = '本次生成 %d 篇，失败 %d 篇；当前可查看 %d 篇' % (kept, blocked, len(items))
        if output['retained_previous']:
            detail += '，已保留上一份成果'
        _set_step(job_id, 'summaries', status, detail)
        _set_step(job_id, 'store', 'done', '成果与生成状态已保存')
        store.update_job(job_id, outputs={'summaries': output})
        store.append_op(code, 'summaries_generate', {'job': job_id, **output})
        result = {'code': code, 'stats': stats, 'available': len(items)}
        if status == 'failed':
            error = stats.get('last_error') or '章节摘要未生成成功'
            _log(job_id, '✗ ' + detail + '：' + error)
            store.update_job(job_id, status='failed', progress=100, finished_at=store.now(),
                             error=error, book_code=code, result=result)
        else:
            _log(job_id, ('⚠ ' if blocked else '') + detail)
            _finish(job_id, book_code=code, result=result)
    except Exception as e:
        _set_step(job_id, 'summaries', 'failed', str(e))
        _log(job_id, '✗ 章节摘要生成失败，已有成果保留：%s' % e)
        store.update_job(job_id, status='failed', finished_at=store.now(), error=str(e), book_code=code)


def run_tag(job_id):
    job = store.get_job(job_id) or {}
    code = job.get('book_code') or ''
    steps = [{'key': 'tags', 'label': '补查标签、摘录和摘要', 'progress': 75},
             {'key': 'audit', 'label': '检查章节和出处', 'progress': 90},
             {'key': 'export', 'label': '更新内容成果和搜索', 'progress': 100}]
    store.update_job(job_id, status='running', started_at=store.now(), steps=_steps_with_status(steps))
    try:
        if not code or not E.book_json(code):
            raise ValueError('图书不存在')
        import tag_all
        _set_step(job_id, 'tags', 'running')
        report = tag_all.run_one(code, include_marketing=False)
        for name in report.get('errors') or []:
            _log(job_id, '⚠ %s 补跑失败：%s' % (name, report['steps'][name].get('error', '')))
        store.update_job(job_id, outputs=report['steps'])
        _set_step(job_id, 'tags', 'partial' if report['errors'] else 'done')
        quality = _quality(job_id, code)
        _set_step(job_id, 'audit', 'partial' if quality['issues'] else 'done', '；'.join(quality['issues']))
        _set_step(job_id, 'export', 'running')
        _refresh(job_id, code)
        _set_step(job_id, 'export', 'done')
        store.append_op(code, 'tag', {'job': job_id, 'errors': report['errors']})
        _finish(job_id, book_code=code, result={'code': code, 'errors': report['errors']})
    except Exception as e:
        _log(job_id, '✗ 补跑失败，已有成果保留：%s' % e)
        store.update_job(job_id, status='failed', finished_at=store.now(), error=str(e), book_code=code)
    finally:
        marker = os.path.join(E.OUT, code, '.tagging')
        if os.path.exists(marker):
            os.remove(marker)


def main():
    if len(sys.argv) < 2:
        print('usage: python3 runner.py <job_id>')
        return 2
    job_id = sys.argv[1]
    job = store.get_job(job_id)
    if not job:
        print('job not found:', job_id)
        return 2
    kind = job.get('kind')
    if kind == 'upload':
        run_upload(job_id)
    elif kind == 'upload_supplement':
        run_upload_supplement(job_id)
    elif kind == 'restore':
        run_restore(job_id)
    elif kind == 'retype':
        run_retype(job_id)
    elif kind == 'marketing':
        run_marketing(job_id)
    elif kind == 'summaries':
        run_summaries(job_id)
    elif kind == 'tag':
        run_tag(job_id)
    elif kind == 'project_assist':
        import project_assist
        project_assist.execute_job(job_id)
    else:
        _fail(job_id, '未知任务类型：%s' % kind)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
