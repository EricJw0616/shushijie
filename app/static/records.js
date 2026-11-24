/* One compact record per project; full content lives in the project workspace. */
'use strict';
window.ProjectRecords=(function(){
  const R={q:'',kind:'',scene:'',offset:0,limit:20,total:0,request:0,host:null,initialized:false,views:{}};
  const STORAGE='bookworld.work-projects';
  const FUNCTIONS={
    editorial:{title:'选题策划',eyebrow:'EDITORIAL PLANNING',description:'供选题与策划编辑跨书查找材料，梳理选题方向并形成目录讨论稿，支持选题会评审；审核交付后记录采用与修改反馈。',history:'选题项目记录'},
    marketing:{title:'我的营销项目',eyebrow:'MARKETING PROJECTS',description:'继续制作，或查看已有内容。',history:'全部项目'}
  };
  function viewKey(kind){return kind||'all';}
  function normalizedKind(kind){return kind==='editorial'||kind==='marketing'?kind:'';}
  function filterState(value){return {q:value&&typeof value.q==='string'?value.q:'',scene:value&&typeof value.scene==='string'?value.scene:'',offset:Math.max(0,Math.floor(Number(value&&value.offset)||0))};}
  function saved(){try{const v=JSON.parse(sessionStorage.getItem(STORAGE)||'null');return v&&typeof v==='object'?v:null;}catch(_){return null;}}
  function restoreViews(){const previous=saved();if(!previous)return;['all','editorial','marketing'].forEach(function(key){if(previous.views&&previous.views[key])R.views[key]=filterState(previous.views[key]);});const key=viewKey(normalizedKind(previous.kind));if(!R.views[key])R.views[key]=filterState(previous);}
  function remember(){R.views[viewKey(R.kind)]={q:R.q,scene:R.scene,offset:R.offset};try{sessionStorage.setItem(STORAGE,JSON.stringify({kind:R.kind,q:R.q,scene:R.scene,offset:R.offset,views:R.views}));}catch(_){}}
  function listUrl(kind){return '#/records'+(kind?'/'+kind:'');}
  function returnUrl(kind){const previous=R.initialized?R:saved();return listUrl(kind===undefined?normalizedKind(previous&&previous.kind):normalizedKind(kind));}
  function returnToList(kind){const url=returnUrl(kind);go('records',url.split('/')[2]||'');}
  function syncLocation(){const hash=listUrl(R.kind);if(location.hash!==hash){history.replaceState(null,'',hash);if(typeof state!=='undefined'){state.lastHash=hash;state.curView={view:'records',arg:R.kind};}}remember();if(window.ProjectNav&&typeof ProjectNav.sync==='function')ProjectNav.sync();}
  const e=esc;
  function count(value){return Math.max(0,Number(value)||0);}
  function label(kind){return kind==='marketing'?'营销策划':'选题策划';}
  function sceneLabel(scene){return scene==='planning'?'营销整体方案':MarketingScenes.label(scene);}
  function date(value){return String(value||'').replace('T',' ').slice(0,16)||'尚无记录';}
  function active(host,request){return request===R.request&&R.host===host&&document.getElementById('projectRecords')===host;}
  function stage(p){
    const r=p.latest_run;
    if(R.kind==='marketing'){
      if(r&&['queued','running'].includes(r.status))return {tone:'running',text:r.capability==='recommend'?'正在查找素材':r.capability==='video_prompts'?'正在生成提示词':'正在生成内容',detail:''};
      if(r&&r.status==='failed')return {tone:'error',text:'需要重试',detail:''};
      if(r&&r.result_status==='insufficient_materials')return {tone:'review',text:'需要补充素材',detail:''};
      if(p.has_draft)return {tone:'ready',text:'已有内容',detail:''};
      if(count(p.adopted_count))return {tone:'review',text:'可以生成内容',detail:''};
      return {tone:'empty',text:'待选素材',detail:''};
    }
    if(r&&r.status==='failed')return {tone:'error',text:'最近生成失败',detail:p.has_draft?'已有稿件保留':'进入项目查看原因'};
    if(r&&['queued','running'].includes(r.status))return {tone:'running',text:r.status==='queued'?'生成任务排队中':'正在生成',detail:r.capability==='recommend'?'发现可用材料':r.capability==='video_prompts'?'生成提示词':'形成讨论稿'};
    if(r&&r.status==='done'&&r.result_status==='insufficient_materials')return {tone:'review',text:'未找到匹配材料',detail:'调整主题或图书范围'};
    if(r&&r.status==='done')return {tone:'ready',text:r.capability==='recommend'?'材料推荐已完成':r.capability==='video_prompts'?'已有提示词记录':'讨论稿已生成',detail:'查看项目中的具体结果'};
    if(r&&r.status==='partial')return {tone:'review',text:'生成部分完成',detail:'进入项目查看结果'};
    if(p.has_draft)return {tone:'ready',text:'已有项目稿件',detail:'查看内容与审核状态'};
    if(count(p.export_count))return {tone:'ready',text:'已有导出记录',detail:'查看历史交付版本'};
    if(count(p.adopted_count))return {tone:'review',text:'已选用材料',detail:count(p.adopted_count)+' 条材料已采用'};
    if(count(p.item_count))return {tone:'review',text:'材料待选择',detail:count(p.item_count)+' 条材料待继续处理'};
    return {tone:'empty',text:'尚未产出',detail:'填写任务，开始选择材料'};
  }
  function row(p){
    const s=stage(p),b=p.brief||{},view=p.kind==='marketing'?'campaigns':'projects';
    const scene=R.kind==='marketing'?R.scene:'',section=scene&&scene!=='planning'&&p.has_draft?'results':'',url='#/'+view+'/'+encodeURIComponent(p.id)+(section?'/'+section:''),goal=b.goal||b.topic||'尚未填写工作目标';
    const feedback={used:'已记录使用',not_used:'本次未使用',needs_revision:'反馈待修改'}[p.last_outcome]||'';
    return '<a class="project-record-row" href="'+e(url)+'" data-id="'+e(p.id)+'" data-kind="'+e(p.kind)+'" data-scene="'+e(scene)+'" data-section="'+section+'" onclick="return ProjectRecords.open(event,this)">'+
      '<span class="record-project"><span class="record-project-title">'+e(p.title||'未命名项目')+'</span>'+(p.kind==='marketing'?'<span class="record-scene-tags">'+(p.marketing_scenes||[]).map(x=>'<span>'+e(sceneLabel(x))+'</span>').join('')+'</span>':'')+'<span class="record-project-goal" title="'+e(goal)+'">'+e(goal)+'</span></span>'+
      (R.kind?'':'<span class="record-kind '+(p.kind==='marketing'?'marketing':'editorial')+'">'+label(p.kind)+'</span>')+
      '<span class="record-stage"><span class="record-stage-label record-tone-'+s.tone+'"><i aria-hidden="true"></i>'+e(s.text)+'</span><small>'+e(s.detail)+'</small></span>'+
      (R.kind==='marketing'?'':'<span class="record-counts"><span>'+count(p.run_count)+' 次生成 · '+count(p.export_count)+' 次导出</span><small>'+count(p.feedback_count)+' 条反馈'+(feedback?' · '+e(feedback):'')+'</small></span>')+
      '<time class="record-date" datetime="'+e(p.last_activity_at||'')+'">'+e(date(p.last_activity_at))+'</time>'+
      '<span class="record-open">'+(R.kind==='marketing'?'进入':'查看项目')+' <span aria-hidden="true">↗</span></span></a>';
  }
  function createButton(kind,style){return kind==='marketing'?'<a class="btn '+(style||'primary')+'" href="#/campaigns">＋ 新建营销项目</a>':'<button class="btn '+(style||'primary')+'" type="button" data-kind="'+kind+'" onclick="Studio.create(this)">＋ 新建'+label(kind)+'</button>';}
  function empty(filtered){
    const feature=FUNCTIONS[R.kind],scene=R.kind==='marketing'?R.scene:'',sceneTitle=scene?sceneLabel(scene):'';
    const title=filtered?'没有符合搜索条件的项目':scene?'还没有'+sceneTitle+'项目':feature?'还没有'+(R.kind==='marketing'?'营销':feature.title)+'项目':'还没有工作项目';
    const message=filtered?'调整项目名称或主题，继续查找记录。':scene==='planning'?'选择图书和推广目标，梳理卖点、受众与内容安排。':scene?'从这个场景开始，选择图书和材料，制作对应内容。':feature?(R.kind==='marketing'?'可以先做营销整体方案，也可以直接制作公众号、短视频等内容。':'新建选题策划，从多本图书中收集材料，形成选题方向与目录讨论稿。'):'创建选题策划或营销策划，材料、稿件、交付与反馈会保存在同一个项目中。';
    const action=filtered?'<button class="btn ghost" type="button" onclick="ProjectRecords.clear()">清除搜索</button>':scene?'<a class="btn primary" href="#/campaigns/new/'+encodeURIComponent(scene)+'">＋ '+(scene==='planning'?'创建营销整体方案':'制作'+e(sceneTitle))+'</a>':createButton(R.kind||'editorial');
    return '<div class="records-empty"><span class="records-empty-mark" aria-hidden="true">◇</span><h2>'+e(title)+'</h2><p>'+e(message)+'</p>'+action+'</div>';
  }

  function filterTabs(){return ['','editorial','marketing'].map(function(kind){return '<button type="button" class="'+(R.kind===kind?'on':'')+'" data-kind="'+kind+'" aria-pressed="'+(R.kind===kind)+'" onclick="ProjectRecords.filter(this)">'+(kind?label(kind):'全部项目')+'<span data-record-count="'+(kind||'total')+'"></span></button>';}).join('');}
  function sceneFilters(){
    return '<div class="marketing-scene-filters studio-tabs" role="group" aria-label="按方案或场景查看项目">'+[['','全部'],['planning',sceneLabel('planning')],...Object.entries(MarketingScenes.scenes).map(([k,v])=>[k,v.title])].map(([key,title])=>'<button type="button" class="'+(R.scene===key?'on':'')+'" data-scene="'+e(key)+'" aria-pressed="'+(R.scene===key)+'" onclick="ProjectRecords.scene(this)">'+e(title)+'</button>').join('')+'</div>';
  }
  function shell(v){
    const feature=FUNCTIONS[R.kind];
    crumb(R.kind==='marketing'?'<a href="#/campaigns">营销创作</a><span>/</span><b>我的营销项目</b>':feature?'<a href="#/records">工作项目</a><span>/</span><b>'+feature.title+'</b>':'<span>工作项目</span>');v.classList.add('studio-view');
    v.innerHTML='<section id="projectRecords" class="project-records'+(feature?' records-function':'')+(R.kind==='marketing'?' marketing-project-records':'')+'"><div class="page-head"><div><div class="eyebrow">'+(feature?feature.eyebrow:'WORK PROJECTS')+'</div><h1>'+(feature?feature.title:'工作项目')+'</h1><p>'+(feature?feature.description:'新建任务、继续策划、查看交付与反馈。')+'</p></div><div class="head-actions">'+(feature?createButton(R.kind):createButton('editorial')+createButton('marketing','ghost'))+'</div></div>'+
      '<div class="records-panel"><div class="records-toolbar">'+(feature?'<div class="records-function-history"><h2>'+(R.kind==='marketing'?'项目列表':feature.history+' <span data-record-count="'+R.kind+'"></span>')+'</h2>'+(R.kind==='marketing'?'':'<p>继续进行中的策划，或查看已完成项目的交付与反馈。</p>')+'</div>':'<div class="records-filters" role="group" aria-label="项目类型">'+filterTabs()+'</div>')+'<form class="records-search" onsubmit="event.preventDefault();ProjectRecords.search(this)"><label class="records-search-field"><svg class="icon" aria-hidden="true"><use href="#i-search"></use></svg><input type="search" name="q" value="'+e(R.q)+'" placeholder="搜索项目名称或主题" aria-label="搜索项目名称或主题"></label><button class="btn" type="submit">搜索</button></form></div>'+(R.kind==='marketing'?sceneFilters():'')+
      '<div class="records-caption"><p id="recordTotal" aria-live="polite">正在读取项目记录…</p><div>'+(R.q?'<button class="btn sm ghost" type="button" onclick="ProjectRecords.clear()">清除搜索</button>':'<span>最近活动在前</span>')+'<button class="btn sm ghost" type="button" onclick="ProjectRecords.refresh()">刷新</button></div></div><div id="recordResults" aria-busy="true">'+loading('正在加载项目记录')+'</div></div></section>';
    R.host=document.getElementById('projectRecords');return R.host;
  }
  async function load(host){
    const request=++R.request,results=host.querySelector('#recordResults');results.setAttribute('aria-busy','true');
    try{
      const params=new URLSearchParams({q:R.q,kind:R.kind,scene:R.kind==='marketing'?R.scene:'',limit:R.limit,offset:R.offset});
      const d=await jget('/api/project-records?'+params);
      if(!active(host,request))return;
      if(d.ok===false)throw new Error(d.error||'工作项目暂时不可用');
      const items=Array.isArray(d.items)?d.items:[];R.total=count(d.total);R.limit=count(d.limit)||20;R.offset=R.total?count(d.offset):0;remember();
      if(!items.length&&R.offset>0&&R.total>0){R.offset=Math.floor((R.total-1)/R.limit)*R.limit;return load(host);}
      host.querySelector('#recordTotal').textContent=R.total+' 个'+(R.kind==='marketing'?'营销':R.kind?label(R.kind):'')+'项目'+(R.q?'符合当前搜索':R.kind==='marketing'?'':'，每个项目保留一条入口');
      if(d.counts)host.querySelectorAll('[data-record-count]').forEach(function(n){n.textContent=count(d.counts[n.dataset.recordCount]);});
      results.innerHTML=items.length?'<div class="records-column-head" aria-hidden="true"><span>'+(R.kind==='marketing'?'项目':'项目 / 工作目标')+'</span>'+(R.kind?'':'<span>类型</span>')+'<span>'+(R.kind==='marketing'?'当前进度':'最近产出')+'</span>'+(R.kind==='marketing'?'':'<span>记录数量</span>')+'<span>最近活动</span><span></span></div><div class="records-list" aria-label="项目列表">'+items.map(row).join('')+'</div>'+(R.kind==='marketing'&&R.total<=R.limit?'':'<div class="records-pagination"><span>第 '+(Math.floor(R.offset/R.limit)+1)+' / '+Math.max(1,Math.ceil(R.total/R.limit))+' 页 · 共 '+R.total+' 个项目</span><div><button class="btn sm ghost" type="button" data-step="-1" onclick="ProjectRecords.page(this)"'+(R.offset===0?' disabled':'')+'>上一页</button><button class="btn sm ghost" type="button" data-step="1" onclick="ProjectRecords.page(this)"'+(R.offset+R.limit>=R.total?' disabled':'')+'>下一页</button></div></div>'):empty(!!R.q);
      results.setAttribute('aria-busy','false');
    }catch(err){
      if(!active(host,request))return;
      host.querySelector('#recordTotal').textContent='工作项目加载失败';
      results.innerHTML='<div class="records-empty" role="alert"><h2>暂时无法加载记录</h2><p>'+e(err.message)+'</p><button class="btn primary" type="button" onclick="ProjectRecords.refresh()">重新加载</button>'+(R.q?'<button class="btn ghost" type="button" onclick="ProjectRecords.clear()">清除搜索</button>':'')+'</div>';
      results.setAttribute('aria-busy','false');
    }
  }
  async function render(v,arg){
    if(R.initialized)remember();else restoreViews();
    const kind=normalizedKind(arg),previous=filterState(R.views[viewKey(kind)]);
    R.q=previous.q;R.scene=kind==='marketing'?previous.scene:'';R.offset=previous.offset;
    R.kind=kind;R.initialized=true;remember();const host=shell(v);await load(host);
  }
  function rebuild(){const host=R.host;if(!host||document.getElementById('projectRecords')!==host)return;const v=host.parentNode;syncLocation();load(shell(v));}
  function search(form){R.q=String(new FormData(form).get('q')||'').trim();R.offset=0;rebuild();}
  function filter(el){const input=R.host&&R.host.querySelector('[name=q]');if(input)R.q=input.value.trim();remember();R.kind=normalizedKind(el.dataset.kind);R.scene='';R.offset=0;rebuild();}
  function scene(el){R.scene=el.dataset.scene||'';R.offset=0;rebuild();}
  function clear(){R.q='';R.offset=0;rebuild();}
  function page(el){const next=R.offset+Number(el.dataset.step)*R.limit;if(next<0||next>=R.total)return;R.offset=next;rebuild();R.host?.scrollIntoView({behavior:'instant',block:'start'});}
  function refresh(){if(R.host&&document.getElementById('projectRecords')===R.host)load(R.host);}
  function open(event,el){if(event.ctrlKey||event.metaKey||event.shiftKey||event.altKey||event.button>0)return true;event.preventDefault();const scene=el.dataset.scene;if(scene&&scene!=='planning')try{sessionStorage.setItem('bookworld.draft-scene:'+el.dataset.id,scene);}catch(_){}go(el.dataset.kind==='marketing'?'campaigns':'projects',el.dataset.id,el.dataset.section||'');return false;}
  return {render,search,filter,scene,clear,page,refresh,open,returnUrl,returnToList};
})();
