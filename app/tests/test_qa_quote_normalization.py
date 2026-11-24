# -*- coding: utf-8 -*-
"""Quote-boundary repairs must retain exact evidence checks; no model calls."""
import copy
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import qa_service as Q


class QuoteNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.source = {'id': 1, 'code': 'A1', 'book': '植物观察',
                       'quote': '植物有30片叶片，每天记录叶片的生长变化。'}
        self.sources = [self.source]
        guard = patch.object(Q.llm, 'chat', side_effect=AssertionError('unit tests must not call a model'))
        guard.start()
        self.addCleanup(guard.stop)

    def payload(self, quote, text='每天记录叶片的生长变化。', source_id=1):
        return {'status': 'answered', 'claims': [{'text': text, 'source_ids': [1],
                'support': [{'source_id': source_id, 'quote': quote}]}],
                'suggestions': ['怎样记录叶片？']}

    def test_only_boundary_quote_marks_are_removed_before_exact_validation(self):
        original_quote = self.source['quote']
        for opening, closing in [('“', '”'), ('“', ''), ('', '”'), ('‘', '’'), ('"', '"'), ('“‘', '’”')]:
            with self.subTest(opening=opening, closing=closing):
                payload = self.payload(opening + original_quote + closing)
                normalized = Q._normalize_support_quotes(payload, self.sources)
                self.assertEqual(normalized['claims'][0]['support'][0]['quote'], original_quote)
                answer, checks, suggestions = Q._validate_answer(normalized, self.sources)
                self.assertIn('每天记录叶片的生长变化。 [1]', answer)
                self.assertEqual(checks[0]['evidence'][0]['quote'], original_quote)
                self.assertEqual(suggestions, payload['suggestions'])

    def test_already_literal_quotes_are_preserved_even_when_they_have_quote_marks(self):
        source = dict(self.source, quote='他说：“每天记录叶片的生长变化。”随后离开。')
        for quote in ['“每天记录叶片的生长变化。”', '每天记录叶片的生长变化。', '每天记录叶片的生长变化。”']:
            with self.subTest(quote=quote):
                payload = self.payload(quote)
                normalized = Q._normalize_support_quotes(payload, [source])
                self.assertEqual(normalized, payload)
                self.assertEqual(Q._validate_answer(normalized, [source])[1][0]['evidence'][0]['quote'], quote)

    def test_internal_edits_ellipsis_and_changed_digits_are_not_repaired(self):
        quotes = [
            '“植物有30片叶片，每周记录叶片的生长变化。”',
            '“植物有30片叶片……每天记录叶片的生长变化。”',
            '“植物有3片叶片，每天记录叶片的生长变化。”',
            '“植物有30片叶片，每天记录“叶片”的生长变化。”',
        ]
        for quote in quotes:
            with self.subTest(quote=quote):
                payload = self.payload(quote)
                normalized = Q._normalize_support_quotes(payload, self.sources)
                self.assertEqual(normalized, payload)
                with self.assertRaisesRegex(ValueError, '逐字原文'):
                    Q._validate_answer(normalized, self.sources)

    def test_normalizing_a_valid_quote_does_not_allow_an_unsupported_claim_number(self):
        payload = self.payload('“' + self.source['quote'] + '”', text='植物有3片叶片。')
        normalized = Q._normalize_support_quotes(payload, self.sources)
        self.assertEqual(normalized['claims'][0]['support'][0]['quote'], self.source['quote'])
        with self.assertRaisesRegex(ValueError, '未支持的数字'):
            Q._validate_answer(normalized, self.sources)

    def test_evidence_must_match_its_own_source_and_a_valid_integer_source_id(self):
        other = {'id': 2, 'code': 'B2', 'book': '星空观察', 'quote': '观察星空需要避开城市灯光。'}
        for source_id, quote in [(1, '“' + other['quote'] + '”'),
                                 (99, '“' + self.source['quote'] + '”'),
                                 (True, '“' + self.source['quote'] + '”'),
                                 ('1', '“' + self.source['quote'] + '”')]:
            with self.subTest(source_id=source_id, quote=quote):
                payload = self.payload(quote, source_id=source_id)
                normalized = Q._normalize_support_quotes(payload, self.sources + [other])
                self.assertEqual(normalized, payload)
                with self.assertRaisesRegex(ValueError, '逐字原文'):
                    Q._validate_answer(normalized, self.sources + [other])

    def test_minimum_literal_length_is_preserved_and_unlisted_punctuation_is_not_stripped(self):
        for quote in ['“叶片”', "'" + self.source['quote'] + "'", '《' + self.source['quote'] + '》']:
            with self.subTest(quote=quote):
                payload = self.payload(quote)
                normalized = Q._normalize_support_quotes(payload, self.sources)
                self.assertEqual(normalized, payload)
                with self.assertRaisesRegex(ValueError, '逐字原文'):
                    Q._validate_answer(normalized, self.sources)
        payload = self.payload('“生长变化”', text='记录生长变化。')
        normalized = Q._normalize_support_quotes(payload, self.sources)
        self.assertEqual(normalized['claims'][0]['support'][0]['quote'], '生长变化')
        self.assertTrue(Q._validate_answer(normalized, self.sources)[0])

    def test_normalization_copies_payload_and_does_not_modify_sources_or_other_fields(self):
        payload = self.payload('“' + self.source['quote'] + '”')
        payload['metadata'] = {'nested': ['原始元信息']}
        original_payload, original_sources = copy.deepcopy(payload), copy.deepcopy(self.sources)
        normalized = Q._normalize_support_quotes(payload, self.sources)
        self.assertEqual(payload, original_payload)
        self.assertEqual(self.sources, original_sources)
        self.assertIsNot(normalized, payload)
        expected = copy.deepcopy(payload)
        expected['claims'][0]['support'][0]['quote'] = self.source['quote']
        self.assertEqual(normalized, expected)
        normalized['claims'][0]['support'][0]['quote'] = '修改返回对象'
        normalized['metadata']['nested'].append('修改返回对象')
        self.assertEqual(payload, original_payload)


if __name__ == '__main__':
    unittest.main()
