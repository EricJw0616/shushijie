/* Start a marketing plan or a scene directly. Unsubmitted requirements stay in this browser tab. */
'use strict';
window.MarketingEntry=(function(){
  const M={host:null,scene:'',pending:new Set(),drafts:{},seed:null,request:0,attempts:{}};
  const PREFIX='bookworld.marketing-new:';
  const PLANS={reposition:'为一本老书找传播方向',theme:'围绕一个主题组合多本书',general:'通用营销 / 新书上市'};
  const e=esc;
  const valid=scene=>scene==='planning'||Object.hasOwn(MarketingScenes.scenes,scene);
  const suffix=()=>M.seed?'?material='+encodeURIComponent(M.seed.id):'';
  const homeUrl=()=>'#/campaigns'+suffix();
  const url=scene=>'#/campaigns/new/'+encodeURIComponent(scene)+suffix();
  const draftKey=scene=>scene+(M.seed?':'+M.seed.id:'');
  function hasSavedDraft(scene){
    const key=draftKey(scene);
    if(M.drafts[key])return true;
    try{return !!sessionStorage.getItem(PREFIX+key);}catch(_){return false;}
  }
  function read(scene){
    const key=draftKey(scene);
    if(M.drafts[key])return M.drafts[key];
    try{const value=JSON.parse(sessionStorage.getItem(PREFIX+key)||'null');if(value&&typeof value==='object')return value;}catch(_){}
    return M.seed?{primary_code:M.seed.code,target_codes:[M.seed.code],marketing_task:'general'}:{};
  }
  function values(form){
    const v={additional_codes:[],target_codes:[]};
    Array.from(form.elements).forEach(input=>{if(!input.name)return;if(input.type==='checkbox'){if(input.checked)(v[input.name]||(v[input.name]=[])).push(input.value);}else v[input.name]=input.value;});
    return v;
  }
  function remember(){
    const form=document.getElementById('marketingNewForm');
    if(!form||form.dataset.submitted||form.closest('#marketingEntry')!==M.host||M.pending.has(draftKey(M.scene)))return;
    const value=values(form),key=draftKey(M.scene);M.drafts[key]=value;
    try{sessionStorage.setItem(PREFIX+key,JSON.stringify(value));}catch(_){}
    const note=form.querySelector('[data-draft-note]');if(note)note.textContent='填写内容已暂存';
  }
  function beforeNavigate(){remember();}
  function field(label,name,value,placeholder,textarea=false,required=false,describedBy=''){
    return '<label class="studio-field"><span>'+e(label)+(required?' <em aria-hidden="true">*</em>':'')+'</span>'+
      (textarea?'<textarea rows="3"':'<input type="text"')+' name="'+name+'"'+(name==='writing_notes'?' maxlength="4000"':'')+(required?' required':'')+(describedBy?' aria-describedby="'+e(describedBy)+'"':'')+' placeholder="'+e(placeholder)+'"'+
      (textarea?'>'+e(value||'')+'</textarea>':' value="'+e(value||'')+'">')+'</label>';
  }
  function bookOptions(selected,blank){
    const books=state.books||[],missing=selected&&!books.some(b=>b.code===selected);
    return '<option value="">'+e(blank)+'</option>'+(missing?'<option value="'+e(selected)+'" selected>原选图书已不在书库，请重新选择</option>':'')+
      books.map(b=>'<option value="'+e(b.code)+'"'+(b.code===selected?' selected':'')+'>'+e(b.book)+'</option>').join('');
  }
  function bookChecks(name,selected){
    return '<div class="marketing-entry-books">'+(state.books||[]).map(b=>'<label><input type="checkbox" name="'+name+'" value="'+e(b.code)+'"'+(Array.isArray(selected)&&selected.includes(b.code)?' checked':'')+'><span>'+e(b.book)+'</span></label>').join('')+'</div>';
  }
  function home(v){
    crumb('<b>营销创作</b>');
    const icons=['文','影','记','讲','聚'];
    const channels=Object.entries(MarketingScenes.scenes).map(([key,item],index)=>`
      <a class="marketing-entry-scene" href="${url(key)}">
        <span class="marketing-entry-icon" aria-hidden="true">${icons[index]}</span>
        <div class="marketing-entry-scene-copy"><h3>${e(item.title)}</h3><p>${e(item.output)}</p></div>
        <span class="marketing-entry-arrow" aria-hidden="true">↗</span>
      </a>`).join('');
    v.innerHTML=`<main id="marketingEntry" class="marketing-entry marketing-entry-home">
      <header class="marketing-entry-heading"><h1>营销创作</h1><a class="btn ghost" href="#/records/marketing">我的营销项目 →</a></header>
      ${M.seed?MarketingMaterials.banner(M.seed):''}
      <a class="marketing-entry-scene marketing-entry-plan" href="${url('planning')}">
        <span class="marketing-entry-icon" aria-hidden="true">策</span>
        <div class="marketing-entry-scene-copy"><h2>营销整体方案</h2><p>推广目标、核心卖点与渠道安排</p></div>
        <span class="marketing-entry-start">开始策划 <span class="marketing-entry-arrow" aria-hidden="true">↗</span></span>
      </a>
      <section aria-labelledby="marketingChannelsTitle">
        <h2 class="marketing-entry-channel-title" id="marketingChannelsTitle">渠道内容</h2>
        <div class="marketing-entry-scenes">${channels}</div>
      </section>
    </main>`;
  }
  function newPage(v,scene){
    const data=read(scene),planning=scene==='planning',title=planning?'营销整体方案':MarketingScenes.label(scene);
    const plan=Object.hasOwn(PLANS,data.marketing_task)?data.marketing_task:'reposition';
    const guide=MarketingScenes.audienceGuide(scene);
    crumb('<a href="'+homeUrl()+'">营销创作</a><span>/</span><b>'+e(title)+'</b>');
    v.innerHTML='<main id="marketingEntry" class="marketing-entry marketing-entry-new"><a class="marketing-entry-back" href="'+homeUrl()+'">← 返回营销创作</a><header class="marketing-entry-heading"><div><span class="marketing-entry-scene-label">'+e(title)+'</span><h1>'+(planning?'这次推广准备怎么做？':'这份内容要写什么？')+'</h1><p>'+ (M.seed?'填写要求后创建项目，所带资料会进入候选材料。':'填写要求，下一步选择书中素材。') +'</p></div><span class="marketing-entry-step">1 / 4 · '+(planning?'推广要求':'内容要求')+'</span></header>'+
      (M.seed?MarketingMaterials.banner(M.seed,true):'')+'<form id="marketingNewForm" class="marketing-entry-form studio-card" oninput="MarketingEntry.remember()" onchange="MarketingEntry.changed()" onsubmit="event.preventDefault();MarketingEntry.submit(this)">'+
      (planning?'<label class="studio-field"><span>策划方向</span><select name="marketing_task">'+Object.entries(PLANS).map(([key,label])=>'<option value="'+key+'"'+(plan===key?' selected':'')+'>'+e(label)+'</option>').join('')+'</select></label>':'')+
      '<div data-entry-group="single"><label class="studio-field"><span data-primary-label>推广哪本书 <em aria-hidden="true">*</em></span><select name="primary_code">'+bookOptions(data.primary_code,plan==='general'&&planning?'待出版新书':'请选择图书')+'</select></label></div>'+
      (planning?'<fieldset class="marketing-entry-book-group" data-entry-group="theme"><legend>推广图书 · 至少选择两本</legend>'+bookChecks('target_codes',data.target_codes)+'</fieldset>':'')+
      field('内容主题','topic',data.topic,'例如：从书中挑一个读者关心的问题',false,true)+
      '<div class="marketing-entry-requirements">'+field(guide.label,'audience',data.audience,guide.placeholder,false,true,'marketingAudienceHint')+'<p class="marketing-audience-hint" id="marketingAudienceHint">'+e(guide.hint)+'</p>'+MarketingPurpose.fields(data)+field(guide.goalLabel,'goal',data.goal,guide.goalPlaceholder,true,true)+'</div>'+
      (planning?'<div data-entry-group="new-book">'+field('已确认的新书资料','new_book_brief',data.new_book_brief,'填写已确认的内容、定位和特点。',true)+'</div>':'')+
      '<details class="marketing-entry-more"'+(data.title||data.writing_notes||(data.additional_codes||[]).length?' open':'')+'><summary>更多设置（选填）</summary>'+MarketingPurpose.readers(data)+field(guide.notesLabel,'writing_notes',data.writing_notes,guide.notesPlaceholder,true)+field('项目名称','title',data.title,'留空时使用内容主题')+
      (planning?field('计划使用的渠道','channel',data.channel,'例如：公众号、书店活动'):'<fieldset class="marketing-entry-book-group"><legend>补充其他图书</legend><p>需要组合多本书时再选择；已选的主书不必重复勾选。</p>'+bookChecks('additional_codes',data.additional_codes)+'</fieldset>')+'</details>'+
      '<p class="marketing-entry-error" role="alert" hidden></p><footer class="marketing-entry-form-footer"><a class="btn ghost" href="'+homeUrl()+'">返回营销创作</a><span data-draft-note>'+(hasSavedDraft(scene)?'已恢复上次填写的内容':'')+'</span><button type="submit" class="btn primary">'+(M.seed?'创建项目并带入资料 →':'下一步：选择素材 →')+'</button></footer></form></main>';
    M.host=document.getElementById('marketingEntry');syncGroups();
    if(!(state.books||[]).length){const f=document.getElementById('marketingNewForm');f.querySelector('[data-entry-group="single"]').insertAdjacentHTML('beforeend','<p class="marketing-entry-empty-book">书库暂无图书，可先填写要求，再到“来源图书”导入。</p>');}
    if(M.pending.has(draftKey(scene)))setBusy(document.getElementById('marketingNewForm'),true);
  }
  function syncGroups(){
    const form=document.getElementById('marketingNewForm');if(!form)return;
    const planning=M.scene==='planning',task=planning?form.elements.marketing_task.value:'channel';
    form.querySelectorAll('[data-entry-group]').forEach(group=>{
      group.hidden=group.dataset.entryGroup==='theme'?task!=='theme':group.dataset.entryGroup==='single'?task==='theme':task!=='general';
      group.querySelectorAll('input,select,textarea').forEach(input=>{input.disabled=group.hidden;});
    });
    const select=form.elements.primary_code;
    if(select?.options.length)select.options[0].textContent=task==='general'?'待出版新书':'请选择图书';
    const label=form.querySelector('[data-primary-label]');if(label)label.innerHTML=task==='general'?'推广图书（已有图书时选择）':'推广哪本书 <em aria-hidden="true">*</em>';
  }
  function changed(){syncGroups();remember();}
  function setBusy(form,busy){
    if(!form)return;form.setAttribute('aria-busy',String(busy));
    form.querySelectorAll('input,select,textarea,button').forEach(control=>control.disabled=busy);
    if(!busy)syncGroups();
    const submit=form.querySelector('[type=submit]');submit.textContent=busy?'正在创建…':M.seed?'创建项目并带入资料 →':'下一步：选择素材 →';
  }
  function error(form,message){const node=form.querySelector('[role=alert]');node.hidden=false;node.textContent=message;node.scrollIntoView({block:'nearest'});}
  async function submit(form){
    const scene=M.scene,key=draftKey(scene),seed=M.seed;if(form.dataset.submitted||M.pending.has(key)||form.closest('#marketingEntry')!==M.host)return;
    remember();const data=values(form),planning=scene==='planning',task=planning?data.marketing_task:'channel',known=new Set((state.books||[]).map(b=>b.code));
    if(!['topic','audience','goal'].every(k=>String(data[k]||'').trim()))return error(form,'请填写内容主题、内容给谁看和希望谁做什么。');
    const targets=task==='theme'?data.target_codes:task==='channel'?[...new Set([data.primary_code,...data.additional_codes].filter(Boolean))]:[];
    const source=task==='reposition'||task==='general'?data.primary_code||'':'';
    if(targets.some(c=>!known.has(c))||(source&&!known.has(source)))return error(form,'原选图书已不在书库，请重新选择。');
    if(task==='channel'&&!data.primary_code)return error(form,'请选择要推广的图书。');
    if(task==='reposition'&&!source)return error(form,'请选择要推广的图书。');
    if(task==='theme'&&targets.length<2)return error(form,'跨书主题请至少选择两本图书。');
    if(task==='general'&&!source&&!String(data.new_book_brief||'').trim())return error(form,'请填写已确认的新书资料，或选择书库中的图书。');
    if(seed&&!(task==='theme'||task==='channel'?targets:[source]).includes(seed.code))return error(form,'带入资料来自《'+seed.book+'》，请将它保留在本次推广图书中。');
    const body={kind:'marketing',title:(String(data.title||'').trim()||data.topic.trim()).slice(0,160),brief:{topic:data.topic.trim(),audience:data.audience.trim(),goal:data.goal.trim(),...MarketingPurpose.values(data),writing_notes:String(data.writing_notes||'').trim(),marketing_task:task,source_code:source,target_codes:targets,channels:planning?[]:[scene],channel:planning?data.channel||'':scene,new_book_brief:task==='general'?data.new_book_brief||'':''}};
    if(seed){
      body.marketing_asset_id=seed.id;
      const fingerprint=JSON.stringify(body),storageKey=PREFIX+key+':attempt';
      let attempt=M.attempts[key];
      if(!attempt)try{attempt=JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch(_){}
      if(!attempt||attempt.fingerprint!==fingerprint)attempt={fingerprint,id:crypto.randomUUID()};
      M.attempts[key]=attempt;try{sessionStorage.setItem(storageKey,JSON.stringify(attempt));}catch(_){}
      body.request_id=attempt.id;
    }
    M.pending.add(key);setBusy(form,true);const host=M.host;
    try{
      const result=await post('/api/projects',body);if(!result.project?.id)throw new Error(result.error||'创建未完成，请重试。');
      form.dataset.submitted='true';delete M.drafts[key];delete M.attempts[key];
      try{sessionStorage.removeItem(PREFIX+key);sessionStorage.removeItem(PREFIX+key+':attempt');}catch(_){}
      if(M.host===host&&document.getElementById('marketingNewForm')===form){go('campaigns',result.project.id,'materials');}
      else toast('营销项目已创建，可在“我的营销项目”继续。');
    }catch(err){if(form.isConnected)error(form,err.message||'创建失败，填写内容已保留。');else toast(err.message||'创建失败，填写内容已保留。',true);}
    finally{M.pending.delete(key);if(form.isConnected&&!form.dataset.submitted)setBusy(form,false);}
  }
  async function render(v,step,scene){
    remember();M.host=null;M.scene='';M.seed=null;v.classList.add('studio-view');
    const ticket=++M.request,id=window.MarketingMaterials?.sourceId()||'',origin=typeof location==='undefined'?'':location.hash;
    if(id){
      v.innerHTML=loading('正在带入营销资料');
      try{
        const seed=await MarketingMaterials.load(id);
        if(ticket!==M.request||location.hash!==origin)return;
        M.seed=seed;
      }catch(err){if(ticket===M.request&&location.hash===origin)v.innerHTML='<div class="studio-empty"><h2>暂时无法带入这条资料</h2><p>'+e(err.message)+'</p><a class="btn ghost" href="#/marketing">返回图书营销资料</a></div>';return;}
    }
    if(step==='new'&&valid(scene)){M.scene=scene;newPage(v,scene);}
    else{home(v);M.host=document.getElementById('marketingEntry');}
  }
  window.addEventListener('pagehide',remember);
  return {render,beforeNavigate,remember,changed,submit};
})();
