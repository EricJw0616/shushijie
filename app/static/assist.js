/* Shared publishing/marketing assistance; generation is always an editable proposal. */
'use strict';
window.ProjectAssist=(function(){
  const A={project:null,runs:[],choice:{},scopes:{},scopeOpen:{},sections:{},busy:false,dirty:false,error:'',loadFailed:false,poll:null,epoch:0,loadSeq:0,dialog:null};
  const status={queued:'排队中',running:'生成中',done:'已生成',partial:'部分完成',failed:'生成失败'};
  const e=esc;
  function text(v){if(typeof v==='string')return v;if(Array.isArray(v))return v.map(text).filter(Boolean).join('；');return v&&typeof v==='object'?text(v.message||v.reason||v.text||v.issue||v.detail||v.title):'';}
  function sourceText(v){return e(text(v)).replace(/\n/g,'<br>');}
  function formatted(v){return ManuscriptReader.build(text(v),undefined,{frozen:true}).html;}
  function plainSummary(v){
    const template=document.createElement('template');
    template.innerHTML=formatted(v);
    for(const block of template.content.querySelectorAll('br,p,li,th,td,h1,h2,h3,h4,h5,h6,blockquote,pre')){
      block.after(' ');
    }
    return template.content.textContent.replace(/\s+/g,' ').trim();
  }
  function materialTitleText(a,fallback){
    const title=a.kind==='quote'?text(a.title||fallback):plainSummary(a.title||fallback);
    if(a.kind==='marketing'){
      const key=a.marketing_key||a.field||a.legacy_id?.split(':')[0];
      const labels={summary:'内容简介',keywords:'主题关键词',audience:'适读人群',scenarios:'阅读场景',gains:'阅读收获',emotions:'情感体验',leads:'推荐切入点'};
      if(key==='summary')return labels.summary;
      const label=labels[key]||(typeof a.name==='string'&&a.name.length<=24?plainSummary(a.name):'');
      if(label&&title.length>48)return label+'：'+clip(title,36);
    }
    return clip(title,48);
  }
  function materialTitle(a,fallback){return e(materialTitleText(a,fallback));}
  function button(label,fn,data,style,disabled){return '<button type="button" class="btn '+(style||'ghost')+'" data-assist-key="'+e(fn+':'+Object.values(data||{}).join(':'))+'"'+Object.entries(data||{}).map(function(x){return ' data-'+x[0]+'="'+e(x[1])+'"';}).join('')+' onclick="ProjectAssist.'+fn+'(this)"'+(disabled?' disabled':'')+'>'+label+'</button>';}
  function host(id){const h=document.getElementById(id||'projectAssist');return h&&A.project&&h.dataset.project===A.project.id?h:null;}
  function hosts(){return [host('projectDiscovery'),host()].filter(Boolean);}
  function here(pid,epoch){return epoch===A.epoch&&A.project&&A.project.id===pid&&!!host();}
  function marketingScope(project){
    if(!project||project.kind!=='marketing')return null;
    const b=project.brief||{},task=b.marketing_task;
    if(task==='reposition')return b.source_code?[b.source_code]:[];
    if(task==='theme'||task==='channel')return Array.isArray(b.target_codes)?[...new Set(b.target_codes)]:[];
    return null;
  }
  function scopeFor(pid){const scope=A.project?.id===pid?marketingScope(A.project):null;if(scope!==null)return scope;if(!Object.prototype.hasOwnProperty.call(A.scopes,pid)){try{const v=JSON.parse(sessionStorage.getItem('project-assist-scope:'+pid)||'null');if(Array.isArray(v))A.scopes[pid]=v.filter(function(x){return typeof x==='string';});}catch(_){} }return A.scopes[pid]||[];}
  function scopeControls(project,scope){
    const books=state.books||[];
    if(scopedWorkflow(project))return '<div class="assist-scope assist-scene-scope"><p>素材来自：'+e(scope.length?scope.map(code=>books.find(b=>b.code===code)?.book||'原选定图书').join('、'):'尚未选择图书')+'</p>'+button('更换图书','editBrief',{},'sm ghost')+'</div>';
    if(marketingScope(project)!==null)return '<div class="assist-scope assist-workspace-scope"><p>本次推广图书：'+e(scope.length?scope.map(code=>books.find(b=>b.code===code)?.book||'原选定图书').join('、'):'尚未选择')+'</p><p class="studio-note">材料发现与生成将使用这些图书。'+button('修改推广图书','editBrief',{},'sm ghost')+'</p></div>';
    return '<details class="assist-scope assist-workspace-scope"'+(A.scopeOpen[project.id]?' open':'')+' ontoggle="ProjectAssist.scopeToggle(this)"><summary data-assist-key="scope-toggle">检索范围：'+(scope.length?'已选 '+scope.length+' 本图书':'全书库')+'</summary><div class="assist-scope-content"><p>不勾选时检索全库，也可组合多本书。</p><div class="assist-book-options">'+books.map(function(b){return '<label><input type="checkbox" data-assist-key="scope:'+e(b.code)+'" value="'+e(b.code)+'"'+(scope.includes(b.code)?' checked':'')+' onchange="ProjectAssist.scopeChange(this)"><span>'+e(b.book)+'</span></label>';}).join('')+(!books.length?'<p>请先上传图书并生成内容成果。</p>':'')+'</div></div></details>';
  }
  function workflow(project=A.project){
    return window.MarketingScenes?.workflow?.(project?.brief)||{scoped:false,title:'营销策划',noun:'内容',draft:'营销初稿',materials:'素材',select:'选入本次内容',generate:'用已选素材生成营销初稿'};
  }
  function scopedWorkflow(project=A.project){return project?.kind==='marketing'&&project.brief?.marketing_task==='channel';}
  function selectedForTask(project){
    const scope=marketingScope(project);
    return chosenMaterials(project).filter(item=>scope===null||scope.includes(item.snapshot?.code||item.asset_id?.split(':')[0]));
  }
  function recommendationTaskChanged(run){
    if(run?.capability!=='recommend'||!run.snapshot?.brief||!A.project)return false;
    const normalized=b=>JSON.stringify(Object.keys({...b,writing_notes:b?.writing_notes||''}).sort().map(key=>[key,Array.isArray(b[key])?b[key].slice().sort():key==='writing_notes'?b[key]||'':b[key]]));
    return normalized(run.snapshot.brief)!==normalized(A.project.brief);
  }
  function recommendationState(run){
    const count=run.result?.suggestions?.length||0;
    return {queued:'找素材排队中',running:'正在找素材',done:'找到 '+count+' 条候选素材',partial:'找到部分候选素材',failed:'找素材失败'}[run.status]||run.status;
  }
  function active(){return A.runs.some(function(r){return !r.applied&&['queued','running'].includes(r.status);});}
  function selected(cap){const runs=A.runs.filter(function(r){return r.capability===cap;});return runs.find(function(r){return r.id===A.choice[cap];})||runs[0];}
  function materials(run){const all=(run.snapshot||{}).materials||[];const map={};all.forEach(function(a){map[a.asset_id||a.id]=a;});return map;}
  function sourceLinks(ids,run){const by=materials(run);return '<div class="assist-sources">'+(ids||[]).map(function(id){const a=by[id]||{};return button('↗ '+materialTitle(a,a.book||'查看材料依据'),'source',{id,run:run.id},'sm ghost');}).join('')+'</div>';}
  function keyValue(label,value){return value?'<div class="assist-labeled-value"><b>'+label+'</b><div class="assist-formatted">'+formatted(value)+'</div></div>':'';}
  function gaps(rows){return (rows||[]).length?'<section class="assist-gaps"><h3>资料缺口与下一步核实</h3><ul>'+rows.map(function(g){return '<li><b>'+e(plainSummary(g.issue||g.question||text(g)))+'</b>'+(g.next_action||g.action?'<div class="assist-formatted assist-gap-action">'+formatted(g.next_action||g.action)+'</div>':'')+'</li>';}).join('')+'</ul></section>':'';}
  function writingNeeds(run){
    const rows=run.result?.writing_needs||[];
    if(!rows.length)return '';
    return '<details class="marketing-writing-needs"><summary>内容调整建议</summary>'+rows.map(row=>'<div><p>'+e(row.message)+'</p>'+button(row.kind==='materials'?'补选素材':'修改写作要求',row.kind==='materials'?'reviseMaterials':'editWritingNotes',{},'sm ghost')+'</div>').join('')+'</details>';
  }
  function legacyGenerationNotes(run){
    if(Object.hasOwn(run.result||{},'writing_needs'))return '';
    const rows=run.result?.gaps||[],steps=run.result?.next_steps||[];if(!rows.length&&!steps.length)return '';
    return '<details class="marketing-legacy-notes"><summary>查看旧版生成说明</summary><div>'+rows.map(g=>'<p><b>'+e(g.issue)+'</b><br>'+e(g.next_action)+'</p>').join('')+steps.map(x=>'<p>'+e(x)+'</p>').join('')+'<div class="card-actions">'+button('重新选材','reviseMaterials',{},'sm ghost')+button('补充写作要求','editWritingNotes',{},'sm ghost')+'</div></div></details>';
  }
  function editWritingNotes(){if(document.getElementById('assistDialog'))closePreview();Studio.editWritingNotes();}
  function reviseMaterials(){if(document.getElementById('assistDialog'))closePreview();Studio.openProjectSection('materials');}
  function runNotice(run){
    if(!run)return '';
    const pending=!run.applied&&['queued','running'].includes(run.status),failed=!run.applied&&run.status==='failed';
    const topicRun=Boolean(run.result?.topic_angles?.length);
    let html='<div role="status" class="assist-run-state '+(pending?'is-running':failed?'is-failed':'')+'"><span class="studio-badge '+(pending?'review':failed?'rejected':'approved')+'">'+e(run.applied?'已应用':run.capability==='recommend'&&scopedWorkflow()?recommendationState(run):status[run.status]||run.status)+'</span><span>'+e(String(run.created_at||'').replace('T',' ').slice(0,16))+'</span>'+(pending?'<span class="assist-pulse">正在处理本次任务与材料，可继续编辑或稍后回来查看。</span>':'')+'</div>';
    if(run.error&&!run.applied)html+='<div class="assist-warning">'+e(run.error)+'</div>';
    if(run.applied)html+='<p class="assist-applied">✓ 这份初稿已应用到项目'+(run.is_current_draft?'，当前工作稿与本次生成一致。':'，后续修订或替换以当前工作稿为准。')+'</p>';
    else if((topicRun?run.topic_angle_choices_stale:run.capability==='recommend'?(recommendationTaskChanged(run)||run.source_stale):run.stale)||A.dirty){
      const issue=A.dirty?'项目有尚未保存的修改。':topicRun?run.topic_angle_choices_stale_reason||'选题说明已有修改。':run.stale_reason||'项目任务或材料已经变化。';
      html+='<div class="assist-warning">'+e(issue)+(run.capability==='draft'?' 请重新生成后应用。':topicRun?'':' 请重新查找素材；这份记录保留供参考。')+'</div>';
    }
    if(run.source_stale&&run.applied)html+='<div class="assist-warning">'+e(run.source_stale_reason||'来源材料发生变化，请重新核对后再交付。')+'</div>';
    if(run.capability==='recommend'){const codes=(run.snapshot||{}).book_codes||[],books=state.books||[],sameScene=scopedWorkflow()&&JSON.stringify(codes.slice().sort())===JSON.stringify(scopeFor(A.project.id).slice().sort());if(!sameScene)html+='<p class="assist-input-scope">本次检索范围：'+e(codes.length?codes.map(function(c){const b=books.find(function(x){return x.code===c;});return b?b.book:'原范围内图书';}).join('、'):'全书库')+'</p>';}
    return html;
  }
  function failedDraftReason(run){
    return clip(text(run.review_issues?.find(issue=>issue.severity==='blocker')?.message||run.error),240);
  }
  function canEditRecovery(run){
    return Boolean(run?.status==='failed'&&run.recovery_draft?.length&&!run.stale&&!run.source_stale&&!A.dirty);
  }
  function recoveryKey(run){return 'bookworld.recovery-draft:'+run.project_id+':'+run.id;}
  function recoveryEditor(run){
    let cached;
    try{cached=JSON.parse(sessionStorage.getItem(recoveryKey(run))||'null');}catch(_){}
    const fields=run.recovery_draft.map((row,index)=>{
      const saved=cached?.[index], value=saved?.channel===row.channel?saved:row;
      return '<fieldset class="studio-field"><legend>'+e(row.channel)+'</legend>'+
        '<label class="studio-field"><span>标题</span><input name="title-'+index+'" maxlength="300" required value="'+e(value.title)+'"></label>'+
        '<label class="studio-field"><span>正文</span><textarea name="body-'+index+'" rows="10" maxlength="5000" required>'+e(value.body)+'</textarea></label>'+
        '<label class="studio-field"><span>结尾</span><textarea name="ending-'+index+'" rows="3" maxlength="500">'+e(value.ending)+'</textarea></label></fieldset>';
    }).join('');
    return '<form class="assist-proposal" data-recovery-run="'+e(run.id)+'" oninput="ProjectAssist.cacheRecovery(this)" onsubmit="event.preventDefault();ProjectAssist.recheck(this)">'+
      '<h3>修改待检查初稿</h3><p>检查通过后，可以预览并确认应用到工作稿。</p>'+fields+
      '<div class="assist-apply"><button type="submit" class="btn primary"'+(A.busy||active()?' disabled':'')+'>重新检查修改稿</button></div></form>';
  }
  function quality(run){const r=run.result||{},snap=run.snapshot||{},warnings=r.quality_warnings||r.warnings||snap.quality_warnings||[],excluded=r.excluded||snap.excluded||[],count=snap.counts||{},notice=snap.retrieval_notice||'';if(!warnings.length&&!excluded.length&&!notice)return '';return '<details class="assist-quality"><summary>材料范围与质量提示'+(count.provided!==undefined?' · 本次提供 '+e(count.provided)+' 条材料':'')+'</summary>'+(notice?'<p>'+e(notice)+'</p>':'')+(warnings.length?'<ul>'+warnings.map(function(w){return '<li>'+e((w.title?w.title+'：':'')+text(w))+'</li>';}).join('')+'</ul>':'')+(excluded.length?'<p>以下材料未进入本次生成：</p><ul>'+excluded.slice(0,12).map(function(w){return '<li>'+e((w.title?w.title+'：':'')+text(w))+'</li>';}).join('')+'</ul>':'')+'</details>';}
  function history(cap){const rows=A.runs.filter(function(r){return r.capability===cap;});if(rows.length<2)return '';const cur=selected(cap);return '<label class="assist-history"><span>'+(cap==='recommend'?'推荐记录':'讨论稿记录')+'</span><select data-assist-key="history:'+cap+'" data-cap="'+cap+'" onchange="ProjectAssist.selectRun(this)">'+rows.map(function(r){return '<option value="'+e(r.id)+'"'+(r.id===cur.id?' selected':'')+'>'+e(String(r.created_at||'').replace('T',' ').slice(0,19)+' · '+(r.applied?'已应用':status[r.status]||r.status))+'</option>';}).join('')+'</select></label>';}
  function canApply(run){return !!(run&&run.capability==='draft'&&run.status==='done'&&run.result&&!run.applied&&!run.stale&&!run.source_stale&&!A.dirty&&!A.busy);}
  function canChooseRecommendation(run,item){
    return run?.capability==='recommend'&&run.status==='done'&&!A.dirty&&!A.busy&&
      !recommendationTaskChanged(run)&&!run.source_stale&&!item?.stale&&!['rejected','missing'].includes(item?.current_status);
  }
  function topicAngleBlocker(angle){
    const ids=angle.asset_ids||[],items=(A.project.items||[]).filter(i=>ids.includes(i.asset_id));
    if(items.some(i=>i.status==='not_fit'))return '有材料已设为本项目不采用，可在「已收集」处理。';
    if(items.some(i=>i.stale||['rejected','missing'].includes(i.current_status)))return '有材料需要更新，请先在「已收集」处理。';
    return '';
  }
  function chosenMaterials(project,angle){
    return (project.items||[]).filter(i=>i.status==='adopted'&&(!angle||(angle.asset_ids||[]).includes(i.asset_id)));
  }
  function topicAngleComparison(run,angles){
    const strength={strong:'依据相对充足',partial:'有部分依据',limited:'依据不足'};
    const by=materials(run),selectedAngle=A.project.topic_angle;
    return '<section class="assist-topic-comparison" aria-labelledby="assistTopicComparisonTitle">'+
      '<h3 id="assistTopicComparisonTitle">选题切口对比</h3><div class="assist-topic-grid">'+angles.map(function(angle,index){
        const ids=(angle.asset_ids||[]).filter(id=>by[id]);
        const books=new Set(ids.map(id=>by[id].code||by[id].book).filter(Boolean));
        const current=selectedAngle?.run_id===run.id&&selectedAngle.angle_index===index;
        const chosen=current?chosenMaterials(A.project,selectedAngle):[];
        const blocker=current?
          (!chosen.length?'这个切口的材料已全部取消采用。':topicAngleBlocker({asset_ids:chosen.map(i=>i.asset_id)})):
          topicAngleBlocker(angle);
        const unavailable=run.status!=='done'||run.topic_angle_choices_stale||A.dirty||A.busy||active();
        const support=Object.hasOwn(strength,angle.strength)?angle.strength:'limited';
        const action=current?(blocker?button('去处理材料','editMaterials',{mode:'selected'},'sm ghost'):
          button('去组稿','goToDraft',{},'sm primary',unavailable)):
          ids.length?button(selectedAngle?'改用这个切口':'采用切口与材料','adoptAngle',{run:run.id,angle:index},'sm '+(support==='strong'?'primary':'ghost'),unavailable||Boolean(blocker)):'';
        return '<article class="assist-topic-card'+(current?' is-current':'')+'">'+
          '<header class="assist-topic-card-head"><span class="assist-topic-strength" data-level="'+support+'">'+strength[support]+'</span>'+
            (current?'<span class="assist-topic-selected">本项目已选</span>':'')+'</header>'+
          '<h4>'+e(plainSummary(angle.title))+'</h4><p class="assist-topic-source-count">'+ids.length+' 条材料 · '+books.size+' 本来源图书</p>'+
          '<div class="assist-topic-summary assist-formatted">'+formatted(angle.summary)+'</div>'+
          '<div class="assist-topic-scope">'+keyValue('可以写到哪一步',angle.supported_scope)+keyValue('还有哪些缺口',angle.gap)+'</div>'+
          (ids.length?'<details class="assist-topic-evidence"><summary>查看材料依据</summary>'+sourceLinks(ids,run)+'</details>':'')+
          '<div class="assist-topic-actions">'+(blocker?'<p>'+e(blocker)+'</p>':'')+action+'</div></article>';
      }).join('')+'</div></section>';
  }
  function selectionNext(){
    if(!scopedWorkflow())return '';
    const w=workflow(),selected=selectedForTask(A.project),used=selected.length;
    const drafts=A.runs.filter(r=>r.capability==='draft'),latest=drafts[0];
    const running=drafts.find(r=>!r.applied&&['queued','running'].includes(r.status));
    const ready=latest?.status==='done'&&!latest.applied&&!latest.stale&&!latest.source_stale&&!A.dirty;
    let title,description,action;
    if(running){
      title='正在生成'+w.draft;description='已选 '+used+' 条素材。生成完成后，在这里预览并放入工作稿。';
      action=button('正在生成…','start',{cap:'draft'},'primary',true);
    }else if(ready){
      title=w.draft+'已生成';description='先预览，确认后点击“应用到工作稿”，再继续编辑。';
      action=button('预览'+e(w.draft),'openPreview',{run:latest.id},'primary');
    }else if(!used){
      title='已选 0 条，请从下方选择素材';description='点击“'+w.select+'”后，即可生成'+w.draft+'。';
      action=button(e(w.generate),'start',{cap:'draft'},'primary',true);
    }else{
      title='已选 '+used+' 条'+w.materials;description=A.project.draft?'可继续选素材，或生成一份新初稿；应用后才会替换当前稿。':'可以继续选择，也可以生成初稿。内容和出处仍需在定稿前核对。';
      if(latest?.status==='failed')description='上次生成未完成，已选素材仍保留，可以重试。';
      action=button(e(w.generate),'start',{cap:'draft'},'primary',A.busy||active());
    }
    return '<section class="assist-selection-next" aria-label="选素材后的下一步"><div><h3>'+e(title)+'</h3><p>'+e(description)+'</p></div><div class="assist-selection-actions">'+action+(used?button('查看已选素材','editMaterials',{mode:'selected'},'sm ghost'):'')+'</div></section>';
  }
  function recommendationRow(s,i,run,by){
    const a=by[s.asset_id]||{},existing=(A.project.items||[]).find(x=>x.asset_id===s.asset_id),adopted=existing?.status==='adopted';
    const scene=scopedWorkflow(),w=workflow(),id={run:run.id,id:s.asset_id};
    const original=a.kind==='marketing'?(a.evidence||[]).find(x=>x.quote)?.quote:null;
    const excerpt=original||a.text||a.content||'',excerptLabel=original||a.kind==='quote'?'原文片段':'素材概要';
    const content=scene?'<span class="assist-recommend-excerpt"><b>'+excerptLabel+'</b>'+e(clip(plainSummary(excerpt),160))+'</span>'+('<span class="assist-recommend-use"><b>可放在'+e(w.noun)+'哪里</b>'+e(clip(plainSummary(s.proposed_use||s.reason),160))+'</span>'):'<span class="assist-recommend-reason">'+e(clip(plainSummary(s.reason),105))+'</span>';
    const stateLabel=adopted?(scene?'已选入'+w.noun:'项目已采用'):existing?'已收集，尚未选用':'待选择';
    const useButton=scene?button(e(adopted?'已选入'+w.noun:w.select),'adopt',{...id,confirm:'false'},'sm primary',adopted||!canChooseRecommendation(run,existing)):'';
    return '<article class="assist-recommend-row"><span class="assist-number">'+String(i+1).padStart(2,'0')+'</span><button type="button" class="assist-recommend-open" data-run="'+e(run.id)+'" data-id="'+e(s.asset_id)+'" onclick="ProjectAssist.openRecommendation(this)"><strong>'+materialTitle(a,'候选素材')+'</strong><span class="assist-recommend-book">'+e(a.book||a.code||'原书材料')+'</span>'+content+'</button><div class="assist-recommend-action"><span class="assist-material-state'+(adopted?' adopted':'')+'">'+e(stateLabel)+'</span>'+useButton+button(scene?'查看内容与原文':'查看详情','openRecommendation',id,'sm ghost')+'</div></article>';
  }
  function recommendResult(run){
    const scene=scopedWorkflow(),w=workflow();
    if(!run)return '<div class="assist-empty">'+(A.project.kind==='editorial'?'填写选题后，可以查找历史材料，比较几个切口。':scene?'还没有候选素材。点击“从图书找素材”，系统会按主题和读者查找可用于'+e(w.title)+'的内容。':marketingScope(A.project)!==null?'暂无材料推荐。点击“发现可用材料”，从本次推广图书中查找依据。':'暂无材料推荐。选择图书范围后，点击“发现可用材料”。')+'</div>'+selectionNext();
    const r=run.result||{},by=materials(run),suggestions=r.suggestions||[];
    let html=runNotice(run)+history('recommend');
    if(!run.result)return html+selectionNext();
    const angles=A.project.kind==='editorial'?r.topic_angles||[]:[];
    if(angles.length)html+=topicAngleComparison(run,angles);
    if(!suggestions.length&&!angles.length)html+='<div class="assist-empty">本次没有找到足够相关的素材。可调整主题或图书范围后重新查找。</div>';
    if(scene)html+=selectionNext();
    if(suggestions.length){
      const isOpen=A.sections[A.project.id]?.topicMaterials;
      if(angles.length)html+='<details class="assist-topic-materials" data-cap="topicMaterials" ontoggle="ProjectAssist.sectionToggle(this)"'+(isOpen?' open':'')+'><summary data-assist-key="topic-materials">查看本次推荐材料 · '+suggestions.length+' 条</summary>';
      html+='<div class="assist-recommend-list">'+suggestions.map((s,i)=>recommendationRow(s,i,run,by)).join('')+'</div>';
      if(angles.length)html+='</details>';
    }
    if((r.gaps||[]).length||quality(run))html+='<details class="assist-recommend-notes"><summary>还缺哪些内容，哪些地方需要核对</summary>'+gaps(r.gaps)+quality(run)+'</details>';
    return html;
  }
  function marketingRows(run){
    const by=run?materials(run):{},scope=marketingScope(A.project),seen=new Set();
    const rows=((run?.result||{}).suggestions||[]).map(s=>{
      seen.add(s.asset_id);
      return {id:s.asset_id,asset:by[s.asset_id]||{},run:run.id,suggestion:s,item:A.project.items?.find(x=>x.asset_id===s.asset_id)};
    });
    for(const item of A.project.items||[]){
      if(seen.has(item.asset_id)||item.status==='not_fit')continue;
      const asset=item.snapshot||{},code=asset.code||item.asset_id?.split(':')[0];
      if(scope!==null&&!scope.includes(code))continue;
      rows.push({id:item.asset_id,asset,item});
    }
    return rows;
  }
  function marketingMaterialRow(row,index,run){
    const a=row.asset,item=row.item,adopted=item?.status==='adopted';
    const unavailable=A.busy||A.dirty||active()||(!adopted&&(row.run?!canChooseRecommendation(run,item):item?.stale||['rejected','missing'].includes(item?.current_status)));
    const data={id:row.id,...(row.run?{run:row.run}:{})};
    const original=a.kind==='marketing'?(a.evidence||[]).find(x=>x.quote)?.quote:null;
    const excerpt=plainSummary(original||a.text||a.content||row.suggestion?.reason||'');
    const title=materialTitleText(a,'图书素材');
    return '<article class="marketing-assist-material'+(adopted?' is-selected':'')+'"><span class="marketing-assist-number" aria-hidden="true">'+String(index+1).padStart(2,'0')+'</span><div class="marketing-assist-material-copy"><h3>'+e(title)+'</h3>'+(excerpt&&excerpt!==title?'<p>'+e(clip(excerpt,115))+'</p>':'')+'<small>'+e(a.book||a.code||'图书素材')+(item?.stale?' · 原文有更新，需核对':'')+'</small></div><div class="marketing-assist-material-actions">'+
      button(adopted?'✓ 已选用':'选用','toggleMaterial',data,'sm '+(adopted?'marketing-assist-selected':'ghost'),unavailable).replace('<button ','<button aria-pressed="'+adopted+'" ')+
      button('查看详情',row.run?'openRecommendation':'openCollected',data,'sm ghost')+'</div></article>';
  }
  function marketingDiscovery(run){
    const rows=marketingRows(run),pending=run&&!run.applied&&['queued','running'].includes(run.status),failed=run?.status==='failed';
    const disabled=A.busy||active()||!(state.books||[]).length;
    let html='<div class="marketing-assist-toolbar"><span>'+e(pending?'正在从图书查找素材…':rows.length?'已找到 '+rows.length+' 条素材':'可用素材')+'</span>'+(rows.length||run?button(pending?'查找中…':'重新查找','start',{cap:'recommend'},'sm ghost',disabled):'')+'</div>';
    if(pending)html+='<p class="marketing-assist-state" role="status">'+(run.status==='queued'?'正在排队，完成后会在这里显示。':'正在根据主题和读者查找，可稍后回来查看。')+'</p>';
    if(failed)html+='<p class="marketing-assist-state is-error" role="alert">本次查找未完成，请重新查找。</p>';
    if(run&&(recommendationTaskChanged(run)||run.source_stale))html+='<p class="marketing-assist-state is-error">主题或图书内容已更新，请重新查找后选择。</p>';
    if(rows.length)html+='<div class="marketing-assist-material-list">'+rows.map((row,index)=>marketingMaterialRow(row,index,run)).join('')+'</div>';
    else if(!pending)html+='<div class="marketing-assist-empty"><p>'+e(run?'暂未找到合适素材，可调整主题或图书后再查找。':'从推广图书中找到素材，选用后用于生成初稿。')+'</p>'+button(run?'修改主题或图书':'查找素材',run?'editBrief':'start',run?{}:{cap:'recommend'},'primary',disabled)+'</div>';
    const moreOpen=A.sections[A.project.id]?.marketingMaterialsMore;
    html+='<details class="marketing-assist-more" data-cap="marketingMaterialsMore" ontoggle="ProjectAssist.sectionToggle(this)"'+(moreOpen?' open':'')+'><summary data-assist-key="marketing-materials-more">更多</summary><div>'+scopeControls(A.project,scopeFor(A.project.id))+history('recommend')+(run?legacyGenerationNotes(run)+quality(run):'')+'</div></details>';
    return html;
  }
  function workflowSummary(){
    if(!A.project)return null;
    const p=A.project,recommend=selected('recommend'),draft=A.runs.find(r=>r.capability==='draft'),currentDraft=A.runs.find(r=>r.capability==='draft'&&r.is_current_draft&&!r.source_stale),running=A.runs.find(r=>!r.applied&&['queued','running'].includes(r.status));
    return {projectId:p.id,writingNeeds:!A.dirty?(currentDraft?.result?.writing_needs||[]).slice(0,3):[],usedCount:(p.kind==='marketing'?selectedForTask(p):chosenMaterials(p,p.topic_angle)).length,busy:A.busy,dirty:A.dirty,loadFailed:A.loadFailed,hasDraft:!!String(p.draft||'').trim(),recommendStatus:recommend?.status||'',recommendedCount:p.kind==='marketing'?marketingRows(recommend).length:recommend?.result?.suggestions?.length||0,draftStatus:draft?.status||'',draftRunId:draft?.id||'',draftReady:!!(draft?.status==='done'&&!draft.applied&&!draft.stale&&!draft.source_stale&&!A.dirty),runningCapability:running?.capability||'',videoPromptCount:A.runs.filter(r=>r.capability==='video_prompts').length};
  }
  function marketingGeneration(){
    const summary=workflowSummary(),w=workflow(),draft=A.runs.find(r=>r.capability==='draft');
    let title='',description='';
    if(summary.runningCapability==='draft'){
      title=draft?.recovered_from?'正在检查修改稿':summary.draftStatus==='queued'?w.draft+'正在排队':'正在生成'+w.draft;
      description='生成完成后先预览，再决定是否应用。';
    }else if(summary.draftReady){
      title=w.draft+'已生成，待预览';description=summary.hasDraft?'预览确认后再替换当前工作稿。':'预览确认后，即可放入工作稿继续编辑。';
    }else if(draft?.status==='failed'&&!draft.applied){
      title='上次生成未完成';description=failedDraftReason(draft)||'已选素材仍保留，可以重新生成。';
    }else if(!summary.hasDraft){
      title=summary.usedCount?'素材已就绪':'还没有初稿';description=summary.usedCount?'已选 '+summary.usedCount+' 条素材，可以生成'+w.draft+'。':'先选用素材，再生成'+w.draft+'。';
    }
    let html=title?'<div class="marketing-assist-generation" role="status"><h3>'+e(title)+'</h3><p>'+e(description)+'</p>'+
      (canEditRecovery(draft)?button('修改这份初稿','openPreview',{run:draft.id},'sm ghost',A.busy||active()):'')+'</div>':'';
    return html+(summary.writingNeeds.length?writingNeeds({result:{writing_needs:summary.writingNeeds}}):'');
  }
  function draftPlanning(run,marketing){
    const r=run.result;let html='<h2>'+e(plainSummary(r.title)||'项目讨论稿')+'</h2><div class="assist-summary assist-formatted">'+formatted(r.summary)+'</div>';
    if((r.angles||[]).length)html+='<section><h3>'+(marketing?'传播角度':'选题方向与差异假设')+'</h3><div class="assist-angle-grid">'+r.angles.map(function(x){return '<div class="assist-angle"><h4>'+e(plainSummary(x.title))+'</h4>'+keyValue('为什么考虑',x.rationale)+keyValue('读者价值',x.reader_value)+keyValue('差异假设',x.difference)+sourceLinks(x.asset_ids,run)+'</div>';}).join('')+'</div></section>';
    if((r.outline||[]).length)html+='<section><h3>'+(marketing?'内容组织建议':'目录与内容组织建议')+'</h3><ol class="assist-outline">'+r.outline.map(function(x){return '<li><h4>'+e(plainSummary(x.title))+'</h4>'+keyValue('目标',x.objective)+keyValue('内容安排',x.content)+sourceLinks(x.asset_ids,run)+'</li>';}).join('')+'</ol></section>';
    if(marketing&&(r.book_roles||[]).length){
      const by=materials(run);
      html+='<section><h3>各书在专题中的作用</h3><div class="assist-reuse-list">'+r.book_roles.map(function(x){
        const source=Object.values(by).find(a=>a.code===x.code),book=(state.books||[]).find(b=>b.code===x.code);
        return '<div><h4>'+e(source?.book||book?.book||'来源图书')+'</h4>'+keyValue('在本次主题中的作用',x.role)+sourceLinks(x.asset_ids,run)+'</div>';
      }).join('')+'</div></section>';
    }
    if((r.reuse||[]).length)html+='<section><h3>已有材料怎样复用</h3><div class="assist-reuse-list">'+r.reuse.map(function(x){return '<div>'+sourceLinks([x.asset_id],run)+keyValue('用于',x.use)+keyValue('需要加工',x.adaptations)+keyValue('适用边界',x.constraints)+'</div>';}).join('')+'</div></section>';
    html+=(marketing?legacyGenerationNotes(run):gaps(r.gaps))+quality(run);
    if(!marketing&&(r.next_steps||[]).length)html+='<section><h3>建议的下一步</h3><ol class="assist-next">'+r.next_steps.map(function(x){return '<li class="assist-formatted">'+formatted(x)+'</li>';}).join('')+'</ol></section>';
    return html;
  }
  function channelPreview(run){
    const rows=run.result.channel_assets,index=Math.max(0,rows.findIndex(x=>x.channel===A.dialog?.channel)),x=rows[index];
    const video=x.channel==='短视频'?VideoScript.render(x.body,'preview:'+run.id+':'+index):'';
    const delivery=MarketingScenes.deliveryParts(x.channel,x.body);
    const copy=delivery?'<div class="assist-formatted">'+formatted(delivery.main)+'</div><details class="marketing-preview-support"><summary>'+e(x.channel==='小红书'?'预览配图提示词':'预览讲述提示')+'</summary><div class="assist-formatted">'+formatted(delivery.support)+'</div></details>':'<div class="assist-formatted">'+formatted(x.body)+'</div>';
    return '<section class="assist-scene-preview">'+(rows.length>1?'<h2>按场景查看内容</h2>':'')+'<div class="studio-tabs assist-scene-tabs" role="tablist" aria-label="生成内容的使用场景"'+(rows.length===1?' hidden':'')+'>'+rows.map(function(row,i){
      return '<button type="button" id="assistSceneTab'+i+'" role="tab" aria-selected="'+(i===index)+'" aria-controls="assistSceneContent" tabindex="'+(i===index?'0':'-1')+'" class="'+(i===index?'on':'')+'" data-assist-key="scene:'+i+'" data-index="'+i+'" onclick="ProjectAssist.selectChannel(this)" onkeydown="ProjectAssist.channelKeydown(event,this)">'+e(row.channel)+'</button>';
    }).join('')+'</div><div id="assistSceneContent" '+(rows.length>1?'role="tabpanel" aria-labelledby="assistSceneTab'+index+'" ':'')+'tabindex="0" class="assist-channel-assets"><article class="assist-angle"><span class="asset-type">'+e(MarketingScenes.label(x.channel))+'</span><h3>'+e(plainSummary(x.title))+'</h3>'+(video||copy)+(x.cta?'<div class="assist-formatted">'+formatted(x.cta)+'</div>':'')+sourceLinks(x.asset_ids,run)+'</article></div></section>';
  }
  function draftResult(run){
    if(!run)return '<div class="assist-empty">'+(A.project.draft?'当前工作稿保留在项目主页面；新建议应用后才会替换正文。':'尚未生成建议。采用材料后，可生成并预览。')+'</div>';
    let html=runNotice(run);const r=run.result;
    if(!r)return html+(canEditRecovery(run)?recoveryEditor(run):'');
    const marketing=A.project.kind==='marketing',channels=marketing?(r.channel_assets||[]):[];
    html+='<article class="assist-proposal"><div class="eyebrow">可编辑的内容初稿 · 待审核</div>';
    if(channels.length){
      html+=writingNeeds(run)+channelPreview(run);
    }else if(marketing&&run.snapshot?.plan_delivery_version==='1.0'){
      const plan=MarketingScenes.stripMarkers(run.markdown,Object.values(r.source_labels||{}));
      html+=formatted(plan)+sourceLinks(r.asset_ids,run);
    }else html+=(marketing?writingNeeds(run):'')+draftPlanning(run,marketing);
    if(marketing)html+='<div class="marketing-revision-actions"><span>调整初稿</span>'+button(channels.some(x=>x.channel==='短视频')?'修改制作要求':'修改写作要求','editWritingNotes',{},'sm ghost')+button('重新选材','reviseMaterials',{},'sm ghost')+'</div>';
    const singleVideo=channels.length===1&&channels[0].channel==='短视频';
    const applyLabel=run.applied?'已应用记录':singleVideo?'使用这份口播稿':channels.length===1?'使用这份初稿':channels.length?'应用全部 '+channels.length+' 个场景到工作稿':A.project.draft?'应用并替换当前工作稿':'应用到当前工作稿';
    const note=A.project.draft?'应用后会替换当前稿，请先核对。':singleVideo?'使用后可编辑口播，再选择呈现方式。':'使用后可编辑稿件。';
    html+='<div class="assist-apply"><p>'+note+'</p>'+button(applyLabel,'apply',{run:run.id},'primary',!canApply(run))+'</div></article>';
    return html;
  }
  function selectChannel(el){
    if(A.dialog?.type!=='draft')return;
    const run=A.runs.find(x=>x.id===A.dialog.run),index=Number(el.dataset.index),row=Number.isInteger(index)?run?.result?.channel_assets?.[index]:null;
    if(!row)return;A.dialog.channel=row.channel;delete A.dialog.source;paintDialog();
    document.getElementById('assistSceneTab'+index)?.focus({preventScroll:true});
  }
  function channelKeydown(ev,el){
    const tabs=Array.from(el.parentElement.querySelectorAll('[role=tab]')),index=tabs.indexOf(el);let next=index;
    if(ev.key==='ArrowRight')next=(index+1)%tabs.length;else if(ev.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;else if(ev.key==='Home')next=0;else if(ev.key==='End')next=tabs.length-1;else return;
    ev.preventDefault();selectChannel(tabs[next]);
  }
  function planningToggle(el){if(A.dialog?.type==='draft'&&el.isConnected)A.dialog.planningOpen=el.open;}
  function runLabel(run){
    if(run.applied)return run.is_current_draft?'当前稿的生成来源':'已应用记录';
    if(run.stale||run.source_stale)return '需重新生成';
    return run.status==='done'?'待应用建议':status[run.status]||run.status;
  }
  function recordsHtml(){
    const rows=A.runs.filter(function(r){return r.capability==='draft';});
    return '<div class="assist-dialog-heading"><div class="eyebrow">GENERATION RECORDS</div><h2 id="assistDialogTitle">生成记录</h2><p>每次建议单独保存。当前工作稿以项目主页面为准，预览不会覆盖正文。</p></div>'+(rows.length?'<div class="assist-record-list">'+rows.map(function(run){return '<button type="button" class="assist-record-row" data-run="'+e(run.id)+'" onclick="ProjectAssist.openPreview(this)"><span class="assist-record-main"><strong>'+e(plainSummary(run.result?.title)||'本次讨论建议')+'</strong><span>'+e(String(run.created_at||'').replace('T',' ').slice(0,19))+'</span></span><span class="assist-record-state">'+e(runLabel(run))+'</span><span class="assist-record-arrow" aria-hidden="true">↗</span></button>';}).join('')+'</div>':'<div class="assist-empty">尚无生成记录。先采用材料，再生成讨论建议。</div>');
  }
  function sourceHtml(run,id){
    const a=materials(run)[id];if(!a)return '<p class="assist-empty">本次快照未包含这条材料，请核对当前成果。</p>'+button('核对当前成果','currentSource',{id},'sm ghost');
    const context=(a.source_context||[]).length?a.source_context:(a.evidence||[]),warnings=a.quality_warnings||[];
    return '<h3 tabindex="-1" id="assistSourceTitle">'+materialTitle(a,'材料依据')+'</h3><p class="muted">'+e(a.book||a.code||'')+'</p><p class="review-scope">本次生成保存的原文片段，用于核对依据与适用范围。</p>'+(a.context_coverage?'<p class="studio-note">来源覆盖：'+e(text(a.context_coverage))+'</p>':'')+(warnings.length?'<div class="assist-warning">'+warnings.map(function(w){return e(text(w));}).join('<br>')+'</div>':'')+'<div class="asset-detail-evidence">'+context.map(function(c){return '<blockquote><p>'+sourceText(c.quote||c.text)+'</p><footer>'+e(c.chapter||'')+(c.is_excerpt?' · 选段':'')+' '+button('新页查看原文','openSource',{code:a.code,anchor:c.anchor||c.seg},'sm ghost')+'</footer></blockquote>';}).join('')+(!context.length?'<p class="assist-empty">暂缺原文片段，可打开当前成果核对。</p>':'')+'</div>'+button('核对当前成果','currentSource',{id},'sm ghost');
  }
  function recommendationHtml(run,id){
    const suggestion=((run.result||{}).suggestions||[]).find(function(x){return x.asset_id===id;}),a=materials(run)[id]||{},existing=(A.project.items||[]).find(function(x){return x.asset_id===id;});
    if(!suggestion)return '<div class="assist-empty">这条推荐已不可用，请回推荐列表重新选择。</div>';
    const adopted=existing?.status==='adopted',confirmed=(existing?.current_status||a.status)==='approved'&&!existing?.stale;
    const disabled=!canChooseRecommendation(run,existing),data={id,run:run.id},scene=scopedWorkflow(),w=workflow();
    if(A.project.kind==='marketing'){
      const unavailable=A.busy||A.dirty||active()||(!adopted&&disabled),content=a.text||a.content||'';
      return '<div class="assist-dialog-heading"><div class="marketing-assist-detail-context">'+e(w.title)+' · 素材详情</div><h2 id="assistDialogTitle">'+materialTitle(a,'图书素材')+'</h2><p>'+e(a.book||a.code||'原书材料')+'</p></div>'+
        '<article class="assist-recommend-detail">'+keyValue('这条素材怎么用',suggestion.proposed_use||suggestion.reason)+'<h3>素材内容</h3><div class="assist-detail-content assist-formatted">'+(a.kind==='quote'?sourceText(content):formatted(content))+'</div></article>'+
        '<details class="assist-recommend-notes"><summary>查看原文与出处</summary><div class="assist-detail-evidence">'+sourceHtml(run,id)+'</div></details>'+
        '<div class="assist-dialog-footer"><p>'+e(adopted?'已选用，将用于生成本次初稿。':disabled?'这条素材已变化，请重新查找或核对。':'选用后，将用于生成本次初稿。')+'</p>'+button(adopted?'取消选用':'选用这条素材','toggleMaterial',data,'primary',unavailable)+'</div>'+
        (!confirmed?'<details class="marketing-assist-detail-review"><summary>核对内容与出处</summary><p>对照原文核实后，可保存核对结果，供其他项目沿用。</p>'+button(adopted?'确认内容与出处':'确认内容与出处并选用','adopt',{...data,confirm:'true'},'sm ghost',disabled)+'</details>':'');
    }
    let guidance='对照原文确认内容和出处后，可将核对结果保存到内容成果库，其他项目也可沿用。';
    let actions='';
    if(existing?.stale||['rejected','missing'].includes(existing?.current_status)){
      guidance='这条材料在项目中的引用有变化，请到「已收集」查看处理方式。';
    }else if(confirmed){
      guidance=adopted?'内容已核对，已在本项目采用。':'内容已有核对记录，可以直接采用到本项目。';
      if(!adopted)actions=button(scene?e(w.select):'采用并加入项目','adopt',data,'primary',disabled);
    }else{
      if(!adopted)actions=button(scene?e(w.select)+'，稍后核对':'先采用，稍后核对','adopt',data,scene?'primary':'ghost',disabled);
      actions+=button(adopted?'确认内容与出处':'确认内容并采用','adopt',Object.assign({},data,{confirm:'true'}),scene?'ghost':'primary',disabled);
    }
    const content=a.text||a.content||'';
    return '<div class="assist-dialog-heading"><div class="eyebrow">RECOMMENDATION / EVIDENCE</div><h2 id="assistDialogTitle">'+materialTitle(a,'推荐材料')+'</h2><p>'+e(a.book||a.code||'原书材料')+'</p></div>'+runNotice(run)+'<article class="assist-recommend-detail">'+keyValue('推荐理由',suggestion.reason)+keyValue('建议用法',suggestion.proposed_use)+'<h3>材料内容</h3><div class="assist-detail-content assist-formatted">'+(a.kind==='quote'?sourceText(content):formatted(content))+'</div></article><div class="assist-detail-evidence">'+sourceHtml(run,id)+'</div><div class="assist-dialog-footer"><p>'+guidance+'</p><div class="assist-adopt-actions">'+actions+'</div></div>';
  }
  function dialogHtml(){
    const dialog=A.dialog,run=dialog&&A.runs.find(function(x){return x.id===dialog.run;});
    if(!dialog)return '';
    let body='';
    if(dialog.type==='records')body=recordsHtml();
    else if(!run)body='<h2 id="assistDialogTitle">记录暂不可用</h2><div class="assist-empty">这份生成记录暂不可用，请返回记录列表。</div>'+button('生成记录','openRecords',{},'ghost');
    else if(dialog.type==='recommend')body=recommendationHtml(run,dialog.asset);
    else if(dialog.type==='source')body='<div class="assist-dialog-heading"><h2 id="assistDialogTitle">本次使用的材料依据</h2></div>'+sourceHtml(run,dialog.asset);
    else body='<div class="assist-dialog-heading"><div class="assist-dialog-breadcrumb">'+button('← 生成记录','openRecords',{},'sm ghost')+'<span>'+e(runLabel(run))+'</span></div><h2 id="assistDialogTitle">建议预览</h2><p>这是一份独立的生成记录。应用后才会替换当前工作稿。</p></div><div class="assist-preview-layout"><div class="assist-preview-body">'+draftResult(run)+'</div><aside id="assistSourcePanel" class="assist-source-panel" aria-label="本次生成的材料依据" hidden></aside></div>';
    return '<section id="assistDialog" class="assist-dialog" role="dialog" aria-modal="true" aria-labelledby="assistDialogTitle" tabindex="-1"><button type="button" class="modal-x" onclick="ProjectAssist.closePreview()" aria-label="关闭预览">×</button>'+(A.error?'<div class="assist-warning" role="alert">'+e(A.error)+'</div>':'')+body+'<div class="assist-dialog-back">'+button(dialog.type==='recommend'||dialog.type==='source'?'返回材料列表':'返回当前工作稿','closePreview',{},'ghost')+'</div></section>';
  }
  function paintDialog(){
    const root=document.getElementById('assistDialog');if(!root||!A.dialog||!A.project||A.dialog.project!==A.project.id)return;
    const focused=root.contains(document.activeElement)?document.activeElement:null,focusKey=focused&&focused.dataset.assistKey,focusId=focused&&focused.id;
    const modal=root.closest('.modal'),card=root.parentElement,scroll=modal?modal.scrollTop:0;card.innerHTML=dialogHtml();if(modal)modal.scrollTop=scroll;
    if(A.dialog.source)paintSource();
    if(focusKey)Array.from(document.getElementById('assistDialog').querySelectorAll('[data-assist-key]')).find(function(el){return el.dataset.assistKey===focusKey;})?.focus({preventScroll:true});
    else if(focusId)document.getElementById(focusId)?.focus({preventScroll:true});
  }
  function showDialog(dialog){
    if(!A.project||!host())return;const opened=Object.assign({project:A.project.id},dialog);A.dialog=opened;openModal(()=>{A.dialog=opened;return dialogHtml();},true);
    const root=document.getElementById('assistDialog'),modal=root&&root.closest('.modal');
    if(modal)modal.onclick=function(ev){if(ev.target===modal)closePreview();};root?.focus({preventScroll:true});
  }
  function openRecords(){showDialog({type:'records'});}
  function openPreview(el){const run=A.runs.find(function(x){return x.id===(el&&el.dataset.run)&&x.capability==='draft';})||(!el?selected('draft'):null);if(run)showDialog({type:'draft',run:run.id});}
  function openRecommendation(el){const run=A.runs.find(function(x){return x.id===el.dataset.run&&x.capability==='recommend';});if(run)showDialog({type:'recommend',run:run.id,asset:el.dataset.id});}
  function restorePreview(){if(A.dialog&&A.project&&A.dialog.project===A.project.id)showDialog(A.dialog);}
  function closePreview(){const dialog=A.dialog;A.dialog=null;closeModal();if(dialog&&A.project&&A.project.kind!=='marketing'&&dialog.project===A.project.id&&host()&&['draft','records'].includes(dialog.type))Studio.focusDraft();}
  function paintSource(){
    const panel=document.getElementById('assistSourcePanel'),source=A.dialog&&A.dialog.source;if(!panel||!source)return;
    const run=A.runs.find(function(x){return x.id===source.run;});if(!run)return;
    panel.innerHTML='<div class="assist-source-head"><span>原文依据</span>'+button('收起','hideSource',{},'sm ghost')+'</div>'+sourceHtml(run,source.id);panel.hidden=false;panel.parentElement.classList.add('has-source');
  }
  function hideSource(){const previous=A.dialog&&A.dialog.source;if(A.dialog)delete A.dialog.source;const panel=document.getElementById('assistSourcePanel');if(panel){panel.hidden=true;panel.parentElement.classList.remove('has-source');const modal=panel.closest('.modal');if(modal&&previous&&typeof previous.scroll==='number')modal.scrollTop=previous.scroll;}}
  function render(){
    const h=host(),discovery=host('projectDiscovery');if(!h)return;
    const p=A.project,m=p.kind==='marketing',angle=m?null:p.topic_angle,scene=scopedWorkflow(p),w=workflow(p);
    const used=(scene?selectedForTask(p):chosenMaterials(p,angle)).length;
    const scope=scopeFor(p.id),running=active(),recommend=selected('recommend'),drafts=A.runs.filter(function(r){return r.capability==='draft';}),latest=drafts[0],ready=drafts.filter(function(r){return r.status==='done'&&!r.applied&&!r.stale&&!r.source_stale;});
    const manuscriptState=document.getElementById('projectDraftAssistState');
    if(manuscriptState)manuscriptState.textContent=drafts.some(r=>['queued','running'].includes(r.status))?'生成中':
      ready.length?ready.length+' 份待应用':latest?.status==='failed'?'上次生成失败':drafts.length?drafts.length+' 条记录':'';
    const focusedHost=hosts().find(function(el){return el.contains(document.activeElement);}),focused=focusedHost&&document.activeElement?.dataset.assistKey;
    const error=A.error?'<div class="assist-warning assist-workspace-error" role="alert"><span>'+e(A.error)+'</span>'+(A.loadFailed?button('重新加载','retry',{},'sm ghost'):'')+'</div>':'';
    const discoveryLabel=scene?(recommend?'重新查找素材':'从图书找素材'):m?(recommend?'重新发现材料':'发现可用材料'):(recommend?'重新分析选题':'分析选题');
    const draftLabel=scene?(p.draft?'重新生成'+w.draft:w.generate):angle?'按选定切口组稿':p.draft||drafts.length?'生成新建议':m?'生成营销建议':'生成选题建议';
    if(m){
      if(discovery)discovery.innerHTML=error+marketingDiscovery(recommend);
      h.innerHTML=error+marketingGeneration();
    }else{
    if(discovery)discovery.innerHTML=error+'<div class="assist-workspace-toolbar"><div class="assist-toolbar-copy"><h2>'+(scene?'可用于'+e(w.title)+'的素材':m?'推荐材料':'选题分析')+'</h2><p>'+(scene?'这些是系统从图书中找到的候选内容。选入后，才会用于生成'+e(w.draft)+'。':m?'先看理由，按需展开内容与原文依据。':'根据书库材料比较切口、可写范围和资料缺口。')+'</p></div><div class="assist-toolbar-actions">'+(A.dialog&&A.dialog.project===p.id&&['recommend','source'].includes(A.dialog.type)&&!document.getElementById('assistDialog')?button('返回材料详情','restorePreview',{},'ghost'):'')+button(running?'任务处理中…':discoveryLabel,'start',{cap:'recommend'},'primary',running||A.busy||!(state.books||[]).length)+'</div></div>'+
      scopeControls(p,scope)+recommendResult(recommend);
    h.innerHTML=error+'<div class="assist-workspace-toolbar assist-generation-bar"><div class="assist-toolbar-copy"><h2>'+(scene?'生成'+e(w.draft):'生成建议')+'</h2><p>'+(angle?'已选切口 <strong>'+e(plainSummary(angle.title))+'</strong> · ':'已采用 ')+used+' 条材料'+(latest?' · 最近一次'+e(runLabel(latest)):' · 应用后写入工作稿')+'</p></div><div class="assist-toolbar-actions">'+(!used?button('选择材料','editMaterials',{},'ghost'):'')+button('生成记录'+(drafts.length?' · '+drafts.length:''),'openRecords',{},'ghost')+(scene&&ready.length?button('预览'+e(w.draft),'openPreview',{run:ready[0].id},'primary',running||A.busy):button(running?'任务处理中…':e(draftLabel),'start',{cap:'draft'},'primary',running||A.busy||!used))+'</div></div>'+
      (ready.length?'<div class="assist-ready-line"><span>'+(scene?e(w.draft)+'已生成。预览确认后，点击“应用到工作稿”继续编辑。':ready.length+' 份建议待应用；当前工作稿保持原样。')+'</span>'+button(scene?'查看'+e(w.draft):'预览最新建议','openPreview',{run:ready[0].id},'sm ghost')+'</div>':'')+
      (latest&&!latest.applied&&latest.status==='failed'?'<p class="assist-generation-error">'+e(failedDraftReason(latest)||'最近一次生成未完成。当前工作稿仍保留。')+'</p>':'')+
      (A.dialog&&A.dialog.project===p.id&&!document.getElementById('assistDialog')?'<div class="assist-return-preview">'+button('返回刚才查看的内容','restorePreview',{},'sm ghost')+'</div>':'');
    }
    if(focused)Array.from(focusedHost.querySelectorAll('[data-assist-key]')).find(function(x){return x.dataset.assistKey===focused;})?.focus({preventScroll:true});
    paintDialog();
    Studio.updateAssistProgress?.(p.id,workflowSummary());
  }
  function schedule(){clearTimeout(A.poll);if(!active()||!host())return;A.poll=setTimeout(function(){load(A.project.id,A.epoch);},2200);}
  async function load(pid,epoch){
    const seq=++A.loadSeq;
    try{
      const d=await jget('/api/projects/'+pid+'/assist');if(seq!==A.loadSeq||!here(pid,epoch))return;
      const changed=JSON.stringify(A.runs)!==JSON.stringify(d.runs||[]),failed=A.loadFailed;A.runs=d.runs||[];
      if(failed){A.error='';A.loadFailed=false;}
      if(!Object.prototype.hasOwnProperty.call(A.scopes,pid)){const last=A.runs.find(function(r){return r.capability==='recommend';});if(last)A.scopes[pid]=(last.snapshot||{}).book_codes||[];}
      if(changed||failed)render();
      schedule();
    }catch(err){if(seq!==A.loadSeq||!here(pid,epoch))return;A.error='生成记录暂时无法更新：'+err.message+'。已有工作稿仍保留。';A.loadFailed=true;render();}
  }
  function mount(p){
    const changed=!A.project||A.project.id!==p.id;
    if(changed){if(document.getElementById('assistDialog'))closeModal();A.dialog=null;A.runs=[];A.choice={};}
    A.project=p;A.busy=false;A.dirty=false;A.error='';A.loadFailed=false;const epoch=++A.epoch;clearTimeout(A.poll);render();load(p.id,epoch);
  }
  async function prepare(cap){
    const p=await Studio.assistContext();if(!p)throw new Error('项目尚未加载');
    const b=p.brief||{},topicOnly=p.kind==='editorial'&&(cap==='recommend'||p.topic_angle);
    const required=topicOnly?['topic']:['topic','audience','goal'];
    if(required.some(key=>!String(b[key]||'').trim())){
      editBrief();throw new Error(topicOnly?'请先填写选题主题':p.kind==='marketing'?'请先填写主题、内容给谁看和具体目标':'请先在任务定义中填写主题、目标读者和工作目标');
    }
    return p;
  }
  async function start(el){
    if(A.busy||active()||!A.project)return;
    const pid=A.project.id,epoch=A.epoch,cap=el.dataset.cap;
    if(!['recommend','draft'].includes(cap))return;
    if(cap==='recommend'&&Studio.showMaterialMode)Studio.showMaterialMode('recommended');
    A.busy=true;A.error='';render();
    try{
      const p=await prepare(cap);if(!here(pid,epoch)||p.id!==pid)return;A.project=p;
      const d=await post('/api/projects/'+pid+'/assist',{revision:p.revision,capability:cap,book_codes:scopeFor(pid)});
      if(!here(pid,epoch))return;
      if(d.run){A.choice[cap]=d.run.id;A.runs=[d.run].concat(A.runs.filter(r=>r.id!==d.run.id));}
      A.sections[pid]=Object.assign({},A.sections[pid],{[cap]:true});
      A.busy=false;render();
      if(cap==='draft'&&p.kind==='marketing')goToDraft();
      toast(cap==='draft'?(p.kind==='marketing'?'正在生成'+workflow(p).draft:'正在根据任务与材料生成讨论稿'):p.kind==='editorial'?'正在比较选题切口':'正在从图书查找素材');
      await load(pid,epoch);
    }catch(err){if(!here(pid,epoch))return;A.busy=false;A.error=err.message;render();toast(err.message,true);}
  }
  function cacheRecovery(form){
    const run=A.runs.find(r=>r.id===form.dataset.recoveryRun);
    if(!canEditRecovery(run))return null;
    const data=new FormData(form);
    const fields=run.recovery_draft.map((row,index)=>({channel:row.channel,
      title:String(data.get('title-'+index)||''),body:String(data.get('body-'+index)||''),
      ending:String(data.get('ending-'+index)||'')}));
    try{sessionStorage.setItem(recoveryKey(run),JSON.stringify(fields));}catch(_){}
    return fields;
  }
  async function recheck(form){
    const run=A.runs.find(r=>r.id===form.dataset.recoveryRun);
    if(A.busy||active()||!A.project||!canEditRecovery(run))return;
    const fields=cacheRecovery(form),pid=A.project.id,epoch=A.epoch;
    A.busy=true;A.error='';
    form.querySelectorAll('fieldset,button').forEach(node=>node.disabled=true);
    try{
      const p=await prepare('draft');if(!here(pid,epoch)||p.id!==pid)return;
      const d=await post('/api/projects/'+pid+'/assist',{revision:p.revision,capability:'draft',
        recovery_run_id:run.id,recovery_draft:fields});
      if(!here(pid,epoch))return;
      if(d.run){A.choice.draft=d.run.id;A.runs=[d.run].concat(A.runs.filter(row=>row.id!==d.run.id));}
      A.busy=false;closePreview();render();
      toast('正在检查修改稿');await load(pid,epoch);
    }catch(err){
      if(!here(pid,epoch))return;
      A.busy=false;A.error=err.message;render();paintDialog();toast(err.message,true);
    }
  }
  function triggerDraft(){return start({dataset:{cap:'draft'}});}
  function previewLatest(){
    const run=A.runs.find(r=>r.capability==='draft'&&r.status==='done'&&!r.applied&&!r.stale&&!r.source_stale);
    if(run)openPreview({dataset:{run:run.id}});
  }
  function openCollected(el){Studio.openMaterialDetail(el);}
  async function toggleMaterial(el){
    if(!A.project||A.busy||A.dirty||active())return;
    const id=el.dataset.id,item=A.project.items?.find(x=>x.asset_id===id);
    if(item?.status!=='adopted'&&el.dataset.run)return adopt({dataset:{...el.dataset,confirm:'false'}});
    if(!item||item.status!=='adopted'&&(item.stale||['rejected','missing'].includes(item.current_status)))return;
    const pid=A.project.id,epoch=A.epoch,adopted=item.status==='adopted';
    A.busy=true;A.error='';render();
    try{
      await Studio.assistMutate({action:'update_item',asset_id:id,status:adopted?'selected':'adopted'},true,pid);
      if(!A.project||A.project.id!==pid||!host())return;
      A.busy=false;render();toast(adopted?'已取消选用':'已选用这条素材');
    }catch(err){if(!here(pid,epoch))return;A.busy=false;A.error=err.message;render();toast(err.message,true);}
  }
  function source(el){
    const run=A.runs.find(function(r){return r.id===el.dataset.run;})||A.runs.find(function(r){return !!materials(r)[el.dataset.id];});
    if(!run){currentSource(el);return;}
    if(A.dialog&&A.dialog.type==='draft'&&document.getElementById('assistDialog')){
      const modal=document.getElementById('assistDialog').closest('.modal');A.dialog.source={run:run.id,id:el.dataset.id,scroll:modal?modal.scrollTop:0};paintSource();document.getElementById('assistSourceTitle')?.focus({preventScroll:true});document.getElementById('assistSourcePanel')?.scrollIntoView({behavior:'smooth',block:'nearest'});return;
    }
    showDialog({type:'source',run:run.id,asset:el.dataset.id});
  }
  async function currentSource(el){
    const dialog=A.dialog,pid=A.project&&A.project.id;
    await Studio.detail({dataset:{id:el.dataset.id,purpose:A.project?A.project.title:''}});
    if(!dialog||A.dialog!==dialog||!A.project||A.project.id!==pid||!host())return;
    const card=document.querySelector('#modalRoot .modal-card');
    if(card&&!document.getElementById('assistDialog'))card.insertAdjacentHTML('afterbegin','<div class="assist-source-return">'+button('← 返回建议与依据','restorePreview',{},'sm ghost')+'</div>');
    render();
  }
  function openSource(el){
    if(A.dialog&&document.getElementById('assistDialog')){
      const url='#/book/'+encodeURIComponent(el.dataset.code||'')+'/text/'+encodeURIComponent(el.dataset.anchor||'');window.open(url,'_blank','noopener');return;
    }
    closeModal();go('book',el.dataset.code,'text',el.dataset.anchor);
  }
  async function adoptAngle(el){
    const run=A.runs.find(r=>r.id===el.dataset.run),index=Number(el.dataset.angle);
    const angle=run?.result?.topic_angles?.[index];
    if(A.project?.kind!=='editorial'||run?.status!=='done'||!angle?.asset_ids?.length||
      run.topic_angle_choices_stale||topicAngleBlocker(angle)||A.dirty||A.busy||active())return;
    const pid=A.project.id,epoch=A.epoch;A.busy=true;A.error='';render();
    try{
      const result=await Studio.assistMutate({action:'adopt_topic_angle',run_id:run.id,angle_index:index},true,pid);
      if(!A.project||A.project.id!==pid||!host())return;
      A.busy=false;render();
      toast('已选定切口，'+(result.project.topic_angle?.asset_ids||[]).length+' 条材料可用于组稿');
      host('projectDiscovery')?.querySelector('.assist-topic-card.is-current .assist-topic-actions button')?.focus({preventScroll:true});
    }catch(err){if(!here(pid,epoch))return;A.busy=false;A.error=err.message;render();toast(err.message,true);await load(pid,epoch);}
  }
  function goToDraft(){
    Studio.openProjectSection('results');
    const details=document.getElementById('projectDraftAssist');
    if(details)details.open=true;
    host()?.scrollIntoView({behavior:'instant',block:'start'});
    host()?.querySelector('[data-cap="draft"]:not(:disabled)')?.focus({preventScroll:true});
  }
  async function adopt(el){
    const {id,run:runId}=el.dataset,confirm=el.dataset.confirm==='true';
    const run=A.runs.find(function(r){return r.id===runId;}),existing=A.project?.items?.find(function(i){return i.asset_id===id;});
    if(!A.project||!canChooseRecommendation(run,existing)||(!confirm&&existing?.status==='adopted'))return;
    const pid=A.project.id,epoch=A.epoch;A.busy=true;A.error='';render();
    try{
      const result=await Studio.assistMutate({action:'adopt_recommendation',run_id:runId,asset_id:id,confirm_content:confirm},true,pid);
      if(!A.project||A.project.id!==pid||!host())return;
      A.busy=false;render();
      const item=result.project.items.find(function(x){return x.asset_id===id;});
      toast(scopedWorkflow()?'已选入'+workflow().noun+'，可继续选素材或生成初稿':item.current_status==='approved'&&!item.stale?'内容已核对，已在本项目采用':'已在本项目采用，内容待核对');
    }catch(err){if(!here(pid,epoch))return;A.busy=false;A.error=err.message;render();toast(err.message,true);}
  }
  async function apply(el){
    const run=A.runs.find(function(r){return r.id===el.dataset.run;});if(!A.project||!canApply(run))return;
    const pid=A.project.id,epoch=A.epoch,dialog=A.dialog;A.busy=true;A.error='';render();
    try{
      await Studio.assistMutate({action:'apply_generation',run_id:run.id},true,pid);
      if(A.project&&A.project.id===pid&&host()){
        A.busy=false;if(A.dialog===dialog){A.dialog=null;if(document.getElementById('assistDialog'))closeModal();}
        toast('建议已应用到当前工作稿，请继续修订并审核');Studio.focusDraft();
      }
    }catch(err){if(!here(pid,epoch))return;A.busy=false;A.error=err.message;render();toast(err.message,true);await load(pid,epoch);}
  }
  function scopeChange(){const h=host('projectDiscovery');if(!A.project||!h)return;const pid=A.project.id;A.scopes[pid]=Array.from(h.querySelectorAll('.assist-book-options input:checked')).map(function(x){return x.value;});try{sessionStorage.setItem('project-assist-scope:'+pid,JSON.stringify(A.scopes[pid]));}catch(_){}A.scopeOpen[pid]=true;render();}
  function scopeToggle(el){if(A.project&&el.isConnected)A.scopeOpen[A.project.id]=el.open;}
  function sectionToggle(el){if(!A.project||!el.isConnected)return;const section=A.sections[A.project.id]||(A.sections[A.project.id]={});section[el.dataset.cap]=el.open;}
  function selectRun(el){A.choice[el.dataset.cap]=el.value;render();}
  function projectEdited(){if(host()&&!A.dirty){A.dirty=true;render();}}
  function projectSaved(p,dirty){if(!p||!A.project||A.project.id!==p.id||!host())return;A.project=p;A.dirty=!!dirty;render();load(p.id,A.epoch);}
  function editBrief(){if(Studio.editProjectBrief){Studio.editProjectBrief();return;}Studio.openProjectSection('task');const f=document.getElementById('projectBrief');if(f){f.scrollIntoView({behavior:'smooth',block:'start'});f.querySelector('[name=topic]')?.focus({preventScroll:true});}}
  function editMaterials(el){Studio.openProjectSection('materials');if(el?.dataset.mode)Studio.showMaterialMode(el.dataset.mode);}
  function retry(){A.error='';A.loadFailed=false;render();if(A.project)load(A.project.id,A.epoch);}
  async function reuse(){if(!A.project)return;const pid=A.project.id,epoch=A.epoch;try{const p=await Studio.assistContext();if(!p||p.id!==pid||!here(pid,epoch))return;A.project=p;openModal(modalX()+'<div class="eyebrow">REUSE A WORKFLOW</div><h2>复用为新项目</h2><p class="muted">沿用任务说明，再为新的目标或读者调整。生成记录、审核结论和使用反馈保留在原项目中。</p><form id="assistReuseForm" data-project="'+e(p.id)+'" onsubmit="event.preventDefault();ProjectAssist.submitReuse(this)"><label class="studio-field"><span>新项目名称</span><input name="title" required value="'+e(p.title+' · 新项目')+'"></label><label class="studio-field"><span>复用范围</span><select name="copy_materials"><option value="false">只复用任务说明</option><option value="true">任务说明与材料一并带入，重新选择与核对</option></select></label><div class="modal-actions"><button class="btn primary" type="submit">创建可继续编辑的新项目</button></div></form>');}catch(err){toast(err.message,true);}}
  async function submitReuse(form){const b=form.querySelector('[type=submit]'),pid=form.dataset.project,epoch=A.epoch;b.disabled=true;try{const fields=Object.fromEntries(new FormData(form)),p=await Studio.assistContext();if(!p||p.id!==pid||!here(pid,epoch))throw new Error('项目已切换，请回到原项目后重新复用');const d=await post('/api/projects/'+p.id+'/reuse',{revision:p.revision,title:fields.title,copy_materials:fields.copy_materials==='true'});if(!here(pid,epoch))return;closeModal();go(d.project.kind==='marketing'?'campaigns':'projects',d.project.id);toast('已创建新项目，请调整任务定义后继续');}catch(err){b.disabled=false;toast(err.message,true);}}
  window.addEventListener('hashchange',function(){clearTimeout(A.poll);if(document.getElementById('assistDialog'))closeModal();if(A.project?.kind==='marketing'&&location.hash.split('/')[2]===A.project.id)schedule();});
  document.addEventListener('keydown',function(ev){
    const dialog=document.getElementById('assistDialog');if(!dialog)return;
    if(ev.key==='Escape'){ev.preventDefault();ev.stopImmediatePropagation();closePreview();return;}
    if(ev.key==='Tab'){const controls=Array.from(dialog.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')).filter(function(el){return el.getClientRects().length;});const first=controls[0],last=controls[controls.length-1];if(!first)return;if(ev.shiftKey&&(document.activeElement===first||document.activeElement===dialog)){ev.preventDefault();last.focus();}else if(!ev.shiftKey&&(document.activeElement===last||document.activeElement===dialog)){ev.preventDefault();first.focus();}}
  },true);
  return {editWritingNotes,reviseMaterials,mount,start,workflowSummary,triggerDraft,previewLatest,toggleMaterial,openCollected,openRecords,openPreview,openRecommendation,closePreview,restorePreview,hideSource,source,currentSource,openSource,adopt,adoptAngle,goToDraft,apply,selectChannel,channelKeydown,planningToggle,scopeChange,scopeToggle,selectRun,sectionToggle,projectEdited,projectSaved,editBrief,editMaterials,retry,reuse,submitReuse,materialTitleText,cacheRecovery,recheck};
})();
