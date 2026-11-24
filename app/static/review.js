/* Review is driven by material selected for a publishing task. */
'use strict';
window.ReviewHub = (function () {
  const states = {approved:'内容已确认',review:'待核对',rejected:'已停用',missing:'来源已缺失'};
  const ROUND_KEY='bookworld.review-round',MAX_PROJECTS=60,MAX_ASSETS=3000;
  let round=readRound(),queueProjects=new Map(),renderEpoch=0;
  function ids(values,limit,project){return [...new Set((Array.isArray(values)?values:[]).filter(function(id){return typeof id==='string'&&id.length>0&&id.length<300&&(!project||/^prj-[a-f0-9]{16}$/.test(id));}))].slice(-limit);}
  function emptyRound(){return {projectIds:[],confirmedProjectIds:[],pendingAssetIds:[]};}
  function readRound(){
    try{const saved=JSON.parse(sessionStorage.getItem(ROUND_KEY)||'null');if(saved&&typeof saved==='object')return {projectIds:ids(saved.projectIds,MAX_PROJECTS,true),confirmedProjectIds:ids(saved.confirmedProjectIds,MAX_PROJECTS,true),pendingAssetIds:ids(saved.pendingAssetIds,MAX_ASSETS,false)};}catch(_){}
    return emptyRound();
  }
  function saveRound(){try{if(round.projectIds.length)sessionStorage.setItem(ROUND_KEY,JSON.stringify(round));else sessionStorage.removeItem(ROUND_KEY);}catch(_){} }
  function rememberQueue(items){
    queueProjects=new Map();
    if(items.length){
      // A new queue after a completed round starts a new session of work.
      if(!round.pendingAssetIds.length)round=emptyRound();
      items.forEach(function(a){queueProjects.set(a.asset_id,ids((a.projects||[]).map(function(p){return p.id;}),MAX_PROJECTS,true));});
      round.projectIds=ids(round.projectIds.concat(...queueProjects.values()),MAX_PROJECTS,true);
      round.pendingAssetIds=ids(items.map(function(a){return a.asset_id;}),MAX_ASSETS,false);
    }else{
      round.pendingAssetIds=[];
      if(!round.confirmedProjectIds.length)round=emptyRound();
    }
    saveRound();
  }
  function noteReviewed(assetId,status){
    const projects=queueProjects.get(assetId);
    if(status!=='approved'||!projects||!projects.length)return;
    round.confirmedProjectIds=ids(round.confirmedProjectIds.concat(projects),MAX_PROJECTS,true);
    saveRound();
  }
  function finishRound(){round=emptyRound();queueProjects=new Map();saveRound();reload();}
  function stillHere(v,epoch){const p=parse();return epoch===renderEpoch&&document.getElementById('view')===v&&p.view==='editor'&&!p.arg;}
  function button(label, fn, data, style) {
    const attrs = Object.entries(data || {}).map(function(x){return ' data-'+x[0]+'="'+esc(x[1])+'"';}).join('');
    return '<button type="button" class="btn '+(style||'ghost')+'"'+attrs+' onclick="ReviewHub.'+fn+'(this)">'+label+'</button>';
  }
  function nav(el){go(el.dataset.view,el.dataset.id||'',el.dataset.section||'');}
  function detail(el){return Studio.detail({dataset:{id:el.dataset.id,queue:'true'}});}
  function reload(){route();}
  function openProjects(el){
    const panel=document.getElementById(el.dataset.target);if(!panel)return;
    panel.open=true;panel.querySelector('button')?.focus();
  }
  function openBookTools(){
    openModal(modalX()+'<h2 id="reviewBookToolsTitle">单书资料整理</h2><label class="studio-field"><span>选择图书</span><select id="reviewToolBook" aria-label="选择要整理的图书"><option value="">请选择</option>'+(state.books||[]).map(function(b){return '<option value="'+esc(b.code)+'">'+esc(b.book)+'</option>';}).join('')+'</select></label><div class="modal-actions">'+button('整理章节提要','tools',{tab:'chapter'},'primary')+button('整理文献线索','tools',{tab:'cite'},'ghost')+'</div>');
    document.getElementById('reviewToolBook')?.focus();
  }
  function tools(el){
    const code=document.getElementById('reviewToolBook')?.value;
    if(!code){toast('先选择要整理的图书',true);return;}
    closeModal();
    go('editor',code,el.dataset.tab);
  }
  async function showSummary(code,title){
    try{
      const d=await jget('/api/content-assets?'+new URLSearchParams({code,kind:'summary',limit:200}));
      const a=d.items.find(function(x){return x.title===title;});
      if(!a){toast('请先保存提要并检查来源，再查看成果',true);return;}
      await Studio.detail({dataset:{id:a.id}});
    }catch(err){toast(err.message,true);}
  }
  function row(a,index){
    const ps=a.projects||[],updateOnly=a.action==='refresh_reference';
    const replace=a.action==='replace_asset'||a.status==='missing'||a.status==='rejected'||a.evidence_valid===false;
    const panelId='review-projects-'+index,projectLabel=updateOnly?'更新引用':replace?'处理引用':'打开项目';
    const projectButton=(p,style)=>{
      const marketing=p.kind==='marketing';
      return button(projectLabel,'nav',{view:marketing?'campaigns':'projects',id:p.id,section:marketing?'review':'materials'},style||'sm ghost');
    };
    let action=button('核对素材','detail',{id:a.asset_id},'primary');
    if(updateOnly||replace){
      action=ps.length===1?projectButton(ps[0],'primary'):ps.length?button('选择项目','openProjects',{target:panelId},'primary').replace('<button ','<button aria-controls="'+panelId+'" '):button('查看项目','nav',{view:'records'},'primary');
    }
    const projects=ps.length?'<details class="review-projects" id="'+panelId+'"><summary>涉及 '+num(ps.length)+' 个项目</summary><ul>'+ps.map(p=>'<li><span>'+esc(p.title||'未命名项目')+'</span>'+projectButton(p)+'</li>').join('')+'</ul></details>':'';
    const explain=replace||a.status!=='review'||a.stale||(a.reasons||[]).length>1;
    const status=updateOnly?'需更新引用':replace&&a.status!=='missing'&&a.status!=='rejected'?'出处需处理':states[a.status]||'待核对';
    const title=a.marketing_key==='summary'?'图书简介':a.title||'图书素材';
    return '<article class="studio-card review-item"><div class="review-material-head"><div><h2 class="review-material-title">'+esc(title)+'</h2><p class="review-material-book">'+esc(a.book||'来源待核对')+'</p></div><span class="studio-badge '+esc(updateOnly?'review':a.status||'review')+'">'+esc(status)+'</span></div>'+(explain&&a.reason?'<p class="review-reason">'+esc(a.reason)+'</p>':'')+'<div class="review-material-footer">'+projects+'<div class="review-primary-action">'+action+'</div></div></article>';
  }
  function nextProject(p){
    const marketing=p.kind==='marketing',adopted=(p.items||[]).filter(function(item){return item.status==='adopted';}).length,hasDraft=!!String(p.draft||'').trim();
    return '<article class="review-next-project"><div class="review-next-copy"><h3>'+esc(p.title||'未命名项目')+'</h3><p>'+(hasDraft?'已有稿件':adopted?'已选 '+num(adopted)+' 条素材':'待选素材')+'</p></div>'+button(hasDraft?'打开稿件':'打开项目','nav',{view:marketing?'campaigns':'projects',id:p.id,section:hasDraft||adopted?'results':'materials'},'primary')+'</article>';
  }
  async function completion(){
    const projectIds=round.confirmedProjectIds.slice();
    const results=await Promise.allSettled(projectIds.map(function(id){return jget('/api/projects/'+encodeURIComponent(id));}));
    const projects=results.filter(function(result){return result.status==='fulfilled'&&result.value&&result.value.project;}).map(function(result){return result.value.project;});
    const failed=results.length-projects.length;
    return '<section class="review-complete" aria-labelledby="reviewCompleteTitle"><div class="review-complete-head"><span class="review-complete-mark" aria-hidden="true">✓</span><div><h2 id="reviewCompleteTitle">本轮素材已核对</h2><p>打开相关项目，继续检查稿件。</p></div></div><div class="review-next-projects">'+projects.map(nextProject).join('')+'</div>'+(failed?'<div class="review-next-unavailable" role="status"><p>'+num(failed)+' 个项目暂时无法读取。</p>'+button('重新读取','reload',{},'sm ghost')+button('查看项目','nav',{view:'records'},'sm ghost')+'</div>':'')+'<div class="review-complete-footer">'+button('结束本轮核对','finishRound',{},'sm ghost')+'</div></section>';
  }
  async function render(v){
    const epoch=++renderEpoch;
    crumb('<a href="#/dashboard">工作台</a><span>/</span><b>素材核对待办</b>');v.classList.add('studio-view');v.innerHTML=loading('加载待核对素材');
    const d=await jget('/api/review-queue');
    if(!stillHere(v,epoch))return;
    const items=d.items||[];rememberQueue(items);
    const done=!items.length&&round.confirmedProjectIds.length>0;
    const completeHtml=done?await completion():'';
    if(!stillHere(v,epoch))return;
    v.innerHTML='<section class="review-workspace" aria-label="素材核对待办"><div class="page-head"><div><h1>素材核对待办</h1><p>处理项目中待核对的素材和引用。</p></div>'+button('刷新','reload',{},'ghost')+'</div><section class="review-queue" aria-label="待处理素材">'+
      (done?completeHtml:items.length?'<p class="review-queue-count" role="status">'+num(d.total)+' 条素材 · 涉及 '+num(d.project_count)+' 个项目</p>'+items.map(row).join(''):'<div class="studio-empty"><h2>暂无待核对素材</h2>'+button('查看项目','nav',{view:'records'},'primary')+'</div>')+'</section></section>';
  }
  return {render,nav,detail,reload,openProjects,openBookTools,tools,showSummary,noteReviewed,finishRound};
})();
