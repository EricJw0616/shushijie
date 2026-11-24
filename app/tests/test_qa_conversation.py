# -*- coding: utf-8 -*-
"""Conversational wording keeps its evidence and remains subject to verification."""
import copy
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_qa_service as fixtures

Q = fixtures.Q


class ConversationalClaimsTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 1, 'code': 'A1', 'book': '植物观察',
                       'quote': '植物需要光照和水分，观察叶片可以了解植物的变化。'}
        self.payload = {'status': 'answered', 'claims': [
            {'role': 'direct', 'text': '植物需要光照和水分。', 'source_ids': [1],
             'support': [{'source_id': 1, 'quote': self.source['quote']}]},
            {'role': 'action', 'text': '可以观察叶片了解植物的变化。', 'source_ids': [1],
             'support': [{'source_id': 1, 'quote': self.source['quote']}]},
        ], 'suggestions': ['怎样观察叶片？']}
        self.request = Q.prepare_question({'question': '那我可以怎么观察它？',
            'history': [{'role': 'user', 'content': '想了解植物的变化。'},
                        {'role': 'assistant', 'content': '可以先观察叶片。'}]})

    def rewrite(self, response=None, error=None, sources=None):
        with patch.object(Q.llm, 'chat', return_value=response, side_effect=error) as model:
            result = Q._conversational_claims(self.payload, self.request, sources or [self.source])
        return result, model

    def test_changes_only_text_preserves_evidence_roles_and_input_and_passes_question_context(self):
        paragraphs = ['植物需要光照和水分，你可以先记住这两点。', '你可以从叶片入手，看看植物有什么变化。']
        original_payload, original_source = copy.deepcopy(self.payload), copy.deepcopy(self.source)
        (rewritten, usage), model = self.rewrite({'text': json.dumps({'paragraphs': paragraphs}), 'usage': {'total_tokens': 7}})
        expected = copy.deepcopy(self.payload)
        for claim, text in zip(expected['claims'], paragraphs):
            claim['text'] = text
        self.assertEqual(rewritten, expected)
        self.assertEqual(usage, {'total_tokens': 7})
        self.assertEqual(self.payload, original_payload)
        self.assertEqual(self.source, original_source)
        self.assertIsNot(rewritten, self.payload)
        packet = json.loads(model.call_args.args[0][-1]['content'])
        self.assertEqual(packet['task'], 'conversational_reply')
        self.assertEqual(packet['question'], self.request['question'])
        self.assertEqual(packet['history'], self.request['history'])
        self.assertEqual(packet['paragraphs'], [claim['text'] for claim in self.payload['claims']])
        self.assertEqual(Q._validate_answer(rewritten, [self.source])[1][0]['claim'], paragraphs[0])

    def test_unsupported_numeric_claim_rolls_back_the_entire_rewrite(self):
        paragraphs = ['植物每天需要365小时光照和水分。', '你可以从叶片入手观察植物。']
        (rewritten, usage), _model = self.rewrite({'text': json.dumps({'paragraphs': paragraphs}), 'usage': {'total_tokens': 7}})
        self.assertEqual(rewritten, self.payload)
        self.assertNotIn('365', Q._validate_answer(rewritten, [self.source])[0])
        self.assertEqual(usage, {'total_tokens': 7}, 'discarding a rewrite must not hide the tokens already spent')

    def test_bad_json_shape_count_or_paragraph_content_rolls_back(self):
        values = [[], {}, {'paragraphs': []}, {'paragraphs': ['只有一段植物观察']},
                  {'paragraphs': '植物需要光照和水分。'},
                  {'paragraphs': ['植物需要光照和水分。', 2]},
                  {'paragraphs': ['植物需要光照和水分。', '   ']},
                  {'paragraphs': ['植物需要光照和水分。', '叶' * 701]}]
        responses = [{'text': json.dumps(value)} for value in values] + [{'text': '{not JSON'}]
        for response in responses:
            with self.subTest(response=str(response)[:90]):
                (rewritten, _), _model = self.rewrite(response)
                self.assertEqual(rewritten, self.payload)

    def test_timeout_or_provider_failure_falls_back_without_changing_input(self):
        for error in (TimeoutError('test timeout'), RuntimeError('test provider failure')):
            with self.subTest(error=type(error).__name__):
                original = copy.deepcopy(self.payload)
                (rewritten, _), _model = self.rewrite(error=error)
                self.assertEqual(rewritten, original)
                self.assertEqual(self.payload, original)

    def test_merging_paragraphs_keeps_all_unique_evidence_and_role_priority_without_mutating_input(self):
        second = {'id': 2, 'code': 'B2', 'book': '植物记录', 'quote': '每天记录叶片的生长变化。'}
        self.payload['claims'][1].update(text='可以每天记录叶片的生长变化。', source_ids=[1, 2],
            support=[{'source_id': 1, 'quote': self.source['quote']}, {'source_id': 2, 'quote': second['quote']}])
        sources = [self.source, second]
        original_payload, original_sources = copy.deepcopy(self.payload), copy.deepcopy(sources)
        wording = '你可以先了解植物需要的光照和水分，再每天记录叶片的生长变化。'
        # The action paragraph is listed first, but direct still has the higher role priority.
        response = {'text': json.dumps({'paragraphs': [{'text': wording, 'claim_ids': [2, 1]}]})}
        (rewritten, _), _model = self.rewrite(response, sources=sources)
        self.assertEqual(len(rewritten['claims']), 1)
        claim = rewritten['claims'][0]
        self.assertEqual(claim['text'], wording)
        self.assertEqual(claim['role'], 'direct')
        self.assertEqual(claim['source_ids'], [1, 2])
        self.assertEqual(claim['support'], [
            {'source_id': 1, 'quote': self.source['quote']}, {'source_id': 2, 'quote': second['quote']}])
        self.assertEqual(rewritten['suggestions'], original_payload['suggestions'])
        answer, checks, _ = Q._validate_answer(rewritten, sources, comparison_codes=['A1', 'B2'])
        self.assertIn('[1][2]', answer)
        self.assertEqual([e['book'] for e in checks[0]['evidence']], ['植物观察', '植物记录'])
        self.assertEqual(self.payload, original_payload)
        self.assertEqual(sources, original_sources)
        claim['support'][0]['quote'] = '修改返回对象不会修改原草稿'
        self.assertEqual(self.payload, original_payload)
        self.assertEqual(sources, original_sources)

    def test_incomplete_duplicate_out_of_range_or_boolean_claim_mapping_rolls_back(self):
        mappings = [([1],), ([1, 1, 2],), ([1], [1, 2]), ([1, 3],), ([0, 2],),
                    ([True, 2],), ([1.0, 2],), (['1', 2],), ([],)]
        for groups in mappings:
            with self.subTest(groups=groups):
                response = {'text': json.dumps({'paragraphs': [
                    {'text': '植物需要光照和水分，可以观察叶片了解植物的变化。', 'claim_ids': ids}
                    for ids in groups]})}
                original = copy.deepcopy(self.payload)
                (rewritten, _), _model = self.rewrite(response)
                self.assertEqual(rewritten, original)
                self.assertEqual(self.payload, original)

    def test_merged_paragraph_with_unsupported_number_is_rejected_and_original_claims_survive(self):
        response = {'text': json.dumps({'paragraphs': [{
            'text': '植物每天需要365小时光照，你可以观察叶片了解植物的变化。', 'claim_ids': [1, 2]}]})}
        (rewritten, _), _model = self.rewrite(response)
        self.assertEqual(rewritten, self.payload)
        self.assertEqual(len(rewritten['claims']), 2)
        self.assertNotIn('365', Q._validate_answer(rewritten, [self.source])[0])


class ConversationalPipelineTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the temporary-book fixture, without inheriting its test cases.
        self.books = fixtures.QATests()
        self.addCleanup(self.books.doCleanups)
        self.books.setUp()

    def ask(self, model):
        with patch.object(Q.llm, 'ready', return_value=True), patch.object(Q.llm, 'chat', side_effect=model):
            return Q.ask({'question': '植物光照和水分以及叶片变化', 'book_codes': ['A1']})

    def generated(self, packet):
        source = next(s for s in packet['sources'] if '需要光照和水分' in s['quote'])
        claims = [{'role': 'direct', 'text': '植物需要光照和水分。'},
                  {'role': 'action', 'text': '可以观察叶片了解植物的变化。'}]
        for claim in claims:
            claim.update(source_ids=[source['id']], support=[{'source_id': source['id'], 'quote': source['quote']}])
        return {'text': json.dumps({'status': 'answered', 'claims': claims, 'suggestions': ['怎样继续观察？']}),
                'usage': {'total_tokens': 10}}

    def test_independent_verifier_checks_rewritten_claims_and_removes_unsupported_facts(self):
        accepted = '植物需要光照和水分，你可以先了解这些基本条件。'
        unsupported = '观察叶片就能保证植物永远不会枯萎。'
        seen = []

        def model(messages, **kwargs):
            packet = json.loads(messages[-1]['content'])
            if packet.get('task') == 'conversational_reply':
                seen.append('rewrite')
                return {'text': json.dumps({'paragraphs': [accepted, unsupported]}), 'usage': {'total_tokens': 7}}
            if 'claims' in packet:
                seen.append('verify')
                self.assertEqual([claim['claim'] for claim in packet['claims']], [accepted, unsupported])
                self.assertTrue(all(claim['evidence'][0]['quote'].startswith('植物需要光照和水分') for claim in packet['claims']))
                return {'text': '{"supported":[true,false]}', 'usage': {'total_tokens': 3}}
            seen.append('generate')
            return self.generated(packet)

        result = self.ask(model)
        self.assertEqual(seen, ['generate', 'rewrite', 'verify'])
        self.assertEqual(result['mode'], 'answer')
        self.assertIn(accepted, result['answer'])
        self.assertNotIn('永远不会枯萎', result['answer'])
        self.assertIn('未通过原文核对的内容已排除', result['notice'])
        self.assertEqual(result['suggestions'], [])
        self.assertEqual(result['usage']['total_tokens'], 20)

    def test_semantically_unsupported_rewrite_cannot_bypass_final_verification(self):
        paragraphs = ['植物不需要光照和水分。', '观察叶片能保证植物永远不会枯萎。']

        def model(messages, **kwargs):
            packet = json.loads(messages[-1]['content'])
            if packet.get('task') == 'conversational_reply':
                return {'text': json.dumps({'paragraphs': paragraphs})}
            if 'claims' in packet:
                self.assertEqual([claim['claim'] for claim in packet['claims']], paragraphs)
                return {'text': '{"supported":[false,false]}'}
            return self.generated(packet)

        result = self.ask(model)
        self.assertEqual(result['mode'], 'sources_only')
        self.assertEqual(result['answer'], '')

    def test_invalid_rewrite_still_verifies_and_answers_from_original_claims(self):
        for failure in ('numbers', 'shape', 'timeout'):
            verified = []

            def model(messages, **kwargs):
                packet = json.loads(messages[-1]['content'])
                if packet.get('task') == 'conversational_reply':
                    if failure == 'timeout':
                        raise TimeoutError('test timeout')
                    if failure == 'shape':
                        return {'text': '{"paragraphs":[]}'}
                    return {'text': json.dumps({'paragraphs': ['植物每天需要365小时光照。', '可以观察叶片了解植物的变化。']})}
                if 'claims' in packet:
                    verified.extend(claim['claim'] for claim in packet['claims'])
                    return {'text': '{"supported":[true,true]}'}
                return self.generated(packet)

            with self.subTest(failure=failure):
                result = self.ask(model)
                self.assertEqual(verified, ['植物需要光照和水分。', '可以观察叶片了解植物的变化。'])
                self.assertEqual(result['mode'], 'answer')
                self.assertIn('植物需要光照和水分。', result['answer'])
                self.assertNotIn('365', result['answer'])


if __name__ == '__main__':
    unittest.main()
