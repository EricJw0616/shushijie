"""Channel delivery contracts; model quality still requires real editorial review."""
import copy
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel_delivery as D
import marketing_delivery
import project_intelligence as I
import test_marketing_tasks as fixtures


def note(ids):
    return {'note_body':'关系中的信任，可以从书中共同经历的故事读起。', 'ending':'你会怎样理解陪伴？',
            'visual_style':'米白底与深蓝纸艺符号，留白充足', 'aspect_ratio':'3:4',
            'cards':[{'role':role,'title':title,'purpose':purpose,'subject':'两个纸艺人物符号',
                      'composition':'人物分列左右，中间以连线关联，下方留文字区',
                      'scene_prompt':'人物与连线呈现联系；用不同线条区分关系，不表示统计数据',
                      'overlay_text':title,'reference_type':'none','reference_requirement':'','asset_ids':[aid]}
                     for role,title,purpose,aid in [('cover','关系需要时间','引出关系中的信任',ids[0]),
                                                   ('content','共同经历','呈现书中讨论的关系',ids[1])]]}


def talk(ids, seconds=180):
    return {'duration_seconds':seconds, 'sections':[
        {'heading':'从故事进入','script':'我们来看书中共同经历与长期陪伴的故事，再讨论信任如何形成。',
         'cue':'说完提问停顿','page_hint':'翻到共同经历的章节','asset_ids':[ids[0]]},
        {'heading':'把问题留给听众','script':'另一条材料从具体生活规则与交往来理解信任。你更关心哪一种关系？',
         'cue':'','page_hint':'','asset_ids':[ids[1]]}]}


class ChannelDeliveryTests(unittest.TestCase):
    setUp=fixtures.MarketingTaskTests.setUp
    tearDown=fixtures.MarketingTaskTests.tearDown
    project=fixtures.MarketingTaskTests.project
    adopt=fixtures.MarketingTaskTests.adopt
    response=fixtures.MarketingTaskTests.response

    def case(self, channel, notes=''):
        p=self.adopt(self.project('channel'))
        p['brief'].update(channels=[channel],audience='为青少年选书的家长',book_readers='青少年',
                          purpose='purchase',decision_maker='家长',writing_notes=notes)
        snapshot=I.build_input(p,'draft')
        ids=[m['asset_id'] for m in snapshot['materials']]
        data=self.response('channel')
        data['channel_assets']=[{'channel':channel,'title':'关系需要时间','body':'','cta':'','asset_ids':[ids[0]],
                                 'delivery':note(ids) if channel=='小红书' else talk(ids,snapshot['booktalk_capacity']['duration_seconds'])}]
        return p,snapshot,data,ids

    def test_social_note_creates_standalone_prompts_and_separate_editable_sections(self):
        p,snapshot,data,ids=self.case('小红书');before=copy.deepcopy(data)
        result=I._validate(data,snapshot,ids);scene=result['channel_assets'][0]
        self.assertEqual(scene['asset_ids'],ids)
        self.assertTrue(set(ids)<=set(result['asset_ids']))
        self.assertEqual(scene['cta'],'')
        pack=scene['channel_delivery']
        self.assertEqual(pack['decision_maker'],'家长')
        for card in pack['cards']:
            self.assertIn('最终观众：为青少年选书的家长',card['prompt'])
            self.assertIn('本书阅读者：青少年',card['prompt'])
            for value in (card['purpose'],card['subject'],card['composition'],pack['visual_style'],pack['aspect_ratio']):
                self.assertIn(value,card['prompt'])
            self.assertIn('画面不渲染文字',card['prompt'])
            self.assertIn('概念示意',card['prompt'])
            self.assertNotIn('上传',card['prompt'])
        markdown=I.render_markdown(result,snapshot)
        publishing,production=markdown.split('#### 配图制作',1)
        self.assertIn('#### 发布正文',publishing)
        self.assertNotIn('生图提示词',publishing)
        self.assertEqual(production.count('**生图提示词**'),2)
        self.assertIn('##### 第 1 张 · 封面 ·',production)
        self.assertNotIn('参考图：',production)
        self.assertEqual(data,before)

    def test_repeated_closing_is_removed_before_review_and_rendering(self):
        _, snapshot, data, ids = self.case('小红书')
        delivery = data['channel_assets'][0]['delivery']
        for ending, tags in [('请翻开原书读这一段。', '#读书 #原文'), ('你会怎么读这段？', '#共读')]:
            delivery.update(note_body='从具体情节展开。' + ending + '\n\n' + tags, ending=ending)
            result = I._validate(data, snapshot, ids)
            pack = result['channel_assets'][0]['channel_delivery']
            self.assertEqual(pack['ending'], '')
            self.assertEqual(I.render_markdown(result, snapshot).count(ending), 1)
            self.assertEqual(D.render(dict(pack, ending=ending)).count(ending), 1)
            self.assertEqual(D.social_note_ending('开头。' + ending + ' ' + tags, ending), '')
        delivery.update(note_body='另一份开头。' + ending + '\n\n还有一个不同的结尾。\n' + tags)
        result = I._validate(data, snapshot, ids)
        self.assertEqual(result['channel_assets'][0]['channel_delivery']['ending'], ending)

    def test_length_blocker_can_be_edited_and_rechecked_against_same_sources(self):
        _, snapshot, data, ids = self.case('小红书', '正文不超过200字')
        delivery = data['channel_assets'][0]['delivery']
        blocker = {'accepted': False, 'issues': [{'code': 'length_mismatch', 'severity': 'blocker',
            'location': '正文', 'message': '请缩短正文', 'candidate_quote': delivery['note_body'],
            'source_basis': '写作要求不超过200字'}]}
        response = lambda value: {'text': json.dumps(value, ensure_ascii=False)}
        with patch.object(I.llm, 'chat', side_effect=map(response, [data, blocker, data, blocker])), \
                self.assertRaises(I.RecoverableDraftError) as caught:
            I.execute(snapshot)
        failure = caught.exception
        edit = dict(failure.fields[0], body='从共同经历读起。')
        edited = I.edit_recovery_candidate(failure.candidate, [edit])
        self.assertEqual(edited['channel_assets'][0]['asset_ids'], data['channel_assets'][0]['asset_ids'])
        self.assertEqual(edited['channel_assets'][0]['delivery']['cards'], delivery['cards'])
        self.assertEqual(failure.candidate, data)
        with self.assertRaisesRegex(ValueError, '保留原有渠道'):
            I.edit_recovery_candidate(failure.candidate, [dict(edit, channel='公众号')])
        with patch.object(I.llm, 'chat', return_value=response({'accepted': True, 'issues': []})) as semantic:
            result = I.execute(snapshot, edited_candidate=edited)
        self.assertEqual(semantic.call_count, 1)
        self.assertTrue(result['provenance']['editor_revision'])
        self.assertIn(edit['body'], I.render_markdown(result, snapshot))
        fact = {'accepted': False, 'issues': [dict(blocker['issues'][0], code='ungrounded',
                message='无法找到事实出处', candidate_quote=edit['body'], source_basis=ids[0])]}
        with patch.object(I.llm, 'chat', return_value=response(fact)), self.assertRaises(ValueError) as blocked:
            I.execute(snapshot, edited_candidate=edited)
        self.assertNotIsInstance(blocked.exception, I.RecoverableDraftError)
        self.assertIn('无法找到事实出处', str(blocked.exception))

    def test_real_cover_reference_is_specific_to_its_card(self):
        _,snapshot,data,ids=self.case('小红书')
        cover=data['channel_assets'][0]['delivery']['cards'][0]
        cover.update(reference_type='book_cover',reference_requirement='本次图书真实封面图片')
        pack=I._validate(data,snapshot,ids)['channel_assets'][0]['channel_delivery']
        self.assertIn('上传对应参考图：本次图书真实封面图片',pack['cards'][0]['prompt'])
        self.assertIn('不重新生成或伪造',pack['cards'][0]['prompt'])
        self.assertNotIn('上传',pack['cards'][1]['prompt'])

    def test_wrong_ids_missing_cards_and_false_reference_requirements_fail(self):
        for mutate in (lambda x:x['cards'][1].update(asset_ids=['not-provided']),
                       lambda x:x.update(cards=x['cards'][:1]),
                       lambda x:x['cards'][1].update(role='cover'),
                       lambda x:x['cards'][0].update(reference_requirement='先找一张背景纸')):
            _,snapshot,data,ids=self.case('小红书');mutate(data['channel_assets'][0]['delivery'])
            with self.assertRaises(ValueError):I._validate(data,snapshot,ids)

    def test_booktalk_separates_operator_audience_script_and_only_needed_cues(self):
        _,snapshot,data,ids=self.case('达人讲书','讲书时长5分钟')
        self.assertEqual(snapshot['booktalk_capacity']['duration_seconds'],300)
        pack=I._validate(data,snapshot,ids)['channel_assets'][0]['channel_delivery']
        self.assertEqual(pack['operator'],'讲书者')
        self.assertEqual(pack['audience'],'为青少年选书的家长')
        self.assertEqual(pack['book_readers'],'青少年')
        body,cues=D.render(pack).split('#### 提词与翻页',1)
        self.assertIn('#### 讲述正文',body)
        self.assertNotIn('说完提问停顿',body)
        self.assertIn('说完提问停顿',cues)
        self.assertNotIn('第 2 段',cues)
        self.assertIn('5 分钟',cues)
        self.assertEqual(D.render(pack).count(pack['sections'][0]['script']),1)

    def test_booktalk_duration_budget_and_page_numbers_are_not_invented(self):
        for field,value in [('duration_seconds',600),('page_hint','翻到第10页'),('script','字'*721)]:
            _,snapshot,data,ids=self.case('达人讲书','讲书时长3分钟')
            pack=data['channel_assets'][0]['delivery']
            if field=='duration_seconds':pack[field]=value
            else:pack['sections'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):I._validate(data,snapshot,ids)
        self.assertEqual(D.booktalk_capacity({'writing_notes':'讲书时长20分钟'})['duration_seconds'],1200)
        with self.assertRaises(ValueError):D.booktalk_capacity({'writing_notes':'讲书时长40分钟'})

    def test_legacy_channel_snapshots_keep_existing_body_and_cta(self):
        for channel in D.CHANNELS:
            _,snapshot,data,ids=self.case(channel);snapshot.pop('channel_delivery_version')
            scene=data['channel_assets'][0];scene.pop('delivery')
            scene.update(body='旧版已有完整正文',cta='旧版结尾',asset_ids=ids)
            result=I._validate(data,snapshot,ids)
            self.assertEqual(result['channel_assets'][0]['body'],'旧版已有完整正文')
            self.assertEqual(result['channel_assets'][0]['cta'],'旧版结尾')
            self.assertNotIn('channel_delivery',result['channel_assets'][0])

    def test_other_channels_do_not_acquire_new_delivery_requirements(self):
        p=self.adopt(self.project('channel'));snapshot=I.build_input(p,'draft')
        self.assertNotIn('channel_delivery_version',snapshot)
        result=I._validate(self.response('channel'),snapshot,[m['asset_id'] for m in snapshot['materials']])
        self.assertEqual([c['channel'] for c in result['channel_assets']],['公众号','短视频'])

    def test_export_uses_current_edited_manuscript_and_keeps_both_delivery_sections(self):
        for channel in D.CHANNELS:
            _,snapshot,data,ids=self.case(channel)
            result=I._validate(data,snapshot,ids)
            source=I.render_markdown(result,snapshot)
            if channel=='小红书':
                source=source.replace('画面要求：','画面要求：编辑增加柔和侧光，',1)
                expected=('#### 发布正文','#### 配图制作','编辑增加柔和侧光')
            else:
                source=source.replace('说完提问停顿','编辑确认：提问后停顿两秒')
                expected=('#### 讲述正文','#### 提词与翻页','提问后停顿两秒')
            out=marketing_delivery.channel_document(source,[channel],{aid:'S%d'%(i+1) for i,aid in enumerate(result['asset_ids'])})['text']
            for text in expected:self.assertIn(text,out)
            for text in ('渠道素材初稿','材料怎样复用','来源索引','[S1]'):self.assertNotIn(text,out)
            self.assertTrue(out.startswith('# 关系需要时间'))

    def test_independent_review_sees_production_content_without_counting_it_as_published_copy(self):
        for channel in D.CHANNELS:
            p,snapshot,data,ids=self.case(channel);before=copy.deepcopy(p)
            def response(value):return {'text':json.dumps(value,ensure_ascii=False),'model':'test','usage':{}}
            with patch.object(I.llm,'chat',side_effect=[response(data),response({'accepted':True,'issues':[]})]) as chat:
                result=I.execute(snapshot)
            candidate=json.loads(chat.call_args_list[1].args[0][1]['content'])['candidate'][0]
            self.assertIn('channel_delivery',candidate)
            if channel=='小红书':
                self.assertNotIn('生图提示词',candidate['body'])
                self.assertIn('prompt',candidate['channel_delivery']['cards'][0])
            else:
                self.assertEqual(candidate['duration_seconds'],240)
                self.assertNotIn('提词', ''.join(candidate['voiceover_paragraphs']))
            self.assertEqual(result['quality_review']['repair_attempts'],0)
            self.assertEqual(p,before)


if __name__=='__main__':unittest.main()
