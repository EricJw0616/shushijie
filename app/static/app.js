
'use strict';
const state = {books:[], stats:{}, groups:[], settings:null, jobs:[], trash:[], bookCache:{}, detailTab:'overview', textMode:'chapter', tier:'', book:{}, loadError:'', pin:null,
  // 跳原文的「来意」：从哪进来决定标什么词、横幅怎么写。见 pinNoteHtml()
  pinTerm:'', pinMode:'', pinTotal:0, pinFrom:'', pinFocus:false, entJump:null,
  curView:null, navPrev:null, lastHash:'', scroll:{}, depth:0, fromGo:false,
  libFilters:{q:'',clc:'',status:''}, arcQ:''};
const PROTO = {P1:'规范型',P2:'知识型',P3:'论说型',P4:'叙事型',P5:'戏曲型',P6:'散文型',P7:'韵文集型',P8:'条目型',P9:'选集笺注型',P10:'笔记志书型',P11:'图鉴型',P12:'纪事型'};
const PROTO_ORDER = Object.keys(PROTO);
const MODE_CN = {regex:'按篇名切分',toc:'按目录切分',numeral:'按章号切分',echo:'按篇名切分',solo:'按篇名切分',flat:'不分篇'};
/* 应用清单只维护一份：工作台、应用中心、导航列表与徽标都读它。
   以前工作台写 4 个、应用中心写 5 个，客户看到两套口径。 */
const APPS = [
  {key:'kg',        name:'关系探索', desc:'查书中的人物关系、事件与工程、概念与案例，核对原文并为项目收集材料。', status:'已接入', path:'relations', ico:'◉', need:['按关键词查找','浏览关系图谱']},
  {key:'hotspot',   name:'热点匹配', desc:'输入热点或话题，按标签与原文召回相关图书，给命中理由', status:'已接入', path:'hotspot',   ico:'✦', need:['标签体系','原文检索','命中理由']},
  {key:'marketing', name:'营销资料', desc:'了解一本书的内容与传播角度，找到有价值的资料后带入营销策划', status:'已接入', path:'marketing', ico:'◇', need:['了解图书','寻找角度','用于策划']},
  {key:'qa',        name:'智能问答', desc:'用一个问题读懂书中观点，找到原文依据，也能比较不同图书的表达。', status:'已接入', path:'qa',          ico:'◈', need:['选书提问','原文出处','连续追问']},
  {key:'api',       name:'开放 API', desc:'检索、条目、数据集导出；按 Key / 配额 / 审计管理',     status:'设计',   path:'',          ico:'⇄', need:['API Key','限流','审计日志']},
];
const APPS_LIVE = APPS.filter(a=>a.path);
const RELATION_TYPE_COLORS = Object.freeze({
  人物: '#FFB476', 地点: '#6DDAB2', 籍贯: '#83D5AA', 学科: '#6AC9F4',
  主题: '#C3A4F5', 意象: '#EE9BC7', 书: '#829BFF', 篇章: '#EBC76E',
  科: '#5DC7D7', 物种: '#89D68F', 条目: '#BBA5F4', 段落: '#A4B5CF',
  事件: '#FF8C99', 工程: '#B9DB78', 概念: '#8DB6FF', 案例: '#64D8C5'
});
const LAYERS = [['L3','类型','这本书属于哪一类'],['L5','能力','能提供什么内容成果'],['L4','内容','书里写了什么'],['L6','概念','哪一段在讲道理'],['L7','议题','能对上哪些议题'],['L2','语体','用什么语言写的'],['L1','结构','怎么编的'],['L0','原文','内容是否完整可检索']];

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function num(n){return n==null||n===''?'—':Number(n).toLocaleString('zh-CN');}
function pct(n){return n==null||n===''?'—':Number(n).toFixed(1)+'%';}
function clip(s,n){s=String(s==null?'':s).replace(/\s+/g,' ').trim();return s.length>n?s.slice(0,n)+'…':s;}
function arr(v){return Array.isArray(v)?v:[];}
function coverChar(t){const s=String(t||'').replace(/^\s*\d{4}\s*版?/,'');const m=s.match(/[\u3400-\u9FFF\uF900-\uFAFF]/);return m?m[0]:'书';}
function pill(p){return `<span class="pill ${String(p||'').toLowerCase()}">${esc(p||'—')} ${esc(PROTO[p]||'待分类')}</span>`;}
function status(r){if(r.status==='pending')return '<span class="status wait">待确认</span>';if(r.status==='failed')return '<span class="status fail">异常</span>';if(r.confirmed)return '<span class="status ok">已确认</span>';return '<span class="status ok">已入库</span>';}
function ago(s){if(!s)return '—';return String(s).replace('T',' ').slice(0,10);}

async function jget(url){const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}
async function boot(){
  try{
    const d=await jget('/api/books');
    state.books=d.books||[];state.stats=d.stats||{};state.groups=d.groups||[];
  }catch(e){state.loadError=e.message;}
  try{state.settings=await jget('/api/settings');}catch(e){}
  try{const d=await jget('/api/jobs');state.jobs=d.jobs||[];}catch(e){}
  try{updateNavTasks();}catch(e){}
  try{const d=await jget('/api/trash');state.trash=d.items||[];}catch(e){}
  paintNavCounts();
  syncKgCount();
  route();
  checkAssetVersion();
}

/* 前端资源版本自检：页面里注入的 __ASSET_V 和服务器当前版本不一致，说明这个标签页还在跑旧 JS。
   自动刷新一次（用 sessionStorage 防循环）。 */
async function checkAssetVersion(){
  try{
    const d=await jget('/api/version');
    const v=d&&d.v;
    if(!v||!window.__ASSET_V||v===window.__ASSET_V)return;
    if(sessionStorage.getItem('assetReloadFor')===v)return;
    sessionStorage.setItem('assetReloadFor',v);
    location.reload();
  }catch(e){}
}
function paintNavCounts(){
  const s=state.stats||{};
  const b=document.getElementById('navBookCount'); if(b)b.textContent=num(s.books||state.books.length||0);
}
async function syncKgCount(){
  try{
    const d=await jget('/api/kg/books');
    state.kgBuilt=new Set((d.books||[]).filter(x=>x.status==='已建图').map(x=>x.code));
    const el=document.getElementById('navKgCount');
    if(el)el.textContent=(d.books||[]).filter(x=>x.status==='已建图').length;
  }catch(e){}
}

async function refreshBooks(){
  try{
    const d=await jget('/api/books');
    state.books=d.books||[]; state.stats=d.stats||{}; state.groups=d.groups||[];
    paintNavCounts();
  }catch(e){}
}

// A browser-history entry is a visit, not a workflow step. Keep its scroll
// position separate from other visits to the same URL.
const AppHistory=(function(){
  if('scrollRestoration' in history)history.scrollRestoration='manual';
  const key='__bookNav',storageKey='bookworld.navigation-scroll';
  const hash=()=>location.hash||'#/dashboard';
  let current=null,serial=0,positions={};
  try{positions=JSON.parse(sessionStorage.getItem(storageKey)||'{}')||{};}catch(_){}
  const identity=()=>Date.now().toString(36)+'-'+(++serial)+'-'+Math.random().toString(36).slice(2,8);
  function valid(value){return value&&Number.isInteger(value.index)&&typeof value.hash==='string';}
  function mark(value,extra){
    const next={...(history.state||{}),...(extra||{}),[key]:value};
    history.replaceState(next,'',location.href);current=value;return value;
  }
  function sync(){
    const saved=history.state&&history.state[key];
    if(valid(saved)&&saved.hash===hash()){
      current=saved.id?saved:mark({...saved,id:identity()});return current;
    }
    return mark({id:identity(),index:current?current.index+1:0,hash:hash(),previousHash:current?current.hash:''});
  }
  function persist(){try{const ids=Object.keys(positions);for(const id of ids.slice(0,Math.max(0,ids.length-100)))delete positions[id];sessionStorage.setItem(storageKey,JSON.stringify(positions));}catch(_){} }
  function capture(readScroll=true){
    if(current&&current.id){
      if(readScroll)positions[current.id]=Math.max(0,window.scrollY||0);
      persist();
    }
    if(window.Studio?.rememberNavigation)Studio.rememberNavigation();
  }
  function scroll(top){
    if(current&&current.hash===hash())positions[current.id]=Math.max(0,top||0);
  }
  function push(extra){
    capture();const previous=sync(),next={id:identity(),index:previous.index+1,hash:hash(),previousHash:previous.hash};
    positions[next.id]=positions[previous.id]||0;
    history.pushState({...history.state,...extra,[key]:next},'',location.href);current=next;return next;
  }
  function restore(target){
    const saved=history.state&&history.state[key];
    const next={...(valid(saved)?saved:current||{id:identity(),index:0,previousHash:''}),hash:target};
    const entry={...(history.state||{}),[key]:next};delete entry.__marketingOverlay;
    history.replaceState(entry,'',target);current=next;
  }
  sync();
  return {sync,push,restore,capture,scroll,position:()=>positions[sync().id]||0,canBack:()=>sync().index>0,previous:()=>sync().previousHash};
})();

// Overlay visits retain an immutable page descriptor. In-memory renderers make
// Back instant; registered read-only resolvers restore the same page after reload.
window.MarketingOverlay=(function(){
  const key='__marketingOverlay',cache=new Map(),resolvers=new Map();
  let active=null,closing=false,muting=false,pending=null,serial=0,restoring=null;
  const currentHash=()=>location.hash||'#/dashboard';
  const clone=value=>value?JSON.parse(JSON.stringify(value)):null;
  function allowed(){const p=parse();return p.view==='campaigns'&&/^prj-[a-f0-9]{16}$/.test(p.arg||'');}
  function roots(){return ['modalRoot','projectSidePanelRoot'].map(id=>document.getElementById(id)).filter(Boolean);}
  function capture(){
    if(!active)return;
    active.ui=roots().map(root=>({id:root.id,controls:Array.from(root.querySelectorAll('input,textarea,select')).map(el=>({tag:el.tagName,name:el.name||'',type:el.type||'',value:el.value,checked:el.checked,selectionStart:el.selectionStart,selectionEnd:el.selectionEnd})),details:Array.from(root.querySelectorAll('details')).map(el=>el.open),scroll:Array.from(root.querySelectorAll('*')).map((el,index)=>({index,top:el.scrollTop,left:el.scrollLeft})).filter(x=>x.top||x.left)}));
    try{sessionStorage.setItem('bookworld.overlay-state:'+active.token,JSON.stringify(active.ui));}catch(_){}
  }
  function restoreUI(item){
    if(active!==item)return;
    if(!item.ui)try{item.ui=JSON.parse(sessionStorage.getItem('bookworld.overlay-state:'+item.token)||'null');}catch(_){}
    for(const saved of item.ui||[]){
      const root=document.getElementById(saved.id);if(!root)continue;
      const controls=root.querySelectorAll('input,textarea,select');
      (saved.controls||[]).forEach((value,i)=>{const el=controls[i];if(!el||el.tagName!==value.tag||(el.name||'')!==value.name||(el.type||'')!==value.type||el.type==='file')return;el.value=value.value;if('checked'in el)el.checked=value.checked;if(typeof value.selectionStart==='number')try{el.setSelectionRange(value.selectionStart,value.selectionEnd);}catch(_){} });
      root.querySelectorAll('details').forEach((el,i)=>{if(typeof saved.details?.[i]==='boolean')el.open=saved.details[i];});
      const all=root.querySelectorAll('*');for(const value of saved.scroll||[]){const el=all[value.index];if(el){el.scrollTop=value.top;el.scrollLeft=value.left;}}
    }
  }
  function dismiss(){
    capture();const previous=active;active=null;muting=true;
    try{if(previous&&previous.cleanup)previous.cleanup();}
    finally{const root=document.getElementById('modalRoot');if(root)root.innerHTML='';muting=false;}
  }
  function metadata(item){return {token:item.token,hash:item.hash,depth:item.depth,descriptor:clone(item.descriptor)};}
  function open(name,render,cleanup,options={}){
    if(muting)return;
    if(!allowed()){render();return;}
    if(closing){pending=()=>open(name,render,cleanup,options);return;}
    const hash=currentHash(),stored=history.state&&history.state[key];
    const same=active&&active.hash===hash&&stored&&stored.token===active.token;
    const restoringEntry=options.restore&&stored?.hash===hash;
    if((same&&!options.step)||restoringEntry||options.replace&&stored?.hash===hash){
      const previous=active,item=same?active:cache.get(stored.token)||{token:stored.token,hash,depth:stored.depth||1};
      if(previous&&previous!==item||same&&item.name!==name)dismiss();else capture();
      Object.assign(item,{name,render,cleanup,descriptor:clone(options.descriptor||item.descriptor||stored.descriptor)});
      cache.set(item.token,item);active=item;history.replaceState({...history.state,[key]:metadata(item)},'',location.href);
      render();if(restoringEntry)restoreUI(item);return;
    }
    const depth=same&&options.step?(active.depth||1)+1:1;
    dismiss();
    const item={token:'marketing-detail-'+Date.now()+'-'+(++serial),name,hash,render,cleanup,depth,descriptor:clone(options.descriptor)};
    cache.set(item.token,item);active=item;
    AppHistory.push({[key]:metadata(item)});render();
  }
  function close(toRoot=false){
    if(muting)return false;
    const stored=history.state&&history.state[key];
    if(closing)return true;
    if(!active||!stored||stored.token!==active.token||active.hash!==currentHash()){dismiss();return false;}
    const steps=toRoot?active.depth||1:1;
    AppHistory.capture();dismiss();closing=true;if(steps>1)history.go(-steps);else history.back();return true;
  }
  function clear(){dismiss();restoring=null;}
  function sync(){
    AppHistory.sync();
    const stored=history.state&&history.state[key],hash=currentHash();
    const item=stored&&stored.hash===hash&&cache.get(stored.token);
    if(active&&(!item||active.token!==item.token))dismiss();
    if(state.lastHash===hash&&!active&&stored?.hash===hash){
      if(item){active=item;item.render();restoreUI(item);}
      else if(restoring!==stored.token){
        const resolver=resolvers.get(stored.descriptor?.type);
        if(resolver){
          restoring=stored.token;
          const isCurrent=()=>history.state?.[key]?.token===stored.token&&currentHash()===hash&&state.lastHash===hash;
          Promise.resolve(resolver(clone(stored.descriptor),{isCurrent,options:{restore:true}})).catch(err=>{if(isCurrent())toast('暂时无法恢复此页面：'+err.message,true);}).finally(()=>{if(restoring===stored.token)restoring=null;});
        }else{
          // Legacy entries have no durable descriptor. Skip their orphaned
          // overlay chain instead of leaving several invisible Back stops.
          const entry={...history.state};delete entry[key];history.replaceState(entry,'',location.href);
          const depth=Math.min(stored.depth||1,history.state?.__bookNav?.index||0);
          if(depth){closing=true;history.go(-depth);}
        }
      }
    }
    if(closing){closing=false;const next=pending;pending=null;if(next)setTimeout(next,0);}
  }
  function sourceOrigin(){
    const stored=history.state?.[key],descriptor=stored?.descriptor;
    if(!active||active.token!==stored?.token||stored.hash!==currentHash()||descriptor?.type!=='video-prompts'||descriptor.stage!=='handoff')return null;
    return clone({overlay:stored,visit:AppHistory.sync()});
  }
  function sourceReturn(){
    const p=parse(),origin=history.state?.__marketingSourceReturn,descriptor=origin?.overlay?.descriptor;
    if(p.view!=='campaigns'||p.tab!=='sources'||descriptor?.type!=='video-prompts'||descriptor.stage!=='handoff'||descriptor.projectId!==p.arg||!descriptor.runId||!['image','video'].includes(descriptor.mode))return null;
    if(!origin.overlay.hash?.startsWith('#/campaigns/'+encodeURIComponent(p.arg))||!Number.isInteger(origin.visit?.index))return null;
    return clone(origin);
  }
  function returnToSourceOrigin(){
    if(closing)return true;
    const origin=sourceReturn();if(!origin)return false;
    const current=AppHistory.sync(),steps=current.index-origin.visit.index;
    if(steps<=0)return false;
    AppHistory.capture();dismiss();closing=true;history.go(-steps);return true;
  }
  function deferNavigation(next){
    if(muting)return false;
    if(closing){pending=next;return true;}
    // Navigating to sources is a new visit after this overlay. Do not pop its
    // predecessors, otherwise pushing the source URL destroys the return path.
    if(active&&active.hash===currentHash()){AppHistory.capture();dismiss();}
    return false;
  }
  return {open,close,clear,sync,capture,sourceOrigin,sourceReturn,returnToSourceOrigin,deferNavigation,register:(type,resolver)=>resolvers.set(type,resolver),isOpen:()=>!!active,isClosing:()=>closing};
})();

// tab 可选：从哪个入口进来，就落到那个页签（'assets' / 'records' / 'tags' / 'text'）
// 不带 tab 时一律回「概览」，不再沿用上一次残留的 state.detailTab
function go(view,arg,tab,q,options={}){
  AppHistory.capture();
  if(window.MarketingOverlay&&MarketingOverlay.deferNavigation(()=>go(view,arg,tab,q,options)))return;
  let h='#/'+view;
  if(arg!==undefined&&arg!=='')h+='/'+encodeURIComponent(arg);
  if(tab)h+='/'+encodeURIComponent(tab);
  if(q)h+='/'+encodeURIComponent(q);   // 第四段：资产筛选词 / 原文锚点
  if(state.lastHash===location.hash)state.scroll[state.lastHash]=window.scrollY;
  state.depth++;
  if(location.hash===h){
    state.depth--;
    if(options.sourceReturn){
      // Sources may already be the page below the dialog. Keep the handoff
      // visit and add a separate, ordinary source visit even at the same URL.
      AppHistory.push({__marketingOverlay:null,__marketingSourceReturn:options.sourceReturn});route({navigation:true});
    }
    return;
  }
  state.fromGo=true;location.hash=h;AppHistory.sync();
  if(options.sourceReturn)history.replaceState({...history.state,__marketingSourceReturn:options.sourceReturn},'',location.href);
}

// 「从工作台点进一本书」时，先把父级（来源图书）压进历史。
// 这样按后退回到的是来源图书，而不是跨过层级直接掉回工作台。
function openBook(code){
  // 父级按真实来路记：从工作台进来就回工作台，从来源图书进来就回来源图书。
  // 之前为了「浏览器后退别回首页」硬塞了一层 #/library，结果面包屑写的是来源图书，
  // 人却以为自己是从工作台进来的——来路被改写了。
  go('book',code);
}

function parentOf(view){
  return {book:'library',card:'content',kes:'library',ents:'library',review:'book',job:'tasks',apps:'dashboard',qa:'apps',marketing:'content',editor:'dashboard',hotspot:'records',relations:'apps',kg:'relations',kglab:'relations',output:'content',report:'library','creator-match':'marketing-tools','xhs-writing':'marketing-tools'}[view]||'dashboard';
}

function navBack(){
  // Back follows visits in every module; hierarchy is only a deep-link fallback.
  const cur=parse();
  if(window.MarketingOverlay&&MarketingOverlay.isClosing())return;
  if(window.MarketingOverlay&&MarketingOverlay.isOpen()){MarketingOverlay.close();return;}
  AppHistory.capture();
  if(AppHistory.canBack()){history.back();return;}
  if(cur.view==='dashboard') return;
  if(cur.view==='campaigns'){
    if(!cur.arg){go('dashboard');return;}
    if(cur.arg==='new'){go('campaigns');return;}
    const parent={materials:'task',results:'materials',review:'results',sources:'results',history:'results'}[cur.tab];
    if(parent)go('campaigns',cur.arg,parent);else go('records','marketing');
    return;
  }
  const context=workflowContext();if(context&&WORKFLOW_TOOLS.includes(cur.view)){go(context.view,context.id,context.section);return;}
  if(cur.view==='records'&&cur.arg){go('records');return;}
  if(cur.view==='editor'){go(cur.arg?'content':'dashboard');return;}
  if(['projects','campaigns'].includes(cur.view)&&cur.arg){
    const active=document.querySelector('#projectNav .project-nav-item.on')?.dataset.function;
    const kind=['editorial','marketing'].includes(active)?active:cur.view==='campaigns'?'marketing':'editorial';
    if(window.ProjectRecords)ProjectRecords.returnToList(kind);else go('records',kind);return;
  }
  const prev=state.navPrev;
  const known=new Set(['dashboard','library','archive','assets','search','tasks','apps','qa','relations','kg','kglab','settings','trash','card','kes','ents','review','output','marketing','editor','report','projects','campaigns','records','content']);
  if(cur.view==='review'){ go('book',cur.arg||''); return; }
  if(cur.view==='book' && prev && known.has(prev.view) && prev.view!=='book'){
    go(prev.view, prev.arg||undefined);
    return;
  }
  go(parentOf(cur.view));
}
window.marketingBackTo=function(parentStep){
  const cur=parse();
  if(window.MarketingOverlay?.isOpen()||AppHistory.canBack()){navBack();return;}
  if(cur.view==='campaigns'&&cur.arg&&cur.arg!=='new'&&parentStep)go('campaigns',cur.arg,parentStep);
  else navBack();
};
function parse(hash){
  const h=(hash===undefined?location.hash:hash||'').replace(/^#\/?/,'');
  if(!h)return{view:'dashboard',arg:'',tab:''};
  const p=h.split('/');
  // 书详情把第三段当页签；其他视图的 arg 允许含 `/`（如检索词），整段保留
  if(p[0]==='book'){
    // 原文锚点可带「来意」：...#/book/B59/text/B59-02-P08?t=《四库全书》&k=cite&n=14
    // 先按 ? 切开再解码：参数值里的 & 已经过 URL 编码，不会被当成分隔符。
    // 这样刷新、分享、后退回来，高亮和横幅都还在，不会退化成「已定位到某人第 8 段」。
    let raw=p[3]||'', extra=null;
    const qi=raw.indexOf('?');
    if(qi>=0){extra=new URLSearchParams(raw.slice(qi+1));raw=raw.slice(0,qi);}
    return{view:'book',arg:decodeURIComponent(p[1]||''),tab:decodeURIComponent(p[2]||''),q:decodeURIComponent(raw),extra};
  }
  if(p[0]==='card')return{view:'card',arg:decodeURIComponent(p[1]||''),tab:'',q:decodeURIComponent(p[2]||'')};
  if(p[0]==='kes')return{view:'kes',arg:decodeURIComponent(p[1]||''),tab:'',q:''};
  if(p[0]==='ents')return{view:'ents',arg:decodeURIComponent(p[1]||''),tab:decodeURIComponent(p[2]||''),q:''};
  if(p[0]==='tasks')return{view:'tasks',arg:'',tab:p[1]==='records'?'records':'',q:''};
  if(p[0]==='report'||p[0]==='marketing'){
    const qi=h.indexOf('?'),parts=(qi<0?h:h.slice(0,qi)).split('/');
    return{view:p[0],arg:decodeURIComponent(parts[1]||''),tab:'',q:'',...(qi<0?{}:{extra:new URLSearchParams(h.slice(qi+1))})};
  }
  if(p[0]==='review')return{view:'review',arg:decodeURIComponent(p[1]||''),tab:'',q:decodeURIComponent(p[2]||'')};
  if(p[0]==='editor')return{view:'editor',arg:decodeURIComponent(p[1]||''),tab:decodeURIComponent(p[2]||''),q:''};
  if(['projects','campaigns'].includes(p[0].split('?')[0])){
    const qi=h.indexOf('?'),parts=(qi<0?h:h.slice(0,qi)).split('/');
    return{view:parts[0],arg:decodeURIComponent(parts[1]||''),tab:decodeURIComponent(parts[2]||''),q:'',...(qi<0?{}:{extra:new URLSearchParams(h.slice(qi+1))})};
  }
  return{view:p[0],arg:decodeURIComponent(p.slice(1).join('/')),tab:'',q:''};
}
function workflowContext(){try{const c=JSON.parse(sessionStorage.getItem('workflowContext')||'null');return c&&['projects','campaigns'].includes(c.view)&&/^prj-[a-f0-9]{16}$/.test(c.id)?c:null;}catch(_){return null;}}
const WORKFLOW_TOOLS=['hotspot','marketing','relations','kg','kglab','editor','book','review'];
const RELATION_VIEWS=['relations','kg','kglab'];
function saveWorkflowContext(context,rememberVisit){
  if(rememberVisit)history.replaceState({...history.state,relationProject:context},'');
  try{
    if(context)sessionStorage.setItem('workflowContext',JSON.stringify(context));
    else sessionStorage.removeItem('workflowContext');
  }catch(_){}
}
function rememberWorkflowContext(view){
  const relationVisit=RELATION_VIEWS.includes(view);
  const globalEntry=state.globalFunctionNavigation;state.globalFunctionNavigation=null;
  if(globalEntry){
    const destination=parse();
    if(destination.view===globalEntry.view&&destination.arg===globalEntry.arg){
      saveWorkflowContext(null,relationVisit);
      return;
    }
  }
  // Returning through browser history restores the project from this visit.
  if(relationVisit&&Object.hasOwn(history.state||{},'relationProject')){
    saveWorkflowContext(history.state.relationProject,false);
    return;
  }
  const prev=state.curView;
  const picker=document.getElementById('contentProjectContext');
  if(WORKFLOW_TOOLS.includes(view)&&prev&&['projects','campaigns'].includes(prev.view)&&/^prj-[a-f0-9]{16}$/.test(prev.arg||'')){
    const title=document.querySelector('#view .marketing-project-name, #view .project-name-row h1')?.textContent||'当前策划';
    saveWorkflowContext({view:prev.view,id:prev.arg,title,section:parse(state.lastHash).tab},relationVisit);
  }else if(WORKFLOW_TOOLS.includes(view)&&prev&&prev.view==='content'&&picker&&/^prj-[a-f0-9]{16}$/.test(picker.dataset.projectId||'')){
    saveWorkflowContext({view:picker.dataset.projectKind==='marketing'?'campaigns':'projects',id:picker.dataset.projectId,title:picker.dataset.projectTitle||'当前策划',section:'materials'},relationVisit);
  }else if(relationVisit){
    saveWorkflowContext(prev&&WORKFLOW_TOOLS.includes(prev.view)?workflowContext():null,true);
  }else if(!WORKFLOW_TOOLS.includes(view))saveWorkflowContext(null,false);
}
function showWorkflowReturn(v,view){
  const c=workflowContext();if(!c||!WORKFLOW_TOOLS.includes(view)||parse().view!==view||v.querySelector('.workflow-return'))return;
  v.insertAdjacentHTML('afterbegin','<div class="workflow-return"><span>正在为 <b>'+esc(c.title)+'</b> 查找与核对内容</span><button type="button" class="btn sm ghost" data-view="'+esc(c.view)+'" data-id="'+esc(c.id)+'" data-section="'+esc(c.section||'')+'" onclick="go(this.dataset.view,this.dataset.id,this.dataset.section)">返回当前策划 →</button></div>');
}
window.ProjectNav=(function(){
  const functions={editorial:['records','editorial'],marketing:['campaigns','']};
  const validId=id=>/^prj-[a-f0-9]{16}$/.test(id||'');
  let resolvedProject=null;
  function activate(kind){
    document.querySelectorAll('#projectNav .project-nav-item').forEach(function(button){
      const on=button.dataset.function===kind;button.classList.toggle('on',on);
      if(on)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
  }
  function clear(){activate('');}
  function update(project,section){
    const p=parse();
    if(!project||!validId(project.id)||!['editorial','marketing'].includes(project.kind)||!['projects','campaigns'].includes(p.view)||p.arg!==project.id)return;
    resolvedProject={id:project.id,kind:project.kind};activate(project.kind);
  }
  function sync(){
    const p=parse();let kind='',inside=false;
    if(p.view==='records'){
      inside=true;if(['editorial','marketing'].includes(p.arg))kind=p.arg;
    }else if(p.view==='campaigns'&&(!p.arg||p.arg==='new')){
      inside=true;kind='marketing';
    }else if(['projects','campaigns'].includes(p.view)&&validId(p.arg)){
      inside=true;if(resolvedProject&&resolvedProject.id===p.arg)kind=resolvedProject.kind;
    }else{
      const pick=p.view==='content'&&/^pick:(prj-[a-f0-9]{16})(?::[A-Za-z0-9_-]+)?$/.exec(p.arg||'');
      const flow=workflowContext();
      if(pick){
        inside=true;const picker=document.getElementById('contentProjectContext');
        if(picker&&picker.dataset.projectId===pick[1]&&['editorial','marketing'].includes(picker.dataset.projectKind))kind=picker.dataset.projectKind;
        else if(resolvedProject&&resolvedProject.id===pick[1])kind=resolvedProject.kind;
        else if(flow&&flow.id===pick[1])kind=flow.view==='campaigns'?'marketing':'editorial';
      }else if(WORKFLOW_TOOLS.includes(p.view)&&flow){
        inside=true;kind=resolvedProject&&resolvedProject.id===flow.id?resolvedProject.kind:flow.view==='campaigns'?'marketing':'editorial';
      }
    }
    if(!inside)resolvedProject=null;
    activate(kind);return inside;
  }
  function open(el){
    const key=el.dataset.function;if(!Object.prototype.hasOwnProperty.call(functions,key))return;
    const target=functions[key];
    state.globalFunctionNavigation={view:target[0],arg:target[1]};
    try{sessionStorage.removeItem('workflowContext');}catch(_){}
    go(target[0],target[1]);
  }
  return {update,clear,sync,open};
})();

window.AppsNav=(function(){
  const nav=document.getElementById('appsNav');
  if(nav)nav.innerHTML=APPS_LIVE.map(a=>`<button type="button" class="project-nav-item" data-app="${esc(a.key)}" onclick="AppsNav.open(this)"><span class="project-nav-dot" aria-hidden="true"></span><span>${esc(a.name)}</span></button>`).join('');
  function sync(view,projectContext){
    const key=['relations','kglab'].includes(view)?'kg':view;
    document.querySelectorAll('#appsNav .project-nav-item').forEach(button=>{
      const on=!projectContext&&button.dataset.app===key;
      button.classList.toggle('on',on);
      if(on)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
  }
  function open(el){
    const app=APPS_LIVE.find(a=>a.key===el.dataset.app);if(!app)return;
    if(location.hash==='#/'+app.path&&!workflowContext())return;
    state.globalFunctionNavigation={view:app.path,arg:''};
    try{sessionStorage.removeItem('workflowContext');}catch(_){}
    if(location.hash==='#/'+app.path){route({navigation:true});return;}
    go(app.path);
  }
  return {sync,open};
})();

function setNav(v){
  const map={dashboard:'dashboard',library:'library',book:'library',card:'content',kes:'library',ents:'library',tasks:'tasks',job:'tasks',assets:'library',archive:'tasks',search:'content',output:'content',marketing:'apps',editor:'dashboard',apps:'apps',qa:'apps',hotspot:'apps',relations:'apps',kg:'apps',kglab:'apps',settings:'settings',trash:'trash',report:'library',projects:'records',campaigns:'records',records:'records','creator-match':'marketing-tools','xhs-writing':'marketing-tools'};
  const projectContext=ProjectNav.sync();
  AppsNav.sync(v,projectContext);
  const cur=projectContext?'records':v==='editor'&&parse().arg?'content':map[v]||v;
  document.querySelectorAll('.nav-item').forEach(x=>{
    const on=x.dataset.view===cur;
    x.classList.toggle('on',on);
    if(on&&(cur!=='marketing-tools'||v===cur))x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');
  });
  document.querySelectorAll('#marketingToolsNav .project-nav-item').forEach(link=>{
    const on=link.getAttribute('href')==='#/'+v;
    link.classList.toggle('on',on);
    if(on)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  });
  const el=document.querySelector('.nav-item.on');if(el){const group=el.closest('details');if(group)group.open=true;el.scrollIntoView({block:'nearest'});}
}

function crumb(html){
  const {view}=parse();
  const back = view==='dashboard' ? ''
    : `<button class="crumb-back" onclick="navBack()" title="返回上一页" aria-label="返回">←</button>`;
  document.getElementById('crumb').innerHTML = back + html;
}
// Async page work owns both a route visit and its mounted DOM node. A later
// visit to the same URL is a different request and cannot accept an old response.
function capturePageRequest(v){
  const request=state.routeRequest,hash=location.hash||'#/dashboard';
  return ()=>request===state.routeRequest&&(location.hash||'#/dashboard')===hash&&document.getElementById('view')===v;
}
async function route(options={}){
  const request=state.routeRequest=(state.routeRequest||0)+1;
  const requestedHash=location.hash||'#/dashboard';
  const isCurrent=()=>request===state.routeRequest&&(location.hash||'#/dashboard')===requestedHash;
  try{
    if(window.MarketingEntry&&MarketingEntry.beforeNavigate)await MarketingEntry.beforeNavigate();
    if(!isCurrent())return;
    if(window.Studio)await Studio.beforeNavigate();
  }catch(err){
    if(!isCurrent())return;
    state.globalFunctionNavigation=null;
    if(state.lastHash)AppHistory.restore(state.lastHash);
    toast('保存未完成：'+err.message,true);return;
  }
  if(!isCurrent())return;
  AppHistory.sync();
  if(state.lastHash&&state.lastHash!==requestedHash&&window.MarketingOverlay)MarketingOverlay.clear();
  clearJobTimer();
  state.pinTerm=''; state.pinMode=''; state.pinTotal=0; state.pinFrom=''; state.pinFocus=false;   // 换页就清掉上一页的高亮词与来意，避免串页
  const {view,arg,tab,q,extra}=parse(requestedHash);
  if(view==='projects'&&!arg){AppHistory.restore('#/records/editorial');return route();}
  rememberWorkflowContext(view);
  const newHash = location.hash || '#/dashboard';
  const returnScroll = AppHistory.position();
  // 离开一个页面时记住滚动位置，回来时还原（列表页尤其明显）
  // Scroll is captured before changing the hash; hash navigation can already reset window.scrollY here.
  state.navPrev = state.curView;
  state.curView = {view,arg};
  state.lastHash = newHash;
  setNav(view);
  let v=document.getElementById('view');
  const sameProject=options.navigation&&['campaigns','projects'].includes(view)&&state.navPrev?.view===view&&state.navPrev?.arg===arg&&v.querySelector('.project-section-panel');
  if(!sameProject){
    // Give each page visit its own host. Late renderers may still finish, but
    // their retained node is detached and cannot overwrite the current page.
    const next=v.cloneNode(false);next.removeAttribute('data-project-section');v.replaceWith(next);v=next;
  }
  if(view!=='kg'&&window.KG)window.KG.destroy();
  if(view!=='kglab'&&window.KGLAB)window.KGLAB.destroy();
  v.className='view';
  const restore=()=>{ if(state.pin||!isCurrent())return; window.scrollTo({top:returnScroll,behavior:'instant'}); };
  try{
    if(view==='editor'&&!arg&&window.ReviewHub){await ReviewHub.render(v);return;}
    if(view==='records'&&window.ProjectRecords){await ProjectRecords.render(v,arg);return;}
    if(window.Studio && ['dashboard','content','projects','campaigns'].includes(view)){await Studio.render(v,view,arg,tab,{preserve:!!options.navigation});return;}
    v.classList.remove('studio-view');
    if(view==='dashboard'){crumb('<span>工作台</span>');await renderDashboard(v);return;}
    if(view==='library'){crumb('<span>数据资产</span><span>/</span><b>来源图书</b>');await renderLibrary(v);return;}
    if(view==='book'){await renderBook(v,arg,tab,q,extra);return;}
    if(view==='card'){await renderCard(v,arg,q);return;}
    if(view==='kes'){await renderKes(v,arg);return;}
    if(view==='ents'){await renderEnts(v,arg,tab);return;}
    if(view==='report'){await renderReport(v,arg);return;}
    if(view==='review'){await renderReview(v,arg,q);return;}
    if(view==='tasks'){crumb('<span>数据资产</span><span>/</span><b>运行任务</b>'+(tab==='records'?'<span>/</span><b>记录</b>':''));await renderTasks(v,tab);return;}
    if(view==='job'){crumb('<span>数据资产</span><span>/</span><a onclick="go(\'tasks\')">入库任务</a><span>/</span><b>任务详情</b>');await viewJob(arg);return;}
    // 「知识资产」不再是独立页面：资产总量并入工作台与来源图书页头，旧链接统一落到来源图书
    if(view==='assets'){location.replace('#/library');return;}
    // 「图书档案」并进「运行任务」的第二页签，旧链接直接跳过去
    if(view==='archive'){location.replace('#/tasks/records');return;}
    if(view==='output'){crumb('<span>数据资产</span><span>/</span><b>资产产出</b>');await renderOutput(v,arg);return;}
    if(view==='marketing'){crumb('<a href="#/content">内容成果</a><span>/</span><b>图书营销资料</b>');await renderMarketing(v,arg);return;}
    if(view==='editor'){crumb('<span>应用</span><span>/</span><b>资料整理</b>');await renderEditor(v,arg,tab);return;}
    if(view==='search'){crumb('<b>跨书搜索</b>');await renderSearch(v,arg);return;}
    if(view==='relations'){crumb('<a href="#/apps">内容应用</a><span>/</span><b>关系探索</b>');renderRelations(v);return;}
    if(view==='kg'||view==='kglab'){
      const graph=view==='kg';
      crumb('<a href="#/relations">关系探索</a><span>/</span><b>'+(graph?'关系图谱':'查人物与关系')+'</b>');
      const rendering=(graph?window.KG:window.KGLAB).render(v,arg);
      showWorkflowReturn(v,view);
      await rendering;
      return;
    }
    if(view==='apps'){crumb('<span>内容工作空间</span><span>/</span><b>内容应用</b>');await renderApps(v,arg);return;}
    if(view==='qa'){crumb('<a href="#/apps">内容应用</a><span>/</span><b>智能问答</b>');await window.BookQA.render(v,arg);return;}
    if(view==='marketing-tools'){crumb('<b>营销工具</b>');renderMarketingTools(v);return;}
    if(view==='creator-match'){crumb('<a href="#/marketing-tools">营销工具</a><span>/</span><b>图书达人匹配</b>');await window.CreatorMatch.render(v,arg);return;}
    if(view==='xhs-writing'){crumb('<a href="#/marketing-tools">营销工具</a><span>/</span><b>小红书笔记</b>');await window.XhsWriting.render(v);return;}
    if(view==='hotspot'){crumb('<a href="#/records/marketing">营销策划</a><span>/</span><b>热点匹配</b>');await renderHotspot(v,arg);return;}
    if(view==='settings'){crumb('<span>平台管理</span><span>/</span><b>解析设置</b>');await renderSettings(v);return;}
    if(view==='trash'){crumb('<span>系统</span><span>/</span><b>回收站</b>');await renderTrash(v);return;}
    go('dashboard');
  } finally {
    if(isCurrent()){
      ProjectNav.sync();showWorkflowReturn(v,view);
      if(window.MarketingOverlay)MarketingOverlay.sync();
      if(view==='creator-match')restore();
      else setTimeout(restore,200);
    }
  }
}

/* ================= 工作台 ================= */
function weekNewBooks(){
  const t=Date.now()-7*864e5;
  return state.books.filter(b=>{const d=Date.parse(b.added_at||'');return !isNaN(d)&&d>=t;}).length;
}

// 一本书的状态徽标：有知识类成果 → 分类；没有但有编校活 → 待编校；编校做完了 → 编校完成；都没有 → 0 条可交付
function outBadge(b,ed){
  if(b.cards>0&&!b.knowledge){
    if(ed&&ed.total){
      return `<span class="badge amber" style="cursor:pointer" title="自动抽取此类条目尚未生成，请到内容成果查看其他成果；篇目和引文要人在资料整理补完" data-c="${esc(b.code)}" onclick="event.stopPropagation();go('editor',this.dataset.c)">待编校 ${num(ed.total)}</span>`;
    }
    if(ed&&ed.done){
      return `<span class="badge green" title="编校完成，文献线索清单 / 篇章表已可导出">编校完成</span>`;
    }
    return `<span class="badge red" title="解析完成但没有知识类成果">0 条可交付</span>`;
  }
  return pill(b.prototype);
}
async function renderDashboard(v){
  const isCurrent=capturePageRequest(v);
  await refreshBooks();if(!isCurrent())return;
  let kinds={知识:0,索引:0};
  try{kinds=(await jget('/api/assets?limit=1')).by_kind||kinds;}catch(e){}
  const s=state.stats||{};
  const week=weekNewBooks();
  const recent=state.books.slice().sort((a,b)=>(b.added_at||'').localeCompare(a.added_at||'')).slice(0,5);
  let ep={books:[]};
  try{ep=await jget('/api/editor/pending');}catch(e){}
  const editMap={};
  (ep.books||[]).forEach(b=>{editMap[b.code]=b;});
  const zero=state.books.filter(b=>b.cards>0&&!b.knowledge);
  // 自动抽取没有知识类成果、但有篇目/引文等人编校的书，是「待编校」而不是「失败」
  const trueGap=zero.filter(b=>!editMap[b.code]);
  const editAll=state.books.filter(b=>editMap[b.code]&&editMap[b.code].total>0);
  const editPending=editAll.reduce((n,b)=>n+((editMap[b.code]||{}).total||0),0);
  if(!isCurrent())return;v.innerHTML=`
    <div class="page-head">
      <div><div class="eyebrow">Workbench</div><h1>工作台</h1>
        <p>${editAll.length?`有 <b>${num(editAll.length)}</b> 本书还需要补充资料。`:'可以查看最近入库的图书和已整理内容。'}</p></div>
      <div class="head-actions"><button class="btn ghost" onclick="go('output')">资产产出</button><button class="btn primary" onclick="go('tasks')">＋ 上传图书</button></div>
    </div>
    <div class="kpis">
      <div class="kpi click" onclick="go('library')"><div class="k">图书资产</div><div class="v">${num(state.books.length)}</div><div class="d">本周新增 ${num(week)} 本 · 分类待确认 ${num(s.pending||0)} 本</div></div>
      <div class="kpi click" onclick="go('output')"><div class="k">知识类成果</div><div class="v">${num(s.knowledge||kinds.知识||0)}</div><div class="d">索引类 ${num(s.index||kinds.索引||0)} 条（只能定位，不算交付）</div></div>
      <div class="kpi"><div class="k">待核对条目</div><div class="v">${num(s.review||0)}</div><div class="d"><a class="lnk" onclick="go('output','todo')">查看条目</a></div></div>
      <div class="kpi click" onclick="go('apps')"><div class="k">已接入应用</div><div class="v">${APPS_LIVE.length}<span class="den"> / ${APPS.length}</span></div><div class="d">${APPS_LIVE.map(a=>a.name).join(' · ')}</div></div>
    </div>
      <section class="panel">
        <div class="panel-head"><div><h2>最近入库</h2><div class="sub">一眼看出哪本「完成了但没东西」</div></div><a onclick="go('library')">来源图书 →</a></div>
        <div class="recent">
          ${recent.map(b=>`<div class="recent-row" onclick="go('book','${esc(b.code)}')">
            <div class="mini-cover">${esc(coverChar(b.book))}</div>
            <div class="recent-main"><b>${esc(b.book)}</b><span>${esc(b.author||'作者未填写')} · ${num(b.segments)} 段 · 知识 ${num(b.knowledge||0)} · 索引 ${num(b.index||0)}</span></div>
            ${outBadge(b,editMap[b.code])}${status(b)}
          </div>`).join('')}
        </div>
      </section>
    <div class="grid-2 lower">
      <section class="panel">
        <div class="panel-head"><div><h2>资产产出</h2><div class="sub">能直接交出去的只有两种：结构化数据 / 人物卡；引文和篇目是编辑手工活，在资料整理</div></div><a onclick="go('output')">去资产产出 →</a></div>
        <div class="panel-body">
          <div class="tri-row">
            <div class="tri"><span>知识</span><b>${num(kinds.知识||0)}</b><em>能当内容用</em></div>
            <div class="tri idx"><span>索引</span><b>${num(kinds.索引||0)}</b><em>只能定位</em></div>
            <div class="tri gap"><span>待编校</span><b>${num(editAll.length)}</b><em>本 · ${num(editPending)} 条要人补</em></div>
          </div>
          ${editAll.length?`<div class="todo-row" style="margin-top:10px"><div class="todo-main"><b>${editAll.map(b=>esc(b.book)).join('、')}</b><span>这些书的篇目主旨和引文判定还没补完；补完才出文献线索清单 / 篇章表</span></div><button class="btn sm" data-code="${esc(editAll[0].code)}" onclick="go('editor',this.dataset.code)">去编校</button></div>`:''}
          ${trueGap.length?`<div class="todo-row" style="margin-top:10px"><div class="todo-main"><b>${trueGap.map(b=>esc(b.book)).join('、')}</b><span>解析完成，知识类成果 0 条，也没有可编校的篇目/引文 · 看解析报告定位原因</span></div><button class="btn sm" data-code="${esc(trueGap[0].code)}" onclick="go('report',this.dataset.code)">看报告</button></div>`:''}
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h2>应用入口</h2><div class="sub">只列能点进去干活的；未接入的见应用中心</div></div><a onclick="go('apps')">应用中心 →</a></div>
        <div class="apps-list">${APPS_LIVE.map(a=>`<div class="app-row" onclick="go('${a.path}')"><span class="app-ico">${a.ico}</span><div class="app-main"><b>${a.name}</b><span>${a.desc}</span></div><span class="status ok">${a.status}</span></div>`).join('')}</div>
      </section>
    </div>`;
  paintNavCounts();
}

/* ================= 应用中心 ================= */
function renderApps(v,focus){
  const live=APPS_LIVE.filter(a=>a.key!=='qa'), soon=APPS.filter(a=>!a.path);
  v.classList.add('apps-center');
  v.innerHTML=`
    <div class="page-head"><div><div class="eyebrow">BOOK WORLD / APPLICATIONS</div><h1>内容应用</h1>
      <p>让书中的知识，成为解决问题的工具。选一个任务，从这里开始。</p></div><span class="apps-count">${APPS_LIVE.length} 个应用可使用</span></div>
    <section class="apps-qa-feature ${focus==='qa'?'focus':''}" id="app-qa" aria-labelledby="appsQaTitle">
      <div class="apps-qa-copy"><div class="apps-feature-label"><span></span> 智能问答 · 从问题出发</div>
        <h2 id="appsQaTitle">有问题，<br>向你的书库提问。</h2><p>理解一个概念，找到一段原文，比较不同观点。<br>把书里的线索，整理成有出处的答案。</p>
        <button class="btn primary" type="button" onclick="go('qa')">开始提问 <span aria-hidden="true">↗</span></button>
        <div class="apps-feature-meta"><span>可选择图书</span><span>可回查原文</span><span>新入库图书自动纳入</span></div>
      </div>
      <div class="apps-qa-art" aria-hidden="true"><div class="apps-orbit apps-orbit-a"></div><div class="apps-orbit apps-orbit-b"></div><div class="apps-orbit apps-orbit-c"></div><div class="apps-core">◈</div><span class="apps-orbit-label apps-label-a">一个问题</span><span class="apps-orbit-label apps-label-b">书中依据</span><span class="apps-orbit-label apps-label-c">新的理解</span><i class="apps-star s1"></i><i class="apps-star s2"></i><i class="apps-star s3"></i></div>
    </section>
    <div class="apps-section-title"><h2>继续探索书中的价值</h2><span>找关系 · 找话题 · 找表达</span></div>
    <div class="app-grid">
      ${live.map(a=>`<section class="app-card ${focus===a.key?'focus':''}" id="app-${a.key}">
        <div class="app-card-h"><span class="app-card-ico">${a.ico}</span><span class="status ok">可使用</span></div>
        <h3>${a.name}</h3><p>${a.desc}</p>
        <div class="app-req">${a.need.map(x=>`<span>${x}</span>`).join('')}</div>
        <div class="app-card-f"><button type="button" class="btn sm" onclick="go('${a.path}')">打开${a.name} <span aria-hidden="true">↗</span></button></div>
      </section>`).join('')}
    </div>
    <details class="apps-api-details"><summary><span><b>接口与扩展</b><small>供需要连接其他系统的团队查看</small></span><span class="apps-expand" aria-hidden="true">＋</span></summary>
      <div class="apps-api-content"><p>以下接口供当前工作空间使用，沿用应用的访问控制。</p><div class="api-grid">
        ${[['GET /api/books','图书列表与统计'],['GET /api/book','图书档案与原文'],['GET /api/book/segment','原文定位与上下文'],['GET /api/search','跨书检索'],['GET /api/qa/status','可提问的图书范围'],['POST /api/qa/ask','图书问答与引用依据']].map(([m,d])=>`<div class="api-row"><code>${m}</code><span>${d}</span><em class="status ok">已接入</em></div>`).join('')}
      </div>${soon.length?`<div class="apps-planned">${soon.map(a=>`<p><b>${a.name} · 规划中</b><span>${a.desc}</span></p>`).join('')}</div>`:''}</div>
    </details>`;
  if(focus){const el=document.getElementById('app-'+focus);if(el)el.scrollIntoView({block:'center'});}
}

function renderMarketingTools(v){
  v.innerHTML=`
    <div class="page-head"><div><h1>营销工具</h1></div></div>
    <div class="relations-choices">
      <a class="relations-choice" href="#/creator-match" aria-labelledby="marketingToolCreator" aria-describedby="marketingToolCreatorDesc">
        <span class="relations-icon"><svg class="icon" aria-hidden="true"><use href="#i-search"></use></svg></span>
        <h2 id="marketingToolCreator">图书达人匹配</h2>
        <p id="marketingToolCreatorDesc">根据图书主题、读者和推广目标寻找合适的达人，查看匹配依据。</p>
        <span class="relations-cta">查找达人 <span aria-hidden="true">→</span></span>
      </a>
      <a class="relations-choice" href="#/xhs-writing" aria-labelledby="marketingToolXhs" aria-describedby="marketingToolXhsDesc">
        <span class="relations-icon"><svg class="icon" aria-hidden="true"><use href="#i-editor"></use></svg></span>
        <h2 id="marketingToolXhs">小红书笔记</h2>
        <p id="marketingToolXhsDesc">用图书资料生成笔记文案，回查依据并在线改稿。</p>
        <span class="relations-cta">开始创作 <span aria-hidden="true">→</span></span>
      </a>
    </div>`;
}

function renderRelations(v){
  v.innerHTML=`
    <div class="page-head relations-heading"><div><h1>关系探索</h1>
      <p>找人物关系、事件与工程、概念与案例。选中一条关系，可核对出处并收入项目材料。</p></div></div>
    <div class="relations-choices">
      <a class="relations-choice" href="#/kglab" aria-labelledby="relationsSearch" aria-describedby="relationsSearchDesc">
        <span class="relations-icon"><svg class="icon" aria-hidden="true"><use href="#i-search"></use></svg></span>
        <h2 id="relationsSearch">查人物与关系</h2>
        <p id="relationsSearchDesc">已有查找目标时，输入人物、事件、概念或书名，直接找相关对象和原文。</p>
        <p class="relations-example">例如，搜「钱塘江大桥」，看看书里写了谁主持修建、谁受命修复。</p>
        <span class="relations-cta">开始查找 <span aria-hidden="true">→</span></span>
      </a>
      <a class="relations-choice" href="#/kg" aria-labelledby="relationsGraph" aria-describedby="relationsGraphDesc">
        <span class="relations-icon"><svg class="icon" aria-hidden="true"><use href="#i-kg"></use></svg></span>
        <h2 id="relationsGraph">浏览关系图谱</h2>
        <p id="relationsGraphDesc">选书浏览图谱，点一个对象即可切换关系列表与局部图，查看它和哪些人或事有关。</p>
        <p class="relations-example">例如，在《乡土中国》里选「差序格局」，看看作者用了哪些例子来说明它。</p>
        <span class="relations-cta">打开图谱 <span aria-hidden="true">→</span></span>
      </a>
    </div>`;
}

/* ================= 来源图书 ================= */
async function renderLibrary(v){
  const isCurrent=capturePageRequest(v);
  v.innerHTML=loading('加载图书列表');
  await refreshBooks();if(!isCurrent())return;
  // 抽取量按书现算：出版 / 结构 / 内容 / 事实 / 金句 / 营销
  const stats={};
  await Promise.all((state.books||[]).map(async b=>{
    const z={pub:0,page:0,ent:0,fact:0,quote:0,mk:0,entc:{}};
    try{
      const d=await jget('/api/book?code='+encodeURIComponent(b.code));
      const items=(d.publication||{}).items||{};
      z.pub=Object.values(items).filter(x=>x&&(x.status==='found'||x.status==='needs_review')).length;
      z.page=((d.page_roles||{}).roles||[]).filter(x=>x&&x.status==='found').length;
      z.fact=((((d.deep||{}).items||{}).facts||{}).value||[]).length;
      z.quote=((d.understanding||{}).quotes||[]).length;
      z.mk=Object.keys((d.marketing||{}).items||{}).length;
      const e=await jget('/api/book/entities?code='+encodeURIComponent(b.code)+'&limit=1');
      z.entc=e.counts||{}; z.ent=Object.values(z.entc).reduce((a,n)=>a+(n||0),0);
    }catch(e){}
    stats[b.code]=z;
  }));
  const clcs={};
  (state.books||[]).forEach(b=>{const c=b.clc||{};if(c.代码)clcs[c.代码]=c.名称||'';});
  if(!isCurrent())return;v.innerHTML=`
    <div class="page-head">
      <div><div class="eyebrow">Library / Inventory</div><h1>来源图书</h1>
        <p>共 ${num(state.books.length)} 本图书。这里只做三件事：陈列、分类、告知每本抽取了多少。</p></div>
      <div class="head-actions"><button class="btn ghost" onclick="exportLibraryCsv()">导出清单 CSV</button><button class="btn primary" onclick="go('tasks')">＋ 上传图书</button></div>
    </div>
    <section class="panel">
      <div class="filters">
        <div class="search"><input id="libQ" placeholder="搜索书名 / 作者 / 出版社"></div>
        <select id="libClc"><option value="">全部分类</option>${Object.keys(clcs).sort().map(k=>`<option value="${esc(k)}">${esc(k)} ${esc(clcs[k])}</option>`).join('')}</select>
        <select id="libStatus"><option value="">全部状态</option><option value="pending">待确认</option><option value="ready">已入库</option></select>
      </div>
      <div id="libTable"></div>
      <div class="table-foot"><span id="libCount">—</span></div>
    </section>`;
  const F=state.libFilters;
  document.getElementById('libQ').value=F.q||'';
  document.getElementById('libClc').value=F.clc||'';
  document.getElementById('libStatus').value=F.status||'';
  const draw=()=>{
    const q=(document.getElementById('libQ').value||'').toLowerCase();
    const clc=document.getElementById('libClc').value, st=document.getElementById('libStatus').value;
    Object.assign(state.libFilters,{q:document.getElementById('libQ').value,clc:clc,status:st});
    const rows=state.books.filter(b=>{
      const c=b.clc||{};
      if(q&&![b.book,b.author,b.publisher,b.code,c.代码,c.名称].join(' ').toLowerCase().includes(q))return false;
      if(clc&&c.代码!==clc)return false;
      if(st==='pending'&&b.status!=='pending')return false;
      if(st==='ready'&&b.status==='pending')return false;
      return true;
    });
    document.getElementById('libCount').textContent=`显示 ${rows.length} / ${state.books.length} 本`;
    document.getElementById('libTable').innerHTML=`<table class="table lib-table">
      <thead><tr><th>图书</th><th>分类</th><th>抽取情况</th><th>状态</th><th>入库</th></tr></thead>
      <tbody>${rows.map(b=>{
        const z=stats[b.code]||{};
        const c=b.clc||{};
        const ent=z.entc||{};
        const mini=[['人物',ent.person||0],['地点',['country','province','region','city','district','landmark','nature'].reduce((a,k)=>a+(ent[k]||0),0)],['机构',ent.org||0],['概念',ent.concept||0]]
          .filter(([_,n])=>n).map(([k,n])=>`${k} ${num(n)}`).join(' · ');
        return `<tr onclick="go('book','${esc(b.code)}')">
          <td><div class="bookcell"><div class="mini-cover">${esc(coverChar(b.book))}</div><div><b>${esc(b.book)}</b><span>${esc(b.author||'作者未填写')} · ${esc(b.publisher||'出版社未填写')}</span></div></div></td>
          <td>${c.代码?`<span class="pill">${esc(c.代码)} ${esc(c.名称||'')}</span>`:'<span class="faint">未分类</span>'}</td>
          <td><div class="exline"><span>出版 ${num(z.pub)}/19</span><span>结构 ${num(z.page)}/12</span><span>内容 ${num(z.ent)}</span><span>事实 ${num(z.fact)}</span><span>金句 ${num(z.quote)}</span><span>营销 ${num(z.mk)}</span></div>${mini?`<div class="faint" style="margin-top:4px">${mini}</div>`:''}</td>
          <td>${status(b)}</td>
          <td>${ago(b.added_at)}</td>
        </tr>`;}).join('')}</tbody></table>`;
  };
  ['libQ','libClc','libStatus'].forEach(id=>document.getElementById(id).addEventListener('input',draw));
  draw();
}

/* ================= 书详情 ================= */
async function renderBook(v,code){
  // 父级按真实来路显示：从工作台进来就写「工作台」，别写成来源图书却回退到首页
  const _pv=(state.navPrev&&state.navPrev.view)||'';
  const _pm={dashboard:['工作台','dashboard'],library:['来源图书','library'],
    archive:['图书档案','archive'],assets:['知识资产','assets'],
    search:['全局检索','search'],job:['入库任务','tasks'],kg:['知识图谱','kg']}[_pv]||['来源图书','library'];
  crumb(`<span>数据资产</span><span>/</span><a onclick="go('${_pm[1]}')">${_pm[0]}</a><span>/</span><b>图书档案</b>`);
  v.innerHTML='<div class="empty">加载图书档案…</div>';
  let d=state.bookCache[code];
  if(!d){try{d=await jget('/api/book?code='+encodeURIComponent(code));state.bookCache[code]=d;}catch(e){v.innerHTML=`<div class="panel"><div class="empty">加载失败：${esc(e.message)}</div></div>`;return;}}
  state.book=d;
  const b=d.book||{},r=d.row||{},rec=d.record||{};
  const title=r.book||b.book||rec.book||code;
  // 末级写书名，避免「图书档案 / 图书档案」重复
  // 工作台是顶层，不该写成「数据资产 / 工作台」
  const _head = (_pm[1]==='dashboard'||_pm[1]==='kg') ? '' : '<span>数据资产</span><span>/</span>';
  crumb(`${_head}<a onclick="go('${_pm[1]}')">${_pm[0]}</a><span>/</span><b>${esc(clip(title,22))}</b>`);
  const tc=d.tag_counts||{},cc=d.cards||{};
  v.innerHTML=`
    <div class="breadcrumbs crumbs"><a onclick="go('library')">来源图书</a><span>/</span><span>${esc(title)}</span></div>
    <section class="panel book-hero">
      <div class="book-cover">${esc(coverChar(title))}</div>
      <div class="hero-main">
        <div class="eyebrow">${esc(r.code||code)}</div>
        <h1>${esc(title)}</h1>
        <div class="meta">${[r.author,r.publisher].filter(Boolean).map(esc).join(' · ')||'作者 / 出版社未填写'} <span class="faint">· ${rec.source==='upload'?'新入库':'基准库'}</span></div>
        <div class="badges">${pill(r.prototype)}${status(r)}<span class="pill">${esc(r.confidence||'—')}置信</span>${b['人工改判']?'<span class="pill p5">人工分类</span>':''}</div>
        <div class="hero-actions">
          <button class="btn sm ghost" onclick="alert('原型预览：编辑图书信息')">编辑信息</button>
          <button class="btn sm ghost" onclick="alert('原型预览：更多操作')">更多</button>
        </div>
      </div>
      <div class="hero-stats">
        <div class="hs"><b>${num(r.han)}</b><span>汉字</span></div>
        <div class="hs"><b>${num(r.segments)}</b><span>内容段</span></div>
        <div class="hs"><b>${num(cc.total)}</b><span>知识条目</span></div>
        <div class="hs"><b>${num(tc.total)}</b><span>标签</span></div>
      </div>
    </section>
    <div class="tabs">
      <button class="${state.detailTab==='overview'?'on':''}" onclick="setTab('overview')">概览</button>
      <button class="${state.detailTab==='pub'?'on':''}" onclick="setTab('pub')">出版档案</button>
      <button class="${state.detailTab==='pages'?'on':''}" onclick="setTab('pages')">页面结构</button>
      <button class="${state.detailTab==='assets'?'on':''}" onclick="setTab('assets')">内容成果</button>
      <button class="${state.detailTab==='marketing'?'on':''}" onclick="setTab('marketing')">营销资料</button>
      <button class="${state.detailTab==='tags'?'on':''}" onclick="setTab('tags')">标签体系</button>
      <button class="${state.detailTab==='text'?'on':''}" onclick="setTab('text')">原文</button>
      <button class="${state.detailTab==='records'?'on':''}" onclick="setTab('records')">操作记录</button>
    </div>
    <div id="detailBody"></div>`;
  drawDetailTab();
}

function kgCapabilityRow(b,p11){
  const code=b['code']||b['码']||'';
  if(state.kgBuilt&&state.kgBuilt.has(code)) return '<span class="badge green">已出图谱</span><div class="faint">独立图谱见「知识图谱 · 图谱工作台」；这里的自动解析判断不变，图谱是另一套人工校验的资产。</div>';
  return p11?'<span class="badge">不适用</span><div class="faint">图鉴没有人物叙事，本类书不出人物关系图谱。</div>':(b['可出关系图谱']?'<span class="badge green">可出</span>':'<span class="badge">不出</span>')+(b['可出关系图谱']?'':'<div class="faint">'+esc(plainGraph(b))+'</div>');
}
/* ================= 资料整理：机器做不了、必须人过的两件事 =================
   章节主旨、引文判定。这两件事补完，「篇目索引」和「引证线索」才变成能交付的
   篇章表和文献线索清单；补不完就只是索引和线索。所以它们不该待在「资产产出」里
   假装是产出，应该在这里变成一道活。 */
const ED_USES = ['支持论点', '反驳/存疑', '举例', '参见作者其他著作', '仅提到书名'];
let ED = {code: '', tab: 'cite', data: null, books: [], pending: null};

async function renderEditor(v, code, tab){
  const isCurrent=capturePageRequest(v);
  await refreshBooks();if(!isCurrent())return;
  let pend = {books: [], chapters: 0, cites: 0, total: 0};
  try { pend = await jget('/api/editor/pending'); } catch (e) {}
  if(!isCurrent())return;
  ED.books = state.books.slice();
  ED.pending = pend;
  const withWork = (pend.books || []).map(function (b) { return b.code; });
  let pick = code && state.books.some(function (b) { return b.code === code; }) ? code : '';
  if (!pick) pick = withWork[0] || ((state.books[0] || {}).code || '');
  ED.tab = tab === 'cite' ? 'cite' : 'chapter';
  let d = null;
  try { d = await jget('/api/editor?code=' + encodeURIComponent(pick)); } catch (e) {}
  if(!isCurrent())return;
  ED.code = pick;
  ED.data = d || {chapters: [], cites: [], stats: {}, book: ''};
  const p = ED.data;
  const yesN = (p.cites || []).filter(function (c) { return c['判定'] === '引用'; }).length;
  const chN = (p.chapters || []).filter(function (c) { return (c['主旨'] || '').trim(); }).length;
  if(!isCurrent())return;v.innerHTML = `
    <div class="page-head">
      <div><div class="eyebrow">OPTIONAL / READING MATERIALS</div><h1>单书资料整理</h1>
        <p>按当前任务需要，整理相关章节的阅读提要，或梳理书中提到的文献线索。</p></div>
      <div class="head-actions">
        <button class="btn ghost" onclick="go('content')">返回内容成果</button>
        <select id="edBook" onchange="edGo(this.value)">${edBookOptions()}</select>
        <button class="btn ghost${yesN ? '' : ' is-off'}" ${yesN ? '' : 'disabled'} onclick="edExport('cite')">导出文献线索 ${num(yesN)}</button>
        <button class="btn ghost${chN ? '' : ' is-off'}" ${chN ? '' : 'disabled'} onclick="edExport('chapter')">导出阅读提要 ${num(chN)}</button>
      </div>
    </div>
    <div class="mkt-cats" id="edTabs">
      <button class="mkt-cat-tab${ED.tab === 'chapter' ? ' on' : ''}" data-k="chapter" onclick="edTab(this.dataset.k)">章节阅读提要 <b>${num(p.stats.chapters_done || 0)}/${num(p.stats.chapters || 0)}</b></button>
      <button class="mkt-cat-tab${ED.tab === 'cite' ? ' on' : ''}" data-k="cite" onclick="edTab(this.dataset.k)">书中提及的文献 <b>${num(p.stats.cites_checked || 0)}/${num(p.stats.cites || 0)}</b></button>
    </div>
    <div id="edBody">${edBodyHtml()}</div>`;
}

function edBookOptions() {
  const cur = ED.code;
  const pend = {};
  ((ED.pending || {}).books || []).forEach(function (b) { pend[b.code] = b.total; });
  return ED.books.map(function (b) {
    const n = pend[b.code] || 0;
    return `<option value="${esc(b.code)}"${b.code === cur ? ' selected' : ''}>${esc(b.book)}</option>`;
  }).join('');
}

function edGo(code) { go('editor', code, ED.tab); }
function edTab(k) {
  ED.tab = k;
  document.querySelectorAll('#edTabs .mkt-cat-tab').forEach(function (b) { b.classList.toggle('on', b.dataset.k === k); });
  const host = document.getElementById('edBody');
  if (host) host.innerHTML = edBodyHtml();
}

function edBodyHtml() {
  const p = ED.data || {};
  if (!(p.chapters || []).length && !(p.cites || []).length) {
    return '<div class="panel"><div class="panel-body"><div class="empty">这本书暂没有可整理的章节或文献线索。可以到内容成果中查看已提取的其他成果。</div></div></div>';
  }
  const purpose = ED.tab === 'chapter'
    ? '<div><dt>谁用</dt><dd>选题编辑、资料编辑</dd></div><div><dt>什么时候用</dt><dd>了解一本书的内容分布，为新选题找相关章节</dd></div><div><dt>交付什么</dt><dd>章节阅读提要；保存后可查看内容成果，选入选题策划</dd></div>'
    : '<div><dt>谁用</dt><dd>做文献调研的编辑、资料编辑</dd></div><div><dt>什么时候用</dt><dd>查找作者提到的作品，继续追索相关资料</dd></div><div><dt>交付什么</dt><dd>带书中上下文的文献线索清单，供继续查证</dd></div>';
  return '<section class="studio-card review-purpose"><dl>'+purpose+'</dl></section><section class="panel"><div class="panel-body">'
    + (ED.tab === 'chapter' ? edChapterHtml() : edCiteHtml())
    + '</div></section>';
}

/* ---------- 章节主旨 ---------- */
function edChapterHtml() {
  const p = ED.data, ch = p.chapters || [];
  const done = ch.filter(function (x) { return (x['主旨'] || '').trim(); }).length;
  const rows = ch.map(function (c) {
    const has = (c['主旨'] || '').trim();
    return `<tr data-id="${esc(c.id)}">
      <td class="mono faint">${c['序'] != null ? c['序'] : '—'}</td>
      <td>${esc(clip(c['名'], 30))}<span class="faint">${c['字数'] != null ? num(c['字数']) + ' 字' : ''}</span></td>
      <td><input class="ed-input" data-id="${esc(c.id)}" value="${esc(c['主旨'] || '')}"
            placeholder="一句话：这篇讲什么" onblur="edSaveChapter(this)" onkeydown="edEnter(event,this)">${c['建议']?'<div class="studio-note">机器建议：'+esc(c['建议'])+' <button class="btn sm ghost" data-id="'+esc(c.id)+'" onclick="edUseSuggestion(this)">采用后编辑</button></div>':''}</td>
      <td class="ed-state">${has ? '<span class="status wait">已整理</span>' : '<span class="faint">未整理</span>'}</td>
      <td class="ed-op">${c['锚点'] ? `<button class="btn sm ghost" data-code="${esc(ED.code)}" data-seg="${esc(c['锚点'])}" onclick="openSegTerm(this.dataset.code,this.dataset.seg,'',{mode:'chapter',from:'editor'})">去原文</button>` : ''}<button class="btn sm ghost ed-result" data-code="${esc(ED.code)}" data-title="${esc(c['名'])}" onclick="ReviewHub.showSummary(this.dataset.code,this.dataset.title)" ${has||c['建议']?'':'hidden'}>查看成果并选用</button></td>
    </tr>`;
  }).join('');
  return `<div class="ed-tip">先选与当前任务相关的章节，结合原文修订阅读提要。保存后可点击「查看成果并选用」，核对内容并加入项目；也可导出已整理部分供阅读参考。</div>
    <div class="ed-prog">已整理 <b>${num(done)}</b> / ${num(ch.length)} 篇 <span class="faint">· 保存提要后仍需核对，才可用于项目交付</span></div>
    <table class="table ed-table"><thead><tr><th style="width:44px">#</th><th style="width:34%">篇名</th><th>一句话主旨</th><th style="width:72px">状态</th><th style="width:90px"></th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

async function edUseSuggestion(button) {
  const c=(ED.data.chapters||[]).find(x=>x.id===button.dataset.id);
  const input=Array.from(document.querySelectorAll('.ed-input')).find(x=>x.dataset.id===button.dataset.id);
  if(c&&input){input.value=c['建议']||'';await edSaveChapter(input);}
}

function edEnter(e, el) { if (e.key === 'Enter') { e.preventDefault(); el.blur(); } }
async function edSaveChapter(el) {
  const id = el.dataset.id, val = el.value.trim();
  const c = (ED.data.chapters || []).filter(function (x) { return x.id === id; })[0];
  if (!c || (c['主旨'] || '') === val) return;
  try { await post('/api/editor/flag', {code: ED.code, id: id, fields: {'主旨': val}}); }
  catch (e) { toast('保存失败：' + e.message, true); return; }
  c['主旨'] = val;
  const tr = el.closest('tr');
  if (tr) {tr.querySelector('.ed-state').innerHTML = val ? '<span class="status wait">已整理待核对</span>' : '<span class="faint">未整理</span>';tr.querySelector('.ed-result').hidden=!(val||c['建议']);}
  edProgress();
  toast(val ? '提要已保存，可查看成果并选入项目；交付前仍需核对' : '已清空');
}

/* ---------- 引文核对 ---------- */
function edCiteHtml() {
  const p = ED.data, cs = p.cites || [];
  const body = cs.filter(function (x) { return x.body > 0; });
  const frontOnly = cs.filter(function (x) { return !x.body; });
  const frontRows = frontOnly.map(function (c) { return edCiteRow(c, true); }).join('');
  const bodyRows = body.map(function (c) { return edCiteRow(c, false); }).join('');
  return `<div class="ed-tip">系统找到的是书名或篇名的提及，不代表作者一定在引用。查看上下文后，保留对调研有帮助的线索并记录关系，导出后继续查证作者、版本和出版信息。</div>
    <div class="ed-prog">已整理 <b>${num(p.stats.cites_checked || 0)}</b> / ${num(cs.length)} 条 · 保留线索 ${num(p.stats.cites_yes || 0)}</div>
    ${body.length ? `<div class="ed-grp"><span>正文提及的文献线索 ${num(body.length)} 条</span></div><div id="edCites">${bodyRows}</div>` : ''}
    ${frontOnly.length ? `<div class="ed-grp"><span>只出现在前置页 ${num(frontOnly.length)} 条</span>
      <button class="btn sm ghost" onclick="edMarkFront()">不纳入这些前置页线索</button></div>
      <div id="edCitesFront">${frontRows}</div>` : ''}`;
}

// 引文出处对人说：第46篇「怎么写」· 第4段（内部锚点 YC-46-P04 只放 title）
function edSegLabel(x){
  x=x||{};
  const m=String(x.seg||'').match(/-P(\d+)$/);
  const duan=m?Number(m[1]):null;
  const a=x['序']!=null?('第'+x['序']+'篇'):'';
  const b=x['篇']?('「'+x['篇']+'」'):'';
  const c=duan!=null?('· 第'+duan+'段'):'';
  return (a+b+c)||String(x.seg||'');
}

function edCiteRow(c, isFront) {
  const v = c['判定'] || '';
  const qs = (isFront ? (c.front_quotes || []) : (c.quotes || [])).slice(0, isFront ? 1 : 2);
  const q = qs.map(function (x) {
    return `<div class="ec-q">…${esc(x.quote || '')}<span class="ec-src" title="${esc(x.seg || '')}">${esc(edSegLabel(x))}</span></div>`;
  }).join('');
  return `<div class="ed-cite${v === '引用' ? ' yes' : v ? ' no' : ''}" data-id="${esc(c.id)}" title="条目编号 ${esc(c.id)}">
    <div class="ec-h">
      <b>${esc(c['书名'])}</b>
      <span class="faint">正文 ${num(c.body)} 次 · 前置页 ${num(c.front)} 次</span>
      <div class="ec-btns">
        <button class="vbtn${v === '引用' ? ' on' : ''}" data-v="引用" onclick="edVerdict(this)">保留线索</button>
        <button class="vbtn${v === '非引用' ? ' on' : ''}" data-v="非引用" onclick="edVerdict(this)">不纳入清单</button>
        <select class="ec-use" onchange="edUse(this)" ${v === '引用' ? '' : 'disabled'}>
          <option value="">与本书是什么关系…</option>
          ${ED_USES.map(function (u) { return `<option value="${esc(u)}"${c['用途'] === u ? ' selected' : ''}>${esc(u)}</option>`; }).join('')}
        </select>
      </div>
    </div>
    ${q || '<div class="ec-q faint">正文里没有原句。</div>'}
    <div class="ec-f">
      ${qs.length ? `<button class="btn sm ghost" data-code="${esc(ED.code)}" data-seg="${esc(qs[0].seg || '')}" data-book="${esc(c['书名'])}" data-n="${esc(c.body || 0)}" onclick="openSegTerm(this.dataset.code,this.dataset.seg,this.dataset.book,{mode:'cite',total:Number(this.dataset.n)||0,from:'editor'})">查看书中上下文</button>` : ''}
    </div>
  </div>`;
}

async function edVerdict(btn) {
  const box = btn.closest('.ed-cite'); if (!box) return;
  const id = box.dataset.id, val = btn.dataset.v;
  const c = (ED.data.cites || []).filter(function (x) { return x.id === id; })[0];
  if (!c) return;
  const next = c['判定'] === val ? '' : val;
  try { await post('/api/editor/flag', {code: ED.code, id: id, fields: {'引用判定': next}}); }
  catch (e) { toast('保存失败：' + e.message, true); return; }
  c['判定'] = next;
  box.classList.toggle('yes', next === '引用');
  box.classList.toggle('no', next === '非引用');
  box.querySelectorAll('.vbtn').forEach(function (b) { b.classList.toggle('on', b.dataset.v === next); });
  const sel = box.querySelector('.ec-use');
  if (sel) { sel.disabled = next !== '引用'; if (next !== '引用') { sel.value = ''; c['用途'] = ''; } }
  edProgress();
}

async function edUse(sel) {
  const box = sel.closest('.ed-cite'); if (!box) return;
  const id = box.dataset.id;
  try { await post('/api/editor/flag', {code: ED.code, id: id, fields: {'用途': sel.value}}); }
  catch (e) { toast('保存失败：' + e.message, true); return; }
  const c = (ED.data.cites || []).filter(function (x) { return x.id === id; })[0];
  if (c) c['用途'] = sel.value;
  edProgress();
  toast(sel.value ? '已记：' + sel.value : '已清空用途');
}

async function edMarkFront() {
  const cs = (ED.data.cites || []).filter(function (x) { return !x.body && x['判定'] !== '非引用'; });
  if (!cs.length) { toast('前置页的已经标完了'); return; }
  for (const c of cs) {
    try { await post('/api/editor/flag', {code: ED.code, id: c.id, fields: {'引用判定': '非引用'}}); }
    catch (e) { toast('保存失败：' + e.message, true); return; }
    c['判定'] = '非引用';
    const box = document.querySelector('.ed-cite[data-id="' + c.id + '"]');
    if (box) {
      box.classList.remove('yes'); box.classList.add('no');
      box.querySelectorAll('.vbtn').forEach(function (b) { b.classList.toggle('on', b.dataset.v === '非引用'); });
      const sel = box.querySelector('.ec-use'); if (sel) { sel.disabled = true; sel.value = ''; }
    }
  }
  edProgress();
  toast('已将 ' + cs.length + ' 条前置页线索排除出清单');
}

function edProgress() {
  const p = ED.data, cs = p.cites || [], ch = p.chapters || [];
  const checked = cs.filter(function (x) { return x['判定']; }).length;
  const yes = cs.filter(function (x) { return x['判定'] === '引用'; }).length;
  const done = ch.filter(function (x) { return (x['主旨'] || '').trim(); }).length;
  p.stats=Object.assign({},p.stats,{cites_checked:checked,cites_yes:yes,chapters_done:done});
  const host = document.getElementById('edBody');
  if (host) {
    const prog = host.querySelector('.ed-prog');
    if (prog) prog.innerHTML = ED.tab === 'chapter'
      ? '已整理 <b>' + num(done) + '</b> / ' + num(ch.length) + ' 篇 <span class="faint">· 保存提要后仍需核对，才可用于项目交付</span>'
      : '已整理 <b>' + num(checked) + '</b> / ' + num(cs.length) + ' 条 · 保留线索 ' + num(yes);
  }
  document.querySelectorAll('button[onclick]').forEach(function(b){
    if(b.getAttribute('onclick')==="edExport('chapter')"){b.disabled=!done;b.classList.toggle('is-off',!done);b.textContent='导出阅读提要 '+num(done);}
    if(b.getAttribute('onclick')==="edExport('cite')"){b.disabled=!yes;b.classList.toggle('is-off',!yes);b.textContent='导出文献线索 '+num(yes);}
  });
  document.querySelectorAll('#edTabs .mkt-cat-tab').forEach(function (b) {
    if (b.dataset.k === 'cite') b.querySelector('b').textContent = num(checked) + '/' + num(cs.length);
    if (b.dataset.k === 'chapter') b.querySelector('b').textContent = num(done) + '/' + num(ch.length);
  });
}

/* ---------- 导出：只导补完的部分，缺的部分在文件尾说明 ---------- */
function edExport(kind) {
  const p = ED.data;
  const cell = function (v) { v = v == null ? '' : String(v);if(/^[=+@\-\t\r]/.test(v))v="'"+v; return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const stats = p.stats || {};
  if (kind === 'chapter') {
    const chs = (p.chapters || []).filter(function (x) { return (x['主旨'] || '').trim(); });
    if (!chs.length) { toast('还没有写过主旨的篇目', true); return; }
    const lines = [['篇序', '篇名', '字数', '一句话主旨', '原文锚点'].join(',')]
      .concat(chs.map(function (c) { return [c['序'], c['名'], c['字数'], c['主旨'], c['锚点']].map(cell).join(','); }));
    const miss = (stats.chapters || 0) - chs.length;
    if (miss > 0) lines.push(['', '', '', '还有 ' + miss + ' 篇没写主旨，未导出', ''].join(','));
    lines.push(['说明','','','阅读提要供资料整理参考，项目交付前仍需核对内容与出处。',''].map(cell).join(','));
    mktDownload(ED.code + '_章节阅读提要.csv', lines.join('\r\n'), 'text/csv');
    toast('已导出 ' + chs.length + ' 篇' + (miss ? '，另有 ' + miss + ' 篇未写' : ''));
    return;
  }
  const yes = (p.cites || []).filter(function (x) { return x['判定'] === '引用'; });
  if (!yes.length) { toast('还没有保留的文献线索', true); return; }
  const lines = [['书中提到的名称', '与本书的关系（人工记录）', '书中上下文', '篇', '原文锚点'].join(',')]
    .concat(yes.map(function (c) {
      const q0 = (c.quotes || [])[0] || {};
      return [c['书名'], c['用途'] || '（未填作用）', q0.quote || '', q0['篇'] || '', q0.seg || ''].map(cell).join(',');
    }));
  const miss = (p.cites || []).filter(function(c){return !c['判定'];}).length;
  if (miss > 0) lines.push(['', '', '还有 ' + miss + ' 条没核对，未导出', '', ''].join(','));
  lines.push(['说明','','此清单仅为书中提及的文献线索；作者、版本、出版信息尚需继续查证。','',''].map(cell).join(','));
  mktDownload(ED.code + '_文献线索清单.csv', lines.join('\r\n'), 'text/csv');
  toast('已导出 ' + yes.length + ' 条' + (miss ? '，另有 ' + miss + ' 条未核' : ''));
}

function setTab(t){state.detailTab=t;const tabs=document.querySelectorAll('.tabs button');tabs.forEach(x=>x.classList.toggle('on',x.textContent.trim()===({overview:'概览',pub:'出版档案',pages:'页面结构',assets:'内容成果',marketing:'营销资料',tags:'标签体系',text:'原文',records:'操作记录'}[t])));drawDetailTab();}

function drawDetailTab(){
  const host=document.getElementById('detailBody');if(!host)return;
  const d=state.book,b=d.book||{},r=d.row||{},rec=d.record||{},cc=d.cards||{},tc=d.tag_counts||{};
  if(state.detailTab==='overview'){
    const p11=b['原型']==='P11';
    const clc=d.clc||{};
    // 关键词只取「书里写了什么」这一层；引用书目/篇名/人物说的是提到谁，不代表书属于哪类
    const kws=[], seen={};
    ['L4','L6','L7'].forEach(lv=>arr((d.tags||{})[lv]).forEach(it=>{
      const t=(it['标签']||'').trim(), cls=it['类']||'';
      if(!t||t.length>14||seen[t]||['引用书目','篇名','人物'].indexOf(cls)>=0)return;
      seen[t]=1; kws.push(t);
    }));
    const pp=arr(d.people_top);
    host.innerHTML=`
      <div class="metric4">
        <div class="m"><b>${num(cc.total)}</b><span>知识条目</span></div>
        <div class="m"><b>${num(cc['可直接用'])}</b><span>可直接使用</span></div>
        <div class="m"><b>${num(cc['需人筛'])}</b><span>待人工核对</span></div>
        <div class="m"><b>${pct(r.retention)}</b><span>原文完整度</span></div>
      </div>
      <section class="panel dossier-sec">
        <div class="panel-head"><div><h2>这本书怎么用</h2><div class="sub">${esc(r.prototype_name||'')} · ${b['结构单位']==='人'?'按人物':esc(MODE_CN[b['结构模式']]||b['结构模式']||'')} · ${num(b['篇数'])} ${b['结构单位']==='人'?'人':'篇'} / ${num(b['段数'])} 段 / ${num(b['汉字_切段'])} 字</div></div>
        ${clc['代码']?`<span class="clc-wrap">${clcChip(clc)}</span>`:''}</div>
        <div class="panel-body">${howToUseHtml(d,p11,keAll,und)}</div>
      </section>
      ${pp.length?`<section class="panel dossier-sec">
        <div class="panel-head"><div><h2>书里出现的人</h2><div class="sub">点一下跳到这个人第一次出现的原文</div></div><span class="faint">${num((d.people||{}).count)} 人</span></div>
        <div class="panel-body"><div class="kwline">${pp.map(p=>`<span class="personchip" data-seg="${esc(p['首现'])}" data-name="${esc(p['人物']||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.name)">${esc(p['人物'])}<em>×${num(p['频次'])}</em></span>`).join('')}</div></div>
      </section>`:''}
      <section class="panel dossier-sec" id="secFacts">
        <div class="panel-head"><div><h2>关键事实摘录</h2><div class="sub">从「可直接用」的条目里挑出来的，点一条跳到原文那一段</div></div><a onclick="setTab('assets')">看全部 ${num(cc['可直接用'])} 条 →</a></div>
        <div class="panel-body"><div id="factList">${loading('加载条目')}</div></div>
      </section>
      ${(und.quotes||[]).length?`<section class="panel dossier-sec">
        <div class="panel-head"><div><h2>可以引用的句子</h2><div class="sub">模型只选不改，每句都经逐字回查；点一句跳到原文</div></div>${und.quotes.length>8?`<a onclick="openQuotes()">查看全部 ${und.quotes.length} 句 →</a>`:`<span class="faint">${und.quotes.length} 句</span>`}</div>
        <div class="panel-body">${und.quotes.slice(0,8).map(q=>`<div class="quote-item" data-seg="${esc(q.seg||'')}" data-q="${esc(q.quote||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.q,'quote')"><div class="qtext">${esc(q.quote||'')}</div><div class="faint">${esc(q.seg||'')}${q.reason?' · '+esc(q.reason):''}</div></div>`).join('')}</div>
      </section>`:''}
      <section class="panel dossier-sec" id="secEntities">
        <div class="panel-head"><div><h2>书里的专名</h2><div class="sub">只预览数量最多的 4 类；点一个跳到它出现的原文</div></div><div class="head-actions"><span class="faint" id="entCount"></span><a id="entAll" onclick="showEnts()">全部 ›</a></div></div>
        <div class="panel-body" id="entBox">${loading('加载专名')}</div>
      </section>
      <section class="panel dossier-sec">
        <div class="panel-head"><div><h2>图书档案</h2><div class="sub">分类依据、能力边界、源文件与审计</div></div><span class="faint">${esc(r.code||'')}</span></div>
        <div class="panel-body">
          <table class="profile-table">
            <tr><th>图书分类</th><td>${esc(r.prototype||'—')} ${esc(r.prototype_name||'')} <span class="faint">· 置信 ${esc(r.confidence||'—')}</span>
              <a class="clc-edit" data-code="${esc(r.code||'')}" data-title="${esc(r.book||'')}" data-proto="${esc(r.prototype||'')}" onclick="openRetype(this.dataset.code,this.dataset.title,this.dataset.proto)">改类型</a>${r.status==='pending'?`<a class="clc-edit" data-code="${esc(r.code||'')}" onclick="confirmBook(this.dataset.code)">标为已确认</a>`:''}
              <div class="faint">改判：按新类型重跑知识条目与标签；标为已确认：只把状态从待确认改成已入库。</div></td></tr>
            <tr><th>中图分类</th><td>${clc['代码']?`${esc(clc['代码'])} ${esc(clc['名称'])}${clc['细分号']?' · '+esc(clc['细分号']):''} <span class="faint">· ${clc['来源']==='人工'?'人工指定':(clc['来源']==='版权页'?'版权页':'系统建议')}</span><div class="faint">${esc((clc['依据']||[]).join('；'))}</div>`:'<span class="faint">未识别（不影响内容，只影响展示与归架）</span>'} <a class="clc-edit" onclick="openClc('${esc(r.code||'')}','${esc(clc['代码']||'')}')">改判</a></td></tr>
            ${cip['_found']?`<tr><th>版权页</th><td>${[cip['出版社']&&esc(cip['出版社']),cip['出版地']&&esc(cip['出版地']),cip['出版年月']&&esc(cip['出版年月']),cip['版次']&&esc(cip['版次']),cip['印次']&&esc(cip['印次'])].filter(Boolean).join(' · ')||'—'}</td></tr>
            <tr><th>ISBN</th><td><span class="mono">${esc(cip['ISBN']||'—')}</span>${cip['ISBN校验']===true?' <span class="badge green">校验通过</span>':(cip['ISBN校验']===false?' <span class="badge red">校验位不对</span>':'')}${cip['CIP核字号']?` <span class="faint">CIP 核字 ${esc(cip['CIP核字号'])}</span>`:''}</td></tr>
            <tr><th>规格</th><td>${[cip['开本']&&('开本 '+esc(cip['开本'])),cip['印张']&&(esc(cip['印张'])+' 印张'),cip['字数']&&(num(cip['字数'])+' 字（版权页）'),cip['定价']&&('定价 '+esc(cip['定价'])+' 元')].filter(Boolean).join(' · ')||'—'}</td></tr>
            <tr><th>著者</th><td>${esc(cip['著者']||'—')}</td></tr>`:`<tr><th>版权页</th><td><span class="badge">未读到</span> <span class="faint">${esc(cip['_reason']||'没有版权页数据')}；元数据需人工补或等模型</span></td></tr>`}
            <tr><th>分类依据</th><td>${esc(arr(b['依据']).join('；')||'—')}</td></tr>
            ${(()=>{const st=b['稳定性'],fit=b['吻合'],mix=arr(b['混合']);
              if(st==null&&fit==null&&!mix.length)return '';
              const mixs=mix.map(x=>Array.isArray(x)?`${esc(x[0])} ${esc(x[1])}%`:esc(x)).join('、');
              return `<tr><th>分类稳定性</th><td>${st!=null?`稳定性 ${Math.round(st*100)}%（阈值扰动 ±20% 后判型不变的比例）`:''}
                ${fit!=null?` · 分块吻合 ${fit}%（10 个分块里 ${Math.round(fit/10)} 块判成同一类）`:''}
                ${mixs?` · 混入 ${mixs}`:''}
                <div class="faint">低于 95% 记「低」置信，需要人确认；「吻合」低说明这本书内部本就不统一。</div></td></tr>`;})()}
            <tr><th>内容结构</th><td>${esc(MODE_CN[b['结构模式']]||b['结构模式']||'—')} · ${num(b['篇数'])} 篇 / ${num(b['段数'])} 段 / ${num(b['汉字_切段'])} 字 · 原文完整度 ${pct(b['保留率'])}${b['条目数']?' · 另切出 '+num(b['条目数'])+' 条物种条目':''}</td></tr>
            <tr><th>篇名识别</th><td>${esc(pm['性质']||'—')}${pm['可用率']!=null?' · 可用率 '+pct(pm['可用率']):''}<div class="faint">${esc(pm['说明']||'')}</div></td></tr>
            <tr><th>人物关系图谱</th><td>${kgCapabilityRow(b,p11)}</td></tr>
            <tr><th>能力边界</th><td>${p11?'<div class="faint">本类书的产物是「物种条目卡 + 字段表 + 科名索引」；图鉴不做观点段和议题，这是文体差异，不是漏抽。</div><div class="faint">图注 / 图片对位尚未接入。</div>':`${b['人物表性质']?'<div class="faint">'+esc(plainPersonTable(b))+'</div>':''}${b['概念层缺口']?'<div class="faint">'+esc(plainConcept(b))+'</div>':''}`}</td></tr>
            <tr><th>源文件</th><td>${esc(rec.source_format||'—')}${rec.source_note?' · '+esc(rec.source_note):''}${rec.source_completeness?' · '+esc(rec.source_completeness):''}</td></tr>
            ${b['目录清洗']?`<tr><th>目录清洗</th><td>已移除 ${num(b['目录清洗']['删除行数'])} 行 / ${num(b['目录清洗']['删除汉字'])} 字目录内容；章节按清理后文本重切。</td></tr>`:''}
            ${b['结构审计']?`<tr><th>结构审计</th><td>${b['结构审计']['异常']?'<span class="badge red">异常</span>':'<span class="badge green">正常</span>'} ${esc(b['结构审计']['说明']||'章号顺序与目录残留检查通过')}</td></tr>`:''}
            <tr><th>图书编号</th><td>${esc(r.code||'')} <span class="faint">（原文定位前缀；重跑不变）</span></td></tr>
          </table>
        </div>
      </section>`;
    loadFacts();
    loadEntities();
  }else if(state.detailTab==='pub'){
    host.innerHTML=pubHtml(d);
  }else if(state.detailTab==='pages'){
    host.innerHTML=pagesHtml(d);
  }else if(state.detailTab==='marketing'){
    host.innerHTML=marketingHtml(d);
  }else if(state.detailTab==='assets'){
    const tiers=[['','全部'],['可直接用','可直接用'],['需人筛','需人工筛选'],['仅定位器','索引定位']];
    host.innerHTML=deepHtml(d)+`<section class="panel"><div class="panel-head"><div><h2>内容成果</h2><div class="sub">按三级质量分开看，不合并成一个数</div></div><span class="faint">${num(cc.total)} 条</span></div>
      <div class="panel-body">
        <div class="cand-tabs">${tiers.map(([k,l])=>`<button class="${state.tier===k?'on':''}" onclick="setTier('${k}')">${l}</button>`).join('')}</div>
        <div id="candList"><div class="empty">加载知识条目…</div></div>
      </div></section>`;
    loadCards();
  }else if(state.detailTab==='tags'){
    host.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>标签体系</h2><div class="sub">来源只有实测 / 提取 / 判断三种</div></div></div><div class="panel-body">${renderLayers(d.tags||{})}</div></section>`;
  }else if(state.detailTab==='text'){
    host.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>原文</h2><div class="sub">按篇加载，保留原文定位</div></div></div><div class="panel-body">
      <div class="outline" id="outlineBox">${arr(d.outline).map((o,i)=>`<button class="${i===0?'on':''}" onclick="loadText(this,'${esc(o['篇'])}')">${esc(o['篇'])}</button>`).join('')||'<span class="faint">无篇名，按段读取</span>'}</div>
      <div id="segBox"><div class="empty">加载原文…</div></div>
    </div></section>`;
    const first=arr(d.outline)[0];loadSegments(first?first['篇']:'');
  }else{
    const ops=arr(d.operations);
    host.innerHTML=`<section class="panel"><div class="panel-head"><h2>操作记录</h2></div><div class="panel-body">
      ${ops.length?ops.slice().reverse().map(o=>`<div class="list-row"><div class="main"><b>${esc(o.event)}</b><span>${esc((o.time||'').replace('T',' ').slice(0,19))} ${o.detail&&o.detail.title?'· '+esc(o.detail.title):''}</span></div></div>`).join(''):'<div class="empty">暂无操作记录</div>'}
    </div></section>`;
  }
}

async function loadCards(){
  const d=state.book,code=d.row.code;const host=document.getElementById('candList');if(!host)return;
  try{
    const q=new URLSearchParams({code,tier:state.tier,type:'',q:'',offset:'0',limit:'12'});
    const res=await jget('/api/book/cards?'+q.toString());
    host.innerHTML=res.items.length?res.items.map(c=>`<div class="cand">
      <div class="cand-head"><span class="pill">${esc(CARD_TYPE[c['类型']]||c['类型']||'知识条目')}</span><span class="pill">${esc(CARD_NAT[c['资产性质']]||c['资产性质']||'')}</span><span class="faint">${esc(c['锚点']||'')}</span></div>
      <div class="cand-text">${esc(c['_excerpt']||c['原文']||'')}</div>
      <div class="cand-meta">${esc(c['精度说明']||'')}</div>
    </div>`).join(''):'<div class="empty">没有符合条件的知识条目</div>';
  }catch(e){host.innerHTML=`<div class="empty">加载失败：${esc(e.message)}</div>`;}
}
function setTier(t){state.tier=t;drawDetailTab();}

function renderLayers(tags){
  return LAYERS.map(([lv,name,q])=>{const items=arr(tags[lv]);return `<div class="layer"><div class="layer-h"><b>${lv} ${name}</b><span>${q} · ${items.length} 条</span></div>${items.length?items.map(it=>`<span class="tagchip ${lv==='L7'?'l7':''}" title="${esc(it['验证']||'')}">${esc(it['标签']||'')}</span>`).join(''):'<span class="faint">本层暂无</span>'}</div>`;}).join('');
}
function loadText(btn,chapter){document.querySelectorAll('#outlineBox button').forEach(b=>b.classList.remove('on'));btn.classList.add('on');loadSegments(chapter);}
async function loadSegments(chapter){
  const host=document.getElementById('segBox');if(!host)return;host.innerHTML='<div class="empty">加载原文…</div>';
  try{
    const code=state.book.row.code;
    const d=await jget('/api/book/segments?'+new URLSearchParams({code,chapter,offset:'0',limit:'8'}).toString());
    host.innerHTML=d.items.length?d.items.map(s=>`<div class="seg"><div class="anch">${esc(s['锚点']||'')} · ${esc(s['篇']||'')} 第${esc(s['段']||'')}段</div><div class="txt">${esc(s['文本']||'')}</div></div>`).join(''):'<div class="empty">这一篇没有切出段落</div>';
  }catch(e){host.innerHTML=`<div class="empty">${esc(e.message)}</div>`;}
}

/* ================= 入库任务 ================= */
function renderTasks(v){
  const jobs=state.jobs||[];
  v.innerHTML=`
    <div class="page-head"><div><div class="eyebrow">Content Assets / Ingest</div><h1>入库任务</h1><p>上传、解析、入库是一个独立工作区；不再从来源图书弹一个模态框解决。</p></div></div>
    <section class="panel upload-panel">
      <div class="drop"><div class="big">拖入图书文件</div><div class="small">支持 txt / md / docx / 文本型 PDF<br>单文件上限以服务端配置为准</div><button class="btn sm gold" style="margin-top:10px" onclick="alert('原型预览：正式版接上传流程')">选择文件</button></div>
      <div>
        <div class="form-grid">
          <div class="field"><label>书名</label><input placeholder="例：围城"></div>
          <div class="field"><label>作者</label><input placeholder="可空"></div>
          <div class="field"><label>出版社</label><input placeholder="可空"></div>
          <div class="field"><label>分类（可空）</label><select><option>自动识别</option>${Object.keys(PROTO).map(p=>`<option>${p} ${PROTO[p]}</option>`).join('')}</select></div>
        </div>
        <div class="kv-note" style="margin-top:10px">上传后会生成一条入库任务：解析 → 分类 → 内容切分 → 知识条目 → 标签 → 入库。中/低置信自动入库并标待确认。</div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px"><button class="btn ghost" onclick="alert('原型预览')">保存草稿</button><button class="btn primary" onclick="alert('原型预览：正式版接上传流程')">开始入库</button></div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><h2>最近任务</h2><div class="sub">上传 / 恢复 / 改分类都进入任务中心</div></div><span class="faint">${jobs.length} 条</span><button class="btn sm ghost" onclick="clearJobs()">清空已完成</button></div>
      <table class="table"><thead><tr><th>任务</th><th>图书 / 项目</th><th>状态</th><th class="num">进度</th><th>创建时间</th><th class="right">操作</th></tr></thead>
      <tbody>${jobs.length?jobs.slice(0,8).map(j=>`<tr onclick="alert('原型预览：任务详情')"><td>${esc(j.kind==='upload'?'入库':j.kind)}</td><td>${esc(j.title||'—')}</td><td><span class="status ${j.status==='done'?'ok':j.status==='failed'?'fail':'wait'}">${esc({queued:'排队',running:'进行中',done:'已完成',partial:'部分完成',failed:'失败'}[j.status]||j.status)}</span></td><td class="num">${num(j.progress)}%</td><td>${esc((j.created_at||'').replace('T',' ').slice(0,16))}</td><td class="right"><button class="btn sm ghost" onclick="event.stopPropagation();delJob('${esc(j.id)}')">删除</button></td></tr>`).join(''):'<tr><td colspan="6"><div class="empty">还没有任务</div></td></tr>'}</tbody></table>
    </section>`;
}

function compCell(b){
  const c=b.completeness||{};
  const dot=(ok,label)=>`<span class="comp-dot ${ok?'ok':'no'}" title="${label}">${ok?'●':'○'}</span>`;
  const all=c.cards&&c.judge&&c.entities&&c.quotes;
  const btn=c.tagging?'<span class="faint" style="margin-left:4px">补齐中</span>'
    :(!all?`<button class="btn sm ghost" style="margin-left:4px" data-code="${esc(b.code)}" onclick="tagBook(this)">补跑</button>`:'');
  return `<span class="comp">${dot(c.cards,'知识条目')}${dot(c.judge,'判定')}${dot(c.entities,'专名')}${dot(c.quotes,'金句')}</span>${btn}`;
}
async function tagBook(btn){
  const code=btn.dataset.code;
  btn.disabled=true; btn.textContent='已提交';
  try{
    const d=await post('/api/books/tag',{code});
    toast(d.running?'这本书正在补跑，稍后刷新':'已开始补跑，约 1–5 分钟');
    setTimeout(()=>{refreshBooks().then(()=>route());}, 4000);
  }catch(e){btn.disabled=false;btn.textContent='补跑';toast(e.message,true);}
}

/* ================= 跨书搜索 ================= */
const SEARCH_GROUPS={books:'图书',assets:'内容成果',segments:'原文',tags:'标签',cards:'条目'};
const SEARCH_PAGE_SIZE=12;

function renderSearch(v,arg){
  const q=(arg!==undefined&&arg!==null&&String(arg).trim()!=='')?String(arg).trim():(state.globalQ||'');
  state.globalQ=q;
  const top=document.getElementById('globalQ'); if(top) top.value=q;
  v.innerHTML=`
    <div class="page-head"><div><h1>跨书搜索</h1><p>查找书名、原文、标签和已经整理的内容。</p></div></div>
    <section class="panel search-page"><div class="panel-body">
      <form class="big-search" onsubmit="event.preventDefault();submitSearch()"><input id="searchQ" type="search" aria-label="跨书搜索关键词" placeholder="输入书名、人物或原文关键词" value="${esc(q)}"><button class="btn primary" type="submit">搜索</button></form>
      <div id="searchOut">${q?'':'<p class="muted">输入关键词开始搜索。</p>'}</div>
    </div></section>`;
  if(q){
    const search=state.globalSearch;
    if(search?.q===q&&search.result)drawSearchResults(document.getElementById('searchOut'),search);
    else return runSearch();
  }
}

// 检索词进 hash：可分享、可后退回来还是同一组结果
function submitSearch(){
  const el=document.getElementById('searchQ');
  const q=(el&&el.value||'').trim();
  if(!q) return;
  if(q===state.globalQ){ runSearch(); return; }
  go('search',q);
}
async function runSearch(){
  const q=(document.getElementById('searchQ')?.value||'').trim(),out=document.getElementById('searchOut');if(!q||!out)return;
  const search={q,result:null,loadingGroup:new Set(),errors:{}};
  state.globalSearch=search;
  state.globalQ=q;out.innerHTML=loading('检索内容与原文');
  try{
    const result=await jget('/api/search?'+new URLSearchParams({q,scope:'all',limit:String(SEARCH_PAGE_SIZE)}));
    if(state.globalSearch!==search||!out.isConnected)return;
    search.result=result;
    drawSearchResults(out,search);
  }catch(err){
    if(state.globalSearch===search&&out.isConnected)out.innerHTML='<div class="empty">搜索暂时失败。<button type="button" class="btn sm ghost" onclick="runSearch()">重试</button></div>';
  }
}

function searchHighlight(value,query){
  const text=String(value||''), match=text.toLowerCase().indexOf(query.toLowerCase());
  if(match<0)return esc(text);
  return esc(text.slice(0,match))+'<mark>'+esc(text.slice(match,match+query.length))+'</mark>'+esc(text.slice(match+query.length));
}

function searchResultRow(group,item,q){
  const title=group==='assets'?item.title:group==='tags'?item.tag:group==='cards'?item.type:item.book||item.code;
  let meta, excerpt, action;
  if(group==='assets'){
    meta=item.book;
    excerpt=item.excerpt||clip(item.text||'',160);
    action=`<button type="button" class="btn sm ghost" data-id="${esc(item.id)}" onclick="Studio.detail(this)">查看成果</button>`;
  }else{
    const located=group!=='books'&&item.anchor;
    const tab=located?'text':group==='tags'?'tags':'overview';
    meta=group==='books'?[item.author,item.publisher].filter(Boolean).join(' · '):group==='segments'?item['篇']:item.book;
    excerpt=item['原文'];
    action=`<button type="button" class="btn sm ghost" data-code="${esc(item.code)}" data-tab="${tab}" data-anchor="${esc(located||'')}" data-query="${esc(q)}" onclick="viewSearchSource(this)">${located?'查看原文':group==='tags'?'查看标签':'查看图书'}</button>`;
  }
  return `<div class="result"><div class="r-main"><b>${searchHighlight(title,q)}</b>${meta?`<div class="r-meta">${esc(meta)}</div>`:''}${excerpt?`<p class="search-excerpt">${searchHighlight(excerpt,q)}</p>`:''}</div>${action}</div>`;
}

function viewSearchSource(button){
  const {code,tab,anchor,query}=button.dataset;
  if(tab==='text'&&anchor)openSegTerm(code,anchor,query,{mode:'search',from:'search'});
  else go('book',code,tab);
}

function drawSearchResults(out,search){
  const d=search.result;
  const groups=Object.entries(SEARCH_GROUPS).map(([group,name])=>{
    const items=arr(d[group]);
    const total=d.totals?.[group]??items.length;
    if(!total)return '';
    const loadingGroup=search.loadingGroup.has(group);
    return `<section class="result-sec" data-search-results="${group}"><h3>${name} <span>${num(total)} 条</span></h3>${items.map(item=>searchResultRow(group,item,search.q)).join('')}
      ${search.errors[group]?'<p class="muted" role="status">这一组暂时无法继续加载。</p>':''}
      ${items.length<total?`<div class="search-result-footer"><span>已显示 ${num(items.length)} 条</span><button type="button" class="btn sm ghost" data-group="${group}" onclick="moreSearchResults(this)"${loadingGroup?' disabled':''}>${loadingGroup?'加载中…':search.errors[group]?'重试':'查看更多'+name}</button></div>`:''}</section>`;
  });
  out.innerHTML=groups.join('')||'<div class="empty">没有找到相关内容。试试书名、人物名或更短的关键词。</div>';
}

async function moreSearchResults(button){
  const group=button.dataset.group,search=state.globalSearch,out=document.getElementById('searchOut');
  if(!search?.result||!out||!Object.hasOwn(SEARCH_GROUPS,group)||search.loadingGroup.has(group))return;
  const offset=arr(search.result[group]).length;
  search.loadingGroup.add(group);
  button.disabled=true;
  button.textContent='加载中…';
  try{
    const d=await jget('/api/search?'+new URLSearchParams({q:search.q,scope:group,limit:String(SEARCH_PAGE_SIZE),offset:String(offset)}));
    if(state.globalSearch!==search)return;
    search.result[group]=arr(search.result[group]).concat(arr(d[group]));
    if(d.totals)search.result.totals={...search.result.totals,[group]:d.totals[group]};
    delete search.errors[group];
  }catch(err){search.errors[group]=true;}
  finally{
    search.loadingGroup.delete(group);
    const currentOut=document.getElementById('searchOut');
    if(state.globalSearch===search&&currentOut?.isConnected){
      drawSearchResults(currentOut,search);
      if(currentOut===out){
        const section=out.querySelector(`[data-search-results="${group}"]`);
        (section?.querySelectorAll('.result button')[offset]||section?.querySelector('.search-result-footer button'))?.focus();
      }
    }
  }
}

/* ================= 回收站 ================= */
function renderTrash(v){
  v.innerHTML=`<div class="page-head"><div><div class="eyebrow">System / Trash</div><h1>回收站</h1><p>删除是软删除：底本与产物保留，可在保留期内恢复。</p></div></div>
    <section class="panel">${state.trash.length?`<table class="table"><thead><tr><th>图书</th><th>编号</th><th>删除时间</th><th></th></tr></thead><tbody>${state.trash.map(t=>`<tr><td>${esc(t.book)}</td><td>${esc(t.code)}</td><td>${esc((t.time||'').replace('T',' ').slice(0,16))}</td><td class="right"><button class="btn sm ghost">恢复</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">回收站是空的</div>'}</section>`;
}

document.querySelectorAll('.nav-item').forEach(x=>x.addEventListener('click',()=>go(x.dataset.view)));

// 顶栏搜索：回车进「全局检索」，⌘K / Ctrl+K 聚焦，Esc 离开
(function wireTopSearch(){
  const inp=document.getElementById('globalQ');
  if(!inp) return;
  inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();const q=inp.value.trim();if(q)go('search',q);}
    else if(e.key==='Escape'){inp.blur();}
  });
  document.addEventListener('keydown',e=>{
    if((e.metaKey||e.ctrlKey)&&String(e.key||'').toLowerCase()==='k'){
      e.preventDefault();inp.focus();inp.select();
    }
  });
})();
window.addEventListener('scroll',()=>{if(state.lastHash===(location.hash||'#/dashboard')){state.scroll[state.lastHash]=window.scrollY;AppHistory.scroll(window.scrollY);}},{passive:true});
window.addEventListener('popstate',()=>{AppHistory.capture(false);MarketingOverlay.sync();if(state.lastHash===(location.hash||'#/dashboard'))window.Studio?.syncNavigation?.();});
window.addEventListener('hashchange',()=>{
  AppHistory.capture(false);AppHistory.sync();
  if(state.fromGo)state.fromGo=false;else state.depth=Math.max(0,state.depth-1);
  route({navigation:true});
});
document.addEventListener('click',event=>{const link=event.target.closest?.('a[href]');if(link&&link.getAttribute('href')?.startsWith('#/'))AppHistory.capture();},true);
document.addEventListener('input',()=>{if(MarketingOverlay.isOpen())MarketingOverlay.capture();});
document.addEventListener('change',()=>{if(MarketingOverlay.isOpen())MarketingOverlay.capture();});
window.addEventListener('pagehide',()=>{AppHistory.capture();MarketingOverlay.capture();});
document.addEventListener('DOMContentLoaded',boot,{once:true});

/* =====================================================================
   生产扩展：上传 / 任务 / 书详情页签 / 删除改判 / 能力设置 / 回收站
   说明：上面是版式原型的渲染层，这里补真实交互，并覆盖同名的原型函数。
   ===================================================================== */

function clearJobTimer(){ if(state.jobTimer){ clearTimeout(state.jobTimer); state.jobTimer=null; } }
function statusBadge(r){ return status(r); }
function protoPill(r){ return pill(r.prototype); }
function loading(t){ return `<div class="loading">${esc(t||'加载中')}</div>`; }

async function api(path){
  const r=await fetch(path,{headers:{'Accept':'application/json'}});
  const txt=await r.text(); let d;
  try{ d=JSON.parse(txt); }catch(e){ throw new Error('服务返回异常（HTTP '+r.status+'）'); }
  if(!r.ok || d.ok===false) throw new Error(d.error||('HTTP '+r.status));
  return d;
}
async function post(path,body){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body||{})});
  const txt=await r.text(); let d;
  try{ d=JSON.parse(txt); }catch(e){ throw new Error('服务返回异常（HTTP '+r.status+'）'); }
  if(!r.ok || d.ok===false){const error=new Error(d.error||('HTTP '+r.status));error.details=d;error.status=r.status;throw error;}
  return d;
}

let _toastTimer=null;
function toast(msg,bad){
  const el=document.getElementById('toast'); if(!el) return;
  el.textContent=msg; el.className='toast on'+(bad?' bad':'');
  clearTimeout(_toastTimer); _toastTimer=setTimeout(()=>{el.className='toast';},3600);
}
function openModal(html,wide,options){
  const close=options?.closeStep?'closeModal(false)':'closeModal()';
  const render=()=>{const root=document.getElementById('modalRoot');if(root)root.innerHTML=`<div class="modal" onclick="if(event.target===this)${close}"><div class="modal-card${wide?' wide':''}">${typeof html==='function'?html():html}</div></div>`;};
  MarketingOverlay.open('modal',render,undefined,options);
}
function closeModal(toRoot=true){
  if(MarketingOverlay.close(toRoot))return;
  const r=document.getElementById('modalRoot');if(r)r.innerHTML='';
}
function modalX(closeStep=false){ return '<button class="modal-x" onclick="'+(closeStep?'closeModal(false)':'closeModal()')+'" title="关闭">×</button>'; }

/* ---------------- 上传（带识别 + 大文件探测） ---------------- */
const UPLOAD_DISPLAY_FORMATS='TXT、Word（.docx）、PDF（含扫描件）';
let _uploadFile=null;
let _probe={token:'',meta:null,xhr:null,auto:{}};

function fmtSize(n){
  if(n>=1024*1024*1024) return (n/1024/1024/1024).toFixed(2)+' GB';
  if(n>=1024*1024) return (n/1024/1024).toFixed(2)+' MB';
  return Math.max(1,Math.round(n/1024))+' KB';
}
function openUpload(){
  _uploadFile=null; _probe={token:'',meta:null,xhr:null,auto:{}};
  openModal(`${modalX()}
    <h2>上传一本书</h2>
    <div class="upload-format-guide" id="uploadFormats">
      <p><strong>支持</strong> ${UPLOAD_DISPLAY_FORMATS}。</p>
      <p><strong>暂不支持</strong> 单独的图片（JPG、PNG）、旧版 Word（.doc）、EPUB、Excel、PPT 和 InDesign 文件。</p>
      <p class="muted">扫描模糊、双页拼版、多栏、竖排或图表较多时，请对照 PDF 原页核对文字和阅读顺序。</p>
    </div>
    <div class="drop" id="dropZone" onclick="document.getElementById('fileInput').click()">
      <div class="big">把书拖到这里，或点击选择文件</div>
      <div class="small" id="fileName">还没选文件</div>
    </div>
    <input type="file" id="fileInput" accept=".txt,.md,.markdown,.docx,.pdf" aria-describedby="uploadFormats" style="display:none">
    <div class="probe" id="upProbe"></div>
    <div class="formrow">
      <div class="field"><label for="upTitle">书名（必填）</label><input id="upTitle" placeholder="例：围城"></div>
      <div class="field"><label for="upAuthor">作者（可选）</label><input id="upAuthor" placeholder="例：钱钟书"></div>
      <div class="field"><label for="upPublisher">出版社（可选）</label><input id="upPublisher" placeholder="例：人民文学出版社"></div>
    </div>
    <div class="note" style="margin-top:11px">选择文件后会先查找书名、作者和出版社。核对或补填后，点「开始入库」。</div>
    <div id="upMsg" class="note" style="margin-top:9px"></div>
    <div class="modal-actions"><button class="btn ghost" onclick="closeModal()">取消</button><button class="btn primary" id="upBtn" onclick="submitUpload()" disabled>开始入库</button></div>`,true);
  const drop=document.getElementById('dropZone'), input=document.getElementById('fileInput');
  input.addEventListener('change',()=>{if(input.files[0])setUploadFile(input.files[0]);});
  ['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('over');}));
  ['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('over');}));
  drop.addEventListener('drop',e=>{const f=e.dataTransfer.files[0];if(f)setUploadFile(f);});
  loadUploadLimit();
}
function loadUploadLimit(){
  fetch('/api/health').then(r=>r.json()).then(d=>{if(d&&d.max_upload_mb)window.__maxUploadMB=d.max_upload_mb;}).catch(()=>{});
}
function setProbe(text,bad){
  const el=document.getElementById('upProbe'); if(!el)return;
  if(!text){el.style.display='none';el.textContent='';el.className='probe';return;}
  el.style.display='block'; el.className='probe'+(bad?' bad':''); el.textContent=text;
}
function setUploadFile(f){
  _uploadFile=f; _probe.token=''; _probe.meta=null; _probe.auto={};
  if(_probe.xhr){try{_probe.xhr.abort();}catch(e){}_probe.xhr=null;}
  const name=document.getElementById('fileName'); if(name)name.textContent=f.name+' · '+fmtSize(f.size);
  const msg=document.getElementById('upMsg'); if(msg)msg.textContent='';
  const btn=document.getElementById('upBtn'); if(btn){btn.disabled=true;btn.textContent='开始入库';}
  ['upAuthor','upPublisher'].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';});
  const t=document.getElementById('upTitle'); if(t)t.value=f.name.replace(/\.(txt|md|markdown|docx|pdf)$/i,'');
  _probe.auto.title=t?t.value:'';
  if(!/\.(txt|md|markdown|docx|pdf)$/i.test(f.name)){setProbe('暂不支持这种格式。可上传 '+UPLOAD_DISPLAY_FORMATS+'。',true);return;}
  const limit=window.__maxUploadMB||1024;
  if(f.size>limit*1024*1024){setProbe('这个文件 '+fmtSize(f.size)+'，超过 '+limit+' MB 上限。',true);return;}
  runProbe(f);
}
function autofill(id,key,value){
  const el=document.getElementById(id); if(!el||!value)return;
  const cur=el.value.trim(); if(cur&&cur!==(_probe.auto[key]||''))return;
  el.value=value; el.title=value; _probe.auto[key]=value;
}
function probeLine(p){
  const messages=[p.pages?`文件共 ${num(p.pages)} 页`:'文件已检查'];
  if(p.format==='pdf'||p.pages)messages.push('点击「开始入库」后读取全文，需要时识别扫描页（OCR）');
  const srcs=[];
  if(p.title&&p.title_source)srcs.push('书名取自'+p.title_source);
  if(p.author&&p.author_source)srcs.push('作者取自'+p.author_source);
  if(p.publisher&&p.publisher_source)srcs.push('出版社取自'+p.publisher_source);
  messages.push(...arr(p.warnings).slice(0,2));
  if(srcs.length)messages.push(srcs.join('，')+'，可修改');
  if(!p.author&&!p.publisher)messages.push('作者和出版社可手动补填');
  return messages.filter(Boolean).map(message=>message.replace(/。$/,'')+'。').join('');
}
function runProbe(f){
  const btn=document.getElementById('upBtn'); setProbe('正在上传文件并检查书目信息…');
  const xhr=new XMLHttpRequest(); _probe.xhr=xhr;
  xhr.open('POST','/api/probe?name='+encodeURIComponent(f.name));
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.upload.onprogress=e=>{if(e.lengthComputable&&e.total>4*1024*1024)setProbe('文件上传中 '+Math.round(e.loaded/e.total*100)+'%');};
  xhr.onload=()=>{
    if(xhr!==_probe.xhr)return; _probe.xhr=null;
    let d={}; try{d=JSON.parse(xhr.responseText||'{}');}catch(e){}
    if(xhr.status>=200&&xhr.status<300&&d.ok&&d.token){
      const p=d.probe||{}; _probe.token=d.token; _probe.meta=p;
      autofill('upTitle','title',p.title); autofill('upAuthor','author',p.author); autofill('upPublisher','publisher',p.publisher);
      setProbe(probeLine(p)); if(btn)btn.disabled=false;
    }else{
      setProbe((d.error||('文件预检失败（HTTP '+xhr.status+'）'))+'　仍可直接提交。',true); if(btn)btn.disabled=false;
    }
  };
  xhr.onerror=()=>{if(xhr!==_probe.xhr)return;_probe.xhr=null;setProbe('文件预检失败（网络错误）。仍可直接提交。',true);if(btn)btn.disabled=false;};
  xhr.send(f);
}
async function submitUpload(){
  const title=(document.getElementById('upTitle').value||'').trim();
  const author=(document.getElementById('upAuthor').value||'').trim();
  const publisher=(document.getElementById('upPublisher').value||'').trim();
  const msg=document.getElementById('upMsg'), btn=document.getElementById('upBtn');
  if(!_uploadFile){msg.textContent='先选一个文件。';return;}
  if(_probe.xhr){msg.textContent='正在检查文件，请稍等。';return;}
  if(!title){msg.textContent='书名不能为空。';return;}
  btn.disabled=true; const old=btn.textContent; btn.textContent=_probe.token?'提交中…':'上传中…';
  msg.textContent=_probe.token?'正在创建任务…':'正在上传…';
  if(_probe.token){
    try{
      const d=await post('/api/upload',{token:_probe.token,title,author,publisher});
      closeModal(); toast('上传完成，已进入入库任务'); go('job',d.job.id);
    }catch(e){btn.disabled=false;btn.textContent=old;msg.textContent=e.message;}
    return;
  }
  const fd=new FormData(); fd.append('file',_uploadFile); fd.append('title',title); fd.append('author',author); fd.append('publisher',publisher);
  const xhr=new XMLHttpRequest(); xhr.open('POST','/api/upload');
  xhr.upload.onprogress=e=>{if(e.lengthComputable)msg.textContent='上传中 '+Math.round(e.loaded/e.total*100)+'%';};
  xhr.onload=()=>{
    let d={}; try{d=JSON.parse(xhr.responseText||'{}');}catch(e){}
    if(xhr.status>=200&&xhr.status<300&&d.ok){closeModal();toast('上传完成，已进入入库任务');go('job',d.job.id);}
    else{btn.disabled=false;btn.textContent=old;msg.textContent=d.error||('上传失败（HTTP '+xhr.status+'）');}
  };
  xhr.onerror=()=>{btn.disabled=false;btn.textContent=old;msg.textContent='网络错误，上传失败。';};
  xhr.send(fd);
}

/* ---------------- 入库任务 / 任务详情 ---------------- */
async function viewJob(jobId){
  const v=document.getElementById('view'),isCurrent=capturePageRequest(v);v.innerHTML=loading('加载任务');
  let previous='';
  const tick=async()=>{
    if(!isCurrent())return;
    try{
      const d=await api('/api/jobs/'+encodeURIComponent(jobId));
      if(!isCurrent())return;
      const current=JSON.stringify([d.job.status,d.job.progress,d.job.steps,d.job.warnings]);
      if(current!==previous){previous=current;renderJob(v,d.job);}
      if(!['done','partial','failed'].includes(d.job.status)){state.jobTimer=setTimeout(tick,1300);}
    }catch(e){if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">任务加载失败：${esc(e.message)}</div></div>`;}
  };
  tick();
}
function stepIcon(s){
  if(s.status==='done')return '✓'; if(['skipped','not_applicable'].includes(s.status))return '−'; if(s.status==='running')return '●'; if(s.status==='failed')return '✕'; if(s.status==='partial')return '!'; return '○';
}
function renderJob(v,job){
  if(job.kind==='project_assist'){
    const st=job.status||'queued',done=st==='done',failed=st==='failed',prompts=job.capability==='video_prompts';
    v.innerHTML=`<div class="page-head"><div><div class="eyebrow">PROJECT ASSISTANCE</div><h1>${esc(job.title||'项目辅助任务')}</h1><p>${prompts?'根据已确认的大纲和呈现方式生成提示词，完成后可复制到制作工具使用。':job.capability==='recommend'?'根据任务目标查找可用材料，提供推荐理由与资料缺口。':'根据采用的材料生成讨论稿，所有方案仍需编辑判断。'}</p></div><span class="status ${done?'ok':failed?'fail':'wait'}">${esc({queued:'排队中',running:'生成中',done:'已完成',partial:'部分完成',failed:'失败'}[st]||st)}</span></div>
      <section class="panel"><div class="panel-body"><div class="progress"><i style="width:${Number(job.progress||0)}%"></i></div><div class="muted">${Number(job.progress||0)}%</div><div class="steps">${(job.steps||[]).map(s=>`<div class="step ${s.status||'pending'}"><span class="ico">${stepIcon(s)}</span><div><div class="lbl">${esc(s.label||s.key)}</div><div class="det">${esc(s.detail||'')}</div></div></div>`).join('')}</div>
      ${failed?'<div class="banner red">本次生成未完成：'+esc(job.error||'请查看任务记录')+'。已有项目草稿保留，可回项目重试。</div>':done?'<div class="banner">'+(prompts?'提示词已保存，可返回稿件查看并复制。':'结果已保存。返回项目查看推荐或讨论稿，再决定是否采用；生成结果尚未自动审核。')+'</div>':'<p class="studio-note">任务在后台处理，离开页面后仍会继续。</p>'}
      <div class="modal-actions"><button class="btn primary" data-id="${esc(job.project_id||'')}" data-view="${job.project_kind==='marketing'?'campaigns':'projects'}" data-section="${prompts?'results':''}" onclick="go(this.dataset.view,this.dataset.id,this.dataset.section)">返回项目查看结果</button><button class="btn ghost" onclick="go('tasks')">查看全部任务</button></div></div></section>`;
    return;
  }
  const st=job.status||'queued';
  const stText={queued:'等待处理',running:'处理中',done:'已完成',partial:'部分完成',failed:'未完成'}[st]||st;
  const cls=st==='done'?'ok':st==='failed'?'fail':'wait';
  const title=job.title||job.book_title||'新书';
  const code=job.book_code||(job.result&&job.result.code)||'';
  const jobNames={upload:'图书入库',upload_supplement:'补做图书内容',restore:'恢复图书',retype:'调整图书分类',marketing:'整理营销资料',summaries:'生成章节摘要',tag:'补齐图书标签'};
  const stepNames={parse:'读取文件',judge:'整理章节与正文',audit:'检查章节和出处',export:'汇总已整理的内容',tags:'整理标签',pages:'更新图书档案',kg:'生成图谱索引',store:'保存结果'};
  const stepStates={queued:'等待处理',pending:'还未开始',running:'处理中',done:'已完成',partial:'部分完成',failed:'未完成',skipped:'已跳过',not_applicable:'不适用'};
  const needsAttention=st==='partial'||st==='failed';
  const progress=Math.min(100,Math.max(0,Number(job.progress)||0));
  const activeStep=arr(job.steps).find(s=>s.status==='running');
  const activeParse=activeStep?.key==='parse'&&activeStep.detail?activeStep:null;
  const failedStep=arr(job.steps).find(s=>s.status==='failed');
  const issues=st==='failed'?(failedStep?[`处理停在「${stepNames[failedStep.key]||failedStep.label||'检查内容'}」。`]:[]):arr(job.warnings).map(message=>String(message).replace(/^[⚠！!\s]+/,''));
  const failedPages=st==='failed'&&!code&&job.source_page_issues&&Object.keys(job.source_page_issues).length
    ?reportPageIssues(job):null;
  v.innerHTML=`
    <div class="page-head"><div><h1>${esc(title)}</h1><p>${esc(jobNames[job.kind]||'处理图书')}</p></div>
      <span class="status ${cls}">${esc(stText)}</span></div>
    <section class="panel"><div class="panel-body">
      ${needsAttention?`<div class="banner red job-notice"><b>${st==='failed'?'这次处理未完成':'有些内容需要继续处理或核对'}</b>${issues.length?`<ul>${issues.map(issue=>`<li>${esc(issue)}</li>`).join('')}</ul>`:''}${job.retryable?'<p>可以直接继续，使用已上传的文件和已保存的结果。</p>':''}</div>`:''}
      ${['queued','running'].includes(st)?`<p><b>${esc(st==='queued'?'等待前面的任务处理完':activeParse?.detail||activeStep?.label||'正在准备文件')}</b></p><div class="progress" role="progressbar" aria-label="总进度" aria-valuenow="${progress}"><i style="width:${progress}%"></i></div><p class="muted">总进度 ${progress}% · 可以先离开，处理会继续。</p>`:''}
      <div class="steps">${arr(job.steps).map(s=>`<div class="step ${esc(s.status||'pending')}"><span class="ico" aria-hidden="true">${stepIcon(s)}</span><div><div class="lbl">${esc(stepNames[s.key]||s.label||'处理内容')}</div><div class="det">${esc(stepStates[s.status]||'等待处理')}${s.detail&&s!==activeParse?' · '+esc(s.detail):''}</div></div></div>`).join('')}</div>
      ${failedPages?`<details class="job-details" open><summary>页面检查 · ${esc(failedPages.summary)}</summary>${failedPages.html}</details>`:''}
      ${st==='done'?`<div class="banner">${job.kind==='marketing'?'营销资料已更新。下一步返回资料页，核对并确认新的内容。':job.result?.status==='pending'?'处理完成，图书信息或正文还有待核对的地方。':'本次处理完成。可以到图书档案查看已整理的内容。'}</div>`:''}
      <div class="modal-actions">${needsAttention&&job.retryable?`<button type="button" class="btn primary" data-id="${esc(job.id)}" onclick="retryJob(this)">${esc(job.retry_label||'继续处理')}</button>`:''}${job.kind==='marketing'&&code?`<button type="button" class="btn ${['done','partial'].includes(st)?'primary':'ghost'}" data-code="${esc(code)}" onclick="go('marketing',this.dataset.code)">${['done','partial'].includes(st)?'返回营销资料继续核对':'返回营销资料'}</button>`:['done','partial'].includes(st)&&code?`<button type="button" class="btn ${job.retryable?'ghost':'primary'}" data-code="${esc(code)}" onclick="openJobBook(this)">查看图书档案</button><button type="button" class="btn ghost" data-code="${esc(code)}" onclick="go('report',this.dataset.code)">查看解析情况</button>`:''}<button class="btn ghost" onclick="go('tasks')">查看全部任务</button></div>
    </div></section>
    ${!['queued','running'].includes(st)?`<details class="panel job-details"><summary>查看处理记录</summary><div class="panel-body">${job.error?`<p>${esc(job.error)}</p>`:''}${arr(job.steps).filter(s=>s.detail).map(s=>`<p><b>${esc(stepNames[s.key]||s.label||'处理内容')}</b> ${esc(s.detail)}</p>`).join('')}${job.log?.length?`<pre class="logbox">${esc(job.log.slice(-40).join('\n'))}</pre>`:''}<button type="button" class="btn sm ghost" data-id="${esc(job.id)}" onclick="delJob(this.dataset.id,true)">删除任务记录</button></div></details>`:''}`;
}

async function retryJob(button){
  const label=button.textContent;
  button.disabled=true;
  button.textContent='正在提交…';
  try{
    const d=await post('/api/jobs/retry',{id:button.dataset.id});
    if(!button.isConnected)return;
    if(!d.job?.id)throw new Error('暂时无法提交重试任务，请稍后再试。');
    toast('已提交，可以查看这次进度。');
    if(parse().arg===d.job.id)await viewJob(d.job.id);
    else go('job',d.job.id);
  }catch(err){
    if(!button.isConnected)return;
    button.disabled=false;
    button.textContent=label;
    toast(err.message,true);
  }
}

function openJobBook(button){
  delete state.bookCache[button.dataset.code];
  go('book',button.dataset.code,'tags');
}

async function delJob(id, back){
  if(!confirm('只删除这条任务记录，不会删除图书与已入库的资产。确定？')) return;
  try{
    await post('/api/jobs/delete',{id});
    toast('任务记录已删除');
    go('tasks');
  }catch(e){ toast(e.message,true); }
}
async function clearJobs(){
  if(!confirm('清空所有已完成 / 已失败的任务记录？图书与资产不受影响。')) return;
  try{
    const d=await post('/api/jobs/clear',{});
    toast('已清空 '+d.deleted+' 条任务记录');
    go('tasks');
  }catch(e){ toast(e.message,true); }
}

async function renderTasks(v,tab){
  state.taskTab = tab==='records'?'records':'jobs';
  crumb(`<span>数据资产</span><span>/</span><b>运行任务</b>${state.taskTab==='records'?'<span>/</span><b>记录</b>':''}`);
  v.innerHTML=`
    <div class="page-head"><div><h1>运行任务</h1>
      <p>查看上传和整理进度。打开一条任务，可以看结果或继续未完成的处理。</p></div>
      <div class="head-actions"><button class="btn primary" onclick="openUpload()">＋ 上传图书</button></div></div>
    <div class="cand-tabs" id="taskTabs">
      <button class="${state.taskTab==='jobs'?'on':''}" onclick="setTaskTab('jobs')">任务</button>
      <button class="${state.taskTab==='records'?'on':''}" onclick="setTaskTab('records')">记录</button>
    </div>
    <div id="taskBody"></div>`;
  drawTaskTab();
}
function setTaskTab(t){
  state.taskTab=t;
  document.querySelectorAll('#taskTabs button').forEach(b=>b.classList.toggle('on',b.textContent.trim()===(t==='records'?'记录':'任务')));
  try{history.replaceState(null,'',t==='records'?'#/tasks/records':'#/tasks');}catch(e){}
  crumb(`<span>数据资产</span><span>/</span><b>运行任务</b>${t==='records'?'<span>/</span><b>记录</b>':''}`);
  drawTaskTab();
}
function drawTaskTab(){
  if(state.taskTab==='records') return drawOpsRecords();
  return drawJobsPanel();
}
async function drawJobsPanel(){
  const host=document.getElementById('taskBody'); if(!host)return;
  try{const d=await api('/api/jobs');state.jobs=d.jobs||[];}catch(e){state.jobs=state.jobs||[];}
  updateNavTasks();
  const jobs=state.jobs||[];
  host.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>最近任务</h2><div class="sub">查看进度和处理结果</div></div><span class="faint">${jobs.length} 条</span><button class="btn sm ghost" onclick="clearJobs()">清空已完成</button></div>
    <table class="table"><thead><tr><th>任务</th><th>图书 / 项目</th><th>状态</th><th class="num">进度</th><th>创建时间</th><th class="right">操作</th></tr></thead>
    <tbody>${jobs.length?jobs.slice(0,50).map(j=>`<tr onclick="go('job','${esc(j.id)}')"><td>${esc(({upload:'入库',upload_supplement:'补做图书内容',restore:'恢复',retype:'改分类',marketing:'营销资料',summaries:'章节摘要',tag:'整理标签',project_assist:'项目辅助'}[j.kind]||'图书处理'))}</td><td>${esc(j.title||'—')}</td><td><span class="status ${j.status==='done'?'ok':j.status==='failed'?'fail':'wait'}">${esc({queued:'等待处理',running:'处理中',done:'已完成',partial:'部分完成',failed:'未完成'}[j.status]||j.status)}</span></td><td class="num">${num(j.progress)}%</td><td>${esc((j.created_at||'').replace('T',' ').slice(0,16))}</td><td class="right"><button class="btn sm ghost" onclick="event.stopPropagation();delJob('${esc(j.id)}')">删除</button></td></tr>`).join(''):'<tr><td colspan="6"><div class="empty">还没有任务</div></td></tr>'}</tbody></table>
  </section>`;
}
const OP_LABEL={upload:'上传入库',delete:'删除',restore:'恢复',clc:'分类变更',confirm:'人工确认',settings:'能力配置',entity_review:'专名复核'};
function opNote(o){
  const x=o.detail||{};
  if(o.event==='upload')return [x.format,x.prototype?'判型 '+x.prototype:'',x.confidence?'置信 '+x.confidence:'',(x.cards!=null?x.cards+' 条':'')].filter(Boolean).join(' · ');
  if(o.event==='delete')return '回收站 '+(x.trash_id||'');
  if(o.event==='restore')return '从回收站 '+(x.trash_id||'')+' 恢复';
  if(o.event==='clc')return '改为 '+[(x['代码']||''),(x['名称']||'')].filter(Boolean).join(' ');
  if(o.event==='confirm')return x.job==='manual'?'手动确认':'任务 '+(x.job||'');
  if(o.event==='entity_review')return (x.action||'处理')+(x.name?' · '+x.name:'');
  if(o.event==='settings')return '任务 '+(x.job||'');
  return x.title||'';
}
async function drawOpsRecords(){
  const host=document.getElementById('taskBody'); if(!host)return;
  host.innerHTML=loading('加载记录');
  if(!state.ops){ try{const d=await api('/api/ops?limit=500');state.ops=d.items||[];}catch(e){state.ops=[];} }
  if(!state.opsFilter)state.opsFilter='all';
  const all=state.ops||[];
  const kinds=['all'].concat(Object.keys(OP_LABEL).filter(k=>all.some(o=>o.event===k)));
  const cnt=k=>k==='all'?all.length:all.filter(o=>o.event===k).length;
  const bookName=code=>{const b=state.books.find(x=>x.code===code);return b?b.book:(code==='_settings'?'全库设置':code);};
  host.innerHTML=`<section class="panel">
    <div class="panel-head"><div><h2>全部记录</h2><div class="sub">只读：这里不能删除也不能清空，审计要用</div></div><span class="faint">${num(all.length)} 条</span></div>
    <div class="chips" style="padding:12px 16px 0;border:0">
      ${kinds.map(k=>`<span class="chip ${state.opsFilter===k?'on':''}" data-k="${k}" onclick="setOpsFilter('${k}')">${k==='all'?'全部':OP_LABEL[k]} ${num(cnt(k))}</span>`).join('')}
    </div>
    <div class="cand-toolbar" style="padding:12px 16px 0">
      <div class="search"><input id="opsQ" placeholder="搜书名 / 编号" value="${esc(state.opsQ||'')}"
        onkeydown="if(event.key==='Enter'){event.preventDefault();applyOpsQ();}"><kbd>↵</kbd></div>
      <button class="btn sm" onclick="applyOpsQ()">查询</button>
    </div>
    <div id="opsTable" style="padding:0 16px 16px"></div>
  </section>`;
  drawOpsTable();
}
function setOpsFilter(k){state.opsFilter=k;document.querySelectorAll('.chips .chip[data-k]').forEach(c=>c.classList.toggle('on',c.dataset.k===k));drawOpsTable();}
function applyOpsQ(){const el=document.getElementById('opsQ');state.opsQ=el?el.value.trim():'';drawOpsTable();}
function drawOpsTable(){
  const host=document.getElementById('opsTable'); if(!host)return;
  const bookName=code=>{const b=state.books.find(x=>x.code===code);return b?b.book:(code==='_settings'?'全库设置':code);};
  const q=(state.opsQ||'').toLowerCase();
  const rows=(state.ops||[]).filter(o=>(state.opsFilter==='all'||o.event===state.opsFilter)&&
    (!q||(bookName(o.code)+' '+o.code).toLowerCase().includes(q)));
  host.innerHTML=rows.length?`<table class="table"><thead><tr><th style="width:132px">时间</th><th style="width:190px">图书</th><th style="width:96px">事件</th><th>变更内容</th><th style="width:26px"></th></tr></thead><tbody>
    ${rows.map(o=>`<tr onclick="go('book','${esc(o.code)}','records')">
      <td><span class="mono">${esc((o.time||'').replace('T',' ').slice(0,16))}</span></td>
      <td>${esc(clip(bookName(o.code),18))}</td>
      <td><span class="pill">${OP_LABEL[o.event]||o.event}</span></td>
      <td class="faint">${esc(opNote(o))}</td>
      <td class="chev">›</td></tr>`).join('')}</tbody></table>`
    :`<div class="empty">没有符合条件的记录</div>`;
}
function updateNavTasks(){
  const n=(state.jobs||[]).filter(j=>j.status==='queued'||j.status==='running').length;
  const el=document.getElementById('navTaskCount'); if(!el)return;
  el.textContent=n?String(n):''; el.style.display=n?'':'none';
}
function exportLibraryCsv(){
  const F=state.libFilters||{}, q=(F.q||'').toLowerCase();
  const rows=state.books.filter(b=>{
    if(q&&![b.book,b.author,b.code,b.prototype_name].join(' ').toLowerCase().includes(q))return false;
    if(F.clc&&((b.clc||{}).代码||'')!==F.clc)return false;
    if(F.status==='pending'&&b.status!=='pending')return false;
    if(F.status==='ready'&&b.status==='pending')return false;
    return true;
  });
  const cell=v=>{v=v==null?'':String(v);return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
  const head=['编号','书名','作者','出版社','图书分类','中图分类','状态','内容段','汉字','资产条目','知识类成果','索引类','标签','入库时间'];
  const lines=[head.join(',')].concat(rows.map(b=>[
    b.code,b.book,b.author||'',b.publisher||'',(b.prototype||'')+' '+(b.prototype_name||''),
    (b.clc&&b.clc['代码'])?b.clc['代码']+' '+b.clc['名称']:'',
    b.status==='pending'?'待确认':'已入库',b.segments,b.han,b.cards,b.knowledge||0,b.index||0,b.tags,(b.added_at||'').slice(0,10)
  ].map(cell).join(',')));
  const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob); a.download='来源图书清单_'+new Date().toISOString().slice(0,10)+'.csv';
  document.body.appendChild(a); a.click(); setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},500);
  toast('已导出 '+rows.length+' 本');
}

function isIndexType(t){return /^(篇目|引书|索引|专名|目录)/.test(String(t||''));}
function kindBreakdown(types,kind){
  const map={};
  Object.keys(types||{}).forEach(t=>{
    if((isIndexType(t)?'索引':'知识')!==kind)return;
    map[t]=types[t];
  });
  return Object.keys(map).sort((a,b)=>map[b]-map[a]).map(t=>t+' '+num(map[t])).join(' · ');
}
async function renderBook(v,code,tab,q,extra){
  const isCurrent=capturePageRequest(v);
  // 父级按真实来路显示：从工作台进来就写「工作台」，别写成来源图书却回退到首页
  const _pv=(state.navPrev&&state.navPrev.view)||'';
  const _pm={dashboard:['工作台','dashboard'],library:['来源图书','library'],
    archive:['图书档案','archive'],assets:['知识资产','assets'],
    search:['跨书搜索','search'],job:['入库任务','tasks'],kg:['知识图谱','kg']}[_pv]||['来源图书','library'];
  if(!isCurrent())return;crumb(`<span>数据资产</span><span>/</span><a onclick="go('${_pm[1]}')">${_pm[0]}</a><span>/</span><b>图书档案</b>`);
  if(!isCurrent())return;v.innerHTML=loading('加载图书档案');
  let d;
  try{d=await jget('/api/book?code='+encodeURIComponent(code));}catch(e){if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">加载失败：${esc(e.message)}</div></div>`;return;}
  if(!isCurrent())return;
  state.bookCache[code]=d;
  state.book=d; state.cand={tier:'',type:'',q:'',ke:'',page:0,offset:0,items:[],total:0,byType:{},loading:false}; state.pin=null;
  if(!d._byType){try{const _bt=await jget('/api/book/cards?code='+encodeURIComponent(code)+'&limit=1');d._byType=_bt.by_type||{};}catch(e){d._byType={};}}
  if(!state.kgBuilt){try{const _kg=await jget('/api/kg/books');state.kgBuilt=new Set((_kg.books||[]).filter(x=>x.status==='已建图').map(x=>x.code));}catch(e){state.kgBuilt=new Set();}}
  if(!isCurrent())return;
  // 落点由入口决定：带 tab 就落到那个页签，不带就回概览。
  // 以前这里直接沿用上一次的 state.detailTab，导致「从档案点进来却停在标签体系」。
  if(tab==='marketing'){location.replace('#/marketing/'+encodeURIComponent(code));return;}
  const _alias={pub:'archive',pages:'archive',tags:'archive',records:'archive',audit:'archive'};
  state.archFocus=_alias[tab]?tab:'';
  state.detailTab=['overview','text','archive'].includes(_alias[tab]||tab)?(_alias[tab]||tab):'overview';
  // 深链带筛选：#/book/B56/assets/毛茛科 —— 是科名就精确筛，不是就当自由词
  if(q){ if(keNames(d).indexOf(q)>=0)state.cand.ke=q; else state.cand.q=q; }
  const b=d.book||{},r=d.row||{},rec=d.record||{};
  const title=r.book||b.book||rec.book||code;
  // 末级写书名，避免「图书档案 / 图书档案」重复
  // 工作台是顶层，不该写成「数据资产 / 工作台」
  const _head = (_pm[1]==='dashboard'||_pm[1]==='kg') ? '' : '<span>数据资产</span><span>/</span>';
  if(!isCurrent())return;crumb(`${_head}<a onclick="go('${_pm[1]}')">${_pm[0]}</a><span>/</span><b>${esc(clip(title,22))}</b>`);
  const tc=d.tag_counts||{},cc=d.cards||{};
  const pending=r.status==='pending';
  const sourceText=rec.source==='upload'?`上传 · ${rec.source_format||''}${rec.source_pages?' · '+rec.source_pages+' 页':''}`:'馆藏图书';
  if(!isCurrent())return;v.innerHTML=`
    <section class="panel book-hero">
      <div class="book-cover">${esc(coverChar(title))}</div>
      <div class="hero-main">
        <div class="eyebrow">${esc(r.code||code)}</div>
        <h1>${esc(title)}</h1>
        <div class="meta">${[r.author,r.publisher].filter(Boolean).map(esc).join(' · ')||'作者 / 出版社未填写'} <span class="faint">· ${esc(sourceText)}</span></div>
        <div class="badges"><span class="pill ${esc(String(r.prototype||'').toLowerCase())}">参考书型 ${esc(PROTO[r.prototype]||'待分类')}</span>${(d.clc&&d.clc['代码'])?`<span class="pill clc-pill" title="中图分类：${esc((d.clc['依据']||[]).join('；'))}">中图分类 ${esc(d.clc['代码'])} ${esc(d.clc['名称'])}</span>`:''}${status(r)}${b['人工改判']?'<span class="pill p5">人工分类</span>':''}${b['算法断句']?'<span class="pill p3">标点待核对</span>':''}</div>
        <div class="hero-actions">
          <button class="btn sm primary" data-code="${esc(code)}" onclick="go('content',this.dataset.code)">查看全部成果</button>
          <button type="button" class="btn sm ghost" data-code="${esc(code)}" onclick="go('creator-match',this.dataset.code)">匹配达人</button>
          ${pending?`<button class="btn sm gold" data-code="${esc(r.code)}" onclick="confirmBook(this.dataset.code)">标为已确认</button>`:''}
          <button class="btn sm ghost" data-code="${esc(r.code)}" data-author="${esc(r.author||'')}" data-publisher="${esc(r.publisher||'')}" onclick="openMeta(this.dataset.code,this.dataset.author,this.dataset.publisher)">编辑信息</button>
          <button class="btn sm ghost" data-code="${esc(r.code)}" data-title="${esc(title)}" data-proto="${esc(r.prototype||'')}" onclick="openRetype(this.dataset.code,this.dataset.title,this.dataset.proto)">改分类</button>
          <button class="btn sm ghost" data-code="${esc(r.code)}" data-title="${esc(title)}" onclick="openDelete(this.dataset.code,this.dataset.title)">删除</button>
        </div>
      </div>
      <div class="hero-stats">
        <div class="hs"><b>${num(r.han)}</b><span>汉字</span></div><div class="hs"><b>${num(r.segments)}</b><span>内容段</span></div>
        <div class="hs"><b>${num(cc.total)}</b><span>资产条目</span></div><div class="hs"><b>${tc.total?num(tc.total):'—'}</b><span>标签</span></div>
      </div>
    </section>
    ${pending?`<div class="banner">这本书有待核对的地方。可先查看已经整理的原文和内容，具体情况见「档案与记录」。</div>`:''}
    ${b['结构审计']&&b['结构审计']['异常']?`<div class="banner red"><b>章节和正文需要核对。</b>${esc(b['结构审计']['说明']||'')} 正式引用前请对照原书。</div>`:''}
    <div id="kgBookPanel"></div>
    <div class="tabs">
      <button class="${state.detailTab==='overview'?'on':''}" onclick="setTab('overview')">概览</button>
      <button class="${state.detailTab==='text'?'on':''}" onclick="setTab('text')">原文</button>
      <button class="${state.detailTab==='archive'?'on':''}" onclick="setTab('archive')">档案与记录</button>
    </div>
    <div id="detailBody"></div>`;
  drawDetailTab();
  fillBookKgPanel(code);
  // #/book/B56/text/B56-08-P01 —— 深链直接定位到某一段。
  // 跳转的「来意」（标什么词、横幅写什么）优先取入口带进来的，其次取 URL 里的，
  // 都没有就当成普通定位——不在原文页里猜。
  if(tab==='text'&&q)setTimeout(function(){if(!isCurrent())return;
    const j=state.entJump; state.entJump=null;
    if(j)locateAnchor(q,j.term,j.mode,j.total,j.from);
    else locateAnchor(q,
      extra?(extra.get('t')||''):'',
      extra?(extra.get('k')||''):'',
      extra?Number(extra.get('n')||0):0,
      extra?(extra.get('f')||''):'');
  },0);
}

/* 书详情里的图谱入口：只对已建图的书展示，不暴露建图决策 */
async function fillBookKgPanel(code){
  const host=document.getElementById('kgBookPanel'); if(!host)return;
  try{
    const d=await jget('/api/kg/books');
    const badge=document.getElementById('navKgCount');
    if(badge) badge.textContent=String((d.books||[]).filter(x=>x.status==='已建图').length);
    const b=(d.books||[]).find(x=>x.code===code);
    if(!b || b.status!=='已建图'){ host.innerHTML=''; return; }
    host.innerHTML=`<div class="kg-line">
      <span class="kg-ico">◉</span><b>知识图谱</b>
      <span class="faint">${esc(b.form||'')} · ${num(b.nodes||0)} 个节点 · ${num(b.edges||0)} 条关系</span>
      <button class="btn sm ghost" onclick="go('kg','${esc(code)}')">打开 →</button>
    </div>`;
  }catch(e){ host.innerHTML=''; }
}

/* ================= 单条知识条目（独立页面） ================= */
// 「展开」不再原地撑开、把别的条目留在下面；现在是自己的一个路由：#/card/<书码>/<条目id>
async function renderCard(v,code,cid){
  const isCurrent=capturePageRequest(v);
  if(!isCurrent())return;v.innerHTML=loading('加载条目');
  let item=null;
  try{
    const d=await jget('/api/book/card?'+new URLSearchParams({code,id:cid}).toString());
    item=d.item||null;
  }catch(e){if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">加载失败：${esc(e.message)}</div></div>`;return;}
  if(!item){if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">条目不存在：${esc(cid)}</div></div>`;return;}
  if(!isCurrent())return;
  state.cardItem=item;
  let bk=state.bookCache[code];
  if(!bk){try{bk=await jget('/api/book?code='+encodeURIComponent(code));state.bookCache[code]=bk;}catch(e){}}
  const title=(bk&&bk.row&&bk.row.book)||code;
  const f=item['字段']||{};
  const name=cardName(item);
  if(!isCurrent())return;crumb(`<span>数据资产</span><span>/</span><a onclick="go('library')">来源图书</a><span>/</span><a onclick="go('book','${esc(code)}')">${esc(clip(title,16))}</a><span>/</span><a onclick="go('book','${esc(code)}')">图书</a><span>/</span><b>${esc(item.id)}</b>`);
  const isIndex=(item['类型']==='篇目候选'||item['类型']==='引书候选');
  const backQ=(state.cardBack&&state.cardBack.code===code&&state.cardBack.q)||'';
  const back=`<button class="btn ghost" onclick="go('book','${esc(code)}')">← 返回图书</button>`;
  if(!isCurrent())return;v.innerHTML=`
    <div class="page-head">
      <div><div class="eyebrow">${esc(item.id)} · ${esc(item['类型']||'')}</div><h1>${esc(clip(name,30))}</h1>
        <p><a onclick="go('book','${esc(code)}')">${esc(title)}</a> · ${esc(item['锚点']||'')} · ${num((item['原文']||'').length)} 字</p></div>
      <div class="head-actions">${item['seg_id']?`<button class="btn primary" data-code="${esc(code)}" data-seg="${esc(item['seg_id'])}" data-name="${esc(cardName(item))}" onclick="openSegTerm(this.dataset.code,this.dataset.seg,this.dataset.name)">在原文中定位 →</button>`:''}${back}</div>
    </div>
    <div class="badges" style="margin:-6px 0 16px">
      <span class="pill">${esc(item['类型']||'条目')}</span>
      <span class="pill">${esc(item['资产性质']||'—')}</span>
      ${item['精度']?`<span class="pill">${esc(item['精度'])}精度</span>`:''}
      ${item['可回查']?'<span class="pill">可回查原文</span>':'<span class="pill p3">不可回查</span>'}
    </div>
    <section class="panel"><div class="panel-head"><div><h2>原文</h2><div class="sub">${item['依据']?esc(item['依据']):'这条内容就从这一段切出来的'}</div></div><span class="faint mono">${esc(item['锚点']||'')}</span></div>
      <div class="panel-body"><div class="card-raw">${esc(item['原文']||'（无原文）')}</div></div></section>
    ${isIndex?`<section class="panel" style="margin-top:16px"><div class="panel-head"><div><h2>这是索引</h2><div class="sub">篇目/引书只是定位器，不是内容成果；点“在原文中定位”直接看原文。</div></div></div></section>`:(Object.keys(f).length?`<section class="panel" style="margin-top:16px"><div class="panel-head"><div><h2>条目信息</h2><div class="sub">${Object.keys(hideRedundantFields(f)).length} 项</div></div></div><div class="panel-body"><div class="fields">${fieldRows(hideRedundantFields(f))}</div></div></section>`:'')}
}`;
}

function openAssets(){
  state.cand={tier:'',type:'',q:'',ke:'',page:0,offset:0,items:[],total:0,byType:{},loading:false};
  state.pin=null; state.detailTab='assets';
  const code=state.book&&state.book.row&&state.book.row.code;
  if(code){try{history.pushState(null,'','#/book/'+encodeURIComponent(code)+'/assets');}catch(e){}}
  document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x.textContent.trim()==='知识资产'));
  drawDetailTab();
}

/* ================= 全部科名（独立页面） ================= */
// 以前的「全部 118 个科 ›」只是切页签 + 聚焦一个 118 项的下拉框；
// 现在是一个页面：每个科带真实条目数，点一个直接进该科的条目列表。
async function renderKes(v,code){
  const isCurrent=capturePageRequest(v);
  if(!isCurrent())return;v.innerHTML=loading('加载科名');
  let d=null;
  try{ d=await jget('/api/book?code='+encodeURIComponent(code)); }catch(e){ if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">加载失败：${esc(e.message)}</div></div>`; return; }
  const counts=d.ke_counts||{};
  const names=keNames(d);
  const rows=names.map(n=>({n:n,c:counts[n]||0})).sort((a,b)=>b.c-a.c||a.n.localeCompare(b.n,'zh'));
  const total=rows.reduce((a,x)=>a+x.c,0);
  const bookTotal=(d.cards&&d.cards.total)||total;
  const miss=bookTotal-total;   // 没标科名的条目：不藏，直接说清楚
  const title=(d.row&&d.row.book)||code;
  if(!isCurrent())return;crumb(`<span>数据资产</span><span>/</span><a onclick="go('library')">来源图书</a><span>/</span><a onclick="go('book','${esc(code)}')">${esc(clip(title,16))}</a><span>/</span><b>全部科名</b>`);
  if(!isCurrent())return;v.innerHTML=`
    <div class="page-head">
      <div><div class="eyebrow">${esc(code)} · 按科浏览</div><h1>全部科名</h1>
        <p>${num(rows.length)} 个科 · ${num(total)} 条带科名${miss>0?`（全书 ${num(bookTotal)} 条，${num(miss)} 条未标科名）`:''} · 按条目数排序，点一个看这一科的条目</p></div>
      <div class="head-actions"><button class="btn ghost" onclick="go('book','${esc(code)}')">← 返回这本书</button></div>
    </div>
    <section class="panel">
      <div class="panel-head"><div><h2>${num(rows.length)} 个科</h2><div class="sub">点一个进入该科的条目列表</div></div>
        <span class="faint">${num(total)} 条${miss>0?' / 全书 '+num(bookTotal):''}</span></div>
      <div class="panel-body">
        <div class="cand-toolbar"><div class="search"><input id="kesQ" placeholder="搜科名，如「松科」" oninput="filterKes(this.value)"><kbd>⌕</kbd></div></div>
        <div class="ke-grid" id="keGrid">${rows.map(x=>keCard(code,x.n,x.c)).join('')}</div>
        <div class="faint" id="kesEmpty" style="display:none;padding:14px 2px">没有匹配的科</div>
      </div>
    </section>`;
  state.kesRows=rows;
}
function keCard(code,name,n){
  return `<a class="ke-card" data-ke="${esc(name)}" onclick="go('book','${esc(code)}','assets','${esc(name)}')" title="${esc(name)} · ${num(n)} 条">
    <b>${esc(name)}</b><span>${num(n)} 条</span></a>`;
}
function filterKes(q){
  const host=document.getElementById('keGrid'); if(!host)return;
  const kw=(q||'').trim();
  [...host.querySelectorAll('.ke-card')].forEach(el=>{
    el.style.display=(!kw||el.dataset.ke.indexOf(kw)>=0)?'':'none';
  });
  const empty=document.getElementById('kesEmpty');
  const shown=[...host.querySelectorAll('.ke-card')].filter(el=>el.style.display!=='none').length;
  if(empty)empty.style.display=shown?'none':'block';
}
function fmtVal(v){
  if(v==null) return '';
  if(typeof v==='string'||typeof v==='number') return String(v);
  if(Array.isArray(v)) return v.map(x=>fmtVal(x)).filter(Boolean).join('；');
  if(typeof v==='object'){
    if(v.value!=null&&typeof v.value!=='object') return String(v.value);
    if(v.text) return v.text;
    if(v.number) return v.number;
    if(v.raw) return v.raw;
    if(v.name) return v.name;
    if(v.keyword) return v.keyword;
    if(v.concept) return v.concept;
    if(v.principle) return v.principle;
    if(v.quote) return v.quote;
    if(v.spans) return v.spans.map(s=>s.from===s.to?'p'+s.from:'p'+s.from+'–'+s.to).join('；');
    return JSON.stringify(v);
  }
  return String(v);
}
function annoEvidence(it){
  const ev=((it&&it.evidence)||[])[0]||{};
  const page=ev.page?'p'+ev.page:'';
  return [page,ev.seg,ev.quote].filter(Boolean).join(' · ');
}
function annoTable(items){
  const list=Object.values(items||{}).filter(x=>x&&x.status&&x.status!=='not_found');
  if(!list.length) return '<div class="empty">暂无数据（缺项不显示）</div>';
  return '<table class="profile-table">'+list.sort((a,b)=>String(a.no||'').localeCompare(String(b.no||''))).map(it=>{
    const st=it.status==='needs_review'?'需核对':(it.status&&it.status!=='found'?it.status:'');
    const ev=annoEvidence(it);
    const sub=[st,ev,it.note].filter(Boolean).join(' · ');
    return `<tr><th>${esc(it.name||'')}</th><td>${esc(fmtVal(it.value))||'<span class="faint">空</span>'}<div class="faint">${esc(sub)}</div></td></tr>`;
  }).join('')+'</table>';
}
function pubHtml(d){
  const items=((d.publication||{}).items)||{};
  return `<section class="panel"><div class="panel-head"><div><h2>出版档案</h2><div class="sub">版权页/书目库抽取；缺项不显示</div></div><span class="faint">19 项</span></div><div class="panel-body">${annoTable(items)}</div></section>`;
}
function pagesHtml(d){
  const pr=d.page_roles||{};
  const roles=(pr.roles||[]).filter(r=>r.status==='found');
  const rows=roles.map(r=>{
    const sp=(r.spans||[]).map(s=>s.from===s.to?'p'+s.from:'p'+s.from+'–'+s.to).join('；');
    const ev=((r.evidence||[])[0]||{}).quote||'';
    return `<tr><th>${esc(r.name||'')}</th><td>${esc(sp)}<div class="faint">${esc(ev)}</div></td></tr>`;
  }).join('');
  const hs=(pr.headings||[]).slice(0,60).map(h=>`<tr><th>${esc(h.level||1)}</th><td>${esc(h.title||'')}<span class="faint"> ${h.page?'p'+h.page:''}</span></td></tr>`).join('');
  return `<section class="panel"><div class="panel-head"><div><h2>页面结构</h2><div class="sub">按版面识别；缺项不显示</div></div></div><div class="panel-body">${rows?'<table class="profile-table">'+rows+'</table>':'<div class="empty">暂无页面结构</div>'}</div></section>
    <section class="panel"><div class="panel-head"><div><h2>标题层级</h2><div class="sub">按篇章标题映射，未使用字号</div></div><span class="faint">${(pr.headings||[]).length} 条</span></div><div class="panel-body">${hs?'<table class="profile-table">'+hs+'</table>':'<div class="empty">暂无标题</div>'}</div></section>`;
}
function deepHtml(d){
  const items=((d.deep||{}).items)||{};
  const list=Object.values(items).filter(x=>x&&(x.status==='found'||x.status==='needs_review'));
  if(!list.length) return '<section class="panel"><div class="panel-head"><div><h2>理解标注</h2><div class="sub">核心概念 / 概念与原理 / 事实与数值 / 技能与规则</div></div></div><div class="panel-body"><div class="empty">暂无理解标注（缺项不显示）</div></div></section>';
  const head='<section class="panel"><div class="panel-head"><div><h2>理解标注</h2><div class="sub">每条都按字段分列；点“原文”回查，不再把事实和数值挤成两行</div></div><span class="faint">4 项</span></div></section>';
  const src=(x)=>{
    const ev=((x||{}).evidence||[])[0]||{};
    return ev.seg?`<button class="btn sm ghost" data-seg="${esc(ev.seg)}" data-q="${esc(ev.quote||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.q,'quote')" title="${esc(ev.quote||'')}">原文</button>`:'<span class="faint">—</span>';
  };
  const table=(heads,rows,cls='',cols='')=>`<div class="deep-scroll"><table class="deep-table ${cls}">${cols}<thead><tr>${heads.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
  return head+list.map(it=>{
    const v=it.value||[];
    let body='';
    if(it.field==='facts'||it.field==='facts_and_numbers'){
      body=table(['#','事实','数值','时间','条件/范围','出处'],v.map((x,i)=>`<tr>
        <td class="num">${i+1}</td>
        <td><b>${esc(x.fact||'')}</b>${x.category?`<span class="pill" style="margin-left:6px">${esc(x.category)}</span>`:''}</td>
        <td>${esc((x.value||'')+(x.unit||''))||'<span class="faint">—</span>'}</td>
        <td>${esc(x.time||'')||'<span class="faint">—</span>'}</td>
        <td>${esc(x.condition||'')||'<span class="faint">—</span>'}</td>
        <td>${src(x)}</td></tr>`).join(''),
        'facts','<colgroup><col style="width:38px"><col><col style="width:106px"><col style="width:78px"><col style="width:118px"><col style="width:54px"></colgroup>');
    }else if(it.field==='concepts'||it.field==='core_concepts'){
      body=table(['概念','定义','为什么是核心','出处'],v.map(x=>`<tr>
        <td><b>${esc(x.concept||'')}</b></td><td>${esc(x.definition||'')||'<span class="faint">—</span>'}</td>
        <td>${esc(x.why_core||'')||'<span class="faint">—</span>'}</td><td>${src(x)}</td></tr>`).join(''),
        'concepts','<colgroup><col style="width:96px"><col><col style="width:170px"><col style="width:54px"></colgroup>');
    }else if(it.field==='principles'||it.field==='concepts_and_principles'){
      body=table(['概念','原理','解释','适用条件','出处'],v.map(x=>`<tr>
        <td><b>${esc(x.concept||'')}</b></td><td>${esc(x.principle||'')}</td>
        <td>${esc(x.explanation||'')||'<span class="faint">—</span>'}</td>
        <td>${esc(x.condition||'')||'<span class="faint">—</span>'}</td><td>${src(x)}</td></tr>`).join(''),
        'principles','<colgroup><col style="width:96px"><col style="width:160px"><col><col style="width:110px"><col style="width:54px"></colgroup>');
    }else if(it.field==='skills'||it.field==='skills_and_rules'){
      body=table(['类型','做法','顺序','条件','出处'],v.map(x=>`<tr>
        <td>${esc(x.type||'')}</td><td>${esc(x.text||'')}</td><td class="num">${esc(x.order||'')||'—'}</td>
        <td>${esc(x.condition||'')||'<span class="faint">—</span>'}</td><td>${src(x)}</td></tr>`).join(''),
        'skills','<colgroup><col style="width:64px"><col><col style="width:44px"><col style="width:110px"><col style="width:54px"></colgroup>');
    }else{
      body=(v||[]).map(x=>`<div class="list-row"><div class="main"><b>${esc(x.fact||x.text||x.concept||x.principle||'')}</b><span>${esc(x.definition||x.explanation||x.value||'')}</span></div></div>`).join('');
    }
    return `<section class="panel"><div class="panel-head"><div><h2>${esc(it.name||'')}</h2><div class="sub">${esc(it.note||'')}</div></div><span class="faint">${v.length} 条</span></div><div class="panel-body">${body||'<div class="empty">暂无</div>'}</div></section>`;
  }).join('');
}
/* ================= 营销资料：页签与应用页共用一套渲染 ================= */
function mktHash(str){let h=5381;const s=String(str||'');for(let i=0;i<s.length;i++)h=((h<<5)+h+s.charCodeAt(i))>>>0;return h.toString(36);}
/* 把模型给的 7 类杂项归一成「一行一条素材」；每条保留自己的依据与证据 */
function mktNormalize(m){
  const items=(m&&m.items)||{};
  const order=['summary','keywords','audience','scenarios','gains','emotions','leads'];
  const keys=order.filter(k=>items[k]).concat(Object.keys(items).filter(k=>order.indexOf(k)<0));
  const out=[];
  keys.forEach(k=>{
    const it=items[k]||{}, val=it.value, name=it.name||k;
    let rows=[];
    if(k==='keywords') rows=arr(val).map(x=>({main:x.keyword||'',sub:x.reason||'',basis:'',ev:arr(x.evidence)[0]||{}}));
    else if(k==='summary') rows=[{main:(val&&val.text)||'',sub:'',basis:'',ev:arr(it.evidence)[0]||{}}];
    else rows=arr(val).map(x=>({main:x.text||'',sub:x.reason||'',basis:x.basis||'',ev:arr(x.evidence)[0]||{}}));
    rows=rows.filter(r=>r.main||r.sub).map(r=>Object.assign(r,{key:k,id:k+':'+mktHash(r.main+'|'+r.sub)}));
    if(rows.length) out.push({key:k,name,rows});
  });
  return out;
}
function mktServerGroups(rows){
  const groups=[];
  rows.forEach(r=>{let g=groups.find(x=>x.key===r.key);if(!g){g={key:r.key,name:r.title,rows:[]};groups.push(g);}
    g.rows.push({id:r.id,assetId:r.asset_id,key:r.key,main:r.text||r.main,sub:r.sub||'',basis:r.basis||'',ev:(r.evidence||[])[0]||{},serverStatus:r.status});});
  return groups;
}

function mktDerived(r){ return r.serverStatus==='approved'?'ok':r.serverStatus==='rejected'?'reject':'review'; }
function mktStateText(st){ return st==='reject'?'已剔除':(st==='review'?'待确认':'可用'); }
function mktFlags(code){ return (state.mktFlags&&state.mktFlags[code])||{}; }
function mktRowState(r,flags){ const f=flags[r.id]; if(f==='reject')return 'reject'; if(f==='adopt')return r.serverStatus==='review'?'review':'ok'; return mktDerived(r); }
function mktItemHtml(r,code,st,catName){
  return `<div class="mkt-item" data-id="${esc(r.id)}" data-key="${esc(r.key)}" data-review="${r.basis==='推断'?'1':'0'}" data-st="${st}">
    ${catName?`<span class="mkt-cat">${esc(catName)}</span>`:''}
    ${r.key==='summary'
      ? `<div class="mkt-main mkt-sum-text generated-copy">${ManuscriptReader.build(r.main||'',undefined,{frozen:true}).html}</div><button class="mkt-more" onclick="mktMore(this)">展开全文</button>`
      : `<div class="mkt-main generated-copy">${ManuscriptReader.build(r.main||'',undefined,{frozen:true}).html}</div>`}
    ${r.sub?`<div class="mkt-sub generated-copy">${ManuscriptReader.build(r.sub,undefined,{frozen:true}).html}</div>`:''}
    <div class="mkt-meta">
      ${r.basis?`<span class="mkt-basis">${esc(r.basis)}</span>`:''}
      ${(r.ev&&r.ev.seg)?`<a class="mkt-ev" href="#/book/${encodeURIComponent(code)}/text/${encodeURIComponent(r.ev.seg)}?${esc(new URLSearchParams({t:r.ev.quote||'',k:'quote',f:'marketing',mid:r.id}).toString())}" title="查看原文"><span class="mkt-q">${esc(clip(r.ev.quote||'',70))}</span><em>${esc(r.ev.seg)} · 查看原文 →</em></a>`:''}
    </div>
    <div class="mkt-act">
      ${window.MarketingReview?.rowAction(code,r.id)||''}
      ${r.assetId&&st!=='reject'?`<button class="btn xs primary" data-id="${esc(r.assetId)}" onclick="MarketingMaterials.open(this)">用于营销策划 →</button>`:''}
      ${st==='review'?`<button class="btn xs" onclick="mktSet('${esc(code)}','${esc(r.id)}')">确认可用</button>`:''}
      <button class="btn xs ghost mkt-btn" onclick="mktToggle('${esc(code)}','${esc(r.id)}')">${st==='reject'?'恢复':'剔除'}</button>
      <span class="mkt-st">${mktStateText(st)}</span>
    </div>
  </div>`;
}
/* 一次渲染算清：待确认的进顶部块，其余按类别；不再靠 DOM 搬来搬去 */
function mktPanelBodyHtml(d,code,flags){
  const groups=d.marketing_rows ? mktServerGroups(d.marketing_rows) : mktNormalize(d.marketing||{});
  state.mktData={code:code,d:d,groups:groups};
  const total=groups.reduce(function(n,g){return n+g.rows.length;},0);
  if(!total) return '<div class="empty">这本书尚未生成营销资料。<p>按需生成，任务进度与结果会保存到任务中心。</p><button class="btn primary" data-code="'+esc(code)+'" onclick="Studio.generate(this)">生成营销资料</button></div>';
  const st=function(r){return mktRowState(r,flags);};
  const counts={ok:0,review:0,reject:0};
  groups.forEach(function(g){g.rows.forEach(function(r){counts[st(r)]++;});});
  const cats=groups.map(function(g){
    return {key:g.key,name:g.name,rows:g.rows,total:g.rows.length,
      review:g.rows.filter(function(r){return st(r)==='review';}).length,
      rejected:g.rows.filter(function(r){return st(r)==='reject';}).length};
  });
  if(state.mktCode!==code){state.mktCode=code;state.mktCat='';}
  let cur=state.mktCat;
  const valid=(cur==='review'&&counts.review)||(cur!=='review'&&cats.some(function(c){return c.key===cur&&c.rows.length;}));
  if(!valid){cur=counts.review?'review':(cats[0]?cats[0].key:'');state.mktCat=cur;}
  const tabs='<div class="mkt-cats">'+
    (counts.review?`<button class="mkt-cat-tab ${cur==='review'?'on':''}" onclick="mktSetCat('review')">待确认 <b>${counts.review}</b></button>`:'')+
    cats.map(function(c){return `<button class="mkt-cat-tab ${cur===c.key?'on':''}" onclick="mktSetCat('${c.key}')">${esc(c.name)} <b>${c.total}</b>${c.review?`<i class="mkt-cat-rv">${c.review}</i>`:''}</button>`;}).join('')+
    '</div>';
  let body='';
  if(cur==='review'){
    const rows=[]; groups.forEach(function(g){g.rows.forEach(function(r){if(st(r)==='review')rows.push({r:r,cat:g.name});});});
    body=`<section class="mkt-review" id="mktReviewBlock">
      <div class="mkt-review-h"><b>待你确认</b><span class="mkt-rv-count">${counts.review}</span>
        <span class="faint">机器生成的候选内容；核对依据与适用范围后确认</span>
        <button class="btn xs" onclick="mktConfirmAll('${esc(code)}')">全部确认</button></div>
      <div class="mkt-review-body">${rows.map(function(x){return mktItemHtml(x.r,code,st(x.r),x.cat);}).join('')}</div>
    </section>`;
  }else{
    const c=cats.filter(function(x){return x.key===cur;})[0];
    if(c){
      const rows=c.rows.filter(function(r){return st(r)!=='review';});
      const rj=rows.filter(function(r){return st(r)==='reject';}).length;
      body=`<section class="mkt-group" data-group="${esc(c.key)}" data-rj="${rj}">
        <div class="mkt-gh"><h3>${esc(c.name)}</h3>
          <span class="faint">${rows.length} 条${c.review?` · ${c.review} 条在待确认`:''}</span>
          <span class="mkt-gact">
            ${(!c.review&&!rj)?'<span class="mkt-gdone">全部可用</span>':''}
            ${rj?`<button class="btn xs ghost" onclick="mktBatch('${esc(code)}','${esc(c.key)}','')">恢复已剔除 ${rj}</button>`:''}
            ${(rows.length-rj)?`<a class="mkt-gnuke" onclick="mktBatch('${esc(code)}','${esc(c.key)}','reject')">整类剔除</a>`:''}
          </span></div>
        <div class="mkt-items">${rows.map(function(r){return mktItemHtml(r,code,st(r));}).join('')}</div>
      </section>`;
    }
  }
  return `${window.MarketingReview?.panel(code)||''}<div class="mkt-bar">
      <div class="mkt-sum"><b>${num(total)}</b> 条资料 · 可用 <b>${counts.ok}</b> · 待确认 <b>${counts.review}</b> · 已剔除 <b>${counts.reject}</b></div>
      <div class="head-actions"><button class="btn sm ghost" onclick="mktExport('md')">导出已确认稿</button><button class="btn sm ghost" onclick="mktExport('review')">导出审阅稿</button><button class="btn sm ghost" onclick="mktExport('csv')">审阅 CSV</button><button class="btn sm" data-code="${esc(code)}" onclick="Studio.generate(this)">重新生成</button></div>
    </div>${tabs}${body}`;
}
function mktSetCat(k){ state.mktCat=k; mktRender(); }
function mktRender(){
  const md=state.mktData; if(!md)return;
  const host=document.getElementById('mktBody'); if(!host)return;
  host.innerHTML=mktPanelBodyHtml(md.d,md.code,mktFlags(md.code));
}
async function mktLoadFlags(code){
  const hash=location.hash,host=document.getElementById('mktBody');
  try{
    const r=await jget('/api/marketing/flags?code='+encodeURIComponent(code));
    if(hash!==location.hash||host!==document.getElementById('mktBody')||state.mktData?.code!==code)return;
    state.mktFlags=state.mktFlags||{};
    state.mktFlags[code]=r.flags||{};
  }catch(e){return;}
  mktRender();
  await window.MarketingReview?.refresh();
}
async function mktPost(code,ids,status){
  if(!ids||!ids.length)return false;
  const hash=location.hash,host=document.getElementById('mktBody');
  const current=()=>hash===location.hash&&host===document.getElementById('mktBody')&&state.mktData?.code===code;
  try{await post('/api/marketing/flag',{code,ids:ids,status:status});}
  catch(e){if(current()){if(window.MarketingReview)MarketingReview.blocked(code,e.details,e.message);else toast('保存失败：'+e.message,true);}return false;}
  if(!current())return false;
  const m=mktFlags(code);
  ids.forEach(function(id){ if(status==='')delete m[id]; else m[id]=status; });
  try{const fresh=await jget('/api/book?code='+encodeURIComponent(code));state.bookCache[code]=fresh;
    if(!current())return false;
    state.mktData.d=fresh;state.mktData.groups=mktServerGroups(fresh.marketing_rows||[]);}catch(e){}
  mktRender();
  await window.MarketingReview?.refresh();
  return true;
}
function mktRowsById(id){
  const md=state.mktData||{}; const out=[];
  (md.groups||[]).forEach(function(g){g.rows.forEach(function(r){if(r.id===id)out.push(r);});});
  return out[0]||null;
}
async function mktSet(code,id){ await mktPost(code,[id],'adopt'); }
async function mktToggle(code,id){
  const r=mktRowsById(id); if(!r)return;
  const cur=mktRowState(r,mktFlags(code));
  await mktPost(code,[id],cur==='reject'?'':'reject');
}
async function mktConfirmAll(code){
  const md=state.mktData||{}; const flags=mktFlags(code); const ids=[];
  (md.groups||[]).forEach(function(g){g.rows.forEach(function(r){if(mktRowState(r,flags)==='review')ids.push(r.id);});});
  if(!ids.length)return;
  if(await mktPost(code,ids,'adopt')) toast('已确认 '+ids.length+' 条');
}
async function mktBatch(code,key,status){
  const md=state.mktData||{}; const flags=mktFlags(code); const ids=[];
  const g=(md.groups||[]).filter(function(x){return x.key===key;})[0]; if(!g)return;
  g.rows.forEach(function(r){
    const st=mktRowState(r,flags);
    if(st==='review')return;
    if(status==='reject'&&st!=='reject')ids.push(r.id);
    if(status===''&&st==='reject')ids.push(r.id);
  });
  if(!ids.length)return;
  if(await mktPost(code,ids,status)) toast(status==='reject'?'已剔除 '+ids.length+' 条':'已恢复 '+ids.length+' 条');
}
function mktMore(btn){
  const box=btn.closest('.mkt-item'); if(!box)return;
  box.classList.toggle('open');
  btn.textContent=box.classList.contains('open')?'收起':'展开全文';
}
function mktDownload(name,text,mime){
  const blob=new Blob(['\ufeff'+text],{type:(mime||'text/plain')+';charset=utf-8'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;
  document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},400);
}
async function mktExport(mode){
  const code=(state.mktData||{}).code;
  try{
    const d=await post('/api/marketing/export',{code,mode:mode==='md'?'approved':'review',format:mode==='csv'?'csv':'md'});
    mktDownload(d.filename,d.text,mode==='csv'?'text/csv':'text/markdown');
    toast('已导出 '+d.count+' 条');
  }catch(err){toast(err.message,true);}
}

/* 书详情里的旧页签入口（现在书页已并入应用页，这里只做兜底） */
function marketingHtml(d){
  const code=(d.row||{}).code||(d.book||{}).code||'';
  const html=mktPanelBodyHtml(d,code,{});
  setTimeout(function(){mktLoadFlags(code);},0);
  return '<section class="panel"><div class="panel-body" id="mktBody">'+html+'</div></section>';
}
async function renderMarketing(v,code){
  v.classList.add('marketing-data-page');
  const isCurrent=capturePageRequest(v);
  await refreshBooks();if(!isCurrent())return;
  const books=state.books.slice();
  const pick=books.some(b=>b.code===code)?code:((books[0]||{}).code||'');
  if(!isCurrent())return;v.innerHTML=`<div class="page-head">
      <div><div class="eyebrow">Applications / Marketing</div><h1>图书营销资料</h1>
        <p>了解这本书的内容与潜在传播角度。找到有价值的资料后，点击“用于营销策划”，加入已有项目或带入新项目。</p></div>
      <div class="head-actions">
        ${pick?`<button class="btn ghost" onclick="go('book','${esc(pick)}')">打开这本书</button><button class="btn ghost" onclick="go('report','${esc(pick)}')">解析报告</button>`:''}
        <select id="mktBook" onchange="go('marketing',this.value)">
          ${books.map(b=>`<option value="${esc(b.code)}" ${b.code===pick?'selected':''}>${esc(b.book)}</option>`).join('')}
        </select>
      </div></div>
    <div id="mktHost">${loading('加载素材')}</div>`;
  if(!pick){document.getElementById('mktHost').innerHTML='<div class="panel"><div class="empty">还没有图书。</div></div>';return;}
  try{
    const d=await jget('/api/book?code='+encodeURIComponent(pick));state.bookCache[pick]=d;
    if(!isCurrent())return;
    state.book=d;
    document.getElementById('mktHost').innerHTML='<section class="panel"><div class="panel-body" id="mktBody">'+mktPanelBodyHtml(d,pick,{})+'</div></section>';
    await mktLoadFlags(pick);
  }catch(e){
    if(!isCurrent())return;
    document.getElementById('mktHost').innerHTML='<div class="panel"><div class="empty">加载失败：'+esc(e.message)+'</div></div>';
  }
}

/* ================= 资产产出：按「交付形态」分四种产物 =================
   旧版是「825 条平铺 + 知识/索引 + 类型 + 精度」三个筛选器。问题：这三把刀切的是同一块
   （物种+人物+引书=知识=可直接用，篇目=索引=仅定位器），互相重复；而真正要交付的东西
   ——21 个字段、每条待补什么、每种产物导出成什么格式——一条都没露出来。
   现在按「这颗资产拿去干什么」分 4 种产物，各给各的列、各给各的导出。 */
const OUT_PRODS=[
 {k:'species',form:'结构化数据',name:'物种条目',types:['物种条目'],tier:'可直接用',fields:21,
  use:'药材词条 / 详情页 / 资料卡',
  note:'每条是一份完整词条：来源、别名、原植物、生境、分布、采制、性味功效、主治用法、用量、附方。全库只有这一份密度够高、能直接对外用；待补是图注对位和学名抽检，不影响文字。'},
 {k:'person',form:'人物卡',name:'人物条目',types:['人物条目'],tier:'可直接用',fields:5,
  use:'人物卡 / 海报 / 短视频文案',
  note:'姓名、身份、籍贯、主要成就、语录五项齐全，做单张人物卡够用；缺生平时间线和照片，要「讲完一生」得人补。'}
];
const OUT_MOVED=['quote','index'];
const OUT_COLS={
  species:['中名','学名','科名','药用部位','药材名','来源','别名','俗名','原植物','生境','分布','采制','性味功效','主治用法','用量','附方','附注','识别要点','炮制','贮藏','化学成分'],
  person:['姓名','身份','籍贯','主要成就','院士语录']
};
function outProdOf(k){return OUT_PRODS.filter(function(x){return x.k===k;})[0];}
function outCount(p){
  const c=(state.out&&state.out.counts)||{};
  return (p.types||[]).reduce(function(a,t){return a+(c[t]||0);},0);
}
function outPendChips(r,max){
  const p=(r['待补']||[]).slice(0,max||2);
  return p.map(function(x){return '<span class="pchip">'+esc(x)+'</span>';}).join('')||'<span class="faint">—</span>';
}
function outFill(r,p){
  const f=r['字段']||{};
  const have=Object.keys(f).filter(function(k){return f[k]!=null&&f[k]!==''&&f[k]!=='—';}).length;
  const tot=p.fields||have||1;
  return '<span class="ofill'+(have<tot?' thin':'')+'">'+have+'<em>/'+tot+'</em></span>';
}
function outScopeName(){
  const O=state.out||{};
  if(!O.book)return '全库';
  const b=(state.books||[]).filter(function(x){return x.code===O.book;})[0];
  return b?b.book:O.book;
}
function outTabsHtml(){
  const O=state.out||{}; const cur=O.prod;
  const tab=function(p){
    const n=outCount(p);
    return '<button class="mkt-cat-tab'+(cur===p.k?' on':'')+(n?'':' zero')+'" data-k="'+p.k+'"'
      +(n?' onclick="outProd(this.dataset.k)"':' disabled')+'>'
      +esc(p.form)+' <b>'+num(n)+'</b></button>';
  };
  const pick=function(ks){return OUT_PRODS.filter(function(p){return ks.indexOf(p.k)>=0;}).map(tab).join('');};
  return pick(['species','person'])
    +'<span class="tchip-sep"></span><button class="mkt-cat-tab'+(cur==='todo'?' on':'')+'" data-k="todo" id="outTodoTab" onclick="outProd(\'todo\')">待补 <b>'+num(O.todoKinds||0)+'</b> 项</button>'
    +'<a class="ed-link" onclick="go(\'editor\')">引证线索 / 篇目索引 已挪到资料整理 →</a>';
}

async function renderOutput(v,arg){
  const isCurrent=capturePageRequest(v);
  await refreshBooks();if(!isCurrent())return;
  const books=state.books||[];
  let book='';
  if(arg&&books.some(function(b){return b.code===arg;}))book=arg;
  let prod='species',q='';
  if(arg==='todo')prod='todo';
  else if(arg&&OUT_PRODS.some(function(p){return p.k===arg;}))prod=arg;
  else if(arg&&!book)q=arg;
  state.out={prod:prod,q:q,book:book,items:[],total:0,counts:{},todo:null,todoTotal:0};
  try{
    const probe=await jget('/api/assets?limit=1&book='+encodeURIComponent(book));
    if(!isCurrent())return;
    state.out.counts=(probe&&probe.by_type)||{};
  }catch(e){}
  // 从某本书点进来：默认落在「这本书条数最多」的产物上，不硬塞一个空的
  let noOut=false;
  if(book){
    let best='species',bn=-1;
    OUT_PRODS.forEach(function(p){const n=outCount(p);if(n>bn){bn=n;best=p.k;}});
    state.out.prod=bn>0?best:'species';
    noOut=bn<=0;
  }
  if(!isCurrent())return;v.innerHTML=`
    <div class="page-head">
      <div><div class="eyebrow">Content Assets / Output</div><h1>资产产出</h1>
        <p>825 条里能直接交出去的只有两种：物种条目和人物条目。引证线索、篇目索引不在这页——它们要人补完才算东西，已经挪到 <b>资料整理</b>；补完才有文献线索清单和篇章表。</p></div>
      <div class="head-actions">
        <select id="outBook"><option value="">全库</option>${books.map(function(b){return '<option value="'+esc(b.code)+'"'+(b.code===book?' selected':'')+'>'+esc(b.book)+'</option>';}).join('')}</select>
      </div>
    </div>
    <section class="panel"><div class="panel-body">
      <div class="mkt-cats" id="outTabs">${outTabsHtml()}</div>
      <div id="outView"></div>
    </div></section>`;
  if(noOut){
    document.getElementById('outTabs').innerHTML='';
    document.getElementById('outView').innerHTML='<div class="empty">这本书没有能直接交出去的资产（没有物种条目，也没有人物条目）。'
      +'它只有引文和篇目——那是编辑要过的活，在资料整理里。<div style="margin-top:10px">'
      +'<button class="btn sm" data-c="'+esc(book)+'" onclick="go(\'editor\',this.dataset.c)">打开资料整理 →</button></div></div>';
    return;
  }
  const sel=document.getElementById('outBook');
  if(sel)sel.onchange=function(){go('output',this.value);};
  // 待补项数量是独立统计，先占位后回填，不阻塞页面
  jget('/api/assets/todo?book='+encodeURIComponent(book)).then(function(d){
    state.out.todo=d; state.out.todoTotal=d.total||0; state.out.todoKinds=(d.items||[]).length;
    const t=document.querySelector('#outTodoTab b'); if(t)t.textContent=num((d.items||[]).length);
    if(state.out.prod==='todo')outRenderView();
  }).catch(function(){});
  await outRenderView();
}

async function outProd(k){
  const O=state.out; if(!O)return;
  O.prod=k; O.q=''; O.items=[]; O.total=0;
  document.querySelectorAll('#outTabs .mkt-cat-tab').forEach(function(b){b.classList.toggle('on',b.dataset.k===k);});
  await outRenderView();
}

async function outRenderView(){
  const host=document.getElementById('outView'); if(!host)return;
  const O=state.out;
  if(O.prod==='todo')return outRenderTodo(host);
  const p=outProdOf(O.prod); if(!p)return;
  host.innerHTML=outHeadHtml(p)+'<div id="outCov"></div><div id="outList">'+loading('加载'+p.form)+'</div>';
  const q=document.getElementById('outQ');
  if(q){
    q.value=O.q||'';
    q.onkeydown=function(e){if(e.key==='Enter'){O.q=this.value.trim();outLoad(false);}};
  }
  outLoad(false);
}

function outHeadHtml(p){
  const O=state.out;
  const n=outCount(p);
  return `<div class="out-head">
    <div class="out-head-main">
      <h3>${esc(p.form)} <span class="badge ${p.tier==='可直接用'?'green':''}">${esc(p.tier)}</span></h3>
      <div class="out-sub">${esc(p.name)} · ${num(n)} 条 · ${esc(outScopeName())} · 拿去用：${esc(p.use)}</div>
      <p>${esc(p.note)}</p>
      <div id="outPend" class="out-pend"></div>
    </div>
    <div class="out-head-act">
      <input id="outQ" class="out-search" placeholder="搜${p.k==='species'?'中名 / 学名 / 主治':(p.k==='quote'?'书名':'标题 / 原文')}">
      <button class="btn sm" id="outExpBtn" onclick="outExport()">导出 CSV</button>
    </div>
  </div>`;
}

async function outLoad(append){
  const O=state.out; const p=outProdOf(O.prod); if(!p)return;
  const off=append?O.items.length:0;
  const qs='?offset='+off+'&limit=50&book='+encodeURIComponent(O.book||'')
    +'&type='+encodeURIComponent(p.types.join(','))+'&q='+encodeURIComponent(O.q||'');
  const host=document.getElementById('outList');
  if(!append&&host)host.innerHTML=loading('加载'+p.form);
  let d;
  try{d=await jget('/api/assets'+qs);}
  catch(e){if(host)host.innerHTML='<div class="empty">加载失败：'+esc(e.message)+'</div>';return;}
  O.total=d.total||0;
  O.items=append?O.items.concat(d.items||[]):(d.items||[]);
  if(!append)outPaintCov(p);
  if(!host)return;
  if(!O.items.length){
    host.innerHTML='<div class="empty">没有符合条件的条目。'+(O.q?'清空搜索词再看。':'')+'</div>';
    return;
  }
  O.commonPend=outCommonPend(O.items);
  const ph=document.getElementById('outPend');
  if(ph){
    ph.innerHTML=O.commonPend
      ?'待补（每条都一样，所以不占表格一列）：'+O.commonPend.map(function(x){return '<span class="pchip">'+esc(x)+'</span>';}).join('')
        +((p.k==='quote')?outQuoteSkipNote():'')
      :'';
  }
  const showPend=!O.commonPend;
  const rows=O.items.map(function(r,i){return outRowHtml(p,r,i,showPend);}).join('');
  host.innerHTML=outTableHtml(p,rows,showPend)+outFootHtml();
  const btn=document.getElementById('outExpBtn');
  if(btn)btn.textContent='导出 '+num(O.total)+' 条';
}

function outCommonPend(items){
  if(!items.length)return null;
  const norm=function(r){return (r['待补']||[]).slice().sort().join('|');};
  const first=norm(items[0]);
  if(!first)return null;
  for(let i=1;i<items.length;i++){if(norm(items[i])!==first)return null;}
  return (items[0]['待补']||[]).slice();
}
function outTableHtml(p,rows,showPend){
  const T=({
    species:['中名','学名 / 科名','药用部位','字段齐备','待补',''],
    person:['姓名','身份 / 籍贯','主要成就','字段齐备','待补','']
  }[p.k]||[]).slice();
  const W=({
    species:['17%','27%','15%','9%','20%'],
    person:['19%','22%','27%','9%','15%']
  }[p.k]||[]).slice();
  if(!showPend){
    const pi=T.indexOf('待补');
    if(pi>=0){T.splice(pi,1);W.splice(pi,1);}
  }
  return '<table class="table out-table2"><colgroup>'
    +W.map(function(w){return '<col style="width:'+w+'">';}).join('')+'<col></colgroup>'
    +'<thead><tr>'+T.map(function(h){return '<th>'+esc(h)+'</th>';}).join('')
    +'</tr></thead><tbody>'+rows+'</tbody></table>';
}

function outRowHtml(p,r,i,showPend){
  const f=r['字段']||{};
  const at=' data-i="'+i+'" onclick="outToggle(this)"';
  const pend=function(max){return showPend?'<td>'+outPendChips(r,max)+'</td>':'';};
  if(p.k==='person'){
    return '<tr class="out-row"'+at+'>'
      +'<td><b>'+esc(f['姓名']||'—')+'</b><span class="faint">'+esc(r.id||'')+'</span></td>'
      +'<td>'+esc(clip(f['身份']||'—',22))+'<span class="faint">'+esc(f['籍贯']||'')+'</span></td>'
      +'<td class="faint">'+esc(clip(f['主要成就']||'—',54))+'</td>'
      +'<td>'+outFill(r,p)+'</td>'
      +pend(2)
      +'<td class="oc-caret">›</td></tr>';
  }
  return '<tr class="out-row"'+at+'>'
    +'<td><b>'+esc(f['中名']||'—')+'</b><span class="faint">'+esc(f['药材名']||'')+'</span></td>'
    +'<td><i class="sci">'+esc(clip(f['学名']||'—',36))+'</i><span class="faint">'+esc(f['科名']||'')+'</span></td>'
    +'<td class="faint">'+esc(clip(f['药用部位']||'—',26))+'</td>'
    +'<td>'+outFill(r,p)+'</td>'
    +pend(2)
    +'<td class="oc-caret">›</td></tr>';
}

function outFootHtml(){
  const O=state.out;
  const more=O.items.length<O.total;
  return '<div class="out-foot"><span>已显示 '+num(O.items.length)+' / '+num(O.total)+' 条'
    +(O.q?'（搜索：'+esc(O.q)+'）':'')+'</span>'
    +(more?'<button class="btn sm ghost" onclick="outLoad(true)">再看 50 条</button>':'<span class="faint">全部显示完了</span>')
    +'</div>';
}

function outToggle(tr){
  const nx=tr.nextElementSibling;
  if(nx&&nx.classList.contains('out-detail')){nx.remove();tr.classList.remove('open');return;}
  const r=state.out.items[+tr.dataset.i]; if(!r)return;
  const d=document.createElement('tr');
  d.className='out-detail';
  d.innerHTML='<td colspan="'+tr.children.length+'">'+outDetailHtml(r)+'</td>';
  tr.parentNode.insertBefore(d,tr.nextSibling);
  tr.classList.add('open');
}

function outDetailHtml(r){
  const f=r['字段']||{};
  const keys=Object.keys(f).filter(function(k){return f[k]!=null&&f[k]!==''&&f[k]!=='—';});
  const kv=keys.map(function(k){
    return '<div class="kv-row"><span>'+esc(k)+'</span><b>'+esc(fmtVal(f[k]))+'</b></div>';
  }).join('');
  const pend=(r['待补']||[]).map(function(x){return '<span class="pchip">'+esc(x)+'</span>';}).join('');
  // 去原文要带上来意：引书标书名，篇目标题不标，其余条目只定位
  const _isCite=r['类型']==='引书候选';
  const _segTerm=_isCite?(f['书名']||''):'';
  const _segMode=_isCite?'cite':(r['类型']==='篇目候选'?'chapter':'term');
  return '<div class="out-detail-in">'
    +'<div class="out-kv">'+(kv||'<div class="faint">这条没有结构字段，只有原文。</div>')+'</div>'
    +'<div class="out-side">'
      +(r['依据']?'<div><span>依据</span><b>'+esc(r['依据'])+'</b></div>':'')
      +(r['精度说明']?'<div><span>边界</span><b>'+esc(r['精度说明'])+'</b></div>':'')
      +'<div><span>锚点</span><b class="mono">'+esc(r.seg_id||r['锚点']||'—')+'</b></div>'
      +(pend?'<div><span>待补</span><b>'+pend+'</b></div>':'')
      +'<div class="out-acts">'
        +(r.seg_id?'<button class="btn sm ghost" data-code="'+esc(r['码']||'')+'" data-seg="'+esc(r.seg_id)+'" data-term="'+esc(_segTerm)+'" data-mode="'+_segMode+'" data-from="output" onclick="openSegTerm(this.dataset.code,this.dataset.seg,this.dataset.term,{mode:this.dataset.mode,from:this.dataset.from})">去原文</button>':'')
        +(r.id?'<button class="btn sm ghost" data-code="'+esc(r['码']||'')+'" data-id="'+esc(r.id)+'" onclick="go(\'card\',this.dataset.code,this.dataset.id)">条目详情</button>':'')
      +'</div>'
    +'</div></div>';
}

async function outPaintCov(p){
  const host=document.getElementById('outCov'); if(!host)return;
  try{
    const d=await jget('/api/assets/fields?type='+encodeURIComponent(p.types.join(','))
      +'&book='+encodeURIComponent(state.out.book||''));
    const fs=d.fields||[], tot=d.total||0;
    if(!fs.length){host.innerHTML='';return;}
    const thin=fs.filter(function(x){return x.count<tot*0.5;}).sort(function(a,b){return a.count-b.count;});
    const bars=fs.map(function(x){
      return '<div class="cov-bar"><span>'+esc(x.name)+'</span><div class="cov-track"><i style="width:'+Math.round(x.count/tot*100)+'%"></i></div><b>'+x.count+'</b></div>';
    }).join('');
    host.innerHTML='<details class="out-cov"><summary>字段覆盖：'+fs.length+' 个字段'
      +(thin.length?'，'+thin.length+' 个不到一半（'+thin.slice(0,4).map(function(x){return esc(x.name)+' '+x.count;}).join(' · ')+'）':'，全部齐')
      +'</summary><div class="cov-bars">'+bars+'</div></details>';
  }catch(e){host.innerHTML='';}
}

function outRenderTodo(host){
  const T=state.out.todo||{items:[],total:0};
  const items=T.items||[];
  const rows=items.map(function(g){
    const books=Object.keys(g.books||{}).sort(function(a,b){return g.books[b]-g.books[a];});
    const prod=OUT_PRODS.filter(function(p){
      return Object.keys(g.types||{}).some(function(t){return p.types.indexOf(t)>=0;});
    })[0];
    const isEdit=/引用它做什么|本篇主旨一句话|因果链|谁是主动方/.test(g.item);
    const bname=books[0]||'';
    const bk=(state.books||[]).filter(function(x){return x.book===bname;})[0]||{};
    return '<tr><td><b>'+esc(g.item)+'</b></td>'
      +'<td><span class="badge '+(g.kind==='抽检'?'':(g.kind==='缺件'?'red':'amber'))+'">'+esc(g.kind)+'</span></td>'
      +'<td class="mono">'+num(g.count)+(g.skipped?'<span class="faint"> +'+num(g.skipped)+' 不用补</span>':'')+'</td>'
      +'<td class="faint">'+books.slice(0,2).map(function(b){return esc(clip(b,12))+' '+num(g.books[b]);}).join(' · ')
        +(books.length>2?' 等 '+books.length+' 本':'')+'</td>'
      +'<td>'+(isEdit
        ?'<button class="btn sm ghost" data-c="'+esc(bk.code||'')+'" onclick="go(\'editor\',this.dataset.c)" title="去资料整理补《'+esc(bname)+'》">资料整理 →</button>'
        :(prod?'<button class="btn sm ghost" data-k="'+prod.k+'" onclick="outProd(this.dataset.k)">'+esc(prod.form)+' →</button>':'—'))+'</td></tr>';
  }).join('');
  host.innerHTML='<div class="out-head"><div class="out-head-main">'
    +'<h3>待补项 <span class="badge amber">'+num(items.length)+' 项 · '+num(T.total||0)+' 条</span></h3>'
    +'<div class="out-sub">「待补」是条目里机器填不了、交付前又必须有的字段</div>'
    +'<p>三类工作量差一个数量级：抽检＝机器已经填了，人抽样复核就能签收；人写＝机器填不了，必须人写；缺件＝平台还没抽出来（图注、照片），不是写不写的问题。混在一起数，会让人以为还差 1000 多条。</p>'
    +'</div><div class="out-head-act"><button class="btn sm ghost" onclick="outExportTodo()">导出待办 CSV</button></div></div>'
    +'<table class="table out-table2"><thead><tr><th>待补项</th><th>性质</th><th>条数</th><th>落在哪本书</th><th>对应产物</th></tr></thead><tbody>'
    +rows+'</tbody></table>';
}

function outExportTodo(){
  const T=state.out.todo||{items:[]};
  if(!(T.items||[]).length){toast('没有待办项',true);return;}
  const cell=function(v){v=v==null?'':String(v);return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
  const lines=[['待补项','性质','条数','涉及图书','示例条目'].join(',')].concat(T.items.map(function(g){
    return [g.item,g.kind,g.count,Object.keys(g.books||{}).join('、'),(g.ids||[]).join(' ')].map(cell).join(',');
  }));
  mktDownload('待补项_'+new Date().toISOString().slice(0,10)+'.csv',lines.join('\r\n'),'text/csv');
  toast('已导出 '+T.items.length+' 项');
}

async function outExport(){
  const O=state.out,p=outProdOf(O.prod);
  if(!p){toast('待补项请用「导出待办 CSV」',true);return;}
  const rows=[];let off=0,total=1;
  toast('正在收集…');
  while(off<total&&off<5000){
    const d=await jget('/api/assets?offset='+off+'&limit=100&book='+encodeURIComponent(O.book||'')
      +'&type='+encodeURIComponent(p.types.join(','))+'&q='+encodeURIComponent(O.q||''));
    total=d.total||0; rows.push.apply(rows,d.items||[]);
    if(!(d.items||[]).length)break;
    off+=100;
  }
  if(!rows.length){toast('没有可导出的条目',true);return;}
  const cell=function(v){v=v==null?'':String(v);return /[",\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
  const cols=OUT_COLS[p.k]||[];
  const head=['图书','条目ID'].concat(cols).concat(['待补','锚点','依据']);
  const lines=[head.map(cell).join(',')].concat(rows.map(function(r){
    const f=r['字段']||{};
    const vals=cols.map(function(c){
      const v=f[c];
      return v==null?'':(typeof v==='object'?fmtVal(v):String(v));
    });
    return [r['书']||'',r.id||''].concat(vals)
      .concat([(r['待补']||[]).join('；'),r.seg_id||r['锚点']||'',r['依据']||'']).map(cell).join(',');
  }));
  mktDownload(p.form+'_'+new Date().toISOString().slice(0,10)+'.csv',lines.join('\r\n'),'text/csv');
  toast('已导出 '+rows.length+' 条 · '+p.form);
}

function setTab(t){
  if(t==='marketing'){const c=(state.book&&state.book.row&&state.book.row.code)||'';if(c){go('marketing',c);return;}}
  state.pin=null; if(t==='text')state.textMode='chapter';
  // 旧页签全部并入「档案与记录」，带一个焦点块
  if(['pub','pages','tags','records','audit'].indexOf(t)>=0){state.archFocus=t;t='archive';}
  if(t==='assets')t='overview';
  state.detailTab=t;
  const LAB={overview:'概览',text:'原文',archive:'档案与记录'};
  document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x.textContent.trim()===LAB[t]));
  drawDetailTab();
}
function openArchive(blk){state.archFocus=blk||'pub';setTab('archive');}

/* 档案与记录用：技术审计表（分类判据 / 稳定性 / 目录清洗 / 结构审计 / 源文件） */
function auditBody(d){
  const b=d.book||{},r=d.row||{},rec=d.record||{},cip=d.cip||{},clc=d.clc||{};
  const pm=b['篇名质量']||{}, p11=b['原型']==='P11';
  return `

          <div class="kv3">
            <div><span>参考书型</span><b>${esc(r.prototype_name||PROTO[r.prototype]||'待分类')}</b><em>${b['人工改判']?'人工指定':'系统建议'}</em></div>
            <div><span>中图分类</span><b>${clc['代码']?esc(clc['代码'])+' '+esc(clc['名称']):'未识别'}</b><em>${clc['来源']==='人工'?'人工指定':(clc['来源']==='版权页'?'版权页读取':'系统建议')}${(clc['依据']||[]).length?' · 有依据':''}</em></div>
            <div><span>章节与正文</span><b>${b['结构审计']?b['结构审计']['异常']?'需要核对':'初步检查通过':'暂无检查记录'}</b></div>
          </div>
          <table class="profile-table">
            <tr><th>图书分类</th><td>${esc(r.prototype||'—')} ${esc(r.prototype_name||'')} <span class="faint">· 置信 ${esc(r.confidence||'—')}</span>
              <a class="clc-edit" data-code="${esc(r.code||'')}" data-title="${esc(r.book||'')}" data-proto="${esc(r.prototype||'')}" onclick="openRetype(this.dataset.code,this.dataset.title,this.dataset.proto)">改类型</a>${r.status==='pending'?`<a class="clc-edit" data-code="${esc(r.code||'')}" onclick="confirmBook(this.dataset.code)">标为已确认</a>`:''}
              <div class="faint">调整书型会重新整理部分内容。标签请查看本书的逐项检查记录。</div></td></tr>
            <tr><th>中图分类</th><td>${clc['代码']?`${esc(clc['代码'])} ${esc(clc['名称'])}${clc['细分号']?' · '+esc(clc['细分号']):''} <span class="faint">· ${clc['来源']==='人工'?'人工指定':(clc['来源']==='版权页'?'版权页':'系统建议')}</span><div class="faint">${esc((clc['依据']||[]).join('；'))}</div>`:'<span class="faint">未识别（不影响内容，只影响展示与归架）</span>'} <a class="clc-edit" onclick="openClc('${esc(r.code||'')}','${esc(clc['代码']||'')}')">改判</a></td></tr>
            ${cip['_found']?`<tr><th>版权页</th><td>${[cip['出版社']&&esc(cip['出版社']),cip['出版地']&&esc(cip['出版地']),cip['出版年月']&&esc(cip['出版年月']),cip['版次']&&esc(cip['版次']),cip['印次']&&esc(cip['印次'])].filter(Boolean).join(' · ')||'—'}</td></tr>
            <tr><th>ISBN</th><td><span class="mono">${esc(cip['ISBN']||'—')}</span>${cip['ISBN校验']===true?' <span class="badge green">校验通过</span>':(cip['ISBN校验']===false?' <span class="badge red">校验位不对</span>':'')}${cip['CIP核字号']?` <span class="faint">CIP 核字 ${esc(cip['CIP核字号'])}</span>`:''}</td></tr>
            <tr><th>规格</th><td>${[cip['开本']&&('开本 '+esc(cip['开本'])),cip['印张']&&(esc(cip['印张'])+' 印张'),cip['字数']&&(num(cip['字数'])+' 字（版权页）'),cip['定价']&&('定价 '+esc(cip['定价'])+' 元')].filter(Boolean).join(' · ')||'—'}</td></tr>
            <tr><th>著者</th><td>${esc(cip['著者']||'—')}</td></tr>`:`<tr><th>版权页</th><td><span class="badge">未读到</span> <span class="faint">${esc(cip['_reason']||'没有版权页数据')}；元数据需人工补或等模型</span></td></tr>`}
            <tr><th>分类依据</th><td>${esc(arr(b['依据']).join('；')||'—')}</td></tr>
            ${(()=>{const st=b['稳定性'],fit=b['吻合'],mix=arr(b['混合']);
              if(st==null&&fit==null&&!mix.length)return '';
              const mixs=mix.map(x=>Array.isArray(x)?`${esc(x[0])} ${esc(x[1])}%`:esc(x)).join('、');
              return `<tr><th>分类稳定性</th><td>${st!=null?`稳定性 ${Math.round(st*100)}%（阈值扰动 ±20% 后判型不变的比例）`:''}
                ${fit!=null?` · 分块吻合 ${fit}%（10 个分块里 ${Math.round(fit/10)} 块判成同一类）`:''}
                ${mixs?` · 混入 ${mixs}`:''}
                <div class="faint">低于 95% 记「低」置信，需要人确认；「吻合」低说明这本书内部本就不统一。</div></td></tr>`;})()}
            <tr><th>内容结构</th><td>${esc(MODE_CN[b['结构模式']]||b['结构模式']||'—')} · ${num(b['篇数'])} 篇 / ${num(b['段数'])} 段 / ${num(b['汉字_切段'])} 字 · 原文完整度 ${pct(b['保留率'])}${b['条目数']?' · 另切出 '+num(b['条目数'])+' 条物种条目':''}</td></tr>
            <tr><th>篇名识别</th><td>${esc(pm['性质']||'—')}${pm['可用率']!=null?' · 可用率 '+pct(pm['可用率']):''}<div class="faint">${esc(pm['说明']||'')}</div></td></tr>
            <tr><th>人物关系图谱</th><td>${kgCapabilityRow(b,p11)}</td></tr>
            <tr><th>源文件</th><td>${esc(rec.source_format||'—')}${rec.source_note?' · '+esc(rec.source_note):''}${rec.source_completeness?' · '+esc(rec.source_completeness):''}</td></tr>
            ${b['目录清洗']?`<tr><th>目录清洗</th><td>已移除 ${num(b['目录清洗']['删除行数'])} 行 / ${num(b['目录清洗']['删除汉字'])} 字目录内容；章节按清理后文本重切。</td></tr>`:''}
            ${b['结构审计']?`<tr><th>结构审计</th><td>${b['结构审计']['异常']?'<span class="badge red">异常</span>':'<span class="badge green">正常</span>'} ${esc(b['结构审计']['说明']||'章号顺序与目录残留检查通过')}</td></tr>`:''}
            <tr><th>图书编号</th><td>${esc(r.code||'')} <span class="faint">（原文定位前缀；重跑不变）</span></td></tr>
          </table>

  `;
}
function pubFound(d){
  const it=((d.publication||{}).items)||{};
  const all=Object.keys(it).length;
  const found=Object.values(it).filter(x=>x&&x.status&&x.status!=='not_found').length;
  return {found:found,all:all};
}
function pagesBody(d){
  const pr=d.page_roles||{};
  const roles=(pr.roles||[]).filter(r=>r.status==='found');
  const rows=roles.map(r=>{
    const sp=(r.spans||[]).map(s=>s.from===s.to?'p'+s.from:'p'+s.from+'–'+s.to).join('；');
    const ev=((r.evidence||[])[0]||{}).quote||'';
    return `<tr><th>${esc(r.name||'')}</th><td>${esc(sp)}<div class="faint">${esc(ev)}</div></td></tr>`;
  }).join('');
  const hs=(pr.headings||[]).slice(0,60).map(h=>`<tr><th>${esc(h.level||1)}</th><td>${esc(h.title||'')}<span class="faint"> ${h.page?'p'+h.page:''}</span></td></tr>`).join('');
  return `<div class="arch-sub">版面角色 ${roles.length} 项</div>${rows?'<table class="profile-table">'+rows+'</table>':'<div class="empty">暂无页面结构</div>'}
    <div class="arch-sub">标题层级 ${(pr.headings||[]).length} 条</div>${hs?'<table class="profile-table">'+hs+'</table>':'<div class="empty">暂无标题</div>'}`;
}
function opsBody(d){
  const ops=arr(d.operations);
  const EVCN={upload:'上传入库',delete:'删除',restore:'恢复',clc:'分类变更',confirm:'人工确认',settings:'能力配置',entity_review:'专名确认'};
  const evNote=(o)=>{const x=o.detail||{};
    if(o.event==='upload')return [x.format,x.prototype?'判型 '+x.prototype:'',x.confidence?'置信 '+x.confidence:'',(x.cards!=null?x.cards+' 条':'')].filter(Boolean).join(' · ');
    if(o.event==='delete')return '回收站 '+(x.trash_id||'');
    if(o.event==='restore')return '从回收站 '+(x.trash_id||'')+' 恢复';
    if(o.event==='clc')return '改为 '+[(x['代码']||''),(x['名称']||'')].filter(Boolean).join(' ');
    if(o.event==='confirm')return x.job==='manual'?'手动确认':'任务 '+(x.job||'');
    if(o.event==='entity_review')return (x.name||'')+(x.drop?' → 忽略':' → '+({'country':'国家','province':'省份','region':'区域/大区','city':'城市','district':'区县','landmark':'道路/地标','nature':'自然地理','fossil':'化石/古人类','org':'机构','object':'器物','animal':'动物','plant':'植物','taxon':'科属','alias':'别名','person':'人物','concept':'概念/术语','award':'奖项','event':'事件','dynasty':'朝代','family':'家族'}[x.cat]||x.cat||''));
    return x.title||'';
  };
  return ops.length?`<div class="opsline">${ops.slice().reverse().map(o=>`<div><b>${esc((o.time||'').replace('T',' ').slice(0,19))}</b> · ${esc(EVCN[o.event]||o.event)}<span class="faint">${evNote(o)?' · '+esc(evNote(o)):''}</span></div>`).join('')}</div>`:'<div class="empty">暂无操作记录</div>';
}
const TAG_COVERAGE_STATUS={available:'已找到',review:'待核对',not_found:'本次未找到',not_applicable:'不适用',not_run:'待整理',unsupported:'暂不支持',blocked:'需要处理'};
function tagCoverageHtml(d){
  const coverage=d.tag_coverage,code=d.row?.code,job=d.record?.last_job;
  const groups=arr(coverage?.groups).filter(group=>arr(group.items).length);
  if(!groups.length)return '<p class="muted">这本书暂时没有逐项检查记录。重新整理后可查看每项的情况。</p>';
  const summary=Object.entries(TAG_COVERAGE_STATUS).filter(([key])=>Number(coverage.counts?.[key])>0)
    .map(([key,label])=>`<span class="pill">${label} ${num(coverage.counts[key])} 项</span>`).join('');
  return `<section class="tag-coverage"><h3>逐项检查</h3><p class="muted">已找到的内容可对照出处核对。标为「待整理」的项目还没有检查结果。</p>
    ${summary?`<div class="tag-coverage-counts">${summary}</div>`:''}
    ${code?`<div class="tag-coverage-actions">
      <button type="button" class="btn sm ghost" data-code="${esc(code)}" onclick="Studio.filterKind(this)">查看成果与出处</button>
      ${d.book?.['结构审计']?.['异常']?'<button type="button" class="btn sm ghost" onclick="setTab(\'text\')">核对章节原文</button>':''}
      ${job&&coverage.counts?.blocked?`<button type="button" class="btn sm ghost" data-job="${esc(job)}" onclick="go('job',this.dataset.job)">查看待处理任务</button>`:''}</div>`:''}
    ${groups.map(group=>`<details class="tag-coverage-group"><summary>${esc(group.name||'检查项目')} · ${num(group.items.length)} 项</summary><ul>${group.items.map(item=>{
      const note=item.note==='本次未找到可确认的依据'&&item.status==='not_found'?'':item.note;
      const count=Number(item.count)>0?' · '+num(item.count)+' 条':'';
      const action=code&&item.label==='章节摘要'&&['available','review','not_run','blocked'].includes(item.status)?`<button type="button" class="btn sm ghost" data-code="${esc(code)}" data-kind="summary" onclick="Studio.filterKind(this)">查看与整理摘要</button>`:'';
      const source=item.anchor?`<button type="button" class="btn sm ghost" data-anchor="${esc(item.anchor)}" onclick="locateAnchor(this.dataset.anchor)">查看相关原文</button>`:'';
      return `<li><div><b>${esc(item.label)}</b>${note?`<p>${esc(note)}</p>`:''}${action}${source}</div><span class="tag-coverage-state ${esc(item.status)}">${esc(TAG_COVERAGE_STATUS[item.status]||'待核对')}${count}</span></li>`;
    }).join('')}</ul></details>`).join('')}</section>`;
}

function archiveHtml(d,focus){
  const b=d.book||{}, tc=d.tag_counts||{};
  const pf=pubFound(d), pages=(d.page_roles&&(d.page_roles.roles||[]).filter(r=>r.status==='found').length)||0;
  const ops=arr(d.operations);
  const blocks=[
    ['pub','出版档案',pf.found+' / '+pf.all+' 项', annoTable(((d.publication||{}).items)||{})],
    ['pages','页面结构',pages+' 项', pagesBody(d)],
    ['tags','标签与检查情况',num(tc.total||0)+' 条标签', tagCoverageHtml(d)+`<details class="tag-coverage-group"><summary>查看已整理的标签</summary><div class="book-tag-lines">${renderLayers(d.tags||{})}</div></details>`],
    ['audit','识别情况',b['稳定性']!=null?'稳定性 '+Math.round(b['稳定性']*100)+'%':'识别依据', auditBody(d)],
    ['records','操作记录',ops.length+' 条', opsBody(d)],
  ];
  const openKey=focus||'';   // 默认全部收起，只露 5 行摘要
  return '<div class="arch-tip">展开任一项目，可查看图书信息、标签和操作记录。</div>'+
    blocks.map(function(x){
      const k=x[0],title=x[1],meta=x[2],body=x[3];
      return `<details class="arch-blk" id="arch-${k}" ${k===openKey?'open':''}>
        <summary><b>${title}</b><span class="arch-meta">${esc(meta)}</span></summary>
        <div class="arch-body">${body}</div>
      </details>`;
    }).join('');
}

function drawDetailTab(keepChapter){
  const host=document.getElementById('detailBody'); if(!host)return;
  const d=state.book,b=d.book||{},r=d.row||{},rec=d.record||{},cc=d.cards||{},tc=d.tag_counts||{},pm=b['篇名质量']||{},cip=d.cip||{},und=d.understanding||{};
  const keAll=keNames(d);
  if(state.detailTab==='overview'){
    const p11=b['原型']==='P11';
    const clc=d.clc||{};
    const kn=cc['知识']||0, idx=cc['索引']||0;
    const coverage=d.tag_coverage;
    const available=Number(coverage?.counts?.available)||0;
    const matched=arr(coverage?.groups).flatMap(group=>arr(group.items)).filter(item=>item.status==='review'&&Number(item.count)>0).length;
    const pf=pubFound(d);
    const mktN=mktNormalize(d.marketing||{}).reduce((n,g)=>n+g.rows.length,0);
    const entN=Object.values(d.entity_counts||{}).reduce((a,x)=>a+(Number(x)||0),0);
    const quotesN=arr(und.quotes).length;
    const quoteState=und.processing?.quotes?.status;
    const nameState=d.name_processing?.status;
    const needsMore=state=>['partial','failed','blocked','stale'].includes(state);
    host.innerHTML=`
      <div class="asset-tri">
        <div class="tri ${kn?'':'zero'}"><span>知识类成果</span><b>${num(kn)}</b><em>${kindBreakdown(d._byType,'知识')||'此类条目尚未生成，请到内容成果查看其他成果'}</em></div>
        <div class="tri idx"><span>索引类</span><b>${num(idx)}</b><em>${kindBreakdown(d._byType,'索引')||'—'}</em></div>
        <div class="tri"><span>标签检查</span><b>${available||matched?num(available+matched)+' 项':'查看状态'}</b><em>${available||matched?[available&&num(available)+' 项已找到',matched&&num(matched)+' 项待核对'].filter(Boolean).join(' · '):'查看已查过和待整理的项目'}</em></div>
      </div>
      ${(kn===0&&cc.total)?`<div class="banner"><b>已找到 ${num(idx)} 条原文索引。</b> 可以用来找对应的段落，本次还没有整理出知识类成果。</div>`:''}
      <div class="ov-actions">
        <button class="btn sm ghost" onclick="openArchive('tags')">查看标签检查</button>
        <button class="btn sm ghost" data-code="${esc(r.code||'')}" onclick="go('report',this.dataset.code)">查看解析情况</button>
        <button class="btn sm ghost" data-code="${esc(r.code||'')}" onclick="go('output',this.dataset.code)">查看已整理内容</button>
      </div>
      <section class="panel dossier-sec">
        <div class="panel-head"><div><h2>从这里找资料</h2><div class="sub">已整理 ${num(b['篇数'])} ${b['结构单位']==='人'?'人':'篇'}、${num(b['段数'])} 段</div></div>
        ${clc['代码']?`<span class="clc-wrap">${clcChip(clc)}</span>`:''}</div>
        <div class="panel-body">${howToUseHtml(d,p11,keAll,und)}</div>
      </section>
      <section class="panel dossier-sec">
        <div class="panel-head"><h2>已整理的内容</h2></div>
        <div class="panel-body"><div class="prod-grid">
          ${quotesN?`<a onclick="openQuotes()"><b>${num(quotesN)}</b><span>可引用句</span><em>${needsMore(quoteState)?'已保留的摘录 · 待补查':'逐句回查原文'}</em></a>`:`<div class="prod-empty"><b>${needsMore(quoteState)?'待补查':quoteState==='done'?'未找到':'待整理'}</b><span>可引用句</span></div>`}
          <a data-code="${esc(r.code||'')}" onclick="go('ents',this.dataset.code)"><b>${entN?num(entN):needsMore(nameState)?'待补查':nameState==='done'?'未找到':'待整理'}</b><span>人名、地名等</span><em>${needsMore(nameState)?'部分内容待核对':entN?'查看名称和出处':''}</em></a>
          <a onclick="openArchive('tags')"><b>${tc.total?num(tc.total):'待整理'}</b><span>标签</span><em>查看逐项检查</em></a>
          <a data-code="${esc(r.code||'')}" onclick="go('marketing',this.dataset.code)"><b>${mktN?num(mktN):'按需整理'}</b><span>营销资料</span><em>${mktN?'查看已整理的资料':'打开后可生成'}</em></a>
          <a onclick="openArchive('pub')"><b>${pf.found}/${pf.all}</b><span>出版档案</span><em>缺 ${num(pf.all-pf.found)} 项</em></a>
        </div></div>
      </section>`;
  }else if(state.detailTab==='archive'){
    host.innerHTML=archiveHtml(d,state.archFocus||'');
  }else if(state.detailTab==='assets'){
    const tiers=[['','全部'],['可直接用','可直接用'],['需人筛','需人工筛选'],['仅定位器','索引定位']];
    const types=Object.keys(state.cand.byType||{}).sort((a,b)=>(state.cand.byType[b]||0)-(state.cand.byType[a]||0));
    const dirty=state.cand.ke||state.cand.q||state.cand.type||state.cand.tier;
    host.innerHTML=deepHtml(d)+`<section class="panel"><div class="panel-head"><div><h2>内容成果</h2><div class="sub">按三级质量分开看，不合并成一个数</div></div><span class="faint" id="candTotal">${num(cc.total)} 条</span></div><div class="panel-body">
      <div class="cand-tabs">${tiers.map(([k,l])=>`<button class="${state.cand.tier===k?'on':''}" onclick="setTier('${k}')">${l}</button>`).join('')}</div>
      <div class="cand-toolbar" id="candBar" data-types="${types.length>1?'1':'0'}">${candBarHtml()}</div>
      <div id="candList">${loading('加载知识条目')}</div>
      <div id="candPager" class="cand-pager"></div>
    </div></section>`;
    loadCards();
  }else if(state.detailTab==='text'){
    const pin=state.pin, ol=arr(d.outline), quotes=arr(und.quotes);
    // 「可以引用的句子」的全部落点：原文页签里的第二种视图，不是另开一页
    if(!pin&&state.textMode==='quotes'){
      host.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>可引用句</h2><div class="sub">模型只选不改，每句都经逐字回查；点一句跳到原文那一段</div></div>
        <div class="head-actions"><button class="btn sm ghost" onclick="openChapterMode()">← 按篇阅读</button></div></div><div class="panel-body">
        ${quotes.length?quotes.map(q=>`<div class="quote-item" data-seg="${esc(q.seg||'')}" data-q="${esc(q.quote||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.q,'quote')"><div class="qtext">${esc(q.quote||'')}</div><div class="faint">${esc(q.seg||'')}${q.reason?' · '+esc(q.reason):''}</div></div>`).join(''):'<div class="empty">这本书没有抽到可引用句</div>'}
        </div></section>`;
      return;
    }
    const keep=keepChapter&&ol.some(o=>o['篇']===keepChapter)?keepChapter:'';
    const chap=pin?(pin['篇']||''):(keep||(ol[0]?ol[0]['篇']:''));
    // 从引文核对进来：只铺「这个词出现的那几段」，不铺全章目录、也不铺无关原文；
    // 要看整篇再点「看这一篇全文」。
    const focus=!!pin&&state.pinMode==='cite'&&state.pinFocus!==false;
    host.innerHTML=`<section class="panel"><div class="panel-head"><div><h2>原文</h2><div class="sub">${focus?'只显示与这条引文有关的段落':'按篇加载，保留原文定位'}</div></div><div class="head-actions">${quotes.length?`<button class="btn sm ghost" onclick="openQuotes()">可引用句 ${quotes.length}</button>`:''}${pin&&!focus?`<button class="btn sm ghost" onclick="clearPin()">取消定位</button>`:''}</div></div><div class="panel-body">
      ${pin?pinNoteHtml(pin):''}
      ${focus?`<div class="pin-focus-bar"><span id="pinFocusStat">只显示「${esc(state.pinTerm||'')}」出现的原文段落</span>
        <button class="btn sm ghost" onclick="pinShowChapter()">看「${esc(clip(pin['篇']||'',16))}」全文 ${esc(pin.chapter_total||'')} 段 →</button></div>`
        :`<div class="outline" id="outlineBox">${ol.map(o=>`<button class="${o['篇']===chap?'on':''}" data-pian="${esc(o['篇'])}" onclick="loadText(this,this.dataset.pian)">${esc(o['篇'])}</button>`).join('')||'<span class="faint">无篇名，按段读取</span>'}</div>`}
      <div id="segBox">${loading('加载原文')}</div><div id="segMore" class="modal-actions"></div>
    </div></section>`;
    state.seg={chapter:chap,offset:pin?(pin.chapter_offset||0):0,total:0,hit:pin?(pin.seg_id||''):''};
    if(focus) loadPinFocus(); else loadSegments(state.seg.chapter,true);
  }else{
    host.innerHTML=archiveHtml(d,state.archFocus||'');
  }
}

/* ---------------- 知识条目 ---------------- */
function cardName(c){
  const f=(c&&c['字段'])||{};
  const keys=['中名','姓名','人物','篇名','书名','标题','名称','术语','词条'];
  for(let i=0;i<keys.length;i++){const v=f[keys[i]];if(v&&String(v).trim())return String(v).trim();}
  const raw=String((c&&c['原文'])||'').replace(/\s+/g,' ').trim();
  return raw?clip(raw,18):(c&&c['类型']||'条目');
}
function candBarHtml(){
  const keAll=keNames(state.book||{});
  const types=Object.keys(state.cand.byType||{}).sort((a,b)=>(state.cand.byType[b]||0)-(state.cand.byType[a]||0));
  const dirty=state.cand.ke||state.cand.q||state.cand.type||state.cand.tier;
  return `<div class="search"><input id="candQ" placeholder="搜条目名 / 原文片段，回车查询" value="${esc(state.cand.q||'')}"
      onkeydown="if(event.key==='Enter'){event.preventDefault();applyCandQ();}"><kbd>↵</kbd></div>
    ${keAll.length?`<button class="btn sm" onclick="showKePicker()" title="打开全部科名">科名：${esc(state.cand.ke||'全部')}${state.cand.ke?'':'（'+keAll.length+'）'} ${state.cand.ke?'':'›'}</button>`:''}
    ${types.length>1?`<select id="typeSel" onchange="setCandType(this.value)" title="按条目类型筛选">
      <option value="">全部类型</option>
      ${types.map(t=>`<option value="${esc(t)}" ${state.cand.type===t?'selected':''}>${esc(t)}（${num(state.cand.byType[t])}）</option>`).join('')}
    </select>`:''}
    <button class="btn sm" onclick="applyCandQ()">查询</button>
    ${dirty?`<button class="btn sm ghost" onclick="clearCandFilters()">清除筛选</button>`:''}`;
}
// 第一次拿到 by_type 之前不知道有哪些类型，拿到后补渲染一次（只在选项数变化时重建，避免打字时失焦）
function refreshCandBar(){
  const bar=document.getElementById('candBar'); if(!bar)return;
  const want=Object.keys(state.cand.byType||{}).length>1?'1':'0';
  if(bar.dataset.types===want)return;
  bar.dataset.types=want; bar.innerHTML=candBarHtml();
}

async function loadCards(page){
  const d=state.book; if(!d)return; const code=d.row.code;
  const host=document.getElementById('candList'); if(!host)return;
  if(page!==undefined)state.cand.page=page;
  if(typeof state.cand.page!=='number'||state.cand.page<0)state.cand.page=0;
  const PAGE=30, offset=state.cand.page*PAGE;
  try{
    const q=new URLSearchParams({code,tier:state.cand.tier,type:state.cand.type||'',q:state.cand.q||'',
      ke:state.cand.ke||'',offset:String(offset),limit:String(PAGE)});
    const res=await jget('/api/book/cards?'+q.toString());
    state.cand.total=res.total; state.cand.byType=res.by_type||{}; state.cand.offset=offset;
    if(res.total&&offset>=res.total){state.cand.page=Math.max(0,Math.ceil(res.total/PAGE)-1);return loadCards();}
    const items=res.items||[];
    state.cand.items=items;
    const tot=document.getElementById('candTotal');
    if(tot){
      // 筛选后显示「毛茛科 · 89 条（共 574 条）」，否则 89 看着像全书只有 89 条
      const all=(state.book&&state.book.cards&&state.book.cards.total)||res.total;
      const cond=[state.cand.ke,state.cand.q,state.cand.type,state.cand.tier].filter(Boolean);
      tot.innerHTML=(state.cand.ke?esc(state.cand.ke)+' · ':'')+num(res.total)+' 条'+
        (cond.length?' <span class="faint">（共 '+num(all)+' 条）</span>':'');
    }
    const hasKe=items.some(c=>(c['字段']||{})['科名']);
    host.innerHTML=items.length?`<table class="table cand-table"><thead><tr>
        <th>条目</th><th style="width:92px">类型</th><th style="width:96px">质量档</th>
        ${hasKe?'<th style="width:120px">科名</th>':''}<th style="width:120px">锚点</th><th style="width:26px"></th></tr></thead>
      <tbody>${items.map(c=>{const f=c['字段']||{};
        return `<tr onclick="openCard('${esc(c.id)}')">
          <td><div class="card-main"><b>${esc(cardName(c))}</b><span>${esc(clip(c['_excerpt']||c['原文']||'',90))}</span></div></td>
          <td><span class="pill">${esc(c['类型']||'条目')}</span></td>
          <td><span class="pill">${esc(c['资产性质']||'—')}</span></td>
          ${hasKe?`<td class="faint">${esc(f['科名']||'—')}</td>`:''}
          <td><span class="mono">${esc(c['锚点']||'')}</span></td>
          <td class="chev">›</td></tr>`;}).join('')}</tbody></table>`
      :`<div class="empty">没有符合条件的知识条目</div>`;
    // 这两项是「这本书的抽取方式」，574 条里一模一样；摊到每条卡片上只是噪音，这里只出现一次
    if(items.length){
      const q0=items[0]['精度说明']||'', t0=items[0]['待补']||[];
      const sameQ=items.every(c=>(c['精度说明']||'')===q0);
      const sameT=items.every(c=>JSON.stringify(c['待补']||[])===JSON.stringify(t0));
      let note='';
      if(q0&&sameQ)note+=`<div><b>切法与质检</b><span>${esc(q0)}</span></div>`;
      if(t0.length&&sameT)note+=`<div><b>还缺</b>${t0.map(t=>`<span class="chip-mini">${esc(t)}</span>`).join('')}</div>`;
      if(note)host.insertAdjacentHTML('beforeend',`<div class="cand-note">${note}</div>`);
    }
    renderCandPager(res.total,PAGE,state.cand.page);
    refreshCandBar();
  }catch(e){host.innerHTML=`<div class="empty">加载失败：${esc(e.message)}</div>`;}
}
function renderCandPager(total,PAGE,page){
  const el=document.getElementById('candPager'); if(!el)return;
  const pages=Math.max(1,Math.ceil(total/PAGE));
  el.innerHTML=`<span>第 ${page+1} / ${pages} 页 · 每页 ${PAGE} 条 · 共 ${num(total)} 条</span>
    <span class="sp"></span>
    <button class="btn sm ghost" ${page<=0?'disabled':''} onclick="loadCards(${page-1})">上一页</button>
    <button class="btn sm ghost" ${page>=pages-1?'disabled':''} onclick="loadCards(${page+1})">下一页</button>`;
}
function applyCandQ(){
  const el=document.getElementById('candQ');
  state.cand.q=el?el.value.trim():'';
  if(state.cand.q){
    state.cand.ke='';
    // 工具栏不重建（保焦点），但下拉必须跟着清，否则显示的和实际筛的对不上
    const k=document.getElementById('keSel'); if(k)k.value='';
  }
  state.cand.page=0; loadCards();
}
function setCandType(v){state.cand.type=v||'';state.cand.page=0;loadCards();}
function clearCandFilters(){
  state.cand.q='';state.cand.ke='';state.cand.type='';state.cand.tier='';state.cand.page=0;
  drawDetailTab();
}
// 「来源」只是 科名+中名+学名+药用部位 的拼接（例：松科松杉Abies…的枝、叶），
// 上面几行已经逐项列了，再放一行只会让人以为「松科松杉」是一个名字
function hideRedundantFields(f){
  const out={};
  Object.keys(f||{}).forEach(k=>{if(k!=='来源')out[k]=f[k];});
  return out;
}
function fieldRows(f){
  return Object.keys(f||{}).map(k=>{
    let v=f[k];
    if(v===null||v===undefined) return '';
    if(typeof v!=='string') v=JSON.stringify(v);
    if(!String(v).trim()) return '';
    return `<div class="fx"><b>${esc(k)}</b><span>${esc(v)}</span></div>`;
  }).join('');
}
async function copyFields(id){
  // 深链直接打开条目页时 state.cand 还没初始化，直接 .items 会抛错（点了复制没反应）
  let c=((state.cand&&state.cand.items)||[]).find(x=>x.id===id)||(state.cardItem&&state.cardItem.id===id?state.cardItem:null);
  // 兜底：列表没加载过就从接口取，别静默什么都不做
  if(!c||!c['字段']){
    const code=state.book&&state.book.row&&state.book.row.code;
    if(code){try{const d=await jget('/api/book/card?'+new URLSearchParams({code,id}).toString());c=d.item;}catch(e){}}
  }
  if(!c||!c['字段']){toast('没取到这一条的字段，复制失败',true);return;}
  const payload=hideRedundantFields(c['字段']);   // 和页面上看到的一致
  const txt=JSON.stringify(payload,null,2);
  const done=()=>toast('已复制 '+Object.keys(payload).length+' 项');
  if(navigator.clipboard&&navigator.clipboard.writeText){
    // 有的浏览器剪贴板权限会被挂起（既不 resolve 也不 reject）→ 超时就兜底，别点了没反应
    let settled=false;
    const ok=()=>{if(settled)return;settled=true;done();};
    const fb=()=>{if(settled)return;settled=true;fallbackCopy(txt,done);};
    navigator.clipboard.writeText(txt).then(ok,fb);
    setTimeout(fb,900);
  }else fallbackCopy(txt,done);
}
function fallbackCopy(txt,done){
  const ta=document.createElement('textarea');
  ta.value=txt; ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.select();
  try{document.execCommand('copy');done();}catch(e){toast('复制失败，请手动选择',true);}
  document.body.removeChild(ta);
}

// 索引类（篇目/引书）不打开无用的详情页，直接回原文
function openAssetRow(el){
  const type=el.dataset.type||'', code=el.dataset.code||'', seg=el.dataset.seg||'';
  if((type==='篇目候选'||type==='引书候选') && seg){openSegTerm(code,seg,'');return;}
  go('card',code,el.dataset.id||'');
}
// 打开单条知识条目的独立页面；带上当前筛选，返回时能回到同一批结果
function openCard(id){
  const code=state.book&&state.book.row&&state.book.row.code; if(!code||!id)return;
  const f=state.cand&&(state.cand.ke||state.cand.q)||'';
  state.cardBack={code:code,tab:'assets',q:f};
  go('card',code,id);
}
function setTier(t){state.cand.tier=t;state.cand.page=0;drawDetailTab();}
// 从「这本书怎么用」里的科名点进来：切到知识资产页签并按这个词筛
function filterCandBy(q){
  state.cand={tier:'',type:'',q:'',ke:q||'',page:0,offset:0,items:[],total:0,byType:{},loading:false};
  state.pin=null; state.detailTab='assets';
  document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x.textContent.trim()==='知识资产'));
  const code=state.book&&state.book.row&&state.book.row.code;
  if(code&&q){try{history.pushState(null,'','#/book/'+encodeURIComponent(code)+'/assets/'+encodeURIComponent(q));}catch(e){}}
  drawDetailTab();
}
function clearCandQ(){state.cand.q='';state.cand.ke='';state.cand.page=0;drawDetailTab();}
// 图鉴的「全部科名」直接从标签体系 L4 里取，按出现权重排序；
// 以前这里 slice(0,16) 硬截断，118 个科只露出 16 个，且没有出口
function keNames(d){
  return arr((d.tags||{}).L4).filter(x=>String(x['标签']||'').endsWith('科'))
    .sort((a,b)=>(b['权']||0)-(a['权']||0)).map(x=>x['标签']);
}
// 从概览的「全部 N 个科」跳过来：切到知识资产页签并聚焦科名选择器
function showKePicker(){
  const code=state.book&&state.book.row&&state.book.row.code;
  if(code)go('kes',code);
}
function setKe(v){
  state.cand.ke=v||'';state.cand.q='';state.cand.page=0;state.cand.type='';
  const code=state.book&&state.book.row&&state.book.row.code;
  if(code){try{history.pushState(null,'','#/book/'+encodeURIComponent(code)+'/assets/'+(v?encodeURIComponent(v):''));}catch(e){}}
  drawDetailTab();
}

/* ---------------- 标签证据 ---------------- */
function renderLayers(tags){
  const rows=LAYERS.filter(([level])=>arr(tags[level]).length).map(([level,name])=>{
    const items=arr(tags[level]),inferred=['L6','L7'].includes(level);
    return `<div class="layer"><div class="layer-h"><b>${esc(name)}${inferred?'线索 · 待核对':''}</b><span>${num(items.length)} 条</span></div>${items.map(item=>{
      const source=item['seg_id']?`<div class="evgo"><button class="btn sm ghost" data-seg="${esc(item['seg_id'])}" data-name="${esc(item['标签']||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.name)">查看原文</button></div>`:'';
      const detail=[item['值'],item['验证']].filter(Boolean).join(' · ');
      return `<span class="tagitem"><button type="button" class="tagchip ${level==='L7'?'l7':''}" aria-expanded="false" onclick="toggleTagEvidence(this)">${esc(item['标签']||'')}</button><div class="evbox">${detail?`<div class="evh">${esc(detail)}</div>`:''}${item['原文']?`<div>${esc(item['原文'])}</div>`:''}${source}</div></span>`;
    }).join('')}</div>`;
  });
  return rows.join('')||'<p class="muted">暂时没有可查看的标签。</p>';
}
function toggleTagEvidence(el){
  const box=el.closest('.tagitem')?.querySelector('.evbox'),open=box&&!box.classList.contains('on');
  document.querySelectorAll('.tagitem .evbox.on').forEach(previous=>{
    previous.classList.remove('on');previous.previousElementSibling?.setAttribute('aria-expanded','false');
  });
  if(open){box.classList.add('on');el.setAttribute('aria-expanded','true');}
}

let _clcClasses=null;
async function openClc(code,cur){
  if(!_clcClasses){
    try{const d=await jget('/api/clc/classes');_clcClasses=d.items||[];}catch(e){_clcClasses=[];}
  }
  const opts=_clcClasses.length?_clcClasses.map(x=>`<option value="${esc(x.code)}" ${x.code===cur?'selected':''}>${esc(x.code)} ${esc(x.name)}</option>`).join(''):'<option value="">（分类表加载失败）</option>';
  openModal(`${modalX()}
    <h2>改中图分类</h2>
    <div class="muted">中图分类只用于检索、推荐和归架，不影响书里的内容与知识条目；改完立即生效，重跑也不会丢。</div>
    <div class="field" style="margin-top:14px"><label>主类（中图分类 22 类）</label>
      <select id="clcPick">${opts}</select></div>
    <div id="clcMsg" class="note" style="margin-top:8px"></div>
    <div class="modal-actions"><button class="btn ghost" onclick="closeModal()">取消</button>
      <button class="btn primary" id="clcBtn" onclick="saveClc('${esc(code)}')">保存</button></div>`);
}
async function saveClc(code){
  const el=document.getElementById('clcPick'), msg=document.getElementById('clcMsg');
  const v=el?el.value:'';
  if(!v){ if(msg)msg.textContent='先选一个主类。'; return; }
  const btn=document.getElementById('clcBtn'); if(btn){btn.disabled=true;btn.textContent='保存中…';}
  try{
    await post('/api/books/clc',{code,clc:v});
    delete state.bookCache[code];
    closeModal(); toast('中图分类已改为人工指定');
    route();
  }catch(e){ if(btn){btn.disabled=false;btn.textContent='保存';} if(msg)msg.textContent=e.message; }
}

function fmtMix(t){
  // 「判定层裁掉：篇目」是内部决策，不给人看
  return String(t||'').split('；').filter(x=>x&&x.indexOf('判定层裁掉')<0).join('；');
}
const CARD_TYPE={'引书候选':'引书','篇目候选':'篇目','情节候选':'情节','规则候选':'规则','人物条目':'人物','物种条目':'物种','概念候选':'概念'};
const CARD_NAT={'仅定位器':'只用于定位','可直接用':'可直接使用','需人筛':'待人工核对'};
function plainGraph(b){
  if(b['可出关系图谱']) return '可以出：书里有足够的人物同场场景。';
  const g=b['图谱判定']||'';
  if(/强证据人物仅/.test(g)) return '不出。人物基本只在叙述里被提到，没有稳定的同场场景；要出图得先人工确认人物名单。';
  if(/场景密度/.test(g)) return '不出。书里没有「几个人同处一个场合」的场景，人物多是被引用的古人或泛称，出图只会得到没有边的散点。';
  return '不出。';
}
function plainConcept(b){
  const k=b['概念层缺口']||'';
  if(/未抽出论断段/.test(k)) return '这本书没有可抽的观点段（正文没有「故曰/是以」这类明确推理句），所以不出观点条目——这是文体差异，不是漏抽。';
  if(/论断段仅/.test(k)) return '观点段很少，观点层只抽到很少几条。';
  return k;
}
function plainPersonTable(b){
  return '人物表是机器从正文里挑出来的，人工确认后才能用来建关系图。';
}
function howToUseHtml(d,p11,keAll,und){
  let ent='';
  if(p11&&keAll.length){
    ent=`<div class="kwline">${keAll.slice(0,8).map(t=>`<span class="kwchip kwlink" data-q="${esc(t)}" onclick="filterCandBy(this.dataset.q)" title="筛出「${esc(t)}」的条目">${esc(t)}</span>`).join('')}<span class="kwmore" onclick="showKePicker()">全部 ${keAll.length} 个科 ›</span></div>`;
  }else if((und.themes||[]).length){
    ent=`<div class="kwline">${und.themes.slice(0,8).map(t=>`<span class="kwchip theme" data-seg="${esc(t.seg||'')}" data-name="${esc(t['议题']||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.name)">${esc(t['议题']||'')}</span>`).join('')}</div>`;
  }else if(arr(d.people_top).length){
    ent=`<div class="kwline">${arr(d.people_top).slice(0,8).map(p=>`<span class="personchip" data-seg="${esc(p['首现'])}" data-name="${esc(p['人物']||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.name)">${esc(p['人物'])}<em>×${num(p['频次'])}</em></span>`).join('')}</div>`;
  }
  return `
    <div class="how-row"><div class="how-k">查原文</div><div class="how-v">打开「原文」按篇阅读，或用上方搜索框找关键词。</div></div>
    ${ent?`<div class="how-row"><div class="how-k">快速查找</div><div class="how-v">${ent}</div></div>`:''}`;
}

function clcChip(clc){
  const manual=clc['来源']==='人工';
  const conf=clc['置信']||'';
  const weak=!manual && conf && conf!=='高';
  return `<span class="clc-chip" title="${esc((clc['依据']||[]).join('；'))}"><span class="clc-label">中图分类</span><b>${esc(clc['代码'])}</b> ${esc(clc['名称'])}<span class="clc-sep"></span>
    <span class="clc-flag${manual?' manual':''}">${manual?'人工指定':'系统建议'}</span>${weak?'<span class="clc-wait">待核对</span>':''}
    <button class="clc-help" type="button" onclick="toggleClcHelp(this)" aria-label="中图分类说明">?</button></span>
  <div class="clc-helpbox">
    <div class="clc-hb-title">中图分类说明</div>
    <p>中图分类（CLC）是国家图书馆分类标准，共 22 个主类，覆盖全部图书品种。这里显示的是这本书的归类，只用于检索、推荐和上架。</p>
    <p>分类号由系统按书名与内容自动判定，不是出版社的正式编目号。标「待核对」表示判定依据较弱，对外使用前请核对。</p>
    <p>书架分类用于查找和归架。标签按书中内容检查。</p>
    <p class="faint">如需更正，点下方「图书档案」里的「改判」人工指定。</p>
  </div>`;
}
function toggleClcHelp(btn){
  const box=btn.closest('.clc-wrap').querySelector('.clc-helpbox');
  const open=box&&!box.classList.contains('on');
  document.querySelectorAll('.clc-helpbox.on').forEach(b=>b.classList.remove('on'));
  if(box&&open)box.classList.add('on');
}

/* ---------------- 概览：事实摘录 ---------------- */
async function loadFacts(){
  const host=document.getElementById('factList'); if(!host)return;
  const code=state.book&&state.book.row&&state.book.row.code; if(!code)return;
  try{
    // 只认真正可交付的条目。引书 / 篇目是「定位类」，不算关键事实：
    // 只有它们的时候，这块标题名不副实，宁可整块不显示（未编目状态在下面的图书档案里有说明）。
    const ready=await jget('/api/book/cards?'+new URLSearchParams({code,tier:'可直接用',limit:'24'}).toString());
    // 「关键事实」只收事实类条目。物种条目、人物条目、引书、篇目都是资产或定位，
    // 各自有专门的位置（知识资产 / 书里出现的人 / 原文），不在这里重复一遍。
    const NOT_FACT=['引书候选','篇目候选','物种条目','人物条目'];
    const items=(ready.items||[]).filter(c=>NOT_FACT.indexOf(c['类型'])<0).slice(0,6);
    // 一条可用条目都没有，就不留一个空面板占地方；整块收掉
    if(!items.length){const sec=document.getElementById('secFacts');if(sec)sec.remove();return;}
    // 概览里的摘录也打开同一个条目页，别出现「列表能点、摘录不能点」
    host.innerHTML=items.map(c=>`<div class="fact fact-click" onclick="openCard('${esc(c.id)}')">
      <div class="fact-main">${esc(clip(c['_excerpt']||c['原文']||'',150))}</div>
      <div class="fact-meta"><span class="pill">${esc(c['类型']||'条目')}</span><span class="faint">${esc(c['锚点']||'')}</span>
      ${c['seg_id']?`<button class="btn sm ghost" data-seg="${esc(c['seg_id'])}" data-name="${esc(cardName(c))}" onclick="event.stopPropagation();locateAnchor(this.dataset.seg,this.dataset.name)">定位原文 →</button>`:''}</div>
    </div>`).join('');
  }catch(e){host.innerHTML=`<div class="faint">条目加载失败：${esc(e.message)}</div>`;}
}
function entChips(k,sub){
  return sub.map(x=>`<span class="entchip ${k}" data-seg="${esc(x.seg||'')}" data-name="${esc(x.name||'')}" title="${esc(x.sci||x.src||'')}" onclick="locateAnchor(this.dataset.seg,this.dataset.name)">${esc(x.name)}${x.count>1?`<em>×${num(x.count)}</em>`:''}</span>`).join('');
}
// 一个类目一组；组里只放前 24 个，剩下给「还有 N 个 ›」，点了再取全
function entGroupHtml(k,label,sub,total,code){
  const rest=total-sub.length;
  return `<div class="ent-group" id="ent-${k}">
    <div class="ent-h">${label}<span class="faint">${num(total)}</span>${rest>0?`<span class="kwmore" style="margin-left:9px" onclick="go('ents','${esc(code||'')}','${k}')">还有 ${num(rest)} 个 ›</span>`:''}</div>
    <div class="kwline">${entChips(k,sub)}</div></div>`;
}

/* ================= 按名称核对出处 ================= */
const NAME_CHECK_PAGE_SIZE=20,NAME_CHECK_QUERY_LIMIT=100;
async function renderReview(v,code,query){
  const isCurrent=capturePageRequest(v);
  v.innerHTML=loading('打开名称查找');
  let book=state.bookCache[code];
  if(!book){
    try{book=await jget('/api/book?'+new URLSearchParams({code}));state.bookCache[code]=book;}
    catch(err){if(isCurrent())v.innerHTML=`<div class="panel"><div class="empty">无法打开图书。${esc(err.message)}</div></div>`;return;}
  }
  if(!isCurrent())return;
  const title=book.row?.book||code;
  const q=String(query||'').trim().slice(0,NAME_CHECK_QUERY_LIMIT);
  const R=state.review={code,items:[],query:q,offset:0,count:0,request:0,selection:0,idx:-1};
  crumb(`<span>来源图书</span><span>/</span><button type="button" class="btn xs ghost" onclick="go('book','${esc(code)}')">${esc(clip(title,16))}</button><span>/</span><b>查找待核对名称</b>`);
  v.innerHTML=`<div class="page-head"><div><h1>查找待核对名称</h1><p>输入要用的人名、地名或书名，找到出处后，可以为这一段补一条核对记录。</p></div>
      <div class="head-actions"><button type="button" class="btn ghost" onclick="go('ents','${esc(code)}')">返回名称索引</button></div></div>
    <section class="panel"><div class="panel-body">
      <form class="cand-toolbar" onsubmit="event.preventDefault();revSearch(this)">
        <div class="search"><input id="revQ" name="q" type="search" aria-label="要查找的名称" placeholder="输入名称，如陶澍" value="${esc(q)}" maxlength="${NAME_CHECK_QUERY_LIMIT}"></div>
        <button type="submit" class="btn primary">查找</button>
      </form>
      <div class="split"><div style="min-width:0"><div class="review-list" id="revList" style="max-height:420px" aria-live="polite"><p class="muted">先输入想核对的名称。</p></div><div id="revPager" hidden></div></div>
        <div style="min-width:0"><div class="rev-ctx" id="revCtx"></div><div id="revActions"></div></div></div>
    </div></section>`;
  if(R.query)await revLoad(0);
}
function revSearch(form){
  const R=state.review;
  if(!R)return;
  R.query=String(new FormData(form).get('q')||'').trim().slice(0,NAME_CHECK_QUERY_LIMIT);
  return revLoad(0);
}
async function revLoad(offset){
  const R=state.review,list=document.getElementById('revList'),pager=document.getElementById('revPager');
  const ctx=document.getElementById('revCtx'),acts=document.getElementById('revActions');
  if(!R||!list||!pager||!ctx||!acts)return;
  const request=++R.request,isCurrent=capturePageRequest(document.getElementById('view'));
  const active=()=>isCurrent()&&state.review===R&&request===R.request;
  R.items=[];R.idx=-1;R.selected=null;R.selection++;
  ctx.innerHTML='';acts.innerHTML='';pager.hidden=true;pager.classList.remove('cand-pager');
  if(!R.query){list.innerHTML='<p class="muted">先输入想核对的名称。</p>';return;}
  list.innerHTML=loading('正在查找名称');
  try{
    const d=await jget('/api/book/entity-review?'+new URLSearchParams({code:R.code,q:R.query,offset:String(offset),limit:String(NAME_CHECK_PAGE_SIZE)}));
    if(!active())return;
    if(!Number.isInteger(d.offset)){list.innerHTML='<p class="muted">这时还无法按名称查找。可在这本书的原文里搜索。</p>';return;}
    R.items=arr(d.items);R.offset=d.offset;R.count=Number(d.count)||0;
    drawReviewList();
  }catch(err){if(active())list.innerHTML='<p class="muted">暂时无法查找名称，请再试一次。</p>';}
}
function drawReviewList(){
  const R=state.review,list=document.getElementById('revList'),pager=document.getElementById('revPager');
  if(!R||!list||!pager)return;
  list.innerHTML=R.items.length?R.items.map((item,index)=>{
    const current=index===R.idx,excerpt=item.snippet?`<div class="rev-snip">${hlName(item.snippet,item.name)}</div>`:'';
    return `<div class="rev-item${current?' on':''}"><button type="button" class="btn sm ghost" data-index="${index}" aria-pressed="${current}" onclick="revSelect(Number(this.dataset.index))">${esc(item.name)} · 查看出处</button>${excerpt}</div>`;
  }).join(''):'<p class="empty">没找到相关名称。可以换个写法，或在原文里查找。</p>';
  const more=R.offset+R.items.length<R.count;
  pager.hidden=!R.offset&&!more;
  pager.classList.toggle('cand-pager',!pager.hidden);
  pager.innerHTML=`<button type="button" class="btn sm ghost" onclick="revLoad(Math.max(0,state.review.offset-NAME_CHECK_PAGE_SIZE))"${R.offset?'':' disabled'}>上一页</button><button type="button" class="btn sm ghost" onclick="revLoad(state.review.offset+NAME_CHECK_PAGE_SIZE)"${more?'':' disabled'}>下一页</button>`;
}
async function revSelect(index){
  const R=state.review,item=R?.items[index],ctx=document.getElementById('revCtx'),acts=document.getElementById('revActions');
  if(!item||!ctx||!acts)return;
  const token=++R.selection,isCurrent=capturePageRequest(document.getElementById('view'));
  const active=()=>isCurrent()&&state.review===R&&token===R.selection;
  const anchor=item.anchor||item.seg||'';
  R.idx=index;R.selected=null;
  document.querySelectorAll('#revList [data-index]').forEach(button=>{
    const current=Number(button.dataset.index)===index;
    button.setAttribute('aria-pressed',String(current));button.closest('.rev-item').classList.toggle('on',current);
  });
  if(!anchor){ctx.innerHTML='<p class="muted">这条记录没有可查看的出处。</p>';acts.innerHTML='';return;}
  ctx.innerHTML=loading('正在打开出处');acts.innerHTML='';
  const routeLink=`<button type="button" class="btn sm ghost" data-code="${esc(R.code)}" data-anchor="${esc(anchor)}" data-name="${esc(item.name)}" onclick="openSegTerm(this.dataset.code,this.dataset.anchor,this.dataset.name)">在原文页打开</button>`;
  try{
    const d=await jget('/api/book/name-check?'+new URLSearchParams({code:R.code,anchor,name:item.name}));
    if(!active())return;
    R.selected={anchor:d.anchor||anchor,name:item.name,revision:d.revision};
    const saved=d.review||{};
    ctx.innerHTML=`<h3>「${esc(item.name)}」所在段落</h3><div class="rev-seg-t">${hlName(d.text,item.name)}</div><div class="rev-links">${routeLink}</div>`;
    if(window.matchMedia('(max-width:1100px)').matches)ctx.scrollIntoView({block:'start'});
    if(!d.revision)return;
    acts.innerHTML=`<form class="rev-actions" style="display:grid;gap:10px" onsubmit="event.preventDefault();revSave(this)">
      <div class="field"><label for="revCat">类别（可选）</label><select id="revCat" name="cat"><option value="">不指定类别</option>${ENT_ORDER.map(key=>`<option value="${key}"${saved.cat===key?' selected':''}>${ENT_LABEL[key]}</option>`).join('')}<option value="ignore"${saved.cat==='ignore'?' selected':''}>这处无需核对</option></select></div>
      <label class="studio-field"><span>核对说明（可选）</span><textarea name="note" rows="3" maxlength="240" placeholder="例如这里指一处地名，采用时保留书中的写法。">${esc(saved.note||'')}</textarea></label>
      <div class="rev-btns"><button type="submit" class="btn primary">保存这一处</button><span class="muted" role="status">${saved.updated_at?'已保存核对记录':''}</span></div>
    </form>`;
  }catch(err){if(active())ctx.innerHTML=`<p class="muted">暂时无法在这里打开这处原文。</p><div class="rev-links">${routeLink}<button type="button" class="btn sm ghost" data-index="${index}" onclick="revSelect(Number(this.dataset.index))">重试</button></div>`;}
}
async function revSave(form){
  const R=state.review,selected=R?.selected;
  if(!selected||!selected.revision||form.dataset.busy)return;
  const msg=form.querySelector('[role="status"]'),button=form.querySelector('[type="submit"]');
  const values=new FormData(form),note=String(values.get('note')||'').trim(),cat=String(values.get('cat')||'');
  if(!note&&!cat){msg.textContent='请填写说明或选择类别。';return;}
  form.dataset.busy='true';button.disabled=true;msg.textContent='正在保存';
  try{
    const payload={code:R.code,anchor:selected.anchor,name:selected.name,revision:selected.revision,note,cat};
    const d=await post('/api/book/name-check',payload);
    if(!form.isConnected||state.review!==R||R.selected!==selected)return;
    if(d.revision)selected.revision=d.revision;
    msg.textContent='已保存这一处的核对记录。';
  }catch(err){if(form.isConnected)msg.textContent=err.message||'这次未保存，可以重试。';}
  finally{delete form.dataset.busy;button.disabled=false;}
}

/* ================= 全部专名（独立页面） ================= */
// 组内「还有 N 个 ›」不再就地铺开（铺开就收不回去），一律进这一页看全
const GEO_ORDER=['country','province','region','city','district','landmark','nature'];
const ENT_LABEL={country:'国家',province:'省份',region:'区域/大区',city:'城市',district:'区县',landmark:'道路/地标',nature:'自然地理',fossil:'化石/古人类',org:'机构',object:'器物',animal:'动物',plant:'植物',taxon:'科属',alias:'别名',person:'人物',book:'引书',concept:'概念/术语',award:'奖项',event:'事件',dynasty:'朝代',family:'家族'};
const ENT_ORDER=[...GEO_ORDER,'fossil','org','object','animal','plant','taxon','alias','person','book','concept','award','event','dynasty','family'];
function entChipsNav(code,k,sub){
  return sub.map(x=>`<a class="entchip ${k}" data-code="${esc(code)}" data-seg="${esc(x.seg||'')}" data-name="${esc(x.name)}" data-cat="${esc(k)}"
      onclick="openEnt(this.dataset.code,this.dataset.seg,this.dataset.name,this.dataset.cat)"
      title="${esc(x.sci||x.src||'')}">${esc(x.name)}${x.count>1?`<em>×${num(x.count)}</em>`:''}</a>`).join('');
}
async function renderEnts(v,code,cat){
  const isCurrent=capturePageRequest(v);
  if(!isCurrent())return;v.innerHTML=loading('加载专名');
  let d=null,bk=state.bookCache[code];
  try{
    d=await jget('/api/book/entities?'+new URLSearchParams({code,limit:'2000'}).toString());
    if(!bk){bk=await jget('/api/book?'+new URLSearchParams({code}).toString());state.bookCache[code]=bk;}
  }catch(e){ if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">加载失败：${esc(e.message)}</div></div>`; return; }
  if(!isCurrent())return;
  const items=d.items||[], counts=d.counts||{};
  const total=Object.values(counts).reduce((a,b)=>a+b,0);
  const title=(bk&&bk.row&&bk.row.book)||code;
  const cats=ENT_ORDER.filter(k=>(counts[k]||0)>0);
  const geoCats=GEO_ORDER.filter(k=>(counts[k]||0)>0);
  const otherCats=ENT_ORDER.filter(k=>!GEO_ORDER.includes(k)&&(counts[k]||0)>0);
  const geoTotal=geoCats.reduce((a,k)=>a+(counts[k]||0),0);
  state.entsAll={code:code,items:items,counts:counts,total:total,cats:cats};
  // 默认落在地名；带类别进来就选中那个类别。一次只显示一个类别，全部在同一页切换
  state.ents={cat:(cat&&ENT_LABEL[cat])?cat:(cats[0]||''),q:''};
  if(!isCurrent())return;crumb(`<span>来源图书</span><span>/</span><a onclick="go('book','${esc(code)}')">${esc(clip(title,16))}</a><span>/</span><b>名称索引</b>`);
  if(!isCurrent())return;v.innerHTML=`
    <div class="page-head">
      <div><h1>人名、地名等</h1>
        <p>${num(total)} 个名称，分为 ${num(cats.length)} 类。点名称查看出处。</p></div>
      <div class="head-actions"><button class="btn ghost" onclick="go('book','${esc(code)}')">← 返回这本书</button></div>
    </div>
    <section class="panel">
      <div class="panel-head"><div><h2>专名</h2><div class="sub">先选类别，再在里面找</div></div><span class="faint" id="entsCount"></span></div>
      <div class="panel-body">
        <div class="cand-toolbar">
          <div class="search"><input id="entsQ" placeholder="搜专名，如「松」" value=""
            onkeydown="if(event.key==='Enter'){event.preventDefault();applyEntsQ();}"><kbd>↵</kbd></div>
          <button class="btn sm" onclick="applyEntsQ()">查询</button>
          <button type="button" class="btn sm ghost" data-code="${esc(code)}" onclick="openNameChecks(this.dataset.code)">查找待核对名称</button>
        </div>
        <div id="entsCats" style="padding:0 0 14px">
          ${geoCats.length?`<details class="ent-fold" open><summary><b>地理</b><span class="faint">${num(geoTotal)} 个 · 按层级分</span></summary>
            <div class="chips" style="padding:8px 0 10px">
              ${geoCats.map(k=>`<span class="chip ${state.ents.cat===k?'on':''}" data-cat="${k}" onclick="setEntCat('${k}')">${ENT_LABEL[k]} ${num(counts[k])}</span>`).join('')}
            </div></details>`:''}
          <div class="chips" style="padding:8px 0 4px">
            ${otherCats.map(k=>`<span class="chip ${state.ents.cat===k?'on':''}" data-cat="${k}" onclick="setEntCat('${k}')">${ENT_LABEL[k]} ${num(counts[k])}</span>`).join('')}
          </div>
        </div>
        <div id="entsTable"></div>
        <div class="cand-pager" id="entsPager"></div>
      </div>
    </section>`;
  drawEnts();
}
function openNameChecks(code){
  const query=(document.getElementById('entsQ')?.value||'').trim().slice(0,NAME_CHECK_QUERY_LIMIT);
  go('review',code,query);
}
function entsFiltered(){
  const A=state.entsAll||{items:[]}, E=state.ents||{};
  const kw=(E.q||'').trim();
  return (A.items||[]).filter(x=>
    (!E.cat||x.cat===E.cat)&&(!kw||(x.name||'').indexOf(kw)>=0)
  ).sort((a,b)=>b.count-a.count||String(a.name).localeCompare(String(b.name),'zh'));
}
function drawEnts(){
  const host=document.getElementById('entsTable'); if(!host)return;
  const rows=entsFiltered(), E=state.ents||{};
  const cnt=document.getElementById('entsCount');
  if(cnt)cnt.textContent=num(rows.length)+' 个';
  host.innerHTML=rows.length?`<div class="ent-group">
      <div class="ent-h">${ENT_LABEL[E.cat]||'专名'}<span class="faint">${num(rows.length)}</span></div>
      <div class="kwline">${rows.map(x=>`<a class="entchip ${x.cat}" data-code="${esc(state.entsAll.code)}" data-seg="${esc(x.seg||'')}" data-name="${esc(x.name)}" data-cat="${esc(x.cat)}"
        onclick="openEnt(this.dataset.code,this.dataset.seg,this.dataset.name,this.dataset.cat)"
        title="${esc(x.sci||x.src||'')}">${esc(x.name)}${x.count>1?`<em>×${num(x.count)}</em>`:''}</a>`).join('')}</div>
    </div>`:`<div class="empty">这一类里没有匹配的专名</div>`;
  const pg=document.getElementById('entsPager');
  if(pg)pg.innerHTML=`<span>${ENT_LABEL[E.cat]||''} 共 ${num(rows.length)} 个</span><span class="sp"></span>
    <button class="btn sm ghost" onclick="window.scrollTo({top:0,behavior:'smooth'})">↑ 回到顶部</button>`;
}
function setEntCat(k){
  state.ents.cat=k||''; state.ents.q='';
  const q=document.getElementById('entsQ'); if(q)q.value='';
  document.querySelectorAll('#entsCats .chip').forEach(c=>c.classList.toggle('on',c.dataset.cat===state.ents.cat));
  drawEnts();
}
function applyEntsQ(){
  const el=document.getElementById('entsQ');
  state.ents.q=el?el.value.trim():'';
  drawEnts();
}

function showEnts(cat){
  const code=state.book&&state.book.row&&state.book.row.code;
  if(code)go('ents',code,cat||'');
}
async function loadEntities(){
  const host=document.getElementById('entBox'); if(!host)return;
  const code=state.book&&state.book.row&&state.book.row.code; if(!code)return;
  try{
    const d=await jget('/api/book/entities?'+new URLSearchParams({code,limit:'24'}).toString());
    const items=d.items||[], counts=d.counts||{};
    const total=Object.values(counts).reduce((a,b)=>a+b,0);
    const cnt=document.getElementById('entCount');
    if(cnt)cnt.textContent=num(total)+' 个已整理名称';
    const ea=document.getElementById('entAll'); if(ea)ea.textContent='全部专名 '+num(total)+' 个 ›';
    if(!items.length){const sec=document.getElementById('secEntities');if(sec)sec.remove();return;}
    const CATS=ENT_ORDER.map(k=>[k,ENT_LABEL[k]]);
    const geoCats=GEO_ORDER.filter(k=>(counts[k]||0)>0);
    const otherCats=CATS.filter(([k])=>!GEO_ORDER.includes(k)&&(counts[k]||0)>0)
      .sort((a,b)=>(counts[b[0]]||0)-(counts[a[0]]||0));
    const geoHtml=geoCats.length?`<div class="ent-group"><div class="ent-h">地理<span class="faint">${num(geoCats.reduce((a,k)=>a+(counts[k]||0),0))} 个 · 按层级分</span></div>${
      geoCats.map(k=>{const sub=items.filter(x=>x.cat===k).slice(0,6);return sub.length?`<div class="faint" style="margin:8px 0 2px">${ENT_LABEL[k]} · ${num(counts[k]||0)}</div><div class="kwline">${entChipsNav(code,k,sub)}</div>`:'';}).join('')
    }</div>`:'';
    // 概览只预览地理 + 数量最多的 2 个非地理类；完整清单在「全部专名」页
    host.innerHTML=geoHtml+otherCats.slice(0,2)
      .map(([k,label])=>entGroupHtml(k,label,items.filter(x=>x.cat===k).slice(0,8),counts[k]||8,code))
      .join('')||'<div class="faint">这本书还没抽出专名。</div>';
  }catch(e){host.innerHTML=`<div class="faint">专名加载失败：${esc(e.message)}</div>`;}
}
function openTextAt(chapter){
  state.pin=null; state.pinTerm=''; state.pinMode=''; state.pinTotal=0; state.pinFrom=''; state.pinFocus=false; state.detailTab='text';
  document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x.textContent.trim()==='原文'));
  drawDetailTab(chapter);
}

/* ---------------- 原文 ---------------- */
function loadText(btn,chapter){
  document.querySelectorAll('#outlineBox button').forEach(b=>b.classList.remove('on'));btn.classList.add('on');
  state.pin=null; state.pinTerm=''; state.pinMode=''; state.pinTotal=0; state.pinFrom=''; state.pinFocus=false;
  state.seg.hit=''; state.seg.chapter=chapter; state.seg.offset=0;
  const pn=document.querySelector('.pin-note'); if(pn)pn.remove();
  loadSegments(chapter,true);
}
/* 锚点定位：只取目标段前后各 2 段，不拉整篇；命中段高亮并滚到中间 */
function hlName(text,name){
  const t=esc(text||''), n=esc(name||'');
  return n?t.split(n).join(`<mark class="nmhl">${n}</mark>`):t;
}
async function openEntityOcc(code,name){
  try{
    const d=await jget('/api/book/entity?'+new URLSearchParams({code,name,limit:'30'}).toString());
    const items=d.items||[];
    openModal(`${modalX()}<h2>${esc(name)}</h2>
      <div class="muted">在全书 ${num(d.total)} 段里出现。地名/机构多是夹在物种「分布」或版权页里被提到，直接跳一段看不出关系——先从下面挑一处。</div>
      <div class="entoccs">${items.length?items.map(x=>`<div class="entocc" data-seg="${esc(x.seg)}" onclick="closeModal();openSegTerm('${esc(code)}',this.dataset.seg,'${esc(name)}')"><div class="eo-snip">${hlName(x.snippet,name)}</div><div class="faint">${esc(x.chapter||'')} · ${esc(x.seg)}</div></div>`).join(''):'<div class="empty">没有找到出现位置</div>'}</div>`);
  }catch(e){toast('加载失败：'+e.message,true);}
}
function openEnt(code,seg,name,cat){
  if(GEO_ORDER.includes(cat)||cat==='org'){openEntityOcc(code,name);return;}
  openSegTerm(code,seg,name);
}
/* 跳原文时把「来意」一起带上：mode 决定落到原文标什么、横幅怎么写。
   mode: cite=从引文核对来（标书名） / chapter=从篇目来（不标词，读完就走）
         person|term=从人物、专名、术语来（标这个词） / quote=从金句、营销证据来 */
function openSegTerm(code,seg,name,opts){
  opts=opts||{};
  state.entJump={term:name||'', mode:opts.mode||'term', total:opts.total||0, from:opts.from||''};
  // 来意写进 URL：刷新、分享、后退回来，高亮和横幅都还在。
  // 参数各自编码后直接拼，不再交给 go() 二次编码——地址栏保持可读。
  const ps=[];
  if(name)ps.push('t='+encodeURIComponent(name));
  if(opts.mode)ps.push('k='+encodeURIComponent(opts.mode));
  if(opts.total)ps.push('n='+encodeURIComponent(opts.total));
  if(opts.from)ps.push('f='+encodeURIComponent(opts.from));
  let h='#/book/'+encodeURIComponent(code)+'/text/'+encodeURIComponent(seg||'');
  if(ps.length)h+='?'+ps.join('&');
  if(state.lastHash===location.hash)state.scroll[state.lastHash]=window.scrollY;
  state.depth++;
  if(location.hash===h){state.depth--;return;}
  else{state.fromGo=true;location.hash=h;}
}
async function locateAnchor(anchor,term,mode,total,from){
  const code=state.book&&state.book.row&&state.book.row.code; if(!code||!anchor)return;
  try{
    const d=await jget('/api/book/segment?'+new URLSearchParams({code,anchor,radius:'2'}).toString());
    state.pin=d; state.pinTerm=term||'';
    state.pinMode=(mode||'')||(state.pinTerm?'term':'');
    state.pinTotal=total||0; state.pinFrom=from||'';
    state.pinFocus=((mode||'')==='cite');
    state.detailTab='text';
    document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x.textContent.trim()==='原文'));
    drawDetailTab();
  }catch(e){toast('定位失败：'+e.message,true);}
}
function clearPin(){const ch=state.seg&&state.seg.chapter;state.pin=null;state.pinTerm='';state.pinMode='';state.pinTotal=0;state.pinFrom='';state.pinFocus=false;drawDetailTab(ch);}
// 原文页签的两种视图：按篇阅读 / 可引用句（默认按篇）
function openQuotes(){
  state.pin=null; state.textMode='quotes'; state.detailTab='text';
  document.querySelectorAll('.tabs button').forEach(x=>x.classList.toggle('on',x.textContent.trim()==='原文'));
  drawDetailTab();
}
function openChapterMode(){ state.textMode='chapter'; drawDetailTab(); }
/* 定位横幅：先说来意（从哪来、看什么），再说位置。
   以前所有入口都写「已定位到 XX 第 N 段」，从引文点进来会以为跳错了。 */
function pinNoteHtml(pin){
  const mode=state.pinMode||'', term=String(state.pinTerm||''), total=state.pinTotal||0;
  const pian=esc(pin['篇']||''), duan=esc(pin['段']||'');
  const pos=`篇内第 ${(pin.chapter_index||0)+1}/${esc(pin.chapter_total)} 段 · 全文第 ${(pin.index||0)+1}/${esc(pin.total)} 段`;
  let head='', back='', cnt='';
  if(mode==='cite'){
    // 从引文核对进来：先回答「这本书在这段里出现了几次、全书几次」
    head=`<b>${esc(term)}</b><span>在「${pian}」第 ${duan} 段</span>`;
    if(total)head+=`<span>全书正文 ${num(total)} 次</span>`;
    cnt='<span>本段出现 <b id="pinHitCount">…</b> 次</span>';
    if(state.pinFrom==='editor')back=`<a class="pin-back" onclick="backToEditor('cite')">← 回资料整理</a>`;
  }else if(mode==='chapter'){
    head=`<b>第 ${esc(pin['篇序']!=null?pin['篇序']:'—')} 篇「${pian}」</b><span>读到第 ${duan} 段</span>`;
    if(state.pinFrom==='editor')back=`<a class="pin-back" onclick="backToEditor('chapter')">← 回资料整理</a>`;
  }else if(mode==='person'||mode==='term'){
    head=`<b>「${esc(term)}」</b><span>在「${pian}」第 ${duan} 段</span>`;
    cnt='<span>本段出现 <b id="pinHitCount">…</b> 次</span>';
  }else if(mode==='quote'){
    head=`<b>引句落点</b><span>「${pian}」第 ${duan} 段</span>`;
  }else if(mode==='search'){
    head=`<b>「${esc(term)}」</b><span>在「${pian}」第 ${duan} 段</span>`;
    if(AppHistory.previous()?.startsWith('#/search/'))back='<button type="button" class="btn sm ghost" onclick="navBack()">返回搜索结果</button>';
  }else{
    head=`<b>已定位到「${pian}」第 ${duan} 段</b>`;
  }
  const page=Number(pin.source_page),code=state.book?.row?.code;
  if(code&&window.MarketingReview)back+=MarketingReview.returnLink(code);
  const pdf=page>0?pin.has_original_pdf&&code?`<a class="pin-back" href="/api/book/source?${new URLSearchParams({code})}#page=${page}" target="_blank" rel="noopener">PDF 第 ${page} 页 ↗</a>`:`<span>PDF 第 ${page} 页</span>`:'';
  const scan=pin.source_method==='ocr'?'<span>文字由页面识别得到，引用前请对照 PDF 原页。</span>':'';
  return `<div class="pin-note">${head}${cnt}<span class="pin-pos">${pos}</span>${pdf}${scan}${back}</div>`;
}

function backToEditor(tab){
  const code=state.book&&state.book.row&&state.book.row.code;
  if(code)go('editor',code,tab==='chapter'?'chapter':'cite');
}

// 横幅里的「本段出现 N 次」要等这一段原文加载完才能数
function setPinHitCount(items){
  const el=document.getElementById('pinHitCount'); if(!el)return;
  const term=String(state.pinTerm||''); if(!term)return;
  const hit=arr(items).filter(x=>x['id']===state.seg.hit)[0];
  if(!hit)return;
  const n=String(hit['文本']||'').split(term).length-1;
  el.textContent=num(n);
  // 议题/术语常常是概括词，原文里不一定逐字出现；0 次就不摆这一句，免得像出错
  if(!n&&state.pinMode!=='cite')el.parentNode.hidden=true;
}

function segItemHtml(s){
  const hit=!!(state.seg&&state.seg.hit&&s['id']===state.seg.hit);
  const ch=state.seg&&state.seg.chapter;
  const cur=!!(ch&&s['篇']===ch);
  const mode=state.pinMode||'';
  // 带词进来就标那个词；只进来读（篇目/深链）时，只有人物体的书才标篇名
  const term=(mode&&mode!=='chapter')?String(state.pinTerm||''):'';
  const personBook=!!(state.book&&state.book.book&&state.book.book['结构单位']==='人');
  let txt=esc(s['文本']||'');
  if(term){
    const te=esc(term);
    txt=txt.split(te).join(`<mark class="nmhl pinhl">${te}</mark>`);
  }else if(personBook&&ch&&ch.length>=2){
    // 人物体：篇名就是人名，标出来方便在长段里找这个人
    const c=esc(ch);
    txt=txt.split(c).join(`<mark class="nmhl">${c}</mark>`);
  }
  const pian=cur?`<b>${esc(s['篇']||'')}</b>`:esc(s['篇']||'');
  const pno=s['篇序']!=null?`第 ${esc(s['篇序'])} 篇 · `:'';
  const scan=s.source_method==='ocr'?' · 页面识别文字':'';
  return `<div class="seg-item${hit?' hit':''}${cur?' cur':''}" data-seg="${esc(s['id']||'')}"><div class="anch" title="${esc(s['锚点']||'')}">${pno}${pian} · 第 ${esc(s['段']||'')} 段${hit?' · 已定位':''}${scan}</div><div class="txt">${txt}</div></div>`;
}
function pinShowChapter(){ state.pinFocus=false; drawDetailTab(); }

// 引文落点：本章扫一遍，只渲染含这个词的段（其余原文不往页面上铺）
async function loadPinFocus(){
  const host=document.getElementById('segBox'); if(!host)return;
  host.innerHTML=loading('加载相关段落');
  const term=String(state.pinTerm||''), chapter=state.seg.chapter;
  try{
    const code=state.book.row.code;
    const d=await jget('/api/book/segments?'+new URLSearchParams({code,chapter,offset:'0',limit:'100'}));
    const all=d.items||[];
    const hits=term?all.filter(x=>String(x['文本']||'').indexOf(term)>=0):[];
    if(!hits.length){ state.pinFocus=false; drawDetailTab(); return; }
    state.seg.total=all.length;
    const times=hits.reduce(function(a,x){return a+String(x['文本']||'').split(term).length-1;},0);
    const total=Number(state.pinTotal||0);
    const stat=document.getElementById('pinFocusStat');
    if(stat){
      let msg='本篇 '+all.length+' 段里，有 '+hits.length+' 段提到「'+term+'」，共 '+times+' 次';
      if(total>times) msg+='；全书 '+total+' 次，其余 '+(total-times)+' 次在别的篇';
      stat.textContent=msg;
    }
    host.innerHTML=hits.map(segItemHtml).join('');
    setPinHitCount(all);
    setTimeout(function(){
      const m=host.querySelector('mark.pinhl');
      if(m)m.scrollIntoView({block:'center'});
      else{const h=host.querySelector('.seg-item');if(h)h.scrollIntoView({block:'start'});}
    },80);
    const more=document.getElementById('segMore'); if(more)more.innerHTML='';
  }catch(e){ host.innerHTML='<div class="empty">'+esc(e.message)+'</div>'; }
}

async function loadSegments(chapter,reset){
  const host=document.getElementById('segBox'); if(!host)return;
  if(reset){
    // 定位到某一段时，不能从篇首开始加载：命中段常常在篇内第 10 段以后，
    // 从 0 开始只加载前 12 段，命中段根本没渲染 → 看起来"跳错了"。
    const pinOk=state.pin&&state.seg&&chapter===(state.pin['篇']||'');
    state.seg.offset=pinOk?(state.pin.chapter_offset||0):0;
    host.innerHTML=loading('加载原文');
  }
  try{
    const code=state.book.row.code;
    const d=await jget('/api/book/segments?'+new URLSearchParams({code,chapter,offset:String(state.seg.offset),limit:'12'}).toString());
    const items=d.items||[]; state.seg.total=d.total;
    if(reset){
      host.innerHTML=items.length?items.map(segItemHtml).join(''):'<div class="empty">这一篇没有切出段落</div>';
      setPinHitCount(items);
      setTimeout(()=>{
        const h=host.querySelector('.seg-item.hit');
        const m=h&&h.querySelector('mark.pinhl');
        if(m)m.scrollIntoView({block:'center'});
        else if(h)h.scrollIntoView({block:'center'});
      },80);
    }else host.insertAdjacentHTML('beforeend',items.map(segItemHtml).join(''));
    const more=document.getElementById('segMore'); const shown=host.querySelectorAll('.seg-item').length;
    if(more)more.innerHTML=shown<state.seg.total?`<button class="btn sm ghost" onclick="loadMoreSegments()">加载更多（${shown}/${state.seg.total}）</button>`:'';
  }catch(e){host.innerHTML=`<div class="empty">${esc(e.message)}</div>`;}
}
function loadMoreSegments(){state.seg.offset+=12;loadSegments(state.seg.chapter,false);}

/* ---------------- 删除 / 改判 / 元信息 / 确认 ---------------- */
function openDelete(code,title){
  openModal(`${modalX()}<h2>删除《${esc(title)}》</h2>
    <div class="note warn">这是软删除：底本与产物保留，可在回收站恢复；全库统计会立即重建。</div>
    <div class="field" style="margin-top:12px"><label>输入书名确认</label><input id="delTitle" placeholder="${esc(title)}"></div>
    <div id="delMsg" class="note" style="margin-top:7px"></div>
    <div class="modal-actions"><button class="btn ghost" onclick="closeModal()">取消</button><button class="btn danger" id="delBtn" data-code="${esc(code)}" data-title="${esc(title)}" onclick="doDelete(this.dataset.code,this.dataset.title)">确认删除</button></div>`);
}
async function doDelete(code,title){
  const v=(document.getElementById('delTitle').value||'').trim(), msg=document.getElementById('delMsg');
  if(v!==title){msg.textContent='书名不一致，未删除。';return;}
  const btn=document.getElementById('delBtn'); btn.disabled=true; btn.textContent='删除中…';
  try{delete state.bookCache[code];await post('/api/books/delete',{code,confirm:v});closeModal();toast('已删除，可在回收站恢复');go('library');}
  catch(e){btn.disabled=false;btn.textContent='确认删除';msg.textContent=e.message;}
}
function openRetype(code,title,cur){
  openModal(`${modalX()}<h2>调整《${esc(title)}》的书型</h2>
    <div class="note warn">保存后会按新书型重新整理部分内容。涉及已有引用时，请核对更新后的内容。</div>
    <div class="field" style="margin-top:12px"><label for="retypeProto">参考书型</label><select id="retypeProto">${PROTO_ORDER.map(p=>`<option value="${p}" ${p===cur?'selected':''}>${PROTO[p]}</option>`).join('')}</select></div>
    <div class="modal-actions"><button class="btn ghost" onclick="closeModal()">取消</button><button class="btn primary" onclick="doRetype('${esc(code)}')">保存并整理</button></div>`);
}
async function doRetype(code){
  const proto=document.getElementById('retypeProto').value;
  try{const d=await post('/api/books/retype',{code,prototype:proto});closeModal();toast('已创建改分类任务');go('job',d.job.id);}
  catch(e){toast(e.message,true);}
}
function openMeta(code,author,publisher){
  openModal(`${modalX()}<h2>编辑图书信息</h2>
    <div class="muted">只改作者 / 出版社，不动正文与知识资产。</div>
    <div class="formrow"><div class="field"><label>作者</label><input id="metaAuthor" value="${esc(author||'')}"></div><div class="field"><label>出版社</label><input id="metaPublisher" value="${esc(publisher||'')}"></div></div>
    <div class="modal-actions"><button class="btn ghost" onclick="closeModal()">取消</button><button class="btn primary" data-code="${esc(code)}" onclick="saveMeta(this.dataset.code)">保存</button></div>`);
}
async function saveMeta(code){
  const author=(document.getElementById('metaAuthor').value||'').trim(), publisher=(document.getElementById('metaPublisher').value||'').trim();
  try{delete state.bookCache[code];await post('/api/books/meta',{code,author,publisher});closeModal();toast('图书信息已保存');route();}catch(e){toast(e.message,true);}
}
async function confirmBook(code){
  try{delete state.bookCache[code];await post('/api/books/confirm',{code,confirmed:true});toast('已标为确认');route();}catch(e){toast(e.message,true);}
}

/* ---------------- 回收站 ---------------- */
async function renderTrash(v){
  const isCurrent=capturePageRequest(v);
  let items=state.trash||[];
  try{const d=await api('/api/trash');items=d.items||[];state.trash=items;}catch(e){}
  if(!isCurrent())return;v.innerHTML=`<div class="page-head"><div><div class="eyebrow">Platform / Trash</div><h1>回收站</h1><p>删除是软删除：底本与产物保留，可在保留期内恢复。</p></div></div>
    <section class="panel">${items.length?`<table class="table"><thead><tr><th>图书</th><th>编号</th><th>删除时间</th><th></th></tr></thead><tbody>${items.map(t=>`<tr><td>${esc(t.book)}</td><td>${esc(t.code)}</td><td>${esc((t.time||'').replace('T',' ').slice(0,16))}</td><td class="right"><button class="btn sm ghost" data-tid="${esc(t.id)}" onclick="restoreTrash(this.dataset.tid)">恢复</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">回收站是空的</div>'}</section>`;
}
async function restoreTrash(tid){
  try{const d=await post('/api/trash/restore',{trash_id:tid});toast('恢复任务已创建');go('job',d.job.id);}catch(e){toast(e.message,true);}
}

/* ---------------- 解析能力（真实保存） ---------------- */
async function renderHotspot(v,title){
  state.hotspot=state.hotspot||{items:[],platform:'',q:'',facts:'',analysis:null,books:[],msg:''};
  if(title){
    state.hotspot.title=title;
    v.innerHTML=`
      <div class="page-head"><div><div class="eyebrow">Applications / Hotspot</div><h1>${esc(title)}</h1>
        <p>四维拆解 + 图书匹配。匹配会摆出命中关键词、情绪、受众和风险。</p></div>
        <div class="head-actions"><button class="btn ghost" onclick="go('hotspot')">← 返回热点列表</button></div></div>
      <div id="hotMain">${loading('拆解并匹配')}</div>`;
    hotAnalyzeDetail(title,state.hotspot.facts||'');
    return;
  }
  v.innerHTML=`
    <div class="page-head"><div><div class="eyebrow">Applications / Hotspot</div><h1>热点营销</h1>
      <p>先搜热点，再进四维拆解和图书匹配。热点列表按平台筛，点一条进入详情。</p></div>
      <div class="head-actions"><button class="btn ghost" onclick="hotFetch()">抓取六平台</button></div></div>
    <section class="panel"><div class="panel-body">
      <div class="hot-search"><input id="hotSearch" placeholder="搜热点 / 话题，如：APEC、开学季、廉洁家风" value="${esc(state.hotspot.q||'')}" onkeydown="if(event.key==='Enter'){event.preventDefault();hotSearch();}"><button class="btn primary" onclick="hotSearch()">搜索热点</button><button class="btn ghost" onclick="hotStart()">拆解这个话题</button><span id="hotMsg" class="hot-msg">${esc(state.hotspot.msg||'')}</span></div>
    </div></section>
    <div id="hotSuggest">${hotSuggestHtml()}</div>
    <section class="panel"><div class="panel-head"><div><h2>热点列表</h2><div class="sub">点一条进入四维拆解；可按平台筛</div></div><span class="faint" id="hotCount">${(state.hotspot.items||[]).length} 条</span></div>
      <div class="panel-body"><div id="hotPlatforms" class="hot-platforms">${hotPlatformsHtml()}</div><div id="hotList" class="hot-grid">${hotListHtml()}</div></div></section>`;
  if(!(state.hotspot.items||[]).length) setTimeout(hotFetch,0);
}
const HOT_PLATFORMS=['今日头条','百度热搜','B站热门','微博热搜','抖音热点','知乎热榜'];
function hotPlatformsHtml(){
  const it=state.hotspot.items||[], cur=state.hotspot.platform||'';
  const cnt=p=>it.filter(x=>(x.sources||[]).some(s=>s.split('#')[0]===p)).length;
  return `<button class="chip ${!cur?'on':''}" onclick="hotSetPlatform('')">全部 ${it.length}</button>`+
    HOT_PLATFORMS.map(p=>{const n=cnt(p);return `<button class="chip ${cur===p?'on':''}" onclick="hotSetPlatform('${p}')" ${n?'':'disabled'}>${p} ${n}</button>`;}).join('');
}
function hotListHtml(){
  const all=state.hotspot.items||[], cur=state.hotspot.platform||'', q=(state.hotspot.q||'').toLowerCase();
  let it=cur?all.filter(x=>(x.sources||[]).some(s=>s.split('#')[0]===cur)):all;
  if(q) it=it.filter(x=>(x.title||'').toLowerCase().includes(q));
  if(!it.length) return '<div class="hot-empty">没有匹配的热点。换个词，或点“抓取六平台”重试。</div>';
  return it.map(x=>`<button class="hot-card" data-title="${esc(x.title)}" onclick="hotPick(this.dataset.title)">
    <b>${esc(x.title)}</b>
    <span>${esc((x.sources||[]).slice(0,2).join(' · '))}</span>
    ${(x.recs||[]).length?`<div class="hot-recs"><em>初筛</em>${(x.recs||[]).map(r=>`<span data-code="${esc(r.code)}" onclick="event.stopPropagation();go('book',this.dataset.code)" title="${esc(r.reason||'')}">${esc(r.title)} <b>${r.score}</b></span>`).join('')}</div>`:''}
  </button>`).join('');
}
async function hotSearch(){
  const el=document.getElementById('hotSearch'); if(!el)return;
  state.hotspot.q=el.value.trim();
  const all=state.hotspot.items||[], cur=state.hotspot.platform||'', q=(state.hotspot.q||'').toLowerCase();
  let n=(cur?all.filter(x=>(x.sources||[]).some(s=>s.split('#')[0]===cur)):all).filter(x=>!q||(x.title||'').toLowerCase().includes(q)).length;
  document.getElementById('hotCount').textContent=n+' 条';
  document.getElementById('hotList').innerHTML=hotListHtml();
  state.hotspot.suggest=[];
  if(state.hotspot.q){
    try{
      const d=await post('/api/hotspot/preview',{titles:[state.hotspot.q],limit:3});
      state.hotspot.suggest=((d.items||{})[state.hotspot.q])||[];
    }catch(e){}
  }
  document.getElementById('hotSuggest').innerHTML=hotSuggestHtml();
}
function hotSuggestHtml(){
  const q=state.hotspot.q||'', list=state.hotspot.suggest||[];
  if(!q) return '';
  return `<section class="panel hot-suggest"><div class="panel-head"><div><h2>“${esc(q)}”推荐图书</h2><div class="sub">关键词初筛；点“完整匹配”看四维拆解和 85 分门槛</div></div><button class="btn sm ghost" onclick="hotStart()">完整匹配 →</button></div><div class="panel-body">
    ${list.length?list.map(b=>`<div class="hot-rec-row"><b data-code="${esc(b.code)}" onclick="go('book',this.dataset.code)">${esc(b.title)}</b><span class="faint">${esc(b.reason||'')}</span><em>${b.score}</em></div>`).join(''):'<div class="empty">这个话题下没有明显匹配的图书。点“完整匹配”看四维拆解，或换更具体的词。</div>'}
  </div></section>`;
}
function hotStart(){
  const el=document.getElementById('hotSearch'); const t=el?el.value.trim():'';
  if(!t){toast('先输入热点或话题',true);return;}
  go('hotspot',t);
}
function hotSetPlatform(p){
  state.hotspot.platform=p||'';
  document.getElementById('hotPlatforms').innerHTML=hotPlatformsHtml();
  document.getElementById('hotList').innerHTML=hotListHtml();
  const all=state.hotspot.items||[], cur=state.hotspot.platform||'', q=(state.hotspot.q||'').toLowerCase();
  const n=(cur?all.filter(x=>(x.sources||[]).some(s=>s.split('#')[0]===cur)):all).filter(x=>!q||(x.title||'').toLowerCase().includes(q)).length;
  document.getElementById('hotCount').textContent=n+' 条';
}
function hotPick(t){ if(t) go('hotspot',t); }
function hotMainHtml(){
  const H=state.hotspot; const a=H.analysis;
  if(!a) return '';
  const books=H.books||[];
  return `<section class="panel hot-analysis"><div class="panel-head"><div><h2>四维拆解</h2><div class="sub">事情内核 / 情绪 / 受众 / 关联词 / 风险</div></div><span class="pill">${esc(a.风险等级||'无')}风险</span></div><div class="panel-body">
    <div class="hot-core generated-copy">${ManuscriptReader.build(a.事情内核||'',undefined,{frozen:true}).html}</div>
    <div class="hot-tagblock">
      <div class="hot-tagrow"><span class="hot-taglabel">情绪</span><div class="hot-tagitems">${(a.情绪内核词||[]).length?(a.情绪内核词||[]).map(x=>`<span class="kwchip">${ManuscriptReader.inline(x,undefined,{frozen:true})}</span>`).join(''):'<span class="faint">—</span>'}</div></div>
      <div class="hot-tagrow"><span class="hot-taglabel">受众</span><div class="hot-tagitems">${(a.受众画像词||[]).length?(a.受众画像词||[]).map(x=>`<span class="personchip">${ManuscriptReader.inline(x,undefined,{frozen:true})}</span>`).join(''):'<span class="faint">—</span>'}</div></div>
      <div class="hot-tagrow"><span class="hot-taglabel">关联词</span><div class="hot-tagitems">${(a.可关联关键词||[]).length?(a.可关联关键词||[]).map(x=>`<span class="hot-kwchip">${ManuscriptReader.inline(x,undefined,{frozen:true})}</span>`).join(''):'<span class="faint">—</span>'}</div></div>
    </div>
    <div class="hot-taglegend">情绪、受众只能从固定词表里挑；关联词由模型按热点生成，用于匹配书名/简介/卖点。</div>
    ${a.借势建议?`<div class="hot-advice"><b>借势建议</b><div class="generated-copy">${ManuscriptReader.build(a.借势建议,undefined,{frozen:true}).html}</div></div>`:''}
  </div></section>
  <section class="panel"><div class="panel-head"><div><h2>匹配图书</h2><div class="sub">只列总分 ≥85 的合适图书；分数构成：关键词 45 + 情绪 20 + 受众 20 + 安全 15</div></div><span class="faint">${books.filter(b=>(b.score||0)>=85).length} 本合适</span></div><div class="panel-body">
    ${books.filter(b=>(b.score||0)>=85).length?books.filter(b=>(b.score||0)>=85).map(b=>`<div class="hot-book">
      <div class="hot-head"><b>${esc(b.title)}</b><span class="hot-score">${b.score}<em>/100</em></span></div>
      <div class="faint">${esc(b.author||'')}${b.publisher?' · '+esc(b.publisher):''} · ${b.level==='ok'?'建议借势':b.level==='mid'?'有条件':'不建议'}</div>
      <div class="hot-breakdown"><span>关键词 <b>${b.keyword||0}</b>/45</span><span>情绪 <b>${b.emotion||0}</b>/20</span><span>受众 <b>${b.audience||0}</b>/20</span><span>安全 <b>${b.safety||0}</b>/15</span></div>
      <div class="hot-reason"><span>理由</span><div class="kwline">${(b.reasons||[]).map(x=>`<span class="chip">${ManuscriptReader.inline(x,undefined,{frozen:true})}</span>`).join('')}</div></div>
      <div class="hot-gap"><span>缺陷</span><div>${(b.gaps||[]).length?esc(b.gaps.join('；')):'未发现明显缺口（关键词、情绪、受众均命中）'}</div></div>
      <div class="faint" style="margin-top:4px">${esc(b.next||'')}</div>
      <div class="modal-actions" style="justify-content:flex-start;margin-top:8px"><button class="btn sm" onclick="go('book','${esc(b.code)}')">打开书</button><button class="btn sm ghost" onclick="go('marketing','${esc(b.code)}')">看营销资料</button>${workflowContext()?`<button class="btn sm primary" data-pick="${esc('pick:'+workflowContext().id+':'+b.code)}" onclick="go('content',this.dataset.pick)">为当前项目选材</button>`:''}</div>
    </div>`).join(''):`<div class="empty"><b>无合适图书</b><div style="margin-top:6px">当前最高 ${books.length?books[0].score+' 分':'—'}，未达到 85 分。建议换一个更贴近这本书的热点，或补更具体的热点事实后重试。</div></div>`}
  </div></section>`;
}
async function hotFetch(){
  const H=state.hotspot=state.hotspot||{}; H.msg='抓取中…'; const m=document.getElementById('hotMsg'); if(m){m.textContent=H.msg;m.className='hot-msg';}
  try{
    const d=await post('/api/hotspot/fetch',{limit:12});
    H.items=d.items||[];
    try{
      const pv=await post('/api/hotspot/preview',{titles:H.items.map(x=>x.title),limit:2});
      H.items.forEach(x=>{x.recs=((pv.items||{})[x.title])||[];});
    }catch(e){}
    const failed=Object.keys(d.errors||{});
    H.msg=failed.length?('已抓取；'+failed.length+' 个平台暂不可用：'+failed.join('、')):'抓取完成';
    document.getElementById('hotPlatforms').innerHTML=hotPlatformsHtml();
    document.getElementById('hotList').innerHTML=hotListHtml();
    document.getElementById('hotCount').textContent=(H.items||[]).length+' 条';
    if(m){m.textContent=H.msg;m.className='hot-msg'+(failed.length?' warn':'');}
  }catch(e){H.msg='抓取失败：'+e.message;if(m){m.textContent=H.msg;m.className='hot-msg err';}}
}
async function hotAnalyzeDetail(title,facts){
  const H=state.hotspot=state.hotspot||{}; H.title=title; H.analysis=null; H.books=[];
  const host=document.getElementById('hotMain'); if(host)host.innerHTML=loading('拆解并匹配');
  try{
    const a=await post('/api/hotspot/analyze',{title,facts:facts||''});
    H.analysis=a.analysis; if(host)host.innerHTML=hotMainHtml();
    const d=await post('/api/hotspot/match',{analysis:H.analysis,limit:10});
    H.books=d.books||[]; if(host)host.innerHTML=hotMainHtml();
  }catch(e){if(host)host.innerHTML=`<div class="panel"><div class="empty">失败：${esc(e.message)}</div></div>`;toast('拆解失败：'+e.message,true);}
}
async function renderSettings(v){
  const isCurrent=capturePageRequest(v);
  if(!isCurrent())return;v.innerHTML=loading('加载能力配置');
  try{ if(!state.settings) state.settings=await api('/api/settings'); }catch(e){if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">加载失败：${esc(e.message)}</div></div>`;return;}
  const d=state.settings, labels=arr(d.labels), enabled=Array.isArray(d.content_labels)?d.content_labels:labels;
  if(!isCurrent())return;v.innerHTML=`<div class="page-head"><div><h1>解析设置</h1><p>选择整理图书时要检查哪些内容。找到对应依据才会产生标签。</p></div>
    <div class="head-actions"><button type="button" class="btn ghost" onclick="resetSettings(this)">恢复默认</button><button type="button" class="btn primary" onclick="saveSettings(this)">保存设置</button></div></div>
    <section class="panel"><div class="panel-head"><h2>检查哪些内容</h2></div><div class="panel-body">
      <div class="tag-setting-grid">${labels.map(label=>`<label><input type="checkbox" name="contentLabel" value="${esc(label)}"${enabled.includes(label)?' checked':''}><span>${esc(label)}</span></label>`).join('')}</div>
      <p class="muted">设置在之后上传或重新整理图书时生效。</p>
    </div></section>`;
}
async function saveSettings(button){
  const v=document.getElementById('view'),isCurrent=capturePageRequest(v);
  const content_labels=Array.from(v.querySelectorAll('input[name="contentLabel"]:checked'),cb=>cb.value);
  if(button)button.disabled=true;
  try{
    const d=await post('/api/settings',{content_labels});state.settings=d.settings;
    if(isCurrent()){toast('设置已保存');await renderSettings(v);}
  }catch(e){if(isCurrent())toast(e.message,true);}finally{if(button)button.disabled=false;}
}
async function resetSettings(button){
  if(!confirm('恢复默认检查项？设置在之后整理图书时生效。'))return;
  const v=document.getElementById('view'),isCurrent=capturePageRequest(v);
  if(button)button.disabled=true;
  try{
    const d=await post('/api/settings/reset',{});state.settings=d.settings;
    if(isCurrent()){toast('已恢复默认设置');await renderSettings(v);}
  }catch(e){if(isCurrent())toast(e.message,true);}finally{if(button)button.disabled=false;}
}

/* ================= 解析报告（弹窗） ================= */
// 弹窗与独立页面均读取 /api/book/report 的本书解析记录和产物
const ENT_CN={country:'国家',province:'省份',region:'区域/大区',city:'城市',district:'区县',landmark:'道路/地标',nature:'自然地理',fossil:'化石/古人类',person:'人物',concept:'概念',org:'机构',object:'器物',animal:'动物',plant:'植物',taxon:'科属',award:'奖项',event:'事件',dynasty:'朝代',family:'家族',alias:'别名'};
function reportPageIssues(r){
  const issues=r.source_page_issues;
  if(!issues||typeof issues!=='object'||Array.isArray(issues))return {summary:'尚无逐页记录',html:'<p class="muted">此书尚无逐页解析记录，暂不能列出待查看的页面。</p>'};
  const groups=[
    ['failed','文字识别失败','查看原页，确认是否有正文需要补录或重新识别。',true],
    ['unavailable','未能启用文字识别','此页未完成文字识别，请查看原页确认缺失内容。',true],
    ['review','识别文字待核对','识别结果不完整或不够可靠，请核对原页中的文字、数字和标点。',true],
    ['layout_review','版面顺序待核对','检查竖排、分栏或特殊版式的阅读顺序，确认正文没有错位。',true],
    ['no_text','未取得可用正文','页面有图像或标记，但未取得可用正文；查看原页，区分插图与待补录文字。',true],
    ['non_body','已分开的非正文页','卷末丛书书目等内容已和正文分开。',false],
    ['blank','已确认空白页','这些页面显示为空白。',false],
  ];
  const pending=new Set();
  const blocks=groups.map(([key,title,hint,needsReview])=>{
    const pages=[...new Set((Array.isArray(issues[key])?issues[key]:[]).filter(page=>Number.isInteger(page)&&page>0))].sort((a,b)=>a-b);
    if(!pages.length)return '';
    if(needsReview)pages.forEach(page=>pending.add(page));
    const links=pages.map(page=>r.has_original_pdf&&r.code?
      `<a class="pill p2" href="/api/book/source?${esc(new URLSearchParams({code:r.code}).toString())}#page=${page}" target="_blank" rel="noopener" aria-label="打开 PDF 第 ${page} 页">第 ${page} 页 ↗</a>`:
      `<span class="pill">第 ${page} 页</span>`).join('');
    return `<details class="rp-page-group" data-page-issue="${key}"${needsReview?' open':''}><summary><b>${title}</b><span>${num(pages.length)} 页</span></summary><p class="faint">${hint}</p><div class="rp-page-links">${links}</div></details>`;
  }).filter(Boolean).join('');
  const total=Number.isInteger(r.source_pages)&&r.source_pages>0?`共 ${num(r.source_pages)} 页 · `:'';
  const summary=total+(pending.size?`${num(pending.size)} 页需查看`:'未记录待处理页');
  const note=blocks?`<p class="faint">以下页码按 PDF 阅读器中的页序计算，可能与书上印刷页码不同。${r.has_original_pdf?'可点击页码查看原页。':'原始 PDF 暂不可用，可按页码核对底本。'}</p>`:'';
  return {summary,html:(pending.size?'':'<p class="muted">本次解析没有记录待处理的页面。</p>')+note+blocks};
}
// 报告正文（弹窗与独立页面共用同一份，避免两处数字不一样）
function reportHtml(r){
  const sec=(no,title,right,body)=>`<div class="rp-sec"><div class="rp-h"><b>${no} ${title}</b><span>${right||''}</span></div><div class="rp-b">${body}</div></div>`;
  const okList=arr=>arr.length?arr.map(x=>`<span class="rp-ok">✓ ${esc(x)}</span>`).join(''):'<span class="faint">—</span>';
  const missList=arr=>arr.length?arr.map(x=>`<span class="rp-miss">⚠ ${esc(x)}</span>`).join(''):'';
  const idn=r.identity, str=r.structure, ct=r.content, us=r.usage, tr=r.trust;
  const pages=reportPageIssues(r);
  const checked=x=>`${x.found.length}/${x.total} 项已找到${x.missing?.length?' · '+x.missing.length+' 项未找到':''}${Number(x.failed)>0?' · '+num(x.failed)+' 项处理失败':''}`;
  const entRows=Object.keys(ct.entity_counts||{}).filter(k=>ct.entity_counts[k]).sort((a,b)=>ct.entity_counts[b]-ct.entity_counts[a])
    .map(k=>`<span class="pill">${ENT_CN[k]||k} ${num(ct.entity_counts[k])}</span>`).join('');
  return `
    <div class="rp-head">
      <div><div class="eyebrow">${esc(r.code)} · 解析报告</div><h2>${esc(r.book)}</h2>
        <div class="faint">参考书型 ${esc(PROTO[tr.prototype]||'待分类')}${tr.pending?' · 待核对':''}</div></div>
    </div>
    ${sec(1,'页面检查',pages.summary,pages.html)}
    ${sec(2,'出版信息',checked(idn),
      okList(idn.found.map(x=>x.name))+(idn.missing.length?`<div style="margin-top:8px">${missList(idn.missing.map(x=>x.name))}</div>`:'')
      +(idn.note?`<div class="faint" style="margin-top:8px">${esc(idn.note)}</div>`:''))}
    ${sec(3,'章节与页面',checked(str),
      okList(str.found)+(str.missing.length?`<div style="margin-top:8px">${missList(str.missing)}</div>`:'')
      +(str.note?`<div class="faint" style="margin-top:8px">${esc(str.note)}</div>`:''))}
    ${sec(4,'已整理的条目',`${num(ct.total)} 项`,
      (ct.total?`<div class="badges" style="margin:0 0 10px">${Object.keys(ct.by_type).map(k=>`<span class="pill">${esc(k)} ${num(ct.by_type[k])}</span>`).join('')}</div>`
              :'<p class="muted">本次还没有整理出条目。</p>')
      +`<div style="margin-top:6px"><span class="faint">名称索引 ${num(ct.entity_total)} 个</span> ${entRows}</div>`)}
    ${sec(5,'可供核对的内容','',`<span class="pill">${us.has_understanding?`可引用句 ${num(us.quotes)}`:'可引用句 待整理'}</span><span class="pill">${us.has_understanding?`议题 ${num(us.themes)}`:'议题 待整理'}</span><span class="pill">${us.marketing?`营销草稿 ${num(us.marketing)} 条待核对`:'营销草稿 待整理'}</span>`)}
    ${sec(6,'出处检查',tr.pass_rate!=null?`本次核验通过 ${Math.round(tr.pass_rate*100)}%`:'',
      `<p class="muted">${tr.pass_rate==null?'暂无出处核验记录。':'可到具体内容查看对应原文。'}</p>`)}`;
}
async function renderReport(v,code){
  const isCurrent=capturePageRequest(v);
  if(!isCurrent())return;v.innerHTML=loading('生成解析报告');
  let r=null;
  try{ r=(await jget('/api/book/report?code='+encodeURIComponent(code))).report; }
  catch(e){ if(!isCurrent())return;v.innerHTML=`<div class="panel"><div class="empty">报告生成失败：${esc(e.message)}</div></div>`; return; }
  if(!isCurrent())return;crumb(`<span>数据资产</span><span>/</span><a onclick="go('library')">来源图书</a><span>/</span><b>${esc(clip(r.book,16))}</b><span>/</span><b>解析报告</b>`);
  if(!isCurrent())return;v.innerHTML=`
    <div class="page-head"><div><h1>解析报告</h1>
      <p>查看这本书已整理的内容、未找到的信息和出处检查结果。</p></div>
      <div class="head-actions">
        ${window.MarketingReview?.returnLink(code)||''}
        <button class="btn ghost" onclick="exportReport('${esc(code)}')">下载报告数据</button>
        <button class="btn primary" onclick="go('book','${esc(code)}')">打开这本书</button></div></div>
    <section class="panel"><div class="panel-body">${reportHtml(r)}</div></section>`;
}
async function openReport(code){
  let r;
  try{ r=(await jget('/api/book/report?code='+encodeURIComponent(code))).report; }
  catch(e){ toast('报告加载失败：'+e.message,true); return; }
  const html=reportHtml(r);
  openModal(html,true);
}
function exportReport(code){
  jget('/api/book/report?code='+encodeURIComponent(code)).then(d=>{
    const txt=JSON.stringify(d.report,null,2);
    const blob=new Blob([txt],{type:'application/json;charset=utf-8'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
    a.download=(d.report.book||code)+'_解析报告.json';
    document.body.appendChild(a); a.click();
    setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},400);
    toast('解析报告已导出');
  }).catch(e=>toast('导出失败：'+e.message,true));
}
