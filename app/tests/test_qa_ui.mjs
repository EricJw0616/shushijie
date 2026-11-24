import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source=readFileSync(new URL('../static/qa.js',import.meta.url),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {resolve,reject,promise};};
const clone=value=>JSON.parse(JSON.stringify(value));
const status={books:[{code:'B01',title:'甲书',segments:12},{code:'B02',title:'乙书',segments:18}],book_count:2,segment_count:30,ready:true,model_ready:true,revision:'r1'};
const result={answer:'这是有依据的回答。[1]',sources:[{id:1,code:'B01',book:'甲书',chapter:'第一章',anchor:'B01-01-P01',quote:'这是原文。'}],suggestions:['继续解释这个观点'],mode:'answer',notice:'',scope:{book_codes:[],book_count:2,revision:'r1'}};
const sourceNotice='回答依据当前检索到的原文生成；书中观点与现实事实仍需区分。';
const libraryUpdateNotice='书库已更新。这条回答保留生成时的内容，可按当前书库重新提问。';
function setup(options={}){
  const storage=options.storage||new Map(),calls=[],copied=[],notifications=[],nodes={},listeners={},responses={status:clone(options.status||status),answer:clone(result)};
  const input={value:'',style:{},scrollHeight:92,selectionStart:0,selectionEnd:0,focus(){context.document.activeElement=this;},setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;},scrollIntoView(){}};
  const dialog={open:false,className:'',innerHTML:'',showModal(){this.open=true;},close(){this.open=false;},querySelector:selector=>nodes[selector]||null,querySelectorAll:()=>[]};
  nodes['#qaQuestion']=input;nodes['dialog']=dialog;nodes['.qa-send']={disabled:false};nodes['.qa-live']={textContent:''};nodes['.qa-delete-error']={textContent:''};
  const host={innerHTML:'',isConnected:true,classList:{add(){},toggle(){}},querySelector:selector=>nodes[selector]||null,addEventListener:(name,fn)=>listeners[name]=fn};
  const view={innerHTML:'',classList:{add(){}},firstElementChild:host};
  let serial=0;
  const context={location:{hash:'#/qa',origin:'http://localhost:8943'},document:{activeElement:null,querySelector:selector=>selector==='.workspace-name'?{textContent:options.workspace||'测试空间'}:null},
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>{if(options.quota)throw new Error('quota');storage.set(key,value);}},
    crypto:{randomUUID:()=>`qa-test-${++serial}`},requestAnimationFrame:fn=>fn(),AbortController,URLSearchParams,setTimeout,clearTimeout,
    matchMedia:()=>({matches:false}),crumb(){},toast(message){notifications.push(message);},navigator:{clipboard:{writeText:async value=>{if(options.clipboardDenied)throw new Error('clipboard denied');if(options.clipboardWait)await options.clipboardWait;copied.push(value);}}},
    fetch:async(url,config={})=>{calls.push({url,body:config.body?JSON.parse(config.body):undefined});const data=url==='/api/qa/status'?responses.status:await (typeof responses.answer==='function'?responses.answer():responses.answer);return {ok:true,json:async()=>clone(data)};}};
  context.window=context;
  // Expose existing closures to exercise async completion with a minimal browser stub.
  runInNewContext(source.replace('return {render};','return {render,ask,Q,draw,openScope,openHistory,answerText,sourceCards,selectSource,copyAnswer,changeCategory,openDelete,confirmDelete,cancelDelete};'),context);
  return {api:context.BookQA,context,view,host,nodes,storage,calls,copied,notifications,responses,listeners};
}

test('welcome uses live books and escapes book titles in question examples',async()=>{
  const ui=setup();ui.responses.status.books[0].title='书名"><img src=x onerror=alert(1)>';
  await ui.api.render(ui.view);
  assert.match(ui.host.innerHTML,/让每一个问题/);assert.match(ui.host.innerHTML,/2 本图书可检索/);
  assert.match(ui.host.innerHTML,/新入库图书自动纳入/);assert.match(ui.host.innerHTML,/maxlength="1200"/);
  assert.match(ui.host.innerHTML,/&lt;img/);assert.doesNotMatch(ui.host.innerHTML,/<img|onerror="alert/);
  assert.match(ui.host.innerHTML,/选择任务，填入你的关键词/);assert.doesNotMatch(ui.host.innerHTML,/95%|7 本图书/);
});

test('task cards prefer actual scoped-book examples and unfinished comparison templates are not sent',async()=>{
  const ui=setup();ui.responses.status.books[0].sample_question='甲书怎样描述真实概念？';ui.responses.status.books[0].sample_quote_question='找出甲书中关于真实概念的原文。';
  await ui.api.render(ui.view);
  assert.match(ui.host.innerHTML,/data-question="甲书怎样描述真实概念？"/);assert.match(ui.host.innerHTML,/找出甲书中关于真实概念的原文/);
  await ui.api.ask('比较“[填入共同主题]”');assert.equal(ui.calls.filter(x=>x.url==='/api/qa/ask').length,0);
  ui.api.Q.current.book_codes=['B02'];ui.api.draw();assert.doesNotMatch(ui.host.innerHTML,/甲书怎样描述真实概念/);
  assert.match(ui.host.innerHTML,/选择任务，填入你的关键词/);
});

test('answers, questions and quotes are escaped, and only actual sources become citation controls',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  ui.responses.answer.answer='<script>alert(1)</script> **有依据** [1] 以及未知引用 [99]';
  ui.responses.answer.sources[0].quote='<img src=x onerror=alert(2)>';
  await ui.api.ask('问题 <svg onload=alert(3)>');
  assert.match(ui.host.innerHTML,/问题 &lt;svg/);assert.match(ui.host.innerHTML,/&lt;script&gt;/);
  assert.match(ui.api.sourceCards(ui.api.Q.current.turns[0]),/&lt;img src=x/);assert.doesNotMatch(ui.host.innerHTML,/<script>|<img src=x|<svg onload/);
  assert.match(ui.host.innerHTML,/<strong>有依据<\/strong>/);assert.match(ui.host.innerHTML,/data-qa-action="cite" data-turn="[^"]+" data-source="1"/);
  assert.doesNotMatch(ui.host.innerHTML,/data-source="99"/);assert.match(ui.host.innerHTML,/\[99\]/);
  const saved=JSON.parse([...ui.storage.values()][0]);assert.equal(saved.sessions[0].turns[0].sources[0].anchor,'B01-01-P01');
});

test('follow-up sends completed conversational context and a fixed explicit book scope',async()=>{
  const ui=setup();await ui.api.render(ui.view);ui.api.Q.current.book_codes=['B01'];
  await ui.api.ask('第一个问题');await ui.api.ask('再解释一下');
  const requests=ui.calls.filter(x=>x.url==='/api/qa/ask');
  assert.deepEqual(requests[1].body.book_codes,['B01']);
  assert.deepEqual(requests[1].body.history,[{role:'user',content:'第一个问题'},{role:'assistant',content:result.answer}]);
  assert.match(ui.host.innerHTML,/已选 1 本图书/);assert.equal(ui.api.Q.current.turns.length,2);
});

test('late answers are retained without repainting a different page',async()=>{
  const ui=setup(),pending=deferred();await ui.api.render(ui.view);ui.responses.answer=()=>pending.promise;
  const work=ui.api.ask('等待回答');ui.context.location.hash='#/content';ui.host.isConnected=false;ui.host.innerHTML='另一页面';
  pending.resolve(result);await work;
  assert.equal(ui.host.innerHTML,'另一页面');assert.equal(ui.api.Q.current.turns[0].status,'done');assert.equal(ui.api.Q.pending,null);
  const saved=JSON.parse([...ui.storage.values()][0]);assert.equal(saved.sessions[0].turns[0].answer,result.answer);
});

test('failures preserve the question for editing and retry, excluding failed answers from follow-up context',async()=>{
  const ui=setup();await ui.api.render(ui.view);ui.responses.answer=()=>Promise.reject(new Error('网络中断'));
  await ui.api.ask('保留我的问题');
  assert.equal(ui.api.Q.draft,'保留我的问题');assert.doesNotMatch(ui.host.innerHTML,/网络中断|本次回答未完成|重新提问|qa-turn\"/);
  const id=ui.api.Q.current.turns[0].id;ui.responses.answer=result;await ui.api.ask('保留我的问题',id);
  assert.equal(ui.api.Q.current.turns.length,1);assert.equal(ui.api.Q.current.turns[0].status,'done');
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[]);
});

test('completed answer refreshes library revision and does not mark a newly added book as stale',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  ui.responses.status={...status,revision:'r2',book_count:3,segment_count:40,books:[...status.books,{code:'B03',title:'新入库图书',segments:10}]};
  ui.responses.answer.scope={book_codes:['B01','B02','B03'],book_count:3,revision:'r2'};
  await ui.api.ask('新书的问题');
  assert.equal(ui.api.Q.status.revision,'r2');assert.match(ui.host.innerHTML,/3 本图书可检索/);
  assert.doesNotMatch(ui.host.innerHTML,/图书内容已有更新|书库已更新/);assert.match(ui.host.innerHTML,/全部图书 · 3 本/);
});

test('global library changes keep historical quotes and do not claim that the cited book itself changed',async()=>{
  const first=setup();await first.api.render(first.view);await first.api.ask('历史问题');
  const second=setup({storage:first.storage,status:{...status,revision:'r2',book_count:3,segment_count:35,books:[...status.books,{code:'B03',title:'新增的其他图书',segments:5}]}});await second.api.render(second.view);
  const turn=second.api.Q.current.turns[0];
  assert.match(second.host.innerHTML,/历史问题/);assert.ok(second.host.innerHTML.includes(libraryUpdateNotice));
  assert.doesNotMatch(second.host.innerHTML,/图书内容已有更新|这本书已更新|甲书已更新/);
  assert.ok(second.host.innerHTML.indexOf('qa-answer-prose')<second.host.innerHTML.indexOf(libraryUpdateNotice),'the update hint belongs below the answer');
  assert.match(second.api.sourceCards(turn),/这是原文/);
  second.api.selectSource(turn.id,1);
  assert.equal(second.nodes.dialog.open,true);
  assert.ok(second.nodes.dialog.innerHTML.includes(sourceNotice),'older answers without a stored notice receive the drawer guidance');
  assert.match(second.nodes.dialog.innerHTML,/回答生成时的引用/);
  assert.match(second.nodes.dialog.innerHTML,/查看上下文时读取当前原文/);
  assert.match(second.nodes.dialog.innerHTML,/这是原文/);
  await second.api.copyAnswer(turn.id);
  assert.ok(second.copied[0].includes(libraryUpdateNotice));assert.match(second.copied[0],/\[1\] 《甲书》 第一章\n这是原文。/);
  const other=setup({storage:first.storage,workspace:'另一空间'});await other.api.render(other.view);
  assert.doesNotMatch(other.host.innerHTML,/历史问题/);assert.equal(other.api.Q.current.turns.length,0);
});

test('standard source guidance moves to the source drawer while citations and source access remain',async()=>{
  const ui=setup();await ui.api.render(ui.view);ui.responses.answer.notice=sourceNotice;
  await ui.api.ask('解释这段内容');const turn=ui.api.Q.current.turns[0];
  assert.doesNotMatch(ui.host.innerHTML,/qa-answer-source-count|依据 1 段原文/);
  assert.ok(!ui.host.innerHTML.includes(sourceNotice));
  assert.match(ui.host.innerHTML,/data-qa-action="cite" data-turn="[^"]+" data-source="1"/);
  assert.match(ui.host.innerHTML,/data-qa-action="sources"/);
  await ui.api.copyAnswer(turn.id);
  assert.ok(!ui.copied[0].includes(sourceNotice));assert.ok(ui.copied[0].includes(result.answer));
  assert.match(ui.copied[0],/\[1\] 《甲书》 第一章\n这是原文。/);
  ui.api.selectSource(turn.id,1);
  assert.equal(ui.nodes.dialog.open,true);assert.ok(ui.nodes.dialog.innerHTML.includes(sourceNotice));
});

test('additional material limitations stay in the answer and copied content after the standard prefix is removed',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  const limitation='部分疑似缺失数字的片段已排除；本回答未覆盖全部章节。';
  ui.responses.answer.notice=sourceNotice+'\n'+limitation;
  await ui.api.ask('解释材料中的数字');const turn=ui.api.Q.current.turns[0];
  assert.ok(ui.host.innerHTML.includes(limitation));assert.ok(!ui.host.innerHTML.includes(sourceNotice));
  await ui.api.copyAnswer(turn.id);
  assert.ok(ui.copied[0].includes(limitation));assert.ok(!ui.copied[0].includes(sourceNotice));
  ui.api.selectSource(turn.id,1);
  assert.ok(ui.nodes.dialog.innerHTML.includes(sourceNotice));assert.ok(ui.nodes.dialog.innerHTML.includes(limitation));
  const restored=setup({storage:ui.storage});await restored.api.render(restored.view);
  assert.ok(restored.host.innerHTML.includes(limitation));assert.ok(!restored.host.innerHTML.includes(sourceNotice));
});

test('unknown notices are preserved, including standard wording that is not a prefix',async()=>{
  for(const notice of ['这条回答只依据第一章，不能据此判断其他章节。','编辑补充：'+sourceNotice+'本次仅比较了两个选段。']){
    const ui=setup();await ui.api.render(ui.view);ui.responses.answer.notice=notice;
    await ui.api.ask('比较这两个选段');
    assert.ok(ui.host.innerHTML.includes(notice));
    await ui.api.copyAnswer(ui.api.Q.current.turns[0].id);
    assert.ok(ui.copied[0].includes(notice));
  }
});

test('manual copy fallback preserves and escapes an unknown material restriction',async()=>{
  const ui=setup({clipboardDenied:true});await ui.api.render(ui.view);
  ui.responses.answer.notice='仅依据标为 <待核对> 的选段，尚不能推断全书结论。';
  await ui.api.ask('说明这一观点');
  assert.match(ui.host.innerHTML,/标为 &lt;待核对&gt; 的选段/);
  await ui.api.copyAnswer(ui.api.Q.current.turns[0].id);
  assert.equal(ui.copied.length,0);assert.equal(ui.nodes.dialog.open,true);
  assert.match(ui.nodes.dialog.innerHTML,/标为 &lt;待核对&gt; 的选段/);
  assert.doesNotMatch(ui.nodes.dialog.innerHTML,/<待核对>/);
});

test('an unavailable or unknown library revision does not assert that the library changed',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('解释这一概念');
  ui.api.Q.status.revision='r2';ui.api.Q.statusError='状态暂不可用';ui.api.draw();
  assert.doesNotMatch(ui.host.innerHTML,/书库已更新/);
  await ui.api.copyAnswer(ui.api.Q.current.turns[0].id);assert.ok(!ui.copied[0].includes(libraryUpdateNotice));
  ui.api.Q.statusError='';ui.api.Q.current.turns[0].scope.revision='';ui.api.draw();
  assert.doesNotMatch(ui.host.innerHTML,/书库已更新/);
});

test('storage quota does not lose the current answer and leaves a persistent visible save warning',async()=>{
  const ui=setup({quota:true});await ui.api.render(ui.view);await ui.api.ask('保留当前回答');
  assert.equal(ui.api.Q.current.turns[0].answer,result.answer);assert.match(ui.host.innerHTML,/当前浏览器无法保存记录/);
  ui.api.draw();assert.match(ui.host.innerHTML,/关闭前请复制重要回答/);
});

test('oversized input is rejected before network work and loading never fabricates progress',async()=>{
  const ui=setup(),pending=deferred();await ui.api.render(ui.view);await ui.api.ask('字'.repeat(1201));
  assert.equal(ui.calls.filter(x=>x.url==='/api/qa/ask').length,0);
  ui.responses.answer=()=>pending.promise;const work=ui.api.ask('正常问题');
  assert.match(ui.host.innerHTML,/正在检索图书并整理回答/);assert.doesNotMatch(ui.host.innerHTML,/\d+%|停止生成/);
  assert.match(ui.host.innerHTML,/data-qa-action="new" disabled/);assert.match(ui.host.innerHTML,/data-qa-action="history" disabled/);
  pending.resolve(result);await work;
});

test('classification replaces title chips and travels with every question',async()=>{
  const ui=setup();
  ui.responses.status.books[0].clc_code='I';ui.responses.status.books[1].clc_code='C';
  ui.responses.status.classifications=[{code:'I',name:'文学',book_count:1},{code:'C',name:'社会科学总论',book_count:1}];
  await ui.api.render(ui.view);
  assert.match(ui.host.innerHTML,/select aria-label="中图分类"/);
  assert.doesNotMatch(ui.host.innerHTML,/class="qa-book-chip|class="qa-book-more/);
  ui.api.Q.draft='保留待提问内容';ui.api.Q.current.book_codes=['B02'];
  ui.api.changeCategory('I');
  assert.equal(ui.api.Q.draft,'保留待提问内容');assert.deepEqual(clone(ui.api.Q.current.book_codes),[]);
  assert.match(ui.host.innerHTML,/value="I" selected/);assert.match(ui.host.innerHTML,/1 本图书可检索/);
  assert.match(ui.host.innerHTML,/新入库同类图书自动纳入/);
  await ui.api.ask('解释人物关系');
  const request=ui.calls.find(x=>x.url==='/api/qa/ask');assert.equal(request.body.clc_code,'I');assert.deepEqual(request.body.book_codes,[]);
  const previous=ui.api.Q.current.id;ui.api.changeCategory('C');
  assert.notEqual(ui.api.Q.current.id,previous);assert.equal(ui.api.Q.current.turns.length,0);
  assert.ok(ui.api.Q.sessions.some(s=>s.id===previous&&s.clc_code==='I'));
});

test('empty classification never sends an all-library question; new matching books are included',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  ui.api.changeCategory('I');
  await ui.api.ask('查找原文');assert.equal(ui.calls.filter(x=>x.url==='/api/qa/ask').length,0);
  assert.match(ui.host.innerHTML,/暂无可提问图书/);
  ui.responses.status.books.push({code:'B03',title:'新文学书',segments:5,clc_code:'I'});
  ui.responses.status.classifications=[{code:'I',name:'文学',book_count:1}];
  await ui.api.render(ui.view);assert.match(ui.host.innerHTML,/1 本图书可检索/);
  await ui.api.ask('查找原文');const req=ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1);
  assert.equal(req.body.clc_code,'I');assert.deepEqual(req.body.book_codes,[]);
});


test('retrieval-only stays hidden, keeps the question editable, and supports retry in place',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  ui.responses.answer={...result,answer:'',mode:'sources_only',notice:'回答尚未完成，请稍后重试。'};
  await ui.api.ask('东北有什么植物可以学习');
  assert.doesNotMatch(ui.host.innerHTML,/尚未生成答案|重新生成回答|修改问题|查看找到的|qa-turn\"/);
  assert.equal(ui.api.Q.draft,'东北有什么植物可以学习');
  assert.doesNotMatch(ui.host.innerHTML,/复制回答|本次引用|class="qa-evidence"|让每一个问题/);
  assert.equal(ui.nodes['.qa-live'].textContent,'');
  const id=ui.api.Q.current.turns[0].id;ui.responses.answer=result;
  await ui.api.ask('东北有什么植物可以学习',id);
  assert.equal(ui.api.Q.current.turns.length,1);assert.match(ui.host.innerHTML,/复制回答/);
});

test('retrieval-only turns never become assistant history for the next answer',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  ui.responses.answer={...result,answer:'',mode:'sources_only'};await ui.api.ask('未完成的问题');
  ui.responses.answer=result;await ui.api.ask('重新问一个具体问题');
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[{role:'user',content:'未完成的问题'}]);
});


test('hidden incomplete results remain editable after restoring history',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  ui.responses.answer={...result,answer:'',mode:'sources_only',retryable:false,notice:'请改问具体概念。'};
  await ui.api.ask('列出全部内容');
  assert.doesNotMatch(ui.host.innerHTML,/重新生成回答|复制回答|修改问题|尚未生成答案/);assert.equal(ui.api.Q.draft,'列出全部内容');
  const restored=setup({storage:ui.storage});await restored.api.render(restored.view);
  assert.doesNotMatch(restored.host.innerHTML,/重新生成回答|尚未生成答案|请改问具体概念/);assert.equal(restored.api.Q.draft,'列出全部内容');
});

test('resubmitting the latest incomplete question reuses its turn and excludes it from history',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('先介绍这些植物');
  ui.responses.answer={...result,answer:'',mode:'sources_only',retryable:false};
  await ui.api.ask('东北哪里有地钱');const id=ui.api.Q.current.turns.at(-1).id;
  ui.responses.answer=result;await ui.api.ask('  东北哪里有地钱  ');
  assert.equal(ui.api.Q.current.turns.length,2);assert.equal(ui.api.Q.current.turns.at(-1).id,id);
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[{role:'user',content:'先介绍这些植物'},{role:'assistant',content:result.answer}]);
  await ui.api.ask('东北哪里有地钱');assert.equal(ui.api.Q.current.turns.length,3);
  const requests=ui.calls.length;await ui.api.ask('无效重试','missing');assert.equal(ui.calls.length,requests);assert.equal(ui.api.Q.current.turns.length,3);
});

test('starting a new topic preserves earlier sessions but sends no previous conversational context',async()=>{
  const ui=setup();await ui.api.render(ui.view);ui.api.Q.current.book_codes=['B01'];await ui.api.ask('旧话题');
  const id=ui.api.Q.current.id;assert.equal((ui.host.innerHTML.match(/data-qa-action="new"/g)||[]).length,2);
  ui.listeners.click({target:{closest:()=>({dataset:{qaAction:'new'}})}});
  assert.notEqual(ui.api.Q.current.id,id);assert.equal(ui.api.Q.current.turns.length,0);assert.equal(ui.api.Q.sessions.find(s=>s.id===id).turns[0].question,'旧话题');
  await ui.api.ask('新的独立话题');assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[]);
  const saved=JSON.parse([...ui.storage.values()][0]);assert.equal(saved.sessions.length,2);
});

test('earlier turns collapse by default and user expansion survives a redraw',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('第一个问题');await ui.api.ask('接下来呢');
  const id=ui.api.Q.current.turns[0].id;
  assert.match(ui.host.innerHTML,new RegExp('data-qa-previous="'+id+'"><summary>'));
  assert.doesNotMatch(ui.host.innerHTML,new RegExp('data-qa-previous="'+ui.api.Q.current.turns[1].id+'"'));
  ui.listeners.toggle({target:{matches:()=>true,dataset:{qaPrevious:id},open:true}});ui.api.draw();
  assert.match(ui.host.innerHTML,new RegExp('data-qa-previous="'+id+'" open>'));
});


test('hidden network errors keep their user question in follow-up context without an assistant answer',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('东北有什么植物');
  ui.responses.answer=()=>Promise.reject(new Error('服务错误'));await ui.api.ask('地钱在什么地方');
  assert.doesNotMatch(ui.host.innerHTML,/服务错误|本次回答未完成/);
  ui.responses.answer=result;await ui.api.ask('具体城市呢');
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[{role:'user',content:'东北有什么植物'},{role:'assistant',content:result.answer},{role:'user',content:'地钱在什么地方'}]);
});

test('several hidden attempts retain the last successful exchange as context',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('先介绍地钱');
  ui.responses.answer={...result,answer:'',mode:'insufficient',notice:'依据不足'};
  for(let i=0;i<5;i++)await ui.api.ask('追问 '+i);
  assert.doesNotMatch(ui.host.innerHTML,/未完成|依据不足|尚未生成答案|qa-previous-turn/);
  assert.equal((ui.host.innerHTML.match(/class="qa-turn"/g)||[]).length,1);
  ui.responses.answer=result;await ui.api.ask('它适合在哪里观察');
  const history=ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history;
  assert.equal(history[0].content,'先介绍地钱');assert.equal(history[1].content,result.answer);
  assert.deepEqual(history.slice(2).map(h=>h.role),['user','user','user','user']);
  assert.equal(history.at(-1).content,'追问 4');
});

test('interrupted stored requests restore quietly and remain in follow-up context',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('地钱的分布');
  const [key]=ui.storage.keys(),saved=JSON.parse(ui.storage.get(key));saved.sessions[0].turns[0].status='pending';ui.storage.set(key,JSON.stringify(saved));
  const restored=setup({storage:ui.storage});await restored.api.render(restored.view);
  assert.doesNotMatch(restored.host.innerHTML,/尚未取得结果|未完成|qa-turn"/);
  assert.equal(restored.api.Q.draft,'地钱的分布');await restored.api.ask('那具体呢');
  assert.deepEqual(restored.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[{role:'user',content:'地钱的分布'}]);
});

test('deleting a turn requires confirmation and cancellation preserves all records',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('第一个问题');await ui.api.ask('保留的后续问题');
  const current=clone(ui.api.Q.current),stored=[...ui.storage.entries()],id=current.turns[0].id;
  assert.match(ui.host.innerHTML,/data-qa-action="deleteTurn"/);
  assert.match(ui.host.innerHTML,/data-qa-action="deleteSession"/);
  let prevented=false;
  ui.listeners.click({target:{closest:()=>({dataset:{qaAction:'deleteTurn',turn:id}})},preventDefault(){prevented=true;}});
  assert.equal(prevented,true,'a delete action in a collapsed summary must not toggle the details');
  assert.equal(ui.nodes.dialog.open,true);assert.equal(ui.api.Q.deletion.turnId,id);
  assert.equal(ui.api.Q.deletion.sessionId,current.id);
  assert.deepEqual(clone(ui.api.Q.current),current);assert.deepEqual([...ui.storage.entries()],stored);
  ui.api.cancelDelete();
  assert.equal(ui.api.Q.deletion,null);assert.equal(ui.nodes.dialog.open,false);
  assert.deepEqual(clone(ui.api.Q.current),current);assert.deepEqual([...ui.storage.entries()],stored);
  ui.api.openDelete('turn',id);ui.nodes.dialog.oncancel();
  assert.equal(ui.api.Q.deletion,null);assert.equal(ui.api.confirmDelete(),false);
  assert.deepEqual(clone(ui.api.Q.current),current);assert.deepEqual([...ui.storage.entries()],stored);
});

test('confirmed turn deletion removes its answer and evidence, renumbers the view, and excludes it from future context and reloads',async()=>{
  const ui=setup();await ui.api.render(ui.view);
  ui.responses.answer={...clone(result),answer:'将删除的独有回答。[1]',sources:[{...result.sources[0],quote:'将删除的独有原文。'}]};
  await ui.api.ask('将删除的第一个问题');
  ui.responses.answer={...clone(result),answer:'应保留的后续回答。[1]'};await ui.api.ask('保留的后续问题');
  const removed=ui.api.Q.current.turns[0].id,retained=ui.api.Q.current.turns[1].id;
  ui.api.Q.selectedTurn=removed;ui.api.Q.selectedSource=1;ui.api.Q.expandedTurns=[removed,retained];
  ui.api.openDelete('turn',removed);await ui.api.confirmDelete();
  assert.equal(ui.api.Q.deletion,null);assert.equal(ui.api.Q.current.turns.length,1);
  assert.equal(ui.api.Q.current.turns[0].id,retained);assert.equal(ui.api.Q.current.title,'保留的后续问题');
  assert.notEqual(ui.api.Q.selectedTurn,removed);assert.equal(ui.api.Q.selectedSource,null);
  assert.ok(!ui.api.Q.expandedTurns.includes(removed));
  assert.match(ui.host.innerHTML,/qa-question-number">01</);assert.doesNotMatch(ui.host.innerHTML,/qa-question-number">02</);
  assert.doesNotMatch(ui.host.innerHTML,/将删除的第一个问题|将删除的独有回答/);
  assert.doesNotMatch([...ui.storage.values()].join(''),/将删除的第一个问题|将删除的独有回答|将删除的独有原文/);
  const restored=setup({storage:ui.storage});await restored.api.render(restored.view);
  assert.equal(restored.api.Q.current.turns.length,1);assert.equal(restored.api.Q.current.turns[0].id,retained);
  assert.doesNotMatch(restored.host.innerHTML,/将删除的/);
  await ui.api.ask('接着讨论保留的问题');
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[
    {role:'user',content:'保留的后续问题'},{role:'assistant',content:'应保留的后续回答。[1]'}]);
});

test('deleting the last turn removes the session and opens an empty topic with the same book scope and category',async()=>{
  const scoped=clone(status);scoped.books[0].clc_code='I';scoped.classifications=[{code:'I',name:'文学',book_count:1}];
  const ui=setup({status:scoped});await ui.api.render(ui.view);
  ui.api.Q.current.book_codes=['B01'];ui.api.Q.current.clc_code='I';await ui.api.ask('唯一的问题');
  const sessionId=ui.api.Q.current.id,turnId=ui.api.Q.current.turns[0].id;
  ui.api.openDelete('turn',turnId);await ui.api.confirmDelete();
  assert.notEqual(ui.api.Q.current.id,sessionId);assert.equal(ui.api.Q.current.turns.length,0);
  assert.deepEqual(clone(ui.api.Q.current.book_codes),['B01']);assert.equal(ui.api.Q.current.clc_code,'I');
  assert.ok(!ui.api.Q.sessions.some(s=>s.id===sessionId));assert.equal(ui.api.Q.draft,'');
  assert.equal(ui.api.Q.selectedTurn,'');assert.equal(ui.api.Q.selectedSource,null);assert.deepEqual(clone(ui.api.Q.expandedTurns),[]);
  assert.match(ui.host.innerHTML,/让每一个问题/);assert.doesNotMatch(ui.host.innerHTML,/唯一的问题/);
  const restored=setup({storage:ui.storage,status:scoped});await restored.api.render(restored.view);
  assert.equal(restored.api.Q.current.turns.length,0);assert.ok(!restored.api.Q.sessions.some(s=>s.id===sessionId));
});

test('deleting the current session keeps other sessions and resets follow-up context',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('另一段应保留的对话');const older=ui.api.Q.current.id;
  ui.listeners.click({target:{closest:()=>({dataset:{qaAction:'new'}})}});
  await ui.api.ask('准备删除的当前对话');const removed=ui.api.Q.current.id;
  ui.api.openDelete('session',removed);await ui.api.confirmDelete();
  assert.notEqual(ui.api.Q.current.id,removed);assert.equal(ui.api.Q.current.turns.length,0);
  assert.equal(ui.api.Q.sessions.find(s=>s.id===older).turns[0].question,'另一段应保留的对话');
  assert.ok(!ui.api.Q.sessions.some(s=>s.id===removed));assert.equal(ui.api.Q.deletion,null);
  assert.doesNotMatch([...ui.storage.values()].join(''),/准备删除的当前对话/);
  await ui.api.ask('一个新的独立问题');
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[]);
  const restored=setup({storage:ui.storage});await restored.api.render(restored.view);
  assert.ok(restored.api.Q.sessions.some(s=>s.id===older));assert.ok(!restored.api.Q.sessions.some(s=>s.id===removed));
});

test('deleting another session from history preserves the current draft and returns to the updated list',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('准备删除的旧对话');const removed=ui.api.Q.current.id;
  ui.listeners.click({target:{closest:()=>({dataset:{qaAction:'new'}})}});
  await ui.api.ask('继续保留的当前对话');const current=clone(ui.api.Q.current);ui.api.Q.draft='还没有发送的草稿';
  ui.api.Q.selectedTurn=current.turns[0].id;ui.api.Q.selectedSource=1;ui.api.Q.expandedTurns=[current.turns[0].id];
  ui.api.openHistory();assert.match(ui.nodes.dialog.innerHTML,/data-qa-action="deleteSession"/);
  ui.listeners.click({target:{closest:()=>({dataset:{qaAction:'deleteSession',id:removed,history:'true'}})},preventDefault(){}});
  assert.equal(ui.api.Q.deletion.fromHistory,true);ui.api.cancelDelete();
  assert.equal(ui.nodes.dialog.open,true);assert.match(ui.nodes.dialog.innerHTML,/历史对话/);
  assert.ok(ui.api.Q.sessions.some(s=>s.id===removed));assert.equal(ui.api.Q.draft,'还没有发送的草稿');
  ui.api.openDelete('session',removed,true);await ui.api.confirmDelete();
  assert.deepEqual(clone(ui.api.Q.current),current);assert.equal(ui.api.Q.draft,'还没有发送的草稿');
  assert.equal(ui.api.Q.selectedTurn,current.turns[0].id);assert.equal(ui.api.Q.selectedSource,1);
  assert.deepEqual(clone(ui.api.Q.expandedTurns),[current.turns[0].id]);
  assert.ok(!ui.api.Q.sessions.some(s=>s.id===removed));assert.equal(ui.api.Q.deletion,null);
  assert.equal(ui.nodes.dialog.open,true);assert.match(ui.nodes.dialog.innerHTML,/历史对话|继续保留的当前对话/);
  assert.doesNotMatch(ui.nodes.dialog.innerHTML,/准备删除的旧对话/);
  const restored=setup({storage:ui.storage});await restored.api.render(restored.view);
  assert.equal(restored.api.Q.current.id,current.id);assert.ok(!restored.api.Q.sessions.some(s=>s.id===removed));
});

test('deleting the last visible answer retains hidden user context until the whole session is deleted',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('已得到回答的问题');
  const sessionId=ui.api.Q.current.id,answeredId=ui.api.Q.current.turns[0].id;
  ui.responses.answer={...result,answer:'',mode:'sources_only',notice:'不显示的失败提示'};
  await ui.api.ask('仍需保留上下文的未完成问题');const hiddenId=ui.api.Q.current.turns[1].id;
  ui.api.openDelete('turn',answeredId);await ui.api.confirmDelete();
  assert.equal(ui.api.Q.current.id,sessionId);assert.equal(ui.api.Q.current.turns.length,1);
  assert.equal(ui.api.Q.current.turns[0].id,hiddenId);assert.equal(ui.api.Q.current.title,'仍需保留上下文的未完成问题');
  assert.doesNotMatch(ui.host.innerHTML,/不显示的失败提示|已得到回答的问题/);
  ui.responses.answer=result;await ui.api.ask('那具体呢');
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[{role:'user',content:'仍需保留上下文的未完成问题'}]);
  ui.api.openDelete('session',sessionId);await ui.api.confirmDelete();
  assert.ok(!ui.api.Q.sessions.some(s=>s.id===sessionId));
  assert.doesNotMatch([...ui.storage.values()].join(''),/仍需保留上下文的未完成问题/);
  await ui.api.ask('新的独立问题');
  assert.deepEqual(ui.calls.filter(x=>x.url==='/api/qa/ask').at(-1).body.history,[]);
});

test('deleting a turn does not make the recently edited session the next capacity-eviction victim',async()=>{
  const ui=setup();await ui.api.render(ui.view);await ui.api.ask('最早的历史对话');const oldest=ui.api.Q.current.id;
  for(let i=1;i<30;i++){
    ui.listeners.click({target:{closest:()=>({dataset:{qaAction:'new'}})}});
    await ui.api.ask('历史话题 '+i);
  }
  const recent=ui.api.Q.current.id,removed=ui.api.Q.current.turns[0].id;
  await ui.api.ask('最近会话中需要保留的补充问题');
  assert.equal(ui.api.Q.sessions.length,30);
  ui.api.openDelete('turn',removed);await ui.api.confirmDelete();
  ui.listeners.click({target:{closest:()=>({dataset:{qaAction:'new'}})}});await ui.api.ask('第三十一个新话题');
  assert.equal(ui.api.Q.sessions.length,30);
  assert.ok(ui.api.Q.sessions.some(s=>s.id===recent),'deleting one turn must not discard the rest of the recent session at the next new topic');
  assert.ok(!ui.api.Q.sessions.some(s=>s.id===oldest));
  const saved=JSON.parse([...ui.storage.values()][0]);
  assert.equal(saved.sessions.find(s=>s.id===recent).turns[0].question,'最近会话中需要保留的补充问题');
});

test('pending requests reject both opening deletion and confirming an already opened deletion',async()=>{
  const ui=setup(),pending=deferred();await ui.api.render(ui.view);await ui.api.ask('已经完成的问题');
  const target=ui.api.Q.current.turns[0].id;ui.api.openDelete('turn',target);const staleTarget=clone(ui.api.Q.deletion);
  ui.responses.answer=()=>pending.promise;const work=ui.api.ask('正在生成的问题');
  // Simulate a stale confirmation callback after redraw: the busy guard must work even with a target.
  ui.api.Q.deletion=staleTarget;
  assert.equal(await ui.api.confirmDelete(),false);
  assert.equal(ui.api.Q.current.turns.length,2);assert.ok(ui.api.Q.current.turns.some(t=>t.id===target));
  ui.api.cancelDelete();ui.api.openDelete('session',ui.api.Q.current.id);
  assert.equal(ui.api.Q.deletion,null);assert.equal(ui.api.Q.current.turns.length,2);
  pending.resolve(result);await work;
  assert.equal(ui.api.Q.current.turns.length,2);assert.ok(ui.api.Q.current.turns.every(t=>t.status==='done'));
});

test('storage failures preserve turns and sessions without claiming deletion, and allow a successful retry',async()=>{
  for(const {kind,count:turnCount} of [{kind:'turn',count:2},{kind:'turn',count:1},{kind:'session',count:2}]){
    const options={},ui=setup(options);await ui.api.render(ui.view);
    for(let i=0;i<turnCount;i++)await ui.api.ask('必须保留的问题 '+i);
    const target=kind==='turn'?ui.api.Q.current.turns[0].id:ui.api.Q.current.id;
    ui.api.Q.selectedTurn=ui.api.Q.current.turns[0].id;ui.api.Q.selectedSource=1;
    ui.api.Q.expandedTurns=[ui.api.Q.current.turns[0].id];ui.api.Q.draft='保留未发送草稿';
    const current=clone(ui.api.Q.current),sessions=clone(ui.api.Q.sessions),stored=[...ui.storage.entries()],notices=[...ui.notifications];
    const selected={turn:ui.api.Q.selectedTurn,source:ui.api.Q.selectedSource,expanded:clone(ui.api.Q.expandedTurns)};
    ui.api.openDelete(kind,target);options.quota=true;await ui.api.confirmDelete();
    assert.deepEqual(clone(ui.api.Q.current),current);assert.deepEqual(clone(ui.api.Q.sessions),sessions);
    assert.equal(ui.api.Q.current,ui.api.Q.sessions.find(s=>s.id===current.id),'rollback must retain the live session object used by future asks');
    assert.deepEqual([...ui.storage.entries()],stored);assert.equal(ui.api.Q.draft,'保留未发送草稿');
    assert.equal(ui.api.Q.selectedTurn,selected.turn);assert.equal(ui.api.Q.selectedSource,selected.source);
    assert.deepEqual(clone(ui.api.Q.expandedTurns),selected.expanded);
    assert.ok(ui.api.Q.deletion);assert.equal(ui.nodes.dialog.open,true);
    assert.match(ui.nodes['.qa-delete-error'].textContent,/未能保存删除操作，记录已保留/);
    assert.match(ui.nodes['.qa-live'].textContent,/记录已保留/);
    assert.deepEqual(ui.notifications,notices);
    const restored=setup({storage:ui.storage});await restored.api.render(restored.view);
    assert.equal(restored.api.Q.current.id,current.id);assert.equal(restored.api.Q.current.turns.length,turnCount);
    options.quota=false;await ui.api.confirmDelete();
    assert.equal(ui.api.Q.deletion,null);
    if(kind==='session'||turnCount===1)assert.ok(!ui.api.Q.sessions.some(s=>s.id===current.id));
    else assert.equal(ui.api.Q.current.turns.length,turnCount-1);
  }
});

test('late clipboard results after deleting a turn or session or leaving the page cannot reopen deleted content or announce success',async()=>{
  for(const change of ['turn','session','page'])for(const outcome of ['resolve','reject']){
    const clipboard=deferred(),ui=setup({clipboardWait:clipboard.promise});await ui.api.render(ui.view);
    await ui.api.ask('复制期间可能删除的问题');const turnId=ui.api.Q.current.turns[0].id,sessionId=ui.api.Q.current.id;
    await ui.api.ask('继续保留的其他问题');
    const copying=ui.api.copyAnswer(turnId);assert.equal(ui.copied.length,0);
    if(change==='page'){
      ui.context.location.hash='#/content';ui.host.isConnected=false;ui.host.innerHTML='当前已切换至其他页面';
    }else{
      ui.api.openDelete(change,change==='turn'?turnId:sessionId);assert.equal(await ui.api.confirmDelete(),true);
      if(change==='turn')assert.equal(ui.api.Q.current.id,sessionId,'exercise deletion while the same session remains active');
    }
    const before={html:ui.host.innerHTML,dialog:ui.nodes.dialog.innerHTML,open:ui.nodes.dialog.open,
      className:ui.nodes.dialog.className,live:ui.nodes['.qa-live'].textContent,notifications:[...ui.notifications]};
    if(outcome==='reject')clipboard.reject(new Error('delayed clipboard denial'));else clipboard.resolve();
    await copying;
    assert.equal(ui.host.innerHTML,before.html,change+' / '+outcome);
    assert.equal(ui.nodes.dialog.innerHTML,before.dialog);assert.equal(ui.nodes.dialog.open,before.open);
    assert.equal(ui.nodes.dialog.className,before.className);assert.doesNotMatch(ui.nodes.dialog.className,/qa-dialog-copy/);
    assert.equal(ui.nodes['.qa-live'].textContent,before.live);assert.deepEqual(ui.notifications,before.notifications);
    assert.ok(!ui.notifications.some(message=>String(message).includes('回答与出处已复制')));
  }
});
