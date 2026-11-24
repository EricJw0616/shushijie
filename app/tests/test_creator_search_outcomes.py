import sys
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'platform' / 'engine'))
import creator_match
import creator_works
import creator_work_search as search


class SearchOutcomes(unittest.TestCase):
    book = {'title': '历史故事选', 'synopsis': '讲述时苗留犊、赵广汉治颍川的故事。'}
    terms = ('时苗留犊', '赵广汉治颍川')
    url = 'https://www.douyin.com/video/7111111111111111111'

    def lookup(self, provider, status='no_match'):
        creator = creator_match.Creator(2, '001', '讲故事', (), '')
        result = {'matches': [], 'content_status': status, 'content_notice': '作品分析暂时不可用。'}
        with patch.object(search, '_search_backend', return_value=(provider, 'test')), \
             patch.object(search, '_search_topic', return_value=self.terms), \
             patch.object(creator_works, 'read_works', return_value={}), \
             patch.object(creator_match, '_snapshot', return_value=([creator], {})), \
             patch.object(creator_match, 'match', return_value=result):
            return search.lookup(self.book)

    def test_independent_stories_get_independent_site_queries(self):
        self.assertEqual(search._queries(self.terms, None),
                         ('时苗留犊 site:douyin.com/video', '赵广汉治颍川 site:douyin.com/video'))

    def test_conflicting_authorship_cannot_pass_by_search_order(self):
        def provider(query, key):
            account = '001' if self.terms[0] in query else 'outside_library'
            return [{'title': '历史故事', 'url': self.url, 'author': {'unique_id': account}}]

        result = self.lookup(provider)
        self.assertEqual(result['search_reason'], 'unverified_owner')
        self.assertEqual(result['public_work_count'], 1)
        self.assertEqual(result['verified_work_count'], 0)
        self.assertEqual(result['search_terms'], list(self.terms))
        self.assertEqual(result['matches'], [])

    def test_offline_and_analysis_failures_have_distinct_reasons(self):
        def partly_unavailable(query, key):
            if self.terms[0] in query:
                raise search.SearchUnavailable()
            return []

        self.assertEqual(self.lookup(None)['search_reason'], 'search_unconfigured')
        self.assertEqual(self.lookup(partly_unavailable)['search_reason'], 'search_unavailable')
        self.assertEqual(self.lookup(lambda q, k: [])['search_reason'], 'no_public_works')
        hit = {'title': '历史故事', 'url': self.url, 'author': {'unique_id': '001'}}
        online = lambda q, k: [hit]
        evaluated = self.lookup(online)
        self.assertEqual(evaluated['search_reason'], 'no_content_overlap')
        self.assertEqual(evaluated['verified_work_count'], 1)
        self.assertEqual(self.lookup(online, 'analysis_unavailable')['search_reason'], 'analysis_unavailable')

    def test_verified_account_with_placeholder_title_needs_content(self):
        hit = {'title': '快来看看我的视频吧', 'url': self.url, 'author': {'unique_id': '001'}}
        result = self.lookup(lambda q, k: [hit])
        self.assertEqual(result['search_reason'], 'missing_work_content')
        self.assertEqual(result['verified_work_count'], 1)
        self.assertEqual(result['matches'], [])
