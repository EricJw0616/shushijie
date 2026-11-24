/* Frozen deliveries and their feedback, opened one record at a time. */
'use strict';
window.ProjectHistory=(function(){
  const H={container:null,project:null,epoch:0,request:0,views:new Map(),snapshots:new Map(),pending:null};
  const outcomes={used:'已实际使用',needs_revision:'需要修改后使用',not_used:'本次未使用'};
  const e=esc;
  function view(){let value=H.views.get(H.project.id);if(!value){value={selected:'',forms:{},scroll:0};H.views.set(H.project.id,value);}return value;}
  function current(pid){const p=parse();return !!(H.project&&H.project.id===pid&&H.container&&H.container.isConnected&&H.container.dataset.project===pid&&['projects','campaigns'].includes(p.view)&&p.arg===pid);}
  function active(pid,container,epoch,request,id){return current(pid)&&H.container===container&&H.epoch===epoch&&H.request===request&&view().selected===id;}
  function delivery(id){return (H.project.exports||[]).find(function(item){return item.id===id;});}
  function feedbackFor(id){return (H.project.feedback||[]).filter(function(item){return id?item.export_id===id:!item.export_id;});}
  function oldBundle(data){return !!(data&&MarketingScenes.split(data.text)&&/^## 任务说明\s*$/m.test(data.text)&&/^## 材料与来源\s*$/m.test(data.text));}
  function mode(item,data){const delivery=MarketingScenes.deliveryInfo(item);return delivery?delivery.title:oldBundle(data)?'旧版导出（含项目说明）':H.project?.kind==='marketing'&&H.project.brief?.marketing_task==='channel'?(item.mode==='approved'?'已审核记录':'审阅记录'):item.mode==='approved'?'已审核交付稿':'审阅稿';}
  function detailHeading(item,data){const delivery=MarketingScenes.deliveryInfo(item);return '<h2>'+e(mode(item,data))+'</h2><p>'+e(date(item.created_at))+'</p>'+((delivery||oldBundle(data))?'<p>'+e(delivery?.next||'此记录包含当时的项目说明。需要文章或脚本正文，请到当前稿件重新导出。')+'</p>':'');}
  function date(value){return String(value||'').replace('T',' ').slice(0,19)||'时间未记录';}
  function button(label,fn,data,style){return '<button type="button" class="btn '+(style||'ghost')+'" data-project="'+e(H.project.id)+'"'+Object.entries(data||{}).map(function(x){return ' data-'+x[0]+'="'+e(x[1])+'"';}).join('')+' onclick="ProjectHistory.'+fn+'(this)">'+label+'</button>';}
  function guard(el){return !!(el&&el.dataset&&current(el.dataset.project));}
  function row(item){const feedback=feedbackFor(item.id),last=feedback[feedback.length-1];return '<button type="button" class="project-history-row" data-project="'+e(H.project.id)+'" data-export="'+e(item.id)+'" onclick="ProjectHistory.open(this)"><span class="project-history-mode"><b>'+mode(item)+'</b>'+(item.project_revision!==undefined?'<small>项目版本 '+e(item.project_revision)+'</small>':'')+'</span><time datetime="'+e(item.created_at||'')+'">'+e(date(item.created_at))+'</time><span class="project-history-feedback-summary">'+(last?'<b>'+e(outcomes[last.outcome]||'已记录反馈')+'</b><small>'+feedback.length+' 条反馈'+(last.channel?' · '+e(last.channel):'')+'</small>':'<span>尚无反馈</span>')+'</span><span class="project-history-view">查看 <span aria-hidden="true">↗</span></span></button>';}
  function renderList(){
    const exports=(H.project.exports||[]).slice().reverse(),unbound=feedbackFor('');
    H.container.innerHTML='<div class="project-history-heading"><div><h2>交付记录 <span>'+exports.length+'</span></h2><p>每条记录保留导出时的稿件与对应反馈。</p></div>'+(unbound.length?button('项目反馈 · '+unbound.length,'projectFeedback',{},'sm ghost'):'')+'</div>'+
      (exports.length?'<div class="project-history-table"><div class="project-history-columns" aria-hidden="true"><span>稿件类型</span><span>导出时间</span><span>使用反馈</span><span></span></div>'+exports.map(row).join('')+'</div>':'<div class="project-history-empty"><h3>还没有交付记录</h3><p>去当前稿件完成修订和导出，之后可在这里查看具体版本、记录使用反馈。</p><div>'+button('去当前稿件 →','currentDraft',{},'primary')+button('记录待改或未使用','projectFeedback',{},'ghost')+'</div></div>');
  }
  function feedbackRows(rows){return rows.length?'<div class="project-history-feedback-list">'+rows.slice().reverse().map(function(item){return '<article><div><b>'+e(outcomes[item.outcome]||'已记录反馈')+'</b><time>'+e(date(item.created_at||item.ts))+'</time></div>'+(item.channel?'<span class="project-history-channel">'+e(item.channel)+'</span>':'')+'<p>'+e(item.note||'未填写说明').replace(/\n/g,'<br>')+'</p></article>';}).join('')+'</div>':'<p class="project-history-no-feedback">尚未记录反馈。</p>';}
  function formHtml(item){
    const key=item?item.id:'project',draft=view().forms[key]||{},approved=item&&item.mode==='approved',outcome=approved||draft.outcome!=='used'?draft.outcome||'':'';
    const values=approved?['used','needs_revision','not_used']:['needs_revision','not_used'];
    return '<form id="projectFeedback" class="project-history-form" data-project="'+e(H.project.id)+'" data-history-key="'+e(key)+'" oninput="ProjectHistory.rememberForm(this)" onchange="ProjectHistory.rememberForm(this)" onsubmit="event.preventDefault();ProjectHistory.saveFeedback(this)"><input type="hidden" name="export_id" value="'+e(item?item.id:'')+'"><label><span>本次结果</span><select name="outcome" required><option value="">请选择实际结果</option>'+values.map(function(value){return '<option value="'+value+'"'+(outcome===value?' selected':'')+'>'+outcomes[value]+'</option>';}).join('')+'</select></label><label><span>渠道或使用环节</span><input name="channel" maxlength="300" value="'+e(draft.channel===undefined?(H.project.brief||{}).channel||'':draft.channel)+'" placeholder="例如：选题会、公众号、渠道提案"></label><label class="project-history-note"><span>具体情况或修改原因</span><textarea name="note" rows="3" maxlength="4000" required placeholder="采用了什么，或还需要修改什么？">'+e(draft.note||'')+'</textarea></label><div class="project-history-form-actions"><span>'+(!item?'尚无交付版本，本次记录属于项目。':approved?'反馈对应这份交付稿，导出不等于实际使用。':'审阅稿只能记录待修改或未使用；实际使用请记录到已审核交付稿。')+'</span><button class="btn primary" type="submit">保存反馈</button></div></form>';
  }
  function snapshotHtml(data){
    const article=ManuscriptReader.build(data.text,new Map(),{frozen:true}).html;
    return '<div class="project-history-snapshot-meta"><span>稿件预览</span>'+
      (data.export.project_revision!==undefined?'<span>导出时项目版本 '+e(data.export.project_revision)+'</span>':'')+
      '</div><article class="manuscript-reading project-history-document" tabindex="0" aria-label="导出时的完整稿件">'+
      (article||'<p>这份稿件没有可预览的正文。</p>')+'</article>';
  }
  function renderDetail(item){
    const cached=H.snapshots.get(H.project.id+':'+item.id);
    H.container.innerHTML='<div class="project-history-detail-heading">'+button('← 返回交付记录','back',{},'sm ghost')+'<div class="project-history-detail-actions">'+(item.content_kind==='channel_content'?button('复制'+MarketingScenes.workflow({marketing_task:'channel',channels:item.channels}).noun,'copy',{export:item.id},'sm primary'):'')+button('下载排版 PDF','download',{export:item.id,format:'pdf'},'sm primary')+button('下载 Markdown','download',{export:item.id,format:'md'},'sm ghost')+button('去当前稿件','currentDraft',{},'sm ghost')+'</div></div><div class="project-history-version" id="projectHistoryVersion">'+detailHeading(item,cached)+'</div><section class="project-history-snapshot" aria-label="稿件快照"><div id="projectHistorySnapshot" aria-live="polite">'+(cached?snapshotHtml(cached):'<p class="project-history-loading">正在读取这份稿件…</p>')+'</div></section><section class="project-history-feedback"><h3>这份稿件的反馈 <span>'+feedbackFor(item.id).length+'</span></h3>'+feedbackRows(feedbackFor(item.id))+'<h3 class="project-history-add-feedback">记录本次反馈</h3>'+formHtml(item)+'</section>';
    if(!cached)loadSnapshot(item.id);
  }
  function renderProjectFeedback(){const hasExports=(H.project.exports||[]).length>0;H.container.innerHTML='<div class="project-history-detail-heading">'+button('← 返回交付记录','back',{},'sm ghost')+'</div><div class="project-history-version"><h2>项目反馈</h2><p>这里保留尚无交付版本时记录的待改或未使用情况。</p></div><section class="project-history-feedback">'+feedbackRows(feedbackFor(''))+(hasExports?'<p class="project-history-feedback-hint">项目已有交付记录。新增反馈请返回列表，选择对应的稿件版本。</p>':'<h3 class="project-history-add-feedback">记录待改或未使用</h3>'+formHtml(null))+'</section>';}
  function render(){if(!H.project||!current(H.project.id))return;const selected=view().selected;if(selected==='project')renderProjectFeedback();else if(selected&&delivery(selected))renderDetail(delivery(selected));else{view().selected='';renderList();}}
  async function loadSnapshot(id){
    const pid=H.project.id,container=H.container,epoch=H.epoch,request=++H.request;
    try{const data=await jget('/api/projects/'+encodeURIComponent(pid)+'/exports/'+encodeURIComponent(id));if(!active(pid,container,epoch,request,id))return;if(data.ok===false||typeof data.text!=='string'||!data.export||data.export.id!==id||data.export.project_id!==pid)throw new Error(data.error||'交付记录与当前项目不一致，请重新加载');H.snapshots.set(pid+':'+id,data);while(H.snapshots.size>40)H.snapshots.delete(H.snapshots.keys().next().value);const node=container.querySelector('#projectHistorySnapshot');if(node)node.innerHTML=snapshotHtml(data);const heading=container.querySelector('#projectHistoryVersion');if(heading)heading.innerHTML=detailHeading(delivery(id),data);}catch(err){if(!active(pid,container,epoch,request,id))return;const node=container.querySelector('#projectHistorySnapshot');if(node)node.innerHTML='<div class="project-history-read-error" role="alert"><p>'+e(err.message||'暂时无法读取这份稿件')+'</p>'+button('重新读取稿件','retry',{export:id},'sm ghost')+'</div>';}
  }
  function rememberForm(form){if(!form||!guard(form)||!H.container.contains(form))return;const data=Object.fromEntries(new FormData(form));view().forms[form.dataset.historyKey]={outcome:String(data.outcome||''),note:String(data.note||''),channel:String(data.channel||'')};}
  function captureForm(){const form=H.container&&H.container.querySelector('#projectFeedback');if(form)rememberForm(form);}
  function mount(container,project){
    if(!container||!project)return;captureForm();H.container=container;H.project=project;H.epoch++;H.request++;container.dataset.project=project.id;container.classList.add('project-history');
    const pending=H.pending;if(pending&&pending.pid===project.id&&(project.feedback||[]).slice(pending.count).some(function(item){return (item.export_id||'')===pending.exportId&&item.outcome===pending.outcome&&item.note===pending.note&&item.channel===pending.channel;})){delete view().forms[pending.key];H.pending=null;}
    const selected=view().selected;if(selected&&selected!=='project'&&!delivery(selected))view().selected='';render();
  }
  function open(el){if(!guard(el)||!delivery(el.dataset.export))return;captureForm();if(!view().selected)view().scroll=window.scrollY||0;view().selected=el.dataset.export;H.request++;render();}
  function back(el){if(!guard(el))return;captureForm();const pid=H.project.id,scroll=view().scroll;view().selected='';H.request++;render();setTimeout(function(){if(current(pid)&&!view().selected)window.scrollTo({top:scroll,behavior:'instant'});},0);}
  function projectFeedback(el){if(!guard(el))return;captureForm();if(!view().selected)view().scroll=window.scrollY||0;view().selected='project';H.request++;render();}
  function currentDraft(el){if(guard(el))Studio.focusDraft();}
  function copy(el){if(guard(el)&&view().selected===el.dataset.export&&delivery(el.dataset.export))return Studio.copyExport(el,H.snapshots.get(H.project.id+':'+el.dataset.export));}
  function download(el){if(guard(el)&&view().selected===el.dataset.export&&delivery(el.dataset.export))return Studio.downloadExport(el);}
  function retry(el){if(guard(el)&&view().selected===el.dataset.export&&delivery(el.dataset.export))return loadSnapshot(el.dataset.export);}
  async function saveFeedback(form){
    if(!guard(form)||!H.container.contains(form)||H.pending)return;
    const item=view().selected==='project'?null:delivery(view().selected),data=Object.fromEntries(new FormData(form)),exportId=String(data.export_id||'');
    if((item&&exportId!==item.id)||(!item&&((H.project.exports||[]).length||exportId))){toast('请从对应的交付记录填写反馈',true);return;}
    if(!['used','needs_revision','not_used'].includes(data.outcome)||(data.outcome==='used'&&(!item||item.mode!=='approved'))){toast('请选择这份稿件支持的实际结果',true);return;}
    if(!String(data.note||'').trim()){toast('请记录具体使用情况或修改原因',true);return;}
    rememberForm(form);const pending=H.pending={pid:H.project.id,key:form.dataset.historyKey,count:(H.project.feedback||[]).length,exportId,outcome:data.outcome,note:data.note,channel:String(data.channel||'')};
    try{const saving=Studio.feedback();form.querySelectorAll('input,select,textarea,button').forEach(function(el){el.disabled=true;});await saving;}catch(err){if(current(pending.pid))toast(err.message||'反馈保存失败，请重试',true);}finally{if(H.pending===pending)H.pending=null;if(form.isConnected)form.querySelectorAll('input,select,textarea,button').forEach(function(el){el.disabled=false;});}
  }
  return {mount,open,back,projectFeedback,currentDraft,copy,download,retry,rememberForm,saveFeedback};
})();
