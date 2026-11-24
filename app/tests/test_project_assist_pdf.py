"""Read-only, version-aware PDF downloads of saved visual production packages."""
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pdfplumber
import assets_service as assets
import manuscript_pdf as pdf
import project_assist as assist
import projects
import server
import store
from download_names import document_filename, production_filename
from test_production_document import legacy_run, saved_run


PID, RID = 'prj-' + 'a' * 16, 'assist-' + 'b' * 16
MARKDOWN = '''# 图片展示制作包

## 完整口播

这是一份已经确认的口播，保留正文原样。

## 第 1 张图

**提示词：** 竖屏构图，主体清晰，底部留白。

## 第 8 张图

最后一张图完整保留。

## 参考要求

请提供经核对的物种参考图，不能用文字依据代替图片。

## 制作步骤

1. 核对参考图。
2. 制作画面后再合成完整口播。
'''


def extracted(data):
    with pdfplumber.open(io.BytesIO(data)) as document:
        return '\n'.join(p.extract_text() or '' for p in document.pages), len(document.pages)


class ProjectAssistPdfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project_dir = self.root / 'projects'
        self.assist_dir = self.root / 'assists'
        self.project_dir.mkdir(); self.assist_dir.mkdir()
        self.project = {'id': PID, 'title': '当前项目', 'revision': 1, 'brief': {}, 'items': [],
                        'draft': '当前正在修改的正文，绝不能进入旧制作包。', 'exports': []}
        self.run = {'id': RID, 'project_id': PID, 'capability': 'video_prompts', 'status': 'done',
                    'input_hash': 'revision-1', 'markdown': MARKDOWN,
                    'finished_at': '2026-11-21T18:30:00',
                    'snapshot': {'title': '读懂一座城', 'presentation_mode': 'image', 'input_asset_revisions': {}},
                    'result': {'video_prompts': {'presentation_mode': 'image'}}}
        self.engine = types.SimpleNamespace(fingerprint=lambda p: 'revision-%s' % p['revision'],
                                            execute=Mock(side_effect=AssertionError('No generation during download')))
        self.patches = [patch.object(projects, 'DIR', str(self.project_dir)),
                        patch.object(assist, 'DIR', str(self.assist_dir)),
                        patch.object(assist, '_engine', return_value=self.engine)]
        for item in self.patches:
            item.start()
        self.write_fixtures()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def write_fixtures(self):
        (self.project_dir / (PID + '.json')).write_text(json.dumps(self.project, ensure_ascii=False))
        (self.assist_dir / (RID + '.json')).write_text(json.dumps(self.run, ensure_ascii=False))

    def file_snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_download_is_frozen_complete_and_does_not_write_any_file_or_export(self):
        before = self.file_snapshot()
        with patch.object(store, 'write_json', side_effect=AssertionError('Download must not write')):
            name, data, mime = assist.get_run_download(PID, RID)
        self.assertEqual((name, mime), ('读懂一座城_图片制作包.pdf', 'application/pdf'))
        self.assertEqual(assist.get_run(PID, RID)['download_filename'], name)
        self.assertTrue(data.startswith(b'%PDF-'))
        text, _ = extracted(data)
        for expected in ('已经确认的口播', '最后一张图完整保留', '不能用文字依据代替图片', '合成完整口播'):
            self.assertIn(expected, text)
        self.assertNotIn('当前正在修改的正文', text)
        self.assertNotIn('已审核', text)
        self.assertNotIn('审阅稿', text)
        self.assertEqual(self.file_snapshot(), before)
        self.engine.execute.assert_not_called()

    def test_video_mode_and_explicit_old_version_are_marked_without_approval_claim(self):
        self.project['revision'] = 2
        self.run['result']['video_prompts']['presentation_mode'] = 'video'
        self.write_fixtures()
        with patch.object(pdf, 'render_export_pdf', side_effect=AssertionError('No PDF before consent')):
            with self.assertRaisesRegex(assets.Conflict, '请确认旧版'):
                assist.get_run_download(PID, RID)
        name, data, _ = assist.get_run_download(PID, RID, allow_stale=True)
        text, pages = extracted(data)
        self.assertEqual(name, '旧版-读懂一座城_视频制作包.pdf')
        self.assertEqual(text.count('旧版 · 视频展示-制作包'), pages)
        self.assertNotIn('已审核', text)
        self.assertNotIn('待审核', text)

    def test_source_stale_is_checked_even_when_project_fingerprint_matches(self):
        with patch.object(assist, '_source_issue', return_value='原材料已更新'), \
             patch.object(pdf, 'render_export_pdf', side_effect=AssertionError('No PDF before consent')):
            with self.assertRaises(assets.Conflict):
                assist.get_run_download(PID, RID)

    def test_newly_stale_during_render_is_rejected_without_old_version_consent(self):
        fresh = dict(self.run, stale=False, source_stale=False)
        old = dict(fresh, stale=True)
        with patch.object(assist, 'get_run', side_effect=[fresh, old]), \
             patch.object(pdf, 'render_export_pdf', return_value=b'%PDF-test') as render:
            with self.assertRaisesRegex(assets.Conflict, '请确认旧版'):
                assist.get_run_download(PID, RID)
        self.assertEqual(render.call_count, 1)

    def test_allowed_old_version_rerenders_label_if_stale_changes_during_render(self):
        fresh = dict(self.run, stale=False, source_stale=False)
        old = dict(fresh, source_stale=True)
        with patch.object(assist, 'get_run', side_effect=[fresh, old]), \
             patch.object(pdf, 'render_export_pdf', return_value=b'%PDF-test') as render:
            name, _, _ = assist.get_run_download(PID, RID, allow_stale=True)
        self.assertEqual(name, '旧版-读懂一座城_图片制作包.pdf')
        self.assertEqual(render.call_count, 2)
        self.assertTrue(render.call_args.args[0]['export']['stale'])
        self.assertEqual(render.call_args.args[0]['text'], MARKDOWN)

    def test_cross_project_does_not_expose_package(self):
        with patch.object(pdf, 'render_export_pdf', side_effect=AssertionError('Must not render another project')):
            with self.assertRaisesRegex(ValueError, '没有这份生成记录'):
                assist.get_run_download('prj-' + 'c' * 16, RID, allow_stale=True)

    def test_invalid_or_incomplete_records_do_not_download(self):
        changes = [{'capability': 'draft'}, {'status': 'running'}, {'status': 'failed'},
                   {'markdown': ''}, {'markdown': '   '}, {'markdown': None},
                   {'result': {}}, {'result': {'video_prompts': {'presentation_mode': 'both'}}, 'snapshot': {}}]
        with patch.object(pdf, 'render_export_pdf', side_effect=AssertionError('Invalid run must not render')):
            for fields in changes:
                with self.subTest(fields=fields), patch.object(assist, 'get_run', return_value=dict(self.run, **fields)):
                    with self.assertRaises(ValueError):
                        assist.get_run_download(PID, RID, allow_stale=True)
            with self.assertRaisesRegex(ValueError, '仅支持 PDF'):
                assist.get_run_download(PID, RID, 'docx')
            with self.assertRaisesRegex(ValueError, '旧版下载选项无效'):
                assist.get_run_download(PID, RID, allow_stale='1')

    def test_old_record_can_use_saved_snapshot_mode(self):
        self.run['result']['video_prompts'].pop('presentation_mode')
        self.write_fixtures()
        with patch.object(pdf, 'render_export_pdf', return_value=b'%PDF-test'):
            self.assertEqual(assist.get_run_download(PID, RID)[0], '读懂一座城_图片制作包.pdf')

    def test_filename_keeps_saved_project_name_and_does_not_add_dates_or_identifiers(self):
        self.project['title'] = '今天改的名称'
        self.write_fixtures()
        with patch.object(pdf, 'render_export_pdf', return_value=b'%PDF-test'):
            first = assist.get_run_download(PID, RID)[0]
            second = assist.get_run_download(PID, RID)[0]
        self.assertEqual(first, '读懂一座城_图片制作包.pdf')
        self.assertEqual(second, first)
        self.assertNotIn('今天', first)
        self.assertNotIn('2026', first)

    def test_filename_fallback_is_saved_topic_then_book_title(self):
        run = {'snapshot': {'brief': {'topic': '诗歌里的四季'},
                            'marketing': {'target_books': [{'book': '诗歌选读'}]}}}
        self.assertEqual(production_filename(run, 'image'), '诗歌里的四季_图片制作包.pdf')
        run['snapshot']['brief'] = {}
        self.assertEqual(production_filename(run, 'video'), '诗歌选读_视频制作包.pdf')
        self.assertEqual(production_filename({'snapshot': {}}, 'image'), '未命名项目_图片制作包.pdf')

    def test_filename_is_portable_with_long_titles_and_unsafe_characters(self):
        title = '../城市:记忆/\\?*\"<>|\r\n\u202e' + '有很长中文标题' * 60
        filename = document_filename(title, '图片制作包', old=True)
        self.assertTrue(filename.startswith('旧版-城市'))
        self.assertTrue(filename.endswith('_图片制作包.pdf'))
        self.assertLessEqual(len(filename.encode('utf-8')), 220)
        self.assertNotRegex(filename, r'[\\/:*?"<>|\x00-\x1f\x7f\u202e]')
        self.assertEqual(document_filename('CON.txt', '图片制作包'), '项目-CON.txt_图片制作包.pdf')

    def test_structured_download_uses_saved_context_and_does_not_write_to_history(self):
        frozen = legacy_run()
        self.run.update(frozen)
        self.project.update(title='今天的新标题', draft='今天正在修改的新口播',
                            brief={'audience': '新项目的购买者'})
        self.write_fixtures()
        before = self.file_snapshot()
        with patch.object(store, 'write_json', side_effect=AssertionError('Download must not write')), \
             patch.object(pdf, 'render_export_pdf', return_value=b'%PDF-test') as rendered:
            _, data, mime = assist.get_run_download(PID, RID)
        self.assertEqual(mime, 'application/pdf')
        self.assertTrue(data.startswith(b'%PDF-'))
        exported = rendered.call_args.args[0]
        display = exported['production_document']
        self.assertEqual(exported['text'], frozen['markdown'])
        self.assertEqual(display['topic'], '旧版口播与镜头')
        self.assertEqual(display['audience'], '成年文学读者')
        self.assertEqual(display['narration'][0]['text'], frozen['snapshot']['confirmed_outline'][0]['source_text'])
        self.assertEqual(display['shots'][0]['prompt'], frozen['result']['video_prompts']['shots'][0]['prompt'])
        self.assertNotIn('今天', str(display))
        self.assertNotIn('新项目的购买者', str(display))
        self.assertEqual(self.file_snapshot(), before)
        self.engine.execute.assert_not_called()

    def test_custom_markdown_extra_instruction_survives_generic_pdf_fallback(self):
        self.run.update(saved_run())
        self.run['markdown'] += '\n\n## 编辑附注\n\n尾页保留出版社联系电话。'
        self.write_fixtures()
        before = self.file_snapshot()
        with patch.object(pdf, 'render_export_pdf', wraps=pdf.render_export_pdf) as rendered:
            _, data, _ = assist.get_run_download(PID, RID)
        self.assertNotIn('production_document', rendered.call_args.args[0])
        text, _ = extracted(data)
        self.assertIn('尾页保留出版社联系电话', text)
        self.assertEqual(self.file_snapshot(), before)


class AssistPdfHttpTests(unittest.TestCase):
    def handler(self, query=None):
        handler = object.__new__(server.Handler)
        handler._auth_ok = lambda: True
        handler._qs = lambda: ('/api/projects/%s/assist/%s/download' % (PID, RID), query or {})
        handler._send = lambda body, ctype=None, extra=None: {'body': body, 'ctype': ctype, 'headers': extra}
        handler._err = lambda message, status=400: {'error': message, 'status': status}
        return handler

    def test_get_sets_pdf_and_utf8_download_headers(self):
        with patch.object(assist, 'get_run_download', return_value=('图片展示-制作包.pdf', b'%PDF-test', 'application/pdf')) as download:
            response = self.handler({'format': ['pdf']}).do_GET()
        download.assert_called_once_with(PID, RID, 'pdf', False)
        self.assertEqual(response['ctype'], 'application/pdf')
        self.assertEqual(response['headers']['Content-Disposition'],
                         'attachment; filename="production-pack.pdf"; filename*=UTF-8\'\'' + quote('图片展示-制作包.pdf', safe=''))
        self.assertEqual(response['headers']['X-Content-Type-Options'], 'nosniff')

    def test_conflict_is_409_and_old_version_requires_explicit_flag(self):
        with patch.object(assist, 'get_run_download', side_effect=assets.Conflict('请确认旧版')) as download:
            response = self.handler().do_GET()
        self.assertEqual(response['status'], 409)
        self.assertIn('确认旧版', response['error'])
        with patch.object(assist, 'get_run_download', return_value=('旧版-图片展示-制作包.pdf', b'%PDF-test', 'application/pdf')) as download:
            self.handler({'allow_stale': ['1']}).do_GET()
        download.assert_called_once_with(PID, RID, 'pdf', True)

    def test_invalid_query_and_missing_markdown_are_clear_errors(self):
        with patch.object(assist, 'get_run_download') as download:
            response = self.handler({'allow_stale': ['true']}).do_GET()
        self.assertEqual(response['status'], 400)
        download.assert_not_called()
        with patch.object(assist, 'get_run_download', side_effect=ValueError('这份记录没有完整制作包')):
            response = self.handler().do_GET()
        self.assertEqual(response, {'status': 400, 'error': '这份记录没有完整制作包'})

    def test_download_uses_existing_authentication(self):
        handler = self.handler()
        handler._auth_ok = lambda: False
        handler._need_auth = lambda: {'status': 401}
        with patch.object(assist, 'get_run_download') as download:
            self.assertEqual(handler.do_GET(), {'status': 401})
        download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
