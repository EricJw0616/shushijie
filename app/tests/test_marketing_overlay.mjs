import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';
const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const start=source.indexOf('const AppHistory=(function(){');
const code=source.slice(start,source.indexOf('// tab 可选',start));
const backCode=source.slice(source.indexOf('function parentOf(view){'),source.indexOf('\nfunction parse(hash)'));
const baseHash='#/campaigns/prj-0000000000000000/results';
const settle=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function setup(shared){
  const browser=shared||{entries:[{hash:baseHash,state:null}],cursor:0,storage:new Map()};
  const root={id:'modalRoot',innerHTML:'',controls:[],details:[],nodes:[],querySelectorAll(selector){return selector==='input,textarea,select'?this.controls:selector==='details'?this.details:this.nodes;}};
  const renders=[],toasts=[];let context,ui,nav;
  const location={get hash(){return browser.entries[browser.cursor].hash;},get href(){return 'http://localhost/'+this.hash;},set hash(value){browser.entries.splice(browser.cursor+1);browser.entries.push({hash:value,state:null});browser.cursor++;}};
  const history={get state(){return browser.entries[browser.cursor].state;},scrollRestoration:'auto',replaceState(value,_,url){browser.entries[browser.cursor]={state:value,hash:url?.includes('#')?url.slice(url.indexOf('#')):location.hash};},pushState(value,_,url){browser.entries.splice(browser.cursor+1);browser.entries.push({state:value,hash:url?.includes('#')?url.slice(url.indexOf('#')):location.hash});browser.cursor++;},back(){this.go(-1);},go(delta){const old=location.hash;browser.cursor=Math.max(0,Math.min(browser.entries.length-1,browser.cursor+delta));queueMicrotask(()=>{nav.capture(false);ui.sync();if(old!==location.hash){ui.clear();context.state.lastHash=location.hash;ui.sync();}});}};
  context={location,history,state:{lastHash:location.hash},scrollY:0,sessionStorage:{getItem:key=>browser.storage.get(key)||null,setItem:(key,value)=>browser.storage.set(key,value),removeItem:key=>browser.storage.delete(key)},document:{getElementById:id=>id==='modalRoot'?root:null,querySelector:()=>null},setTimeout:fn=>queueMicrotask(fn),toast:message=>toasts.push(message),parse:()=>{const parts=location.hash.slice(2).split('/');return{view:parts[0],arg:parts[1],tab:parts[2]};},workflowContext:()=>null,WORKFLOW_TOOLS:[],go:(...args)=>{location.hash='#/'+args.filter(Boolean).join('/');nav.sync();context.state.lastHash=location.hash;}};
  context.window=context;runInNewContext(code+'\nthis.nav=AppHistory;'+backCode,context);ui=context.MarketingOverlay;nav=context.nav;
  const show=(name,options={})=>ui.open('modal',()=>{root.innerHTML=name;root.controls=[];root.details=[];root.nodes=[];renders.push(name);},undefined,options);
  function route(hash){nav.capture();ui.deferNavigation(()=>{});location.hash=hash;nav.sync();ui.clear();context.state.lastHash=hash;ui.sync();}
  return {browser,context,root,ui,nav,show,route,history,renders,toasts,cursor:()=>browser.cursor,html:()=>root.innerHTML};
}

test('nested preparation is a real visit: Back restores prompts and Forward restores preparation',async()=>{
  const app=setup();app.show('prompts');app.show('preparation',{step:true});assert.equal(app.cursor(),2);
  app.history.back();await settle();assert.equal(app.html(),'prompts');assert.equal(app.ui.isOpen(),true);
  app.history.go(1);await settle();assert.equal(app.html(),'preparation');
  app.ui.close(true);await settle();assert.equal(app.cursor(),0);assert.equal(app.ui.isOpen(),false);assert.equal(app.html(),'');
});
test('updating the current page does not add a Back stop; one-step close retains the parent visit',async()=>{
  const app=setup();app.show('choose');app.show('choose-video',{replace:true});assert.equal(app.cursor(),1);
  app.show('prompts',{step:true});app.show('preparation',{step:true});app.ui.close(false);await settle();assert.equal(app.html(),'prompts');assert.equal(app.cursor(),2);
  app.ui.close(false);await settle();assert.equal(app.html(),'choose-video');
});
test('viewing sources preserves the preparation page and its predecessor instead of truncating history',async()=>{
  const app=setup();app.show('prompts');app.show('preparation',{step:true});
  app.route(baseHash.replace('/results','/sources'));assert.equal(app.cursor(),3);assert.equal(app.ui.isOpen(),false);
  app.history.back();await settle();assert.equal(app.html(),'preparation');assert.equal(app.cursor(),2);
  app.history.back();await settle();assert.equal(app.html(),'prompts');
  app.history.go(1);await settle();assert.equal(app.html(),'preparation');
  app.history.go(1);await settle();assert.equal(app.context.location.hash,baseHash.replace('/results','/sources'));assert.equal(app.ui.isOpen(),false);
});
test('durable immutable descriptors restore the exact run and stage after refresh, without generating',async()=>{
  const first=setup(),descriptor={type:'video-prompts',projectId:'prj-0000000000000000',stage:'handoff',runId:'assist-existing',mode:'video',parentStage:'result'};
  first.show('choose',{descriptor:{...descriptor,stage:'choose'}});first.show('handoff',{step:true,descriptor});descriptor.stage='choose';
  assert.equal(first.history.state.__marketingOverlay.descriptor.stage,'handoff');
  const fresh=setup(first.browser),reads=[];
  fresh.ui.register('video-prompts',async(saved,context)=>{reads.push(saved);await Promise.resolve();if(context.isCurrent())fresh.show(saved.runId+':'+saved.stage,{...context.options,descriptor:saved});});
  fresh.ui.sync();await settle();assert.equal(fresh.html(),'assist-existing:handoff');assert.equal(fresh.cursor(),2);assert.equal(reads.length,1);assert.equal(reads[0].mode,'video');
  fresh.history.back();await settle();assert.equal(fresh.html(),'assist-existing:choose');assert.equal(fresh.cursor(),1);
});
test('a late restore cannot reopen a result after navigation moved elsewhere',async()=>{
  const first=setup();first.show('handoff',{descriptor:{type:'video-prompts',stage:'handoff'}});
  const fresh=setup(first.browser);let finish;fresh.ui.register('video-prompts',async(saved,context)=>{await new Promise(resolve=>{finish=resolve;});if(context.isCurrent())fresh.show('late',{...context.options,descriptor:saved});});
  fresh.ui.sync();fresh.route('#/records/marketing');finish();await settle();assert.equal(fresh.ui.isOpen(),false);assert.equal(fresh.html(),'');
});
test('unsaved overlay fields, expanded sections and internal scroll survive Back and reload',async()=>{
  const app=setup(),descriptor={type:'edit',stage:'form'};
  const renderForm=()=>{app.root.innerHTML='form';app.root.controls=[{tagName:'TEXTAREA',name:'body',type:'textarea',value:'saved',selectionStart:0,selectionEnd:0,setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;}}];app.root.details=[{open:false}];app.root.nodes=[{scrollTop:0,scrollLeft:0}];};
  app.ui.open('editor',renderForm,null,{descriptor});app.root.controls[0].value='未保存\n第二行';app.root.controls[0].selectionStart=2;app.root.controls[0].selectionEnd=4;app.root.details[0].open=true;app.root.nodes[0].scrollTop=160;
  app.show('detail',{step:true});app.history.back();await settle();assert.equal(app.root.controls[0].value,'未保存\n第二行');assert.equal(app.root.details[0].open,true);assert.equal(app.root.nodes[0].scrollTop,160);assert.equal(app.root.controls[0].selectionEnd,4);
  app.ui.capture();const fresh=setup(app.browser);fresh.ui.register('edit',(saved,context)=>fresh.ui.open('editor',()=>{fresh.root.controls=[{tagName:'TEXTAREA',name:'body',type:'textarea',value:'saved'}];fresh.root.details=[{open:false}];fresh.root.nodes=[{scrollTop:0,scrollLeft:0}];},null,{...context.options,descriptor:saved}));
  fresh.ui.sync();await settle();assert.equal(fresh.root.controls[0].value,'未保存\n第二行');assert.equal(fresh.root.nodes[0].scrollTop,160);
});
test('ordinary page back and marketing back both follow actual visits, not parentStep',async()=>{
  const app=setup();app.route(baseHash.replace('/results','/history'));app.route(baseHash.replace('/results','/sources'));
  app.context.marketingBackTo('results');await settle();assert.equal(app.context.location.hash,baseHash.replace('/results','/history'));
  app.route('#/settings');app.route('#/book/B56');app.context.navBack();await settle();assert.equal(app.context.location.hash,'#/settings');
});
test('scroll belongs to an individual visit even for repeated URLs and survives refresh',async()=>{
  const app=setup();app.context.scrollY=410;app.nav.capture();app.route(baseHash.replace('/results','/sources'));
  app.context.scrollY=220;app.nav.capture();app.route(baseHash);app.context.scrollY=30;app.nav.capture();
  app.history.back();await settle();assert.equal(app.nav.position(),220);app.history.back();await settle();assert.equal(app.nav.position(),410);
  const fresh=setup(app.browser);assert.equal(fresh.nav.position(),410);
});
test('unsupported legacy overlay entries do not create invisible repeated Back stops after refresh',async()=>{
  const app=setup();app.show('old prompts');app.show('old handoff',{step:true});
  const fresh=setup(app.browser);fresh.ui.sync();await settle();assert.equal(fresh.cursor(),0);assert.equal(fresh.ui.isOpen(),false);assert.equal(fresh.context.location.hash,baseHash);
});

function sourceControls(app){
  const {context}=app;context.state.scroll={};context.state.depth=0;
  context.route=()=>{app.nav.sync();app.ui.clear();context.state.lastHash=context.location.hash;app.ui.sync();};
  runInNewContext(source.slice(source.indexOf('function go(view,arg,tab,q,'),source.indexOf('\nfunction openBook(code)')),context);
  return ()=>{const origin=app.ui.sourceOrigin();assert.ok(origin);context.go('campaigns','prj-0000000000000000','sources',undefined,{sourceReturn:origin});context.route();};
}
const handoffDescriptor=mode=>({type:'video-prompts',projectId:'prj-0000000000000000',stage:'handoff',runId:'assist-'+mode,mode});
test('the source visit returns to the exact handoff and keeps the same target on browser Forward',async()=>{
  for(const mode of ['image','video']){
    const app=setup(),visitSources=sourceControls(app);app.show('handoff-'+mode,{descriptor:handoffDescriptor(mode)});const originCursor=app.cursor();visitSources();
    assert.equal(app.html(),'');assert.equal(app.ui.sourceReturn().overlay.descriptor.runId,'assist-'+mode);
    assert.equal(app.ui.returnToSourceOrigin(),true);await settle();assert.equal(app.cursor(),originCursor);assert.equal(app.html(),'handoff-'+mode);
    app.history.go(1);await settle();assert.equal(app.context.location.hash,baseHash.replace('/results','/sources'));assert.equal(app.ui.sourceReturn().overlay.descriptor.mode,mode);assert.equal(app.ui.isOpen(),false);
  }
});
test('refreshing sources restores the exact handoff descriptor through read-only resolution',async()=>{
  const original=setup(),visitSources=sourceControls(original);original.show('handoff',{descriptor:handoffDescriptor('video')});visitSources();
  const fresh=setup(original.browser),resolved=[];fresh.ui.register('video-prompts',async(saved,context)=>{resolved.push(saved);if(context.isCurrent())fresh.show(saved.runId+':'+saved.stage,{...context.options,descriptor:saved});});
  assert.equal(fresh.ui.sourceReturn().overlay.descriptor.runId,'assist-video');fresh.ui.returnToSourceOrigin();await settle();
  assert.equal(fresh.html(),'assist-video:handoff');assert.equal(resolved.length,1);
});
test('material details and original-text visits retain the source return target without polluting other projects',async()=>{
  const app=setup(),visitSources=sourceControls(app);app.show('handoff',{descriptor:handoffDescriptor('image')});visitSources();
  app.show('material detail');app.route('#/book/B56/text/segment');assert.equal(app.ui.sourceReturn(),null);
  app.history.back();await settle();assert.equal(app.html(),'material detail');app.ui.close();await settle();assert.equal(app.ui.sourceReturn().overlay.descriptor.runId,'assist-image');
  app.ui.returnToSourceOrigin();await settle();assert.equal(app.html(),'handoff');app.ui.close(true);await settle();
  app.route(baseHash.replace('/results','/sources'));assert.equal(app.ui.sourceReturn(),null,'a later direct source visit does not inherit the earlier handoff');
  app.route('#/campaigns/prj-1111111111111111/sources');assert.equal(app.ui.sourceReturn(),null);
});
test('handoff opened over sources can visit that same URL and return once, without a silent no-op',async()=>{
  const app=setup(),visitSources=sourceControls(app);app.route(baseHash.replace('/results','/sources'));const base=app.cursor();
  app.show('handoff over sources',{descriptor:handoffDescriptor('image')});const origin=app.cursor();visitSources();
  assert.equal(app.cursor(),origin+1);assert.equal(app.ui.isOpen(),false);assert.equal(app.ui.sourceReturn().overlay.descriptor.runId,'assist-image');
  app.ui.returnToSourceOrigin();await settle();assert.equal(app.cursor(),origin);assert.equal(app.html(),'handoff over sources');
  app.ui.close(true);await settle();assert.equal(app.cursor(),base);assert.equal(app.ui.sourceReturn(),null,'after closing, the original source page has no stale handoff-return context');
});
