import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source=readFileSync(new URL('../static/review.js',import.meta.url),'utf8');
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const projects=[{id:'prj-1111111111111111',kind:'marketing',title:'营销项目',brief:{goal:'不要在待办重复展示的长目标'}},{id:'prj-2222222222222222',kind:'editorial',title:'选题项目',brief:{topic:'不要重复展示的主题'}}];
const asset={asset_id:'book:quote:shared',title:'一条共用素材',book:'来源图书',kind:'quote',status:'review',action:'review_asset',reason:'内容尚未核对',projects};

function setup(){
  const storage=new Map(),calls={routes:[],details:[],toasts:[],closed:0},host={innerHTML:'',classList:{add(){}}};
  const nodes={view:host,reviewToolBook:{value:'',focused:false,focus(){this.focused=true;}}};
  const data={queue:[asset],projects:new Map(projects.map(p=>[p.id,{...p,items:[{status:'adopted'}],draft:p.kind==='marketing'?'已写好的稿件':''}]))};
  let modal='';
  const context={esc:escape,num:String,state:{books:[{code:'book',book:'来源图书'}]},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    document:{getElementById:id=>nodes[id]||null},parse:()=>({view:'editor',arg:''}),crumb(){},loading:()=>'<loading>',route(){},
    Studio:{detail:el=>calls.details.push(el)},go:(...args)=>calls.routes.push(args),toast:message=>calls.toasts.push(message),
    modalX:()=>'',openModal:html=>{modal=html;},closeModal:()=>{calls.closed++;},
    jget:async path=>path==='/api/review-queue'?{items:data.queue,total:data.queue.length,project_count:projects.length}:{project:data.projects.get(path.split('/').at(-1))}};
  context.window=context;runInNewContext(source.replace('return {render,nav,','return {row,render,nav,'),context);
  return {api:context.ReviewHub,context,calls,host,nodes,data,storage,modal:()=>modal};
}

test('shared material starts with a closed project count and opens a neutral source review',async()=>{
  const ui=setup();await ui.api.render(ui.host);
  assert.match(ui.host.innerHTML,/<h1>素材核对待办<\/h1>/);
  assert.match(ui.host.innerHTML,/<details class="review-projects" id="review-projects-0"><summary>涉及 2 个项目<\/summary>/);
  assert.doesNotMatch(ui.host.innerHTML,/review-role|review-flow|不要.*展示|data-purpose|单书资料整理|返回/);
  ui.api.detail({dataset:{id:asset.asset_id,purpose:projects[0].title}});
  assert.deepEqual(JSON.parse(JSON.stringify(ui.calls.details)),[{dataset:{id:asset.asset_id,queue:'true'}}]);
});

test('multiple stale references require choosing a project; missing sources still offer a usable project action',()=>{
  const ui=setup(),html=ui.api.row({...asset,action:'refresh_reference',status:'approved',reason:'项目引用的是旧版本'},3);
  const action=html.match(/<div class="review-primary-action">(.*?)<\/div>/s)[1];
  assert.match(action,/aria-controls="review-projects-3"/);
  assert.match(action,/ReviewHub.openProjects\(this\)">选择项目/);
  assert.match(html,/data-view="campaigns" data-id="prj-1111111111111111" data-section="review" onclick="ReviewHub.nav\(this\)">更新引用/);
  assert.match(html,/data-view="projects" data-id="prj-2222222222222222" data-section="materials" onclick="ReviewHub.nav\(this\)">更新引用/);
  assert.doesNotMatch(action,/data-id=/,'the primary action must not silently choose the first project');
  let focused=false;ui.nodes['review-projects-3']={open:false,querySelector:()=>({focus(){focused=true;}})};
  ui.api.openProjects({dataset:{target:'review-projects-3'}});assert.equal(ui.nodes['review-projects-3'].open,true);assert.equal(focused,true);
  const missing=ui.api.row({...asset,action:'replace_asset',status:'missing',projects:[projects[1]]},4);
  const missingAction=missing.match(/<div class="review-primary-action">(.*?)<\/div>/s)[1];
  assert.match(missingAction,/data-view="projects"/);assert.match(missingAction,/data-id="prj-2222222222222222"/);
  assert.match(missingAction,/>处理引用<\/button>/);assert.doesNotMatch(missingAction,/ReviewHub.detail/);
});

test('a blocked book summary with a suggested replacement links to work on the reference, not a version preview',async()=>{
  const ui=setup(),oldId='book:marketing:old-summary',newId='book:marketing:new-summary';
  ui.data.queue=[{...asset,asset_id:oldId,title:'来源图书 · 历史图书简介（带多余信息）',kind:'marketing',marketing_key:'summary',status:'missing',action:'replace_asset',reason:'原文出处无法回查，请处理稿件引用',replacement:{id:newId,title:'来源图书 · 新版简介',book:'来源图书',status:'approved'}}];
  await ui.api.render(ui.host);
  const html=ui.host.innerHTML,action=html.match(/<div class="review-primary-action">(.*?)<\/div>/s)[1];
  assert.match(html,/<h2 class="review-material-title">图书简介<\/h2>/);
  assert.match(html,/<p class="review-material-book">来源图书<\/p>/);
  assert.match(html,/原文出处无法回查，请处理稿件引用/);
  assert.doesNotMatch(html,/历史图书简介|带多余信息|查看新版简介|简介有新版|book:marketing:new-summary/);
  assert.match(action,/ReviewHub.openProjects\(this\)">选择项目<\/button>/);
  assert.match(html,/<details class="review-projects" id="review-projects-0"><summary>涉及 2 个项目<\/summary>/);
  assert.match(html,/data-view="campaigns" data-id="prj-1111111111111111" data-section="review" onclick="ReviewHub.nav\(this\)">处理引用<\/button>/);
  assert.match(html,/data-view="projects" data-id="prj-2222222222222222" data-section="materials" onclick="ReviewHub.nav\(this\)">处理引用<\/button>/);
  assert.equal(ui.calls.details.length,0);assert.equal(ui.calls.routes.length,0);
  ui.api.nav({dataset:{view:'campaigns',id:projects[0].id,section:'review'}});
  ui.api.nav({dataset:{view:'projects',id:projects[1].id,section:'materials'}});
  assert.deepEqual(ui.calls.routes,[['campaigns',projects[0].id,'review'],['projects',projects[1].id,'materials']]);
});

test('a genuinely missing summary leads to the selected marketing project’s delivery check',()=>{
  const ui=setup();
  for(const replacement of [undefined,null,{}]){
    const html=ui.api.row({...asset,kind:'marketing',marketing_key:'summary',title:'来源图书 · 旧简介长标题',status:'missing',action:'replace_asset',reason:'原简介已不在内容成果中',projects:[projects[0]],replacement},0);
    assert.match(html,/<h2 class="review-material-title">图书简介<\/h2>/);
    assert.match(html,/>来源已缺失<\/span>/);assert.match(html,/原简介已不在内容成果中/);
    assert.match(html,/data-view="campaigns" data-id="prj-1111111111111111" data-section="review" onclick="ReviewHub.nav\(this\)">处理引用<\/button>/);
    assert.doesNotMatch(html,/简介有新版|查看新版简介|查看引用|ReviewHub.detail/);
  }
});

test('reviewable sources can be checked directly and unusable sources link to a project action',()=>{
  const ui=setup(),ready=ui.api.row({...asset,kind:'marketing',marketing_key:'summary',title:'简介的完整正文'},0);
  assert.match(ready,/<h2 class="review-material-title">图书简介<\/h2>/);
  assert.match(ready,/>核对素材<\/button>/);
  for(const [status,evidenceValid,label] of [['rejected',true,'已停用'],['review',false,'出处需处理']]){
    const html=ui.api.row({...asset,status,evidence_valid:evidenceValid,projects:[projects[0]]},0);
    assert.match(html,/<h2 class="review-material-title">一条共用素材<\/h2>/);
    assert.ok(html.includes('>'+label+'</span>'));
    assert.match(html,/data-section="review" onclick="ReviewHub.nav\(this\)">处理引用<\/button>/);
    assert.doesNotMatch(html,/ReviewHub.detail/);
  }
  const unrelated=ui.api.row({...asset,status:'missing',action:'replace_asset',replacement:{id:'unrelated'}},0);
  assert.match(unrelated,/<h2 class="review-material-title">一条共用素材<\/h2>/);
  assert.match(unrelated,/>来源已缺失<\/span>/);assert.doesNotMatch(unrelated,/简介有新版|查看新版简介|查看引用/);
});

test('after shared confirmation, completion links still reach every related project',async()=>{
  const ui=setup();await ui.api.render(ui.host);ui.api.noteReviewed(asset.asset_id,'approved');
  ui.data.queue=[];await ui.api.render(ui.host);
  assert.match(ui.host.innerHTML,/本轮素材已核对/);
  assert.match(ui.host.innerHTML,/营销项目/);assert.match(ui.host.innerHTML,/选题项目/);
  assert.match(ui.host.innerHTML,/data-id="prj-1111111111111111" data-section="results"/);
  assert.match(ui.host.innerHTML,/data-id="prj-2222222222222222" data-section="results"/);
  assert.match(ui.host.innerHTML,/>打开稿件<\/button>/);assert.match(ui.host.innerHTML,/>打开项目<\/button>/);
  assert.doesNotMatch(ui.host.innerHTML,/讨论稿|READY FOR THE NEXT STEP|返回/);
});

test('book tools are independently callable and preserve chapter and citation routes without appearing in the queue',async()=>{
  const ui=setup();ui.data.queue=[];await ui.api.render(ui.host);
  assert.doesNotMatch(ui.host.innerHTML,/单书资料整理|reviewToolBook|openBookTools/);
  ui.api.openBookTools();assert.match(ui.modal(),/单书资料整理/);assert.match(ui.modal(),/aria-label="选择要整理的图书"/);assert.equal(ui.nodes.reviewToolBook.focused,true);
  ui.api.tools({dataset:{tab:'chapter'}});assert.equal(ui.calls.routes.length,0);assert.equal(ui.calls.toasts.length,1);
  ui.nodes.reviewToolBook.value='book';ui.api.tools({dataset:{tab:'chapter'}});ui.api.tools({dataset:{tab:'cite'}});
  assert.deepEqual(ui.calls.routes,[['editor','book','chapter'],['editor','book','cite']]);assert.equal(ui.calls.closed,2);
});
