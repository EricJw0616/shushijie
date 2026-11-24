import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const appSource=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const workspace=readFileSync(new URL('../static/workspace.js',import.meta.url),'utf8');
const cut=(source,from,to)=>source.slice(source.indexOf(from),source.indexOf(to,source.indexOf(from)));
const overlayCode=cut(appSource,'const AppHistory=(function(){','// tab 可选');
const materialCode=cut(workspace,'  function materialDetailDescriptor(', '  function markDirty(');
const nameCheckMarkup=cut(workspace,'  function nameCheckForm(', '  async function loadNameChecks(');
const registration=workspace.match(/^  window\.MarketingOverlay\?\.register\?\.\('project-material'.*$/m)[0];
const pid='prj-0000000000000000',aid='B01:fact:0123456789abcdefabcd';
const baseHash='#/campaigns/'+pid+'/review';
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone=value=>JSON.parse(JSON.stringify(value));
const settle=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function project(){return {id:pid,kind:'marketing',title:'共用项目',revision:4,draft:'保留已保存正文',draft_asset_ids:[aid],items:[
  {asset_id:aid,asset_revision:'source-v1',status:'adopted',current_status:'review',stale:false,evidence_valid:true,quality_issues:[],note:'原有备注',
   snapshot:{id:aid,code:'B01',kind:'fact',title:'材料一',book:'任意图书',text:'当前引用的书中内容',status:'review',evidence:[{anchor:'B01-01',quote:'书中原文'}]}}
]};}
function setup(shared,saved=project()){
  const browser=shared||{entries:[{hash:baseHash,state:null}],cursor:0,storage:new Map()};
  const calls={writes:0,generations:0,remember:0},toasts=[];let context,ui,nav;
  const root={id:'projectSidePanelRoot',innerHTML:'',querySelector(){return {focus(){}};},querySelectorAll(){return [];}};
  const modal={id:'modalRoot',innerHTML:'',querySelectorAll(){return [];}};
  const S={project:null,section:'review',dirty:true},ProjectUI={detail:null,notes:{[aid]:'还没保存的备注'}};
  const location={get hash(){return browser.entries[browser.cursor].hash;},get href(){return 'http://localhost/'+this.hash;},set hash(value){browser.entries.splice(browser.cursor+1);browser.entries.push({hash:value,state:null});browser.cursor++;}};
  const parse=()=>{const p=location.hash.slice(2).split('/').map(decodeURIComponent);return {view:p[0],arg:p[1],tab:p[2]};};
  function hydrate(){const p=parse();S.project=p.view==='campaigns'?clone(saved):null;S.section=p.tab;}
  hydrate();
  const history={get state(){return browser.entries[browser.cursor].state;},scrollRestoration:'auto',replaceState(value,_,url){browser.entries[browser.cursor]={state:value,hash:url?.includes('#')?url.slice(url.indexOf('#')):location.hash};},pushState(value,_,url){browser.entries.splice(browser.cursor+1);browser.entries.push({state:value,hash:url?.includes('#')?url.slice(url.indexOf('#')):location.hash});browser.cursor++;},back(){this.go(-1);},go(delta){const old=location.hash;browser.cursor=Math.max(0,Math.min(browser.entries.length-1,browser.cursor+delta));queueMicrotask(()=>{nav.capture(false);ui.sync();if(old!==location.hash){ui.clear();hydrate();context.state.lastHash=location.hash;ui.sync();}});}};
  context={S,ProjectUI,SECTIONS:['task','materials','results','review','sources','history'],K:{fact:'事实与案例'},STAT:{review:'待核对',approved:'已确认',adopted:'项目采用',selected:'待选择',not_fit:'本项目不采用'},e:escape,
    location,history,parse,state:{lastHash:location.hash,scroll:{},depth:0},scrollY:0,
    sessionStorage:{getItem:key=>browser.storage.get(key)||null,setItem:(key,value)=>browser.storage.set(key,value)},
    document:{getElementById:id=>id===root.id?root:id===modal.id?modal:null,querySelector:()=>root.innerHTML?{}:null},
    setTimeout:fn=>queueMicrotask(fn),toast:message=>toasts.push(message),markDirty(){},
    request:()=>{calls.writes++;throw new Error('Material navigation must not save');},
    ProjectAssist:{start:()=>{calls.generations++;throw new Error('Material navigation must not generate');}}};
  context.window=context;
  runInNewContext([overlayCode,'this.nav=AppHistory;',
    cut(appSource,'function go(view,arg,tab,q,','\nfunction openBook(code)'),
    cut(workspace,'  function attrs(', '  function empty('),nameCheckMarkup,materialCode,
    'this.Studio={openMaterialDetail,closeMaterialDetail,materialSource,restoreMaterialDetail,rememberNavigation:()=>{calls.remember++;}};',registration].join('\n'),
    Object.assign(context,{calls,loadNameChecks(){}}));
  ui=context.MarketingOverlay;nav=context.nav;
  function route(){ui.clear();hydrate();context.state.lastHash=location.hash;ui.sync();}
  return {context,browser,S,ProjectUI,root,history,ui,calls,toasts,route,html:()=>root.innerHTML,api:context.Studio};
}

test('original-text Back restores the same material and review visit after refreshing the browser',async()=>{
  const first=setup();first.api.openMaterialDetail({dataset:{id:aid}});
  assert.deepEqual(clone(first.history.state.__marketingOverlay.descriptor),{type:'project-material',projectId:pid,assetId:aid,section:'review'});
  assert.match(first.html(),/返回交付前检查/);
  assert.match(first.html(),/还没保存的备注/);
  first.api.materialSource({dataset:{code:'B01',anchor:'B01-01'}});first.route();
  assert.equal(first.context.location.hash,'#/book/B01/text/B01-01');assert.equal(first.html(),'');
  const fresh=setup(first.browser);fresh.history.back();await settle();
  assert.equal(fresh.context.location.hash,baseHash);assert.equal(fresh.ProjectUI.detail.id,aid);
  assert.match(fresh.html(),/当前引用的书中内容/);assert.match(fresh.html(),/返回交付前检查/);
  assert.equal(fresh.browser.cursor,1,'restoring uses the saved history visit rather than adding a step');
  fresh.api.closeMaterialDetail();await settle();assert.equal(fresh.browser.cursor,0);assert.equal(fresh.html(),'');
  fresh.history.go(1);await settle();assert.match(fresh.html(),/材料一/);
  for(const app of [first,fresh]){assert.equal(app.calls.writes,0);assert.equal(app.calls.generations,0);}
});

test('refreshing a detail restores only its panel and preserves mounted local edits',async()=>{
  const first=setup();first.api.openMaterialDetail({dataset:{id:aid}});
  const fresh=setup(first.browser);fresh.S.project.draft='挂载后未保存的正文';fresh.S.project.brief={topic:'未保存要求'};
  const before=JSON.stringify(fresh.S.project);fresh.ui.sync();await settle();
  assert.equal(JSON.stringify(fresh.S.project),before);assert.equal(fresh.S.dirty,true);
  assert.equal(fresh.ProjectUI.notes[aid],'还没保存的备注');assert.match(fresh.html(),/还没保存的备注/);
  assert.equal(fresh.calls.writes,0);assert.equal(fresh.calls.generations,0);
});

test('a removed material restores a readable return panel instead of an invisible Back stop',async()=>{
  const first=setup();first.api.openMaterialDetail({dataset:{id:aid}});const latest=project();latest.items=[];
  const fresh=setup(first.browser,latest);fresh.ui.sync();await settle();
  assert.match(fresh.html(),/这条材料已移出项目/);assert.match(fresh.html(),/返回交付前检查/);
  assert.ok(!fresh.html().includes('Studio.confirmMaterial'));fresh.api.closeMaterialDetail();await settle();
  assert.equal(fresh.browser.cursor,0);assert.equal(fresh.html(),'');
});

test('restoration ignores another project, another section, invalid identifiers and expired visits',()=>{
  const app=setup(),saved={type:'project-material',projectId:pid,assetId:aid,section:'review'};
  for(const patch of [{projectId:'prj-1111111111111111'},{projectId:'../elsewhere'},{assetId:'bad\nvalue'},{assetId:''},{assetId:'x'.repeat(301)},{section:'sources'},{section:'unknown'}]){
    app.api.restoreMaterialDetail({...saved,...patch},{isCurrent:()=>true,options:{restore:true}});assert.equal(app.html(),'');
  }
  app.api.restoreMaterialDetail(saved,{isCurrent:()=>false,options:{restore:true}});assert.equal(app.html(),'');
  assert.equal(app.browser.cursor,0);assert.equal(app.calls.writes,0);
});

test('old references cannot inherit a new version approval or offer confirmation and adoption',()=>{
  const saved=project();saved.items[0].stale=true;saved.items[0].current_status='approved';
  const app=setup(undefined,saved);app.api.openMaterialDetail({dataset:{id:aid}});
  assert.match(app.html(),/引用版本待更新/);assert.match(app.html(),/旧引用，不能直接确认/);assert.match(app.html(),/原引用位置/);
  assert.match(app.html(),/查看当前成果/);assert.match(app.html(),/Studio\.refreshItem/);
  assert.ok(!app.html().includes('studio-badge approved'));assert.ok(!app.html().includes('Studio.confirmMaterial'));
  assert.ok(!app.html().includes('data-status="adopted"'));assert.equal(saved.items[0].snapshot.text,'当前引用的书中内容');
});

test('missing and retired sources give replacement guidance without dead update actions',()=>{
  for(const status of ['missing','rejected']){
    const saved=project();saved.items[0].current_status=status;saved.items[0].stale=true;
    const app=setup(undefined,saved);app.api.openMaterialDetail({dataset:{id:aid}});
    assert.match(app.html(),status==='missing'?/来源已缺失/:/内容已停用/);assert.match(app.html(),/请更换素材/);
    assert.ok(!app.html().includes('Studio.refreshItem'));assert.ok(!app.html().includes('Studio.confirmMaterial'));
    assert.ok(!app.html().includes('data-status="adopted"'));
  }
  const current=setup();current.api.openMaterialDetail({dataset:{id:aid}});assert.match(current.html(),/Studio\.confirmMaterial/);
  current.api.closeMaterialDetail();
});

test('source-page material restores its own location without incorrectly labeling it as review',async()=>{
  const first=setup();first.context.go('campaigns',pid,'sources');first.route();first.api.openMaterialDetail({dataset:{id:aid}});
  const fresh=setup(first.browser);fresh.ui.sync();await settle();
  assert.equal(fresh.history.state.__marketingOverlay.descriptor.section,'sources');
  assert.match(fresh.html(),/材料一/);assert.ok(!fresh.html().includes('返回交付前检查'));
  fresh.api.closeMaterialDetail();await settle();assert.equal(fresh.context.location.hash,'#/campaigns/'+pid+'/sources');
});
