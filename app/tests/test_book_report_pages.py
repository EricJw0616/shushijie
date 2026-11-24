# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store


class BookReportPageTests(unittest.TestCase):
    def report(self, record, original=None):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(store.E, 'OUT', directory), \
             patch.object(store.E, 'book_json', return_value={}), \
             patch.object(store, 'get_record', return_value=record), \
             patch.object(store, 'get_entities', return_value={'counts': {}}), \
             patch.object(store, 'original_pdf', return_value=original):
            return store.book_report('T01')

    def test_legacy_record_has_unknown_page_coverage_not_zero_issues(self):
        report = self.report({'book': '旧书', 'source_pages': 25})
        self.assertNotIn('source_page_issues', report)
        self.assertEqual(report['source_pages'], 25)
        self.assertFalse(report['has_original_pdf'])

    def test_completed_parse_preserves_empty_page_issue_list(self):
        report = self.report({'source_page_issues': {}, 'source_pages': 12}, '/temporary/original.pdf')
        self.assertEqual(report['source_page_issues'], {})
        self.assertTrue(report['has_original_pdf'])

    def test_report_keeps_physical_page_numbers_and_all_supported_reasons(self):
        record = {'source_pages': 30, 'source_page_issues': {
            'blank': [30, 2, 2, 0, -1, True, '3', None, 4.5],
            'no_text': [11], 'review': [9, 8], 'failed': [18],
            'unavailable': [19], 'layout_review': [8], 'non_body': [28],
            'unsupported': [27],
        }}
        report = self.report(record)
        self.assertEqual(report['source_page_issues'], {
            'blank': [2, 30], 'no_text': [11], 'review': [8, 9],
            'failed': [18], 'unavailable': [19], 'layout_review': [8], 'non_body': [28],
        })
        self.assertEqual(record['source_page_issues']['review'], [9, 8])

    def test_malformed_coverage_does_not_turn_into_a_clean_report(self):
        for issues in (None, [], 'unknown'):
            with self.subTest(issues=issues):
                report = self.report({'source_page_issues': issues, 'source_pages': True})
                self.assertNotIn('source_page_issues', report)
                self.assertNotIn('source_pages', report)


if __name__ == '__main__':
    unittest.main()
