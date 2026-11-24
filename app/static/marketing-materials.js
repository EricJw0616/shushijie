/* Bring one reusable book profile item into an explicitly chosen marketing task. */
'use strict';
window.MarketingMaterials=(function(){
  let request=0;
  const e=esc;
  function sourceId(){
    const hash=typeof location==='undefined'?'':location.hash;
    const index=hash.indexOf('?');
    return index<0?'':new URLSearchParams(hash.slice(index+1)).get('material')||'';
  }
  async function load(id){
    const a=(await jget('/api/content-assets/detail?'+new URLSearchParams({id}))).asset;
    if(!a||a.kind!=='marketing'||a.status==='rejected')throw new Error('这条营销资料已停用或无法读取，请回到图书重新选择。');
    return a;
  }
  function scopeReason(project,asset){
    if(project.kind!=='marketing'||project.status==='paused')return '项目已暂缓或不属于营销策划';
    const b=project.brief||{},task=b.marketing_task||'general';
    // General/new-book projects may intentionally collect older books as references.
    if(task==='general')return '';
    const codes=task==='reposition'?[b.source_code]:(b.target_codes||[]);
    return codes.includes(asset.code)?'':'推广图书不含这本书';
  }
  function summary(a){
    return '<div class="marketing-material-summary"><span>'+e(a.book||a.code)+'</span><p>'+e(a.text||a.title)+'</p></div>';
  }
  function banner(a,form=false){
    return '<section class="marketing-seed" aria-label="带入的营销资料"><div><strong>已带入 1 条图书营销资料</strong><p>'+(form?'填写要求后，创建项目并把资料放入候选材料。':'先选择要做的工作，再填写本次任务要求。')+'</p></div>'+summary(a)+'<p class="marketing-seed-status">尚未创建项目 · 资料保留原文出处和原有核对状态</p><a class="btn sm ghost" href="#/marketing/'+encodeURIComponent(a.code)+'">返回图书营销资料</a></section>';
  }
  async function open(el){
    const id=el.dataset.id,token=++request,origin=location.hash;
    el.disabled=true;
    try{
      const [asset,list]=await Promise.all([load(id),jget('/api/projects?kind=marketing')]);
      if(token!==request||location.hash!==origin||!el.isConnected)return;
      const ps=(list.projects||[]).filter(p=>p.kind==='marketing'&&p.status!=='paused');
      const eligible=ps.filter(p=>!scopeReason(p,asset));
      const context=typeof workflowContext==='function'?workflowContext():null;
      const options=ps.map(p=>{const reason=scopeReason(p,asset);return '<option value="'+e(p.id)+'"'+(reason?' disabled':'')+(context?.id===p.id&&!reason?' selected':'')+'>'+e(p.title)+(reason?' · '+e(reason):'')+'</option>';}).join('');
      openModal(modalX()+'<section id="marketingMaterialPicker" class="marketing-material-picker" data-asset="'+e(id)+'"><h2>用于营销策划</h2>'+summary(asset)+
        '<p class="muted">加入项目后，在候选材料中决定是否采用。</p>'+
        (ps.length?'<form onsubmit="event.preventDefault();MarketingMaterials.add(this)"><label class="studio-field"><span>加入已有营销项目</span><select name="project" required><option value="">请选择项目</option>'+options+'</select></label><button type="submit" class="btn primary"'+(!eligible.length?' disabled':'')+'>加入并查看项目材料 →</button></form>':'<p class="marketing-material-empty">还没有营销项目。可以用这条资料开始一次策划。</p>')+
        (ps.length&&!eligible.length?'<p class="marketing-material-empty">现有项目的推广图书不匹配，可以为这本书新建项目。</p>':'')+
        '<div class="marketing-material-new"><h3>开始一次新的营销工作</h3><p>带入资料和来源图书，填写主题、受众与目标后再创建。</p><a class="btn '+(eligible.length?'ghost':'primary')+'" href="#/campaigns?material='+encodeURIComponent(id)+'" onclick="closeModal()">用这条资料新建营销项目 →</a></div><p data-material-feedback role="status" hidden></p></section>',true);
      const panel=document.getElementById('marketingMaterialPicker');if(panel)panel.materialAsset=asset;
    }catch(err){if(token===request&&location.hash===origin)toast(err.message,true);}
    finally{el.disabled=false;}
  }
  async function add(form){
    const panel=form.closest('#marketingMaterialPicker');
    if(!panel||panel.dataset.busy)return;
    const pid=form.elements.project.value;if(!pid)return;
    const id=panel.dataset.asset,feedback=panel.querySelector('[data-material-feedback]');
    panel.dataset.busy='true';panel.setAttribute('aria-busy','true');
    panel.querySelectorAll('button,select').forEach(x=>x.disabled=true);
    feedback.hidden=false;feedback.textContent='正在加入项目…';
    try{
      const [asset,result]=await Promise.all([load(id),jget('/api/projects/'+encodeURIComponent(pid))]);
      if(!panel.isConnected)return;
      const before=result.project,reason=scopeReason(before,asset);if(reason)throw new Error(reason+'，请重新选择项目。');
      const existing=(before.items||[]).find(i=>i.asset_id===id);
      let project=before;
      if(!existing)project=(await post('/api/projects/'+encodeURIComponent(pid),{action:'add_asset',revision:before.revision,asset_id:id})).project;
      if(!existing)window.Studio?.advanceLocalDraftAfterRelation?.(pid,before.revision,project.revision);
      const notFit=existing?.status==='not_fit';
      toast(notFit?'这条资料在本项目中标为“不采用”，可在素材与出处中查看或调整。':existing?'这条资料已在项目中，已打开项目材料。':'资料已加入候选材料，下一步决定是否采用。');
      if(panel.isConnected){
        closeModal();
        if(notFit)window.Studio?.prepareMarketingMaterialList?.(pid,id);
        go('campaigns',pid,notFit?'sources':'materials');
      }
    }catch(err){if(panel.isConnected){feedback.textContent=err.message;feedback.classList.add('marketing-material-error');}}
    finally{delete panel.dataset.busy;panel.removeAttribute('aria-busy');panel.querySelectorAll('button,select').forEach(x=>x.disabled=false);}
  }
  return {open,add,sourceId,load,banner,scopeReason};
})();
