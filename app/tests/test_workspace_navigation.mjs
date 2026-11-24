import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';
const source=readFileSync(new URL('../static/workspace.js',import.meta.url),'utf8');
const between=(from,to)=>source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
const code=[between('  async function render(', '  async function dashboard('),between('  function rememberNavigation(', '  function localDraftKey('),between('  function peekAssistContext(', '  async function assistContext('),between('  async function beforeNavigate(', '  function upload('),between('  async function marketingNext(', '  function rememberNavigation('),between('  function openProjectSection(', '  function projectSection(')].join('\n');
function setup(kind='marketing'){
  const p={id:'prj-0000000000000000',kind,revision:6,title:'当前项目',brief:{topic:'原主题',audience:'普通观众',goal:'了解知识'},draft:'已保存口播',draft_asset_ids:['old']};
  const form={fields:{title:'未保存项目名',topic:'新主题',audience:'十一岁观众',goal:'了解知识'}},draft={value:'未保存口播\n第二行'},storage=new Map(),calls={save:0,cache:0,load:0,sections:[],go:[],back:[]};
  const S={project:p,dirty:true,section:'results',view:'campaigns',request:0,draftAssetIds:['current']};
  const ProjectUI={materials:{[p.id]:{mode:'selected',q:'叶片',filter:'adopted',offset:12}},draftMode:'edit',draftScene:'短视频',outlineOpen:true,assistOpen:false};
  const v={innerHTML:'existing DOM',classList:{add(){}},querySelector:()=>true};
  const context={S,ProjectUI,sessionStorage:{setItem:(key,value)=>storage.set(key,value),getItem:key=>storage.get(key)||null},document:{getElementById:id=>id==='projectBrief'?form:id==='projectDraft'?draft:id.startsWith('project-panel-')?{}:null},projectFormFields:x=>({...x.fields}),cacheLocalDraft:()=>{calls.cache++;},saveCurrent:async()=>{calls.save++;S.dirty=false;},initialProjectSection:(_p,section)=>section||S.section,showProjectSection:section=>{S.section=section;calls.sections.push(section);},loading:()=>'<loading>',projects:async()=>{calls.load++;},report:error=>{throw error;},empty:()=>'',btn:()=>'',go:(...args)=>calls.go.push(args),navBack:()=>calls.back.push('native'),location:{hash:'#/campaigns/'+p.id+'/results'},marketingBackTo:step=>calls.back.push(step)};
  context.window=context;runInNewContext(code+'\nthis.api={render,beforeNavigate,peekAssistContext,rememberNavigation,restoreNavigation,marketingNext,returnToSourceOrigin,marketingStepBack,openProjectSection};',context);
  return{context,S,ProjectUI,form,draft,v,storage,calls,api:context.api};
}
test('ordinary marketing back caches an incomplete form without saving or blocking navigation',async()=>{
  const app=setup();app.form.fields.title='';await app.api.beforeNavigate();
  assert.equal(app.calls.save,0);assert.equal(app.calls.cache,1);assert.equal(app.S.dirty,true);assert.equal(app.draft.value,'未保存口播\n第二行');
  app.api.marketingStepBack();assert.deepEqual(app.calls.back,['materials']); // The fallback is only a hint; AppHistory owns the real visit.
});
test('project page switches and same-page history restoration preserve mounted unsaved fields',async()=>{
  const app=setup();await app.api.render(app.v,'campaigns',app.S.project.id,'sources',{preserve:true});
  assert.equal(app.calls.save,0);assert.equal(app.calls.load,0);assert.equal(app.v.innerHTML,'existing DOM');assert.equal(app.S.section,'sources');
  await app.api.render(app.v,'campaigns',app.S.project.id,'sources',{preserve:true});assert.equal(app.calls.load,0);
  assert.equal(app.form.fields.title,'未保存项目名');assert.equal(app.draft.value,'未保存口播\n第二行');
  await app.api.render(app.v,'campaigns',app.S.project.id,'sources');assert.equal(app.calls.load,1,'an explicit Reload still reads the latest project');
});
test('current confirmation snapshot includes local narration and requirements without mutation or requests',()=>{
  const app=setup(),original=JSON.stringify(app.S.project),snapshot=app.api.peekAssistContext();
  assert.equal(snapshot.draft,'未保存口播\n第二行');assert.equal(snapshot.brief.audience,'十一岁观众');assert.equal(snapshot.title,'未保存项目名');assert.deepEqual([...snapshot.draft_asset_ids],['current']);
  assert.equal(JSON.stringify(app.S.project),original);assert.equal(app.calls.save,0);assert.equal(app.calls.load,0);
  snapshot.brief.audience='不应写回';snapshot.draft_asset_ids.push('foreign');assert.equal(app.S.project.brief.audience,'普通观众');assert.deepEqual(app.S.draftAssetIds,['current']);
});
test('view mode, selected scene and material filters restore per project after remount',()=>{
  const app=setup();app.api.rememberNavigation();app.ProjectUI.draftMode='read';app.ProjectUI.draftScene='公众号';app.ProjectUI.materials={};app.api.restoreNavigation(app.S.project);
  assert.equal(app.ProjectUI.draftMode,'edit');assert.equal(app.ProjectUI.draftScene,'短视频');assert.equal(app.ProjectUI.materials[app.S.project.id].offset,12);assert.equal(app.ProjectUI.materials[app.S.project.id].q,'叶片');
  app.ProjectUI.draftMode='read';app.api.restoreNavigation({...app.S.project,id:'another'});assert.equal(app.ProjectUI.draftMode,'read');
});
test('editorial section changes use navigation instead of replacing the current history entry',()=>{
  const app=setup('editorial');app.api.openProjectSection('history');assert.deepEqual(app.calls.go,[['projects',app.S.project.id,'history']]);assert.equal(app.calls.sections.length,0);
});

test('leaving a workspace invalidates an in-flight project load before it can replace active project state',async()=>{
  const app=setup();let finish;const pending=new Promise(resolve=>{finish=resolve;});
  app.context.request=()=>pending;app.context.crumb=()=>{};
  runInNewContext(between('  async function projects(', '  function explicitDraftScope('),app.context);
  const original=app.S.project,load=app.context.projects(app.v,'marketing','prj-1111111111111111',app.S.request,'results');
  await app.api.beforeNavigate();finish({project:{id:'prj-1111111111111111',kind:'marketing',draft:'迟到项目'}});await load;
  assert.equal(app.S.project,original);assert.equal(app.v.innerHTML,'existing DOM');assert.equal(app.draft.value,'未保存口播\n第二行');
});

test('source return buttons navigate without saving, even when an unfinished form would fail save validation',async()=>{
  const app=setup();app.S.section='sources';app.form.fields.title='';app.context.location.hash=app.context.location.hash.replace('/results','/sources');
  let returned=0;app.context.MarketingOverlay={returnToSourceOrigin:()=>{returned++;return true;}};
  const original=app.context.document.getElementById,button={disabled:false,dataset:{action:'return-origin'}};app.context.document.getElementById=id=>id==='marketingNext'?button:original(id);
  app.context.MARKETING_STEPS={results:['查看稿件']};
  await app.api.marketingNext();app.api.returnToSourceOrigin();assert.equal(returned,2);assert.equal(app.calls.save,0);
  button.dataset.action='results';await app.api.marketingNext();assert.equal(app.calls.save,0);assert.deepEqual(app.calls.go,[['campaigns',app.S.project.id,'results']]);
});
test('same-hash sources can leave a handoff overlay with its exact visit context',()=>{
  const app=setup();app.S.section='sources';app.context.location.hash=app.context.location.hash.replace('/results','/sources');
  const origin={overlay:{descriptor:{runId:'assist-original',stage:'handoff'}},visit:{index:4,id:'original'}};
  app.context.MarketingOverlay={sourceOrigin:()=>origin};app.api.openProjectSection('sources');
  assert.equal(app.calls.go.length,1);assert.equal(app.calls.go[0][2],'sources');assert.equal(app.calls.go[0][4].sourceReturn,origin);
});
test('source return controls follow the current visit and clear when the same source URL has no origin',()=>{
  const app=setup(),elements=new Map(),element=()=>({hidden:false,textContent:'',innerHTML:'',dataset:{},value:'',toggleAttribute(){}});
  for(const id of ['marketingPageTitle','marketingOriginReturn','marketingPageHint','marketingStepCount','marketingNext','marketingStepState','projectDraftEditor'])elements.set(id,element());
  elements.set('projectDraft',app.draft);const back=element();app.S.section='sources';
  app.context.document.getElementById=id=>elements.get(id)||null;app.context.document.querySelectorAll=()=>[];app.context.document.querySelector=()=>back;
  app.context.MARKETING_STEPS={sources:['素材与出处','查看素材',null]};app.context.sceneWorkflow=()=>({title:'短视频'});app.context.videoBrief=()=>true;app.context.crumb=()=>{};app.context.e=String;
  let origin={overlay:{descriptor:{mode:'video'}}};app.context.MarketingOverlay={sourceReturn:()=>origin};
  runInNewContext(between('  function updateMarketingFlow(', '  async function marketingNext('),app.context);
  app.context.updateMarketingFlow();assert.equal(elements.get('marketingOriginReturn').hidden,false);assert.match(elements.get('marketingOriginReturn').innerHTML,/data-marketing-origin-return.*返回视频制作包/);assert.equal(elements.get('marketingNext').dataset.action,'return-origin');
  origin=null;app.context.updateMarketingFlow();assert.equal(elements.get('marketingOriginReturn').hidden,true);assert.equal(elements.get('marketingOriginReturn').innerHTML,'');assert.equal(elements.get('marketingNext').dataset.action,'results');assert.equal(elements.get('marketingNext').textContent,'返回稿件 →');
});

test('content landing waits for a search while a blank project picker still opens its project',async()=>{
  const requests=[],pid='prj-0000000000000000',v={querySelectorAll:()=>[]};
  const context={S:{request:1},state:{books:[]},URLSearchParams,crumb(){},e:String,num:String,K:{},STAT:{},
    pageHead:(_eyebrow,title)=>title,attrs:()=>'',btn:()=>'',request:async url=>{requests.push(url);return {project:{id:pid,title:'项目材料',items:[]}};}};
  runInNewContext(between('  function filterKind(', '  async function detail('),context);
  await context.content(v,'',1);
  assert.deepEqual(requests,[]);
  assert.doesNotMatch(v.innerHTML,/找到 0|可见成果|应用后台能力/);
  await context.content(v,'pick:'+pid,1);
  assert.deepEqual(requests,['/api/projects/'+pid]);
  assert.match(v.innerHTML,/contentProjectContext/);
});

test('book and type entries serialize filters, and a direct book entry starts at page one',async()=>{
  const requests=[],links=[],v={querySelectorAll:()=>[]};
  const context={S:{request:1},state:{books:[{code:'B68',book:'陶澍在江南'}]},URLSearchParams,crumb(){},
    e:String,num:String,K:{quote:'摘录'},STAT:{},pageHead:()=>'',attrs:()=>'',btn:()=>'',empty:()=>'',assetCard:()=>'',
    parse:()=>({view:'dashboard'}),go:(...args)=>links.push(args),request:async url=>{requests.push(new URL(url,'http://local.test').searchParams);return {items:[],total:31};}};
  runInNewContext(between('  function filterKind(', '  async function detail('),context);
  context.filterKind({dataset:{kind:'quote'}});
  assert.deepEqual(links,[['content','?kind=quote']]);
  await context.content(v,'?q=盐政&kind=quote&offset=24',1);
  assert.equal(requests[0].get('offset'),'24');
  assert.equal(requests[0].get('q'),'盐政');
  await context.content(v,'B68',1);
  assert.equal(requests[1].get('code'),'B68');
  assert.equal(requests[1].get('q'),'');
  assert.equal(requests[1].get('offset'),'0');
});
