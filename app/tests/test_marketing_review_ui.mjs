import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const read=name=>readFileSync(new URL('../static/'+name,import.meta.url),'utf8');
const app=read('app.js');
const parseCode=app.slice(app.indexOf('function parse(hash){'),app.indexOf('function workflowContext()'));
const postCode=app.slice(app.indexOf('async function mktPost('),app.indexOf('function mktRowsById('));
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const problem={code:'B69',legacy_id:'keywords:problem',asset_id:'B69:marketing:abc',title:'出版信息',
  reasons:[{code:'source_structure',message:'PDF 第 1 页 OCR 与版面顺序待核对'}],
  sources:[{anchor:'B69-00-P01',quote:'封面 & 版本文字',source_page:1,source_url:'#/book/B69/text/B69-00-P01',pdf_url:'/api/book/source?code=B69#page=1',reasons:[{code:'ocr_review'}]},
    {anchor:'B69-01-P01',quote:'正常正文',source_page:3,source_url:'#/book/B69/text/B69-01-P01',pdf_url:'/api/book/source?code=B69#page=3',reasons:[]}]};

const sourceSegment={anchor:'B69-00-P01',revision:'source-v1',text:'完整的识别段落 & 版面顺序',chapter:'前置',source_page:1,
  preview_url:'/api/book/source-page?code=B69&page=1',pdf_url:'/api/book/source?code=B69#page=1',can_verify:true,has_issue:true,issues:['识别文字待核对']};
const sourceContext={code:'B69',asset_id:problem.asset_id,legacy_id:problem.legacy_id,revision:'material-v1',title:'出版信息',text:'待核对的营销资料',status:'review',
  segments:[sourceSegment],pending_segments:[sourceSegment],pending_count:1,can_proceed:false,requires_regeneration:false};
const materialContext=()=>({...structuredClone(sourceContext),revision:'material-v2',pending_segments:[],pending_count:0,can_proceed:true,
  segments:[{...structuredClone(sourceSegment),has_issue:false,review:{id:'review-1'}}]});

function setup(storage=new Map()){
  const host={},flags={},calls={render:0,get:[],post:[],focus:[],toasts:[]};
  let problemNodes=[],rows=[];
  const element=(id,issue=false)=>({dataset:issue?{marketingIssue:id}:{id},scrollIntoView:()=>calls.focus.push(['scroll',id]),focus:()=>calls.focus.push(['focus',id])});
  const elements={marketingSourceChecked:{checked:false},marketingMaterialChecked:{checked:false},marketingSourceSave:{disabled:true},marketingMaterialSave:{disabled:true},marketingSourceText:{focus(){}}};
  const context={sourceContext:structuredClone(sourceContext),sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},esc:escape,clip:(s,n)=>String(s).slice(0,n),URLSearchParams,
    location:{hash:'#/marketing/B69'},state:{mktData:{code:'B69',groups:[{key:'keywords',rows:[{id:problem.legacy_id,serverStatus:'review'}]}]},mktCat:'review',bookCache:{}},
    document:{getElementById:id=>id==='mktBody'?host:id==='marketingReviewProblems'?element('panel'):elements[id]||null,querySelectorAll:selector=>selector==='[data-marketing-issue]'?problemNodes:selector==='.mkt-item'?rows:[]},
    mktRender:()=>calls.render++,mktFlags:()=>flags,mktRowState:row=>row.serverStatus==='approved'?'ok':'review',mktServerGroups:items=>[{key:'keywords',rows:items}],
    toast:(...args)=>calls.toasts.push(args),
    api:async url=>{calls.get.push(url);return url.startsWith('/api/marketing/source-review?')?context.sourceContext:{blocked_items:[structuredClone(problem)]};},
    jget:async url=>{calls.get.push(url);return {marketing_rows:[{id:problem.legacy_id,status:'review'}]};},
    post:async(url,body)=>{calls.post.push({url,body});return {ok:true};}
  };
  context.window=context;
  runInNewContext(parseCode+'\n'+read('marketing-review.js')+'\n'+postCode,context);
  return {context,calls,flags,elements,storage,ui:context.MarketingReview,
    nodes(ids,isIssues=true){const nodes=ids.map(id=>element(id,isIssues));if(isIssues)problemNodes=nodes;else rows=nodes;return nodes;}};
}

test('source blockers offer one guided entry and explain the two separate confirmation steps',()=>{
  const {ui}=setup();ui.blocked('B69',{blocked_items:[problem],error:'本次未确认任何资料'},'');
  const html=ui.panel('B69');
  assert.match(html,/本次未确认任何资料/);assert.match(html,/开始核对/);
  assert.match(html,/对照原版 → 保存原文核对 → 确认这条资料/);
  assert.match(ui.rowAction('B69',problem.legacy_id),/逐步核对/);
  assert.equal(ui.rowAction('B69','unrelated'),'');
});

test('missing PDF shows a truthful unavailable step and never offers a source save button',async()=>{
  const {context,ui}=setup();context.sourceContext.pending_segments[0].can_verify=false;
  context.sourceContext.pending_segments[0].preview_url='';context.sourceContext.pending_segments[0].pdf_url='';
  context.sourceContext.pending_segments[0].blocked_reason='原始 PDF 不可用，暂不能对照确认。';
  ui.blocked('B69',{blocked_items:[problem]},'');await ui.start();const html=ui.panel('B69');
  assert.match(html,/原始 PDF 不可用/);assert.match(html,/跳过，处理下一条/);
  assert.doesNotMatch(html,/id="marketingSourceSave"|href="\/api\/book\/source/);
});

test('source and report return links encode the exact material and only appear for marketing visits',()=>{
  const {context,ui}=setup();
  context.location.hash=ui.sourceUrl(problem,problem.sources[0]);
  assert.equal(context.parse().q,'B69-00-P01');
  assert.equal(context.parse().extra.get('t'),problem.sources[0].quote);
  const link=ui.returnLink('B69');assert.match(link,/href="#\/marketing\/B69\?issue=keywords%3Aproblem"/);
  context.location.hash=ui.reportUrl(problem);assert.equal(context.parse().arg,'B69');assert.equal(ui.returnLink('B69'),link);
  context.location.hash='#/book/B69/text/B69-00-P01?k=quote';assert.equal(ui.returnLink('B69'),'');
  context.location.hash='#/marketing/B69?issue=keywords%3Aproblem';assert.equal(context.parse().extra.get('issue'),problem.legacy_id);
});

test('failed batch confirmation renders structured blockers without optimistic flags or follow-up writes',async()=>{
  const {context,calls,ui,flags}=setup();
  context.post=async(url,body)=>{calls.post.push({url,body});const error=Error('来源待处理');error.details={blocked_items:[problem],error:'本次未确认任何资料'};throw error;};
  assert.equal(await context.mktPost('B69',[problem.legacy_id],'adopt'),false);
  assert.deepEqual(flags,{});assert.equal(calls.post.length,1);assert.equal(calls.get.length,0);
  assert.match(ui.panel('B69'),/本次未确认任何资料/);assert.equal(calls.render,1);
});

test('ordinary network errors also remain visible and do not masquerade as completed confirmation',async()=>{
  const {context,ui,flags}=setup();context.post=async()=>{throw Error('网络暂不可用');};
  assert.equal(await context.mktPost('B69',[problem.legacy_id],'adopt'),false);
  assert.deepEqual(flags,{});assert.match(ui.panel('B69'),/本次确认未完成/);assert.match(ui.panel('B69'),/网络暂不可用/);
});

test('return focuses the blocked material; after source resolution it focuses the original pending row',async()=>{
  const {context,ui,calls,nodes}=setup();context.location.hash='#/marketing/B69?issue=keywords%3Aproblem';
  ui.blocked('B69',{blocked_items:[problem]},'');nodes([problem.legacy_id]);ui.focusReturn();
  assert.deepEqual(calls.focus.at(-1),['focus',problem.legacy_id]);
  context.api=async()=>({blocked_items:[]});nodes([]);const material=nodes([problem.legacy_id],false)[0];
  await ui.refresh();assert.equal(ui.panel('B69'),'');assert.equal(material.tabIndex,-1);
  assert.deepEqual(calls.focus.at(-1),['focus',problem.legacy_id]);assert.equal(calls.post.length,0);
});

test('manual refresh reloads source material and removes fixed blockers without confirming it',async()=>{
  const {context,ui,calls,flags}=setup();ui.blocked('B69',{blocked_items:[problem]},'');
  const fresh={marketing_rows:[{id:problem.legacy_id,status:'review'}],marker:'new source'};
  context.api=async url=>{calls.get.push(url);return {blocked_items:[]};};context.jget=async url=>{calls.get.push(url);return fresh;};
  await ui.refresh(true);
  assert.equal(ui.panel('B69'),'');assert.equal(context.state.bookCache.B69,fresh);assert.equal(context.state.book,fresh);
  assert.equal(context.state.mktData.d,fresh);assert.equal(fresh.marketing_rows[0].status,'review');
  assert.deepEqual(flags,{});assert.equal(calls.post.length,0);assert.equal(calls.get.length,2);
});

test('an unavailable refresh retains known blocker details alongside its error',async()=>{
  const {context,ui}=setup();ui.blocked('B69',{blocked_items:[problem]},'');
  context.api=async()=>{throw Error('检查服务暂不可用');};await ui.refresh();
  assert.match(ui.panel('B69'),/来源检查暂未更新/);assert.match(ui.panel('B69'),/1 条资料需要核对来源/);
});

test('a delayed source check cannot replace the next book page or cache',async()=>{
  const {context,ui,calls}=setup();let finish;
  context.api=()=>new Promise(resolve=>finish=resolve);const pending=ui.refresh(true);
  context.location.hash='#/marketing/B58';context.state.mktData={code:'B58',groups:[]};
  finish({blocked_items:[problem]});await pending;
  assert.equal(calls.render,0);assert.equal(context.state.bookCache.B69,undefined);assert.equal(ui.panel('B58'),'');
});

test('a delayed failed confirmation cannot put the previous book blockers on the current book',async()=>{
  const {context,ui,calls}=setup();let fail;
  context.post=()=>new Promise((_,reject)=>fail=reject);const pending=context.mktPost('B69',[problem.legacy_id],'adopt');
  context.location.hash='#/marketing/B58';context.state.mktData={code:'B58',groups:[]};
  const error=Error('来源待处理');error.details={blocked_items:[problem]};fail(error);
  assert.equal(await pending,false);assert.equal(calls.render,0);assert.equal(ui.panel('B58'),'');
});

test('the source and material steps require separate consent and separate writes',async()=>{
  const {context,ui,calls}=setup();ui.blocked('B69',{blocked_items:[problem]},'');await ui.start();
  let html=ui.panel('B69');assert.match(html,/完整的识别段落 &amp; 版面顺序/);
  assert.match(html,/src="\/api\/book\/source-page\?code=B69&amp;page=1"/);
  assert.match(html,/id="marketingSourceSave"[^>]+disabled/);
  await ui.saveSource();assert.equal(calls.post.length,0);
  context.post=async(url,body)=>{calls.post.push({url,body});context.sourceContext=materialContext();return {changed:false};};
  ui.check(true);await ui.saveSource();
  assert.equal(calls.post.length,1);assert.equal(calls.post[0].url,'/api/marketing/source-review/verify');
  assert.equal(calls.post[0].body.anchor,sourceSegment.anchor);assert.equal(calls.post[0].body.confirmed,true);
  assert.equal(calls.post[0].body.revision,sourceSegment.revision);assert.equal(calls.post[0].body.text,undefined);
  html=ui.panel('B69');assert.match(html,/第 2 步/);assert.match(html,/id="marketingMaterialSave"[^>]+disabled/);
  await ui.review('approved');assert.equal(calls.post.length,1);
  ui.check(true);await ui.review('approved');assert.equal(calls.post.length,2);
  assert.equal(calls.post[1].url,'/api/content-assets/review');assert.equal(calls.post[1].body.status,'approved');
  assert.equal(calls.post[1].body.revision,'material-v2');assert.match(ui.panel('B69'),/已确认可用/);
});

test('a shared verified paragraph goes straight to independent material review',async()=>{
  const {context,ui,calls}=setup();context.sourceContext=materialContext();
  ui.blocked('B69',{blocked_items:[problem]},'');await ui.start();
  assert.match(ui.panel('B69'),/同一段原文无需重复处理/);
  assert.doesNotMatch(ui.panel('B69'),/id="marketingSourceSave"/);assert.equal(calls.post.length,0);
  await ui.review('approved');assert.equal(calls.post.length,0);
});

test('closing and refreshing preserves an edited draft but never restores consent',async()=>{
  const first=setup();first.ui.blocked('B69',{blocked_items:[problem]},'');await first.ui.start();
  first.ui.edit(true);first.ui.editText('按原版修正后的完整文字');first.ui.check(true);first.ui.close();
  assert.match(first.ui.panel('B69'),/继续核对/);assert.equal(first.calls.post.length,0);
  const second=setup(first.storage);await second.ui.start();
  const html=second.ui.panel('B69');assert.match(html,/按原版修正后的完整文字/);
  assert.match(html,/id="marketingSourceSave"[^>]+disabled/);
  assert.doesNotMatch(html,/id="marketingSourceChecked"[^>]+ checked/);
  await second.ui.saveSource();assert.equal(second.calls.post.length,0);
});

test('editing after consent clears consent and saving corrected text requires regeneration',async()=>{
  const {context,ui,calls,elements}=setup();ui.blocked('B69',{blocked_items:[problem]},'');await ui.start();
  ui.edit(true);ui.check(true);elements.marketingSourceChecked.checked=true;ui.editText('修正后的完整识别段落');
  assert.equal(elements.marketingSourceChecked.checked,false);assert.equal(elements.marketingSourceSave.disabled,true);
  context.post=async(url,body)=>{calls.post.push({url,body});context.sourceContext={...materialContext(),can_proceed:false,requires_regeneration:true};return {changed:true};};
  ui.check(true);await ui.saveSource();assert.equal(calls.post[0].body.text,'修正后的完整识别段落');
  assert.match(ui.panel('B69'),/原文修正已保存/);assert.match(ui.panel('B69'),/重新生成营销资料/);
  assert.doesNotMatch(ui.panel('B69'),/id="marketingMaterialSave"/);
  ui.check(true);await ui.review('approved');assert.equal(calls.post.length,1);
});

test('skipping and closing never writes a review and next item starts with unchecked consent',async()=>{
  const {ui,calls}=setup();ui.blocked('B69',{blocked_items:[problem,{...problem,asset_id:'second',legacy_id:'second'}]},'');await ui.start();
  ui.check(true);ui.skip();assert.match(ui.panel('B69'),/已跳过，仍保留待确认/);
  await ui.next();assert.match(ui.panel('B69'),/资料 2 \/ 2/);
  assert.match(ui.panel('B69'),/id="marketingSourceSave"[^>]+disabled/);ui.close();assert.equal(calls.post.length,0);
});

test('a failed source save remains on the same step and requires fresh consent to retry',async()=>{
  const {context,ui,calls}=setup();ui.blocked('B69',{blocked_items:[problem]},'');await ui.start();
  context.post=async(url,body)=>{calls.post.push({url,body});throw Error('原文版本已变化，请重新载入');};
  ui.check(true);await ui.saveSource();assert.match(ui.panel('B69'),/原文版本已变化/);
  assert.match(ui.panel('B69'),/第 1 步/);assert.match(ui.panel('B69'),/id="marketingSourceSave"[^>]+disabled/);
  await ui.saveSource();assert.equal(calls.post.length,1);
});

test('returning with a material query restarts from its checkpoint and accepts a fresh save',async()=>{
  const {context,ui,calls}=setup();ui.blocked('B69',{blocked_items:[problem]},'');await ui.start();
  ui.check(true);context.location.hash=ui.sourceUrl(problem,problem.sources[0]);
  context.location.hash='#/marketing/B69?issue='+encodeURIComponent(problem.legacy_id);
  assert.match(ui.panel('B69'),/继续核对/);await ui.start();
  assert.match(ui.panel('B69'),/id="marketingSourceSave"[^>]+disabled/);
  context.post=async(url,body)=>{calls.post.push({url,body});context.sourceContext=materialContext();return {changed:false};};
  ui.check(true);await ui.saveSource();assert.equal(calls.post.length,1);assert.match(ui.panel('B69'),/第 2 步/);
});

test('a disappeared queued material offers skip and exit instead of a dead loading step',async()=>{
  const {context,ui,calls}=setup();ui.blocked('B69',{blocked_items:[problem]},'');
  context.api=async()=>{throw Error('营销资料已更新，请重新选择');};await ui.start();
  const html=ui.panel('B69');assert.match(html,/营销资料已更新/);assert.match(html,/跳过这条，继续下一条/);assert.match(html,/返回资料列表/);
  ui.skip();await ui.next();assert.match(ui.panel('B69'),/本轮核对结束/);assert.equal(calls.post.length,0);
});

test('a delayed guide load cannot render the previous book on a different book page',async()=>{
  const {context,ui,calls}=setup();ui.blocked('B69',{blocked_items:[problem]},'');let finish;
  context.api=()=>new Promise(resolve=>finish=resolve);const pending=ui.start();
  context.location.hash='#/marketing/B58';context.state.mktData={code:'B58',groups:[]};
  assert.equal(ui.panel('B58'),'');const renders=calls.render;finish(sourceContext);await pending;
  assert.equal(calls.render,renders);assert.equal(ui.panel('B58'),'');assert.equal(calls.post.length,0);
});

test('a rejected item restored after refresh shows its saved outcome without repeating review',async()=>{
  const first=setup();first.ui.blocked('B69',{blocked_items:[problem]},'');await first.ui.start();first.ui.close();
  const second=setup(first.storage);second.context.sourceContext.status='rejected';await second.ui.start();
  const html=second.ui.panel('B69');assert.match(html,/已标记为不采用/);assert.match(html,/查看本轮结果/);
  assert.doesNotMatch(html,/id="marketingSourceSave"|id="marketingMaterialSave"/);assert.equal(second.calls.post.length,0);
});

test('regenerated marketing material returns directly to its book review page',()=>{
  const context={esc:escape,arr:value=>Array.isArray(value)?value:[]};
  for(const name of ['stepIcon','renderJob']){
    const start=app.indexOf(`function ${name}(`);
    runInNewContext(app.slice(start,app.indexOf('\n}\n',start)+2),context);
  }
  for(const status of ['running','done','failed']){
    const view={};context.renderJob(view,{id:'marketing-test',kind:'marketing',book_code:'B69',status});
    assert.match(view.innerHTML,/data-code="B69" onclick="go\('marketing',this.dataset.code\)"/);
    assert.match(view.innerHTML,/返回营销资料/);
    if(status==='done'){
      assert.match(view.innerHTML,/营销资料已更新。下一步返回资料页，核对并确认新的内容/);
      assert.match(view.innerHTML,/返回营销资料继续核对/);
    }
  }
  const ordinary={};context.renderJob(ordinary,{kind:'upload',book_code:'B69',status:'done'});
  assert.match(ordinary.innerHTML,/查看图书档案/);assert.doesNotMatch(ordinary.innerHTML,/返回营销资料/);
});
