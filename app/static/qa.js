/* Book-grounded questions. Generated text is always escaped; citations are local IDs. */
'use strict';
window.BookQA=(function(){
  const Q={host:null,status:null,statusError:'',storageError:false,sessions:[],current:null,loaded:false,pending:null,draft:'',selectedTurn:'',selectedSource:null,expandedTurns:[],deletion:null,renderId:0,statusRequest:0,dialogToken:0};
  const e=value=>String(value==null?'':value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const arr=value=>Array.isArray(value)?value:[];
  const count=value=>Math.max(0,Math.floor(Number(value)||0));
  const text=value=>typeof value==='string'?value:'';
  const uid=()=>globalThis.crypto?.randomUUID?.()||'qa-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
  const icons={trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',spark:'<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6L12 3Z"/>',arrow:'<path d="M12 19V5m-6 6 6-6 6 6"/>',book:'<path d="M12 5v15M3 4c4-1 6 0 9 2 3-2 5-3 9-2v15c-4-1-6 0-9 2-3-2-5-3-9-2V4Z"/>',history:'<path d="M3 11a9 9 0 1 1 3 8M3 4v7h7M12 7v5l3 2"/>',plus:'<path d="M12 5v14M5 12h14"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>',copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 4V3H3v13h2"/>',quote:'<path d="M10 5H3v8h5c0 3-2 5-4 6M21 5h-7v8h5c0 3-2 5-4 6"/>',compare:'<path d="M7 3v18M17 3v18M3 7l4-4 4 4M13 17l4 4 4-4"/>',chevron:'<path d="m8 5 7 7-7 7"/>',check:'<path d="m5 12 4 4L19 6"/>'};
  function icon(name){return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(icons[name]||icons.spark)+'</svg>';}
  function action(label,name,attrs,cls,disabled){return '<button type="button" class="qa-button '+(cls||'')+'" data-qa-action="'+name+'"'+Object.entries(attrs||{}).map(([k,v])=>' data-'+k+'="'+e(v)+'"').join('')+(disabled?' disabled':'')+'>'+label+'</button>';}
  function storageKey(){return 'bookworld.qa.v1:'+location.origin+':'+(document.querySelector('.workspace-name')?.textContent||'local');}
  function normalizeSource(s,i){return {id:count(s?.id)||i+1,code:text(s?.code),book:text(s?.book),title:text(s?.title),chapter:text(s?.chapter),anchor:text(s?.anchor),quote:text(s?.quote)};}
  function normalizeSession(s){
    if(!s||typeof s.id!=='string'||!Array.isArray(s.turns))return null;
    return {id:s.id,title:text(s.title).slice(0,100),created_at:text(s.created_at),updated_at:text(s.updated_at),book_codes:arr(s.book_codes).filter(x=>typeof x==='string'),clc_code:text(s.clc_code),turns:s.turns.slice(-60).filter(t=>t&&typeof t.question==='string').map(t=>({id:text(t.id)||uid(),question:t.question,answer:text(t.answer),sources:arr(t.sources).map(normalizeSource),suggestions:arr(t.suggestions).filter(x=>typeof x==='string'),mode:text(t.mode),retryable:typeof t.retryable==='boolean'?t.retryable:undefined,notice:text(t.notice),scope:t.scope&&typeof t.scope==='object'?t.scope:{},status:t.status==='pending'?'error':text(t.status)||'done',error:t.status==='pending'?'上次请求尚未取得结果，可以重新提问。':text(t.error),created_at:text(t.created_at)}))};
  }
  function hasAnswer(t){return t?.status==='done'&&t.mode==='answer'&&!!text(t.answer).trim();}
  const sourceNotice='回答依据当前检索到的原文生成；书中观点与现实事实仍需区分。';
  const libraryUpdateNotice='书库已更新。这条回答保留生成时的内容，可按当前书库重新提问。';
  function materialNotice(t){const notice=text(t.notice).trim();return notice.startsWith(sourceNotice)?notice.slice(sourceNotice.length).trim():notice;}
  function libraryChanged(t){return !Q.statusError&&!!t.scope?.revision&&!!Q.status?.revision&&t.scope.revision!==Q.status.revision;}
  function pendingQuestion(s){const last=s?.turns.at(-1);return last&&last.status!=='pending'&&!hasAnswer(last)?last.question:'';}
  function restore(){if(Q.loaded)return;Q.loaded=true;try{const saved=JSON.parse(localStorage.getItem(storageKey())||'{}');Q.sessions=arr(saved.sessions).map(normalizeSession).filter(Boolean).slice(0,30);Q.current=Q.sessions.find(s=>s.id===saved.current)||null;Q.draft=pendingQuestion(Q.current);}catch(_){Q.sessions=[];}}
  function save(){try{localStorage.setItem(storageKey(),JSON.stringify({current:Q.current?.id,sessions:Q.sessions.filter(s=>s.turns.length).slice(0,30)}));Q.storageError=false;}catch(_){Q.storageError=true;}}
  function emptySession(codes,clcCode=''){return {id:uid(),title:'新话题',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),book_codes:[...(codes||[])],clc_code:clcCode,turns:[]};}
  function fresh(codes,clcCode=''){const s=emptySession(codes,clcCode);Q.current=s;Q.draft=pendingQuestion(s);Q.selectedTurn='';Q.selectedSource=null;Q.expandedTurns=[];return s;}
  function active(){return Q.host?.isConnected&&/^#\/qa(?:\/|$)/.test(location.hash);}
  function busy(){return !!Q.pending;}
  function books(){return arr(Q.status?.books);}
  function categoryBooks(){const code=Q.current?.clc_code||'';return books().filter(b=>!code||b.clc_code===code);}
  function selectedBooks(){const codes=Q.current?.book_codes||[];return categoryBooks().filter(b=>!codes.length||codes.includes(b.code));}
  function searchableCount(book){return count(book.searchable_segments??book.segments);}
  function searchableBooks(){return selectedBooks().filter(b=>searchableCount(b)>0);}
  function canAsk(){return !!Q.status?.ready&&searchableBooks().length>0;}
  function sourceLink(book){return '#/book/'+encodeURIComponent(book.code)+'/overview';}
  function categoryName(code){return text(arr(Q.status?.classifications).find(c=>c.code===code)?.name)||(code==='unclassified'?'未分类':code);}
  function sessionScope(s){return scopeLabel(s.book_codes)+(s.clc_code?' · '+categoryName(s.clc_code):'');}
  function bookTitle(code){return text(books().find(b=>b.code===code)?.title)||code;}
  function scopeLabel(codes){return codes.length?'已选 '+codes.length+' 本图书':'全部图书';}
  function currentTurn(){return Q.current?.turns.find(t=>t.id===Q.selectedTurn&&hasAnswer(t))||[...(Q.current?.turns||[])].reverse().find(hasAnswer)||null;}
  async function request(url,body,timeout){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout||25000);
    try{
      const response=await fetch(url,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
      let data;try{data=await response.json();}catch(_){throw new Error('服务暂未返回有效结果，请稍后重试。');}
      if(!response.ok||data.ok===false)throw new Error(text(data.error)||text(data.message)||'请求未完成（'+response.status+'），请稍后重试。');
      return data;
    }catch(err){if(err.name==='AbortError')throw new Error('等待响应超时，问题已保留。服务端可能仍在处理，请稍后重试。');throw err;}finally{clearTimeout(timer);}
  }
  function constellation(){return '<div class="qa-constellation" aria-hidden="true"><div class="qa-orbit qa-orbit-one"></div><div class="qa-orbit qa-orbit-two"></div><div class="qa-orbit qa-orbit-three"></div><div class="qa-orbit-core">'+icon('spark')+'</div><span class="qa-orbit-node qa-node-a">'+icon('book')+'</span><span class="qa-orbit-node qa-node-b">'+icon('quote')+'</span><span class="qa-orbit-dot qa-dot-a"></span><span class="qa-orbit-dot qa-dot-b"></span></div>';}
  function toolbar(){return '<header class="qa-topline"><a href="#/apps" class="qa-back">内容应用 <span aria-hidden="true">/</span></a><span class="qa-page-label">智能问答</span><div class="qa-top-actions">'+action(icon('history')+'历史对话','history',{},'',busy())+action(icon('plus')+'新话题','new',{},'',busy())+(Q.current?.turns.length?action(icon('trash')+'删除对话','deleteSession',{id:Q.current.id},'qa-delete-current',busy()):'')+'</div></header>';}
  function hero(compact){return '<div class="qa-hero'+(compact?' qa-hero-compact':'')+'"><div class="qa-hero-copy"><div class="qa-kicker"><span class="qa-mini-spark">'+icon('spark')+'</span> 与书对话 · 有据可循</div><h1>让每一个问题，<br class="qa-mobile-break">都有书可循。</h1><p>从书中找到答案，让每个判断都有出处。</p></div>'+constellation()+'</div>';}
  function statusHtml(){
    if(Q.statusError)return '<div class="qa-notice qa-notice-error" role="alert"><span>'+e(Q.statusError)+'</span>'+action('重新连接','refresh',{},'qa-button-small')+'</div>';
    if(!Q.status)return '<div class="qa-service-status" role="status"><span class="qa-status-dot"></span>正在读取可用图书…</div>';
    const scoped=selectedBooks(), ready=searchableBooks();
    const unavailable=scoped.filter(b=>!searchableCount(b));
    const book=unavailable.length===1?unavailable[0]:null;
    const link=book?'<a href="'+e(sourceLink(book))+'">检查来源 '+icon('chevron')+'</a>':'<a href="#/library">查看来源图书 '+icon('chevron')+'</a>';
    if(!ready.length){
      const reason=book?.unavailable_reason||(scoped.length?'当前选书暂无符合问答条件的正文。':'当前分类或选书范围内暂无可提问图书，请调整范围。');
      return '<div class="qa-notice" role="status"><span>'+e(reason)+'</span>'+link+'</div>';
    }
    return '<div class="qa-service-status"><span class="qa-status-dot qa-status-ready"></span><span>'+ready.length+' 本图书可检索</span><span class="qa-status-separator">·</span><span>'+ready.reduce((total,b)=>total+searchableCount(b),0).toLocaleString('zh-CN')+' 段原文可回查</span>'+(unavailable.length?'<span class="qa-status-limited">'+unavailable.length+' 本暂无可检索正文</span>':'')+(Q.status.model_ready===false?'<span class="qa-status-limited">当前提供原文检索，回答服务待连接</span>':'')+'</div>';
  }
  function scopeChips(){
    const codes=Q.current.book_codes,clc=Q.current.clc_code||'',categories=arr(Q.status?.classifications).filter(c=>c.book_count>0||c.code===clc);
    if(clc&&!categories.some(c=>c.code===clc))categories.push({code:clc,name:categoryName(clc),book_count:0});
    return '<div class="qa-scope-row">'+action(icon('book')+'<span>'+e(scopeLabel(codes))+'</span><span class="qa-scope-chevron">⌄</span>','scope',{},'qa-scope-button',busy())+'<label class="qa-clc-filter"><span class="qa-sr-only">中图分类</span><select aria-label="中图分类" data-qa-clc'+(busy()||!Q.status?' disabled':'')+'><option value=""'+(!clc?' selected':'')+'>中图分类 · 全部分类</option>'+categories.map(c=>'<option value="'+e(c.code)+'"'+(clc===c.code?' selected':'')+'>'+e((c.code==='unclassified'?'':c.code+' ')+c.name)+'（'+count(c.book_count)+'）</option>').join('')+'</select><span class="qa-scope-chevron" aria-hidden="true">⌄</span></label>'+(codes.length?'':'<span class="qa-scope-auto">'+(clc?'新入库同类图书自动纳入':'新入库图书自动纳入')+'</span>')+'</div>';
  }
  function changeCategory(code){
    if(busy()||code===(Q.current.clc_code||''))return;
    const draft=Q.draft,hadTurns=!!Q.current.turns.length;
    if(hadTurns)fresh([],code);else{Q.current.clc_code=code;Q.current.book_codes=[];}
    Q.draft=draft;save();draw();
    if(hadTurns&&typeof toast==='function')toast('已切换分类并开始新对话，原对话保存在历史中');
    Q.host?.querySelector('[data-qa-clc]')?.focus();
  }
  function composer(followup){
    const send='<button type="submit" class="qa-send" aria-label="发送问题"'+(busy()||!canAsk()||!Q.draft.trim()?' disabled':'')+'><span>'+(busy()?'处理中':followup?'发送':'开始提问')+'</span>'+icon('arrow')+'</button>';
    const hint='<span class="qa-input-hint">'+(busy()?'正在处理，请稍候':'Enter 发送 · Shift + Enter 换行')+'</span>';
    if(followup)return '<form class="qa-composer qa-composer-followup" data-qa-form><div class="qa-followup-toolbar"><label for="qaQuestion">继续追问</label><span class="qa-followup-context">'+(Q.current.turns.some(hasAnswer)?'接着上面的回答提问':'继续当前话题')+'</span>'+scopeChips()+'</div><div class="qa-followup-input"><textarea id="qaQuestion" name="question" rows="1" maxlength="1200" placeholder="输入你还想了解的问题…"'+(busy()?' readonly':'')+'>'+e(Q.draft)+'</textarea>'+send+'</div><div class="qa-followup-footer">'+hint+action(icon('plus')+'新话题','new',{},'qa-topic-new',busy())+'</div></form>';
    return '<form class="qa-composer" data-qa-form>'+scopeChips()+'<label class="qa-sr-only" for="qaQuestion">输入你的问题</label><textarea id="qaQuestion" name="question" rows="3" maxlength="1200" placeholder="你想从书中了解什么？例如：这些书怎样理解人与自然的关系？"'+(busy()?' readonly':'')+'>'+e(Q.draft)+'</textarea><div class="qa-composer-bottom">'+hint+send+'</div></form><p class="qa-composer-note">答案依据所选图书生成，重要判断请结合原文核对。</p>';
  }
  function examples(){
    const scoped=searchableBooks();const first=scoped[0]?.title;
    const samples=[{icon:'spark',label:'解释一个概念',desc:'输入概念，理解书中的含义',selection:'[填入概念]',q:(first?'《'+first+'》中，':'所选图书中，')+'“[填入概念]”是什么意思？请结合原文解释。'},{icon:'quote',label:'找到原文依据',desc:'输入主题，查找相关原文',selection:'[填入主题]',q:'请从所选图书中找出与“[填入主题]”有关的原文，并注明出处。'},{icon:'compare',label:'比较不同观点',desc:'围绕共同主题，比较书中观点',selection:'[填入共同主题]',q:'所选图书对“[填入共同主题]”有哪些不同观点？请分别提供原文依据。'}];
    const concept=scoped.find(b=>text(b.sample_question)),quote=scoped.find(b=>text(b.sample_quote_question));
    if(concept)Object.assign(samples[0],{q:concept.sample_question,desc:concept.sample_question,selection:''});
    if(quote)Object.assign(samples[1],{q:quote.sample_quote_question,desc:quote.sample_quote_question,selection:''});
    return '<div class="qa-example-heading"><span>从一个具体问题开始</span><span>'+(concept||quote?'点击问题，按你的需要调整':'选择任务，填入你的关键词')+'</span></div><div class="qa-examples">'+samples.map((s,i)=>'<button type="button" class="qa-example" data-qa-action="example" data-question="'+e(s.q)+'" data-selection="'+e(s.selection)+'"'+(busy()?' disabled':'')+'><span class="qa-example-icon qa-example-icon-'+i+'">'+icon(s.icon)+'</span><strong>'+s.label+'</strong><span class="qa-example-description" title="'+e(s.desc)+'">'+e(s.desc)+'</span><span class="qa-example-arrow" aria-hidden="true">↗</span></button>').join('')+'</div>';
  }

  function answerText(value,turn){
    const valid=new Set(turn.sources.map(s=>String(s.id)));
    const inline=line=>e(line).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>').replace(/\[(\d+)\]/g,(all,id)=>valid.has(id)?'<button type="button" class="qa-citation" data-qa-action="cite" data-turn="'+e(turn.id)+'" data-source="'+id+'" aria-label="查看引用 '+id+'">'+id+'</button>':all);
    return String(value||'').split(/\n\s*\n/).map(block=>{
      const lines=block.trim().split('\n');
      if(!block.trim())return '';
      if(lines.every(line=>/^\s*[-*]\s+/.test(line)))return '<ul>'+lines.map(line=>'<li>'+inline(line.replace(/^\s*[-*]\s+/,''))+'</li>').join('')+'</ul>';
      if(lines.every(line=>/^\s*\d+[.)、]\s*/.test(line)))return '<ol>'+lines.map(line=>'<li>'+inline(line.replace(/^\s*\d+[.)、]\s*/,''))+'</li>').join('')+'</ol>';
      return '<p>'+lines.map(line=>/^#{1,4}\s/.test(line)?'<strong>'+inline(line.replace(/^#{1,4}\s+/,''))+'</strong>':inline(line)).join('<br>')+'</p>';
    }).join('');
  }
  function turnHtml(t,index){
    const notice=materialNotice(t);
    let body='';
    if(t.status==='pending')body='<div class="qa-thinking" role="status"><span class="qa-thinking-mark">'+icon('spark')+'</span><div><strong>正在检索图书并整理回答</strong><span>完成后会展示回答和可核对的出处，请稍候。</span></div><span class="qa-thinking-dots" aria-hidden="true"><i></i><i></i><i></i></span></div>';
    else if(hasAnswer(t))body='<div class="qa-answer-label"><span class="qa-answer-mark">'+icon('spark')+'</span><strong>回答</strong></div><div class="qa-answer-prose">'+answerText(t.answer,t)+'</div>'+(notice?'<p class="qa-answer-note">'+e(notice)+'</p>':'')+(libraryChanged(t)?'<p class="qa-answer-note qa-library-update">'+libraryUpdateNotice+'</p>':'')+'<div class="qa-answer-actions">'+action(icon('copy')+'复制回答','copy',{turn:t.id},'qa-button-small')+(t.sources.length?action(icon('book')+'查看 '+t.sources.length+' 处依据','sources',{turn:t.id},'qa-button-small'):'')+action(icon('trash')+'删除问答','deleteTurn',{turn:t.id},'qa-button-small qa-delete-turn',busy())+'</div>';
    else {
      const message=t.status==='error'?t.error:notice;
      body='<div class="qa-answer-note" role="status">'+e(message||(t.sources.length?'已找到原文，暂无法完成回答。':'这次没有得到足够依据。可以调整问题或选书范围。'))+'</div>'+
        (t.sources.length?sourceCards(t):'')+
        '<div class="qa-answer-actions">'+action('修改问题','editQuestion',{turn:t.id},'qa-button-small',busy())+
        (t.status==='error'||t.retryable===true?action('重试','retry',{turn:t.id},'qa-button-small',busy()):'')+
        action(icon('trash')+'删除此条','deleteTurn',{turn:t.id},'qa-button-small qa-delete-turn',busy())+'</div>';
    }
    return '<article class="qa-turn" id="qaTurn-'+e(t.id)+'"><div class="qa-question"><span class="qa-question-number">'+String(index+1).padStart(2,'0')+'</span><div><h2>'+e(t.question)+'</h2><span class="qa-turn-scope">'+e(sessionScope(Q.current))+(t.scope?.book_count!=null?' · '+count(t.scope.book_count)+' 本':'')+'</span></div></div><div class="qa-answer">'+body+'</div></article>';
  }
  function transcriptHtml(turns){
    const visible=turns.filter((t,i)=>i===turns.length-1||hasAnswer(t));
    return visible.map((t,i)=>{
      if(i===visible.length-1)return turnHtml(t,i);
      const label='已回答';
      return '<details class="qa-previous-turn" data-qa-previous="'+e(t.id)+'"'+(Q.expandedTurns.includes(t.id)?' open':'')+'><summary><span class="qa-previous-number">'+String(i+1).padStart(2,'0')+'</span><span class="qa-previous-question">'+e(t.question)+'</span><span class="qa-previous-status">'+label+'</span><span class="qa-previous-hint">展开</span>'+action(icon('trash')+'<span class="qa-sr-only">删除问答：'+e(t.question)+'</span>','deleteTurn',{turn:t.id},'qa-delete-summary',busy())+'</summary>'+turnHtml(t,i)+'</details>';
    }).join('');
  }
  function sourceCards(turn){return turn.sources.map(s=>'<article class="qa-source-card'+(Q.selectedSource===s.id?' is-selected':'')+'" id="qaSource-'+s.id+'" tabindex="-1"><div class="qa-source-title"><span class="qa-source-number">'+s.id+'</span><strong>'+e(s.book||s.code)+'</strong></div><p class="qa-source-chapter">'+e([s.title,s.chapter].filter(Boolean).join(' · ')||'原文片段')+'</p><blockquote>'+e(s.quote)+'</blockquote>'+action('查看上下文 '+icon('chevron'),'context',{turn:turn.id,source:s.id},'qa-source-open',!s.anchor||!s.code)+'</article>').join('');}
  function suggestions(){const t=Q.current?.turns.at(-1);if(!hasAnswer(t)||busy()||!t.suggestions.length)return '';return '<div class="qa-followup-suggestions"><span>继续探索</span>'+t.suggestions.slice(0,3).map(q=>action(e(q)+' <span aria-hidden="true">↗</span>','example',{question:q},'qa-suggestion')).join('')+'</div>';}
  function draw(){
    Q.deletion=null;
    if(!active())return;
    const focused=Q.host.querySelector('#qaQuestion'),keepFocus=focused===document.activeElement,selection=keepFocus?[focused.selectionStart,focused.selectionEnd]:null;
    const turns=Q.current.turns;
    Q.host.classList.toggle('qa-has-conversation',!!turns.length);
    Q.host.innerHTML=toolbar()+(turns.length?'<div class="qa-conversation-heading"><h1>与书对话</h1><p>先看回答，点击引用编号可核对原文。</p></div>':hero(false))+(turns.length?'<div class="qa-conversation-top">'+statusHtml()+'</div><div class="qa-conversation-layout"><div class="qa-conversation-main"><div class="qa-transcript" aria-label="问答记录">'+transcriptHtml(turns)+'</div>'+suggestions()+'<div class="qa-followup-compose">'+composer(true)+'</div></div>'+'</div>':'<div class="qa-welcome">'+composer(false)+statusHtml()+examples()+'<div class="qa-promise"><span>'+icon('check')+' 每个引用可回查</span><span>'+icon('check')+' 支持连续追问</span><span>'+icon('check')+' 可选单书或跨书</span></div></div>')+'<p class="qa-local-note" data-qa-storage>'+(Q.storageError?'当前浏览器无法保存记录，本页内容仍可继续使用；关闭前请复制重要回答。':'对话保存在当前浏览器中，仅供本地查阅。')+'</p><div class="qa-live" role="status" aria-live="polite"></div><dialog class="qa-dialog" aria-labelledby="qaDialogTitle"></dialog>';
    resizeInput();
    if(keepFocus){const input=Q.host.querySelector('#qaQuestion');input?.focus({preventScroll:true});if(selection)input?.setSelectionRange(...selection);}
  }
  function resizeInput(){const el=Q.host?.querySelector('#qaQuestion');if(!el)return;el.style.height='auto';const followup=!!Q.current?.turns.length;el.style.height=Math.min(followup?160:220,Math.max(followup?36:80,el.scrollHeight))+'px';}
  function announce(message){const el=Q.host?.querySelector('.qa-live');if(el)el.textContent=message;}
  function focusInput(selection){requestAnimationFrame(()=>{if(active()){const input=Q.host.querySelector('#qaQuestion');if(!input)return;input.focus();const at=selection?input.value.indexOf(selection):-1;input.setSelectionRange(at>=0?at:input.value.length,at>=0?at+selection.length:input.value.length);}});}
  async function refresh(timeout){const rid=Q.renderId,requestId=++Q.statusRequest;Q.statusError='';try{const data=await request('/api/qa/status',undefined,timeout||25000);if(rid!==Q.renderId||requestId!==Q.statusRequest)return;Q.status=data;}catch(err){if(rid!==Q.renderId||requestId!==Q.statusRequest)return;Q.statusError='图书连接暂不可用：'+err.message;}draw();}
  function closeDialog(){const d=Q.host?.querySelector('dialog');if(d?.open)d.close();Q.deletion=null;Q.dialogToken++;}
  function openDialog(kind,title,body){
    closeDialog();const d=Q.host?.querySelector('dialog');if(!d)return null;
    d.className='qa-dialog qa-dialog-'+kind;d.innerHTML='<div class="qa-dialog-head"><div><span class="qa-dialog-kicker">智能问答</span><h2 id="qaDialogTitle">'+e(title)+'</h2></div>'+action(icon('close')+'<span class="qa-sr-only">关闭</span>','close',{},'qa-dialog-close')+'</div><div class="qa-dialog-body">'+body+'</div>';
    d.onclick=event=>{if(event.target===d){const r=d.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeDialog();}};
    d.oncancel=()=>{Q.deletion=null;Q.dialogToken++;};
    d.showModal();return d;
  }
  async function openScope(){
    await refresh(8000);if(!active()||busy())return;
    const codes=Q.current.book_codes,available=categoryBooks(),classified=!!Q.current.clc_code;
    openDialog('scope','选择提问范围','<p class="qa-dialog-description">'+(Q.current.turns.length?'更换范围后会开始新对话，当前记录会保留。':'选择需要参考的图书，让回答更贴近你的问题。')+(classified?' 当前分类：'+e(categoryName(Q.current.clc_code))+'。':'')+'</p><label class="qa-scope-all"><input type="checkbox" data-qa-all'+(!codes.length?' checked':'')+'><span><strong>'+(classified?'本类全部图书':'全部图书')+'</strong><small>'+(classified?'自动包含之后新入库的同类图书':'自动包含之后新解析入库的图书')+'</small></span><span class="qa-choice-count">'+available.length+'</span></label><div class="qa-book-options">'+available.map(b=>'<label class="qa-book-option"><input type="checkbox" value="'+e(b.code)+'" data-qa-book'+(!codes.length||codes.includes(b.code)?' checked':'')+'><span>'+icon('book')+'</span><strong>'+e(b.title)+'</strong><small>'+(searchableCount(b)?searchableCount(b).toLocaleString('zh-CN')+' 段':'待处理来源')+'</small></label>').join('')+(!available.length?'<p class="qa-dialog-description">当前分类暂无可提问图书，请选择其他分类。</p>':'')+'</div><p class="qa-scope-error" role="alert"></p><div class="qa-dialog-footer">'+action('应用范围','applyScope',{},'qa-button-primary')+'</div>');
  }
  function applyScope(){const d=Q.host.querySelector('dialog'),all=d.querySelector('[data-qa-all]').checked,codes=all?[]:[...d.querySelectorAll('[data-qa-book]:checked')].map(x=>x.value);if(!all&&!codes.length){d.querySelector('.qa-scope-error').textContent='请至少选择一本图书，或选择全部图书。';return;}const changed=JSON.stringify([...codes].sort())!==JSON.stringify([...Q.current.book_codes].sort());closeDialog();if(changed){if(Q.current.turns.length)fresh(codes,Q.current.clc_code||'');else Q.current.book_codes=codes;save();draw();}focusInput();}
  function openHistory(){
    const sessions=Q.sessions.filter(s=>s.turns.length).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
    openDialog('history','历史对话','<p class="qa-dialog-description">保存在此浏览器，最多保留最近 30 个对话。</p>'+(sessions.length?'<div class="qa-history-list">'+sessions.map(s=>'<div class="qa-history-row"><button class="qa-history-item'+(s.id===Q.current.id?' is-current':'')+'" type="button" data-qa-action="loadSession" data-id="'+e(s.id)+'"><span class="qa-history-icon">'+icon('history')+'</span><span><strong>'+e(s.title)+'</strong><small>'+e(s.updated_at?new Date(s.updated_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'')+' · '+s.turns.length+' 个问题 · '+e(sessionScope(s))+'</small></span>'+icon('chevron')+'</button>'+action(icon('trash')+'删除<span class="qa-sr-only">对话：'+e(s.title)+'</span>','deleteSession',{id:s.id,history:'true'},'qa-delete-history',busy())+'</div>').join('')+'</div>':'<div class="qa-history-empty">'+icon('history')+'<h3>从第一个问题开始</h3><p>完成提问后，对话会自动保存在这里。</p></div>'));
  }
  function openDelete(kind,id,fromHistory=false){
    if(!active()||busy()||!['turn','session'].includes(kind))return;
    const session=kind==='turn'?Q.current:[Q.current,...Q.sessions].find(s=>s.id===id);
    const turn=kind==='turn'?session?.turns.find(t=>t.id===id):null;
    if(!session?.turns.length||(kind==='turn'&&!turn)||turn?.status==='pending')return;
    const single=kind==='turn',label=single?'删除这次问答':'删除整段对话';
    const dialog=openDialog('delete',label+'？','<p class="qa-dialog-description">'+(single?'这次提问、回答和引用将被删除，后续追问不再使用这条记录。其他问答保留。':'这段对话中的全部问答和引用将被删除。')+'删除后无法恢复。</p><div class="qa-delete-preview"><strong>'+e(single?turn.question:session.title)+'</strong>'+(!single?'<span>'+session.turns.length+' 次问答</span>':'')+'</div><p class="qa-delete-error" role="alert"></p><div class="qa-dialog-footer qa-delete-footer">'+action('取消','cancelDelete',{},'')+action(label,'confirmDelete',{},'qa-button-danger')+'</div>');
    if(dialog)Q.deletion={sessionId:session.id,turnId:turn?.id||'',fromHistory:!!fromHistory};
  }
  function cancelDelete(){const fromHistory=Q.deletion?.fromHistory;closeDialog();if(fromHistory&&active())openHistory();}
  function confirmDelete(){
    const target=Q.deletion;
    if(!active()||busy()||!target||!Q.host.querySelector('dialog')?.open)return false;
    const session=[Q.current,...Q.sessions].find(s=>s.id===target.sessionId);
    const removed=target.turnId?session?.turns.find(t=>t.id===target.turnId):null;
    if(!session||!session.turns.length||(target.turnId&&!removed)||removed?.status==='pending')return false;
    const turns=target.turnId?session.turns.filter(t=>t.id!==target.turnId):[];
    const nextSession=turns.length?{...session,turns,title:turns[0].question.slice(0,60),updated_at:new Date().toISOString()}:null;
    const nextSessions=Q.sessions.filter(s=>s.id!==session.id);
    if(nextSession)nextSessions.push(nextSession);
    nextSessions.sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
    const isCurrent=Q.current.id===session.id;
    const nextCurrent=isCurrent?(nextSession||emptySession(session.book_codes,session.clc_code||'')):Q.current;
    // Commit storage first. A failed write must not erase records in this page
    // or pretend they will stay deleted after a reload.
    try{localStorage.setItem(storageKey(),JSON.stringify({current:nextCurrent.id,sessions:nextSessions.filter(s=>s.turns.length).slice(0,30)}));}
    catch(_){Q.storageError=true;const error=Q.host.querySelector('dialog')?.querySelector('.qa-delete-error');if(error)error.textContent='未能保存删除操作，记录已保留。请重试。';announce('未能保存删除操作，记录已保留。');return false;}
    let draft=Q.draft;
    if(isCurrent&&!target.turnId)draft='';
    else if(isCurrent&&removed?.question===pendingQuestion(session)&&draft===removed.question)draft=pendingQuestion(nextCurrent);
    Q.sessions=nextSessions;Q.current=nextCurrent;Q.draft=draft;Q.storageError=false;
    if(isCurrent){
      Q.expandedTurns=Q.expandedTurns.filter(id=>nextCurrent.turns.some(t=>t.id===id));
      if(!nextSession||Q.selectedTurn===target.turnId){Q.selectedTurn='';Q.selectedSource=null;}
    }
    closeDialog();draw();
    const message=target.turnId?'已删除这次问答':'已删除整段对话';announce(message);if(typeof toast==='function')toast(message);
    if(target.fromHistory)openHistory();else focusInput();
    return true;
  }
  async function openContext(turnId,sourceId){
    const t=Q.current.turns.find(x=>x.id===turnId),s=t?.sources.find(x=>x.id===Number(sourceId));if(!s||!s.code||!s.anchor)return;
    const d=openDialog('context','阅读原文','<div class="qa-context-meta"><strong>'+e(s.book||s.code)+'</strong><span>'+e(s.chapter)+'</span></div><p class="qa-dialog-description">以下为当前原文。引用记录保留本次回答时的片段。</p><div class="qa-context-content" aria-busy="true"><p role="status">正在定位引用段落…</p></div>');
    const token=Q.dialogToken;
    try{const data=await request('/api/book/segment?'+new URLSearchParams({code:s.code,anchor:s.anchor,radius:'2'}));if(token!==Q.dialogToken||!d?.open)return;const rows=arr(data.items);d.querySelector('.qa-context-content').innerHTML=rows.length?rows.map(row=>'<section class="qa-context-paragraph'+(row.hit?' is-hit':'')+'"><div><span>'+e(row['篇']||s.chapter)+'</span><span>'+(row.hit?'引用段落':row['段']!=null?'第 '+e(row['段'])+' 段':'上下文')+'</span></div><p>'+e(row['文本']||'')+'</p></section>').join(''):'<p>当前无法找到该原文段落，图书可能已更新或移除。</p>';d.querySelector('.qa-context-content').setAttribute('aria-busy','false');}
    catch(err){if(token!==Q.dialogToken||!d?.open)return;d.querySelector('.qa-context-content').innerHTML='<div class="qa-answer-error" role="alert"><p>'+e(err.message)+'</p>'+action('重新读取','context',{turn:turnId,source:sourceId},'qa-button-small')+'</div>';d.querySelector('.qa-context-content').setAttribute('aria-busy','false');}
  }
  function selectSource(turnId,sourceId){
    if(!hasAnswer(Q.current.turns.find(t=>t.id===turnId)))return;
    Q.selectedTurn=turnId;Q.selectedSource=sourceId?Number(sourceId):null;
    const t=currentTurn();if(!t)return;
    openDialog('evidence','回答依据','<p class="qa-dialog-description">'+e(t.question)+'</p><p class="qa-dialog-description">'+e(t.notice||sourceNotice)+'</p>'+(libraryChanged(t)?'<p class="qa-dialog-description">书库已更新。以下保留回答生成时的引用；查看上下文时读取当前原文。</p>':'')+sourceCards(t));
    if(sourceId){const target=Q.host.querySelector('dialog #qaSource-'+Number(sourceId));target?.scrollIntoView({block:'nearest'});target?.focus({preventScroll:true});}
  }
  async function copyAnswer(turnId){
    const sessionId=Q.current.id,rid=Q.renderId,token=Q.dialogToken;
    const t=Q.current.turns.find(x=>x.id===turnId);if(!hasAnswer(t))return;
    const current=()=>active()&&Q.renderId===rid&&Q.dialogToken===token&&Q.current.id===sessionId&&Q.current.turns.some(x=>x.id===turnId&&hasAnswer(x));
    const notice=materialNotice(t),content=t.question+'\n\n'+t.answer+(notice?'\n\n'+notice:'')+(libraryChanged(t)?'\n\n'+libraryUpdateNotice:'')+(t.sources.length?'\n\n来源：\n'+t.sources.map(s=>'['+s.id+'] 《'+s.book+'》 '+s.chapter+'\n'+s.quote).join('\n\n'):'');
    try{await navigator.clipboard.writeText(content);if(!current())return;announce('回答与出处已复制');if(typeof toast==='function')toast('回答与出处已复制');}
    catch(_){if(!current())return;openDialog('copy','复制回答','<p class="qa-dialog-description">浏览器未允许自动复制，可以选择下方文字手动复制。</p><textarea class="qa-copy-text" readonly aria-label="回答及出处">'+e(content)+'</textarea>');Q.host.querySelector('.qa-copy-text')?.select();}
  }
  function questionHistory(turns){
    const settled=turns.filter(t=>t.status==='done'||t.status==='error');
    const recent=settled.slice(-4),lastAnswered=[...settled].reverse().find(hasAnswer);
    if(lastAnswered&&!recent.includes(lastAnswered))recent.unshift(lastAnswered);
    return recent.flatMap(t=>[{role:'user',content:t.question},...(hasAnswer(t)?[{role:'assistant',content:t.answer}]:[])]);
  }
  async function ask(question,retryId){
    const q=String(question||'').trim();if(!q||busy())return;if(!canAsk()){announce('当前选书暂无可检索的正文，请检查来源或调整范围。');return;}if(q.length>1200){announce('问题请控制在 1200 字以内');return;}if(/\[填入(?:概念|主题|共同主题)\]/.test(q)){const message='请先把方括号中的提示替换为你想了解的具体概念或主题。';announce(message);if(typeof toast==='function')toast(message);focusInput(q.match(/\[填入(?:概念|主题|共同主题)\]/)[0]);return;}
    const session=Q.current;
    let targetIndex=-1;
    if(retryId){targetIndex=session.turns.findIndex(t=>t.id===retryId);if(targetIndex<0)return;}
    else{const last=session.turns.at(-1),key=value=>String(value||'').trim().replace(/\s+/g,' ');if(last&&!hasAnswer(last)&&key(last.question)===key(q))targetIndex=session.turns.length-1;}
    const previous=targetIndex>=0?session.turns.slice(0,targetIndex):session.turns;
    const history=questionHistory(previous);
    let turn=targetIndex>=0?session.turns[targetIndex]:null;
    if(!turn){turn={id:uid(),question:q,answer:'',sources:[],suggestions:[],mode:'',notice:'',scope:{book_codes:[...session.book_codes],clc_code:session.clc_code||''},status:'pending',error:'',created_at:new Date().toISOString()};session.turns.push(turn);}else{turn.question=q;turn.status='pending';turn.error='';}
    session.title=session.turns[0].question.slice(0,60);session.updated_at=new Date().toISOString();if(!Q.sessions.some(s=>s.id===session.id))Q.sessions.unshift(session);Q.sessions=Q.sessions.slice(0,30);Q.pending={session:session.id,turn:turn.id};Q.draft='';Q.selectedTurn=turn.id;Q.selectedSource=null;save();draw();requestAnimationFrame(()=>Q.host?.querySelector('#qaTurn-'+turn.id)?.scrollIntoView({block:'nearest'}));
    try{
      const result=await request('/api/qa/ask',{question:q,book_codes:session.book_codes,clc_code:session.clc_code||'',history},150000);
      if(typeof result.answer!=='string')throw new Error('回答格式不完整，问题已保留，请重试。');
      Object.assign(turn,{answer:result.answer,sources:arr(result.sources).map(normalizeSource),suggestions:arr(result.suggestions).filter(x=>typeof x==='string'),mode:text(result.mode)||'answer',retryable:typeof result.retryable==='boolean'?result.retryable:undefined,notice:text(result.notice),scope:result.scope||{book_codes:session.book_codes,clc_code:session.clc_code||''},status:'done',error:''});
      // The server captures a fresh library revision on each question. Refresh metadata
      // before comparing it with a new answer; a long-open tab may have old book data.
      await refresh(8000);
    }catch(err){turn.status='error';turn.error=err.message||'连接暂时中断，请稍后重试。';if(Q.current.id===session.id)Q.draft=q;}
    finally{Q.pending=null;if(!hasAnswer(turn)&&Q.current.id===session.id&&!Q.draft)Q.draft=q;session.updated_at=new Date().toISOString();save();if(active()&&Q.current.id===session.id){draw();announce(hasAnswer(turn)?'回答已完成，提供 '+turn.sources.length+' 处来源':turn.error||turn.notice||'本次未生成回答。');}}
  }
  function events(host){
    host.addEventListener('toggle',event=>{const d=event.target;if(d.matches('details[data-qa-previous]')){Q.expandedTurns=Q.expandedTurns.filter(id=>id!==d.dataset.qaPrevious);if(d.open)Q.expandedTurns.push(d.dataset.qaPrevious);}},true);
    host.addEventListener('input',event=>{if(event.target.id==='qaQuestion'){Q.draft=event.target.value;resizeInput();const btn=host.querySelector('.qa-send');if(btn)btn.disabled=busy()||!canAsk()||!Q.draft.trim();}});
    host.addEventListener('change',event=>{if(event.target.matches('[data-qa-clc]')){changeCategory(event.target.value);return;}const d=host.querySelector('dialog');if(event.target.matches('[data-qa-all]'))d.querySelectorAll('[data-qa-book]').forEach(x=>x.checked=event.target.checked);else if(event.target.matches('[data-qa-book]'))d.querySelector('[data-qa-all]').checked=false;});
    host.addEventListener('keydown',event=>{if(event.target.id==='qaQuestion'&&event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();ask(Q.draft);}});
    host.addEventListener('submit',event=>{if(event.target.matches('[data-qa-form]')){event.preventDefault();ask(Q.draft);}});
    host.addEventListener('click',event=>{
      const el=event.target.closest('[data-qa-action]');if(!el||el.disabled)return;const a=el.dataset.qaAction;
      if(a==='close'){if(Q.deletion)cancelDelete();else closeDialog();}else if(a==='refresh')refresh();else if(a==='scope'&&!busy())openScope();else if(a==='applyScope'&&!busy())applyScope();else if(a==='history'&&!busy())openHistory();
      else if(a==='deleteTurn'){event.preventDefault();openDelete('turn',el.dataset.turn);}
      else if(a==='deleteSession'){event.preventDefault();openDelete('session',el.dataset.id,el.dataset.history==='true');}
      else if(a==='cancelDelete')cancelDelete();else if(a==='confirmDelete')confirmDelete();
      else if(a==='new'&&!busy()){closeDialog();fresh(Q.current.book_codes,Q.current.clc_code||'');save();draw();focusInput();if(typeof toast==='function')toast(Q.storageError?'已开始新话题，但浏览器未能保存历史。':'已开始新话题，之前的对话可在历史中查看。');}
      else if(a==='example'&&!busy()){Q.draft=el.dataset.question||'';const input=host.querySelector('#qaQuestion');if(input){input.value=Q.draft;resizeInput();host.querySelector('.qa-send').disabled=!canAsk();input.scrollIntoView({block:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});}focusInput(el.dataset.selection);}
      else if(a==='loadSession'&&!busy()){const s=Q.sessions.find(x=>x.id===el.dataset.id);if(s){closeDialog();Q.current=s;Q.draft=pendingQuestion(s);Q.selectedTurn='';Q.selectedSource=null;Q.expandedTurns=[];save();draw();focusInput();}}
      else if(a==='cite')selectSource(el.dataset.turn,el.dataset.source);else if(a==='sources')selectSource(el.dataset.turn,null,true);else if(a==='context')openContext(el.dataset.turn,el.dataset.source);else if(a==='copy')copyAnswer(el.dataset.turn);
      else if(a==='editQuestion'&&!busy()){const t=Q.current.turns.find(x=>x.id===el.dataset.turn);if(t){Q.draft=t.question;draw();focusInput();}}
      else if(a==='retry'&&!busy()){const t=Q.current.turns.find(x=>x.id===el.dataset.turn);if(t)ask(t.question,t.id);}
    });
  }
  async function render(v,arg){
    Q.renderId++;restore();if(!Q.current)fresh();
    if(typeof crumb==='function')crumb('<a href="#/apps">内容应用</a><span>/</span><b>智能问答</b>');
    v.classList.add('studio-view','qa-view');v.innerHTML='<section class="qa-app" aria-label="智能问答"></section>';Q.host=v.firstElementChild;events(Q.host);draw();
    if(arg&&!Q.current.turns.length){Q.draft=String(arg).slice(0,1200);draw();}
    await refresh();
  }
  return {render};
})();
