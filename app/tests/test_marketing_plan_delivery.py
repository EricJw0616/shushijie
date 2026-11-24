"""New marketing plans export current actionable content; legacy documents stay intact."""
import copy
import json
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import project_intelligence as I
import projects as P
import test_marketing_tasks as fixtures


class MarketingPlanDeliveryTests(unittest.TestCase):
    setUp=fixtures.MarketingTaskTests.setUp
    tearDown=fixtures.MarketingTaskTests.tearDown
    project=fixtures.MarketingTaskTests.project
    adopt=fixtures.MarketingTaskTests.adopt
    response=fixtures.MarketingTaskTests.response

    def case(self,task):
        p=self.adopt(self.project(task))
        if task=='general':p['brief']['source_code']='A1'
        snapshot=I.build_input(p,'draft')
        data=self.response(task)
        data['outline'][0].update(title='内容准备',objective='让观众看到本书如何讨论信任',
            content='渠道：公众号。职责：内容编辑整理引用，营销编辑制作文章。交付：一篇有具体故事的文章。观察：记录读者集中追问的内容，据此选择后续主题。')
        data['writing_needs']=[]
        result=I._validate(data,snapshot,[m['asset_id'] for m in snapshot['materials']])
        return p,snapshot,data,result

    def test_new_nonchannel_plans_have_actionable_sections_without_process_appendices(self):
        for task in ('general','reposition','theme'):
            p,snapshot,data,result=self.case(task)
            self.assertEqual(snapshot['plan_delivery_version'],'1.0')
            text=I.render_markdown(result,snapshot)
            for title in ('## 目标与对象','## 核心主张','## 推进安排'):
                self.assertIn(title,text)
            for content in ('公众号','内容编辑','交付：','观察：','[S1]'):
                self.assertIn(content,text)
            for unwanted in ('材料怎样复用','下一步验证','AI辅助讨论稿','资产版本','## 需确认'):
                self.assertNotIn(unwanted,text)
            self.assertEqual('## 图书分工' in text,task=='theme')

    def test_only_actual_writing_need_appears_without_generic_gap_list(self):
        _,snapshot,data,result=self.case('theme')
        result.update(writing_needs=[{'kind':'materials','message':'需补充第二本书关于共同生活的具体片段。'}],
                      gaps=[{'issue':'一般性调研','next_action':'先开展市场调查'}])
        text=I.render_markdown(result,snapshot)
        self.assertIn('## 需确认',text)
        self.assertIn('需补充第二本书',text)
        self.assertNotIn('先开展市场调查',text)

    def test_new_book_plan_does_not_label_reference_books_as_promoted_book(self):
        p,snapshot,data,result=self.case('general')
        snapshot['brief']['new_book_brief']='新书讨论家庭共读，旧书仅为创意参考。'
        text=I.render_markdown(result,snapshot)
        self.assertIn('**参考图书：**',text)
        self.assertNotIn('**推广图书：**',text)

    def test_plan_projection_applies_only_to_new_drafts(self):
        p,snapshot,data,result=self.case('theme')
        legacy=copy.deepcopy(snapshot);legacy.pop('plan_delivery_version')
        self.assertIn('## 材料怎样复用',I.render_markdown(result,legacy))
        channel=I.build_input(self.adopt(self.project('channel')),'draft')
        recommend=I.build_input(p,'recommend')
        self.assertNotIn('plan_delivery_version',channel)
        self.assertNotIn('plan_delivery_version',recommend)

    def test_clean_export_preserves_current_manual_edits_and_does_not_change_legacy_export(self):
        p,snapshot,data,result=self.case('theme')
        p['draft']=I.render_markdown(result,snapshot)+'\n\n## 编辑补充\n\n由阅读推广编辑负责对接书店。'
        p['draft_generation']={'plan_delivery_version':'1.0','source_labels':{aid:'S%d'%(i+1) for i,aid in enumerate(result['asset_ids'])}}
        original=copy.deepcopy(p)
        clean=P._markdown(p,[],'approved')
        self.assertIn('由阅读推广编辑负责对接书店',clean)
        for unwanted in ('任务说明','材料与来源','待补与使用记录','[S1]','[S2]'):
            self.assertNotIn(unwanted,clean)
        self.assertEqual(p,original)
        p['draft_generation'].pop('plan_delivery_version')
        legacy=P._markdown(p,[],'review')
        self.assertIn('任务说明',legacy)
        self.assertIn('材料与来源',legacy)

    def test_plan_contract_and_exact_source_content_reach_independent_review(self):
        p,snapshot,data,result=self.case('theme');before=copy.deepcopy(p)
        def response(value):return {'text':json.dumps(value,ensure_ascii=False),'model':'test','usage':{}}
        with patch.object(I.llm,'chat',side_effect=[response(data),response({'accepted':True,'issues':[]})]) as chat:
            finished=I.execute(snapshot)
        self.assertIn(I.marketing_context.PLAN_INSTRUCTION,chat.call_args_list[0].args[0][0]['content'])
        reviewed=json.loads(chat.call_args_list[1].args[0][1]['content'])
        self.assertEqual(reviewed['candidate']['outline'],finished['outline'])
        self.assertTrue(reviewed['supplied_materials'])
        self.assertEqual(p,before)


if __name__=='__main__':unittest.main()
