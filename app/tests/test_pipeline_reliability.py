"""隔离回归：结构反例、稳定身份、失败保留与真实作业状态。
不调用模型，不写业务书库。
"""
import copy
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from contextlib import nullcontext
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'platform/engine')]
import cards
import paths
import structure
import tocclean
import understanding
import pipeline
import runner
import tag_all


class StructureTests(unittest.TestCase):
    def test_person_profile_name_on_next_line_starts_new_chapter(self):
        text = ('<<<PAGE 5>>>\n姓名：张三\n生卒年：1900—1950\n正文甲。\n'
                '<<<PAGE 6>>>\n姓名：\n李四\n生卒年：1901—1951\n正文乙。\n'
                '<<<PAGE 7>>>\n姓名: 王五\n生卒年：1902—1952\n正文丙。')
        people = [{'name': name, 'page': page} for name, page in [('张三', 5), ('李四', 6), ('王五', 7)]]
        plan = pipeline._people_plan(text, people)
        self.assertEqual([(title, page) for title, _, page in structure.outline(text, plan)],
                         [('张三', 5), ('李四', 6), ('王五', 7)])

    def test_all_thirteen_sunzi_chapters(self):
        text = (ROOT / '孙子兵法_简体全文.txt').read_text()
        plan = structure.probe(text)
        heads = structure.outline(text, plan)
        self.assertEqual(len(heads), 13)
        self.assertIn('始计篇', heads[0][0])
        self.assertIn('用间篇', heads[-1][0])

    def test_numbered_sentence_is_not_a_chapter(self):
        text = '第一 今日看过这篇。\n第二 我们今天读第二篇。\n第三 先看完这章。'
        self.assertNotEqual(structure.probe(text).get('pattern'), 'pianlead')

    def test_known_directory_fragment_is_flagged(self):
        seg = {'id': 'B66-01-P01', '篇序': 1, '篇': '附录：个人·群体·社会——',
               '文本': '一生学术历程的自我思考', '锚点': 'B66-01-P01'}
        report = tocclean.audit([seg], [{'篇': seg['篇']}])
        self.assertTrue(report['异常'])
        self.assertEqual(report['异常短篇'][0]['汉字'], 11)

    def test_flat_is_review_not_no_headings_claim(self):
        report = tocclean.audit([{'文本': '孙子曰兵者国之大事', '篇序': 0}], [])
        self.assertTrue(report['结构待复核'])
        self.assertNotIn('无任何结构标记', pipeline._pname_quality([], 'flat')['说明'])


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(paths, 'OUT', self.temp.name)
        self.patcher.start()
        self.folder = pathlib.Path(self.temp.name) / 'B64'
        self.folder.mkdir()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def write_rows(self, rows):
        cards.save_identity_registry('B64', rows)
        (self.folder / 'cards.jsonl').write_text(''.join(json.dumps(x, ensure_ascii=False)+'\n' for x in rows))

    def test_reorder_and_retire_never_reuses_old_identity(self):
        rows = [{'id': 'B64-C001', '类型': '引书候选', '原文': '第一本书的引用材料', '字段': {'书名': '甲'}},
                {'id': 'B64-C002', '类型': '引书候选', '原文': '第二本书的引用材料', '字段': {'书名': '乙'}}]
        self.write_rows(rows)
        reordered = cards.stable_card_ids(copy.deepcopy(rows[::-1]), 'B64')
        self.assertEqual([x['id'] for x in reordered], ['B64-C002', 'B64-C001'])
        self.write_rows(reordered[:1])
        new = {'类型': '引书候选', '原文': '新加入的第三本书内容', '字段': {'书名': '丙'}}
        after = cards.stable_card_ids([copy.deepcopy(rows[1]), new], 'B64')
        self.assertEqual([x['id'] for x in after], ['B64-C002', 'B64-C003'])

    def test_existing_b64_ids_survive_reordered_extraction(self):
        original = [json.loads(x) for x in (ROOT/'platform/out/B64/cards.jsonl').read_text().splitlines()]
        self.write_rows(original)
        changed = cards.stable_card_ids(copy.deepcopy(original[1:][::-1]), 'B64')
        self.assertEqual({x['id']: cards.card_fingerprint(x) for x in changed},
                         {x['id']: cards.card_fingerprint(x) for x in original[1:]})


class LastGoodTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(understanding, 'OUT', self.temp.name)
        self.patcher.start()
        self.folder = pathlib.Path(self.temp.name) / 'T01'
        self.folder.mkdir()
        self.old = {'code': 'T01', 'quotes': [{'quote': '已有核对通过的完整原文句子', 'seg': 'T01-01-P01'}],
                    'themes': [{'议题': '已有议题'}], 'summaries': [{'篇': '第一章', 'summary': '已有摘要'}]}
        (self.folder/'understanding.json').write_text(json.dumps(self.old, ensure_ascii=False))
        row = {'id': 'T01-01-P01', '篇': '第一章', '文本': '这是一段完整的原文证据用于检查模型失败时应该保留已经生成并核对过的内容。'}
        (self.folder/'segments.jsonl').write_text(json.dumps(row, ensure_ascii=False)+'\n')
        (self.folder/'outline.jsonl').write_text(json.dumps({'篇': '第一章'}, ensure_ascii=False)+'\n')

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_model_failures_keep_previous_outputs(self):
        with patch.object(understanding.llm, 'chat', side_effect=RuntimeError('simulated failure')):
            for key in ('quotes', 'themes', 'summaries'):
                items, stats = getattr(understanding, key)('T01')
                self.assertEqual(items, self.old[key])
                self.assertGreater(stats['blocked'], 0)
        result = json.loads((self.folder/'understanding.json').read_text())
        for key in ('quotes', 'themes', 'summaries'):
            self.assertEqual(result[key], self.old[key])
            self.assertTrue(result['processing'][key]['retained_previous'])
            self.assertEqual(result['processing'][key]['status'], 'failed')

    def test_failed_refresh_does_not_clear_stale_source(self):
        before = copy.deepcopy(self.old)
        before['stale'] = True
        before['processing'] = {'themes': {'status': 'stale'}}
        (self.folder/'understanding.json').write_text(json.dumps(before))
        got = understanding._save('T01', 'themes', [], {'blocked': 1})
        self.assertTrue(got['stale'])
        self.assertTrue(got['processing']['themes']['source_stale'])

    def test_success_can_replace_with_genuine_empty_result(self):
        got = understanding._save('T01', 'quotes', [], {'blocked': 0, 'kept': 0})
        self.assertEqual(got['quotes'], [])
        self.assertEqual(got['processing']['quotes']['status'], 'done')

    def test_adapter_http_failure_keeps_previous_outputs_and_marks_failure(self):
        # Exercise the actual llm.chat error adapter, not just a mocked business exception.
        cfg = {'BOOKDISTILL_LLM_BASE': 'https://invalid.test/v1',
               'BOOKDISTILL_LLM_KEY': 'test-only', 'BOOKDISTILL_LLM_MODEL': 'test-model'}
        def denied(*args, **kwargs):
            raise urllib.error.HTTPError('https://invalid.test', 401, 'Unauthorized', {}, io.BytesIO(b'{"error":"denied"}'))
        with patch.object(understanding.llm, 'CFG', cfg), \
             patch.object(understanding.llm.urllib.request, 'urlopen', side_effect=denied) as call:
            for key in ('quotes', 'themes', 'summaries'):
                items, stats = getattr(understanding, key)('T01')
                self.assertEqual(items, self.old[key])
                self.assertGreater(stats['blocked'], 0)
                self.assertIn('HTTP 401', stats['last_error'])
            self.assertEqual(call.call_count, 3)

    def test_empty_api_response_does_not_erase_previous_outputs(self):
        cfg = {'BOOKDISTILL_LLM_BASE': 'https://invalid.test/v1',
               'BOOKDISTILL_LLM_KEY': 'test-only', 'BOOKDISTILL_LLM_MODEL': 'test-model'}
        def empty_response(*args, **kwargs):
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': ''}}]}).encode())
        with patch.object(understanding.llm, 'CFG', cfg), \
             patch.object(understanding.llm.urllib.request, 'urlopen', side_effect=empty_response):
            for key in ('quotes', 'themes', 'summaries'):
                items, stats = getattr(understanding, key)('T01')
                self.assertEqual(items, self.old[key])
                self.assertGreater(stats['blocked'], 0)
        result = json.loads((self.folder/'understanding.json').read_text())
        self.assertTrue(all(result['processing'][k]['retained_previous'] for k in ('quotes', 'themes', 'summaries')))

    def test_explicit_empty_selection_is_success(self):
        with patch.object(understanding.llm, 'chat', return_value={'text': 'NONE', 'model': 'test-model'}):
            for key in ('quotes', 'themes'):
                items, stats = getattr(understanding, key)('T01')
                self.assertEqual(items, [])
                self.assertFalse(stats.get('blocked'))

    def test_unverifiable_model_quotes_are_not_a_successful_empty_result(self):
        text = 'SEG: T01-01-P01\nQUOTE: 这条引文完全不在任何原文段落里面。\nTHEME: 测试主题\nWHY: 无依据'
        with patch.object(understanding.llm, 'chat', return_value={'text': text, 'model': 'test-model'}):
            for key in ('quotes', 'themes'):
                items, stats = getattr(understanding, key)('T01')
                self.assertEqual(items, self.old[key])
                self.assertGreater(stats['blocked'], 0)

    def test_missing_and_empty_outline_block_summaries_without_calling_model(self):
        op = self.folder/'outline.jsonl'
        for absent in (True, False):
            if absent:
                op.unlink()
            else:
                op.write_text('')
            with patch.object(understanding.llm, 'chat') as call:
                items, stats = understanding.summaries('T01')
                call.assert_not_called()
            self.assertEqual(items, self.old['summaries'])
            self.assertGreater(stats['blocked'], 0)
            result = json.loads((self.folder/'understanding.json').read_text())
            self.assertTrue(result['processing']['summaries']['source_stale'])
            self.assertTrue(result['processing']['summaries']['retained_previous'])

    def test_partial_summary_attempt_preserves_previous_complete_set(self):
        row = {'id': 'T01-02-P01', '篇': '第二章', '文本': '另一篇的正文包含足够的信息并且篇章结构有效用于检验部分批次失败时的保存策略。'}
        with (self.folder/'segments.jsonl').open('a') as fp:
            fp.write(json.dumps(row, ensure_ascii=False)+'\n')
        with (self.folder/'outline.jsonl').open('a') as fp:
            fp.write(json.dumps({'篇': '第二章'}, ensure_ascii=False)+'\n')
        with patch.object(understanding.llm, 'chat', side_effect=[{'text': 'SUMMARY: 这次成功的摘要。'}, {'text': ''}]):
            items, stats = understanding.summaries('T01')
        self.assertEqual(items, self.old['summaries'])
        self.assertEqual(stats['kept'], 1)
        self.assertEqual(stats['blocked'], 1)
        attempt = json.loads((self.folder/'understanding.json').read_text())['processing']['summaries']
        self.assertEqual(attempt['status'], 'partial')
        self.assertTrue(attempt['retained_previous'])
        self.assertFalse(attempt.get('source_stale'))

    def test_successful_product_does_not_clear_other_legacy_stale_products(self):
        before = dict(self.old, stale=True)
        (self.folder/'understanding.json').write_text(json.dumps(before))
        got = understanding._save('T01', 'quotes', [], {'blocked': 0, 'kept': 0})
        self.assertEqual(got['processing']['quotes']['status'], 'done')
        self.assertNotIn('source_stale', got['processing']['quotes'])
        self.assertEqual(got['processing']['summaries']['status'], 'stale')
        self.assertTrue(got['stale'])

    def test_explicit_summaries_job_done_partial_and_failed(self):
        row = {'id': 'T01-02-P01', '篇': '第二章', '文本': '另一篇的正文包含足够的信息并且篇章结构有效用于检验部分批次失败时的保存策略。'}
        with (self.folder/'segments.jsonl').open('a') as fp:
            fp.write(json.dumps(row, ensure_ascii=False)+'\n')
        with (self.folder/'outline.jsonl').open('a') as fp:
            fp.write(json.dumps({'篇': '第二章'}, ensure_ascii=False)+'\n')
        good = {'text': 'SUMMARY: 有原文依据的测试摘要。'}
        bad = RuntimeError('test model unavailable')
        for expected, responses, kept in [('done', [good, good], 2),
                                           ('partial', [good, bad], 1),
                                           ('failed', [bad, bad], 0)]:
            with self.subTest(status=expected):
                (self.folder/'understanding.json').write_text(json.dumps(self.old, ensure_ascii=False))
                job = {'kind': 'summaries', 'book_code': 'T01', 'steps': [], 'warnings': []}
                with patch.object(runner.E, 'OUT', self.temp.name), \
                     patch.object(runner.E, 'book_json', return_value={'code': 'T01'}), \
                     patch.object(runner.store, 'get_job', side_effect=lambda _: copy.deepcopy(job)), \
                     patch.object(runner.store, 'update_job', side_effect=lambda _, **kw: job.update(kw)), \
                     patch.object(runner.store, 'append_job_log'), patch.object(runner.store, 'append_op'), \
                     patch.object(runner.store, 'upsert_book') as upsert, \
                     patch.object(understanding.llm, 'chat', side_effect=responses), \
                     patch.object(sys, 'argv', ['runner.py', 'test-summary-job']):
                    self.assertEqual(runner.main(), 0)
                self.assertEqual(job['status'], expected)
                self.assertEqual(job['progress'], 100)
                self.assertEqual(job['outputs']['summaries']['status'], expected)
                self.assertEqual(job['outputs']['summaries']['kept'], kept)
                saved = json.loads((self.folder/'understanding.json').read_text())
                if expected == 'done':
                    self.assertEqual(len(saved['summaries']), 2)
                    self.assertFalse(job['outputs']['summaries']['retained_previous'])
                else:
                    self.assertEqual(saved['summaries'], self.old['summaries'])
                    self.assertTrue(job['outputs']['summaries']['retained_previous'])
                upsert.assert_not_called()


class PipelineVersionTests(unittest.TestCase):
    def test_complete_pipeline_and_source_change_invalidation(self):
        with tempfile.TemporaryDirectory() as td:
            source = pathlib.Path(td) / '验收书.txt'
            text = (ROOT/'孙子兵法_简体全文.txt').read_text()
            source.write_text(text)
            out = pathlib.Path(td) / 'out'
            with patch.object(paths, 'OUT', str(out)), patch.object(pipeline, 'OUT', str(out)):
                first = pipeline.run_one(str(source), 'T01')
                self.assertEqual(first['篇数'], 13)
                folder = out/'T01'
                initial_cards = [json.loads(l) for l in (folder/'cards.jsonl').read_text().splitlines()]
                pipeline.run_one(str(source), 'T01')
                next_cards = [json.loads(l) for l in (folder/'cards.jsonl').read_text().splitlines()]
                self.assertEqual([r['id'] for r in initial_cards], [r['id'] for r in next_cards])
                previous = {'quotes': [{'quote': '旧引文'}], 'themes': []}
                (folder/'understanding.json').write_text(json.dumps(previous))
                source.write_text(text.replace('国之大事', '国之要事', 1))
                second = pipeline.run_one(str(source), 'T01')
                self.assertNotEqual(first['source_version'], second['source_version'])
                retained = json.loads((folder/'understanding.json').read_text())
                self.assertEqual(retained['quotes'], previous['quotes'])
                self.assertTrue(retained['stale'])
                self.assertEqual(retained['processing']['quotes']['status'], 'stale')
                self.assertTrue(list((folder/'.history').glob('*/understanding.json')))


class JobTests(unittest.TestCase):
    def test_upload_prepares_graph_by_default_without_forcing_a_rebuild(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(runner.KG, 'auto_build', return_value={'meta': {'form': '篇章 · 条目'}}) as build, \
             patch.object(runner, '_set_step') as step:
            runner._upload_graph('J', 'T01', 10)
        build.assert_called_once_with('T01')
        self.assertEqual(step.call_args_list[0].args, ('J', 'kg', 'running'))
        self.assertEqual(step.call_args.args[:3], ('J', 'kg', 'done'))
        self.assertIn('篇章 · 条目', step.call_args.args[-1])

    def test_upload_graph_skip_or_failure_preserves_the_job(self):
        with patch.dict(os.environ, {'BOOKDISTILL_AUTO_GRAPH': '0'}), \
             patch.object(runner.KG, 'auto_build') as build, patch.object(runner, '_set_step') as step:
            runner._upload_graph('J', 'T01', 10)
            build.assert_not_called()
            self.assertEqual(step.call_args.args[:3], ('J', 'kg', 'skipped'))
        with patch.dict(os.environ, {'BOOKDISTILL_AUTO_GRAPH': '1'}), \
             patch.object(runner.KG, 'auto_build', side_effect=SystemExit('没有 book.json')), \
             patch.object(runner, '_set_step') as step, patch.object(runner, '_log') as log:
            runner._upload_graph('J', 'T01', 10)
            self.assertEqual(step.call_args.args[:3], ('J', 'kg', 'partial'))
            log.assert_called_once()

    def test_running_batch_updates_step_details_and_progress(self):
        job = {'progress': 47, 'steps': runner._steps_with_status(runner.UPLOAD_STEPS)}
        with patch.object(runner.store, 'get_job', side_effect=lambda _: copy.deepcopy(job)), \
             patch.object(runner.store, 'update_job', side_effect=lambda _, **fields: job.update(fields)):
            report = runner._batch_progress('T', 'entities')
            report(12, 54)
            progress = job['progress']
            step = next(s for s in job['steps'] if s['key'] == 'entities')
            self.assertEqual(step['detail'], '正在检查第 13 批，共 54 批。')
            self.assertGreater(progress, 47)
            report(30, 54)
            self.assertGreater(job['progress'], progress)
            runner._set_step('T', 'entities', 'partial', '可继续处理。')
            self.assertEqual(job['progress'], 70)

    def test_running_upload_is_not_inferred_as_library_book(self):
        store = runner.store
        with patch.object(store, 'load_library', return_value={'books': {}}), \
             patch.object(store, 'list_jobs', return_value=[{'kind': 'upload', 'status': 'running', 'title': '新书'}]), \
             patch.object(store, '_lock', return_value=nullcontext()), \
             patch.object(runner.E, 'books_json', return_value=[{'code': 'T01', 'book': '新书'}]), \
             patch.object(store, 'save_library') as save:
            self.assertEqual(store.sync_library()['books'], {})
            save.assert_not_called()

    def test_refused_name_batch_keeps_other_labels_and_does_not_resend(self):
        import entities
        import llm
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory) / 'T01'
            folder.mkdir()
            source = [{'id': f'T01-01-P{i:02}', '文本': '浙江教育出版社出版这本书。'} for i in range(9)]
            (folder/'segments.jsonl').write_text('\n'.join(json.dumps(row) for row in source))
            good = {'text': 'SEG: T01-01-P08\nORG: 浙江教育出版社'}
            with patch.object(entities, 'ROOT', directory), patch.object(paths, 'OUT', directory), \
                 patch.object(llm, 'chat', side_effect=[llm.SourceRefusedError(), good]) as chat:
                for _ in range(2):
                    with self.assertRaises(tag_all.NamesNeedReview):
                        tag_all.build_entities('T01')
                self.assertEqual(chat.call_count, 2)
            self.assertIn('T01-01-P08', (folder/'entities.jsonl').read_text())
            status = json.loads((folder/'derivative_status.json').read_text())['entities']
            self.assertEqual((status['status'], status['refused_segments'], status['missing_segments']), ('blocked', 8, 0))

    def test_warning_finishes_as_partial(self):
        job = {'warnings': []}
        with patch.object(runner.store, 'get_job', side_effect=lambda _: copy.deepcopy(job)), \
             patch.object(runner.store, 'update_job', side_effect=lambda _, **kw: job.update(kw)), \
             patch.object(runner.store, 'append_job_log'):
            runner._log('T', '⚠ 结构待复核')
            runner._finish('T', result={'code': 'T01'})
        self.assertEqual(job['status'], 'partial')
        self.assertEqual(job['progress'], 100)
        self.assertEqual(job['warnings'], ['⚠ 结构待复核'])

    def test_marketing_failure_does_not_write_or_fail_book(self):
        import marketing
        job = {'book_code': 'T01', 'steps': []}
        with patch.object(runner.store, 'get_job', return_value=job), \
             patch.object(runner.store, 'update_job') as update, \
             patch.object(runner.store, 'append_job_log'), \
             patch.object(runner.E, 'book_json', return_value={'code': 'T01'}), \
             patch.object(marketing, 'build', side_effect=RuntimeError('offline')), \
             patch.object(marketing, 'write') as write, \
             patch.object(runner.store, 'upsert_book') as upsert:
            runner.run_marketing('T')
        write.assert_not_called()
        upsert.assert_not_called()
        self.assertTrue(any(x.kwargs.get('status') == 'failed' for x in update.call_args_list))

    def test_empty_marketing_categories_do_not_publish_or_overwrite_last_good(self):
        import marketing
        with tempfile.TemporaryDirectory() as td:
            folder = pathlib.Path(td)/'T01'
            folder.mkdir()
            (folder/'marketing.json').write_text('{"previous":"last-good"}')
            empty = {'code': 'T01', 'items': {key: {'value': None if key == 'summary' else [], 'evidence': []}
                                             for key in marketing.TAGS}, 'stats': {'items': 7}}
            with patch.object(paths, 'OUT', td), patch.object(marketing, 'build', return_value=empty), \
                 patch.object(marketing, 'write', wraps=marketing.write) as write:
                with self.assertRaisesRegex(RuntimeError, '原成果保留'):
                    tag_all.build_marketing('T01')
                write.assert_not_called()
            self.assertEqual(json.loads((folder/'marketing.json').read_text()), {'previous': 'last-good'})

    def test_quality_report_checks_current_books_invalid_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            folder = pathlib.Path(td)/'T01'
            folder.mkdir()
            fixtures = {'segments.jsonl': {'id': 'T01-01-P01', '篇': '第一章', '篇序': 1, '文本': '正文包含足够的汉字供质量检查使用。本例故意把卡片的引用锚点设为不存在的位置。'},
                        'outline.jsonl': {'篇': '第一章'},
                        'cards.jsonl': {'id': 'T01-C001', '类型': '规则', '锚点': 'missing', '原文': '不存在的原文依据'},
                        'book.json': {'code': 'T01', 'book': '隔离质量测试'}}
            for name, value in fixtures.items():
                (folder/name).write_text(json.dumps(value, ensure_ascii=False)+'\n')
            with patch.object(runner.E, 'OUT', td), patch.object(runner, '_log') as log:
                report = runner._quality('test-job', 'T01')
            self.assertEqual(report['code'], 'T01')
            self.assertEqual(report['status'], 'needs_review')
            self.assertEqual(report['invalid_anchors'], 1)
            self.assertTrue((folder/'quality.json').exists())
            self.assertTrue(log.called)


if __name__ == '__main__':
    unittest.main()
