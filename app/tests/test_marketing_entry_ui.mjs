import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const read=name=>readFileSync(new URL('../static/'+name,import.meta.url),'utf8');
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function setup(){
  const storage=new Map(),routes=[],host={innerHTML:'',classList:{add(){}}};
  const context={esc:escape,state:{books:[]},document:{getElementById:id=>id==='marketingEntry'?host:null},crumb(){},addEventListener(){},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},go:(...args)=>routes.push(args)};
  context.window=context;
  runInNewContext(read('marketing-scenes.js')+'\n'+read('marketing-purpose.js')+'\n'+read('marketing-entry.js')+'\n'+read('records.js').replace('return {render,search,','return {R,sceneFilters,row,empty,restoreViews,remember,render,search,'),context);
  return {context,storage,routes,host,entry:context.MarketingEntry,records:context.ProjectRecords};
}

test('overall planning is visible first while each existing scene remains a direct entry',()=>{
  const ui=setup();ui.entry.render(ui.host);
  const targets=Array.from(ui.host.innerHTML.matchAll(/href="#\/campaigns\/new\/([^"<]+)"/g),m=>decodeURIComponent(m[1]));
  assert.deepEqual(targets,['planning','公众号','短视频','小红书','达人讲书','书店活动']);
  assert.match(ui.host.innerHTML,/<h2>营销整体方案<\/h2>/);
  assert.match(ui.host.innerHTML,/>渠道内容<\/h2>/);
  assert.doesNotMatch(ui.host.innerHTML,/先做整体方案|还没确定渠道/);
  assert.doesNotMatch(ui.host.innerHTML,/<details/,'the first plan entry must not require expanding a hidden section');
  assert.match(ui.host.innerHTML,/href="#\/records\/marketing"/);
});

test('records use the same planning label and first category without changing stored filters or routes',()=>{
  const ui=setup(),saved={kind:'marketing',views:{marketing:{q:'原来的推广主题',scene:'planning',offset:20}}};
  ui.storage.set('bookworld.work-projects',JSON.stringify(saved));
  ui.records.restoreViews();Object.assign(ui.records.R,{kind:'marketing',...ui.records.R.views.marketing});
  const filters=ui.records.sceneFilters();
  assert.deepEqual(Array.from(filters.matchAll(/data-scene="([^"]*)"/g),m=>m[1]),['','planning','公众号','短视频','小红书','达人讲书','书店活动']);
  assert.match(filters,/data-scene="planning" aria-pressed="true"[^>]*>营销整体方案<\/button>/);
  const row=ui.records.row({id:'existing-plan',kind:'marketing',title:'已有方案',brief:{},marketing_scenes:['planning'],has_draft:true});
  assert.match(row,/<span>营销整体方案<\/span>/);
  assert.match(row,/href="#\/campaigns\/existing-plan"/);
  assert.match(ui.records.empty(false),/href="#\/campaigns\/new\/planning"/);
  ui.records.remember();
  assert.deepEqual(JSON.parse(ui.storage.get('bookworld.work-projects')).views.marketing,saved.views.marketing);
  ui.records.open({preventDefault(){}},{dataset:{scene:'planning',kind:'marketing',id:'existing-plan',section:''}});
  assert.deepEqual(ui.routes,[['campaigns','existing-plan','']]);
  assert.ok(!ui.storage.has('bookworld.draft-scene:existing-plan'));
  ui.records.open({preventDefault(){}},{dataset:{scene:'公众号',kind:'marketing',id:'existing-article',section:'results'}});
  assert.equal(ui.storage.get('bookworld.draft-scene:existing-article'),'公众号');
  assert.deepEqual(ui.routes[1],['campaigns','existing-article','results']);
});

test('all six forms explain their audience approach near the audience field without adding required inputs',()=>{
  const ui=setup(),scenes=['planning','公众号','短视频','小红书','达人讲书','书店活动'],hints=[];
  ui.context.state.books=[{code:'different-book',book:'另一类图书'}];
  for(const scene of scenes){
    const guide=ui.context.MarketingScenes.audienceGuide(scene);
    const brief=scene==='planning'?{marketing_task:'theme'}:{marketing_task:'channel',channels:[scene]};
    assert.equal(ui.context.MarketingScenes.audienceGuide(brief).hint,guide.hint);
    ui.entry.render(ui.host,'new',scene);
    assert.ok(ui.host.innerHTML.includes('<p class="marketing-audience-hint" id="marketingAudienceHint">'+escape(guide.hint)+'</p>'));
    assert.match(ui.host.innerHTML,/name="audience" required aria-describedby="marketingAudienceHint"/);
    assert.equal(Array.from(ui.host.innerHTML.matchAll(/<(?:input|textarea)[^>]*\brequired\b/g)).length,3);
    const notes=ui.host.innerHTML.match(/<textarea[^>]*name="writing_notes"[^>]*>/)[0];
    assert.doesNotMatch(notes,/\brequired\b/);
    hints.push(guide.hint);
  }
  assert.equal(new Set(hints).size,6,'each scene has a specific approach instead of a repeated slogan');
});

test('creator hints separate speaker, listeners, readers and buyer while the four-minute example never overwrites user requirements',()=>{
  const ui=setup();ui.context.state.books=[{code:'other',book:'别的图书'}];
  ui.storage.set('bookworld.marketing-new:达人讲书',JSON.stringify({audience:'专业听众',book_readers:'行业初学者',purpose:'purchase',decision_maker:'机构采购',writing_notes:'约7分钟，讲清专业判断依据。'}));
  ui.entry.render(ui.host,'new','达人讲书');
  assert.match(ui.host.innerHTML,/>讲给谁听 /);
  assert.match(ui.host.innerHTML,/讲稿供讲书者使用/);
  assert.match(ui.host.innerHTML,/围绕听众在意的问题/);
  assert.match(ui.host.innerHTML,/图书读者与选购者可另填/);
  assert.match(ui.host.innerHTML,/name="audience"[^>]*value="专业听众"/);
  assert.match(ui.host.innerHTML,/name="book_readers"[^>]*value="行业初学者"/);
  assert.match(ui.host.innerHTML,/name="decision_maker"[^>]*value="机构采购"/);
  assert.match(ui.host.innerHTML,/name="writing_notes"[^>]*placeholder="例如：约4分钟[^>]*>约7分钟，讲清专业判断依据。<\/textarea>/);
});
