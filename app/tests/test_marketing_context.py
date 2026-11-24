import copy
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import marketing_context as M
import projects as P
import project_intelligence as I


class MarketingContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [patch.object(M,'OUT',self.tmp.name), patch.object(P,'DIR',os.path.join(self.tmp.name,'projects'))]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def write_profile(self, code, audience='研究人员'):
        os.makedirs(os.path.join(self.tmp.name,code),exist_ok=True)
        value = {'generated_at':'2026-11-21','items':{
            'audience':{'status':'needs_review','note':'待编辑判断','value':[
                {'text':audience,'basis':'推断','reason':'根据内容估计','evidence':[{'seg':'p1','quote':'书中原文'}]}]},
            'summary':{'status':'rejected','value':{'text':'已拒绝内容'}}}}
        with open(os.path.join(self.tmp.name,code,'marketing.json'),'w') as f: json.dump(value,f)

    def test_old_brief_stays_unchanged_and_no_buyer_is_inferred_from_age(self):
        brief={'audience':'11–14岁','goal':'一分钟知识讲解'}
        self.assertEqual(M.normalize(brief),{})
        context, revisions=M.build(brief, {'target_books':[]})
        self.assertEqual(context['roles'],{'viewer':'11–14岁','book_readers':'','decision_maker':''})
        self.assertEqual(context['purpose'],''); self.assertEqual(revisions,{})
        stored=P.create_project({'kind':'marketing','title':'旧项目','brief':brief})
        self.assertNotIn('purpose',stored['brief']);self.assertEqual(stored['brief']['audience'],'11–14岁')

    def test_roles_survive_save_and_change_fingerprint_without_changing_draft(self):
        p=P.create_project({'kind':'marketing','title':'共读','brief':{'audience':'家长','purpose':'purchase',
                    'book_readers':'家长和孩子','decision_maker':'家长'}})
        p=P.update_project(p['id'],{'action':'save','revision':p['revision'],'draft':'已确认正文'})['project']
        original=I.fingerprint(p)
        updated=P.update_project(p['id'],{'action':'save','revision':p['revision'],
                    'brief':{**p['brief'],'purpose':'inform','audience':'中学生'}})['project']
        self.assertNotEqual(I.fingerprint(updated),original)
        self.assertEqual(updated['draft'],'已确认正文')
        self.assertEqual(updated['brief']['decision_maker'],'家长')
        context,_=M.build(updated['brief'],{'target_books':[]})
        self.assertEqual(context['roles']['decision_maker'],'')
        self.assertEqual(context['roles']['book_readers'],'家长和孩子')
        self.assertEqual(P.get_project(p['id'])['brief'],updated['brief'])

    def test_purchase_buyer_can_remain_unknown_and_invalid_enum_is_rejected(self):
        value=M.normalize({'purpose':'purchase','book_readers':'成年读者','decision_maker':''})
        self.assertEqual(value['decision_maker'],'')
        for bad in ('sales',None,123):
            with self.subTest(bad=bad),self.assertRaises(ValueError):M.normalize({'purpose':bad})
        with self.assertRaises(ValueError):M.normalize({'book_readers':['儿童']})

    def test_only_selected_profiles_are_attributed_hypotheses_and_versions_stale(self):
        self.write_profile('A1');self.write_profile('B2','另一图书读者')
        context,revisions=M.build({'audience':'中学生','purpose':'inform'},{'target_books':[{'code':'A1','book':'自然书'}]})
        self.assertEqual([b['code'] for b in context['books']],['A1'])
        profile=context['books'][0]; field=profile['fields'][0]
        self.assertEqual(field['field'],'audience');self.assertEqual(field['status'],'needs_review')
        self.assertEqual(field['values'][0]['basis'],'推断')
        self.assertEqual(field['values'][0]['evidence'][0]['anchor'],'p1')
        self.assertEqual(context['roles']['viewer'],'中学生')
        snapshot={'marketing_context':copy.deepcopy(context),'book_profile_revisions':revisions}
        self.assertEqual(M.stale_reason(snapshot),'')
        self.write_profile('A1','编辑修订后的读者推断')
        self.assertIn('已更新',M.stale_reason(snapshot))
        self.assertEqual(snapshot['marketing_context']['books'][0]['fields'][0]['values'][0]['text'],'研究人员')
        self.assertEqual(M.stale_reason({}),'')

    def test_narration_capacity_fixes_requested_duration_before_model_generation(self):
        for notes, seconds in [('约30秒，竖屏',30),('一分钟科普',60),('半分钟',30),
                                ('1.5分钟',90),('一分半',90),('1分30秒',90),
                                ('全片60秒，开场5秒',60),('三十秒',30),('30 seconds',30)]:
            with self.subTest(notes=notes):
                budget=M.narration_capacity({'writing_notes':notes})
                self.assertEqual(budget['duration_seconds'],seconds)
                self.assertEqual(budget['limit'],seconds*4)
                self.assertEqual(budget['target_characters'],int(seconds*4*.8))
                self.assertEqual(budget['duration_source'],'brief.writing_notes')
        self.assertEqual(M.narration_capacity({'goal':'1分钟科普知识'})['duration_seconds'],60)
        self.assertEqual(M.narration_capacity({})['duration_source'],'default')
        with self.assertRaisesRegex(ValueError,'总计划时长'):
            M.narration_capacity({'writing_notes':'30秒或者60秒'})

    def test_many_book_profiles_are_budgeted_only_in_model_view(self):
        self.write_profile('A1')
        context,_=M.build({'audience':'中学生','topic':'自然观察'},{'target_books':[{'code':'A1','book':'自然书'}]})
        base=context['books'][0]
        base['fields'][0]['values'] *= 20
        context['books']=[{**copy.deepcopy(base),'code':'B%d'%i} for i in range(12)]
        original=copy.deepcopy(context)
        small=M.prompt_context(context,budget=7000)
        self.assertLessEqual(len(json.dumps(small['books'],ensure_ascii=False,separators=(',',':'))),7000)
        self.assertEqual(len(small['books']),12)
        self.assertTrue(all(book['fields'] and book['context_excerpted'] for book in small['books']))
        self.assertTrue(all(book['fields'][0]['status']=='needs_review' for book in small['books']))
        self.assertEqual(context,original)

    def test_missing_profiles_do_not_invent_information_but_later_creation_is_stale(self):
        context,revisions=M.build({'audience':'普通读者'},{'target_books':[{'code':'C3','book':'新入库'}]})
        self.assertEqual(context['books'][0]['fields'],[])
        self.assertEqual(revisions,{'C3':'missing'})
        self.write_profile('C3')
        self.assertTrue(M.stale_reason({'book_profile_revisions':revisions}))

if __name__=='__main__':unittest.main()
