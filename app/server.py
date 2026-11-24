# -*- coding: utf-8 -*-
"""图书知识库 · 本地/服务器 HTTP 服务。

标准库实现，零 Web 框架依赖：
  - 图书库 / 书详情 / 原文 / 候选卡 / 标签
  - 上传 → 后台解析任务 → 入库
  - 软删除 / 回收站恢复
  - 后台：解析能力设置 / 档案 / 查询
  - 文件型存储（JSON/JSONL），不依赖 SQLite

启动：python3 app/server.py --port 8942
"""
import argparse
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import engine_bridge as E
import ingest
import hotspot
import kg_build as KG
import probe
import runner
import store
import assets_service
import projects
import source_names
import project_assist
import project_records
import marketing_state
import source_review
import pdf_source_preview

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(APP_DIR, 'static')

def asset_version():
    """前端资源版本号：取 app.js / app.css / index.html 的最新 mtime。
    页面里注入同一个值，前端启动时和 /api/version 对一次，对不上就自动刷新——
    避免一直开着的标签页用着旧 JS，却以为自己看到的是新版本。"""
    v = 0
    for name in os.listdir(STATIC):
        if not name.endswith(('.js', '.css', '.html', '.svg')):
            continue
        try:
            v = max(v, os.stat(os.path.join(STATIC, name)).st_mtime_ns)
        except OSError:
            pass
    return str(v or 0)

RUNNER = os.path.join(APP_DIR, 'runner.py')
JOB_LOCK = threading.Lock()
QA_SLOTS = threading.BoundedSemaphore(2)
XHS_UPLOAD_SLOTS = threading.BoundedSemaphore(2)
MAX_UPLOAD = ingest.MAX_BYTES

def _load_dotenv():
    """把 app/.env 读进环境变量（模型 key、访问口令都放这里）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    try:
        with io.open(path, encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_dotenv()
AUTH_USER = os.environ.get('BOOKDISTILL_USER') or ''
AUTH_PASS = os.environ.get('BOOKDISTILL_PASS') or ''

PROBEDIR = os.path.join(store.DATA, 'probe')
os.makedirs(PROBEDIR, exist_ok=True)
PROBE_TTL = 24 * 3600          # 预检文件留一天，够人改完书名再提交
LEGACY_MULTIPART_MAX = 200 * 1024 * 1024   # 老 multipart 路径整包进内存，不能放开


def _log(msg):
    try:
        with open(os.path.join(store.DATA, 'server.log'), 'a', encoding='utf-8') as fp:
            fp.write('%s %s\n' % (store.now(), msg))
    except Exception:
        pass


def _start_job(job_id):
    def worker():
        with JOB_LOCK:
            log_path = os.path.join(store.DATA, 'jobs', job_id + '.log')
            try:
                with open(log_path, 'w', encoding='utf-8') as log:
                    p = subprocess.Popen([sys.executable, RUNNER, job_id],
                                         cwd=APP_DIR, stdout=log,
                                         stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL,
                                         env=os.environ.copy())
                    p.wait()
                job = store.get_job(job_id)
                if job and job.get('status') in ('queued', 'running'):
                    store.update_job(job_id, status='failed',
                                     finished_at=store.now(),
                                     error='执行器异常退出，请查看任务日志或重试。')
            except Exception as e:
                _log('job %s crashed: %s' % (job_id, e))
                store.update_job(job_id, status='failed', finished_at=store.now(),
                                 error='执行器启动失败：%s' % e)
    threading.Thread(target=worker, daemon=True).start()


def _parse_multipart(body, boundary):
    delim = b'--' + boundary
    out = {}
    for part in body.split(delim):
        part = part.strip(b'\r\n')
        if not part or part == b'--':
            continue
        if b'\r\n\r\n' not in part:
            continue
        head, data = part.split(b'\r\n\r\n', 1)
        headers = head.decode('utf-8', 'replace').split('\r\n')
        disp = ''
        for h in headers:
            if h.lower().startswith('content-disposition:'):
                disp = h
                break
        m_name = re.search(r'name="([^"]*)"', disp)
        m_file = re.search(r'filename="([^"]*)"', disp)
        if not m_name:
            continue
        name = m_name.group(1)
        data = data.rstrip(b'\r\n')
        if m_file:
            out[name] = {'filename': m_file.group(1), 'data': data}
        else:
            out[name] = data.decode('utf-8', 'replace')
    return out


def _gc_probe(ttl=PROBE_TTL):
    """清掉过期的预检临时文件。预检目录可能存着几百 MB 的原件。"""
    try:
        now = time.time()
        for name in os.listdir(PROBEDIR):
            p = os.path.join(PROBEDIR, name)
            try:
                if os.path.isdir(p) and now - os.path.getmtime(p) > ttl:
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def _probe_meta(token):
    if not re.fullmatch(r'[0-9a-f]{16,64}', token or ''):
        return None
    d = os.path.join(PROBEDIR, token)
    try:
        with open(os.path.join(d, 'meta.json'), encoding='utf-8') as fp:
            meta = json.load(fp)
    except Exception:
        return None
    p = meta.get('path') or ''
    if not p or not os.path.isfile(p):
        return None
    return meta


class Handler(BaseHTTPRequestHandler):
    server_version = 'BookWorld/0.1'
    protocol_version = 'HTTP/1.1'

    # ---------- 基础响应 ----------
    def _send(self, body, status=200, ctype='application/json; charset=utf-8',
              extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json(self, obj, status=200):
        self._send(obj, status=status)

    def _err(self, msg, status=400):
        self._json({'ok': False, 'error': str(msg)}, status=status)

    def _read_json(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except Exception:
            n = 0
        if n <= 0:
            return {}
        if n > 2 * 1024 * 1024:
            raise ValueError('请求体过大')
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode('utf-8'))
        except Exception:
            raise ValueError('请求体不是合法 JSON')

    def _qs(self):
        u = urllib.parse.urlparse(self.path)
        return u.path, urllib.parse.parse_qs(u.query or '')

    def _one(self, qs, key, default=''):
        v = qs.get(key)
        return v[0] if v else default

    def log_message(self, fmt, *args):
        _log('%s - %s' % (self.address_string(), fmt % args))

    # ---------- 静态文件 ----------
    def _static(self, path):
        if path in ('/', ''):
            path = '/index.html'
        if path.startswith('/static/'):
            rel = path[len('/static/'):]
        else:
            rel = path.lstrip('/')
        full = os.path.realpath(os.path.join(STATIC, rel))
        if not full.startswith(os.path.realpath(STATIC) + os.sep) and full != os.path.realpath(STATIC):
            return self._err('forbidden', 403)
        if not os.path.isfile(full):
            return self._err('not found', 404)
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
            ctype += '; charset=utf-8'
        with open(full, 'rb') as fp:
            data = fp.read()
        if rel == 'index.html':
            version = asset_version()
            data = data.replace(b'__ASSET_V__', version.encode())
            html = data.decode('utf-8')
            html = re.sub(r'(href|src)=([\"\'])(/static/[^\"\'?]+\.(?:css|js))\2',
                          lambda m: m.group(1) + '=' + m.group(2) + m.group(3) + '?v=' + version + m.group(2), html)
            data = html.encode('utf-8')
        self._send(data, ctype=ctype)

    # ---------- GET ----------
    def _auth_ok(self):
        if not AUTH_USER:
            return True
        import base64
        import hmac
        got = self.headers.get('Authorization') or ''
        want = 'Basic ' + base64.b64encode(('%s:%s' % (AUTH_USER, AUTH_PASS)).encode()).decode()
        return hmac.compare_digest(got, want)

    def _need_auth(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="book"')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if not self._auth_ok():
            return self._need_auth()
        try:
            path, qs = self._qs()
            if not path.startswith('/api/'):
                return self._static(path)
            if path == '/api/xhs-writing/native':
                import xhs_native
                return self._json({'ok': True, **xhs_native.status(self)})
            if path == '/api/xhs-writing/book':
                import xhs_materials
                result = xhs_materials.from_book(self._one(qs, 'code'))
                return self._json({'ok': True, **result}) if result else self._err('书库中找不到这本书。', 404)
            xhs_job = re.fullmatch(r'/api/xhs-writing/jobs/([a-f0-9]{32})', path)
            if xhs_job:
                import xhs_jobs
                result = xhs_jobs.get(xhs_job.group(1))
                return self._json({'ok': True, **result}) if result else self._err('生成任务不存在或已过期。', 404)
            if path == '/api/qa/status':
                import qa_service
                return self._json({'ok': True, **qa_service.status()})
            if path == '/api/workspace/overview':
                return self._json({'ok': True, **assets_service.overview()})
            if path == '/api/review-queue':
                return self._json({'ok': True, **projects.review_queue()})
            if path == '/api/content-assets':
                return self._json({'ok': True, **assets_service.list_assets(
                    q=self._one(qs, 'q'), kind=self._one(qs, 'kind'), code=self._one(qs, 'code'),
                    status=self._one(qs, 'status'), limit=self._one(qs, 'limit', 40), offset=self._one(qs, 'offset', 0))})
            if path == '/api/content-assets/detail':
                asset = assets_service.get_asset(self._one(qs, 'id'))
                if not asset:
                    return self._err('资产不存在', 404)
                return self._json({'ok': True, 'asset': asset})
            if path == '/api/marketing/review-issues':
                code = self._one(qs, 'code')
                if not store.is_code(code) or not store.get_record(code):
                    return self._err('书不存在', 404)
                return self._json({'ok': True, **assets_service.marketing_review_issues(code)})
            if path == '/api/marketing/source-review':
                return self._json({'ok': True, **source_review.get_context(
                    self._one(qs, 'code'), self._one(qs, 'asset_id'))})
            if path == '/api/projects':
                return self._json({'ok': True, 'projects': projects.list_projects(self._one(qs, 'kind'))})
            if path == '/api/project-records':
                return self._json({'ok': True, **project_records.list_records(
                    q=self._one(qs, 'q'), kind=self._one(qs, 'kind'),
                    limit=self._one(qs, 'limit', 20), offset=self._one(qs, 'offset', 0),
                    scene=self._one(qs, 'scene'))})
            assist_download = re.fullmatch(r'/api/projects/(prj-[a-f0-9]{16})/assist/(assist-[a-f0-9]{16})/download', path)
            if assist_download:
                allow_stale = self._one(qs, 'allow_stale', '0')
                if allow_stale not in ('0', '1'):
                    raise ValueError('旧版下载选项无效')
                try:
                    filename, data, ctype = project_assist.get_run_download(
                        *assist_download.groups(), self._one(qs, 'format', 'pdf'), allow_stale == '1')
                except assets_service.Conflict as err:
                    return self._err(str(err), 409)
                disposition = 'attachment; filename="production-pack.pdf"; filename*=UTF-8\'\'%s' % urllib.parse.quote(filename, safe='')
                return self._send(data, ctype=ctype, extra={'Content-Disposition': disposition,
                                                           'X-Content-Type-Options': 'nosniff'})
            assist_match = re.fullmatch(r'/api/projects/(prj-[a-f0-9]{16})/assist(?:/(assist-[a-f0-9]{16}))?', path)
            if assist_match:
                pid, rid = assist_match.groups()
                return self._json({'ok': True, **({'run': project_assist.get_run(pid, rid)} if rid else
                                                  {'runs': project_assist.list_runs(pid)})})
            export_match = re.fullmatch(r'/api/projects/(prj-[a-f0-9]{16})/exports/(export-[a-f0-9]{16})', path)
            if export_match:
                file_format = self._one(qs, 'format')
                if file_format:
                    filename, data, ctype = projects.get_export_download(*export_match.groups(), file_format)
                    disposition = 'attachment; filename="export.%s"; filename*=UTF-8\'\'%s' % (
                        file_format, urllib.parse.quote(filename, safe=''))
                    return self._send(data, ctype=ctype, extra={'Content-Disposition': disposition,
                                                                'X-Content-Type-Options': 'nosniff'})
                return self._json({'ok': True, **projects.get_export(*export_match.groups())})
            name_checks = re.fullmatch(r'/api/projects/(prj-[a-f0-9]{16})/name-checks', path)
            if name_checks:
                project = projects.get_project(name_checks.group(1))
                return self._json({'ok': True, 'revision': project['revision'],
                                   'items': source_names.project_checks(project, self._one(qs, 'asset'))})
            if path.startswith('/api/projects/'):
                return self._json({'ok': True, 'project': projects.get_project(path.rsplit('/', 1)[-1])})
            if path == '/api/book/tags':
                code = self._one(qs, 'code')
                if not store.get_record(code):
                    return self._err('书不存在', 404)
                return self._json({'ok': True, 'code': code, 'tags': store.tags_index().get(code, {})})
            if path == '/api/version':
                return self._json({'ok': True, 'v': asset_version()})
            if path == '/api/health':
                d = store.health()
                d['max_upload_mb'] = MAX_UPLOAD // 1024 // 1024
                return self._json(d)
            if path == '/api/books':
                rows = store.library_rows()
                return self._json({'ok': True, 'stats': store.global_stats(rows),
                                   'groups': _groups(rows), 'books': rows})
            if path == '/api/book':
                code = self._one(qs, 'code')
                d = store.get_book_detail(code)
                if not d:
                    return self._err('书不存在', 404)
                d['marketing_rows'] = marketing_state.rows(code, include_rejected=True)
                return self._json({'ok': True, **d})
            if path == '/api/book/report':
                rep = store.book_report(self._one(qs, 'code'))
                if not rep:
                    return self._err('书不存在', 404)
                return self._json({'ok': True, 'report': rep})
            if path == '/api/book/cards':
                return self._json({'ok': True, **store.get_cards(
                    self._one(qs, 'code'), self._one(qs, 'tier'),
                    self._one(qs, 'type'), self._one(qs, 'q'),
                    self._one(qs, 'offset', 0), self._one(qs, 'limit', 24),
                    self._one(qs, 'ke'))})
            if path == '/api/editor':
                d = store.editor_payload(self._one(qs, 'code'))
                if not d:
                    return self._err('书不存在', 404)
                return self._json({'ok': True, **d})
            if path == '/api/editor/pending':
                return self._json({'ok': True, **store.editor_pending()})
            if path == '/api/assets/todo':
                return self._json({'ok': True, **store.card_todo(
                    self._one(qs, 'book'))})
            if path == '/api/assets/fields':
                return self._json({'ok': True, **store.card_field_stats(
                    self._one(qs, 'type'), self._one(qs, 'book'))})
            if path == '/api/assets':
                return self._json({'ok': True, **store.list_cards_all(
                    self._one(qs, 'tier'), self._one(qs, 'type'),
                    self._one(qs, 'book'), self._one(qs, 'q'),
                    self._one(qs, 'kind'), self._one(qs, 'offset', 0),
                    self._one(qs, 'limit', 50))})
            if path == '/api/marketing/flags':
                return self._json({'ok': True,
                                   'flags': store.marketing_flags(self._one(qs, 'code'))})
            if path == '/api/book/card':
                got = store.get_card(self._one(qs, 'code'), self._one(qs, 'id'))
                if not got.get('item'):
                    return self._err('条目不存在：%s' % self._one(qs, 'id'), 404)
                return self._json({'ok': True, **got})
            if path == '/api/book/segments':
                return self._json({'ok': True, **store.get_segments(
                    self._one(qs, 'code'), self._one(qs, 'chapter'),
                    self._one(qs, 'offset', 0), self._one(qs, 'limit', 20))})
            if path == '/api/book/entity':
                return self._json({'ok': True, **store.get_entity_occurrences(
                    self._one(qs, 'code'), self._one(qs, 'name'), self._one(qs, 'limit', 30))})
            if path == '/api/book/entity-review':
                return self._json({'ok': True, **store.review_pending(
                    self._one(qs, 'code'), self._one(qs, 'limit', 200),
                    self._one(qs, 'q'), self._one(qs, 'offset', 0))})
            if path == '/api/book/name-check':
                return self._json({'ok': True, **source_names.get_check(self._one(qs, 'code'),
                                  self._one(qs, 'anchor'), self._one(qs, 'name'))})
            if path == '/api/entity-review/pending':
                return self._json({'ok': True, **store.review_pending_all()})
            if path == '/api/book/entities':
                return self._json({'ok': True, **store.get_entities(
                    self._one(qs, 'code'), self._one(qs, 'cat'),
                    self._one(qs, 'limit', 80))})
            if path == '/api/book/segment':
                code, anchor = self._one(qs, 'code'), self._one(qs, 'anchor')
                seg = store.get_segment_at(code, anchor, self._one(qs, 'radius', 2))
                if not seg:
                    return self._err('这段原文找不到了，请回图书档案核对出处。', 404)
                return self._json({'ok': True, **seg})
            if path == '/api/book/source-page':
                try:
                    preview = pdf_source_preview.render(self._one(qs, 'code'), self._one(qs, 'page'))
                except FileNotFoundError as error:
                    return self._err(str(error), 404)
                except RuntimeError as error:
                    return self._err(str(error), 503)
                return self._send(preview, ctype='image/png')
            if path == '/api/book/source':
                pdf = store.original_pdf(self._one(qs, 'code'))
                if not pdf:
                    return self._err('这本书没有可查看的 PDF 原件。', 404)
                try:
                    with open(pdf, 'rb') as stream:
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/pdf')
                        self.send_header('Content-Length', str(os.fstat(stream.fileno()).st_size))
                        self.send_header('Content-Disposition', 'inline; filename="original.pdf"')
                        self.send_header('Cache-Control', 'private, no-store')
                        self.end_headers()
                        shutil.copyfileobj(stream, self.wfile, length=256 * 1024)
                except FileNotFoundError:
                    return self._err('这本书的 PDF 原件已移走。', 404)
                except (BrokenPipeError, ConnectionResetError):
                    return
                return
            if path == '/api/kg/books':
                return self._json({'ok': True, 'books': KG.catalog(picker=self._one(qs, 'view') == 'picker')})
            if path == '/api/kg/view':
                # An explicit empty selection must never fall back to all books.
                scope = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query,
                                             keep_blank_values=True, max_num_fields=8)
                if 'codes' in scope:
                    if len(scope['codes']) != 1 or 'code' in scope:
                        raise ValueError('请只提供一次 codes，且不要与 code 同时使用')
                    raw_codes = scope['codes'][0]
                    if len(raw_codes) > KG.MAX_VIEW_BOOKS * 25 - 1:
                        raise ValueError('图书选择参数过长')
                    codes = raw_codes.split(',') if raw_codes else []
                    return self._json({'ok': True, **KG.view_graph(codes=codes)})
                return self._json({'ok': True, **KG.view_graph(self._one(qs, 'code') or None)})
            if path == '/api/kg':
                code = self._one(qs, 'code')
                d = KG.load_graph(code)
                if not d:
                    return self._err('这本书还没有建图：%s' % code, 404)
                return self._json({'ok': True, **d})
            if path == '/api/kg/segment':
                got = KG.segment(self._one(qs, 'code'), self._one(qs, 'id'))
                if not got:
                    return self._err('锚点不存在', 404)
                return self._json({'ok': True, **got})
            if path == '/api/search':
                return self._json({'ok': True, **store.search(
                    self._one(qs, 'q'), self._one(qs, 'scope', 'all'),
                    self._one(qs, 'limit', 30), self._one(qs, 'offset', 0))})
            if path == '/api/jobs':
                return self._json({'ok': True, 'jobs': store.list_jobs(
                    int(self._one(qs, 'limit', 30)))})
            if path.startswith('/api/jobs/'):
                jid = path.split('/', 3)[3]
                job = store.get_job(jid) if _valid_job_id(jid) else None
                if not job:
                    return self._err('任务不存在', 404)
                return self._json({'ok': True, 'job': _public_job(job)})
            if path == '/api/clc/classes':
                try:
                    import clc as _CLC
                    items = [{'code': k, 'name': v} for k, v in _CLC.NAME.items()]
                except Exception:
                    items = []
                return self._json({'ok': True, 'items': items})
            if path == '/api/settings':
                return self._json(_settings_payload())
            if path == '/api/archive':
                code = self._one(qs, 'code')
                if code:
                    d = store.get_book_detail(code)
                    if not d:
                        return self._err('书不存在', 404)
                    return self._json({'ok': True, **d, 'ops': store.get_ops(code)})
                rows = store.library_rows()
                for r in rows:
                    ops = store.get_ops(r['code'])
                    r['ops'] = ops[-3:]
                return self._json({'ok': True, 'books': rows,
                                   'ops': store.list_ops(80)})
            if path == '/api/trash':
                items = []
                for t in store.list_trash():
                    t = dict(t)
                    t['raw'] = bool(t.get('raw'))
                    t['out'] = bool(t.get('out'))
                    items.append(t)
                return self._json({'ok': True, 'items': items})
            if path == '/api/ops':
                return self._json({'ok': True, 'items': store.list_ops(
                    int(self._one(qs, 'limit', 100)))})
            return self._err('not found', 404)
        except ValueError as e:
            return self._err(str(e), 400)
        except Exception as e:
            traceback.print_exc()
            _log('GET error: %s' % e)
            self._err('服务异常：%s' % e, 500)

    # ---------- POST ----------
    def do_POST(self):
        if not self._auth_ok():
            return self._need_auth()
        try:
            path, qs = self._qs()
            if path == '/api/xhs-writing/native/open':
                import xhs_native
                origin = xhs_native.local_origin(self)
                if not origin or self.headers.get('Origin') != origin:
                    self.close_connection = True
                    return self._err('请在本机书世界页面打开桌面版。', 403)
                if self.headers.get_content_type() != 'application/json':
                    self.close_connection = True
                    return self._err('请从小红书页面打开桌面版。', 415)
                self._read_json()
                status = xhs_native.status(self)
                if not status['available']:
                    return self._err(status['reason'], 503)
                try:
                    xhs_native.launch()
                except (OSError, subprocess.SubprocessError):
                    return self._err('桌面版未能启动，请在访达中检查应用是否可打开。', 503)
                return self._json({'ok': True, 'message': '已打开小红书桌面版。'})
            if path == '/api/xhs-writing/materials':
                return self._xhs_upload()
            if path == '/api/xhs-writing/jobs':
                if self.headers.get_content_type() != 'application/json':
                    return self._err('请以 JSON 提交小红书写作请求。', 415)
                import xhs_jobs
                try:
                    return self._json({'ok': True, **xhs_jobs.enqueue(self._read_json())}, 202)
                except xhs_jobs.Busy as error:
                    return self._err(str(error), 429)
            if path in ('/api/xhs-writing/generate', '/api/xhs-writing/revise'):
                if self.headers.get_content_type() != 'application/json':
                    return self._err('请以 JSON 提交小红书写作请求。', 415)
                import xhs_writing
                operation = xhs_writing.generate if path.endswith('/generate') else xhs_writing.revise
                try:
                    return self._json({'ok': True, **operation(self._read_json())})
                except xhs_writing.WritingUnavailable as error:
                    return self._err(str(error), 503)
                except xhs_writing.InvalidModelOutput as error:
                    return self._err(str(error), 502)
            if path == '/api/creator-match/works/search':
                import creator_match
                import creator_works
                import creator_work_search
                try:
                    return self._json({'ok': True, **creator_work_search.lookup(self._read_json())})
                except creator_work_search.UnknownCreator as error:
                    return self._err(str(error), 404)
                except (creator_work_search.SearchUnavailable, creator_works.WorksUnavailable,
                        creator_match.CreatorDataUnavailable) as error:
                    return self._err(str(error), 503)
            if path == '/api/creator-match/works':
                import creator_match
                import creator_works
                body = self._read_json()
                if not isinstance(body, dict):
                    raise ValueError('请输入有效的达人作品信息。')
                handle = creator_works.parse_handle(body.get('handle'))
                try:
                    if not creator_match.known_handle(handle):
                        return self._err('达人库中找不到这个账号。', 404)
                    works = creator_works.merge_works(handle, body.get('works'))
                except (creator_works.WorksUnavailable, creator_match.CreatorDataUnavailable) as error:
                    return self._err(str(error), 503)
                except OSError:
                    return self._err('暂时无法保存达人作品。', 503)
                return self._json({'ok': True, 'works': works})
            if path == '/api/creator-match/audiences':
                import creator_match_audiences
                try:
                    return self._json({'ok': True, **creator_match_audiences.suggest(self._read_json())})
                except creator_match_audiences.AudienceSuggestionUnavailable as error:
                    return self._err(str(error), 503)
            if path == '/api/creator-match':
                import creator_match
                body = self._read_json()
                if isinstance(body, dict) and body.get('book_code'):
                    code = body['book_code']
                    record = store.get_record(code) if isinstance(code, str) and store.is_code(code) else None
                    if not record:
                        return self._err('书库中找不到这本书。', 404)
                    if not body.get('title'):
                        body['title'] = record.get('book') or ''
                    if 'synopsis' not in body:
                        detail = store.get_book_detail(code) or {}
                        approved_summary = next((row.get('text') or row.get('main')
                                                 for row in marketing_state.rows(code)
                                                 if row.get('key') == 'summary' and row.get('status') == 'approved'), '')
                        sources = ((detail.get('book') or {}).get('内容简介'),
                                   (detail.get('cip') or {}).get('内容提要'), approved_summary)
                        body['synopsis'] = next((s for s in sources if isinstance(s, str) and s.strip()), '')
                try:
                    return self._json({'ok': True, **creator_match.match(body)})
                except creator_match.CreatorDataUnavailable as error:
                    return self._err(str(error), 503)
            if path == '/api/qa/ask':
                import qa_service
                body = self._read_json()
                if not QA_SLOTS.acquire(blocking=False):
                    return self._err('当前问答正在处理中，请稍后重试。', 429)
                try:
                    return self._json({'ok': True, **qa_service.ask(body)})
                finally:
                    QA_SLOTS.release()
            if path == '/api/content-assets/review':
                return self._json({'ok': True, 'asset': assets_service.review_asset(self._read_json())})
            if path == '/api/projects':
                return self._json({'ok': True, 'project': projects.create_project(self._read_json())})
            assist_match = re.fullmatch(r'/api/projects/(prj-[a-f0-9]{16})/assist', path)
            if assist_match:
                result = project_assist.enqueue(assist_match.group(1), self._read_json())
                if result.get('started'):
                    _start_job(result['job']['id'])
                result['job'] = _public_job(result['job'])
                return self._json({'ok': True, **result})
            reuse_match = re.fullmatch(r'/api/projects/(prj-[a-f0-9]{16})/reuse', path)
            if reuse_match:
                return self._json({'ok': True, 'project': projects.reuse_project(reuse_match.group(1), self._read_json())})
            if path.startswith('/api/projects/'):
                return self._json({'ok': True, **projects.update_project(path.rsplit('/', 1)[-1], self._read_json())})
            if path == '/api/marketing/export':
                body = self._read_json()
                return self._json({'ok': True, **marketing_state.export(body.get('code') or '', body.get('mode') or 'approved', body.get('format') or 'md')})
            if path == '/api/books/generate':
                body = self._read_json()
                kind = body.get('kind', 'marketing')
                if kind not in ('marketing', 'summaries'):
                    raise ValueError('当前补跑入口支持营销素材或篇章摘要')
                return self._enqueue_book_job(body.get('code') or '', kind)
            if path == '/api/upload':
                return self._upload()
            if path == '/api/probe':
                return self._probe_upload()
            if path == '/api/kg/request':
                body = self._read_json()
                code = body.get('code') or ''
                if code not in [b.get('code') for b in store.library_rows()]:
                    return self._err('书不存在', 404)
                got = KG.set_request(code, body.get('note') or '', bool(body.get('cancel')))
                store.append_op(code, 'kg_request', {'cancel': bool(body.get('cancel')), **({} if not got else got)})
                return self._json({'ok': True, 'request': got})
            if path == '/api/kg/rebuild':
                body = self._read_json()
                code = body.get('code') or ''
                if code not in [b.get('code') for b in store.library_rows()]:
                    return self._err('书不存在', 404)
                try:
                    d = KG.build_book(code)
                except SystemExit as e:
                    return self._err(str(e), 400)
                store.append_op(code, 'kg_build', d['meta']['counts'])
                return self._json({'ok': True, 'meta': d['meta']})
            if path == '/api/settings':
                body = self._read_json()
                if 'content_labels' in body:
                    E.save_content_labels(body['content_labels'])
                else:
                    E.save_plan(body.get('plan') or {})
                store.append_op('_settings', 'settings', {'job': 'content_labels'})
                return self._json({'ok': True, 'settings': _settings_payload()})
            if path == '/api/settings/reset':
                E.reset_plan()
                store.append_op('_settings', 'settings_reset', {})
                return self._json({'ok': True, 'settings': _settings_payload()})
            if path == '/api/books/delete':
                body = self._read_json()
                code = body.get('code') or ''
                try:
                    r = store.delete_book(code, body.get('confirm') or '')
                except ValueError as e:
                    return self._err(str(e), 400)
                return self._json({'ok': True, **r})
            if path == '/api/marketing/source-review/verify':
                try:
                    return self._json({'ok': True, **source_review.verify(self._read_json())})
                except source_review.SourceChanged as error:
                    return self._json({'ok': False, 'error': str(error),
                                       'error_code': 'source_changed'}, status=409)
            if path == '/api/marketing/flag':
                body = self._read_json()
                code = body.get('code') or ''
                if not store.get_record(code):
                    return self._err('书不存在', 404)
                ids = body.get('ids') if isinstance(body.get('ids'), list) else [body.get('id') or '']
                status = {'adopt': 'approved', 'reject': 'rejected', '': 'review'}.get(body.get('status') or '')
                if status is None or not ids:
                    raise ValueError('审核状态或素材列表无效')
                try:
                    result = assets_service.review_marketing_assets(code, ids, status)
                except assets_service.ReviewBlocked as error:
                    return self._json({'ok': False, 'error': str(error),
                                       'error_code': 'marketing_review_blocked', 'count': 0, 'changed_count': 0,
                                       'blocked_items': error.blocked_items}, status=400)
                try:
                    store.append_op(code, 'marketing_flag', {'count': result['count'], 'status': body.get('status') or ''})
                except OSError:
                    result.setdefault('warnings', []).append('审核已保存，操作记录暂未写入，请刷新查看当前审核结果。')
                return self._json({'ok': True, **result})
            if path == '/api/editor/flag':
                body = self._read_json()
                code = body.get('code') or ''
                if not store.get_record(code):
                    return self._err('书不存在', 404)
                try:
                    rec = store.set_editor_flag(code, body.get('id') or '',
                                                body.get('fields') or {})
                except ValueError as e:
                    return self._err(str(e), 400)
                return self._json({'ok': True, 'flag': rec})
            if path == '/api/hotspot/fetch':
                body = self._read_json()
                try:
                    d = hotspot.fetch_all(int(body.get('limit') or 12))
                    return self._json({'ok': True, **d})
                except Exception as e:
                    return self._err('抓取失败：%s' % e, 502)
            if path == '/api/hotspot/preview':
                body = self._read_json()
                try:
                    d = hotspot.preview_many(body.get('titles') or [], int(body.get('limit') or 2))
                    return self._json({'ok': True, 'items': d})
                except Exception as e:
                    return self._err('预览失败：%s' % e, 400)
            if path == '/api/hotspot/analyze':
                body = self._read_json()
                try:
                    a = hotspot.analyze(body.get('title') or '', body.get('facts') or '')
                    return self._json({'ok': True, 'analysis': a})
                except Exception as e:
                    return self._err('拆解失败：%s' % e, 400)
            if path == '/api/hotspot/match':
                body = self._read_json()
                try:
                    a = body.get('analysis') or hotspot.analyze(body.get('text') or '',
                                                                body.get('facts') or '')
                    books = hotspot.match(a, int(body.get('limit') or 10))
                    return self._json({'ok': True, 'analysis': a, 'books': books})
                except Exception as e:
                    return self._err('匹配失败：%s' % e, 400)
            if path == '/api/books/tag':
                return self._enqueue_book_job(self._read_json().get('code') or '', 'tag')
            if path == '/api/books/clc':
                body = self._read_json()
                code = body.get('code') or ''
                got = store.set_clc(code, body.get('clc') or '')
                if not got:
                    return self._err('分类号无效', 400)
                store.append_op(code, 'clc', {'代码': got['代码'], '名称': got['名称']})
                return self._json({'ok': True, 'clc': got})
            if path == '/api/book/name-check':
                try:
                    return self._json({'ok': True, **source_names.save_check(self._read_json())})
                except source_names.SourceChanged as error:
                    return self._err(str(error), 409)
            if path == '/api/entity-review':
                body = self._read_json()
                got = store.set_entity_review(body.get('code') or '',
                                              body.get('name') or '',
                                              body.get('cat') or None,
                                              bool(body.get('drop')))
                if not got:
                    return self._err('参数无效', 400)
                store.append_op(body.get('code'), 'entity_review',
                                {'name': body.get('name'), **got})
                return self._json({'ok': True, 'review': got})
            if path == '/api/books/meta':
                body = self._read_json()
                code = body.get('code') or ''
                rec = store.get_record(code)
                if not rec:
                    return self._err('书不存在', 404)
                rec['author'] = (body.get('author') or '').strip()[:80]
                rec['publisher'] = (body.get('publisher') or '').strip()[:80]
                rec['updated_at'] = store.now()
                store.upsert_book(rec)
                store.append_op(code, 'meta', {
                    'author': rec['author'], 'publisher': rec['publisher']})
                return self._json({'ok': True, 'record': rec})
            if path == '/api/books/confirm':
                body = self._read_json()
                code = body.get('code') or ''
                rec = store.get_record(code)
                if not rec:
                    return self._err('书不存在', 404)
                rec['confirmed'] = bool(body.get('confirmed', True))
                rec['status'] = 'ready' if rec['confirmed'] else 'pending'
                rec['updated_at'] = store.now()
                store.upsert_book(rec)
                store.append_op(code, 'confirm' if rec['confirmed'] else 'unconfirm',
                                {'job': 'manual'})
                return self._json({'ok': True, 'record': rec})
            if path == '/api/books/retype':
                body = self._read_json()
                code = body.get('code') or ''
                proto = body.get('prototype') or ''
                rec = store.get_record(code)
                if not rec:
                    return self._err('书不存在', 404)
                if proto not in E.PROTO_NAMES:
                    return self._err('未知原型：%s' % proto, 400)
                job = store.new_job('retype', {
                    'title': rec.get('book'), 'code': code, 'prototype': proto,
                    'steps': [{'key': 'judge', 'label': '按人工判型重跑', 'progress': 55},
                              {'key': 'export', 'label': '重建汇总资产库', 'progress': 85},
                              {'key': 'store', 'label': '更新档案', 'progress': 100}],
                })
                _start_job(job['id'])
                return self._json({'ok': True, 'job': job})
            if path == '/api/jobs/delete':
                body = self._read_json()
                jid = body.get('id')
                if not _valid_job_id(jid):
                    return self._err('任务不存在', 404)
                store.delete_job(jid)
                return self._json({'ok': True})
            if path == '/api/jobs/retry':
                return self._retry_job(self._read_json().get('id'))
            if path == '/api/jobs/clear':
                return self._json({'ok': True, 'deleted': store.clear_finished_jobs()})
            if path == '/api/trash/restore':
                body = self._read_json()
                tid = body.get('trash_id') or ''
                # 查重 + 建任务必须在一个锁里：两个请求同时进来时，
                # 「都没查到正在恢复」会同时放行，两个执行器抢同一批文件。
                with JOB_LOCK:
                    tr = store.get_trash(tid)
                    if not tr:
                        return self._err('回收站记录不存在', 404)
                    if tr.get('restoring'):
                        j = store.get_job(tr['restoring'])
                        if j and j.get('status') in ('queued', 'running'):
                            return self._err('这条记录正在恢复，别重复提交', 409)
                        # 执行器被杀掉时标记会留下：任务已结束就清掉，别把记录锁死
                        store.set_trash_flag(tid, 'restoring', None)
                    job = store.new_job('restore', {
                        'title': tr.get('book'), 'trash_id': tid,
                        'steps': [{'key': 'restore_files', 'label': '还原底本与产物', 'progress': 15},
                                  {'key': 'judge', 'label': '重跑判型 / 切段 / 候选卡', 'progress': 55},
                                  {'key': 'export', 'label': '重建汇总资产库', 'progress': 82},
                                  {'key': 'store', 'label': '恢复图书库记录', 'progress': 100}],
                    })
                    store.set_trash_flag(tid, 'restoring', job['id'])
                _start_job(job['id'])
                return self._json({'ok': True, 'job': job})
            return self._err('not found', 404)
        except assets_service.Conflict as e:
            return self._err(str(e), 409)
        except ValueError as e:
            return self._err(str(e), 400)
        except Exception as e:
            traceback.print_exc()
            _log('POST error: %s' % e)
            self._err('服务异常：%s' % e, 500)

    def _enqueue_book_job(self, code, kind):
        record = store.get_record(code)
        if not record:
            return self._err('书不存在', 404)
        with store._lock('enqueue-book-job'):
            existing = _active_book_job(record.get('book'), code)
            if existing:
                return self._json({'ok': True, 'running': True, 'job': _public_job(existing)})
            job = store.new_job(kind, {'book_code': code, 'title': record.get('book') or code})
        _start_job(job['id'])
        store.append_op(code, kind, {'job': job['id']})
        return self._json({'ok': True, 'started': True, 'job': _public_job(job)})

    def _retry_job(self, job_id):
        if not _valid_job_id(job_id):
            return self._err('找不到这条任务。', 404)
        with store._lock('enqueue-book-job'):
            original = store.get_job(job_id)
            plan = _retry_plan(original)
            if not plan:
                return self._err('这条任务现在不能重试，请查看处理结果。', 409)
            kind, payload, _label = plan
            existing = _active_book_job(payload.get('title'), payload.get('book_code'))
            if existing:
                return self._json({'ok': True, 'running': True, 'job': _public_job(existing)})
            job = store.new_job(kind, payload)
        _start_job(job['id'])
        return self._json({'ok': True, 'job': _public_job(job)})

    # ---------- 上传 ----------
    def _probe_upload(self):
        """收原件 → 认出书名/作者/出版社 → 先存临时目录，等用户确认。

        走原始字节流（application/octet-stream），边收边写盘：
        500 MB 的 PDF 进内存再解析会直接把服务撑爆。
        """
        _, qs = self._qs()
        name = urllib.parse.unquote(self._one(qs, 'name') or '') or '未命名'
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except Exception:
            n = 0
        if n <= 0:
            return self._err('没有收到文件', 400)
        if n > MAX_UPLOAD:
            return self._err('文件超过 %d MB 上限' % (MAX_UPLOAD // 1024 // 1024), 413)
        try:
            fmt = ingest.fmt_of(name)
        except ingest.IngestError as e:
            return self._err(str(e), 400)

        _gc_probe()
        token = secrets.token_hex(16)
        d = os.path.join(PROBEDIR, token)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, 'original.' + fmt)
        left = n
        try:
            with open(dst, 'wb') as fp:
                while left > 0:
                    chunk = self.rfile.read(min(4 * 1024 * 1024, left))
                    if not chunk:
                        break
                    fp.write(chunk)
                    left -= len(chunk)
        except Exception as e:
            shutil.rmtree(d, ignore_errors=True)
            return self._err('接收文件失败：%s' % e, 400)
        if left > 0:
            shutil.rmtree(d, ignore_errors=True)
            return self._err('文件接收不完整（还差 %d 字节），请重试。' % left, 400)

        try:
            info = probe.probe_file(dst, fmt, name)
        except ingest.IngestError as e:
            shutil.rmtree(d, ignore_errors=True)
            return self._err(str(e), 422)
        with open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8') as fp:
            json.dump({'filename': name, 'format': fmt, 'path': dst,
                       'bytes': n, 'created': time.time(), 'probe': info}, fp,
                      ensure_ascii=False)
        _log('probe %s %s %d bytes → %s / %s' % (token[:8], name, n,
                                                 info.get('title'), info.get('author')))
        return self._json({'ok': True, 'token': token, 'probe': info})

    def _upload(self):
        ctype = self.headers.get('Content-Type') or ''
        if ctype.lower().startswith('application/json'):
            return self._upload_commit()
        return self._upload_multipart()

    def _upload_commit(self):
        """前端确认书名后，用预检 token 提交，不再重传文件。"""
        body = self._read_json()
        token = body.get('token') or ''
        meta = _probe_meta(token)
        if not meta:
            return self._err('预检文件不存在或已过期，请重新选择文件。', 410)
        title = store.safe_title(body.get('title') or '')
        if not title:
            return self._err('书名不能为空', 400)
        author = (body.get('author') or '').strip()[:80]
        publisher = (body.get('publisher') or '').strip()[:80]
        return self._new_upload_job(title, author, publisher, meta['format'],
                                    meta.get('filename') or '', meta['path'],
                                    int(meta.get('bytes') or 0), token=token,
                                    probe_info=meta.get('probe'))

    def _xhs_upload(self):
        import xhs_materials

        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            size = 0
        if size <= 0:
            return self._err('请选择要上传的内文。')
        if size > xhs_materials.MAX_UPLOAD + 16 * 1024:
            self.close_connection = True
            return self._err('内文文件不能超过 40 MB。', 413)
        boundary = self.headers.get_boundary()
        if self.headers.get_content_type() != 'multipart/form-data' or not boundary or len(boundary) > 70:
            self.close_connection = True
            return self._err('上传格式必须是 multipart/form-data。', 415)
        if not XHS_UPLOAD_SLOTS.acquire(blocking=False):
            self.close_connection = True
            return self._err('正在处理其他文件，请稍后再上传。', 429)
        try:
            field = _parse_multipart(self.rfile.read(size), boundary.encode('ascii', errors='replace')).get('file')
            if not isinstance(field, dict) or not field.get('filename') or not field.get('data'):
                return self._err('请选择包含内文的文件。')
            if len(field['data']) > xhs_materials.MAX_UPLOAD:
                return self._err('内文文件不能超过 40 MB。', 413)
            return self._json({'ok': True, **xhs_materials.from_upload(field['filename'], field['data'])})
        finally:
            XHS_UPLOAD_SLOTS.release()

    def _upload_multipart(self):
        """老接口：整包读进内存。为兼容保留，但大文件请走 /api/probe。"""
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except Exception:
            n = 0
        if n <= 0:
            return self._err('没有收到文件', 400)
        if n > LEGACY_MULTIPART_MAX:
            return self._err('请刷新页面后重试（新版上传会边收边存，不再有大小限制）。', 413)
        ctype = self.headers.get('Content-Type') or ''
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not m:
            return self._err('上传格式必须是 multipart/form-data', 400)
        body = self.rfile.read(n)
        fields = _parse_multipart(body, m.group(1).encode('utf-8'))
        f = fields.get('file')
        if not isinstance(f, dict) or not f.get('data'):
            return self._err('没有收到文件字段', 400)
        filename = f.get('filename') or '未命名.txt'
        try:
            fmt = ingest.fmt_of(filename)
        except ingest.IngestError as e:
            return self._err(str(e), 400)
        title = store.safe_title(fields.get('title') or filename)
        if not title:
            return self._err('书名不能为空', 400)
        author = (fields.get('author') or '').strip()[:80]
        publisher = (fields.get('publisher') or '').strip()[:80]
        d = os.path.join(PROBEDIR, secrets.token_hex(16))
        os.makedirs(d, exist_ok=True)
        src = os.path.join(d, 'original.' + fmt)
        with open(src, 'wb') as fp:
            fp.write(f['data'])
        try:
            return self._new_upload_job(title, author, publisher, fmt,
                                        os.path.basename(filename), src, len(f['data']))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _new_upload_job(self, title, author, publisher, fmt, filename, src,
                        nbytes, token='', probe_info=None):
        with store._lock('enqueue-book-job'):
            if _active_book_job(title):
                return self._err('《%s》正在处理，可以在运行任务中查看。' % title, 409)
            if runner._title_exists(title):
                return self._err('库里已有《%s》。如果是不同版次，请在书名里注明版次。' % title, 409)
            job = store.new_job('upload', {
                'title': title, 'author': author, 'publisher': publisher,
                'source_format': fmt, 'original_filename': os.path.basename(filename),
                'probe': probe_info or {},
                'steps': [dict(s, status='pending', detail='') for s in runner.UPLOAD_STEPS],
            })
            try:
                updir = os.path.join(store.UPLOADDIR, job['id'])
                os.makedirs(updir, exist_ok=True)
                dst = os.path.join(updir, 'original.' + fmt)
                shutil.move(src, dst)
                store.update_job(job['id'], source_path=dst, upload_bytes=nbytes)
            except OSError:
                store.update_job(job['id'], status='failed', finished_at=store.now(), error='文件未保存成功，请重新上传。')
                return self._err('文件未保存成功，请重新上传。', 500)
            if token:
                shutil.rmtree(os.path.join(PROBEDIR, token), ignore_errors=True)
        _start_job(job['id'])
        return self._json({'ok': True, 'job': _public_job(store.get_job(job['id']))})


def _valid_job_id(value):
    return isinstance(value, str) and re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{6}', value)


def _active_book_job(title, code=None):
    for summary in store.list_jobs(500):
        if summary['status'] not in ('queued', 'running') or summary['kind'] == 'project_assist':
            continue
        existing = store.get_job(summary['id']) or {}
        if existing.get('title') == title or (code and code in (existing.get('book_code'), existing.get('code'))):
            return existing
    return None


def _retry_plan(job):
    if not job or job.get('status') not in ('failed', 'partial') or job.get('error_kind') == 'source':
        return None
    kind, code, title = job.get('kind'), job.get('book_code'), job.get('title')
    if not title:
        return None
    payload = {'title': title, 'retry_of': job['id']}
    if code:
        payload['book_code'] = code
    record = store.load_library()['books'].get(code) if code else None
    if kind == 'upload' and job['status'] == 'failed':
        original_id = job.get('original_job') or job['id']
        fmt = job.get('source_format', '')
        if not _valid_job_id(original_id) or fmt not in ingest.ALLOWED.values():
            return None
        src = os.path.join(store.UPLOADDIR, original_id, 'original.' + fmt)
        if not os.path.isfile(src) or os.path.realpath(src) != os.path.realpath(job.get('source_path') or ''):
            return None
        if record and record.get('last_job') != job['id']:
            return None
        if not record and runner._title_exists(title):
            return None
        payload.update({key: job.get(key) for key in ('author', 'publisher', 'source_format', 'original_filename',
                        'probe', 'source_pages', 'source_chars', 'source_han', 'source_note', 'source_ocr',
                        'source_page_issues', 'outputs')})
        payload.update(source_path=src, original_job=original_id)
        if record:
            payload['resume_code'] = code
        return 'upload', payload, '继续处理' if record else '用原文件重试'
    if kind in ('upload', 'upload_supplement') and record:
        outputs = job.get('outputs') or {}
        parts = [key for key in ('entities', 'understanding', 'marketing') if outputs.get(key) in ('partial', 'failed')]
        if 'entities' in parts:
            names = (store.read_json(os.path.join(E.OUT, code, 'derivative_status.json'), {}) or {}).get('entities') or {}
            if names.get('status') in ('done', 'blocked'):
                parts.remove('entities')
        if 'understanding' in parts:
            reading = (store.read_json(os.path.join(E.OUT, code, 'understanding.json'), {}) or {}).get('processing') or {}
            if all((reading.get(key) or {}).get('status') == 'done' for key in ('quotes', 'themes')):
                parts.remove('understanding')
        if parts or (kind == 'upload_supplement' and job['status'] == 'failed'):
            payload['parts'] = parts
            return 'upload_supplement', payload, '补做未完成的内容'
    if kind in ('tag', 'summaries', 'marketing') and record:
        return kind, payload, '继续处理'
    return None


def _clean_text(s):
    """页面不出现内部工程词与绝对路径。"""
    s = str(s or '')
    s = s.replace(E.ROOT + os.sep, '').replace(E.ROOT, '')
    s = s.replace('判型与蒸馏', '分类与解析')
    s = s.replace('判型与解析', '分类与解析')
    s = s.replace('判型 / 切段 / 候选卡', '分类 / 内容切分 / 知识条目')
    s = s.replace('解析文件', '读取与清洗')
    s = s.replace('确认卡质检', '已确认知识校验')
    s = s.replace('汇总资产库', '汇总内容资产')
    s = s.replace('重建页面', '更新平台视图')
    s = s.replace('判型', '分类')
    s = s.replace('切段', '内容切分')
    s = s.replace('候选卡', '知识条目')
    s = s.replace('八层标签', '标签体系')
    s = s.replace('蒸馏', '解析')
    return s


def _public_job(job):
    """任务对象给前端前做一次清洗：去掉本地绝对路径与内部工程词。"""
    if not job:
        return job
    j = dict(job)
    for key in ('source_path', 'raw_path', 'original_job', 'resume_code'):
        j.pop(key, None)
    retry = _retry_plan(job)
    j['retryable'] = bool(retry)
    if retry:
        j['retry_label'] = retry[2]
    if j.get('error'):
        j['error'] = _clean_text(j['error'])
    j['warnings'] = [_clean_text(note) for note in (j.get('warnings') or [])]
    j['steps'] = [dict(x, label=_clean_text(x.get('label')),
                       detail=_clean_text(x.get('detail')))
                  for x in (j.get('steps') or [])]
    j['log'] = [_clean_text(x) for x in (j.get('log') or [])]
    return j


def _groups(rows):
    out = []
    for p in E.PROTO_ORDER:
        items = [r for r in rows if r['prototype'] == p]
        if items:
            out.append({'key': p, 'name': E.PROTO_NAMES[p], 'count': len(items)})
    return out


def _settings_payload():
    return {
        'ok': True,
        'default': E.default_plan(),
        'current': E.current_plan(),
        'labels': E.all_labels(),
        'content_labels': E.content_labels(),
        'protos': [{'key': p, 'name': E.PROTO_NAMES[p]} for p in E.PROTO_ORDER],
        'confirm': E.confirm_info(),
        'thresholds': E.thresholds(),
        'caps': E.read_caps(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8942)
    args = ap.parse_args()
    store.recover_jobs(on_interrupted_upload=runner.recover_upload)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print('图书知识库 → http://%s:%d' % (args.host, args.port))
    print('根目录：%s' % E.ROOT)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    sys.exit(main())
