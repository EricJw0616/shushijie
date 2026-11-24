"""Regression coverage for candidate evidence and limited subject matching."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parent / 'platform' / 'engine'))
import creator_match
import creator_match_audiences
import creator_content_match
import creator_work_search
import creator_works


class CreatorMatchTests(unittest.TestCase):
    def test_nickname_and_product_categories_never_fill_empty_match_results(self):
        book = {'title': '情绪小怪兽', 'synopsis': '让幼儿在亲子共读的绘本中认识和表达自己的情绪。',
                'audience': '3–6 岁孩子和家长'}
        creator = creator_match.Creator(2, '001', '儿童情绪绘本', ('图书教育',), '童书教育')
        with patch.object(creator_match, '_snapshot', return_value=([creator], {})) as snapshot:
            for goal in ('content', 'sales'):
                result = creator_match.match({**book, 'goal': goal}, works={})
                self.assertEqual(result['matches'], [])
                self.assertEqual(result['content_status'], 'no_works')
                self.assertIn('自动查找公开作品', result['content_notice'])
            snapshot.assert_not_called()

    def test_works_without_valid_content_connection_return_no_match(self):
        works = {'001': [{'id': 'a', 'handle': '001', 'title': '缝纫机的针脚维修', 'text': '',
                          'url': '', 'published': '', 'provenance': '运营录入'}]}
        with patch.object(creator_content_match, '_assess') as model:
            result = creator_match.match({'title': '植物图鉴', 'synopsis': '介绍植物的形态和生态。'}, works=works)
            model.assert_not_called()
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['content_status'], 'no_match')
        self.assertIn('自动查找公开作品', result['content_notice'])

    def test_missing_synopsis_requests_book_content_before_analysis(self):
        with patch.object(creator_works, 'read_works') as read_works:
            result = creator_match.match({'title': '乡土中国'})
            read_works.assert_not_called()
        self.assertEqual(result['matches'], [])
        self.assertEqual(result['content_status'], 'missing_synopsis')
        self.assertIn('图书简介', result['content_notice'])

    def test_rejects_invalid_input(self):
        for invalid in ([], {}, {'title': 0}, {'title': '植物图鉴', 'goal': 'other'}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                creator_match.match(invalid)

    def test_work_content_can_match_a_creator_without_book_category(self):
        creator = creator_match.Creator(2, '001', '喵团星球', ('其他',), '其他')
        works = {'001': [{'id': 'a', 'handle': '001', 'title': '巴格达街区的战后重建',
                           'text': '从市场重新开门讲战后居民如何恢复日常生活。',
                           'url': 'https://example.com/work', 'published': '', 'provenance': '测试资料'}]}
        book = {'title': '走进伊拉克', 'synopsis': '本书跟踪伊拉克居民战后如何恢复日常生活。'}
        match = {'id': '1', 'relation': 'specific', 'book_point': '战后如何恢复日常生活',
                 'work_quote': '市场重新开门', 'connection': '用市场开门的经历衔接书中的战后日常。',
                 'angle': '沿着市场商贩的一天，讲伊拉克居民如何找回日常。',
                 'expression_quote': '从市场重新开门讲战后居民如何恢复日常生活'}
        with patch.object(creator_works, 'read_works', return_value=works), \
             patch.object(creator_content_match, '_assess', return_value=[match]), \
             patch.object(creator_match, '_snapshot', return_value=([creator], {})):
            result = creator_match.match(book)
        self.assertEqual(result['book_topics'], [])
        self.assertEqual(result['content_status'], 'matched')
        self.assertEqual(result['matches'][0]['name'], '喵团星球')
        self.assertEqual(result['matches'][0]['tier'], 'content')
        self.assertEqual(result['matches'][0]['content_match']['works'][0]['url'], 'https://example.com/work')
        self.assertEqual(result['matches'][0]['score'], 100)
        self.assertEqual(result['matches'][0]['content_match']['score_state'], 'strong')
        self.assertTrue(result['matches'][0]['recommend_backup'])

    def test_work_match_rejects_quotes_absent_from_supplied_evidence(self):
        works = {'001': [{'id': 'a', 'handle': '001', 'title': '绘本动画', 'text': '亲子故事分享',
                           'url': '', 'published': '', 'provenance': '测试资料'}]}
        assessment = {'id': '1', 'relation': 'specific', 'book_point': '认识不同感受', 'work_quote': '孩子自动学会管理情绪',
                      'connection': '用类似的亲子故事介绍情绪。', 'angle': '用故事帮助小朋友认识情绪。'}
        with patch.object(creator_content_match, '_assess', return_value=[assessment]):
            self.assertEqual(creator_content_match.compare('情绪绘本', '一本让孩子认识不同感受的绘本。', '', '内容种草', works), {})

    def test_title_only_evidence_remains_weak_despite_specific_case(self):
        work = {'id': 'a', 'handle': '001', 'title': '拍摄巴格达市场重新开门',
                'text': '检索摘要猜测这是街头采访剪辑。', 'url': 'https://example.com/work', 'published': '',
                'provenance': '抖音公开作品 · 标题'}
        assessment = {'id': '1', 'relation': 'specific', 'book_point': '巴格达市场的战后重建',
                      'work_quote': '市场重新开门', 'connection': '标题与书中市场题材具体相接。',
                      'angle': '用市场重开的场景引出章节主题。', 'expression_quote': '这是街头采访剪辑'}
        with patch.object(creator_content_match, '_assess', return_value=[assessment]) as model:
            result = creator_content_match.compare('', '本书记录巴格达市场的战后重建。', '', '内容种草',
                                                   {'001': [work]}, only_handle='001')['001']
        self.assertEqual(json.loads(model.call_args.args[0])['作品'][0]['内容资料'], '')
        self.assertEqual(result['score_state'], 'weak')
        self.assertFalse(result['recommend_backup'])
        self.assertLess(result['score'], 80)
        self.assertEqual(result['score'], sum(item['score'] for item in result['score_details']))

    def test_single_creator_only_assesses_that_creators_works(self):
        work = {'id': 'a', 'handle': '001', 'title': '七夕餐桌', 'text': '凉桌上的一道菜。', 'url': '',
                'published': '', 'provenance': '运营录入'}
        unrelated_handle = {'id': 'b', 'handle': '002', 'title': '巴格达市场', 'text': '', 'url': '',
                            'published': '', 'provenance': '运营录入'}
        with patch.object(creator_content_match, '_assess', return_value=[]) as model:
            creator_content_match.compare('巴格达', '战争岁月的图书。', '', '内容种草',
                                           {'001': [work], '002': [unrelated_handle]}, only_handle='001')
        submitted = json.loads(model.call_args.args[0])['作品']
        self.assertEqual([entry['标题'] for entry in submitted], ['七夕餐桌'])


class CreatorAudienceTests(unittest.TestCase):
    def test_sends_only_book_fields_and_keeps_valid_distinct_options(self):
        reply = {'audiences': [{'label': '购买者', 'text': ' 为孩子挑选情绪绘本的家长 '},
                               {'label': '推广受众', 'text': '为孩子挑选情绪绘本的家长'},
                               {'label': '未知角色', 'text': '一条无效建议'},
                               {'label': '图书读者', 'text': '喜欢亲子共读的孩子'}]}
        with patch.object(creator_match_audiences.llm, 'chat', return_value={'text': json.dumps(reply)}) as chat:
            response = creator_match_audiences.suggest({'title': '情绪绘本', 'synopsis': '亲子共读故事',
                                                        'goal': 'sales', 'book_code': 'B58', 'audience': '原输入'})
        payload = json.loads(chat.call_args.args[0][1]['content'])
        self.assertEqual(payload, {'书名': '情绪绘本', '简介': '亲子共读故事', '合作目标': '销售带货'})
        self.assertEqual(response['audiences'], [{'label': '购买者', 'text': '为孩子挑选情绪绘本的家长'},
                                                 {'label': '图书读者', 'text': '喜欢亲子共读的孩子'}])

    def test_missing_book_does_not_call_model(self):
        with patch.object(creator_match_audiences.llm, 'chat') as chat, self.assertRaises(ValueError):
            creator_match_audiences.suggest({'goal': 'content'})
        chat.assert_not_called()

    def test_does_not_expose_model_error_details(self):
        with patch.object(creator_match_audiences.llm, 'chat', side_effect=RuntimeError('内部模型细节')):
            with self.assertRaises(creator_match_audiences.AudienceSuggestionUnavailable) as error:
                creator_match_audiences.suggest({'title': '情绪绘本'})
        self.assertNotIn('内部模型细节', str(error.exception))


class CreatorWorkSearchTests(unittest.TestCase):
    def test_search_uses_only_direct_douyin_works_with_unambiguous_author(self):
        primary = creator_match.Creator(2, '001', '王老师讲书', (), '')
        other = creator_match.Creator(3, '002', '李老师讲书', (), '')
        base = 'https://www.douyin.com/video/'
        hits = [
            {'name': '谈书中的乡村关系 - 抖音', 'url': base + '7111111111111111111', 'snippet': '作者账号：001。'},
            {'name': '只有同名', 'url': base + '7222222222222222222', 'snippet': '作者：王老师讲书。'},
            {'name': '来源可疑', 'url': base.replace('douyin.com', 'example.org') + '7333333333333333333', 'snippet': '作品作者抖音号：001。'},
            {'name': '归属冲突', 'url': base + '7444444444444444444', 'snippet': '作者账号：001。作者账号：002'},
        ]
        records, links, attributed = creator_work_search._candidates(hits, [primary, other], {}, primary)
        self.assertEqual(attributed, links)
        self.assertEqual(links, {hits[0]['url']})
        self.assertEqual(records['001'][0]['title'], '谈书中的乡村关系')
        self.assertEqual(records['001'][0]['text'], '')

    def test_scored_indexed_works_are_reported_as_indexed_when_search_is_unconfigured(self):
        creator = creator_match.Creator(2, '001', '王老师讲书', (), '')
        works = {'001': [{'id': 'local', 'title': '乡村里的关系', 'text': '', 'url': '',
                          'published': '', 'provenance': '运营录入', 'handle': '001'}]}
        with patch.object(creator_work_search, '_search_backend', return_value=(None, '')), \
             patch.object(creator_match, '_snapshot', return_value=([creator], {})), \
             patch.object(creator_works, 'read_works', return_value=works), \
             patch.object(creator_match, 'match', return_value={'matches': [], 'content_notice': '', 'content_status': 'no_match'}):
            result = creator_work_search.lookup({'title': '乡土中国', 'synopsis': '讲乡村关系。', 'handle': '001'})
        self.assertEqual(result['search_state'], 'indexed')
        self.assertEqual(result['target_handle'], '001')
        self.assertEqual(result['matches'][0]['score_state'], 'weak')
        self.assertFalse(result['matches'][0]['recommend_backup'])

    def test_online_lookup_assesses_attributed_public_titles(self):
        creator = creator_match.Creator(2, '001', '王老师讲书', (), '')
        url = 'https://www.douyin.com/video/7111111111111111111'
        hits = [{'title': '村里买卖为什么讲熟人', 'url': url, 'author': {'unique_id': '001'}}]
        assessment = {'id': '1', 'relation': 'specific', 'book_point': '熟人之间的买卖关系',
                      'work_quote': '村里买卖为什么讲熟人', 'connection': '两边都讨论熟人关系如何影响乡村买卖。',
                      'angle': '由一次乡村买卖展开，再解释书里提到的熟人关系。'}
        with patch.object(creator_work_search, '_search_backend', return_value=(lambda query, key: hits, 'test')), \
             patch.object(creator_work_search, '_search_topic', return_value=('乡村', '熟人之间的买卖关系')), \
             patch.object(creator_match, '_snapshot', return_value=([creator], {})), \
             patch.object(creator_works, 'read_works', return_value={}), \
             patch.object(creator_content_match, '_assess', return_value=[assessment]):
            result = creator_work_search.lookup({'title': '乡土中国', 'synopsis': '这本书讲熟人之间的买卖关系。', 'handle': '001'})
        self.assertEqual(result['search_state'], 'found')
        self.assertEqual(result['matches'][0]['content_match']['works'][0]['url'], url)
        self.assertLess(result['matches'][0]['score'], 80)

    def test_search_queries_use_book_evidence_and_only_identifying_handle(self):
        output = json.dumps({'terms': ['巴格达', '不存在于原文的博主', '战后生活', '巴格达']}, ensure_ascii=False)
        with patch.object(creator_work_search.llm, 'chat', return_value={'text': output}) as chat:
            terms = creator_work_search._search_topic('走进伊拉克', '到巴格达探访战后生活。')
        self.assertEqual(terms, ('巴格达', '战后生活'))
        self.assertNotIn('Johnny', chat.call_args.args[0][1]['content'])
        searches = creator_work_search._queries(terms, 'Johnny_vloger')
        self.assertEqual(searches, ('巴格达 战后生活 抖音视频', 'Johnny_vloger 巴格达 战后生活 抖音视频'))


if __name__ == '__main__':
    unittest.main()
