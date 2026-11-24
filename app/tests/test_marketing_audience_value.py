"""Shared audience-value policy reaches every path without new reader-state claims.

Mocked responses test wiring, scope and repair behavior; they do not prove that a
model will produce moving or persuasive copy. Real output needs editorial review.
"""
import copy
import json
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import marketing_context as M
import project_intelligence as I
import test_marketing_tasks as fixtures


def response(value):
    return {'text':json.dumps(value,ensure_ascii=False),'model':'test','usage':{}}


class AudienceValueTests(unittest.TestCase):
    setUp=fixtures.MarketingTaskTests.setUp
    tearDown=fixtures.MarketingTaskTests.tearDown
    project=fixtures.MarketingTaskTests.project
    adopt=fixtures.MarketingTaskTests.adopt
    draft=fixtures.MarketingTaskTests.response

    def test_standard_is_not_an_inferred_emotional_profile_or_a_required_user_field(self):
        brief={'audience':'青少年','topic':'观察书中世界','goal':'理解一个方法'}
        before=copy.deepcopy(brief)
        context,_=M.build(brief,{'target_books':[]})
        self.assertEqual(brief,before)
        self.assertEqual(context['roles'],{'viewer':'青少年','book_readers':'','decision_maker':''})
        self.assertEqual(context['audience_value_standard']['version'],M.AUDIENCE_VALUE_VERSION)
        self.assertNotIn('emotional_state',context)
        self.assertNotIn('reader_response',context)
        self.assertEqual(M.prompt_context(context)['audience_value_standard'],context['audience_value_standard'])
        context['audience_value_standard']['criteria'].append('当前项目临时修改')
        another,_=M.build(brief,{'target_books':[]})
        self.assertNotIn('当前项目临时修改',another['audience_value_standard']['criteria'])

    def assert_wired(self,snapshot,data):
        with patch.object(I.llm,'chat',side_effect=[response(data),response({'accepted':True,'issues':[]})]) as chat:
            result=I.execute(snapshot)
        self.assertIn(M.AUDIENCE_VALUE_INSTRUCTION,chat.call_args_list[0].args[0][0]['content'])
        self.assertIn(M.audience_value_review_instruction(),chat.call_args_list[1].args[0][0]['content'])
        review=json.loads(chat.call_args_list[1].args[0][1]['content'])
        self.assertEqual(review['task_context']['marketing_context']['audience_value_standard']['version'],M.AUDIENCE_VALUE_VERSION)
        self.assertTrue(review['supplied_materials'])
        self.assertNotIn('情绪价值分析',I.render_markdown(result,snapshot))

    def test_generation_and_independent_review_share_standard_across_all_text_channels_and_plans(self):
        from test_channel_delivery import note,talk
        for task in ('general','reposition','theme'):
            with self.subTest(task=task):
                p=self.adopt(self.project(task))
                if task=='general':p['brief']['source_code']='A1'
                snapshot=I.build_input(p,'draft')
                self.assert_wired(snapshot,self.draft(task))
        for channel in ('公众号','短视频','小红书','达人讲书','书店活动'):
            with self.subTest(channel=channel):
                p=self.adopt(self.project('channel'));p['brief']['channels']=[channel]
                snapshot=I.build_input(p,'draft');ids=[m['asset_id'] for m in snapshot['materials']]
                data=self.draft('channel')
                if channel in ('公众号','短视频'):
                    scene=next(row for row in data['channel_assets'] if row['channel']==channel)
                    scene['asset_ids']=ids
                else:
                    scene={'channel':channel,'title':'读懂关系中的信任','asset_ids':ids,'body':'','cta':''}
                    if channel=='小红书':scene['delivery']=note(ids)
                    elif channel=='达人讲书':scene['delivery']=talk(ids,snapshot['booktalk_capacity']['duration_seconds'])
                    else:scene.update(body='一起读书中的共同经历，讨论关系如何逐渐建立。',cta='可以选择一段与你关注的问题有关的内容交流。')
                data['channel_assets']=[scene]
                self.assert_wired(snapshot,data)

    def test_material_selection_uses_the_same_standard_without_adding_reader_reaction_facts(self):
        p=self.adopt(self.project('theme'));snapshot=I.build_input(p,'recommend')
        aid=snapshot['materials'][0]['asset_id']
        data={'suggestions':[{'asset_id':aid,'reason':'书中共同经历回应关系如何建立的问题。','proposed_use':'用具体片段引入阅读讨论。'}],'gaps':[]}
        with patch.object(I.llm,'chat',return_value=response(data)) as chat:
            result=I.execute(snapshot)
        self.assertEqual(chat.call_count,1)
        self.assertIn(M.AUDIENCE_VALUE_INSTRUCTION,chat.call_args.args[0][0]['content'])
        self.assertNotIn('reader_response',result)

    def test_both_visual_modes_receive_policy_in_initial_generation_and_review_without_changing_confirmed_narration(self):
        import test_video_prompts_quality as visuals
        for mode in ('image','video'):
            with self.subTest(mode=mode):
                p=self.adopt(self.project('channel'));snapshot=I.build_input(p,'draft')
                snapshot.update(visuals.snapshot(mode),capability='video_prompts')
                before=copy.deepcopy(snapshot)
                data=visuals.response(mode);ids=[m['asset_id'] for m in snapshot['materials']]
                data['asset_ids']=ids
                for shot in data['shots']:shot['asset_ids']=ids
                def respond(messages,**kwargs):
                    if '独立的制作方案核对编辑' not in messages[0]['content']:
                        return response(data)
                    given=json.loads(messages[1]['content'])
                    check={'candidate_location':'第1镜.scene_prompt','candidate_quote':given['candidate']['shots'][0]['scene_prompt'],
                           'source_asset_id':given['supplied_materials'][0]['asset_id'],'source_field':'text',
                           'source_quote':given['supplied_materials'][0]['text'],'conclusion':'supported'}
                    return response({'accepted':True,'issues':[],'source_checks':[check]})
                with patch.object(I.llm,'chat',side_effect=respond) as chat:
                    result=I.execute(snapshot)
                self.assertEqual(chat.call_count,2)
                self.assertIn(M.AUDIENCE_VALUE_INSTRUCTION,chat.call_args_list[0].args[0][0]['content'])
                self.assertIn(M.audience_value_review_instruction(visual=True),chat.call_args_list[1].args[0][0]['content'])
                self.assertEqual(result['video_prompts']['confirmed_narration'],
                                 '\n\n'.join(row['source_text'] for row in snapshot['confirmed_outline']))
                self.assertEqual(snapshot,before)

    def test_evidenced_value_gap_repairs_content_but_never_writes_an_audience_analysis_appendix(self):
        p=self.adopt(self.project('channel'));p['brief']['channels']=['公众号']
        snapshot=I.build_input(p,'draft');before=copy.deepcopy(p)
        data=self.draft('channel');data['channel_assets']=data['channel_assets'][:1]
        data['channel_assets'][0].update(body='这本书特别治愈，任何人读完都会被打动。',asset_ids=[m['asset_id'] for m in snapshot['materials']])
        fixed=copy.deepcopy(data)
        fixed['channel_assets'][0]['body']='想知道一段关系如何建立，可以从书中共同经历与长期陪伴的故事读起。这里值得留意的是，两个人怎样在相处中逐渐形成信任。'
        issue={'code':'audience_value_gap','severity':'blocker','location':'公众号正文',
               'candidate_quote':data['channel_assets'][0]['body'],
               'source_basis':snapshot['materials'][0]['asset_id']+'：'+snapshot['materials'][0]['text'],
               'message':'删除无依据的群体效果保证，采用已有具体片段解释本次阅读问题。'}
        with patch.object(I.llm,'chat',side_effect=[response(data),response({'accepted':False,'issues':[issue]}),
                response(fixed),response({'accepted':True,'issues':[]})]) as chat:
            result=I.execute(snapshot)
        self.assertEqual(chat.call_count,4)
        repair=json.loads(chat.call_args_list[2].args[0][-1]['content'])
        self.assertEqual(repair['repair_issues'],[issue])
        self.assertIn('共同经历与长期陪伴',result['channel_assets'][0]['body'])
        self.assertNotIn('情绪价值分析',I.render_markdown(result,snapshot))
        self.assertEqual(p,before)


if __name__=='__main__':unittest.main()
