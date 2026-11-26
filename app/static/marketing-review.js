/* Compare the original, save paragraph proofreading, then review the material. */
'use strict';
window.MarketingReview=(function(){
  const books=new Map(),sessions=new Map();let request=0,guide=null,sequence=0;
  const e=esc,key=code=>'marketing-source-guide-v1:'+code;
  function get(code){return books.get(code)||{items:[],message:''};}
  function checkpoint(code){
    if(sessions.has(code))return sessions.get(code);
    try{const saved=JSON.parse(sessionStorage.getItem(key(code))||'null');if(saved?.items?.length&&saved.code===code){sessions.set(code,saved);return saved;}}catch(_){}
    return null;
  }
  function remember(g){
    const saved={code:g.code,items:g.items,index:g.index,outcomes:g.outcomes,draft:g.editing&&g.segment?{anchor:g.segment.anchor,revision:g.segment.revision,text:g.draft}:null};
    sessions.set(g.code,saved);try{sessionStorage.setItem(key(g.code),JSON.stringify(saved));}catch(_){}
  }
  function forget(code){sessions.delete(code);try{sessionStorage.removeItem(key(code));}catch(_){} }
  function params(){return parse().extra;}
  function backUrl(code,id){return '#/marketing/'+encodeURIComponent(code)+(id?'?issue='+encodeURIComponent(id):'');}
  function returnLink(code){
    const q=params();if(q?.get('f')!=='marketing')return '';
    return '<a class="btn sm ghost marketing-review-return" href="'+e(backUrl(code,q.get('mid')||''))+'">← 返回营销资料继续处理</a>';
  }
  function sourceUrl(item,s){return '#/book/'+encodeURIComponent(item.code)+'/text/'+encodeURIComponent(s.anchor||'')+'?'+new URLSearchParams({k:'quote',t:s.quote||'',f:'marketing',mid:item.legacy_id||''});}
  function reportUrl(item){return '#/report/'+encodeURIComponent(item.code)+'?'+new URLSearchParams({f:'marketing',mid:item.legacy_id||''});}
  function rowAction(code,id){return get(code).items.some(x=>x.legacy_id===id)?'<button type="button" class="btn xs ghost" data-id="'+e(id)+'" onclick="MarketingReview.start(this.dataset.id)">逐步核对 →</button>':'';}
  function panel(code){
    if(guide&&(guide.code!==code||guide.hash!==location.hash)){guide=null;++sequence;}
    if(guide?.code===code)return wizard(guide);
    const d=get(code),saved=checkpoint(code);
    if(!d.items.length&&!d.message&&!saved)return '';
    return '<section class="marketing-review-problems marketing-guide-start" aria-labelledby="marketingProblemsTitle" tabindex="-1" id="marketingReviewProblems"><div><h2 id="marketingProblemsTitle">'+(saved?'继续完成资料核对':d.items.length?d.items.length+' 条资料需要核对来源':'本次确认未完成')+'</h2><p>'+e(d.items.length||saved?'按提示完成：对照原版 → 保存原文核对 → 确认这条资料。每次只处理一条。':d.message)+'</p>'+(d.message&&d.items.length?'<p class="marketing-guide-message">'+e(d.message)+'</p>':'')+'</div><div class="marketing-review-actions">'+(d.items.length||saved?'<button type="button" class="btn primary" onclick="MarketingReview.start()">'+(saved?'继续核对':'开始核对')+' →</button>':'')+'<button type="button" class="btn sm ghost" onclick="MarketingReview.refresh(true)">重新检查</button></div></section>';
  }
  function button(label,action,primary=false,disabled=false){return '<button type="button" class="btn '+(primary?'primary':'ghost')+'" onclick="MarketingReview.'+e(action)+'"'+(disabled?' disabled':'')+'>'+label+'</button>';}
  function wizard(g){
    const c=g.context||{},s=g.segment,done=g.stage==='done',receipt=g.stage==='saved',stage=g.stage==='material'?2:receipt||done?3:1;
    let html='<section class="marketing-guide" id="marketingReviewProblems" aria-labelledby="marketingGuideTitle" aria-busy="'+!!g.busy+'" tabindex="-1"><header class="marketing-guide-heading"><div><span class="marketing-guide-count">'+(done?'本轮核对结束':'资料 '+(g.index+1)+' / '+g.items.length)+'</span><h2 id="marketingGuideTitle" tabindex="-1">'+(done?'处理进度已保存':receipt?'这条资料已处理':'跟着提示完成核对')+'</h2></div>'+button('收起，稍后继续','close()',false,g.busy)+'</header><ol class="marketing-guide-steps" aria-label="核对步骤">'+['对照原版','确认资料','保存结果'].map((label,i)=>'<li'+(stage===i+1?' aria-current="step"':'')+' class="'+(stage>i+1?'done':stage===i+1?'current':'')+'"><span>'+(stage>i+1?'✓':i+1)+'</span>'+label+'</li>').join('')+'</ol>';
    if(g.error)html+='<div class="marketing-guide-error" role="alert">'+e(g.error)+' '+button('重新载入这一步','reload()',false,g.busy)+'</div>';
    if(g.stage==='loading')html+='<p class="marketing-guide-loading" role="status">正在准备原版和待核对文字…</p>';
    if(g.stage==='load-error')html+='<footer class="marketing-guide-footer">'+button('跳过这条，继续下一条','skip()')+button('返回资料列表','finish()',true)+'</footer>';
    if(g.stage==='source'&&s){
      html+='<h3>第 1 步：这段识别文字与原版一致吗？</h3><p class="marketing-guide-instruction">只核对这一段的文字和阅读顺序。'+(c.pending_count>1?'当前还有 '+c.pending_count+' 段需要核对。':'')+'</p><div class="marketing-guide-compare"><section class="marketing-guide-original">'+originalPane(s)+'</section><section class="marketing-guide-transcript"><div class="marketing-guide-pane-title"><strong>'+(g.editing?'修正后的文字':'待核对的识别文字')+'</strong></div>'+(g.editing?'<label class="sr-only" for="marketingSourceText">按原版修正这段文字</label><textarea id="marketingSourceText" oninput="MarketingReview.editText(this.value)"'+(g.busy?' disabled':'')+'>'+e(g.draft)+'</textarea><p>只按原版修正这一段。修改会使本书已有审核结论需要复核，并引导你更新相关营销资料。</p>':'<div class="marketing-guide-source-text">'+e(s.text)+'</div>')+'<p class="marketing-guide-source-label">'+e(s.chapter||'原文段落')+'</p></section></div>';
      if(s.can_verify)html+='<label class="marketing-guide-check"><input id="marketingSourceChecked" type="checkbox" onchange="MarketingReview.check(this.checked)"'+(g.checked?' checked':'')+(g.busy?' disabled':'')+'>我已对照原版，确认'+(g.editing?'修正后的文字':'这段文字和阅读顺序')+'无误</label><footer class="marketing-guide-footer"><div>'+button('暂时跳过这条','skip()',false,g.busy)+(g.editing?button('取消修改','edit(false)',false,g.busy):(s.document_label?'':button('文字有误，我来修正','edit(true)',false,g.busy)))+'</div><button type="button" class="btn primary" id="marketingSourceSave" onclick="MarketingReview.saveSource()"'+(!g.checked||g.busy?' disabled':'')+'>'+(g.busy?'正在保存…':g.editing?'保存修正，继续 →':'文字正确，继续 →')+'</button></footer>';
      else html+=unavailable(g,s.blocked_reason);
    }
    if(g.stage==='unavailable')html+=unavailable(g,(c.blocked_reasons||[]).map(x=>x.message).join('；')||'这条资料暂时无法直接核对。');
    if(g.stage==='regenerate')html+='<div class="marketing-guide-notice"><h3>'+(g.sourceChanged?'原文修正已保存':'这条资料需要更新')+'</h3><p>原文已变化，旧营销资料不能直接确认。下一步根据当前原文重新生成营销资料，再核对新的内容。</p><p>此次生成只更新本书营销资料，不会重新解析整本 PDF；生成任务可能需要几分钟。</p></div><footer class="marketing-guide-footer">'+button('暂时跳过这条','skip()',false,g.busy)+button('重新生成营销资料 →','regenerate()',true,g.busy)+'</footer>';
    if(g.stage==='material')html+='<p class="marketing-guide-success">✓ '+(c.segments?.some(x=>x.review)?'来源已核对，同一段原文无需重复处理。':'来源检查通过。')+'</p><h3>第 2 步：这条营销资料可以使用吗？</h3><p class="marketing-guide-instruction">请核对内容是否准确、表述是否合适。确认后，这条资料才会标为可用。</p><div class="marketing-guide-material"><p>'+e(c.text||c.title)+'</p>'+(c.reason?'<p class="marketing-guide-reason">'+e(c.reason)+'</p>':'')+'</div>'+evidence(c)+'<label class="marketing-guide-check"><input id="marketingMaterialChecked" type="checkbox" onchange="MarketingReview.check(this.checked)"'+(g.checked?' checked':'')+(g.busy?' disabled':'')+'>我已核对这条资料的内容与依据，确认可以使用</label><footer class="marketing-guide-footer"><div>'+button('暂时跳过','skip()',false,g.busy)+button('不采用这条','review("rejected")',false,g.busy)+'</div><button type="button" class="btn primary" id="marketingMaterialSave" onclick="MarketingReview.review(\'approved\')"'+(!g.checked||g.busy?' disabled':'')+'>'+(g.busy?'正在保存…':'确认这条资料 →')+'</button></footer>';
    if(receipt)html+='<div class="marketing-guide-notice success"><h3>'+(g.savedStatus==='approved'?'✓ 已确认可用':g.savedStatus==='skipped'?'已跳过，仍保留待确认':'已标记为不采用')+'</h3><p>'+(g.savedStatus==='skipped'?'没有更改这条资料的审核状态。':'处理结果已保存，不会自动确认其他资料。')+'</p></div><footer class="marketing-guide-footer">'+button(g.index+1<g.items.length?'继续下一条 →':'查看本轮结果 →','next()',true)+'</footer>';
    if(done){const approved=g.outcomes.filter(x=>x==='approved').length,rejected=g.outcomes.filter(x=>x==='rejected').length,skipped=g.outcomes.filter(x=>x==='skipped').length;html+='<div class="marketing-guide-notice success"><h3>已确认 '+approved+' 条 · 不采用 '+rejected+' 条 · 跳过 '+skipped+' 条</h3><p>本轮只处理上面这些资料。其余待确认资料仍需你核对。</p></div><footer class="marketing-guide-footer">'+button('完成，返回资料列表','finish()',true)+'</footer>';}
    return html+'</section>';
  }
  function originalPane(s){
    if(s.document_label){
      return '<div class="marketing-guide-pane-title"><strong>上传原件 · '+e(s.document_label)+'</strong></div>'+
        (s.document_excerpt?'<div class="marketing-guide-source-text">'+e(s.document_excerpt)+'</div>':
          '<p class="marketing-guide-error">未在上传原件中唯一定位这段文字。</p>');
    }
    return '<div class="marketing-guide-pane-title"><strong>原版 · PDF 第 '+e(s.source_page||'?')+' 页</strong><div>'+
      (s.preview_url?button('放大 / 还原','zoom()'):'')+
      (s.pdf_url?'<a class="btn ghost" href="'+e(s.pdf_url)+'" target="_blank" rel="noopener">单独打开 ↗</a>':'')+'</div></div>'+
      (s.preview_url?'<div class="marketing-guide-image" id="marketingSourceImage"><img src="'+e(s.preview_url)+'" alt="用于对照的原版 PDF 第 '+e(s.source_page)+' 页" onerror="MarketingReview.imageFailed(this)"></div><p class="marketing-guide-image-hint" id="marketingImageHint">可放大查看。页码按 PDF 页序计算。</p>':'<p class="marketing-guide-error">没有可用于核对的原版页面。</p>');
  }
  function evidence(c){const segments=c.evidence||c.segments||[];if(!segments.length)return '';return '<details class="marketing-guide-evidence"><summary>查看原文依据（'+segments.length+' 处）</summary>'+segments.map(s=>'<article><strong>'+e(s.chapter||'原文')+(s.source_page?' · PDF 第 '+e(s.source_page)+' 页':'')+'</strong><p>'+e(s.quote||s.text||'')+'</p></article>').join('')+'</details>';}
  function unavailable(g,message){return '<div class="marketing-guide-notice"><h3>这条需要进一步处理</h3><p>'+e(message)+'</p><p><a class="btn ghost" href="'+e(reportUrl({code:g.code,legacy_id:g.items[g.index]?.legacy_id}))+'">查看来源与章节报告 →</a></p><details><summary>查看详细问题</summary><p>'+e((g.context?.blocked_reasons||[]).map(x=>x.message).join('；'))+'</p></details></div><footer class="marketing-guide-footer">'+button('不采用这条','review("rejected")',false,g.busy)+button('跳过，处理下一条 →','skip()',true,g.busy)+'</footer>';}
  function live(g){return guide===g&&state.mktData?.code===g.code&&location.hash===g.hash&&!!document.getElementById('mktBody');}
  function draw(focus=false){mktRender();if(focus)focusIssue();}
  async function start(id){
    const code=state.mktData?.code;if(!code)return;
    let saved=checkpoint(code),items=saved?.items||get(code).items.map(x=>({asset_id:x.asset_id,legacy_id:x.legacy_id,title:x.title}));
    if(id){const item=get(code).items.find(x=>x.legacy_id===id);if(item){items=[item,...items.filter(x=>x.asset_id!==item.asset_id)].map(x=>({asset_id:x.asset_id,legacy_id:x.legacy_id,title:x.title}));saved=null;}}
    if(!items.length)return;
    guide={code,items,index:saved?.index||0,outcomes:saved?.outcomes||[],restoredDraft:saved?.draft,hash:location.hash,stage:'loading',busy:false,error:'',checked:false};
    await reload();
  }
  async function reload(){
    const g=guide;if(!g||g.busy)return;
    if(g.index>=g.items.length){g.stage='done';draw(true);return;}
    const token=++sequence;g.stage='loading';g.error='';g.busy=true;g.checked=false;draw(true);
    try{
      const c=await api('/api/marketing/source-review?'+new URLSearchParams({code:g.code,asset_id:g.items[g.index].asset_id}));
      if(!live(g)||token!==sequence)return;
      g.context=c;g.segment=(c.pending_segments||[])[0];g.editing=false;g.draft=g.segment?.text||'';
      if(['approved','rejected'].includes(c.status)){g.stage='saved';g.savedStatus=c.status;g.outcomes[g.index]=c.status;}
      else if(c.requires_regeneration)g.stage='regenerate';
      else if(g.segment)g.stage='source';
      else g.stage=c.can_proceed?'material':'unavailable';
      const draft=g.restoredDraft;if(draft&&g.segment&&draft.anchor===g.segment.anchor&&draft.revision===g.segment.revision){g.editing=true;g.draft=draft.text;}
      g.restoredDraft=null;remember(g);
    }catch(err){if(live(g)&&token===sequence){g.stage='load-error';g.error=err.message;}}
    finally{g.busy=false;if(live(g)&&token===sequence)draw(true);}
  }
  function check(value){if(!guide)return;guide.checked=value;const b=document.getElementById(guide.stage==='source'?'marketingSourceSave':'marketingMaterialSave');if(b)b.disabled=!value||guide.busy;}
  function edit(on){if(!guide||guide.busy)return;guide.editing=on;guide.checked=false;guide.draft=guide.segment.text;remember(guide);draw();if(on)document.getElementById('marketingSourceText')?.focus();}
  function editText(value){if(guide){guide.draft=value;guide.checked=false;const checkbox=document.getElementById('marketingSourceChecked');if(checkbox)checkbox.checked=false;check(false);remember(guide);}}
  function zoom(){document.getElementById('marketingSourceImage')?.classList.toggle('zoomed');}
  function imageFailed(img){img.hidden=true;const h=document.getElementById('marketingImageHint');if(h)h.textContent='页面预览暂时无法显示，请点“单独打开”查看对应原版页后核对。';}
  async function saveSource(){
    const g=guide;if(!g||g.busy||!g.checked||!g.segment?.can_verify)return;
    g.busy=true;g.error='';draw();
    try{
      const body={code:g.code,asset_id:g.context.asset_id,anchor:g.segment.anchor,revision:g.segment.revision,confirmed:true};if(g.editing)body.text=g.draft;
      const result=await post('/api/marketing/source-review/verify',body);if(!live(g))return;
      g.checked=false;g.editing=false;g.sourceChanged=result.changed;g.restoredDraft=null;remember(g);g.busy=false;
      await refresh(true);if(live(g))await reload();
    }catch(err){if(live(g)){g.error=err.message;g.checked=false;}}
    finally{g.busy=false;if(live(g))draw(true);}
  }
  async function review(status){
    const g=guide;if(!g||g.busy||!g.context||(status==='approved'&&(!g.checked||!g.context.can_proceed)))return;
    g.busy=true;g.error='';draw();
    try{
      await post('/api/content-assets/review',{id:g.context.asset_id,revision:g.context.revision,status});if(!live(g))return;
      g.savedStatus=status;g.outcomes[g.index]=status;g.stage='saved';g.checked=false;remember(g);
      mktFlags(g.code)[g.context.legacy_id]=status==='approved'?'adopt':'reject';await refresh(true);
    }catch(err){if(live(g)){g.error=err.message;g.checked=false;}}
    finally{g.busy=false;if(live(g))draw(true);}
  }
  function skip(){const g=guide;if(!g||g.busy)return;g.savedStatus='skipped';g.outcomes[g.index]='skipped';g.stage='saved';g.error='';g.editing=false;remember(g);draw(true);}
  async function next(){const g=guide;if(!g||g.busy)return;g.index++;g.context=null;g.segment=null;g.sourceChanged=false;g.editing=false;g.error='';remember(g);await reload();}
  function close(){if(!guide||guide.busy)return;remember(guide);guide=null;++sequence;draw(true);}
  async function finish(){if(!guide||guide.busy)return;const code=guide.code;forget(code);guide=null;++sequence;await refresh(true);draw();}
  async function regenerate(){
    const g=guide;if(!g||g.busy)return;g.busy=true;draw();
    try{const result=await post('/api/books/generate',{code:g.code,kind:'marketing'});if(!live(g))return;forget(g.code);guide=null;go('job',result.job.id);}
    catch(err){if(live(g)){g.error=err.message;g.busy=false;draw(true);}}
  }
  function focusIssue(id){const node=document.getElementById('marketingGuideTitle')||Array.from(document.querySelectorAll('[data-marketing-issue]')).find(x=>x.dataset.marketingIssue===id)||document.getElementById('marketingReviewProblems');if(node){node.scrollIntoView({block:'start'});node.focus({preventScroll:true});}}
  function focusReturn(){
    const id=params()?.get('issue');if(!id||guide)return;
    if(get(state.mktData?.code).items.some(x=>x.legacy_id===id)){focusIssue(id);return;}
    const group=(state.mktData?.groups||[]).find(g=>g.rows.some(r=>r.id===id));if(!group)return;
    const row=group.rows.find(r=>r.id===id),cat=mktRowState(row,mktFlags(state.mktData.code))==='review'?'review':group.key;if(state.mktCat!==cat){state.mktCat=cat;mktRender();}
    const node=Array.from(document.querySelectorAll('.mkt-item')).find(x=>x.dataset.id===id);if(node){node.tabIndex=-1;node.scrollIntoView({block:'center'});node.focus({preventScroll:true});}
  }
  function blocked(code,details,message){books.set(code,{items:Array.isArray(details?.blocked_items)?details.blocked_items:get(code).items,message:details?.error||message||'确认未完成，请重试。'});++request;mktRender();focusIssue();}
  async function refresh(manual=false){
    const code=state.mktData?.code;if(!code||!document.getElementById('mktBody'))return;
    const token=++request,hash=location.hash,host=document.getElementById('mktBody');const current=()=>token===request&&hash===location.hash&&host===document.getElementById('mktBody')&&state.mktData?.code===code;
    try{
      const [result,fresh]=await Promise.all([api('/api/marketing/review-issues?'+new URLSearchParams({code})),manual?jget('/api/book?'+new URLSearchParams({code})):Promise.resolve(null)]);if(!current())return;
      if(fresh){state.bookCache[code]=fresh;state.book=fresh;state.mktData.d=fresh;state.mktData.groups=mktServerGroups(fresh.marketing_rows||[]);}
      books.set(code,{items:result.blocked_items||[],message:''});mktRender();focusReturn();if(manual&&!guide&&!result.blocked_items?.length)toast('来源检查通过，可继续核对资料。');
    }catch(err){if(!current())return;books.set(code,{...get(code),message:'来源检查暂未更新：'+err.message});mktRender();}
  }
  return {panel,rowAction,refresh,blocked,focusIssue,focusReturn,returnLink,sourceUrl,reportUrl,start,reload,check,edit,editText,zoom,imageFailed,saveSource,review,skip,next,close,finish,regenerate};
})();
