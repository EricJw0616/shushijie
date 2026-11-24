import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const clone=value=>JSON.parse(JSON.stringify(value));
function setup(storage=new Map()){
  let opened=false,html='',renderer,project={id:'prj-example',revision:8,draft:'用户刚刚修改并保存的口播稿。',brief:{audience:'11—14 岁读者',writing_notes:'纸艺风格'}},run={id:'assist-example',capability:'video_prompts',status:'done',stale:false,snapshot:{presentation_mode:'image',title:'古桥与城市生活'},result:{video_prompts:{presentation_mode:'image',audience:'11—14 岁读者',visual_style:'纸艺',shots:[{number:1,title:'开场',source_text:'用户刚刚修改并保存的口播稿。',prompt:'面向 11—14 岁读者，纸艺风格，竖版画幅，完整的一张图提示词。'}]}}};
  const posted=[],copied=[],toasts=[],gets=[],fetches=[],downloads=[],blobs=[],views=[null],registrations={},windowEvents={},timers=[];let cursor=0,listed=null;
  const restore=()=>{opened=cursor>0;renderer=views[cursor]?.render;html=opened?renderer():'';};
  const back=()=>{cursor=Math.max(0,cursor-1);restore();};
  const forward=()=>{cursor=Math.min(views.length-1,cursor+1);restore();};
  const host={focus(){},get outerHTML(){return html;},set outerHTML(value){html=value;}};
  const context={Blob,fetch:async(path,options)=>{fetches.push({path,options});return new Response('%PDF-1.7\nUI transfer fixture',{headers:{'Content-Type':'application/pdf','Content-Disposition':"attachment; filename*=UTF-8''"+encodeURIComponent((run.stale?'旧版-':'')+(run.snapshot.title||'未命名项目')+'_'+(run.result.video_prompts.presentation_mode==='video'?'视频':'图片')+'制作包.pdf')}});},URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:mock';},revokeObjectURL(){}},window:{addEventListener:(name,handler)=>{windowEvents[name]=handler;},MarketingOverlay:{register:(type,handler)=>{registrations[type]=handler;}}},sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)},document:{body:{appendChild(){}},createElement:()=>({remove(){},click(){downloads.push({name:this.download,blob:blobs.at(-1)});}}),getElementById:id=>id==='videoPromptsDialog'&&opened?host:null,addEventListener(){}},location:{hash:'#/campaigns/prj-example/results'},esc:value=>String(value).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])),ManuscriptReader:{build:value=>({html:value})},setTimeout:(callback,delay)=>{if(delay===0)queueMicrotask(callback);else timers.push({callback,delay});return timers.length;},clearTimeout(){},openModal:(render,wide,options={})=>{const frame={render,options};if(options.restore&&cursor===0){views.push(frame);cursor++;}else if(!opened||options.step){views.splice(cursor+1);views.push(frame);cursor++;}else views[cursor]=frame;restore();},closeModal:(toRoot=true)=>{cursor=toRoot?0:Math.max(0,cursor-1);restore();},toast:(message,bad)=>toasts.push({message,bad}),Studio:{assistContext:async()=>clone(project)},ProjectAssist:{retry(){}},navigator:{clipboard:{writeText:async text=>{copied.push(text);}}},FormData:class{constructor(form){this.form=form;}get(name){return this.form[name];}},post:async(path,payload)=>{posted.push({path,payload:clone(payload)});return {run:clone(run)};},jget:async path=>{gets.push(path);if(path.endsWith('/assist'))return {runs:clone(listed||[run])};if(path.includes('/assist/'))return {run:clone((listed||[run]).find(x=>path.endsWith('/'+x.id))||run)};return {project:clone(project)};}};
  runInNewContext(readFileSync(new URL('../static/video-prompts.js',import.meta.url),'utf8'),context);
  return {ui:context.window.VideoPrompts,context,posted,copied,toasts,gets,fetches,downloads,storage,registrations,windowEvents,timers,renderCurrent:restore,cursor:()=>cursor,descriptor:()=>views[cursor]?.options.descriptor,setRuns:rows=>{listed=rows;},project:()=>project,setProject:p=>{project=p;},run:()=>run,setRun:r=>{run=r;},html:()=>html,opened:()=>opened,back,forward,form:mode=>({presentation_mode:mode,querySelector:()=>({disabled:false,textContent:''})})};
}

test('confirmation selects exactly one presentation and submits the current saved outline verbatim',async()=>{
  const app=setup();await app.ui.open();
  assert.match(app.html(),/图片展示/);assert.match(app.html(),/视频展示/);assert.doesNotMatch(app.html(),/value="both"|生图提示词|生视频提示词/);
  await app.ui.generate(app.form('image'));
  assert.equal(app.posted.length,1);
  assert.deepEqual(app.posted[0],{path:'/api/projects/prj-example/assist',payload:{capability:'video_prompts',revision:8,confirmed:true,confirmed_draft:app.project().draft,presentation_mode:'image'}});
  assert.match(app.html(),/图片展示提示词/);assert.match(app.html(),/第 1 张/);assert.doesNotMatch(app.html(),/第 1 镜|应用到|生成图片/);
  await app.ui.copy({dataset:{shot:'0'},disabled:false});assert.deepEqual(app.copied,[app.run().result.video_prompts.shots[0].prompt]);
});

test('video presentation shows only video prompts and copy keeps the complete supplied context',async()=>{
  const app=setup(),run=app.run();run.snapshot.presentation_mode='video';run.result.video_prompts.presentation_mode='video';run.result.video_prompts.shots[0].prompt='面向中学生，纸艺风格，固定 9:16；缓慢推近 6 秒，再衔接下一镜。';app.setRun(run);
  await app.ui.open();await app.ui.generate(app.form('video'));
  assert.equal(app.posted[0].payload.presentation_mode,'video');assert.match(app.html(),/第 1 镜/);assert.doesNotMatch(app.html(),/第 1 张|生图提示词/);
  await app.ui.copy({dataset:{shot:'0'},disabled:false});assert.equal(app.copied[0],run.result.video_prompts.shots[0].prompt);
});

test('changing the outline or brief after opening confirmation prevents generating an older draft',async()=>{
  for(const kind of ['draft','brief']){
    const app=setup();await app.ui.open();const current=app.project();
    if(kind==='draft')current.draft='打开确认后又修改的口播稿';else current.brief={...current.brief,audience:'成年观众'};
    app.setProject(current);await app.ui.generate(app.form('image'));
    assert.equal(app.posted.length,0);assert.match(app.html(),/已经变化，请返回口播稿重新确认/);
  }
});

test('newly stale results are identified before copying, then can only be copied as visibly old prompts',async()=>{
  const app=setup();await app.ui.open();await app.ui.generate(app.form('image'));
  app.setRun({...app.run(),stale:true});await app.ui.copy({dataset:{shot:'0'},disabled:false});
  assert.equal(app.copied.length,0);assert.match(app.html(),/下面是旧版提示词/);assert.match(app.html(),/复制旧版提示词/);
  await app.ui.copy({dataset:{shot:'0'},disabled:false});assert.equal(app.copied.length,1);
  assert.equal(app.toasts.at(-1).message,'已复制旧版提示词');
});

test('returning closes the panel and existing records recover pending work without replacing the outline',async()=>{
  const app=setup();app.setRun({...app.run(),status:'running',result:null});
  await app.ui.open();await app.ui.generate(app.form('image'));assert.match(app.html(),/稍后从「查看提示词」继续/);
  app.ui.close();assert.equal(app.opened(),false);
  await app.ui.showRecords();for(let i=0;i<6;i++)await Promise.resolve();assert.match(app.html(),/已有提示词记录/);assert.match(app.html(),/生成中/);
  await app.ui.openRun({dataset:{run:'assist-example'}});assert.match(app.html(),/正在根据已确认的口播稿/);
  assert.equal(app.project().draft,'用户刚刚修改并保存的口播稿。');
  assert.ok(app.posted.every(x=>x.payload.capability==='video_prompts'));
});

test('a request finishing after leaving the project cannot reopen or replace another screen',async()=>{
  const app=setup();let complete;
  app.context.post=async(path,payload)=>new Promise(resolve=>{complete=resolve;});
  await app.ui.open();const pending=app.ui.generate(app.form('image'));for(let i=0;i<8&&!complete;i++)await Promise.resolve();assert.equal(typeof complete,'function');
  app.ui.close();app.context.location.hash='#/campaigns/another/results';complete({run:app.run()});await pending;
  assert.equal(app.opened(),false);assert.equal(app.copied.length,0);
});

test('browser forward restores a panel closed by its return button and its copy controls work',async()=>{
  const app=setup();await app.ui.open();await app.ui.generate(app.form('image'));app.ui.close();
  app.forward();for(let i=0;i<6;i++)await Promise.resolve();assert.match(app.html(),/data-stage="choose"/);app.forward();for(let i=0;i<6;i++)await Promise.resolve();
  await app.ui.copy({dataset:{shot:'0'},disabled:false});assert.equal(app.copied.length,1);
});

test('browser forward after a direct back resumes a pending result and fetches its completion',async()=>{
  const app=setup(),done=clone(app.run());app.setRun({...done,status:'running',result:null});
  await app.ui.open();await app.ui.generate(app.form('image'));app.back();app.setRun(done);
  const previous=app.gets.length;app.forward();for(let i=0;i<6;i++)await Promise.resolve();
  assert.ok(app.gets.length>previous);assert.match(app.html(),/复制提示词/);assert.doesNotMatch(app.html(),/正在根据已确认的口播稿/);
});

test('image labels omit video timing and corresponding narration excludes production instructions',async()=>{
  const app=setup(),run=app.run();
  run.result.video_prompts.shots[0].title='镜头 01 · 0–6 秒';
  run.result.video_prompts.shots[0].source_text='**画面：** 不应被当成口播的画面要求。\n\n**口播：** 实际口播第一句。\n实际口播第二句。\n\n**剪辑：** 不应被当成口播的剪辑安排。';
  app.setRun(run);await app.ui.open();await app.ui.generate(app.form('image'));
  assert.match(app.html(),/<summary>第 1 张<\/summary>/);assert.doesNotMatch(app.html(),/0–6 秒|不应被当成口播/);
  assert.match(app.html(),/<summary>对应口播<\/summary>/);assert.match(app.html(),/实际口播第一句[\s\S]*实际口播第二句/);
});

test('new narration-based results show replanned timing only for video',async()=>{
  for(const mode of ['image','video']){
    const app=setup(),run=app.run();run.snapshot.presentation_mode=mode;run.result.video_prompts.presentation_mode=mode;
    run.result.video_prompts.shots[0].title='第 1 段';
    run.result.video_prompts.shots[0].production_timing={global_start_seconds:6.5,global_end_seconds:15};
    app.setRun(run);await app.ui.open();await app.ui.generate(app.form(mode));
    assert.doesNotMatch(app.html(),/第 1 段/);
    if(mode==='video')assert.match(app.html(),/<summary>第 1 镜 · 全片 6\.5–15 秒<\/summary>/);
    else{assert.match(app.html(),/<summary>第 1 张<\/summary>/);assert.doesNotMatch(app.html(),/6\.5–15/);}
  }
});

test('optional overlay wording is separate from the generation prompt and missing legacy wording stays hidden',async()=>{
  const app=setup();await app.ui.open();await app.ui.generate(app.form('image'));assert.doesNotMatch(app.html(),/后期文字/);
  const run=app.run();run.result.video_prompts.shots[0].overlay_text='石头缝里的绿色 <script>';app.setRun(run);
  await app.ui.showRecords();for(let i=0;i<6;i++)await Promise.resolve();await app.ui.openRun({dataset:{run:run.id}});
  assert.match(app.html(),/后期文字：/);assert.match(app.html(),/石头缝里的绿色 &lt;script&gt;/);
  await app.ui.copy({dataset:{shot:'0'},disabled:false});assert.equal(app.copied.at(-1),run.result.video_prompts.shots[0].prompt);
});

test('handoff keeps exact Markdown copying while downloading PDF as its primary package',async()=>{
  const app=setup(),run=app.run();run.markdown='# 图片制作包\n\n完整口播只出现一次。\n\n逐张提示词。';
  const ref={id:'ref-a',name:'桥梁侧面参考图',requirement:'提供整座桥的侧面照片，保留拱形结构。',status:'required',shot_numbers:[1]};
  run.result.video_prompts.required_inputs=[ref,clone(ref)];run.result.video_prompts.shots[0].reference_requirements=ref.requirement;app.setRun(run);
  await app.ui.open();await app.ui.generate(app.form('image'));assert.match(app.html(),/制作这张图需要的参考图/);assert.match(app.html(),/准备制作/);assert.doesNotMatch(app.html(),/data-video-download/);
  await app.ui.prepareProduction({disabled:false});assert.match(app.html(),/图片展示 · 准备制作/);assert.match(app.html(),/用于第 1 张/);assert.doesNotMatch(app.html(),/待提供或确认/);
  assert.equal((app.html().match(/桥梁侧面参考图/g)||[]).length,1);assert.match(app.html(),/返回提示词/);
  app.setRun({...run,markdown:run.markdown+'\n\n已修订的制作说明。'});
  await app.ui.copyAll({disabled:false});assert.equal(app.copied.at(-1),app.run().markdown);
  await app.ui.download({disabled:false});assert.equal(app.downloads.length,1);assert.equal(app.downloads[0].name,'古桥与城市生活_图片制作包.pdf');assert.match(await app.downloads[0].blob.text(),/^%PDF-/);assert.match(app.html(),/下载制作包 PDF/);assert.doesNotMatch(app.html(),/下载整套 Markdown/);assert.equal(app.fetches[0].path,'/api/projects/prj-example/assist/assist-example/download?format=pdf');
  app.ui.backToPrompts();assert.match(app.html(),/data-video-prepare/);assert.doesNotMatch(app.html(),/data-video-download/);
});

test('newly stale package delivery is stopped, while an explicit old-version download has a visible filename',async()=>{
  const app=setup(),run=app.run();run.markdown='# 已确认版本';app.setRun(run);
  await app.ui.open();await app.ui.generate(app.form('image'));await app.ui.prepareProduction({disabled:false});
  app.setRun({...run,stale:true});await app.ui.download({disabled:false});assert.equal(app.downloads.length,0);assert.match(app.html(),/下载旧版制作包/);
  await app.ui.download({disabled:false});assert.equal(app.downloads.length,1);assert.match(app.downloads[0].name,/^旧版-/);
});

test('legacy prompts do not imply references are ready or invent a missing package',async()=>{
  const app=setup();await app.ui.open();await app.ui.generate(app.form('image'));await app.ui.prepareProduction({disabled:false});
  assert.match(app.html(),/未单列参考图/);assert.match(app.html(),/未保存整套文档/);assert.doesNotMatch(app.html(),/data-video-download|素材已齐|上传所列参考图|上传所需参考图/);
});

test('handoff resumes on browser forward and keeps video instructions about one complete narration',async()=>{
  const app=setup(),run=app.run();run.result.video_prompts.presentation_mode='video';run.markdown='# 视频制作包';app.setRun(run);
  await app.ui.open();await app.ui.generate(app.form('video'));await app.ui.prepareProduction({disabled:false});app.back();for(let i=0;i<6;i++)await Promise.resolve();
  assert.match(app.html(),/data-video-prepare/);assert.doesNotMatch(app.html(),/data-video-download/);
  app.forward();for(let i=0;i<6;i++)await Promise.resolve();
  assert.match(app.html(),/视频展示 · 准备制作/);assert.match(app.html(),/完整口播只配音一次/);
  await app.ui.copyAll({disabled:false});assert.equal(app.copied.at(-1),'# 视频制作包');
});


test('returning to narration skips the complete flow while forward follows choose then result then handoff',async()=>{
  const app=setup();app.setRun({...app.run(),markdown:'# 制作包'});await app.ui.open();await app.ui.generate(app.form('image'));await app.ui.prepareProduction({disabled:false});app.ui.close();assert.equal(app.opened(),false);
  app.forward();for(let i=0;i<6;i++)await Promise.resolve();assert.match(app.html(),/data-stage="choose"/);
  app.forward();for(let i=0;i<6;i++)await Promise.resolve();assert.match(app.html(),/data-video-prepare/);assert.doesNotMatch(app.html(),/data-video-download/);
  app.forward();for(let i=0;i<6;i++)await Promise.resolve();assert.match(app.html(),/data-video-download/);
  app.ui.backToPrompts();for(let i=0;i<6;i++)await Promise.resolve();assert.match(app.html(),/data-video-prepare/);assert.doesNotMatch(app.html(),/data-video-download/);
});

const settle=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
function record(base,id,mode,status='done',old=false){const row=clone(base);row.id=id;row.snapshot.presentation_mode=mode;row.result.video_prompts.presentation_mode=mode;row.status=status;row.stale=old;return row;}

test('entry reads every available record without saving or generating, and both presentation modes remain accessible',async()=>{
  const app=setup(),base=app.run();app.setProject({...app.project(),draft:''});
  const rows=[record(base,'current-image','image'),record(base,'pending-video','video','running'),record(base,'old-image','image','done',true),record(base,'failed-video','video','failed')];app.setRuns(rows);
  app.context.Studio.assistContext=()=>{throw Error('history must not save or confirm the current draft');};
  await app.ui.open();assert.equal(app.posted.length,0);assert.match(app.html(),/已有记录/);assert.match(app.html(),/data-run="current-image"/);assert.match(app.html(),/data-run="pending-video"/);assert.match(app.html(),/仍可查看已有记录/);assert.match(app.html(),/type="submit" class="btn primary" disabled/);
  await app.ui.showRecords();await settle();assert.match(app.html(),/data-run="old-image"/);assert.match(app.html(),/旧版 · 已生成/);assert.match(app.html(),/生成中/);assert.match(app.html(),/生成失败/);
  await app.ui.openRun({dataset:{run:'old-image'}});await settle();assert.match(app.html(),/data-run="old-image"/);assert.match(app.html(),/复制旧版提示词/);assert.equal(app.posted.length,0);
});

test('records, selected result and handoff are independent history pages with the same selected run on return',async()=>{
  const app=setup();app.setRun({...app.run(),markdown:'# 制作包'});
  await app.ui.showRecords();const listIndex=app.cursor();await app.ui.openRun({dataset:{run:app.run().id}});await settle();assert.equal(app.cursor(),listIndex+1);
  await app.ui.prepareProduction({disabled:false});assert.equal(app.cursor(),listIndex+2);
  app.back();await settle();assert.match(app.html(),/data-stage="result"/);assert.match(app.html(),/data-run="assist-example"/);
  app.back();await settle();assert.match(app.html(),/data-stage="records"/);assert.doesNotMatch(app.html(),/data-video-prepare|data-video-download/);
  app.forward();await settle();assert.match(app.html(),/data-stage="result"/);app.forward();await settle();assert.match(app.html(),/data-stage="handoff"/);
  assert.equal(app.posted.length,0);
});

test('reentry restores the selected mode or previously viewed run, including an old run, without generating',async()=>{
  const app=setup(),video=record(app.run(),'video-last','video','done',true);app.setRuns([app.run(),video]);
  await app.ui.open();const index=app.cursor();app.ui.selectMode({value:'video'});assert.equal(app.cursor(),index);assert.match(app.html(),/value="video" checked/);app.ui.close();
  await app.ui.open();assert.match(app.html(),/data-stage="choose"/);assert.match(app.html(),/value="video" checked/);
  await app.ui.openRun({dataset:{run:video.id}});app.ui.close();await app.ui.open();assert.match(app.html(),/data-stage="result"/);assert.match(app.html(),/data-run="video-last"/);assert.match(app.html(),/旧版提示词/);
  const reloaded=setup(app.storage);reloaded.setRuns([reloaded.run(),video]);await reloaded.ui.open();assert.match(reloaded.html(),/data-run="video-last"/);assert.equal(reloaded.posted.length,0);assert.equal(app.posted.length,0);
});

test('an explicit generation failure retains the selected mode and reopening does not retry it',async()=>{
  const app=setup();await app.ui.open();app.ui.selectMode({value:'video'});let calls=0;app.context.post=async()=>{calls++;throw Error('temporary generation failure');};
  await app.ui.generate(app.form('video'));assert.match(app.html(),/value="video" checked/);assert.match(app.html(),/temporary generation failure/);assert.doesNotMatch(app.html(),/type="submit" class="btn primary" disabled/);
  app.ui.close();await app.ui.open();assert.equal(calls,1);assert.match(app.html(),/value="video" checked/);
});

test('a serialized handoff descriptor restores from GETs after refresh without saving the draft or generating',async()=>{
  const app=setup();app.setRun({...app.run(),markdown:'# 已有制作包'});await app.ui.showRecords();await app.ui.openRun({dataset:{run:app.run().id}});await app.ui.prepareProduction({disabled:false});
  const descriptor=clone(app.descriptor());assert.deepEqual(descriptor,{type:'video-prompts',projectId:'prj-example',stage:'handoff',runId:'assist-example',mode:'image',parentStage:'result'});assert(!JSON.stringify(descriptor).includes(app.project().draft));
  const fresh=setup();fresh.setProject({...fresh.project(),draft:''});fresh.setRun({...fresh.run(),markdown:'# 已有制作包'});fresh.context.Studio.assistContext=()=>{throw Error('read-only restore expected');};
  await fresh.registrations['video-prompts'](descriptor,{isCurrent:()=>true,options:{restore:true}});await settle();assert.match(fresh.html(),/data-stage="handoff"/);assert.match(fresh.html(),/data-run="assist-example"/);assert.match(fresh.html(),/返回提示词/);assert.equal(fresh.posted.length,0);
  let current=false;const abandoned=setup();await abandoned.registrations['video-prompts'](descriptor,{isCurrent:()=>current,options:{restore:true}});assert.equal(abandoned.opened(),false);
});

test('records and mode remembered for one project are not reused in another project',async()=>{
  const app=setup();await app.ui.open();app.ui.selectMode({value:'video'});await app.ui.openRun({dataset:{run:app.run().id}});app.ui.close();
  app.setProject({...app.project(),id:'prj-another'});app.context.location.hash='#/campaigns/prj-another/results';app.setRuns([]);await app.ui.open();assert.match(app.html(),/data-stage="choose"/);assert.match(app.html(),/value="image" checked/);assert.doesNotMatch(app.html(),/data-run="assist-example"/);assert.equal(app.posted.length,0);
});

test('choosing with an unsaved narration uses the current editor snapshot and saves only on explicit generation',async()=>{
  const app=setup(),stored=clone(app.project());let local={...stored,draft:'用户尚未点保存的最新口播。',brief:{...stored.brief,writing_notes:'水彩风格',purpose:'',book_readers:' 中学生 ',decision_maker:''}},saves=0;
  app.context.Studio.peekAssistContext=()=>clone(local);
  app.context.Studio.assistContext=async()=>{saves++;const saved={...local,revision:stored.revision+1,brief:{decision_maker:'',book_readers:'中学生',purpose:'',writing_notes:'水彩风格',audience:stored.brief.audience}};app.setProject(saved);return clone(saved);};
  await app.ui.open();assert.equal(saves,0);assert.equal(app.posted.length,0);assert.equal(app.project().draft,stored.draft);
  await app.ui.generate(app.form('video'));assert.equal(saves,1);assert.equal(app.posted.length,1);assert.equal(app.posted[0].payload.confirmed_draft,local.draft);assert.equal(app.posted[0].payload.revision,stored.revision+1);assert.match(app.html(),/data-stage="result"/);
});

test('changes made after opening the choice or during its save cannot generate from an older confirmation',async()=>{
  for(const timing of ['after-open','during-save']){
    const app=setup();let local={...app.project(),draft:'选择页确认时的未保存口播。'},saves=0;
    app.context.Studio.peekAssistContext=()=>clone(local);
    app.context.Studio.assistContext=async()=>{saves++;const saved=clone(local);if(timing==='during-save')local.draft='保存期间继续输入的口播。';return saved;};
    await app.ui.open();if(timing==='after-open')local.brief={...local.brief,audience:'刚修改的新观众'};
    await app.ui.generate(app.form('image'));assert.equal(app.posted.length,0);assert.match(app.html(),/已经变化，请返回口播稿重新确认/);assert.equal(saves,timing==='after-open'?0:1);
  }
});

test('restoration refuses another project or a non-prompt run without showing unrelated content',async()=>{
  const app=setup(),descriptor={type:'video-prompts',projectId:'prj-other',stage:'result',runId:'assist-other',mode:'image'};
  await app.registrations['video-prompts'](descriptor,{isCurrent:()=>true,options:{restore:true}});assert.equal(app.opened(),false);assert.equal(app.gets.length,0);
  app.setRun({...app.run(),capability:'draft'});await app.registrations['video-prompts']({...descriptor,projectId:'prj-example',runId:'assist-example'},{isCurrent:()=>true,options:{restore:true}});assert.equal(app.opened(),false);assert.match(app.toasts.at(-1).message,/记录与当前项目的提示词不匹配/);
});

test('opening records from a source page returns to the actual project page instead of claiming to return to narration',async()=>{
  const app=setup();app.context.location.hash='#/campaigns/prj-example/sources';await app.ui.showRecords();assert.match(app.html(),/← 返回项目/);assert.doesNotMatch(app.html(),/← 返回口播稿/);
});

test('leaving the records list and reopening continues that list instead of sending the user to generation',async()=>{
  const app=setup();await app.ui.showRecords();app.ui.close();await app.ui.open();assert.match(app.html(),/data-stage="records"/);assert.doesNotMatch(app.html(),/id="videoPromptsForm"/);assert.equal(app.posted.length,0);
});

test('a delayed hashchange after a cached pending page has restored cannot clear its state or stop polling',async()=>{
  const app=setup(),done=clone(app.run());app.setRun({...done,status:'running',result:null});await app.ui.showRecords();await app.ui.openRun({dataset:{run:done.id}});await settle();
  const original=app.context.location.hash;app.context.location.hash='#/library';app.windowEvents.hashchange();
  // The router restores this page during popstate before its matching hashchange is dispatched.
  app.context.location.hash=original;app.renderCurrent();app.windowEvents.hashchange();await settle();
  app.setRun(done);const poll=app.timers.filter(timer=>timer.delay===2200).at(-1);assert(poll);poll.callback();await settle();
  assert.match(app.html(),/复制提示词/);assert.doesNotMatch(app.html(),/正在根据已确认的口播稿/);await app.ui.copy({dataset:{shot:'0'},disabled:false});assert.equal(app.copied.length,1);
});

test('refreshing a prompt page restores focus inside the dialog while leaving outside focus alone',async()=>{
  for(const kind of ['container','button','summary','removed','outside']){
    const app=setup();await app.ui.showRecords();await app.ui.openRun({dataset:{run:app.run().id}});await settle();
    const doc=app.context.document,body={name:'body'},outside={name:'outside'};let root;
    const makeControl=()=>({tagName:kind==='summary'?'SUMMARY':'BUTTON',textContent:'对应口播',getAttribute:name=>({'data-shot':'0',onclick:'VideoPrompts.copy(this)'}[name]??null),focus(){doc.activeElement=this;}});
    const beforeControl=makeControl(),afterControl=makeControl(),next={querySelectorAll:selector=>selector==='details'||kind==='removed'?[]:[afterControl],focus(){doc.activeElement=this;}};
    root={contains:node=>node===beforeControl,querySelectorAll:selector=>selector==='details'?[]:[beforeControl],set outerHTML(value){root=next;doc.activeElement=body;}};
    doc.getElementById=id=>id==='videoPromptsDialog'?root:null;doc.activeElement=kind==='container'?root:kind==='outside'?outside:beforeControl;
    // A real replacement only disturbs focus owned by the replaced subtree.
    if(kind==='outside')Object.defineProperty(root,'outerHTML',{set(){root=next;}});
    app.setRun({...app.run(),stale:true});await app.ui.copy({dataset:{shot:'0'},disabled:false});
    assert.equal(doc.activeElement,kind==='outside'?outside:['container','removed'].includes(kind)?next:afterControl,kind);
  }
});

test('refresh retains an expanded second shot and its copy focus after disabling the button blurs it',async()=>{
  const app=setup();await app.ui.showRecords();await app.ui.openRun({dataset:{run:app.run().id}});await settle();
  const doc=app.context.document,body={name:'body'};let root;
  const details=(first,second)=>[{open:first,querySelector:()=>({textContent:'第 1 镜'})},{open:second,querySelector:()=>({textContent:'第 2 镜'})}];
  const oldDetails=details(false,true),newDetails=details(true,false);
  const identity={tagName:'BUTTON',getAttribute:name=>({'data-shot':'1',onclick:'VideoPrompts.copy(this)'}[name]??null)};
  let disabled=false;
  const before={...identity,dataset:{shot:'1'},get disabled(){return disabled;},set disabled(value){disabled=value;if(value)doc.activeElement=body;}};
  const after={...identity,disabled:false,focus(){if(newDetails[1].open)doc.activeElement=this;}};
  const next={querySelectorAll:selector=>selector==='details'?newDetails:[after],focus(){doc.activeElement=this;}};
  root={contains:node=>node===before,querySelectorAll:selector=>selector==='details'?oldDetails:[before],set outerHTML(value){root=next;doc.activeElement=body;}};
  doc.body=body;doc.getElementById=id=>id==='videoPromptsDialog'?root:null;doc.activeElement=before;
  app.setRun({...app.run(),stale:true});await app.ui.copy(before);
  assert.equal(newDetails[0].open,false);assert.equal(newDetails[1].open,true);assert.equal(doc.activeElement,after);
});

test('copy and package actions restore their disabled button after success or failure without taking focus from another control',async()=>{
  for(const action of ['copy','copyAll','download'])for(const outcome of ['success','failure','moved','left']){
    const app=setup();app.setRun({...app.run(),markdown:'# 制作包'});await app.ui.showRecords();await app.ui.openRun({dataset:{run:app.run().id}});await settle();
    if(action!=='copy'){await app.ui.prepareProduction({disabled:false});await settle();}
    const doc=app.context.document,other={name:'other'};let disabled=false;
    const button={dataset:{shot:'0'},isConnected:true,get disabled(){return disabled;},set disabled(value){disabled=value;if(value)doc.activeElement=doc.body;},focus(){doc.activeElement=this;}};
    doc.activeElement=button;const get=app.context.jget;
    app.context.jget=async path=>{if(outcome==='moved')doc.activeElement=other;if(outcome==='left')app.ui.close();if(outcome==='failure')throw Error('temporary failure');return get(path);};
    await app.ui[action](button);assert.equal(button.disabled,false,action+' '+outcome);
    assert.equal(doc.activeElement,outcome==='moved'?other:outcome==='left'?doc.body:button,action+' '+outcome);
  }
});

test('prepare failure and newly stale package repaint retain focus from their disabled action',async()=>{
  for(const action of ['prepareProduction','copyAll','download']){
    const app=setup();app.setRun({...app.run(),markdown:'# 制作包'});await app.ui.showRecords();await app.ui.openRun({dataset:{run:app.run().id}});await settle();
    if(action!=='prepareProduction'){await app.ui.prepareProduction({disabled:false});await settle();}
    const doc=app.context.document;let root,disabled=false;
    const identity={tagName:'BUTTON',getAttribute:name=>name==='onclick'?'VideoPrompts.'+action+'(this)':null};
    const before={...identity,isConnected:true,get disabled(){return disabled;},set disabled(value){disabled=value;if(value)doc.activeElement=doc.body;}};
    const after={...identity,disabled:false,focus(){doc.activeElement=this;}};
    const next={querySelectorAll:selector=>selector==='details'?[]:[after],focus(){doc.activeElement=this;}};
    root={contains:node=>node===before,querySelectorAll:selector=>selector==='details'?[]:[before],set outerHTML(value){before.isConnected=false;root=next;doc.activeElement=doc.body;}};
    doc.getElementById=id=>id==='videoPromptsDialog'?root:null;doc.activeElement=before;
    if(action==='prepareProduction')app.context.jget=async()=>{throw Error('temporary failure');};else app.setRun({...app.run(),stale:true});
    await app.ui[action](before);assert.equal(doc.activeElement,after,action);assert.equal(before.disabled,false);
  }
});

test('reference cards show actual image or video uses without turning approved text evidence into ready pictures',async()=>{
  for(const mode of ['image','video']){
    const app=setup(),run=app.run(),pack=run.result.video_prompts;
    pack.presentation_mode=mode;pack.contract_version='2.0';run.snapshot.presentation_mode=mode;
    pack.shots=[1,2,3].map(number=>({...clone(pack.shots[0]),number,reference_ids:number===1?[]:['bridge'],reference_requirements:number===1?'本画面为概念创作。':'待提供：桥梁侧面参考图，必须可辨认拱形结构。\n待制作：固定画幅的构图示意。参考图未提供时，不用想象的结构代替。'}));
    const requirement='待提供：整座桥的侧面照片，必须保留拱形结构。\n待制作：构图示意。参考图待提供时，不用想象的结构代替。';
    pack.references=[{id:'bridge',name:'桥梁侧面参考图',requirement,status:'required',shot_numbers:[3,2,2,0,-1,1.5,'2',99]}];
    pack.required_inputs=clone(pack.references);run.markdown='# 制作包\n'+requirement;const original=clone(run);app.setRun(run);
    app.setProject({...app.project(),assets:[1,2,3,4].map(number=>({id:'text-'+number,status:'approved'}))});
    await app.ui.showRecords();await app.ui.openRun({dataset:{run:run.id}});await settle();
    assert.match(app.html(),new RegExp('制作'+(mode==='image'?'这张图':'这个镜头')+'需要的参考图'));
    await app.ui.prepareProduction({disabled:false});await settle();
    const card=app.html().match(/<section class="video-handoff-materials">([\s\S]*?)<\/section>/)[1];
    assert.match(card,/制作画面需要的参考图/);assert.match(card,new RegExp('用于第 2、3 '+(mode==='image'?'张':'镜')));
    assert.match(card,new RegExp('在所用的'+(mode==='image'?'生图':'视频')+'工具中上传对应参考图，再使用提示词'));
    assert.match(card,/必须保留拱形结构/);assert.match(card,/参考图待提供时，不用想象的结构代替/);
    assert.doesNotMatch(card,/待提供：|待制作：|待提供或确认|已确认|已提供|已齐|data-video-sources/);
    assert.match(app.html(),/<\/section><div class="video-handoff-sources">[\s\S]*?查看口播内容与出处/);
    assert.deepEqual(app.run(),original);assert.equal(app.posted.length,0);
    await app.ui.copyAll({disabled:false});assert.equal(app.copied.at(-1),original.markdown);
  }
});

test('legacy registry usage comes only from valid shot numbers or explicit reference ids',async()=>{
  const app=setup(),run=app.run(),pack=run.result.video_prompts;
  pack.shots=[{...pack.shots[0],number:2,reference_ids:['a'],reference_requirements:'待提供：对象的正面照片。'},{...pack.shots[0],number:4,reference_ids:['a']}];
  pack.references=[{id:'a',name:'对象参考图',requirement:'待提供：对象的正面照片。',shot_numbers:['2',99]},{id:'unused',name:'未使用的参考图',requirement:'待制作：没有对应画面的图片。',shot_numbers:[99]}];
  app.setRun(run);await app.ui.showRecords();await app.ui.openRun({dataset:{run:run.id}});await app.ui.prepareProduction({disabled:false});await settle();
  assert.match(app.html(),/用于第 2、4 张/);assert.doesNotMatch(app.html(),/用于第 99|未使用的参考图/);assert.equal(app.posted.length,0);
});

test('legacy per-shot requirements are deduplicated without guessing unknown shot numbers',async()=>{
  const app=setup(),run=app.run(),pack=run.result.video_prompts;
  pack.shots=[{...pack.shots[0],number:3,reference_requirements:'待提供：叶片正反面照片；没有原图时不得编造纹理。'},{...pack.shots[0],number:2,reference_requirements:'待提供：叶片正反面照片；没有原图时不得编造纹理。'},{...pack.shots[0],number:'6',reference_requirements:'待制作：独立的构图草图。'}];
  app.setRun(run);await app.ui.showRecords();await app.ui.openRun({dataset:{run:run.id}});await app.ui.prepareProduction({disabled:false});await settle();
  const section=app.html().match(/<section class="video-handoff-materials">([\s\S]*?)<\/section>/)[1];
  assert.match(section,/用于第 2、3 张/);assert.equal((section.match(/叶片正反面照片/g)||[]).length,1);assert.match(section,/没有原图时不得编造纹理/);assert.match(section,/独立的构图草图/);assert.doesNotMatch(section,/用于第 6|待提供：|待制作：/);
});

test('an explicitly empty new reference list does not turn creative-scene notes into reference tasks',async()=>{
  for(const mode of ['image','video']){
    const app=setup(),run=app.run(),pack=run.result.video_prompts;
    pack.presentation_mode=mode;pack.contract_version='2.0';pack.references=[];pack.required_inputs=[];pack.shots[0].reference_ids=[];pack.shots[0].reference_requirements='本画面为概念或文学创作；按已确认内容制作，不声明存在原书照片。';app.setRun(run);
    await app.ui.showRecords();await app.ui.openRun({dataset:{run:run.id}});await settle();assert.doesNotMatch(app.html(),/video-reference-requirements/);
    await app.ui.prepareProduction({disabled:false});await settle();assert.doesNotMatch(app.html(),/video-handoff-materials|未单列参考图|待提供|待制作|已齐|上传所列|上传所需/);assert.match(app.html(),/查看口播内容与出处/);assert.equal(app.posted.length,0);
  }
});

async function storedHandoff(){
  const app=setup();app.setRun({...app.run(),markdown:'# 保留原始 Markdown\n\n逐条提示词'});
  await app.ui.showRecords();await app.ui.openRun({dataset:{run:app.run().id}});await app.ui.prepareProduction({disabled:false});await settle();return app;
}
function pdfResponse(headers={}){return new Response('%PDF-1.7\nUI transfer fixture',{headers:{'Content-Type':'application/pdf',...headers}});}

test('PDF download uses a meaningful response filename and safely falls back to the frozen project name',async()=>{
  for(const [header,expected] of [
    ["attachment; filename=production-pack.pdf; filename*=UTF-8''"+encodeURIComponent('城市漫步_图片制作包.pdf'),'城市漫步_图片制作包.pdf'],
    ['attachment; filename="reader-pack.pdf"','reader-pack.pdf'],
    ["attachment; filename*=UTF-8''..%2Fbad%3Aname.pdf",'-bad-name.pdf'],
    ["attachment; filename=production-pack.pdf; filename*=UTF-8''%INVALID",'古桥与城市生活_图片制作包.pdf'],
    ['attachment; filename=production-pack.pdf','古桥与城市生活_图片制作包.pdf'],
    ['', '古桥与城市生活_图片制作包.pdf']
  ]){
    const app=await storedHandoff(),button={disabled:false};app.context.fetch=async()=>pdfResponse({'Content-Disposition':header});await app.ui.download(button);
    assert.equal(app.downloads.length,1);assert.equal(app.downloads[0].name,expected);assert.equal(button.disabled,false);assert.equal(app.posted.length,0);
  }
});

test('PDF filename fallback uses backend metadata then the saved title or topic without dates or current-project names',async()=>{
  for(const [saved,expected] of [
    [{download_filename:'古桥故事_图片制作包.pdf'},'古桥故事_图片制作包.pdf'],
    [{snapshot:{title:'历史项目名称',brief:{topic:'口播话题'}}},'历史项目名称_图片制作包.pdf'],
    [{snapshot:{brief:{topic:'口播话题'}}},'口播话题_图片制作包.pdf'],
    [{snapshot:{}},'未命名项目_图片制作包.pdf']
  ]){
    const app=await storedHandoff();app.setRun({...app.run(),...saved});app.setProject({...app.project(),title:'后来改过的项目名称'});app.context.fetch=async()=>pdfResponse();
    await app.ui.download({disabled:false});await app.ui.download({disabled:false});
    assert.deepEqual(app.downloads.map(d=>d.name),[expected,expected]);assert.equal(app.posted.length,0);
  }
  const app=await storedHandoff(),run=app.run();run.result.video_prompts.presentation_mode='video';app.setRun(run);app.context.fetch=async()=>pdfResponse();await app.ui.download({disabled:false});assert.equal(app.downloads[0].name,'古桥与城市生活_视频制作包.pdf');
});

test('PDF canonical metadata handles invalid response headers and does not duplicate old-version prefixes',async()=>{
  const app=await storedHandoff();app.setRun({...app.run(),stale:true,download_filename:'旧版-古桥故事_图片制作包.pdf'});
  app.context.fetch=async()=>pdfResponse({'Content-Disposition':"attachment; filename=production-pack.pdf; filename*=UTF-8''%INVALID"});
  await app.ui.download({disabled:false});assert.equal(app.downloads.length,0);
  await app.ui.download({disabled:false});assert.equal(app.downloads[0].name,'旧版-古桥故事_图片制作包.pdf');
  assert.equal(app.posted.length,0);
});

test('PDF names remain portable when saved titles contain paths, control characters or very long text',async()=>{
  const app=await storedHandoff();app.setRun({...app.run(),snapshot:{title:'../文学:故事\\篇章\n'+ '长标题'.repeat(70)}});app.context.fetch=async()=>pdfResponse();
  await app.ui.download({disabled:false});const filename=app.downloads[0].name;
  assert.doesNotMatch(filename,/[\\/:*?"<>|\u0000-\u001f\u007f]/);assert.match(filename,/_图片制作包\.pdf$/);assert.ok(Buffer.byteLength(filename,'utf8')<=220);assert.equal(app.posted.length,0);
});

test('failed, empty or non-PDF responses never save a disguised error document and can retry without regeneration',async()=>{
  const cases=[
    ()=>new Response('{"error":"排版暂不可用，请稍后重试。"}',{status:503,headers:{'Content-Type':'application/json'}}),
    ()=>new Response('{"ok":false}',{headers:{'Content-Type':'application/json'}}),
    ()=>new Response('{"ok":false}',{headers:{'Content-Type':'application/pdf'}}),
    ()=>new Response('',{headers:{'Content-Type':'application/pdf'}}),
    ()=>new Response('<html>error</html>',{status:502,headers:{'Content-Type':'text/html'}}),
    ()=>{throw new Error('Failed to fetch');}
  ];
  for(const response of cases){
    const app=await storedHandoff(),button={disabled:false};app.context.fetch=async()=>response();await app.ui.download(button);
    assert.equal(app.downloads.length,0);assert.equal(button.disabled,false);assert.equal(app.toasts.at(-1).bad,true);assert.match(app.toasts.at(-1).message,/PDF|排版/);assert.match(app.html(),/data-stage="handoff"/);
    app.context.fetch=async()=>pdfResponse();await app.ui.download(button);assert.equal(app.downloads.length,1);assert.equal(app.posted.length,0);
    await app.ui.copyAll({disabled:false});assert.equal(app.copied.at(-1),app.run().markdown);
  }
});

test('a PDF stale conflict stops the first download and only an explicit old-version retry grants permission',async()=>{
  const app=await storedHandoff(),requests=[],button={disabled:false};
  app.context.fetch=async path=>{requests.push(path);return requests.length===1?new Response('{"ok":false,"error":"制作内容已变化，请确认旧版后再下载。"}',{status:409,headers:{'Content-Type':'application/json'}}):pdfResponse();};
  await app.ui.download(button);assert.equal(app.downloads.length,0);assert.doesNotMatch(requests[0],/allow_stale/);assert.match(app.html(),/下载旧版制作包 PDF/);assert.match(app.toasts.at(-1).message,/确认旧版/);assert.equal(button.disabled,false);
  await app.ui.download(button);assert.equal(app.downloads.length,1);assert.match(requests[1],/format=pdf&allow_stale=1$/);assert.equal(app.downloads[0].name,'旧版-古桥与城市生活_图片制作包.pdf');assert.equal(app.posted.length,0);
});

test('an in-flight PDF download is not duplicated and cannot save after leaving its handoff page',async()=>{
  const app=await storedHandoff(),button={disabled:false};let complete,count=0;
  app.context.fetch=()=>{count++;return new Promise(resolve=>{complete=resolve;});};
  const pending=app.ui.download(button);await settle();assert.equal(count,1);assert.equal(button.disabled,true);
  await app.ui.download(button);assert.equal(count,1);app.ui.close();complete(pdfResponse());await pending;
  assert.equal(button.disabled,false);assert.equal(app.downloads.length,0);assert.equal(app.posted.length,0);
});
