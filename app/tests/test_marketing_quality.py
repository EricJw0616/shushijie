"""Bounded independent review of role- and source-aware marketing generation."""
import copy
import json
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_intelligence as I
import test_marketing_tasks as fixtures


def response(value):
    return {'text': json.dumps(value, ensure_ascii=False), 'model': 'test', 'usage': {}}


class MarketingQualityTests(unittest.TestCase):
    setUp = fixtures.MarketingTaskTests.setUp
    tearDown = fixtures.MarketingTaskTests.tearDown
    project = fixtures.MarketingTaskTests.project
    adopt = fixtures.MarketingTaskTests.adopt
    response = fixtures.MarketingTaskTests.response

    def snapshot(self):
        p = self.adopt(self.project('channel'))
        p['brief'].update(purpose='inform', audience='首次读文学的中学生',
                          book_readers='', decision_maker='')
        return p, I.build_input(p, 'draft')

    def test_independent_review_receives_roles_sources_and_candidate_without_changing_project(self):
        p, snapshot = self.snapshot(); before = copy.deepcopy(p)
        with patch.object(I.llm, 'chat', side_effect=[response(self.response('channel')),
                  response({'accepted': True, 'issues': []})]) as chat:
            result = I.execute(snapshot)
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(chat.call_args_list[1].kwargs['max_tokens'],1800)
        reviewer = json.loads(chat.call_args_list[1].args[0][1]['content'])
        self.assertEqual(reviewer['task_context']['marketing_context']['roles']['viewer'], '首次读文学的中学生')
        self.assertEqual(reviewer['task_context']['marketing_context']['roles']['decision_maker'], '')
        self.assertTrue(reviewer['supplied_materials']); self.assertTrue(reviewer['candidate'])
        self.assertEqual(result['quality_review']['repair_attempts'], 0)
        self.assertEqual(result['status'], 'needs_review'); self.assertEqual(p, before)

    def test_blocker_gets_one_targeted_repair_then_independent_recheck(self):
        p, snapshot = self.snapshot()
        blocker = {'accepted': False, 'issues': [{'code':'purpose_drift','severity':'blocker',
                    'location':'短视频结尾','message':'知识传播不应催促购买，删除促销语。',
                    'candidate_quote':'翻开原书，找找植物生长在哪里。','source_basis':'本次purpose为inform，应围绕知识理解。'}]}
        with patch.object(I.llm, 'chat', side_effect=[response(self.response('channel')), response(blocker),
                response(self.response('channel')), response({'accepted': True, 'issues': []})]) as chat:
            result = I.execute(snapshot)
        self.assertEqual(chat.call_count, 4)
        repair = json.loads(chat.call_args_list[2].args[0][-1]['content'])
        self.assertEqual(repair['repair_issues'], blocker['issues'])
        self.assertIn('允许针对所列问题改写', repair['requirements'])
        self.assertNotIn('不可改写、删除或重新排列已确认口播', repair['requirements'])
        self.assertEqual(result['quality_review']['repair_attempts'], 1)

    def test_content_gap_repair_can_replace_repetition_with_supplied_explanation(self):
        p,snapshot=self.snapshot();before=copy.deepcopy(p)
        draft=self.response('channel')
        repeated='值得再读一次，才能找到信任的秘密。'
        draft['channel_assets'][1]['video_production']['shots'][1]['voiceover']=repeated
        draft['channel_assets'][1]['video_production']['shots'][2]['voiceover']=repeated
        fixed=copy.deepcopy(draft)
        fixed['channel_assets'][1]['video_production']['shots'][1]['voiceover']='书中用共同经历和长期陪伴，呈现信任逐步建立的过程。'
        fixed['channel_assets'][1]['video_production']['shots'][2]['voiceover']='另一条材料从具体生活规则和交往来讨论信任。'
        blocker={'accepted':False,'issues':[{'code':'content_gap','severity':'blocker',
                 'location':'口播第2、3段','message':'两段重复悬念，补入已提供的具体内容并删除重复。',
                 'candidate_quote':repeated,'source_basis':snapshot['materials'][0]['asset_id']+'：'+snapshot['materials'][0]['text']}]}
        with patch.object(I.llm,'chat',side_effect=[response(draft),response(blocker),
                response(fixed),response({'accepted':True,'issues':[]})]) as chat:
            result=I.execute(snapshot)
        repair=json.loads(chat.call_args_list[2].args[0][-1]['content'])
        self.assertIn('允许针对所列问题改写',repair['requirements'])
        self.assertIn('本次已提供材料支持的解释',repair['requirements'])
        returned=result['channel_assets'][1]['video_production']
        self.assertEqual(returned['shots'][1]['voiceover'],fixed['channel_assets'][1]['video_production']['shots'][1]['voiceover'])
        self.assertNotIn(repeated,result['channel_assets'][1]['body'])
        self.assertEqual(p,before)

    def test_review_length_counts_only_delivered_text_and_includes_cta(self):
        p,snapshot=self.snapshot();draft=self.response('channel')
        draft['channel_assets'][0].update(title='这是不计入正文的标题',body='正文 123。\n下一段！',cta='结尾？')
        with patch.object(I.llm,'chat',side_effect=[response(draft),response({'accepted':True,'issues':[]})]) as chat:
            I.execute(snapshot)
        candidate=json.loads(chat.call_args_list[1].args[0][1]['content'])['candidate']
        self.assertEqual(candidate[0]['body_and_cta_characters'],10)
        self.assertEqual(candidate[1]['narration_characters'],sum(c.isalnum() for s in
                         draft['channel_assets'][1]['video_production']['shots'] for c in s['voiceover']))
        self.assertNotIn('body_and_cta_characters',candidate[1])

    def test_visual_review_retry_receives_exact_noisy_source_without_silently_rewriting_quote(self):
        import test_video_prompts_quality as visuals
        p,current=self.snapshot()
        current.update(visuals.snapshot('image'),capability='video_prompts')
        data=visuals.response('image');ids=[m['asset_id'] for m in current['materials']]
        data['asset_ids']=ids
        for shot in data['shots']:shot['asset_ids']=ids
        result=I.video_prompts.validate(data,current,ids)
        payload=json.loads(I._user_payload(current))
        raw='研究者从土层中发现图4 现场记录第20页多个化石，并逐一记录。'
        payload['materials'][0]['source_context']=[{'anchor':'raw-1','quote':raw}]
        row={'candidate_location':'第1镜.scene_prompt','candidate_quote':data['shots'][0]['prompt'],
             'source_asset_id':ids[0],'source_field':'source_context',
             'source_quote':'研究者从土层中发现多个化石','conclusion':'supported'}
        invalid={'accepted':True,'issues':[],'source_checks':[row]}
        fixed={'accepted':True,'issues':[],'source_checks':[{**row,'source_quote':raw}]}
        before=copy.deepcopy(payload)
        with patch.object(I.llm,'chat',side_effect=[response(invalid),response(fixed)]) as chat:
            review,provenance=I._semantic_review(current,payload,result)
        self.assertEqual(chat.call_count,2)
        correction=json.loads(chat.call_args_list[1].args[0][-1]['content'])
        retry=correction['invalid_source_checks'][0]
        self.assertEqual(retry['previous_check']['source_quote'],row['source_quote'])
        self.assertEqual(retry['provided_source_field'],[payload['materials'][0]['source_context']])
        self.assertIn('source_quote_not_found',retry['validation_issues'])
        self.assertEqual(review['source_checks'][0]['source_quote'],raw)
        self.assertEqual(len(provenance['validation_attempts']),2)
        self.assertEqual(payload,before)
        # If the model repeats its cleaned, non-contiguous quote, it still fails.
        with patch.object(I.llm,'chat',return_value=response(invalid)) as chat, \
                self.assertRaisesRegex(ValueError,'本次内容检查未完成') as raised:
            I._semantic_review(current,payload,result)
        self.assertEqual(chat.call_count,2)
        self.assertIn('source_quote_not_found',raised.exception.diagnostics['attempts'][-1]['validation_error'])

    def test_visual_review_retry_gets_exact_candidate_field_not_confirmed_narration(self):
        import test_video_prompts_quality as visuals
        p,current=self.snapshot()
        current.update(visuals.snapshot('image'),capability='video_prompts')
        data=visuals.response('image');ids=[m['asset_id'] for m in current['materials']]
        data['asset_ids']=ids
        for shot in data['shots']:shot['asset_ids']=ids
        result=I.video_prompts.validate(data,current,ids)
        exact='从共同经历和长期陪伴看信任的建立'
        borrowed='共同的经历和长久的陪伴，让信任逐渐产生。'
        result['video_prompts']['shots'][0]['focus']=exact
        current['confirmed_outline'][0]['source_text']=borrowed
        payload=json.loads(I._user_payload(current))
        row={'candidate_location':'第1镜.focus','candidate_quote':borrowed,
             'source_asset_id':ids[0],'source_field':'text','source_quote':payload['materials'][0]['text'],
             'conclusion':'supported'}
        invalid={'accepted':True,'issues':[],'source_checks':[row]}
        valid={'accepted':True,'issues':[],'source_checks':[{**row,'candidate_quote':exact}]}
        before=copy.deepcopy(result)
        with patch.object(I.llm,'chat',side_effect=[response(invalid),response(valid)]) as chat:
            review,_=I._semantic_review(current,payload,result)
        correction=json.loads(chat.call_args_list[1].args[0][-1]['content'])['invalid_source_checks'][0]
        self.assertEqual(correction['provided_candidate_field'],exact)
        self.assertEqual(correction['previous_check']['candidate_quote'],borrowed)
        self.assertEqual(correction['validation_issues'],['candidate_quote_not_found'])
        self.assertEqual(review['source_checks'][0]['candidate_quote'],exact)
        self.assertEqual(result,before)
        with patch.object(I.llm,'chat',return_value=response(invalid)) as chat, \
                self.assertRaisesRegex(ValueError,'本次内容检查未完成'):
            I._semantic_review(current,payload,result)
        self.assertEqual(chat.call_count,2)

    def test_preference_warnings_do_not_trigger_repair_or_reject_valid_copy(self):
        p,snapshot = self.snapshot()
        warning={'accepted':False,'issues':[{'code':'wording','severity':'warning',
                    'location':'口播第2段','message':'可以换一种更简洁的说法，但原句有来源支持。'}]}
        with patch.object(I.llm,'chat',side_effect=[response(self.response('channel')),response(warning)]) as chat:
            result=I.execute(snapshot)
        self.assertEqual(chat.call_count,2)
        self.assertTrue(result['quality_review']['accepted'])
        self.assertEqual(result['quality_review']['repair_attempts'],0)
        candidate=json.loads(chat.call_args_list[1].args[0][1]['content'])['candidate'][1]
        self.assertIn('voiceover_paragraphs',candidate)
        self.assertNotIn('video_production',candidate)
        self.assertNotIn('body',candidate)

    def test_reviewer_cannot_invent_a_candidate_sentence_to_force_rewrite(self):
        p,snapshot=self.snapshot();before=copy.deepcopy(p)
        invalid={'accepted':False,'issues':[{'code':'ungrounded','severity':'blocker','location':'第1段',
                  'message':'该句不在原稿中。','candidate_quote':'这是审稿者自己编造而候选根本没有的句子。',
                  'source_basis':'声称依据材料，但未对应实际候选。'}]}
        with patch.object(I.llm,'chat',side_effect=[response(self.response('channel')),response(invalid),response(invalid)]) as chat, self.assertRaisesRegex(ValueError,'本次内容检查未完成') as raised:
            I.execute(snapshot)
        self.assertEqual(chat.call_count,3)
        self.assertIn('不在候选稿',str(raised.exception.__cause__))
        diagnostic=raised.exception.diagnostics
        self.assertEqual(diagnostic['stage'],'semantic_review_validation')
        self.assertEqual(len(diagnostic['attempts']),2)
        self.assertEqual(json.loads(diagnostic['attempts'][0]['response_text']),invalid)
        self.assertEqual(diagnostic['review_input']['candidate'],
                         json.loads(chat.call_args_list[1].args[0][1]['content'])['candidate'])
        self.assertNotIn('messages',diagnostic)
        self.assertEqual(p,before)

    def test_warning_empty_optional_evidence_does_not_fail_or_trigger_regeneration(self):
        p,snapshot=self.snapshot()
        for empty in ('',None,'  '):
            warning={'accepted':True,'issues':[{'code':'wording','severity':'warning',
                     'location':'公众号正文','message':'结尾可再简洁一些。',
                     'candidate_quote':empty,'source_basis':empty}]}
            with self.subTest(empty=empty),patch.object(I.llm,'chat',side_effect=[
                    response(self.response('channel')),response(warning)]) as chat:
                result=I.execute(snapshot)
            self.assertEqual(chat.call_count,2)
            self.assertTrue(result['quality_review']['accepted'])
            self.assertEqual(result['quality_review']['repair_attempts'],0)
            self.assertNotIn('candidate_quote',result['quality_review']['issues'][0])

    def test_malformed_review_gets_one_review_retry_without_regenerating_candidate(self):
        p,snapshot=self.snapshot();original=copy.deepcopy(p)
        for invalid in (response({'accepted':False,'issues':[{'code':'ungrounded','severity':'blocker',
                          'location':'正文','message':'缺少依据。','candidate_quote':'','source_basis':''}]}),
                        {'text':'{invalid JSON','model':'test','usage':{}}):
            with self.subTest(invalid=invalid),patch.object(I.llm,'chat',side_effect=[
                    response(self.response('channel')),invalid,response({'accepted':True,'issues':[]})]) as chat:
                result=I.execute(snapshot)
            self.assertEqual(chat.call_count,3)
            self.assertEqual(chat.call_args_list[1].args[0][:2],chat.call_args_list[2].args[0][:2])
            correction=json.loads(chat.call_args_list[2].args[0][-1]['content'])
            self.assertIn('review_validation_error',correction)
            self.assertNotIn('repair_issues',correction)
            self.assertEqual(result['quality_review']['repair_attempts'],0)
            attempts=result['provenance']['semantic_reviews'][0]['validation_attempts']
            self.assertEqual(len(attempts),2)
            self.assertIn('validation_error',attempts[0])
            self.assertNotIn('validation_error',attempts[1])
            self.assertEqual(p,original)

    def test_repaired_review_blocker_still_requires_content_repair_and_recheck(self):
        p,snapshot=self.snapshot()
        blocker={'accepted':False,'issues':[{'code':'purpose_drift','severity':'blocker',
                 'location':'结尾','message':'按本次用途调整结尾。',
                 'candidate_quote':'翻开原书，找找植物生长在哪里。','source_basis':'明确任务要求。'}]}
        malformed=copy.deepcopy(blocker);malformed['issues'][0].pop('candidate_quote')
        with patch.object(I.llm,'chat',side_effect=[response(self.response('channel')),response(malformed),
                response(blocker),response(self.response('channel')),response({'accepted':True,'issues':[]})]) as chat:
            result=I.execute(snapshot)
        self.assertEqual(chat.call_count,5)
        repair=json.loads(chat.call_args_list[3].args[0][-1]['content'])
        self.assertEqual(repair['repair_issues'],blocker['issues'])
        self.assertEqual(result['quality_review']['repair_attempts'],1)

    def test_review_transport_failure_is_not_retried_as_bad_content(self):
        p,snapshot=self.snapshot()
        with patch.object(I.llm,'chat',side_effect=[response(self.response('channel')),
                RuntimeError('模型调用失败')]) as chat,self.assertRaisesRegex(RuntimeError,'模型调用失败'):
            I.execute(snapshot)
        self.assertEqual(chat.call_count,2)

    def test_repeated_blocker_fails_instead_of_approving_or_retrying_forever(self):
        p, snapshot = self.snapshot()
        blocker = {'accepted':False,'issues':[{'code':'ungrounded','severity':'blocker',
                   'location':'口播第1段','message':'删除来源未提供的数字。',
                   'candidate_quote':'先观察根和叶。','source_basis':'测试审查依据，来源仅含关系与信任。'}]}
        with patch.object(I.llm,'chat', side_effect=[response(self.response('channel')),response(blocker),
                response(self.response('channel')),response(blocker)]) as chat, self.assertRaisesRegex(ValueError,'一次定向修复'):
            I.execute(snapshot)
        self.assertEqual(chat.call_count,4)

    def test_structural_failure_cannot_be_marked_success(self):
        p, snapshot = self.snapshot()
        with patch.object(I.llm,'chat', side_effect=[response({}),response({})]) as chat, self.assertRaisesRegex(ValueError,'一次定向修复'):
            I.execute(snapshot)
        self.assertEqual(chat.call_count,2)

    def test_legacy_snapshot_remains_single_call_without_new_quality_contract(self):
        p, snapshot = self.snapshot(); snapshot.pop('quality_policy_version')
        with patch.object(I.llm,'chat', return_value=response(self.response('channel'))) as chat:
            result = I.execute(snapshot)
        self.assertEqual(chat.call_count,1); self.assertNotIn('quality_review',result)

    def test_visual_generation_independently_reviews_but_never_changes_confirmed_narration(self):
        import test_video_prompts_quality as visuals
        p, current = self.snapshot()
        current.update(visuals.snapshot('image'), capability='video_prompts')
        confirmed = current['materials'][0]['asset_id'] + '应当原样保留在确认正文中。'
        current['confirmed_outline'][0]['source_text'] = confirmed
        expected = '\n\n'.join(row['source_text'] for row in current['confirmed_outline'])
        original = copy.deepcopy(current)
        data = visuals.response('image')
        ids = [m['asset_id'] for m in current['materials']]
        data['asset_ids'] = ids
        for shot in data['shots']: shot['asset_ids'] = ids
        source_check = {'candidate_location':'第1镜.scene_prompt','candidate_quote':data['shots'][0]['prompt'],
                        'source_asset_id':ids[0],'source_field':'text',
                        'source_quote':current['materials'][0]['text'],'conclusion':'supported'}
        with patch.object(I.llm, 'chat', side_effect=[response(data),
                response({'accepted':True,'issues':[],'source_checks':[source_check]})]) as chat:
            result = I.execute(current)
        self.assertEqual(chat.call_count,2)
        self.assertEqual(chat.call_args_list[1].kwargs['max_tokens'],3000)
        self.assertEqual(current,original)
        self.assertEqual(result['video_prompts']['confirmed_narration'],expected)
        review_input = json.loads(chat.call_args_list[1].args[0][1]['content'])
        self.assertEqual(review_input['confirmed_narration'],current['confirmed_outline'])
        self.assertEqual(review_input['stage'],'external_production_plan')
        self.assertEqual(review_input['candidate']['stage'],'external_production_plan')
        self.assertNotIn('confirmed_narration',review_input['candidate'])
        self.assertIn('scene_prompt',review_input['candidate']['shots'][0])
        self.assertNotIn('prompt',review_input['candidate']['shots'][0])
        self.assertEqual(result['status'],'needs_review')
        self.assertEqual(result['cited_asset_ids'],[])
        self.assertEqual(result['quality_review']['repair_attempts'],0)

    def test_visual_review_requires_source_checks_and_uses_provided_materials(self):
        import test_video_prompts_quality as visuals
        p,current=self.snapshot()
        current.update(visuals.snapshot('image'),capability='video_prompts')
        data=visuals.response('image');ids=[m['asset_id'] for m in current['materials']]
        data['asset_ids']=ids
        for shot in data['shots']:shot['asset_ids']=ids
        result=I.video_prompts.validate(data,current,ids)
        payload=json.loads(I._user_payload(current))
        for review in ({'accepted':True,'issues':[]},
                       {'accepted':True,'issues':[],'source_checks':'invalid'},
                       {'accepted':True,'issues':[],'source_checks':[]}):
            with self.subTest(review=review),patch.object(I.llm,'chat',return_value=response(review)), \
                    patch.object(I.video_prompts,'validate_review',wraps=I.video_prompts.validate_review) as check, \
                    self.assertRaises(ValueError):
                I._semantic_review(current,payload,result)
            self.assertEqual(check.call_args.kwargs['materials'],payload['materials'])
            self.assertIs(check.call_args.kwargs['require_source_checks'],True)

    def test_incomplete_visual_check_fails_without_content_repair_but_keeps_valid_blocker(self):
        import test_video_prompts_quality as visuals
        p,current=self.snapshot()
        current.update(visuals.snapshot('image'),capability='video_prompts')
        data=visuals.response('image');ids=[m['asset_id'] for m in current['materials']]
        data['asset_ids']=ids
        for shot in data['shots']:shot['asset_ids']=ids
        result=I.video_prompts.validate(data,current,ids)
        payload=json.loads(I._user_payload(current))
        valid={'candidate_location':'第1镜.scene_prompt','candidate_quote':data['shots'][0]['prompt'],
               'source_asset_id':ids[0],'source_field':'text','source_quote':payload['materials'][0]['text'],
               'conclusion':'contradicted'}
        invalid={**valid,'source_asset_id':'not-provided','conclusion':'supported'}
        incomplete={'accepted':True,'issues':[],'source_checks':[invalid]}
        with patch.object(I.llm,'chat',side_effect=[response(data),response(incomplete),response(incomplete)]) as chat, \
                self.assertRaisesRegex(ValueError,'本次内容检查未完成') as raised:
            I.execute(current)
        self.assertEqual(chat.call_count,3)  # generation + two reviews; no content repair
        self.assertIn('自动核对未获得有效依据',str(raised.exception.__cause__))
        correction=json.loads(chat.call_args_list[2].args[0][-1]['content'])
        self.assertIn('source_asset_not_provided',correction['review_validation_error'])
        self.assertIn('"row": 1',correction['review_validation_error'])
        self.assertEqual(len(raised.exception.diagnostics['attempts']),2)
        self.assertEqual(raised.exception.diagnostics['review_input']['supplied_materials'],payload['materials'])
        mixed={'accepted':True,'issues':[],'source_checks':[valid,invalid]}
        with patch.object(I.llm,'chat',return_value=response(mixed)):
            review,_=I._semantic_review(current,payload,result)
        self.assertFalse(review['accepted'])
        self.assertEqual(review['source_check_status'],'incomplete')
        self.assertTrue(any(issue['severity']=='blocker' for issue in review['issues']))
        self.assertEqual(review['source_checks'][1]['conclusion'],'unverified')
        resolved={'accepted':True,'issues':[],'source_checks':[{**valid,'conclusion':'supported'}]}
        with patch.object(I.llm,'chat',side_effect=[response(data),response(mixed),
                response(data),response(resolved)]) as chat:
            finished=I.execute(current)
        self.assertEqual(chat.call_count,4)
        self.assertIn('不可改写、删除或重新排列已确认口播',
                      json.loads(chat.call_args_list[2].args[0][-1]['content'])['requirements'])
        self.assertEqual(finished['quality_review']['repair_attempts'],1)
        self.assertEqual(finished['status'],'needs_review')

    def capacity_case(self, characters=121, duration=30):
        p = self.adopt(self.project('channel'))
        p['brief']['writing_notes'] = '约30秒，竖屏，完整解释一个问题。'
        snapshot = I.build_input(p, 'draft')
        data = self.response('channel')
        production = data['channel_assets'][1]['video_production']
        production['duration_seconds'] = duration
        for i, shot in enumerate(production['shots']):
            shot.update(start_seconds=i * duration // 6, end_seconds=(i + 1) * duration // 6,
                        voiceover='知' * (characters - 5) if i == 0 else '识')
        return p, snapshot, data

    def test_over_budget_narration_is_repaired_once_before_semantic_review(self):
        p, snapshot, data = self.capacity_case()
        before = copy.deepcopy(p)
        fixed = copy.deepcopy(data); fixed['channel_assets'][1]['video_production']['shots'][0]['voiceover'] = '知' * 115
        with patch.object(I.llm, 'chat', side_effect=[response(data),response(fixed),
                response({'accepted':True,'issues':[]})]) as chat:
            result = I.execute(snapshot)
        self.assertEqual(chat.call_count,3)
        repair = json.loads(chat.call_args_list[1].args[0][-1]['content'])
        self.assertIn('121',repair['repair_issues'][0]['message'])
        self.assertIn('120',repair['repair_issues'][0]['message'])
        self.assertIn('不是实测语速',repair['repair_issues'][0]['message'])
        self.assertIn('约96字',repair['repair_issues'][0]['message'])
        self.assertIn('删除完整',repair['repair_issues'][0]['message'])
        self.assertIn('约96个',chat.call_args_list[0].args[0][0]['content'])
        self.assertEqual(result['quality_review']['repair_attempts'],1)
        self.assertEqual(p,before)

    def test_model_cannot_extend_duration_or_repeatedly_exceed_capacity(self):
        for characters,duration,expected in [(121,30,'121'),(160,60,'固定为30秒')]:
            p,snapshot,data = self.capacity_case(characters,duration)
            with self.subTest(characters=characters,duration=duration), patch.object(I.llm,'chat',
                    side_effect=[response(data),response(data)]) as chat, self.assertRaisesRegex(ValueError,expected):
                I.execute(snapshot)
            self.assertEqual(chat.call_count,2)

    def test_pre_capacity_snapshot_keeps_historical_narration_contract(self):
        p,snapshot,data = self.capacity_case(160,30)
        snapshot['quality_policy_version'] = '1.0'; snapshot.pop('narration_capacity')
        with patch.object(I.llm,'chat',side_effect=[response(data),response({'accepted':True,'issues':[]})]):
            result=I.execute(snapshot)
        production=result['channel_assets'][1]['video_production']
        self.assertEqual(sum(c.isalnum() for shot in production['shots'] for c in shot['voiceover']),160)

    def test_context_windows_retain_anchored_quote_and_topic_fact_near_end(self):
        m = I.build_input(self.adopt(self.project('channel')), 'draft')['materials'][0]
        anchor = 'book-99'; exact = '识字不识字并非愚不愚的标准。'
        m['text'] = '其他内容。' * 300 + '核心观点：' + exact
        m['evidence'] = [{'anchor': anchor, 'quote': exact}]
        m['source_context'] = [{'anchor': anchor, 'quote': '历史背景。' * 300 + exact + '学习机会与熟悉程度值得区分。'}]
        out = I._prompt_material(m, 200, 180, I._topic_terms('不识字能说明一个人不聪明吗'), True)
        self.assertIn(exact, out['text']); self.assertIn(exact,out['source_context'][0]['quote'])
        self.assertEqual(out['source_context'][0]['anchor'],anchor)

if __name__ == '__main__': unittest.main()
