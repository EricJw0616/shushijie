/* Second stage: confirmed current outline -> one presentation's text prompts. */
'use strict';
window.VideoPrompts=(function(){
  let state=null,serial=0,poll=null;
  const remembered=new Map(),MEMORY='bookworld.video-prompts:';
  const clone=value=>JSON.parse(JSON.stringify(value));
  const validMode=value=>['image','video'].includes(value);
  const runMode=run=>run?.result?.video_prompts?.presentation_mode||run?.snapshot?.presentation_mode||'';
  function currentDraft(project){const current=Studio.peekAssistContext?.();return current?.id===project.id?clone(current):project;}
  function briefSignature(brief){
    const b={...brief},task=b.marketing_task||'general';
    if(task==='general')delete b.marketing_task;
    if(task!=='channel')delete b.channels;else b.channels=[...(b.channels||[])].sort();
    if(!['channel','theme'].includes(task))delete b.target_codes;else b.target_codes=[...(b.target_codes||[])].sort();
    if(!['general','reposition'].includes(task))delete b.source_code;
    if(task!=='general')delete b.new_book_brief;
    for(const key of ['book_readers','decision_maker'])if(typeof b[key]==='string')b[key]=b[key].trim();
    const entries=Object.entries(b).filter(([,value])=>value!==''&&value!=null&&(!Array.isArray(value)||value.length)).sort(([a],[z])=>a.localeCompare(z));
    return JSON.stringify(Object.fromEntries(entries));
  }
  function sameDraft(a,b){return a.id===b.id&&a.draft===b.draft&&briefSignature(a.brief)===briefSignature(b.brief);}
  function recall(pid){if(remembered.has(pid))return remembered.get(pid);try{return JSON.parse(sessionStorage.getItem(MEMORY+pid)||'null')||{};}catch(_){return {};}}
  function remember(s){const value={mode:s.mode,runId:s.run?.id||s.selectedRunId||'',stage:s.stage};remembered.set(s.project.id,value);try{sessionStorage.setItem(MEMORY+s.project.id,JSON.stringify(value));}catch(_){}}
  const label=mode=>mode==='image'?'图片展示':'视频展示';
  function host(){return document.getElementById('videoPromptsDialog');}
  function here(s){return state===s&&serial===s.token&&location.hash===s.hash&&!!host();}
  function stale(run){return !!(run?.stale||run?.source_stale);}
  function formatted(value){return ManuscriptReader.build(String(value||''),new Map(),{frozen:true}).html;}
  function shotTitle(shot,index,mode){
    const prefix='第 '+(shot.number||index+1)+(mode==='image'?' 张':' 镜'),title=String(shot.title||'').trim();
    const planned=shot.production_timing;
    if(mode==='video'&&Number.isFinite(planned?.global_start_seconds)&&Number.isFinite(planned?.global_end_seconds))return prefix+' · 全片 '+planned.global_start_seconds+'–'+planned.global_end_seconds+' 秒';
    if(/^第\s*\d+\s*段$/.test(title))return prefix;
    const timing=title.match(/^(?:镜头|第)[ \t]*\d+[^\d]*?(\d+(?:\.\d+)?[ \t]*[–—~-][ \t]*\d+(?:\.\d+)?[ \t]*秒)$/);
    return prefix+(timing?(mode==='video'?' · 全片 '+timing[1]:''):title?' · '+title:'');
  }
  function sourceSummary(shot){
    const source=String(shot.source_text||''),voices=Array.from(source.matchAll(/(?:^|\n)\*\*口播：\*\*[ \t]*([\s\S]*?)(?=\n\*\*[^\n*]+：\*\*|$)/g));
    const mixed=/(?:^|\n)\s*(?:#{1,6}\s|\*\*[^\n*]+：\*\*|(?:画面|剪辑|字幕|时长|素材)[：:])/.test(source);
    return voices.length===1?{label:'对应口播',text:voices[0][1].trim()}:{label:mixed?'对应原稿':'对应口播',text:source};
  }
  function button(text,action,attrs='',primary=false){return '<button type="button" class="btn '+(primary?'primary':'ghost')+'" '+attrs+' onclick="VideoPrompts.'+action+'(this)">'+text+'</button>';}
  function exitLabel(s){return /\/results$/.test(s.hash)||s.hash.split('/').length===3?'返回口播稿':'返回项目';}
  function runStatus(run){return (stale(run)?'旧版 · ':'')+(run.status==='done'?'已生成':run.status==='failed'?'生成失败':['queued','running'].includes(run.status)?'生成中':'未完成');}
  function recordCard(run){return '<button type="button" class="video-prompt-record" data-run="'+esc(run.id)+'" data-mode="'+esc(runMode(run))+'" onclick="VideoPrompts.openRun(this)"><strong>'+esc(validMode(runMode(run))?label(runMode(run))+'提示词':'其他提示词记录')+'</strong><span>'+esc(String(run.created_at||'').replace('T',' ').slice(0,16))+' · '+esc(runStatus(run))+'</span></button>';}
  function existing(s){if(s.loading)return '<p role="status">正在读取已有记录…</p>';if(!s.runs.length)return '';const recent=['image','video',''].map(mode=>s.runs.find(run=>(validMode(runMode(run))?runMode(run):'')===mode)).filter(Boolean);return '<section class="video-existing-results"><div><h3>已有记录</h3>'+button('查看全部 '+s.runs.length+' 条','showRecords','data-video-all-records')+'</div><div class="video-existing-cards">'+recent.map(recordCard).join('')+'</div></section>';}
  function choices(s){
    const draft=!!s.project.draft?.trim();
    return '<h2 id="videoPromptsTitle">选择呈现方式</h2><p class="muted">为这份口播配上画面，制作短视频。</p>'+existing(s)+'<form id="videoPromptsForm" onsubmit="event.preventDefault();VideoPrompts.generate(this)"><fieldset class="video-presentation-choices"><legend>'+(s.runs.length?'需要另一份提示词时再生成':'画面怎样呈现？')+'</legend><label><input type="radio" name="presentation_mode" value="image"'+(s.mode==='image'?' checked':'')+' onchange="VideoPrompts.selectMode(this)"><span><strong>图片展示</strong><small>用静态图片配合口播，生成每张图的提示词。</small></span></label><label><input type="radio" name="presentation_mode" value="video"'+(s.mode==='video'?' checked':'')+' onchange="VideoPrompts.selectMode(this)"><span><strong>视频展示</strong><small>用动态片段配合口播，生成每个镜头的提示词。</small></span></label></fieldset>'+(!draft?'<p class="muted">当前没有口播稿，仍可查看已有记录。生成新内容请先返回口播稿。</p>':'')+'<div class="modal-actions">'+button(exitLabel(s),'close')+'<button type="submit" class="btn primary"'+(!draft||s.busy||s.conflict?' disabled':'')+'>'+(s.busy?'正在提交…':'按当前口播生成提示词')+'</button></div></form>';
  }
  function records(s){
    const groups=['image','video',''].map(mode=>{const rows=s.runs.filter(run=>(validMode(runMode(run))?runMode(run):'')===mode);return rows.length?'<section class="video-prompt-record-group"><h3>'+esc(mode?label(mode):'其他记录')+' <small>'+rows.length+' 条</small></h3>'+rows.map(recordCard).join('')+'</section>':'';}).join('');
    return '<h2 id="videoPromptsTitle">已有提示词记录</h2><p class="muted">选择记录继续查看或制作。</p>'+(s.loading?'<p role="status">正在读取记录…</p>':s.runs.length?'<div class="video-prompt-records">'+groups+'</div>':'<p>还没有提示词。确认口播稿后，选择呈现方式即可生成。</p>')+'<div class="modal-actions">'+button('选择呈现方式','choose','data-video-choose')+'</div>';
  }
  function referenceRequirement(value){return String(value||'').replace(/^[ \t]*(?:待提供或确认|待提供|待制作)[ \t]*[：:]?[ \t]*/gm,'').trim();}
  function hasReferenceList(data){return Array.isArray(data.required_inputs)||Array.isArray(data.references);}
  function referenceList(data){
    const shots=Array.isArray(data.shots)?data.shots:[],validNumbers=new Set(shots.map(shot=>shot.number).filter(number=>Number.isInteger(number)&&number>0));
    const rows=Array.isArray(data.required_inputs)&&data.required_inputs.length?data.required_inputs:Array.isArray(data.references)?data.references:[];
    const seen=new Set(),result=[];
    for(const item of rows){
      if(!item||typeof item!=='object')continue;
      const requirement=referenceRequirement(item.requirement),key=item.id||requirement;
      if(!requirement||seen.has(key))continue;
      let numbers=Array.isArray(item.shot_numbers)?item.shot_numbers.filter(number=>Number.isInteger(number)&&validNumbers.has(number)):[];
      if(!numbers.length&&item.id)numbers=shots.filter(shot=>Array.isArray(shot.reference_ids)&&shot.reference_ids.includes(item.id)&&validNumbers.has(shot.number)).map(shot=>shot.number);
      const mapped=Array.isArray(item.shot_numbers)||shots.some(shot=>Array.isArray(shot.reference_ids));
      if(mapped&&!numbers.length)continue;
      seen.add(key);result.push({...item,requirement,shot_numbers:[...new Set(numbers)].sort((a,b)=>a-b)});
    }
    if(!hasReferenceList(data))for(const shot of shots){
      const requirement=referenceRequirement(shot.reference_requirements);if(!requirement)continue;
      const number=validNumbers.has(shot.number)?shot.number:null,existing=result.find(item=>item.requirement===requirement);
      if(existing){if(number&&!existing.shot_numbers.includes(number))existing.shot_numbers.push(number);continue;}
      result.push({name:'参考图',requirement,shot_numbers:number?[number]:[]});
    }
    return result.map(item=>({...item,shot_numbers:item.shot_numbers.sort((a,b)=>a-b)}));
  }
  function shotReferences(data,shot,refs){
    const used=refs.filter(item=>item.shot_numbers.includes(shot.number));
    if(hasReferenceList(data)&&!used.length&&!refs.some(item=>!item.shot_numbers.length))return '';
    return referenceRequirement(shot.reference_requirements)||used.map(item=>item.name+'：'+item.requirement).join('\n');
  }
  function staleNotice(s){return stale(s.run)?'<div class="video-prompts-stale" role="status">口播稿或制作要求已有修改，下面是旧版制作内容。'+button('按当前口播稿重新生成','choose')+'</div>':'';}
  function handoff(s){
    const data=s.run?.result?.video_prompts;if(!data)return result(s);
    const image=data.presentation_mode==='image',refs=referenceList(data),hasDocument=!!String(s.run.markdown||'').trim(),old=stale(s.run);
    const noReferences=!refs.length;
    const steps=image?[(noReferences?'到所用生图工具，':'到所用生图工具上传所列参考图，')+'按张使用提示词制作并核对图片。','完整口播只配音一次，将图片按顺序与配音、字幕剪辑成配图讲解视频，核对后发布。']:[(noReferences?'到所用视频工具，':'到所用视频工具上传所需参考图或已确认静帧，')+'按镜头制作并核对动态片段。','完整口播只配音一次，将各镜片段、配音和字幕合成短视频，核对后发布。'];
    return '<h2 id="videoPromptsTitle">'+label(data.presentation_mode)+' · 准备制作</h2>'+staleNotice(s)+'<p class="muted">PDF 用于阅读和转交；制作时可逐条复制提示词。画面制作与剪辑在所用工具中完成。</p>'+(refs.length?'<section class="video-handoff-materials"><h3>制作画面需要的参考图</h3><p class="muted">在所用的'+(image?'生图':'视频')+'工具中上传对应参考图，再使用提示词。</p><ul>'+refs.map(item=>'<li><div><strong>'+esc(item.name||'参考图')+'</strong>'+(item.shot_numbers.length?'<span class="video-reference-usage">用于第 '+item.shot_numbers.join('、')+(image?' 张':' 镜')+'</span>':'')+'</div><p>'+esc(item.requirement)+'</p></li>').join('')+'</ul></section>':!hasReferenceList(data)?'<p class="muted video-handoff-reference-note">这份旧记录未单列参考图，请按各条提示词核对参考要求。</p>':'')+'<div class="video-handoff-sources">'+button('查看口播内容与出处','sources','data-video-sources')+'</div><section class="video-handoff-steps"><h3>接下来怎么做</h3><ol>'+steps.map(text=>'<li>'+text+'</li>').join('')+'</ol></section>'+(hasDocument?'<div class="video-handoff-downloads">'+button(old?'复制旧版整套内容':'复制全部','copyAll','data-video-copy-all')+button(old?'下载旧版制作包 PDF':'下载制作包 PDF','download','data-video-download',true)+'</div>':'<p class="muted">这份旧记录未保存整套文档，可返回提示词逐条复制。</p>');
  }
  function result(s){
    const run=s.run,data=run?.result?.video_prompts,mode=data?.presentation_mode||run?.snapshot?.presentation_mode||s.mode||'image';
    let html='<h2 id="videoPromptsTitle">'+label(mode)+'提示词</h2>';
    if(!run||['queued','running'].includes(run.status))return html+'<p class="video-prompt-progress" role="status">正在根据已确认的口播稿生成提示词。可以返回口播稿，稍后从「查看提示词」继续。</p>';
    if(run.status==='failed'||!data)return html+'<p role="alert">'+esc(run.error||'本次提示词未生成完成。')+'</p>'+button('重新确认口播稿','choose');
    if(stale(run))html+='<div class="video-prompts-stale" role="status">口播稿或制作要求已有修改，下面是旧版提示词。'+button('按当前口播稿重新生成','choose')+'</div>';
    html+='<p class="muted">'+(mode==='image'?'按张复制提示词，用于制作图片。':'按镜头复制提示词，用于制作视频片段。')+'</p><div class="video-prompts-context"><span>给谁看：'+esc(data.audience)+'</span><details class="video-prompts-style"><summary>查看视觉风格</summary><p>'+esc(data.visual_style)+'</p></details></div><div class="video-prompt-list">';
    const refs=referenceList(data);
    html+=(data.shots||[]).map((shot,i)=>{const source=sourceSummary(shot),reference=shotReferences(data,shot,refs);return '<details class="video-prompt-shot"'+(!i?' open':'')+'><summary>'+esc(shotTitle(shot,i,mode))+'</summary><div class="video-prompt-item"><div class="video-prompt-actions">'+button(stale(run)?'复制旧版提示词':'复制提示词','copy','data-shot="'+i+'"')+'</div><details class="video-prompt-source"><summary>'+source.label+'</summary><div>'+formatted(source.text)+'</div></details>'+(reference?'<details class="video-prompt-source video-reference-requirements"><summary>制作'+(mode==='image'?'这张图':'这个镜头')+'需要的参考图</summary><div>'+formatted(reference)+'</div></details>':'')+(shot.overlay_text?'<p class="video-prompt-overlay"><strong>后期文字：</strong>'+esc(shot.overlay_text)+'</p>':'')+'<p class="video-prompt-text">'+esc(shot.prompt||'')+'</p></div></details>';}).join('')+'</div><div class="video-prompt-next">'+button(stale(run)?'查看旧版制作包':'准备制作','prepareProduction','data-video-prepare',true)+'</div>';
    return html;
  }
  function pageLabel(stage){return {choose:'返回选择方式',records:'返回已有记录',result:'返回提示词',handoff:'返回准备制作'}[stage]||'返回上一页';}
  function html(s){return '<section id="videoPromptsDialog" class="video-prompts-dialog" data-stage="'+s.stage+'" data-run="'+esc(s.run?.id||'')+'" role="dialog" aria-modal="true" aria-labelledby="videoPromptsTitle" tabindex="-1"><button type="button" class="modal-x" onclick="VideoPrompts.close()" aria-label="'+exitLabel(s)+'">×</button><div class="video-prompts-back">'+(s.parentStage?button('← '+pageLabel(s.parentStage),'back','data-video-back'):button('← '+exitLabel(s),'close'))+(s.parentStage?button(exitLabel(s),'close'):'')+(s.stage==='result'?button('查看已有记录','showRecords','data-video-all-records')+button('选择呈现方式','choose','data-video-choose'):'')+'</div>'+(s.error?'<div class="video-prompts-error" role="alert">'+esc(s.error)+(s.listFailed?button('重新读取记录','retryRecords'):'')+'</div>':'')+(s.stage==='choose'?choices(s):s.stage==='records'?records(s):s.stage==='handoff'?handoff(s):result(s))+'</section>';}
  function paint(s,previousFocus=null){
    if(!here(s))return;
    const root=host(),active=document.activeElement===document.body&&root.contains?.(previousFocus)?previousFocus:document.activeElement,owned=active===root||root.contains?.(active);
    const details=Array.from(root.querySelectorAll?.('details')||[]).map(el=>({open:el.open,summary:el.querySelector('summary')?.textContent}));
    const selector='button,a,input,select,textarea,summary,[tabindex]';
    const identity=el=>JSON.stringify([el.tagName,...['id','name','type','value','data-shot','data-run','onclick','href'].map(key=>el.getAttribute(key)),el.tagName==='SUMMARY'?el.textContent:'']);
    const key=owned&&active!==root?identity(active):null;
    const index=key?Array.from(root.querySelectorAll(selector)).filter(el=>identity(el)===key).indexOf(active):0;
    remember(s);root.outerHTML=html(s);
    host().querySelectorAll?.('details').forEach((el,index)=>{const previous=details[index];if(previous&&el.querySelector('summary')?.textContent===previous.summary)el.open=previous.open;});
    if(owned){const next=host(),control=key?Array.from(next.querySelectorAll(selector)).filter(el=>identity(el)===key)[index]:null;(control&&!control.disabled?control:next)?.focus({preventScroll:true});}
  }
  function disableButton(el){const origin=el&&document.activeElement===el?el:null;if(el)el.disabled=true;return origin;}
  function restoreButton(s,el,origin){if(el)el.disabled=false;if(origin?.isConnected&&here(s)&&document.activeElement===document.body)origin.focus({preventScroll:true});}
  function descriptor(s){return {type:'video-prompts',projectId:s.project.id,stage:s.stage,runId:s.run?.id||'',mode:s.mode,parentStage:s.parentStage||''};}
  function show(value,step=false,historyOptions={}){
    // A history page owns its data. Navigation never changes a previous page's stage or selected run.
    const s=clone(value);clearTimeout(poll);
    openModal(()=>{s.token=++serial;state=s;remember(s);setTimeout(()=>{if(!here(s))return;host().focus({preventScroll:true});if(['result','handoff'].includes(s.stage)&&s.run?.id)loadRun(s,s.run.id);else if(['records','choose'].includes(s.stage))loadRecords(s);},0);return html(s);},true,{step,descriptor:descriptor(s),...historyOptions});
  }
  function navigate(s,changes){show({...s,...changes,busy:false,loading:false,error:'',listFailed:false,parentStage:s.stage},true);}
  async function readProject(){const match=location.hash.match(/^#\/campaigns\/([^/]+)/);if(!match)throw new Error('请从营销项目打开提示词。');return (await jget('/api/projects/'+encodeURIComponent(match[1]))).project;}
  async function open(stage='auto',step=false){
    const previous=state&&here(state)?state:null,token=++serial,hash=location.hash;clearTimeout(poll);
    try{
      const p=await readProject();if(token!==serial||hash!==location.hash)return;
      const saved=recall(p.id);let runs=[],error='',listFailed=false;
      try{const d=await jget('/api/projects/'+p.id+'/assist');runs=(d.runs||[]).filter(x=>x.capability==='video_prompts');}catch(err){error='已有记录读取失败，请重试。'+err.message;listFailed=true;}
      if(token!==serial||hash!==location.hash)return;
      const rememberedRun=runs.find(x=>x.id===saved.runId),target=stage==='auto'?(saved.stage==='records'?'records':rememberedRun&&saved.stage!=='choose'?'result':'choose'):stage;
      const mode=target==='result'&&validMode(runMode(rememberedRun))?runMode(rememberedRun):validMode(saved.mode)?saved.mode:'image';
      show({token,hash,project:target==='choose'?currentDraft(p):p,stage:target,run:target==='result'?rememberedRun:null,runs,mode,selectedRunId:saved.runId||'',busy:false,loading:false,error,listFailed,conflict:false,parentStage:step&&previous?previous.stage:''},!!(step&&previous));
    }catch(err){if(token===serial){if(previous){previous.token=serial;state=previous;}toast(err.message,true);}}
  }
  function close(){if(state)remember(state);++serial;clearTimeout(poll);state=null;closeModal();}
  function choose(){return open('choose',true);}
  function showRecords(){return open('records',true);}
  function selectMode(el){const s=state;if(!s||!here(s)||s.busy||!validMode(el.value))return;show({...s,mode:el.value},false,{replace:true});}
  async function loadRecords(s){
    try{const d=await jget('/api/projects/'+s.project.id+'/assist');if(!here(s))return;const runs=(d.runs||[]).filter(x=>x.capability==='video_prompts'),changed=JSON.stringify(runs)!==JSON.stringify(s.runs)||s.loading||s.listFailed;s.runs=runs;s.loading=false;if(s.listFailed)s.error='';s.listFailed=false;if(changed)paint(s);}
    catch(err){if(here(s)){s.loading=false;s.listFailed=true;s.error='已有记录读取失败，请重试。'+err.message;paint(s);}}
  }
  function retryRecords(){const s=state;if(!s||!here(s))return;s.loading=true;s.error='';paint(s);return loadRecords(s);}
  async function openRun(el){
    const s=state;if(!s||!here(s))return;const id=el.dataset.run;let run=s.runs.find(x=>x.id===id);
    if(!run){try{run=(await jget('/api/projects/'+s.project.id+'/assist/'+id)).run;}catch(err){if(here(s))toast(err.message,true);return;}}
    if(!here(s)||!run)return;if(run.capability!=='video_prompts'){toast('这条记录不是画面提示词，请从已有记录选择。',true);return;}navigate(s,{stage:'result',run,mode:validMode(runMode(run))?runMode(run):s.mode,selectedRunId:run.id});
  }
  async function loadRun(s,id){
    try{
      const d=await jget('/api/projects/'+s.project.id+'/assist/'+id);if(!here(s)||!['result','handoff'].includes(s.stage))return;
      if(JSON.stringify(s.run)!==JSON.stringify(d.run)){s.run=d.run;paint(s);}
      if(['queued','running'].includes(d.run?.status)){clearTimeout(poll);poll=setTimeout(()=>loadRun(s,id),2200);}
    }catch(err){if(here(s)){s.error='读取提示词失败，请返回记录后重试。'+err.message;paint(s);}}
  }
  async function generate(form){
    const s=state;if(!s||!here(s)||s.stage!=='choose'||s.busy||s.conflict)return;
    const mode=String(new FormData(form).get('presentation_mode'));if(!validMode(mode))return;
    s.busy=true;s.error='';s.mode=mode;remember(s);const submit=form.querySelector('[type=submit]');submit.disabled=true;submit.textContent='正在提交…';
    try{
      if(!sameDraft(currentDraft(s.project),s.project)){s.conflict=true;throw new Error('口播稿或制作要求已经变化，请返回口播稿重新确认。');}
      const p=await Studio.assistContext();if(!here(s))return;
      if(!p.draft?.trim())throw new Error('请先填写并保存口播稿，再生成提示词。');
      if(!sameDraft(p,s.project)||!sameDraft(currentDraft(p),s.project)){s.conflict=true;throw new Error('口播稿或制作要求已经变化，请返回口播稿重新确认。');}
      const d=await post('/api/projects/'+p.id+'/assist',{capability:'video_prompts',revision:p.revision,confirmed:true,confirmed_draft:p.draft,presentation_mode:mode});
      s.busy=false;if(!here(s))return;
      s.runs=[d.run,...s.runs.filter(x=>x.id!==d.run.id)];s.selectedRunId=d.run.id;navigate(s,{stage:'result',run:d.run});ProjectAssist.retry();
    }catch(err){if(here(s)){s.error=err.message;paint(s);}}finally{s.busy=false;if(here(s))paint(s);}
  }
  async function copy(el){
    const s=state,index=Number(el.dataset.shot);if(!s||!here(s)||!s.run||el.disabled||!Number.isInteger(index))return;
    const before=s.run,wasStale=stale(before),previousFocus=disableButton(el);
    try{
      const d=await jget('/api/projects/'+s.project.id+'/assist/'+before.id);if(!here(s)||s.run.id!==before.id)return;
      s.run=d.run;
      if(stale(d.run)&&!wasStale){paint(s,previousFocus);toast('口播稿已变化，请重新生成，或确认后复制标记为旧版的提示词。',true);return;}
      const prompt=d.run?.result?.video_prompts?.shots?.[index]?.prompt;if(!prompt)throw new Error('这条提示词暂不可用，请重新打开记录。');
      await navigator.clipboard.writeText(prompt);if(here(s))toast(wasStale?'已复制旧版提示词':'已复制提示词');
    }catch(err){if(here(s))toast(err.message||'复制失败，请选择文字后复制。',true);}
    finally{restoreButton(s,el,previousFocus);}
  }
  function back(){if(!state||!here(state))return;++serial;clearTimeout(poll);state=null;closeModal(false);}
  function backToPrompts(){back();}
  function sources(){if(!state||!here(state))return;remember(state);Studio.openProjectSection('sources');}
  async function prepareProduction(el){
    const s=state;if(!s||!here(s)||!s.run||el?.disabled)return;const id=s.run.id,previousFocus=disableButton(el);
    try{const d=await jget('/api/projects/'+s.project.id+'/assist/'+id);if(!here(s)||s.run.id!==id)return;s.run=d.run;if(d.run?.status!=='done'||!d.run.result?.video_prompts)throw new Error('提示词还未完成，请稍后再准备制作。');navigate(s,{stage:'handoff'});}
    catch(err){if(here(s)){s.error=err.message;paint(s,previousFocus);}}finally{restoreButton(s,el,previousFocus);}
  }
  function packageFilename(run){
    if(typeof run.download_filename==='string'&&run.download_filename.trim())return run.download_filename;
    const snapshot=run.snapshot||{},title=[snapshot.title,snapshot.brief?.topic].find(value=>typeof value==='string'&&value.trim()),mode=run.result?.video_prompts?.presentation_mode||snapshot.presentation_mode;
    return (title?.trim()||'未命名项目')+'_'+(mode==='video'?'视频制作包':'图片制作包')+'.pdf';
  }
  function pdfFilename(disposition,fallback){
    const encoded=String(disposition||'').match(/filename\*\s*=\s*UTF-8'[^']*'([^;]+)/i),plain=String(disposition||'').match(/filename\s*=\s*(?:"([^"]*)"|([^;]+))/i);
    let name=plain?.[1]||plain?.[2]||fallback;
    if(encoded)try{name=decodeURIComponent(encoded[1].trim())||fallback;}catch(_){name=fallback;}
    if(/^(?:旧版-)?(?:production-pack|图片展示-制作包|视频展示-制作包)\.pdf$/i.test(String(name).trim()))name=fallback;
    const clean=value=>String(value).normalize('NFC').replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g,'-').replace(/\p{C}/gu,'-').replace(/^[.\s]+|[.\s]+$/g,'').replace(/\.(?:pdf|md)$/i,'').replace(/[.\s]+$/g,'');
    name=clean(name)||clean(fallback)||'内容制作包';
    const suffix=name.match(/_(?:图片|视频)制作包$/)?.[0]||'',stem=suffix?name.slice(0,-suffix.length):name;
    let safe='',bytes=suffix?16:0;
    for(const char of stem){const code=char.codePointAt(0),size=code<=0x7f?1:code<=0x7ff?2:code<=0xffff?3:4;if(bytes+size>216)break;safe+=char;bytes+=size;}
    return safe.replace(/[.\s]+$/g,'')+suffix+'.pdf';
  }
  async function packageAction(el,downloading){
    const s=state;if(!s||!here(s)||s.stage!=='handoff'||!s.run||el?.disabled)return;const before=s.run,wasStale=stale(before),previousFocus=disableButton(el);
    try{
      const d=await jget('/api/projects/'+s.project.id+'/assist/'+before.id);if(!here(s)||s.run.id!==before.id||s.stage!=='handoff')return;s.run=d.run;
      if(stale(d.run)&&!wasStale){paint(s,previousFocus);toast('内容已变化，制作包已标为旧版。请重新生成或明确选择旧版交付。',true);return;}
      if(d.run?.status!=='done'||!d.run.result?.video_prompts)throw new Error('制作内容还未完成，请返回提示词查看状态。');
      const markdown=String(d.run.markdown||'');if(!markdown.trim())throw new Error('这份记录没有整套文档，请返回提示词逐条复制。');
      if(downloading){
        let response;
        try{response=await fetch('/api/projects/'+encodeURIComponent(s.project.id)+'/assist/'+encodeURIComponent(before.id)+'/download?format=pdf'+(wasStale?'&allow_stale=1':''),{credentials:'same-origin',headers:{Accept:'application/pdf'}});}catch(_){throw new Error('制作包 PDF 下载失败，请检查连接后重试。');}
        if(!here(s)||s.run.id!==before.id||s.stage!=='handoff')return;
        if(!response.ok){
          let message='制作包 PDF 下载失败，请重试。';try{const error=await response.json();if(typeof error.error==='string'&&error.error.trim())message=error.error;}catch(_){}
          if(!here(s)||s.run.id!==before.id)return;
          if(response.status===409){s.run={...s.run,stale:true};paint(s,previousFocus);toast(message,true);return;}
          throw new Error(message);
        }
        if(String(response.headers.get('Content-Type')||'').split(';')[0].trim().toLowerCase()!=='application/pdf')throw new Error('下载未返回有效的 PDF 文件，请重试。');
        let blob;try{blob=await response.blob();}catch(_){throw new Error('PDF 文件未能下载完整，请重试。');}
        if(!blob.size||await blob.slice(0,5).text()!=='%PDF-')throw new Error('下载的 PDF 文件为空或无效，请重试。');
        if(!here(s)||s.run.id!==before.id||s.stage!=='handoff')return;
        const file=pdfFilename(response.headers.get('Content-Disposition'),packageFilename(d.run));
        const url=URL.createObjectURL(blob),a=document.createElement('a');
        a.href=url;a.download=(wasStale&&!file.startsWith('旧版-')?'旧版-':'')+file;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }else await navigator.clipboard.writeText(markdown);
      if(here(s))toast((downloading?'已下载':'已复制')+(stale(d.run)?'旧版':'')+(downloading?'制作包 PDF':'文字制作包'));
    }catch(err){if(here(s))toast(err.message||'制作包暂不可用，请重试。',true);}finally{restoreButton(s,el,previousFocus);}
  }
  function copyAll(el){return packageAction(el,false);}
  function download(el){return packageAction(el,true);}
  async function restore(saved,context){
    if(!saved?.projectId||!['choose','records','result','handoff'].includes(saved.stage))return;
    const match=location.hash.match(/^#\/campaigns\/([^/]+)/);if(!match||decodeURIComponent(match[1])!==saved.projectId)return;
    try{
      const response=await jget('/api/projects/'+encodeURIComponent(saved.projectId));if(!context.isCurrent())return;
      const p=response.project,d=await jget('/api/projects/'+encodeURIComponent(saved.projectId)+'/assist');if(!context.isCurrent())return;
      const runs=(d.runs||[]).filter(x=>x.capability==='video_prompts');let run=runs.find(x=>x.id===saved.runId)||null;
      if(saved.runId&&!run){run=(await jget('/api/projects/'+encodeURIComponent(saved.projectId)+'/assist/'+encodeURIComponent(saved.runId))).run;if(!context.isCurrent())return;}
      if(p?.id!==saved.projectId||run&&run.capability!=='video_prompts')throw new Error('记录与当前项目的提示词不匹配。');
      const stage=['result','handoff'].includes(saved.stage)&&!run?'records':saved.stage;
      show({hash:location.hash,project:stage==='choose'?currentDraft(p):p,stage,run,runs,mode:validMode(saved.mode)?saved.mode:validMode(runMode(run))?runMode(run):'image',selectedRunId:saved.runId||'',parentStage:saved.parentStage||'',busy:false,loading:false,error:'',listFailed:false,conflict:false},false,context.options);
    }catch(err){if(context.isCurrent())toast('恢复提示词失败，请从已有记录重新打开。'+err.message,true);}
  }
  window.MarketingOverlay?.register?.('video-prompts',restore);
  document.addEventListener('keydown',ev=>{if(!host())return;if(ev.key==='Escape'){ev.preventDefault();ev.stopImmediatePropagation();close();}},true);
  window.addEventListener('hashchange',()=>{if(state&&state.hash===location.hash&&host())return;++serial;clearTimeout(poll);state=null;});
  return {open,close,choose,showRecords,selectMode,retryRecords,openRun,generate,copy,prepareProduction,back,backToPrompts,sources,copyAll,download};
})();
