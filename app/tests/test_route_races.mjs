import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';
const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const functionCode=name=>{const start=source.lastIndexOf('function '+name+'('),asyncStart=source.slice(start-6,start)==='async '?start-6:start;return source.slice(asyncStart,source.indexOf('\n}\n',start)+2);};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function setup(){
  let view,sequence=0;const nodes=[],timers=[],crumbs=[];
  function node(text=''){
    const v={id:'view',number:++sequence,innerHTML:text,className:'view',dataset:{},classList:{remove(){},add(){}},cloneNode:()=>node(),removeAttribute(){},replaceWith(next){assert.equal(view,v);view=next;},querySelector(selector){return selector==='.project-section-panel'&&this.innerHTML.includes('marketingPageTitle')?{}:null;}};nodes.push(v);return v;
  }
  view=node('<section class="project-section-panel"><h1 id="marketingPageTitle">口播稿</h1></section>');
  const hash='#/campaigns/prj-0000000000000000/results';
  const context={state:{routeRequest:0,lastHash:hash,curView:{view:'campaigns',arg:'prj-0000000000000000'},scroll:{},books:[{code:'B56'}],libFilters:{}},location:{hash},document:{getElementById:id=>id==='view'?view:null},Studio:{beforeNavigate:async()=>{},render:async(v)=>{v.innerHTML='<section class="project-section-panel"><h1 id="marketingPageTitle">口播稿</h1></section>'; }},AppHistory:{sync(){},position:()=>0},MarketingOverlay:{clear(){},sync(){}},ProjectNav:{sync(){}},parse:value=>{const p=(value||context.location.hash).slice(2).split('/');return{view:p[0],arg:p[1],tab:p[2]};},setNav(){},rememberWorkflowContext(){},clearJobTimer(){},showWorkflowReturn(){},setTimeout:(fn,ms)=>{timers.push({fn,ms});},scrollTo(){},crumb:html=>crumbs.push(html),loading:text=>text,refreshBooks:async()=>{},jget:async()=>({}),api:async()=>({}),toast(){},num:String,esc:String,go(){}};
  context.window=context;runInNewContext(functionCode('capturePageRequest')+'\n'+functionCode('route')+'\n'+functionCode('renderLibrary')+'\n'+functionCode('viewJob'),context);
  return {context,nodes,timers,crumbs,view:()=>view,navigate:async hash=>{context.location.hash=hash;return context.route({navigation:true});},replaceView:()=>{view=node('other page');return view;}};
}
test('a real delayed library response cannot replace the marketing page after an immediate Back',async()=>{
  const app=setup(),book=deferred(),requests=[];
  app.context.jget=path=>{requests.push(path);return path.startsWith('/api/book?')?book.promise:Promise.resolve({counts:{}});};
  const old=app.navigate('#/library');await settle();assert.ok(requests.some(x=>x.startsWith('/api/book?')));
  await app.navigate('#/campaigns/prj-0000000000000000/results');const current=app.view(),crumbCount=app.crumbs.length;
  book.resolve({});await old;
  assert.equal(app.view(),current);assert.match(current.innerHTML,/marketingPageTitle/);assert.equal(app.context.state.lastHash,'#/campaigns/prj-0000000000000000/results');assert.equal(app.crumbs.length,crumbCount);
});
test('distinct route visits own different DOM hosts, while project tab visits preserve form identity',async()=>{
  const app=setup(),first=app.view(),pending=deferred();
  await app.navigate('#/campaigns/prj-0000000000000000/sources');assert.equal(app.view(),first);
  app.context.renderLibrary=async v=>{await pending.promise;v.innerHTML='late old library';};
  const old=app.navigate('#/library');await settle();const library=app.view();assert.notEqual(library,first);
  await app.navigate('#/campaigns/prj-0000000000000000/results');const current=app.view();assert.notEqual(current,library);
  pending.resolve();await old;assert.equal(library.innerHTML,'late old library');assert.match(current.innerHTML,/marketingPageTitle/);
});
test('returning to the same URL does not make an old page request current again',()=>{
  const app=setup(),v=app.view(),guard=app.context.capturePageRequest(v);assert.equal(guard(),true);
  app.context.state.routeRequest++;app.context.location.hash='#/library';assert.equal(guard(),false);
  app.context.state.routeRequest++;app.context.location.hash='#/campaigns/prj-0000000000000000/results';assert.equal(guard(),false);
  const newer=app.context.capturePageRequest(v);assert.equal(newer(),true);app.replaceView();assert.equal(newer(),false);
});
test('an in-flight job response cannot redraw the current page or restart its timer after leaving',async()=>{
  const app=setup(),pending=deferred(),rendered=[];app.context.location.hash='#/job/job-1';app.context.api=()=>pending.promise;app.context.renderJob=(v,data)=>rendered.push(data);
  await app.context.viewJob('job-1');app.context.state.routeRequest++;app.context.location.hash='#/campaigns/prj-0000000000000000/results';app.replaceView();pending.resolve({job:{status:'running'}});await settle();
  assert.equal(rendered.length,0);assert.equal(app.timers.length,0);assert.equal(app.view().innerHTML,'other page');
});
