/* Publishing workspaces. Every action writes real, revisioned application data. */
'use strict';
window.Studio = (function () {
  const S = {filters:{q:'',kind:'',code:'',status:'',offset:0}, project:null, dirty:false, asset:null, view:'', request:0, picker:null, pickerBusy:null, assetItems:[]};
  const ProjectUI={materials:{},notes:{},detail:null,outlineTimer:null,draftMode:'read',draftScene:null,outlineOpen:null,assistOpen:null};
  const ExportCopies=new Map();
  const ReviewDrafts=new Map();
  const SECTIONS=['task','materials','results','review','sources','history'];
  const MATERIAL_PAGE_SIZE=12;
  const Switcher = {query:'',offset:0,limit:10,total:0,request:0,timer:null,kind:'',projectId:'',busy:false};
  const K = {overview:'图书概览',summary:'章节摘要',quote:'原文摘录',theme:'主题与观点',fact:'事实与案例',marketing:'营销线索'};
  const STAT = {review:'待核对',approved:'已确认',rejected:'已停用',draft:'草稿',active:'进行中',delivered:'已交付',used:'已使用',paused:'已暂缓',selected:'待选择',adopted:'项目采用',not_fit:'本项目不采用'};
  const e = esc;
  function attrs(data){return Object.entries(data||{}).map(function(x){return ' data-'+x[0]+'="'+e(x[1])+'"';}).join('');}
  function btn(label, fn, data, css){return '<button type="button" class="btn '+(css||'')+'"'+attrs(data)+' onclick="Studio.'+fn+'(this)">'+label+'</button>';}
  function badge(status){return '<span class="studio-badge '+e(status)+'">'+e(STAT[status]||status||'待核对')+'</span>';}
  function empty(title,sub,action){return '<div class="studio-empty"><span class="empty-symbol">＋</span><h3>'+e(title)+'</h3><p>'+e(sub||'')+'</p>'+(action||'')+'</div>';}
  function field(label,name,value,type,placeholder,descriptionId){
    const description=descriptionId?' aria-describedby="'+e(descriptionId)+'"':'';
    return '<label class="studio-field"><span>'+e(label)+'</span>'+(type==='textarea'?'<textarea name="'+name+'" rows="4" placeholder="'+e(placeholder||'')+'"'+description+'>'+e(value||'')+'</textarea>':'<input name="'+name+'" value="'+e(value||'')+'" placeholder="'+e(placeholder||'')+'"'+description+'>')+'</label>';
  }
  const MARKETING_TASKS={
    reposition:{label:'老书新卖点',hint:'从原书找出适合本次读者的新传播角度，保留内容依据与待验证判断。'},
    theme:{label:'跨书主题营销',hint:'围绕同一个问题组合多本书，说明每本书的独特贡献和共同传播安排。'},
    channel:{label:'渠道素材包',hint:'为选定渠道准备可编辑的文案与讲书材料，按渠道调整表达并保留出处。'},
    general:{label:'通用营销 / 新书上市',hint:'推广现有图书，或用已确认的新书资料与历史材料准备上市传播。'}
  };
  const MARKETING_CHANNELS=['公众号','小红书','短视频','达人讲书','书店活动'];
  function marketingTask(value){return Object.hasOwn(MARKETING_TASKS,value)?value:'general';}
  function sourceSelect(code){
    const known=(state.books||[]).some(b=>b.code===code);
    return '<label class="studio-field"><span>推广图书</span><select name="source_code" onchange="Studio.marketingTaskChange(this)"><option value="">待出版新书</option>'+(!known&&code?'<option value="'+e(code)+'" selected>原推广图书（已不在当前书库）</option>':'')+(state.books||[]).map(function(b){return '<option value="'+e(b.code)+'"'+(b.code===code?' selected':'')+'>'+e(b.book)+'</option>';}).join('')+'</select></label>';
  }
  function marketingFields(brief){
    const b=brief||{},task=marketingTask(b.marketing_task),targets=Array.isArray(b.target_codes)?b.target_codes:[],channels=Array.isArray(b.channels)?b.channels:[];
    const books=(state.books||[]).map(b=>({code:b.code,title:b.book}));
    targets.filter(code=>!books.some(b=>b.code===code)).forEach(code=>books.push({code,title:'原选定图书（已不在当前书库）'}));
    return '<label class="studio-field marketing-task-field" data-marketing-plan><span>策划重点</span><select name="marketing_task" onchange="Studio.marketingTaskChange(this)">'+Object.entries(MARKETING_TASKS).map(([key,item])=>'<option value="'+key+'"'+(key===task?' selected':'')+'>'+e(key==='channel'?'制作场景内容':item.label)+'</option>').join('')+'</select><small data-marketing-hint>'+e(MARKETING_TASKS[task].hint)+'</small></label>'+
      '<fieldset class="marketing-task-group marketing-choice-group marketing-scenes-field" data-marketing-group="channels"><legend>使用场景</legend><p>选择需要制作的内容，每个场景分别展示。找卖点和选材料在项目内完成。</p><div class="marketing-choice-list">'+Object.entries(MarketingScenes.scenes).map(([channel,item])=>'<label><input type="checkbox" name="channels" value="'+e(channel)+'"'+(channels.includes(channel)?' checked':'')+'><span>'+e(item.title)+'<small>'+e(item.output)+'</small></span></label>').join('')+'</div></fieldset>'+
      '<div class="marketing-task-group" data-marketing-group="single">'+sourceSelect(b.source_code)+'</div>'+
      '<fieldset class="marketing-task-group marketing-choice-group" data-marketing-group="multiple"><legend>推广图书</legend><p data-marketing-target-hint>选择本次要推广的图书。</p><div class="marketing-choice-list">'+books.map(book=>'<label><input type="checkbox" name="target_codes" value="'+e(book.code)+'"'+(targets.includes(book.code)?' checked':'')+'><span>'+e(book.title)+'</span></label>').join('')+'</div>'+(!books.length?'<p>当前书库没有图书，可先保存任务，再导入图书。</p>':'')+'</fieldset>'+
      '<div class="marketing-task-group" data-marketing-group="channel-text">'+field('使用渠道','channel',b.channel,'input','例如：公众号、短视频、书店活动')+'</div>'+
      '<div class="marketing-task-group marketing-new-book" data-marketing-group="new-book">'+field('新书确认资料','new_book_brief',b.new_book_brief,'textarea','待出版新书请填写已确认的内容、定位和差异点；旧书材料作为背景参考。')+'</div>';
  }
  function syncMarketingFields(form){
    if(!form)return;const selector=form.querySelector('[name=marketing_task]');if(!selector)return;
    const task=marketingTask(selector.value),single=task==='general'||task==='reposition',source=form.querySelector('[name=source_code]');
    const plan=form.querySelector('[data-marketing-plan]');if(plan)plan.hidden=task==='channel';
    if(source&&source.options.length)source.options[0].textContent=task==='reposition'?'请选择推广图书':'待出版新书';
    const show={single,multiple:task==='theme'||task==='channel','channel-text':task!=='channel',channels:task==='channel','new-book':task==='general'};
    form.querySelectorAll('[data-marketing-group]').forEach(group=>{const visible=!!show[group.dataset.marketingGroup];group.hidden=!visible;group.querySelectorAll('input,select,textarea').forEach(control=>{control.disabled=!visible;});});
    const hint=form.querySelector('[data-marketing-hint]');if(hint)hint.textContent=MARKETING_TASKS[task].hint;
    const targetHint=form.querySelector('[data-marketing-target-hint]');if(targetHint)targetHint.textContent=task==='theme'?'选择至少两本图书，围绕主题说明各书的作用。':'选择一本或多本要制作渠道素材的图书。';
  }
  function marketingTaskChange(el){
    const form=el.closest('form');syncMarketingFields(form);if(form?.id==='projectBrief')markDirty();
  }
  function projectFormFields(form){
    const data=new FormData(form),fields=Object.fromEntries(data);
    if(form.querySelector('[name=marketing_task]')){
      const task=marketingTask(fields.marketing_task);fields.marketing_task=task;
      fields.target_codes=task==='theme'||task==='channel'?[...new Set(data.getAll('target_codes').map(String))]:[];
      fields.channels=task==='channel'?[...new Set(data.getAll('channels').map(String))]:[];
      fields.source_code=task==='general'||task==='reposition'?String(data.get('source_code')||''):'';
      fields.new_book_brief=task==='general'?String(data.get('new_book_brief')||''):'';
      fields.channel=task==='channel'?fields.channels.join('、'):String(data.get('channel')||'');
    }
    return fields;
  }
  function comparableBrief(brief,marketing){
    if(!marketing)return brief||{};
    const b=Object.assign({},brief||{}),task=marketingTask(b.marketing_task);b.marketing_task=task;
    b.target_codes=task==='theme'||task==='channel'?(Array.isArray(b.target_codes)?b.target_codes.slice().sort():[]):[];
    b.channels=task==='channel'?(Array.isArray(b.channels)?b.channels.slice().sort():[]):[];
    b.source_code=task==='general'||task==='reposition'?String(b.source_code||''):'';
    b.new_book_brief=task==='general'?String(b.new_book_brief||''):'';
    b.channel=task==='channel'?b.channels.join('、'):String(b.channel||'');b.writing_notes=String(b.writing_notes||'');const roles=MarketingPurpose.values(b);for(const key of Object.keys(roles))delete b[key];Object.assign(b,roles);
    return b;
  }
  function nav(el){go(el.dataset.view,el.dataset.id||'');}
  async function request(url,body){return body===undefined?jget(url):post(url,body);}
  function report(err){toast(readableDraftMarkers(err.message||String(err),S.project),true);}
  function name(p){return p.kind==='marketing'?'营销策划':'选题策划';}
  function pageHead(eyebrow,title,sub,actions){return '<div class="page-head"><div>'+(eyebrow?'<div class="eyebrow">'+eyebrow+'</div>':'')+'<h1>'+e(title)+'</h1><p>'+e(sub)+'</p></div><div class="head-actions">'+(actions||'')+'</div></div>';}
  function projectCard(p){return '<article class="project-card studio-card"><div class="studio-section-head"><span class="asset-type">'+name(p)+'</span>'+badge(p.status)+'</div><h3>'+e(p.title)+'</h3><p>'+e((p.brief||{}).goal||(p.brief||{}).topic||'补充工作目标，开始收集有依据的材料。')+'</p><div class="project-card-meta"><span>'+e((p.brief||{}).audience||'读者待明确')+'</span><span>'+num((p.items||[]).length||p.item_count||0)+' 条材料</span></div><div class="card-actions">'+btn('继续项目 →','nav',{view:p.kind==='marketing'?'campaigns':'projects',id:p.id},'ghost')+'<span class="faint">'+e(ago(p.updated_at))+'</span></div></article>';}
  function assetAction(a){
    if(!S.picker)return btn('＋ 加入项目','chooseProject',{id:a.id},'sm');
    const exists=(S.picker.items||[]).some(function(i){return i.asset_id===a.id;}),busy=S.pickerBusy&&S.pickerBusy.pid===S.picker.id,disabled=exists||busy||a.status==='rejected';
    return '<button type="button" class="btn sm"'+attrs({id:a.id})+' onclick="Studio.addToCurrent(this)"'+(disabled?' disabled':'')+'>'+(exists?'已加入本项目':a.status==='rejected'?'已停用':'＋ 加入本项目')+'</button>';
  }
  function assetCard(a){const evidence=(a.evidence||[])[0]||{};return '<article class="asset-card studio-card"><div class="studio-section-head"><span class="asset-type '+e(a.kind)+'">'+e(K[a.kind]||a.kind)+'</span>'+badge(a.status)+'</div><h3>'+e(a.title||K[a.kind]||'内容成果')+'</h3><p class="asset-preview">'+e(a.text||'')+'</p><div class="asset-evidence"><span>↗</span><span>'+e(a.book||a.code)+'<small>'+e(evidence.anchor||'图书级内容')+'</small></span></div><div class="card-actions">'+btn('查看与核对','detail',{id:a.id},'sm ghost')+assetAction(a)+'</div></article>';}
  async function render(v,view,arg,section,options={}){
    if(S.dirty&&S.project){try{await beforeNavigate();}catch(err){report(err);return;}}
    if(['campaigns','projects'].includes(view)&&S.project?.id===arg&&v.querySelector('.project-section-panel')&&(options.preserve||initialProjectSection(S.project,section)!==S.section)){
      S.view=view;v.classList.add('studio-view','project-workspace');if(S.project.kind==='marketing')v.classList.add('marketing-workspace');showProjectSection(initialProjectSection(S.project,section));return;
    }
    S.view=view;if(view!=='content')S.picker=null;const rid=++S.request;v.classList.add('studio-view');
    if(view==='campaigns'&&(!arg||arg==='new')){S.project=null;S.dirty=false;return MarketingEntry.render(v,arg==='new'?'new':'home',section);}
    v.innerHTML=loading('加载工作空间');
    try{
      if(view==='dashboard')await dashboard(v,rid);
      else if(view==='content')await content(v,arg,rid);
      else await projects(v,view==='campaigns'?'marketing':'editorial',arg,rid,section);
    }catch(err){if(rid===S.request)v.innerHTML=empty('暂时无法加载',err.message,btn('重新加载','reload',{},'primary'));}
  }
  function dashboardProjectRow(p){
    const brief=p.brief||{},route=p.kind==='marketing'?'campaigns':'projects';
    const materialCount=Array.isArray(p.items)?p.items.length:(p.item_count||0);
    return '<article class="dash-project-row"><div class="dash-project-main"><div class="dash-project-top"><span class="asset-type">'+name(p)+'</span>'+badge(p.status)+'</div><h3>'+e(p.title||'未命名项目')+'</h3><p class="dash-project-summary">'+e(brief.goal||brief.topic||'补充工作目标，开始收集有依据的材料。')+'</p><div class="dash-project-meta"><span>'+e(brief.audience||'读者待明确')+'</span><span>'+num(materialCount)+' 条材料</span><span>更新于 '+e(ago(p.updated_at))+'</span></div></div><div class="dash-project-actions">'+btn('继续项目','nav',{view:route,id:p.id},'ghost')+'</div></article>';
  }
  async function dashboard(v,rid){
    crumb('<span>工作台</span>');
    const responses=await Promise.all([request('/api/workspace/overview'),request('/api/review-queue').catch(function(){return null;})]);
    if(rid!==S.request)return;const d=responses[0],review=responses[1];
    const q=d.quality||{};
    const recent=Array.isArray(d.recent_projects)?d.recent_projects:[];
    const reviewKnown=!!review&&Number.isFinite(review.total)&&review.total>=0;
    const reviewState=reviewKnown?(review.total?'pending':'clear'):'unavailable';
    const firstReview=reviewKnown&&Array.isArray(review.items)?review.items[0]:null;
    const reviewText=!reviewKnown?'暂时无法获取核对待办，请重新读取。':review.total?num(review.total)+' 条素材待处理 · 涉及 '+num(review.project_count)+' 个项目':'当前工作空间暂无待核对素材。';
    const qualityKnown=['running','partial','failed'].every(function(key){return Number.isFinite(q[key])&&q[key]>=0;});
    const runtimeState=!qualityKnown?'unavailable':q.failed||q.partial?'attention':q.running?'running':'clear';
    const runtimeTitle=!qualityKnown?'暂时无法获取运行状态':q.failed||q.partial?'有任务需要关注':q.running?'任务正在处理':'近期任务无需处理';
    v.innerHTML='<div class="dash-workspace"><header class="dash-head"><div><div class="eyebrow">工作空间</div><h1>继续你的内容工作</h1><p>从最近的项目继续，优先处理需要核对的材料。</p></div><div class="head-actions">'+btn('＋ 创建选题策划','create',{kind:'editorial'},'primary')+btn('＋ 创建营销策划','create',{kind:'marketing'},'ghost')+'</div></header>'+
      '<section class="dash-metrics" aria-label="工作空间概览">'+[
        ['已入库图书',d.books,'library'],
        ['内容成果','查找','content'],
        ['工作项目',d.projects,'records']
      ].map(function(x){return '<button type="button" class="dash-metric"'+attrs({view:x[2]})+' onclick="Studio.nav(this)"><strong class="dash-metric-value">'+(typeof x[1]==='string'?e(x[1]):num(x[1]))+'</strong><span class="dash-metric-label">'+x[0]+'</span></button>';}).join('')+'</section>'+
      '<div class="dash-layout"><section class="dash-projects" aria-labelledby="dashProjectsTitle"><div class="dash-section-head"><div><h2 id="dashProjectsTitle">最近的项目</h2><p class="dash-panel-note">按最近更新排列</p></div>'+btn('全部项目','nav',{view:'records'},'sm ghost')+'</div><div class="dash-project-list">'+(recent.length?recent.map(dashboardProjectRow).join(''):'<div class="dash-empty"><h3>还没有工作项目</h3><p>从上方创建选题策划或营销策划，把材料与判断留在同一个项目里。</p></div>')+'</div></section>'+
      '<aside class="dash-sidebar" aria-label="待办与内容概览"><section class="dash-panel dash-review" data-state="'+reviewState+'" aria-labelledby="dashReviewTitle"><div class="dash-section-head"><h2 id="dashReviewTitle">素材核对待办</h2></div><p class="dash-review-summary" role="status">'+reviewText+'</p>'+(firstReview?'<p class="dash-review-item">'+e(firstReview.title||'待核对素材')+'</p>':'')+(!reviewKnown?btn('重新读取','reload',{},'sm ghost'):review.total?btn('查看待办','nav',{view:'editor'},'primary'):btn('查看核对工作台','nav',{view:'editor'},'sm ghost'))+'</section>'+
      '<section class="dash-panel dash-runtime" data-state="'+runtimeState+'" aria-labelledby="dashRuntimeTitle"><div class="dash-section-head"><h2 id="dashRuntimeTitle">运行任务</h2><span class="studio-badge '+(runtimeState==='attention'?'review':runtimeState==='clear'?'approved':'draft')+'">'+runtimeTitle+'</span></div>'+(qualityKnown?'<div class="dash-runtime-counts"><span><b>'+num(q.running)+'</b> 处理中</span><span data-tone="'+(q.partial?'warning':'neutral')+'"><b>'+num(q.partial)+'</b> 部分完成</span><span data-tone="'+(q.failed?'danger':'neutral')+'"><b>'+num(q.failed)+'</b> 失败</span></div><p class="dash-panel-note">统计最近 30 条运行任务</p>':'<p class="dash-panel-note">重新读取后查看最新处理状态。</p>')+btn('查看运行任务','nav',{view:'tasks'},'sm ghost')+'</section>'+
      '<section class="dash-panel dash-assets" aria-labelledby="dashAssetsTitle"><div class="dash-section-head"><h2 id="dashAssetsTitle">按类型找成果</h2></div><div class="dash-asset-list">'+Object.entries(K).map(function(x){return '<button type="button" class="dash-asset-row"'+attrs({kind:x[0]})+' onclick="Studio.filterKind(this)"><span>'+x[1]+'</span><span aria-hidden="true">›</span></button>';}).join('')+'</div></section></aside></div></div>';
  }
  function filterKind(el){
    const {code,kind}=el.dataset;
    contentRoute({q:'',kind:kind||'',code:code||'',status:'',offset:0},null);
  }
  async function content(v,arg,rid){
    crumb('<span>内容成果</span>');
    const target=String(arg||''), queryAt=target.indexOf('?');
    const scope=queryAt<0?target:target.slice(0,queryAt);
    const filters=new URLSearchParams(queryAt<0?'':target.slice(queryAt+1));
    const match=/^pick:(prj-[a-f0-9]{16})(?::([A-Za-z0-9_-]+))?$/.exec(scope);
    S.picker=null;
    if(scope.startsWith('pick:')&&!match)throw new Error('项目选材入口无效，请从工作项目重新进入');
    const books=state.books||[], code=match?match[2]||'':scope;
    const known=books.some(b=>b.code===code);
    if(match&&code&&!known)throw new Error('来源图书已变化，请从项目重新选择材料');
    const kind=filters.get('kind')||'',status=filters.get('status')||'';
    S.filters={q:(filters.get('q')||'').trim(),kind:Object.hasOwn(K,kind)?kind:'',code:known?code:'',
      status:['review','approved','rejected'].includes(status)?status:'',offset:Math.max(0,Number.parseInt(filters.get('offset'),10)||0)};
    const narrowed=Boolean(S.filters.q||S.filters.code||S.filters.kind);
    const params=new URLSearchParams({...S.filters,limit:24});
    const responses=await Promise.all([narrowed?request('/api/content-assets?'+params):{items:[],total:0},match?request('/api/projects/'+match[1]):null]);
    if(rid!==S.request)return;const d=responses[0];S.picker=responses[1]?responses[1].project:null;S.assetItems=d.items||[];
    v.innerHTML=pageHead('','内容成果','按书、关键词或成果类型查找，打开结果可核对出处、加入项目。',S.filters.code?btn('生成章节摘要','generate',{code:S.filters.code,kind:'summaries'},'ghost')+btn('生成营销资料','generate',{code:S.filters.code,kind:'marketing'},'ghost'):'')+
      (S.picker?'<section id="contentProjectContext" class="content-project-context"'+attrs({'project-id':S.picker.id,'project-kind':S.picker.kind,'project-title':S.picker.title})+'>'+pickerBanner()+'</section>':'')+
      '<form class="studio-toolbar" id="assetFilters" onsubmit="event.preventDefault();Studio.filter(this)"><input name="q" aria-label="搜索内容成果" placeholder="搜索观点、摘要、案例或原文…" value="'+e(S.filters.q)+'"><select name="code" aria-label="图书"><option value="">选择图书</option>'+books.map(function(b){return '<option value="'+e(b.code)+'"'+(b.code===S.filters.code?' selected':'')+'>'+e(b.book)+'</option>';}).join('')+'</select><select name="kind" aria-label="成果类型"><option value="">全部成果类型</option>'+Object.entries(K).map(function(x){return '<option value="'+x[0]+'"'+(x[0]===S.filters.kind?' selected':'')+'>'+x[1]+'</option>';}).join('')+'</select>'+(narrowed?'<select name="status" aria-label="审核状态"><option value="">全部审核状态</option>'+['review','approved','rejected'].map(function(x){return '<option value="'+x+'"'+(x===S.filters.status?' selected':'')+'>'+STAT[x]+'</option>';}).join('')+'</select>':'')+'<button class="btn primary" type="submit">查找</button>'+(narrowed?btn('清除筛选','resetFilters',{},'ghost'):'')+'</form>'+
      (narrowed?'<div class="studio-section-head"><span class="muted" role="status">找到 '+num(d.total)+' 条成果</span></div><div class="asset-grid" id="contentAssetGrid">'+(S.assetItems.map(assetCard).join('')||empty('没有找到对应成果','可以换个关键词或调整筛选条件。'))+'</div>'+
        (d.total>24?'<div class="studio-pagination">'+(S.filters.offset?btn('上一页','paginate',{delta:-24},'ghost'):'')+'<span>第 '+Math.floor(S.filters.offset/24+1)+' 页</span>'+(S.filters.offset+24<d.total?btn('下一页','paginate',{delta:24,total:d.total},'ghost'):'')+'</div>':''):'')+
      '<div class="content-tools" aria-label="相关工具">'+(!S.picker?'<button type="button" class="btn sm ghost" onclick="ReviewHub.openBookTools()">单书资料整理</button>':'')+btn('关系探索','nav',{view:'relations'},'sm ghost')+btn('图书营销资料','nav',{view:'marketing',id:S.filters.code||''},'sm ghost')+'</div>';
    v.querySelectorAll('#assetFilters select').forEach(function(x){x.onchange=function(){filter(document.getElementById('assetFilters'));};});
  }
  function pickerBanner(){const p=S.picker;if(!p)return '';return '<div><span class="eyebrow">为当前策划选材</span><h2>'+e(p.title)+'</h2><p>已收集 <b>'+num((p.items||[]).length)+'</b> 条材料。点击成果可直接加入本项目，再回项目决定采用与核对。</p></div>'+btn('返回项目继续 →','returnToProject',{},'primary');}
  function pickerActive(pid){return S.picker&&S.picker.id===pid&&document.getElementById('contentProjectContext')&&parse().view==='content';}
  function paintPicker(){const banner=document.getElementById('contentProjectContext'),grid=document.getElementById('contentAssetGrid');if(!banner||!S.picker)return;banner.innerHTML=pickerBanner();if(grid&&S.assetItems.length)grid.innerHTML=S.assetItems.map(assetCard).join('');}
  function returnToProject(){if(S.picker)go(S.picker.kind==='marketing'?'campaigns':'projects',S.picker.id,'materials');}
  function contentRoute(filters=S.filters,picker=S.picker){
    const scope=picker?'pick:'+picker.id+(filters.code?':'+filters.code:''):filters.code;
    const params=new URLSearchParams();
    for(const key of ['q','kind','status','offset'])if(filters[key])params.set(key,filters[key]);
    const query=params.toString(),arg=scope+(query?'?'+query:'');
    const current=parse();
    if(current.view==='content'&&current.arg===arg)route();else go('content',arg);
  }
  async function addToCurrent(el){
    const p=S.picker;if(!p||!pickerActive(p.id)||(S.pickerBusy&&S.pickerBusy.pid===p.id))return;
    const aid=el.dataset.id,lock={pid:p.id},modal=document.querySelector('#modalRoot .modal');S.pickerBusy=lock;paintPicker();
    try{
      const latest=(await request('/api/projects/'+p.id)).project;if(!pickerActive(p.id))return;
      if((latest.items||[]).some(function(i){return i.asset_id===aid;})){S.picker=latest;toast('该材料已在项目中');return;}
      const d=await request('/api/projects/'+p.id,{action:'add_asset',revision:latest.revision,asset_id:aid});
      if(!pickerActive(p.id))return;S.picker=d.project;if(modal&&document.querySelector('#modalRoot .modal')===modal)closeModal();toast('已加入本项目，回项目后可决定采用与核对');
    }catch(err){if(pickerActive(p.id))report(err);}
    finally{if(S.pickerBusy===lock)S.pickerBusy=null;if(pickerActive(p.id))paintPicker();}
  }
  function filter(form){
    const data=new FormData(form),filters={offset:0};
    for(const key of ['q','kind','code','status'])filters[key]=String(data.get(key)||'').trim();
    if(!filters.q&&!filters.code&&!filters.kind){
      if(!S.filters.q&&!S.filters.code&&!S.filters.kind){form.elements.namedItem('q').focus();return;}
      filters.status='';
    }
    contentRoute(filters);
  }
  function resetFilters(){S.filters={q:'',kind:'',code:'',status:'',offset:0};contentRoute();}
  function paginate(el){const n=S.filters.offset+Number(el.dataset.delta);if(n<0||(el.dataset.total&&n>=Number(el.dataset.total)))return;S.filters.offset=n;contentRoute();}
  async function detail(el,historyOptions={}){
    const token=S.detailRequest=(S.detailRequest||0)+1,origin=location.hash,modal=document.querySelector('#modalRoot .modal');
    const projectPreview=el.dataset.preview==='true'&&S.project?.kind==='marketing'&&el.dataset.material;
    const isCurrent=()=>token===S.detailRequest&&location.hash===origin&&document.querySelector('#modalRoot .modal')===modal&&
      (!projectPreview||historyOptions.restore||ProjectUI.detail?.id===el.dataset.material)&&
      (!historyOptions.isCurrent||historyOptions.isCurrent());
    try{const result=await request('/api/content-assets/detail?'+new URLSearchParams({id:el.dataset.id}));if(!isCurrent())return;S.asset=result.asset;const a=S.asset;
      const shared=el.dataset.queue==='true';
      const preview=shared&&el.dataset.preview==='true';
      const title=preview?'新版图书简介':shared&&a.kind==='marketing'&&a.marketing_key==='summary'?'图书简介':a.title;
      const scope=preview?'':shared?'对照原文确认素材。引用同一版本的项目可沿用确认结果。':
        (el.dataset.purpose?'准备用于「'+e(el.dataset.purpose)+'」。':'')+'对照原文，看看这条内容是否准确。';
      const evidence=(a.evidence||[]).map(ev=>{
        const anchor=ev.anchor||ev.seg||'',quote=ev.quote||'';
        const link=anchor?btn('查看原文','source',{code:a.code,anchor,quote},'sm ghost')
          .replace('<button ','<button aria-controls="assetReviewSource" aria-pressed="false" '):'';
        return '<blockquote>'+e(quote)+'<footer>'+link+'</footer></blockquote>';
      }).join('');
      const approvalBlocked=a.stale||a.needs_structure_review||a.evidence_valid===false;
      const approval=btn('核对并确认','review',{status:'approved'},'primary');
      openModal(()=>{
        const draft=ReviewDrafts.get(a.id);
        const restored=draft?.revision===a.revision?draft:null;
        return modalX(!!projectPreview)+'<div class="asset-review-frame"><section class="asset-review-main">'+(preview?'':'<p class="eyebrow">'+e(K[a.kind]||'内容成果')+'</p>')+'<h2>'+e(title)+'</h2>'+(scope?'<p class="review-scope">'+scope+'</p>':'')+
          '<div class="studio-section-head"><span>'+e(a.book||a.code)+'</span>'+badge(a.status)+'</div>'+(a.quality_note?'<div class="banner">'+e(a.quality_note)+'</div>':'')+
          (shared?'':'<p class="studio-note">内容来源 '+e(a.origin||'初步整理')+(a.coverage_note?' · '+e(a.coverage_note):'')+'</p>')+
          '<div class="asset-detail-text">'+e(a.text).replace(/\n/g,'<br>')+'</div><div class="asset-detail-evidence"><h3>原文依据</h3>'+(evidence||'<p class="muted">这条内容暂时没有可回查的出处。</p>')+'</div>'+
          (preview?'':'<details class="studio-revision"'+(restored?' open':'')+'><summary>修订内容或反馈问题</summary><p class="studio-note">'+(restored?'已恢复这次打开网页后留下的修订。':'保存修订后，引用这条内容的项目会收到更新提示。')+'</p><form id="assetReviewForm" oninput="Studio.rememberReview(this)">'+field('修订后的内容','text',restored?.text??a.text,'textarea')+field('修改或停用原因','reason',restored?.reason||'','input','说明哪里有误，或修改的依据')+'</form></details>'+
          (approvalBlocked?'<p class="studio-note">先核对或修复原文，再确认这条内容。</p>':'')+
          '<div class="modal-actions">'+btn('停用错误内容','review',{status:'rejected'},'ghost')+btn('保存修订待核对','review',{status:'review'},'ghost')+(approvalBlocked?approval.replace('<button ','<button disabled '):approval)+(shared?'':btn('加入项目','chooseProject',{id:a.id},''))+'</div>')+'</section>'+
          '<aside class="asset-review-source" id="assetReviewSource" aria-labelledby="assetReviewSourceTitle" hidden><header><h3 id="assetReviewSourceTitle" tabindex="-1">原文与上下文</h3>'+btn('收起原文','closeReviewSource',{},'sm ghost')+'</header><div class="asset-review-source-body" aria-live="polite"></div></aside></div>';
      },true,projectPreview?{...historyOptions,step:true,closeStep:true,
        descriptor:{type:'project-summary-preview',projectId:S.project.id,assetId:el.dataset.material,section:S.section}}:undefined);
    }catch(err){if(isCurrent())report(err);}
  }
  function rememberReview(form){
    const a=S.asset, data=new FormData(form), text=String(data.get('text')||''), reason=String(data.get('reason')||'');
    if(!a)return;
    if(text===a.text&&!reason)ReviewDrafts.delete(a.id);
    else ReviewDrafts.set(a.id,{revision:a.revision,text,reason});
  }
  async function review(el){
    if(!S.asset||S.reviewBusy)return;const a=S.asset,form=document.getElementById('assetReviewForm'),d=form?new FormData(form):null;
    const text=d?String(d.get('text')||''):a.text,reason=d?String(d.get('reason')||''):'';
    if(el.dataset.status==='rejected'&&!reason.trim()){toast('请展开修订区，填写内容有误的原因。项目不适用请在项目中标记。',true);return;}
    const controls=form?Array.from(form.elements):[];
    S.reviewBusy=true;el.disabled=true;controls.forEach(x=>{x.disabled=true;});
    try{
      const body={id:a.id,revision:a.revision,status:el.dataset.status,reason};
      if(text!==a.text)body.text=text;
      await request('/api/content-assets/review',body);
      ReviewDrafts.delete(a.id);
      if(window.ReviewHub&&ReviewHub.noteReviewed)ReviewHub.noteReviewed(a.id,el.dataset.status);
      toast(el.dataset.status==='approved'?(text!==a.text?'修订已确认，引用旧内容的项目需要更新材料。':'材料已确认，同一版本可以沿用这次结果。'):el.dataset.status==='rejected'?'内容已停用，相关项目需更换材料。':'修订已保存，等待核对。');
      if(el.isConnected){closeModal();route();}
    }catch(err){report(err);}finally{S.reviewBusy=false;el.disabled=false;controls.forEach(x=>{x.disabled=false;});}
  }
  function sourceQuoteRange(text,quote){
    const needle=quote.replace(/\s+/g,'');
    if(!needle)return null;
    const exact=text.indexOf(quote);
    if(exact>=0)return [exact,exact+quote.length];
    // Match the source validation rule while preserving punctuation and original spacing.
    const chars=Array.from(text.matchAll(/\S/g));
    const start=chars.map(match=>match[0]).join('').indexOf(needle);
    return start<0?null:[chars[start].index,chars[start+needle.length-1].index+1];
  }
  function sourcePassage(item,quote){
    const text=String(item['文本']||''),range=item.hit&&sourceQuoteRange(text,quote);
    const content=range?e(text.slice(0,range[0]))+'<mark tabindex="-1">'+e(text.slice(...range))+'</mark>'+e(text.slice(range[1])):e(text);
    const label=item.hit?'<strong>'+(quote.trim()&&!range?'仅定位到段落，未找到这条引文':'出处段落')+'</strong>':'';
    return '<div class="asset-review-source-passage'+(item.hit?' is-evidence':'')+'">'+label+'<p>'+content+'</p></div>';
  }
  async function source(el){
    const panel=document.getElementById('assetReviewSource');
    const {code,anchor,quote=''}=el.dataset;
    if(!panel||!code||!anchor)return;
    const body=panel.querySelector('.asset-review-source-body'),heading=panel.querySelector('h3');
    const token=S.reviewSourceRequest=(S.reviewSourceRequest||0)+1;
    if(el.closest('.asset-detail-evidence')){
      S.reviewSourceButton?.setAttribute('aria-pressed','false');
      S.reviewSourceButton=el;
      el.setAttribute('aria-pressed','true');
    }
    panel.hidden=false;
    heading.focus({preventScroll:true});
    const compact=window.matchMedia('(max-width:720px)').matches;
    if(compact)panel.scrollIntoView({block:'nearest'});
    body.innerHTML=loading('正在查找出处');
    const isCurrent=()=>panel.isConnected&&!panel.hidden&&token===S.reviewSourceRequest;
    try{
      const d=await request('/api/book/segment?'+new URLSearchParams({code,anchor,radius:'1'}));
      if(!isCurrent())return;
      const page=Number(d.source_page),pageLabel=page>0?'PDF 第 '+page+' 页':'';
      const location=[pageLabel,d['篇'],d['段']?'第 '+d['段']+' 段':''].filter(Boolean).join(' · ');
      const pdf=d.has_original_pdf&&page>0?'<a class="btn sm ghost" target="_blank" rel="noopener" href="/api/book/source?'+new URLSearchParams({code})+'#page='+page+'">打开原版 PDF</a>':'';
      const bookLink='<a class="btn sm ghost" target="_blank" rel="noopener" href="#/book/'+encodeURIComponent(code)+'/text/'+encodeURIComponent(d.seg_id||anchor)+'">打开图书原文</a>';
      body.innerHTML='<p class="muted">'+e(location)+'</p><div class="asset-review-source-links">'+pdf+bookLink+'</div>'+
        (d.items||[]).map(item=>sourcePassage(item,quote)).join('');
      const mark=body.querySelector('.is-evidence mark');
      const target=mark||body.querySelector('.is-evidence');
      if(target){
        const bounds=target.getBoundingClientRect();
        body.scrollTop+=bounds.top-body.getBoundingClientRect().top-Math.max(0,(body.clientHeight-bounds.height)/2);
      }
      if(compact)panel.scrollIntoView({block:'center'});
      if(mark&&document.activeElement===heading)mark.focus({preventScroll:true});
    }catch(err){
      if(!isCurrent())return;
      body.innerHTML='<p>暂时找不到这段原文。可重试，或到图书档案核对来源。</p>'+btn('重试','source',{code,anchor,quote},'sm ghost');
      if(compact)panel.scrollIntoView({block:'center'});
    }
  }
  function closeReviewSource(){
    const panel=document.getElementById('assetReviewSource');
    if(!panel)return;
    panel.hidden=true;
    S.reviewSourceRequest=(S.reviewSourceRequest||0)+1;
    S.reviewSourceButton?.setAttribute('aria-pressed','false');
    S.reviewSourceButton?.focus();
    S.reviewSourceButton=null;
  }
  async function chooseProject(el){
    if(S.picker&&pickerActive(S.picker.id))return addToCurrent(el);
    try{const id=el.dataset.id;const d=await request('/api/projects');const ps=(d.projects||[]).filter(function(p){return p.status!=='paused';});
      openModal(modalX()+'<h2>加入工作项目</h2><p class="muted">保存这条成果的当前版本，之后可以补充采用理由。</p>'+(ps.length?'<form id="pickProject"><label class="studio-field"><span>选择项目</span><select name="project">'+ps.map(function(p){return '<option value="'+e(p.id)+'">'+e(name(p)+' · '+p.title)+'</option>';}).join('')+'</select></label>'+field('收集理由（选填）','note','','textarea','这条材料对本次任务有什么帮助？')+'</form><div class="modal-actions">'+btn('保存到项目','addAsset',{id},'primary')+'</div>':empty('还没有项目','先创建一个明确的工作任务。'))+'<div class="modal-actions">'+btn('新建选题策划','create',{kind:'editorial',asset:id},'ghost')+btn('新建营销策划','create',{kind:'marketing',asset:id},'ghost')+'</div>');
    }catch(err){report(err);}
  }
  async function addAsset(el){
    const d=new FormData(document.getElementById('pickProject'));try{const p=(await request('/api/projects/'+d.get('project'))).project;await request('/api/projects/'+p.id,{action:'add_asset',revision:p.revision,asset_id:el.dataset.id,note:d.get('note')||''});closeModal();toast('材料已保存到项目');}catch(err){report(err);}
  }
  function projectFlowSteps(steps,firstIsCurrent=false){
    return '<ol role="list">'+steps.map(([label,description],index)=>
      '<li'+(firstIsCurrent&&index===0?' aria-current="step"':'')+'>'+
      '<div><span aria-hidden="true">'+(index+1)+'</span><strong>'+e(label)+'</strong></div>'+
      '<p>'+e(description)+'</p></li>'
    ).join('')+'</ol>';
  }
  function editorialCreateFooter(){
    const steps=[
      ['填写主题','只填主题就能创建项目。'],
      ['分析选题','AI 查书库，比较能写什么、缺什么。'],
      ['选方向并组稿','选一个方向生成稿件，预览后应用到工作稿。'],
      ['审核并导出','编辑核对正文和出处，审核后下载稿件。']
    ];
    return '<div class="project-create-footer">'+
      '<section class="project-create-guide" aria-labelledby="projectCreateGuideTitle"><h3 id="projectCreateGuideTitle">操作流程</h3>'+
        projectFlowSteps(steps,true)+
      '</section>'+
      '<div class="project-create-submit"><button type="submit" class="btn primary" aria-describedby="projectCreateNext">创建选题项目</button>'+
        '<p id="projectCreateNext">创建后，在「发现材料」点「分析选题」。</p>'+
      '</div></div>';
  }
  function create(el){
    const kind=el.dataset.kind||'editorial',marketing=kind==='marketing';
    if(marketing&&!el.dataset.asset){go('campaigns',el.dataset.scene||el.dataset.task?'new':'',el.dataset.scene||(el.dataset.task?'planning':''));return;}
    const title=field(marketing?'项目名称 *':'项目名称（选填）','title','','input',marketing?'例如：科学家精神主题阅读推广':'留空时使用选题主题');
    const topic=field(marketing?'主题 *':'选题主题（必填）','topic','','input',marketing?'本次关注什么问题':'例如：植物为什么长在那里？');
    const planning=marketing&&el.dataset.task&&el.dataset.task!=='channel';
    const scene=Object.hasOwn(MarketingScenes.scenes,el.dataset.scene)?el.dataset.scene:'公众号';
    const description=marketing?(planning?'先明确推广方向，再根据需要制作公众号文章、视频脚本等内容。':'先选使用场景，再确定推广图书、读者和主题。选材和提炼卖点会在制作过程中完成。'):'从已有图书找依据，比较选题方向，生成带出处的策划稿。';
    const taskFields=marketing?marketingFields({marketing_task:planning?el.dataset.task:'channel',channels:planning?[]:[scene]}):'';
    const footer=marketing?'<div class="modal-actions"><button type="submit" class="btn primary">创建并开始收集</button></div>':editorialCreateFooter();
    openModal(modalX()+(marketing?'<div class="eyebrow">MARKETING WORKSPACE</div>':'')+
      '<h2>'+(marketing?(planning?'创建整体策划':'制作营销内容'):'创建选题策划')+'</h2>'+
      '<p class="muted project-create-intro">'+description+'</p>'+
      '<form id="createProject" class="studio-form" onsubmit="event.preventDefault();Studio.submitCreate(this)"'+attrs({kind,asset:el.dataset.asset||''})+'>'+
      (marketing?taskFields+title+topic:topic+title)+
      field(marketing?'内容给谁看 *':'目标读者（选填）','audience','','input','具体到年龄、场景或需求')+
      (marketing?MarketingPurpose.fields({})+'<details class="marketing-secondary-settings"><summary>更多受众设置（选填）</summary>'+MarketingPurpose.readers({})+'</details>':'')+field(marketing?'希望谁做什么 *':'工作目标（选填）','goal','','textarea',marketing?'本次希望完成什么传播任务':'准备解决什么问题，形成什么资料')+
      footer+'</form>',true);
    if(marketing)syncMarketingFields(document.getElementById('createProject'));
  }
  async function submitCreate(form){
    const d=projectFormFields(form),marketing=form.dataset.kind==='marketing';
    if(!d.topic.trim()||(marketing&&(!d.title.trim()||!d.audience.trim()||!d.goal.trim()))){toast(marketing?'请填写项目名称、主题、内容给谁看和具体目标':'请填写选题主题',true);return;}
    if(marketing&&d.marketing_task==='channel'&&!d.channels.length){toast('请选择至少一个使用场景',true);return;}
    if(!marketing&&!d.title.trim())d.title=d.topic.trim().slice(0,160);
    const button=form.querySelector('[type=submit]');button.disabled=true;
    try{const brief=Object.assign({},d);delete brief.title;const r=await request('/api/projects',{kind:form.dataset.kind,title:d.title,brief});const p=r.project;
      if(form.dataset.asset)await request('/api/projects/'+p.id,{action:'add_asset',revision:p.revision,asset_id:form.dataset.asset});
      closeModal();toast('项目已创建');go(p.kind==='marketing'?'campaigns':'projects',p.id,'materials');
    }catch(err){report(err);button.disabled=false;}
  }
  async function projects(v,kind,id,rid,section){
    const label=kind==='marketing'?'营销策划':'选题策划';crumb('<span>'+label+'</span>');
    if(id){const d=await request('/api/projects/'+encodeURIComponent(id));if(rid!==S.request)return;S.project=d.project;S.assistProgress=null;S.section=initialProjectSection(d.project,section);ProjectUI.notes={};ProjectUI.detail=null;ProjectUI.draftMode='read';ProjectUI.draftScene=null;ProjectUI.outlineOpen=null;ProjectUI.assistOpen=null;S.dirty=false;S.draftAssetIds=null;S.draftRebuilt=false;restoreNavigation(d.project);applyRelationMaterialLanding(d.project);projectDetail(v);restoreLocalDraft();return;}
    S.project=null;const d=await request('/api/projects?kind='+kind);if(rid!==S.request)return;
    const ps=d.projects||[];v.innerHTML=pageHead(kind==='marketing'?'MARKETING WORKSPACE':'EDITORIAL WORKSPACE',label,kind==='marketing'?'从受众与场景出发，把有依据的内容变成传播素材。':'从问题出发，在多本书之间寻找材料，形成可评审的选题资料包。',btn('＋ 新建'+label,'create',{kind},'primary'))+
      '<div class="studio-workflow">'+['明确任务','收集材料','选择与编排','审核交付','记录使用'].map(function(x,i){return '<span><b>0'+(i+1)+'</b>'+x+'</span>';}).join('')+'</div>'+
      '<div class="project-grid">'+(ps.map(projectCard).join('')||empty('开始第一个'+label,'每一次材料选择、编辑判断与使用反馈，都可以成为下一次工作的积累。',btn('创建'+label,'create',{kind},'primary')))+'</div>';
  }
  function explicitDraftScope(p){return Boolean(p.draft_refs_confirmed||p.draft_generation?.topic_angle_title);}
  function sceneWorkflow(p){if(p?.kind!=='marketing')return {scoped:false};const w=MarketingScenes.workflow(p.brief);return w.scoped?w:{...w,title:MarketingScenes.label('planning')};}
  function sceneNext(p,w){
    const progress=S.assistProgress?.projectId===p.id?S.assistProgress:{},b=p.brief||{};
    const adopted=(p.items||[]).filter(i=>i.status==='adopted'&&(b.target_codes||[]).includes(i.snapshot?.code));
    let title,description,label,action,tone='pending';
    if(!['topic','audience','goal'].every(k=>String(b[k]||'').trim())){
      title='先填写'+w.title+'的要求';description='明确主题、读者和目标，系统才能按这个场景找素材。';label='填写内容要求';action='task';
    }else if(p.draft_outdated){
      title='当前稿的引用需要核对';description='处理受影响的正文和出处，再继续审核与导出。';label='核对当前稿引用';action='draft-references';
    }else if(progress.runningCapability){
      const writing=progress.runningCapability==='draft';title=writing?'正在生成'+w.draft:'正在从图书中查找素材';description=writing?'完成后先预览，应用到工作稿后再修订。':'完成后会列出可选内容及其在'+w.noun+'中的用法。';label=writing?'查看生成进度':'查看查找进度';action=writing?'draft-progress':'discover';
    }else if(progress.draftReady&&!S.dirty){
      title=w.draft+'已生成，等待你查看';description='预览内容与出处，应用到工作稿后可以继续修改。';label='查看'+w.draft;action='preview-generation';tone='ready';
    }else if(p.draft){
      title='已有'+w.title+'工作稿';description=p.draft_review&&!S.dirty?'可以导出已审核稿，实际使用后记录反馈。':'先阅读和修订正文，再核对材料出处、审核与导出。';label='查看'+w.title;action='draft';tone='ready';
    }else if(adopted.length){
      title='已选 '+adopted.length+' 条素材，可以生成'+w.draft;description='系统将按本次场景组织初稿。素材中待核对的内容会保留提示，交付前仍需检查原文。';label=w.generate;action='generate';tone='ready';
    }else{
      const found=progress.recommendStatus==='done'&&progress.recommendedCount;
      title=found?'已找到 '+progress.recommendedCount+' 条候选素材，请选出要写进'+w.noun+'的内容':'先为'+w.title+'选择素材';
      description=found?'下方每条是书中的候选内容。查看内容和建议用法，点击“'+w.select+'”；选好后生成初稿。':'在下方从图书中找素材，再选择与这次主题有关的内容。';label=found?'去选素材':'查看素材区';action='discover';
    }
    return '<section id="projectNextStep" class="project-next-step scene-next-step '+tone+'" aria-label="当前进度与下一步"><div><h2>'+e(title)+'</h2><p>'+e(description)+'</p></div>'+btn(label+' →','continueProject',{action},'primary')+'</section>';
  }
  function updateAssistProgress(projectId,progress){
    if(S.project?.id!==projectId)return;
    S.assistProgress={...progress,projectId};
    const next=document.getElementById('projectNextStep');if(next)next.outerHTML=projectNext(S.project);
    updateMarketingFlow();
  }
  function projectNext(p){
    const workflow=sceneWorkflow(p);if(workflow.scoped)return sceneNext(p,workflow);
    const items=p.items||[],adopted=items.filter(i=>i.status==='adopted');
    const focused=Boolean(p.draft)&&explicitDraftScope(p);
    const used=!p.draft&&p.topic_angle?adopted.filter(i=>p.topic_angle.asset_ids.includes(i.asset_id)):adopted;
    const current=focused?used.filter(i=>(p.draft_asset_ids||[]).includes(i.asset_id)):used;
    const pending=current.filter(materialPending),b=p.brief||{},m=p.kind==='marketing';
    let title,description,label,action,tone='ready';
    if(S.dirty&&S.project&&S.project.id===p.id&&p.draft_review){
      title='稿件或任务有未保存的修改';description='修改后需要重新审核。先保存当前修改，再检查稿件并完成审核。';label='保存当前修改';action='save';tone='pending';
    }else if(!(m?['topic','audience','goal']:['topic']).every(function(k){return String(b[k]||'').trim();})){
      title='先明确本次任务';description=m?'补充主题、内容给谁看和希望谁做什么。':'填写想分析的选题主题。';label='完善任务说明';action='task';tone='pending';
    }else if(p.draft_outdated){
      const removed=items.some(i=>i.status!=='adopted'&&(p.draft_asset_ids||[]).includes(i.asset_id));
      title=removed?'当前稿仍引用已取消采用的材料':'当前稿的引用需要核对';
      description='处理正文中受影响的段落，再确认这份稿件实际使用的材料。';
      label='核对当前稿引用';action='draft-references';tone='pending';
    }else if(focused&&!current.length){
      title='当前稿暂无引用材料';description='可以导出审阅稿。稿件通过审核前，请确认至少一条实际引用的材料。';label='核对当前稿引用';action='draft-references';tone='pending';
    }else if(!used.length&&!m){
      title=p.topic_angle?'为当前切口补充材料':'先比较这个选题的可做方向';description='查看每个切口的依据、可写范围和资料缺口。';label='查看选题分析';action='discover';tone='pending';
    }else if(!used.length){
      title=items.length?'材料已收集，下一步决定采用哪些':'先为本次策划找到材料';description=items.length?'内容确认说明材料可以使用；“项目采用”表示你决定把它用于本次策划。只需选择本次需要的材料。':'从内容成果选材，或让系统根据主题推荐材料。';label=items.length?'选择本项目采用的材料':'发现可用材料';action='materials';tone='pending';
    }else if(!p.draft&&p.topic_angle){
      title='已选切口「'+p.topic_angle.title+'」';description='用本次采用的 '+used.length+' 条材料组稿。';label='按这个切口组稿';action='generate';
    }else if(pending.length){
      title=current.length+(focused?' 条稿件材料中，还有 ':' 条已采用材料中，还有 ')+pending.length+' 条需要处理';description='先处理未确认、内容有变化或出处异常的材料，再审核交付稿件。其他已确认且内容未变的材料无需重复核对。';label='处理剩余材料';action='materials';tone='pending';
    }else if(p.draft){
      title=current.length+' 条稿件材料已确认';description=p.draft_review?'当前稿件已审核，可以导出交付；实际使用后，到“交付记录”记录结果。':'已有'+(m?'营销':'选题')+'讨论稿。下一步检查'+(m?'传播表达、渠道安排':'选题方向、目录建议')+'与待补资料，修订后审核、导出供团队讨论。材料确认不代表稿件已审核。';label=p.draft_review?'查看与导出已审核稿':'查看并修订已有稿件';action='draft';
    }else{
      title=used.length+' 条采用材料已确认，可以形成讨论稿';description=m?'将材料组织为传播角度、渠道内容和使用安排，生成后由营销编辑修订与审核。':'将材料组织为选题方向、目录建议和待补资料，生成后由编辑修订与审核。';label=m?'生成营销讨论稿':'生成选题讨论稿';action='generate';
    }
    return '<section id="projectNextStep" class="project-next-step '+tone+'" aria-label="当前进度与下一步"><div><span class="eyebrow">'+(tone==='ready'?'READY / NEXT STEP':'YOUR NEXT STEP')+'</span><h2>'+e(title)+'</h2><p>'+e(description)+'</p></div>'+btn(label+' →','continueProject',{action},'primary')+'</section>';
  }
  function continueProject(el){
    const action=el.dataset.action;
    if(action==='preview-generation'){
      const id=S.assistProgress?.draftRunId;if(id&&window.ProjectAssist)ProjectAssist.openPreview({dataset:{run:id}});return;
    }
    if(action==='draft-progress'){
      openProjectSection('results');const details=document.getElementById('projectDraftAssist');if(details)details.open=true;document.getElementById('projectAssist')?.scrollIntoView({block:'start',behavior:'smooth'});return;
    }
    if(action==='save'){save();return;}
    if(action==='draft-references'){openDraftReferenceReview();return;}
    if(action==='draft'){
      if(sceneWorkflow(S.project).scoped)setDraftMode('read');
      else if(!S.project.draft_review||S.project.draft_outdated)setDraftMode('edit');
      focusDraft();return;
    }
    const section=action==='generate'?'results':action==='discover'?'materials':action;
    openProjectSection(section);
    if(action==='materials'||action==='discover')showMaterialMode(action==='discover'?'recommended':(S.project.items||[]).length?'selected':'recommended');
    const panel=document.getElementById(action==='discover'?'projectDiscovery':'project-panel-'+section);if(panel)panel.scrollIntoView({behavior:'smooth',block:'start'});
    if(action==='generate'&&window.ProjectAssist)ProjectAssist.start({dataset:{cap:'draft'}});
  }
  function projectIntent(p){
    const b=p.brief||{},m=p.kind==='marketing';
    return '<section class="project-intent" id="projectIntent" aria-labelledby="projectTopic"><div class="project-intent-topic"><div class="project-intent-label">'+(m?'本次传播主题 · <span id="projectMarketingTask">'+e(MarketingScenes.fromBrief(b).map(MarketingScenes.label).join(' · '))+'</span>':'本次选题主题')+'</div><h2 id="projectTopic">'+e(b.topic||'请明确本次策划的主题')+'</h2></div><div class="project-intent-audience"><span class="project-intent-label">'+(m?'内容给谁看':'目标读者')+'</span><p id="projectAudience">'+e(b.audience||'待明确')+'</p></div><div class="project-intent-goal"><span class="project-intent-label">'+(m?'希望谁做什么':'工作目标')+'</span><p id="projectGoal">'+e(b.goal||'说明这次希望形成什么成果、支持什么决策')+'</p></div><div class="project-intent-actions"><span id="projectIntentState"></span>'+btn('修改任务','editProjectBrief',{},'sm ghost')+'</div></section>';
  }
  function refreshProjectLabels(){
    const p=S.project;if(!p)return;const items=p.items||[],used=items.filter(x=>x.status==='adopted').length;
    const status=document.getElementById('projectStatusBadge');if(status)status.innerHTML=p.status==='approved'?'<span class="studio-badge approved">稿件已审核</span>':badge(p.status);
    const counts=document.getElementById('projectMaterialCount');if(counts)counts.textContent=items.length+' 条材料 · 已采用 '+used+' 条';
    const title=document.querySelector('.project-name-row h1');if(title)title.textContent=p.title;
    const values={materials:items.length+' 条已收集 · '+used+' 条已采用',results:S.dirty?'有修改待保存':p.draft?(p.draft_outdated?'引用待核对':p.draft_review?'已审核':'待编辑审核'):'尚未形成工作稿',history:(p.exports||[]).length+' 次交付 · '+(p.feedback||[]).length+' 条反馈'};
    Object.entries(values).forEach(([section,value])=>{const node=document.querySelector('.project-overview-metrics [data-section="'+section+'"] b');if(node)node.textContent=value;});
    const n=document.querySelector('.project-material-modes [data-mode=selected] span');if(n)n.textContent=items.length;
    syncDraftStatus();updateMarketingFlow();
  }
  function syncProjectIntent(){
    const form=document.getElementById('projectBrief');if(!form||!S.project)return;
    const fields=projectFormFields(form);
    [['projectTopic','topic','请明确本次策划的主题'],['projectAudience','audience','待明确'],['projectGoal','goal','说明这次希望形成什么成果、支持什么决策'],['projectContextTopic','topic','待明确主题'],['projectContextAudience','audience','待明确']].forEach(function(x){
      const el=document.getElementById(x[0]);if(!el)return;
      const value=String(fields[x[1]]||'').trim()||x[2];
      el.textContent=value;
      if(el.id.startsWith('projectContext'))el.title=value;
    });
    const taskLabel=document.getElementById('projectMarketingTask');if(taskLabel)taskLabel.textContent=MarketingScenes.fromBrief(fields).map(MarketingScenes.label).join(' · ');
    const sceneTitle=document.getElementById('projectSceneTitle');
    if(sceneTitle){
      const w=MarketingScenes.workflow(fields),title=w.scoped?w.title:MarketingScenes.label('planning');sceneTitle.textContent=title;
      const crumbScene=document.querySelector('.project-crumb-scene');if(crumbScene){crumbScene.textContent=title;crumbScene.title='正在制作：'+title;}
      const tab=document.querySelector('.project-local-tab[data-section="results"]');if(tab)tab.textContent=fields.channels?.length===1?w.title:'各场景初稿';
      const stage=S.project.draft?3:(S.project.items||[]).some(i=>i.status==='adopted')?2:1;
      document.querySelectorAll('[data-scene-step]').forEach(el=>{const current=Number(el.dataset.sceneStep)===stage;el.classList.toggle('current',current);if(current)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');if(el.dataset.sceneStep==='2')el.innerHTML='<span>2</span>'+e('生成'+w.draft);});
    }
    const state=document.getElementById('projectIntentState');if(state)state.textContent=S.dirty?'有修改待保存':'';
  }
  function switchProject(){
    if(!S.project)return;
    clearTimeout(Switcher.timer);Switcher.request++;Switcher.query='';Switcher.offset=0;Switcher.total=0;Switcher.kind=S.project.kind;Switcher.projectId=S.project.id;Switcher.busy=false;
    openModal(modalX()+'<div id="projectSwitcher" data-project="'+e(S.project.id)+'"><h2>切换'+name(S.project)+'项目</h2><p class="muted">搜索同类项目，切换后继续当前工作环节。</p><form class="project-switch-search" onsubmit="event.preventDefault();Studio.searchProjects(this,true)"><input name="q" type="search" autofocus aria-label="搜索项目名称、主题或读者" placeholder="搜索项目名称、主题或读者" oninput="Studio.searchProjects(this)"><button class="btn primary" type="submit">搜索</button></form><div id="projectSwitchResults" aria-live="polite"></div></div>',true);
    loadProjectChoices();
  }
  async function loadProjectChoices(){
    const host=document.getElementById('projectSwitcher');if(!host||!S.project||host.dataset.project!==Switcher.projectId)return;
    const token=++Switcher.request,results=host.querySelector('#projectSwitchResults');results.innerHTML=loading('查找项目');results.setAttribute('aria-busy','true');
    try{
      const d=await request('/api/project-records?'+new URLSearchParams({kind:Switcher.kind,q:Switcher.query,limit:Switcher.limit,offset:Switcher.offset}));
      if(token!==Switcher.request||document.getElementById('projectSwitcher')!==host)return;
      if(d.ok===false)throw new Error(d.error||'项目列表暂时不可用');
      Switcher.total=Math.max(0,Number(d.total)||0);Switcher.offset=Switcher.total?Math.max(0,Number(d.offset)||0):0;const items=d.items||[];
      if(!items.length&&Switcher.offset>0&&Switcher.total>0){Switcher.offset=Math.floor((Switcher.total-1)/Switcher.limit)*Switcher.limit;return loadProjectChoices();}
      results.innerHTML='<p class="project-switch-count">'+num(Switcher.total)+' 个'+name({kind:Switcher.kind})+'项目</p>'+(items.length?'<div class="project-switch-list">'+items.map(function(p){const current=p.id===Switcher.projectId;return '<button type="button" class="project-switch-row'+(current?' current':'')+'" data-id="'+e(p.id)+'" onclick="Studio.switchToProject(this)"'+(current?' disabled':'')+'><span><b title="'+e(p.title)+'">'+e(p.title)+'</b><small>'+e((p.brief||{}).topic||(p.brief||{}).goal||'待补充工作目标')+'</small></span><span>'+(current?'正在编辑':'切换 →')+'</span></button>';}).join('')+'</div>':'<div class="project-switch-empty">没有找到匹配项目，请调整搜索词。</div>')+'<div class="project-switch-pagination"><span>第 '+(Math.floor(Switcher.offset/Switcher.limit)+1)+' / '+Math.max(1,Math.ceil(Switcher.total/Switcher.limit))+' 页</span><div><button type="button" class="btn sm ghost" data-delta="-1" onclick="Studio.switchProjectPage(this)"'+(Switcher.offset===0?' disabled':'')+'>上一页</button><button type="button" class="btn sm ghost" data-delta="1" onclick="Studio.switchProjectPage(this)"'+(Switcher.offset+Switcher.limit>=Switcher.total?' disabled':'')+'>下一页</button></div></div>';
      results.setAttribute('aria-busy','false');
    }catch(err){if(token!==Switcher.request||document.getElementById('projectSwitcher')!==host)return;results.innerHTML='<div class="project-switch-empty" role="alert">'+e(err.message)+btn('重新加载','retryProjectSwitch',{},'sm ghost')+'</div>';results.setAttribute('aria-busy','false');}
  }
  function searchProjects(el,immediate){
    const input=el.matches('input')?el:el.querySelector('[name=q]');if(!input||Switcher.busy)return;
    clearTimeout(Switcher.timer);Switcher.request++;Switcher.query=input.value.trim();Switcher.offset=0;
    if(immediate)loadProjectChoices();else Switcher.timer=setTimeout(loadProjectChoices,220);
  }
  function switchProjectPage(el){const next=Switcher.offset+Number(el.dataset.delta)*Switcher.limit;if(Switcher.busy||next<0||next>=Switcher.total)return;clearTimeout(Switcher.timer);Switcher.offset=next;loadProjectChoices();}
  function retryProjectSwitch(){loadProjectChoices();}
  async function switchToProject(el){
    const id=el.dataset.id,host=document.getElementById('projectSwitcher'),origin=Switcher.projectId,kind=Switcher.kind,section=S.section||'task';
    if(Switcher.busy||!host||!S.project||S.project.id!==origin||!/^prj-[a-f0-9]{16}$/.test(id||'')||id===origin)return;
    Switcher.busy=true;el.disabled=true;
    try{await saveCurrent(true);if(!S.project||S.project.id!==origin||document.getElementById('projectSwitcher')!==host)return;closeModal();go(kind==='marketing'?'campaigns':'projects',id,section);}catch(err){report(err);}finally{Switcher.busy=false;el.disabled=false;}
  }
  function initialProjectSection(p,section){
    if(SECTIONS.includes(section))return section;
    try{const saved=sessionStorage.getItem('bookworld.project-page:'+p.id);if(SECTIONS.includes(saved))return saved;}catch(_){}
    return p.draft?'results':(p.items||[]).length?'materials':'task';
  }
  function materialState(){
    const id=S.project&&S.project.id;
    return ProjectUI.materials[id]||(ProjectUI.materials[id]={mode:(S.project.items||[]).length?'selected':'recommended',q:'',filter:'',offset:0});
  }
  function prepareRelationMaterialList(projectId,assetId){
    ProjectUI.relationLanding={projectId,assetId};
  }
  function prepareMarketingMaterialList(projectId,assetId){
    ProjectUI.relationLanding={projectId,assetId,marketing:true};
  }
  function applyRelationMaterialLanding(project){
    const landing=ProjectUI.relationLanding;
    ProjectUI.relationLanding=null;
    if(landing?.projectId!==project.id||S.section!==(project.kind==='marketing'?'sources':'materials'))return;
    const index=(project.items||[]).findIndex(item=>item.asset_id===landing.assetId&&(landing.marketing?item.snapshot?.kind==='marketing':item.snapshot?.source_type==='graph_relation'));
    if(index<0)return;
    Object.assign(materialState(),{mode:'selected',q:'',filter:'',offset:Math.floor(index/MATERIAL_PAGE_SIZE)*MATERIAL_PAGE_SIZE});
  }
  function projectOverview(p){
    const b=p.brief||{},m=p.kind==='marketing',items=p.items||[],used=items.filter(x=>x.status==='adopted');
    return projectIntent(p)+'<div class="project-overview-metrics">'+[
      ['材料',items.length+' 条已收集 · '+used.length+' 条已采用','materials'],
      ['当前稿件',p.draft?(p.draft_outdated?'引用待核对':p.draft_review?'已审核':'待编辑审核'):'尚未形成工作稿','results'],
      ['交付与反馈',(p.exports||[]).length+' 次交付 · '+(p.feedback||[]).length+' 条反馈','history']
    ].map(x=>'<button type="button" data-section="'+x[2]+'" onclick="Studio.projectSection(this)"><span>'+x[0]+'</span><b>'+e(x[1])+'</b><i aria-hidden="true">↗</i></button>').join('')+'</div>'+
      '<details id="projectBriefEditor" class="studio-card project-brief-primary"'+(!b.topic||(m&&(!b.audience||!b.goal))?' open':'')+'><summary><span>修改任务说明</span><small>主题、读者与目标决定材料和稿件方向</small></summary><form id="projectBrief" class="studio-form" oninput="Studio.markDirty()">'+(m?marketingFields(b):'')+field('项目名称','title',p.title,'input')+field('主题 *','topic',b.topic,'input','本次关注什么问题')+field(m?'内容给谁看 *':'目标读者（选填）','audience',b.audience,'input','具体到人群、场景或需要解决的问题')+(m?MarketingPurpose.fields(b)+'<details class="marketing-secondary-settings"><summary>更多受众设置（选填）</summary>'+MarketingPurpose.readers(b)+'</details>':'')+field(m?'希望谁做什么 *':'工作目标（选填）','goal',b.goal,'textarea','本次希望形成什么成果、支持什么决策')+'</form><div class="card-actions">'+btn('保存任务说明','save',{},'primary')+'</div></details>'+
      ((p.warnings||[]).length?'<details class="project-overview-warnings"><summary>'+p.warnings.length+' 项来源提示</summary>'+p.warnings.map(w=>'<p>'+e(typeof w==='string'?w:w.title+'：'+w.reason)+'</p>').join('')+'</details>':'');
  }
  function manuscriptWorkspace(p){
    const outlineOpen=ProjectUI.outlineOpen??window.matchMedia('(min-width:1001px)').matches;
    return '<section id="projectDraftEditor" class="manuscript-workspace" aria-labelledby="projectDraftTitle"><div class="manuscript-toolbar"><div class="manuscript-title"><h2 id="projectDraftTitle">当前工作稿</h2><span id="projectDraftStatus" role="status"></span></div><div class="manuscript-actions"><div class="manuscript-view-switch" role="group" aria-label="稿件视图">'+btn('阅读','setDraftMode',{mode:'read'})+btn('编辑','setDraftMode',{mode:'edit'})+'</div><button id="projectDraftSave" type="button" class="btn primary sm" onclick="Studio.save()" hidden>保存稿件</button><details class="manuscript-export" id="projectDraftRelease"><summary class="btn ghost sm">审核与导出 ⌄</summary><div id="projectDraftReleaseActions"></div></details></div></div>'+
      '<details class="manuscript-assist" id="projectDraftAssist" ontoggle="Studio.rememberDraftDetails(this)"'+((ProjectUI.assistOpen??!p.draft)?' open':'')+'><summary><span>生成建议与记录</span><small id="projectDraftAssistState"></small></summary><section class="project-assist studio-card" aria-label="生成建议与记录" id="projectAssist" data-project="'+e(p.id)+'"></section><details class="project-manuscript-tools"><summary>更多整理方式</summary><p>用已采用材料重新整理当前正文。</p>'+btn('整理已采用材料','compose',{},'sm ghost')+'</details></details>'+
      '<div id="projectSceneViews" class="manuscript-scene-views" hidden></div><div class="manuscript-body"><aside class="manuscript-outline"><details id="projectDraftContents" ontoggle="Studio.rememberDraftDetails(this)"'+(outlineOpen?' open':'')+'><summary>稿件目录</summary><nav id="projectDraftOutline" aria-label="稿件目录"></nav></details><button type="button" class="manuscript-source-button" onclick="Studio.openDraftReferenceReview()">核对当前稿引用 ↗</button><div id="projectDraftNameChecks" hidden></div></aside><div class="manuscript-paper"><article id="projectDraftReading" class="manuscript-reading" aria-label="当前工作稿阅读视图" tabindex="-1"></article><div id="projectDraftRichHost" hidden></div><textarea id="projectDraft" hidden oninput="Studio.markDirty()"></textarea></div></div><footer class="manuscript-footer" id="projectDraftCount"></footer></section>';
  }
  function projectPageGuide(id,section,title,description,steps){
    return '<section id="'+id+'" data-project-guide="'+section+'" class="project-page-guide" aria-labelledby="'+id+'Title" hidden>'+
      '<div class="project-page-guide-intro"><h2 id="'+id+'Title">'+e(title)+'</h2>'+
      '<p>'+e(description)+'</p></div>'+
      projectFlowSteps(steps)+'</section>';
  }
  function projectHeaderGuides(marketing){
    return projectPageGuide('projectMaterialsGuide','materials','项目材料怎么用','为本项目选材料、查原文出处，供组稿使用。',[
      ['找材料','用「发现材料」，或从内容成果选材。'],
      ['采用并核对','选要用的材料，按提示核对内容与出处。'],
      [marketing?'去营销稿':'去策划稿','用选定的材料生成稿件。']
    ])+projectPageGuide('projectDraftGuide','results',marketing?'营销稿怎么用':'策划稿怎么用','用选定材料组出带出处的稿件，也可以直接编辑已有工作稿。',[
      ['生成并应用','在「生成建议与记录」生成，预览确认后应用。'],
      ['编辑并核对','点「编辑」修稿，核对出处后保存。'],
      ['审核与导出','审核后导出交付稿，版本见「交付记录」。']
    ]);
  }
  function sceneGuide(p){
    const w=sceneWorkflow(p);if(!w.scoped)return '';
    return '<section class="project-scene-guide" aria-label="本次内容场景与制作步骤"><div><span>正在制作</span><strong id="projectSceneTitle">'+e(w.title)+'</strong></div><ol>'+['选择素材','生成'+w.draft,'审核与导出'].map((title,i)=>'<li data-scene-step="'+(i+1)+'"><span>'+(i+1)+'</span>'+e(title)+'</li>').join('')+'</ol></section>';
  }
  function materialWorkspace(p){
    const ui=materialState(),w=sceneWorkflow(p);
    return '<div class="project-material-header"><h2>'+(w.scoped?e('为'+w.title+'选择素材'):'项目材料')+'</h2><div class="project-material-tools">'+btn(w.scoped?'从素材库补充':'从内容成果选材','findForProject',{},'sm ghost')+relationLookupButton()+'</div></div><div class="project-material-modes" role="group" aria-label="材料视图"><button type="button" data-mode="selected" onclick="Studio.showMaterialMode(this)">'+(w.scoped?'本次素材':'已收集')+' <span>'+(p.items||[]).length+'</span></button><button type="button" data-mode="recommended" onclick="Studio.showMaterialMode(this)">'+(w.scoped?'从图书中选素材':'发现材料')+'</button></div><section id="projectSelectedMaterials" class="project-selected-list"><div class="project-material-filters"><input type="search" aria-label="搜索项目材料" placeholder="搜索标题、来源或用途" value="'+e(ui.q)+'" oninput="Studio.filterMaterials(this)"><select aria-label="材料状态" onchange="Studio.filterMaterials(this)">'+[['','全部材料'],['selected','待选择'],['adopted','已采用'],['pending','采用后待核对'],['not_fit','本项目不采用']].map(x=>'<option value="'+x[0]+'"'+(ui.filter===x[0]?' selected':'')+'>'+x[1]+'</option>').join('')+'</select></div><div id="projectMaterialRows"></div></section><section id="projectDiscovery" class="studio-card project-discovery" aria-label="发现可用材料与推荐结果" data-project="'+e(p.id)+'"></section>';
  }
  function relationLookupButton(){
    return btn('查人物与关系','nav',{view:'kglab','relation-lookup':''},'sm ghost');
  }
  const MARKETING_STEPS={task:['填写要求','选择推广图书，说明这次想写什么、写给谁。',1],materials:['选择素材','选中本次要用的素材，即可写初稿。',2],results:['查看与修改稿件','阅读初稿，按需要修改内容。',3],review:['交付前检查','确认本稿的内容和出处，再下载交付稿。',4],sources:['素材与出处','查看当前稿件的来源、策划依据及引用内容。',null],history:['交付记录','查看已导出的版本和使用反馈。',null]};
  function videoBrief(p){return p?.brief?.marketing_task==='channel'&&(p.brief.channels||[]).includes('短视频');}
  function marketingBrief(p){
    const b=p.brief||{},channel=b.marketing_task==='channel',video=videoBrief(p);
    const guide=MarketingScenes.audienceGuide(b),hintId='projectAudienceGuide';
    const notesHint=video?'希望观众感受到什么，以及画面风格和时长，会用于下一次生成。':'可以指定想让受众产生的感受，以及篇幅和语气。';
    let fields;
    if(channel){
      const codes=b.target_codes||[],books=(state.books||[]).map(x=>({code:x.code,title:x.book}));
      codes.filter(x=>!books.some(y=>y.code===x)).forEach(x=>books.push({code:x,title:'原推广图书（已不在书库）'}));
      fields='<input type="hidden" name="marketing_task" value="channel">'+(b.channels||[]).map(x=>'<input type="hidden" name="channels" value="'+e(x)+'">').join('')+
        '<fieldset class="marketing-book-choices"><legend>推广哪本书</legend>'+books.map(x=>'<label><input type="checkbox" name="target_codes" value="'+e(x.code)+'"'+(codes.includes(x.code)?' checked':'')+'><span>'+e(x.title)+'</span></label>').join('')+'</fieldset>';
    }else fields=marketingFields(b);
    return '<form id="projectBrief" class="studio-form marketing-brief" onsubmit="event.preventDefault();Studio.marketingNext()" oninput="Studio.markDirty()">'+fields+field('内容主题','topic',b.topic,'input','这次想写什么')+field(guide.label,'audience',b.audience,'input',guide.placeholder,hintId)+'<p id="'+hintId+'" class="marketing-audience-hint">'+e(guide.hint)+'</p>'+MarketingPurpose.fields(b)+field(guide.goalLabel,'goal',b.goal,'textarea',guide.goalPlaceholder)+'<label class="studio-field" id="marketingWritingNotes"><span>'+e(guide.notesLabel)+'（选填）</span><textarea name="writing_notes" rows="4" maxlength="4000" placeholder="'+e(guide.notesPlaceholder)+'">'+e(b.writing_notes||'')+'</textarea><small>'+e(notesHint)+'</small></label><details class="marketing-secondary-settings"><summary>更多设置（选填）</summary>'+MarketingPurpose.readers(b)+field('项目名称','title',p.title,'input')+'</details></form>';
  }
  function marketingManuscript(p){
    return '<div id="projectDraftAssist"><section id="projectAssist" class="project-assist" data-project="'+e(p.id)+'"></section></div><section id="projectDraftEditor" class="manuscript-workspace"><div class="manuscript-toolbar"><span id="projectDraftStatus" role="status"></span><div class="manuscript-actions"><div class="manuscript-view-switch" role="group" aria-label="稿件视图">'+btn('阅读','setDraftMode',{mode:'read'})+btn('编辑','setDraftMode',{mode:'edit'})+'</div><button id="projectDraftSave" type="button" class="btn primary sm" onclick="Studio.save()" hidden>保存修改</button></div></div><div id="projectSceneViews" class="manuscript-scene-views" hidden></div><div class="manuscript-body"><div class="manuscript-paper"><article id="projectDraftReading" class="manuscript-reading" tabindex="-1"></article><div id="projectDraftRichHost" hidden></div><textarea id="projectDraft" hidden oninput="Studio.markDirty()"></textarea></div></div><footer class="manuscript-footer" id="projectDraftCount"></footer><nav id="projectDraftOutline" hidden></nav><details id="projectDraftRelease" hidden><div id="projectDraftReleaseActions"></div></details></section>';
  }
  function marketingProjectDetail(v){
    const p=S.project;v.classList.add('project-workspace','marketing-workspace');v.classList.remove('marketing-entry-view');
    v.innerHTML='<div class="marketing-flow"><div id="marketingOriginReturn" hidden></div><header class="marketing-flow-head"><div><div class="marketing-flow-identity"><span id="projectSceneTitle">'+e(sceneWorkflow(p).title)+'</span><span class="marketing-project-name">'+e(p.title)+'</span></div><div class="marketing-flow-title"><h1 id="marketingPageTitle"></h1><span id="marketingStepCount"></span></div><p id="marketingPageHint"></p></div><details class="marketing-more"><summary class="btn ghost sm">更多 ···</summary><nav aria-label="本项目其他页面">'+[['task','修改内容要求'],['materials','选择素材'],['results','查看稿件'],['review','交付前检查'],['sources','素材与出处'],['history','交付记录']].map(x=>btn(x[1],'projectSection',{section:x[0]},'ghost sm')).join('')+'<button type="button" class="btn ghost sm" data-marketing-results-action onclick="ProjectAssist.triggerDraft()">重新生成初稿</button><button type="button" class="btn ghost sm" data-marketing-results-action onclick="Studio.editWritingNotes()">'+(videoBrief(p)?'修改制作要求':'修改写作要求')+'</button><button type="button" class="btn ghost sm" data-marketing-results-action onclick="ProjectAssist.openRecords()">初稿生成记录</button>'+(videoBrief(p)?'<button type="button" class="btn ghost sm" data-video-prompts-records onclick="VideoPrompts.showRecords()" hidden>已生成的画面内容</button>':'')+'<button type="button" class="btn ghost sm" data-marketing-results-action onclick="Studio.setDraftMode(\'edit\')">编辑稿件</button><button type="button" class="btn ghost sm" onclick="ProjectAssist.reuse()">复制为新项目</button><a href="#/records/marketing">我的营销项目</a></nav></details></header><div id="marketingRecovery" hidden></div>'+
      '<section id="project-panel-task" class="project-section-panel" aria-label="填写要求">'+marketingBrief(p)+'</section>'+
      '<section id="project-panel-materials" class="project-section-panel" aria-label="选择素材"><div class="project-material-tools">'+relationLookupButton()+'</div><section id="projectDiscovery" class="project-discovery" data-project="'+e(p.id)+'"></section></section>'+
      '<section id="project-panel-results" class="project-section-panel" aria-label="查看稿件">'+marketingManuscript(p)+'</section>'+
      '<section id="project-panel-review" class="project-section-panel" aria-label="交付前检查"><div id="marketingReview"></div></section>'+
      '<section id="project-panel-sources" class="project-section-panel" aria-label="素材与出处"><article id="marketingSourceContext" class="manuscript-reading studio-card"></article><div class="project-material-header"><h2 class="marketing-sources-heading">本项目素材</h2><div class="project-material-tools">'+btn('从素材库补充','findForProject',{},'ghost sm')+relationLookupButton()+'</div></div><div id="projectMaterialRows"></div></section>'+
      '<section id="project-panel-history" class="project-section-panel" aria-label="交付记录"><div id="projectHistory"></div></section>'+
      '<footer class="marketing-flow-footer"><button type="button" class="btn ghost" onclick="Studio.marketingStepBack()">← 上一步</button><span id="marketingStepState" role="status"></span><button id="marketingNext" type="button" class="btn primary" onclick="Studio.marketingNext()"></button></footer><span id="projectSaveState" class="marketing-save-state"></span><div id="projectSidePanelRoot"></div></div>';
    v.querySelector('#projectDraft').value=p.draft||'';if(p.brief?.marketing_task!=='channel')syncMarketingFields(v.querySelector('#projectBrief'));
    S.section=MARKETING_STEPS[S.section]?S.section:'task';showProjectSection(S.section);refreshProjectLabels();renderMaterialRows();syncDraftView();syncDraftOutline();
    if(window.ProjectHistory)ProjectHistory.mount(document.getElementById('projectHistory'),p);
    if(window.ProjectAssist)ProjectAssist.mount(p);
    if(ProjectUI.detail?.project===p.id)openMaterialDetail({dataset:{id:ProjectUI.detail.id}});
  }
  function deliverySourceState(item){
    if(item.current_status==='missing')return '来源缺失';
    if(item.current_status==='rejected')return '素材已停用';
    if(item.stale)return '需更新引用';
    if(item.status!=='adopted')return '需调整引用';
    if(!item.evidence_valid||(item.quality_issues||[]).length)return '出处需处理';
    if(item.current_status!=='approved')return '核对出处';
    return '需确认引用';
  }
  function renderMarketingReview(p,draft,items,pending,writingNeeds){
    const host=document.getElementById('marketingReview');
    const edit=btn(draft?'修改稿件':'查看稿件','projectSection',{section:'results'},'ghost sm');
    if(!draft){host.innerHTML='<div class="marketing-review-card"><h2>先完成稿件</h2>'+edit+'</div>';return;}
    const row=(item,status)=>'<button class="marketing-review-source" type="button" data-id="'+e(item.asset_id)+'" onclick="Studio.openMaterialDetail(this)"><span>'+e(projectMaterialTitle(item.snapshot,'引用素材'))+'</span><small>'+e(status)+' →</small></button>';
    const adjust=btn('调整本稿引用','openDraftReferenceReview',{},'ghost sm');
    const open=host.querySelector('details[data-confirmed-sources]')?.open;
    const pendingIds=new Set(pending.map(item=>item.asset_id)),confirmed=items.filter(item=>!pendingIds.has(item.asset_id));
    const clear=items.length&&!pending.length&&!p.draft_outdated;
    const title=clear?'本稿出处已核对':pending.length?'待核对素材 · '+pending.length+' 条':p.draft_outdated?'本稿有出处需调整':'为本稿关联出处';
    const pendingRows=pending.map(item=>row(item,deliverySourceState(item))).join('');
    const confirmedRows=confirmed.length?'<details class="marketing-confirmed-sources" data-confirmed-sources'+(open?' open':'')+'><summary>'+ (clear?'查看出处':'已核对出处')+' · '+confirmed.length+' 条</summary>'+confirmed.map(item=>row(item,'查看')).join('')+(clear?'<div class="card-actions">'+adjust+'</div>':'')+'</details>':'';
    const needs=writingNeeds.length?'<details class="marketing-writing-needs"><summary>内容调整建议</summary>'+writingNeeds.map(x=>'<div><p>'+e(x.message)+'</p>'+btn(x.kind==='materials'?'补选素材':videoBrief(p)?'修改制作要求':'修改写作要求',x.kind==='materials'?'projectSection':'editWritingNotes',x.kind==='materials'?{section:'materials'}:{},'ghost sm')+'</div>').join('')+'</details>':'';
    host.innerHTML='<section class="marketing-review-card"><div class="marketing-review-heading"><h2>'+e(title)+'</h2>'+edit+'</div>'+pendingRows+(!clear?'<div class="card-actions">'+adjust+'</div>':'')+confirmedRows+'</section>'+needs+
      '<div data-review-name-checks hidden></div>'+
      '<div class="marketing-review-alt">'+btn('下载审阅稿','exportProject',{mode:'review'},'ghost sm')+'</div>';
    loadNameChecks(host.querySelector('[data-review-name-checks]'),p);
  }
  function updateMarketingFlow(){
    const p=S.project,head=document.getElementById('marketingPageTitle');if(p?.kind!=='marketing'||!head)return;
    const step=S.section||'task',spec=MARKETING_STEPS[step]||MARKETING_STEPS.task,w=sceneWorkflow(p),summary=S.assistProgress?.projectId===p.id?S.assistProgress:{};
    const origin=step==='sources'?window.MarketingOverlay?.sourceReturn?.():null,originLabel=origin?(origin.overlay.descriptor.mode==='image'?'返回图片制作包':'返回视频制作包'):'';
    const originHost=document.getElementById('marketingOriginReturn');
    if(originHost){originHost.hidden=!origin;originHost.innerHTML=origin?'<button type="button" class="btn ghost sm" data-marketing-origin-return onclick="Studio.returnToSourceOrigin()">← '+e(originLabel)+'</button>':'';}

    document.querySelectorAll('[data-video-prompts-records],[data-video-records-row]').forEach(x=>{x.hidden=!summary.videoPromptCount;});
    document.querySelectorAll('[data-video-prompts-start]').forEach(x=>{x.disabled=!!summary.runningCapability||!!summary.busy;});
    document.querySelectorAll('[data-marketing-results-action]').forEach(x=>{x.hidden=step!=='results';if(x.getAttribute('onclick').includes('triggerDraft'))x.disabled=!(summary.usedCount??(p.items||[]).filter(i=>i.status==='adopted').length)||!!summary.runningCapability||!!summary.busy;});
    const videoResult=step==='results'&&videoBrief(p)&&(p.brief.channels||[]).length===1;
    const planResult=step==='results'&&!w.scoped;
    head.textContent=videoResult?'查看与修改口播稿':planResult?'查看与修改方案':spec[0];document.getElementById('marketingPageHint').textContent=videoResult?'确认口播内容，再选择图片或视频展示。':planResult?'核对核心卖点和推进安排，审核后可下载方案。':spec[1];document.getElementById('marketingStepCount').textContent=!videoResult&&spec[2]?'第 '+spec[2]+' / 4 步':'';
    crumb('<a href="#/campaigns">营销</a><span class="crumb-sep">/</span><span class="project-crumb-scene">'+e(w.title)+'</span><span class="crumb-sep">/</span><b>'+e(head.textContent)+'</b>');
    const draft=document.getElementById('projectDraft')?.value.trim(),used=(p.items||[]).filter(x=>x.status==='adopted'),button=document.getElementById('marketingNext'),status=document.getElementById('marketingStepState');
    let label='',info='',action='',disabled=false;
    if(step==='task'){
      const revising=S.writingRevisionFor===p.id;
      if(revising&&(summary.usedCount??used.length)){label='保存要求并重新生成 →';action='generate';info='生成后先预览，再决定是否替换当前稿';disabled=!!summary.runningCapability||!!summary.busy;}
      else{label=revising?'保存要求，去选择素材 →':'下一步：选择素材 →';action='materials';}
    }
    else if(step==='materials'){
      info='已选 '+(summary.usedCount??used.length)+' 条素材';
      if(summary.runningCapability==='draft'){label='查看生成进度 →';action='results';}
      else if(summary.draftReady&&!S.dirty){label='查看已生成初稿 →';action='preview';}
      else if(draft){
        const candidates=p.brief?.marketing_task==='channel'?used.filter(x=>(p.brief.target_codes||[]).includes(x.snapshot?.code)):used,ids=new Set(p.draft_asset_ids||[]);
        const changed=explicitDraftScope(p)&&(candidates.length!==ids.size||candidates.some(x=>!ids.has(x.asset_id)));
        if(changed&&candidates.length){label='用当前素材重新生成 →';action='generate';disabled=!!summary.runningCapability||!!summary.busy;info+=' · 与当前稿不同';}
        else{label='下一步：查看稿件 →';action='results';}
      }
      else{label=w.generate+' →';action='generate';disabled=!(summary.usedCount??used.length)||!!summary.runningCapability||!!summary.busy;}
    }else if(step==='results'){
      if(summary.runningCapability==='draft'){label='正在生成初稿…';disabled=true;}
      else if(summary.draftReady&&!S.dirty){label='预览生成的初稿 →';action='preview';}
      else if(summary.videoPromptCount&&videoBrief(p)){label='继续画面制作 →';action='video-prompts';}
      else if(draft){if(videoBrief(p)&&(p.brief.channels||[]).length===1){label='确认内容，选择呈现方式';action='video-prompts';}else{label='下一步：交付前检查 →';action='review';}}
      else{label=used.length?'生成初稿 →':'先选择素材 →';action=used.length?'generate':'materials';disabled=!!summary.runningCapability;}
      info=S.dirty?'有修改待保存，返回时会保留':draft?'修改会保存在本项目中':'';
    }else if(step==='review'){
      const cited=new Set(p.draft_asset_ids||[]),scoped=explicitDraftScope(p);
      const items=(p.items||[]).filter(x=>cited.has(x.asset_id)||!scoped&&x.status==='adopted');
      const issueIds=new Set((p.draft_reference_issues||[]).map(x=>x.asset_id));
      const pending=items.filter(x=>materialPending(x)||x.status!=='adopted'||issueIds.has(x.asset_id));
      const blocked=!draft||!items.length||p.draft_outdated||pending.length,ready=!blocked&&p.draft_review&&!S.dirty;
      renderMarketingReview(p,draft,items,pending,S.dirty?[]:summary.writingNeeds||[]);
      label=ready?(w.scoped?'下载'+w.title+' →':'下载已审核稿 →'):'确认稿件';action=ready?'export':'approve';disabled=!!blocked;info=ready?'当前版本已审核':'';
    }else if(origin){label='← '+originLabel;action='return-origin';}
    else{label='返回稿件 →';action='results';}
    button.textContent=label;button.dataset.action=action;button.disabled=disabled;button.toggleAttribute('data-video-prompts-start',action==='video-prompts');status.textContent=info;
    const back=document.querySelector('.marketing-flow-footer > button:first-child');back.textContent='← 返回上一页';
    const editor=document.getElementById('projectDraftEditor');if(editor)editor.hidden=step==='results'&&!draft&&!summary.videoPromptCount&&ProjectUI.draftMode!=='edit';
  }
  async function marketingNext(){
    const button=document.getElementById('marketingNext');if(!button||button.disabled)return;
    const action=button.dataset.action;
    try{
      if(S.section==='task'){
        const fields=projectFormFields(document.getElementById('projectBrief'));
        for(const [key,label] of [['topic','内容主题'],['audience','内容给谁看'],['goal','希望谁做什么']])if(!String(fields[key]||'').trim()){toast('请填写'+label,true);document.querySelector('#projectBrief [name="'+key+'"]').focus();return;}
        if(fields.marketing_task==='channel'&&!fields.target_codes.length){toast('请选择推广图书',true);return;}
      }
      if(action==='video-prompts'){VideoPrompts.open();return;}
      if(action==='return-origin'){returnToSourceOrigin();return;}
      if(['sources','history'].includes(S.section)&&MARKETING_STEPS[action]){openProjectSection(action);return;}
      await saveCurrent(true);
      if(action==='generate'){ProjectAssist.triggerDraft();return;}
      if(action==='preview'){if(S.section!=='results')openProjectSection('results');else ProjectAssist.previewLatest();return;}
      if(action==='approve'){await approveProject();return;}
      if(action==='export'){await exportProject({dataset:{mode:'approved'}});return;}
      if(MARKETING_STEPS[action])openProjectSection(action);
    }catch(err){report(err);}
  }
  function returnToSourceOrigin(){
    if(window.MarketingOverlay?.returnToSourceOrigin?.())return;
    openProjectSection('results');
  }
  function marketingStepBack(){
    const parents={materials:'task',results:'materials',review:'results',sources:'results',history:'results'};
    if(window.marketingBackTo)window.marketingBackTo(parents[S.section]);else navBack();
  }
  function rememberNavigation(){
    if(!S.project||!document.getElementById('projectBrief'))return;
    if(S.dirty)cacheLocalDraft();
    const ui={materials:ProjectUI.materials[S.project.id],draftMode:ProjectUI.draftMode,draftScene:ProjectUI.draftScene,outlineOpen:ProjectUI.outlineOpen,assistOpen:ProjectUI.assistOpen,writingRevisionFor:S.writingRevisionFor};
    try{sessionStorage.setItem('bookworld.project-ui:'+S.project.id,JSON.stringify(ui));}catch(_){}
  }
  function restoreNavigation(p){
    let ui;try{ui=JSON.parse(sessionStorage.getItem('bookworld.project-ui:'+p.id)||'null');}catch(_){}if(!ui)return;
    if(ui.materials)ProjectUI.materials[p.id]=ui.materials;
    if(['read','edit'].includes(ui.draftMode))ProjectUI.draftMode=ui.draftMode;
    ProjectUI.draftScene=ui.draftScene||null;ProjectUI.outlineOpen=ui.outlineOpen??null;ProjectUI.assistOpen=ui.assistOpen??null;S.writingRevisionFor=ui.writingRevisionFor===p.id?p.id:null;
  }
  function localDraftKey(projectId=S.project?.id){return 'bookworld.local-draft:'+projectId;}
  function cacheLocalDraft(){
    if(S.project?.kind!=='marketing')return;
    const form=document.getElementById('projectBrief'),draft=document.getElementById('projectDraft');if(!form||!draft)return;
    try{sessionStorage.setItem(localDraftKey(),JSON.stringify({revision:S.project.revision,fields:projectFormFields(form),draft:draft.value,notes:ProjectUI.notes,draftAssetIds:S.draftAssetIds,draftRebuilt:S.draftRebuilt}));}catch(_){}
  }
  function clearLocalDraft(){try{sessionStorage.removeItem(localDraftKey());}catch(_){} }
  function advanceLocalDraftAfterRelation(projectId,previousRevision,newRevision){
    if(!/^prj-[a-f0-9]{16}$/.test(projectId)||!Number.isInteger(previousRevision)||previousRevision<1||newRevision!==previousRevision+1)return;
    const key=localDraftKey(projectId);
    try{
      if(sessionStorage.getItem(key+':conflict'))return;
      const saved=JSON.parse(sessionStorage.getItem(key)||'null');
      if(saved?.revision!==previousRevision)return;
      sessionStorage.setItem(key,JSON.stringify({...saved,revision:newRevision}));
    }catch(_){}
  }
  function restoreLocalDraft(){
    if(S.project?.kind!=='marketing')return;
    let saved,conflict;try{saved=JSON.parse(sessionStorage.getItem(localDraftKey())||'null');conflict=sessionStorage.getItem(localDraftKey()+':conflict');}catch(_){}
    if(saved&&saved.revision!==S.project.revision){try{sessionStorage.setItem(localDraftKey()+':conflict',JSON.stringify(saved));sessionStorage.removeItem(localDraftKey());}catch(_){}conflict=true;saved=null;}
    if(conflict){const alert=document.getElementById('marketingRecovery');alert.hidden=false;alert.innerHTML='<span>发现一份未保存的本地副本，项目版本已更新。</span>'+btn('查看副本','showLocalRecovery',{},'ghost sm');}
    if(!saved)return;
    const form=document.getElementById('projectBrief');
    form.querySelectorAll('[name]').forEach(x=>{const value=saved.fields[x.name];if(value===undefined||Array.isArray(value)&&x.type==='hidden')return;if(x.type==='checkbox')x.checked=Array.isArray(value)&&value.includes(x.value);else x.value=value;});
    syncMarketingFields(form);
    document.getElementById('projectDraft').value=saved.draft||'';ProjectUI.notes=saved.notes||{};S.draftAssetIds=saved.draftAssetIds;S.draftRebuilt=!!saved.draftRebuilt;
    markDirty();syncDraftOutline();toast('已恢复上次未保存的修改');
  }
  function showLocalRecovery(){
    let saved;try{saved=JSON.parse(sessionStorage.getItem(localDraftKey()+':conflict')||sessionStorage.getItem(localDraftKey())||'null');}catch(_){}if(!saved)return;
    openModal(modalX()+'<h2>未保存的本地副本</h2><p>项目已有新版本。可复制需要保留的文字，再回到当前稿件修改。</p><textarea class="marketing-recovery-text" rows="16" readonly>'+e(JSON.stringify(saved.fields,null,2)+'\n\n'+saved.draft+'\n\n素材备注：'+JSON.stringify(saved.notes,null,2))+'</textarea>',true);
  }

  function projectDetail(v){
    if(S.project.kind==='marketing')return marketingProjectDetail(v);
    const p=S.project,b=p.brief||{},m=p.kind==='marketing',w=sceneWorkflow(p),items=p.items||[],used=items.filter(x=>x.status==='adopted').length;
    crumb(w.scoped?'<span class="project-crumb-scene" title="'+e('正在制作：'+w.title)+'">'+e(w.title)+'</span><span class="project-crumb-path">/ <a href="#/records/marketing">营销策划</a> / '+e(clip(p.title,24))+'</span>':'<a href="#/records">工作项目</a><span>/</span><a href="'+e(window.ProjectRecords?ProjectRecords.returnUrl(p.kind):'#/records/'+p.kind)+'">'+name(p)+'</a><span>/</span><b>'+e(clip(p.title,24))+'</b>');
    v.classList.add('project-workspace');
    const specs=[['task',w.scoped?'内容要求':'项目概览'],['materials',w.scoped?'选择素材':'项目材料'],['results',w.scoped?(b.channels?.length===1?w.title:'各场景初稿'):m?'场景成果':'策划稿'],['history','交付记录']];
    v.innerHTML='<header class="project-workspace-head"><div><div class="project-identity"><span>'+name(p)+'</span><span id="projectStatusBadge">'+badge(p.status)+'</span><span id="projectMaterialCount">'+items.length+' 条材料 · 已采用 '+used+' 条</span></div><div class="project-name-row"><h1>'+e(p.title)+'</h1>'+btn('切换项目 ⌄','switchProject',{},'sm ghost')+'</div></div>'+
      (w.scoped?'':projectHeaderGuides(m))+'<div class="project-head-tools"><span id="projectSaveState">已保存 · '+e(ago(p.updated_at))+'</span>'+btn('保存','save',{},'sm ghost')+(m?btn('热点匹配','nav',{view:'hotspot'},'sm ghost'):'')+'<button type="button" class="btn sm ghost" onclick="ProjectAssist.reuse()">复用为新项目</button></div></header>'+
      '<div class="project-local-nav" role="tablist" aria-label="本项目工作区">'+specs.map(x=>'<button type="button" class="project-local-tab" role="tab" id="project-tab-'+x[0]+'" aria-controls="project-panel-'+x[0]+'" data-section="'+x[0]+'" onclick="Studio.projectSection(this)">'+x[1]+'</button>').join('')+'</div>'+
      sceneGuide(p)+'<div id="projectContext" class="project-context-strip"><div><span>'+(m?'传播主题':'选题主题')+'</span><b id="projectContextTopic">'+e(b.topic||'待明确主题')+'</b></div><div><span>'+(m?'内容给谁看':'目标读者')+'</span><b id="projectContextAudience">'+e(b.audience||'待明确')+'</b></div>'+btn('任务详情','projectSection',{section:'task'},'sm ghost')+'</div>'+projectNext(p)+
      '<section id="project-panel-task" class="project-section-panel" role="tabpanel" aria-labelledby="project-tab-task">'+projectOverview(p)+'</section>'+
      '<section id="project-panel-materials" class="project-section-panel" role="tabpanel" aria-labelledby="project-tab-materials">'+materialWorkspace(p)+'</section>'+
      '<section id="project-panel-results" class="project-section-panel" role="tabpanel" aria-labelledby="project-tab-results">'+manuscriptWorkspace(p)+'</section>'+
      '<section id="project-panel-history" class="project-section-panel" role="tabpanel" aria-labelledby="project-tab-history"><div id="projectHistory"></div></section><div id="projectSidePanelRoot"></div>';
    v.querySelector('.project-local-nav').addEventListener('keydown',function(event){if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const tabs=Array.from(this.querySelectorAll('[role=tab]'));let index=tabs.indexOf(document.activeElement);if(index<0)return;event.preventDefault();index=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[index].focus();});
    // Both editable forms remain mounted across all local pages.
    v.querySelector('#projectDraft').value=p.draft||'';
    if(m)syncMarketingFields(v.querySelector('#projectBrief'));
    showProjectSection(S.section||'task');syncProjectIntent();refreshProjectLabels();renderMaterialRows();showMaterialMode(materialState().mode);syncDraftView();syncDraftOutline();
    if(window.ProjectHistory)ProjectHistory.mount(document.getElementById('projectHistory'),p);
    if(window.ProjectAssist)ProjectAssist.mount(p);
    if(ProjectUI.detail&&ProjectUI.detail.project===p.id)openMaterialDetail({dataset:{id:ProjectUI.detail.id}});
    else restoreEditorialRelationDetail(p);
  }
  function showProjectSection(section){
    if(!SECTIONS.includes(section))return;S.section=section;document.querySelectorAll('.marketing-more').forEach(x=>x.open=false);
    document.querySelectorAll('.project-section-panel').forEach(p=>{p.hidden=p.id!=='project-panel-'+section;});
    document.querySelectorAll('.project-local-tab').forEach(tab=>{const selected=tab.dataset.section===section;tab.classList.toggle('on',selected);tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;});
    const context=document.getElementById('projectContext');if(context)context.hidden=section==='task';
    const v=document.getElementById('view');
    if(v){
      v.dataset.projectSection=section;
      v.querySelectorAll('[data-project-guide]').forEach(guide=>{guide.hidden=guide.dataset.projectGuide!==section;});
    }
    if(section==='results')S.writingRevisionFor=null;
    syncProjectIntent();updateMarketingFlow();
    if(section==='task'&&S.focusWritingNotes){S.focusWritingNotes=false;const pid=S.project?.id;setTimeout(()=>{if(S.project?.id!==pid||S.section!=='task')return;const field=document.querySelector('#projectBrief [name=writing_notes]');field?.focus({preventScroll:true});field?.scrollIntoView({block:'center',behavior:'instant'});},260);}
    if(window.ProjectNav)ProjectNav.update(S.project,section);
    if(S.project)try{sessionStorage.setItem('bookworld.project-page:'+S.project.id,section);}catch(_){}
  }
  function openProjectSection(section){
    if(!S.project||!document.getElementById('project-panel-'+section))return;
    const origin=section==='sources'?window.MarketingOverlay?.sourceOrigin?.():null;
    if(S.section===section&&location.hash.endsWith('/'+section)&&!origin)return;
    // The return target belongs to this source visit, not to the project globally.
    const view=S.project.kind==='marketing'?'campaigns':'projects';
    if(origin)go(view,S.project.id,section,undefined,{sourceReturn:origin});else go(view,S.project.id,section);
  }
  function projectSection(el){openProjectSection(el.dataset.section);}
  function editWritingNotes(){
    if(S.project?.kind!=='marketing')return;
    S.writingRevisionFor=S.project.id;S.focusWritingNotes=true;
    if(S.section==='task'){showProjectSection('task');return;}
    openProjectSection('task');
  }
  function editProjectBrief(){openProjectSection('task');const f=document.getElementById('projectBriefEditor');if(f){f.open=true;f.scrollIntoView({block:'start',behavior:'smooth'});document.querySelector('#projectBrief [name=topic]')?.focus({preventScroll:true});}}
  function focusDraft(){
    openProjectSection('results');
    document.getElementById('projectDraftEditor')?.scrollIntoView({block:'start',behavior:'instant'});
    if(ProjectUI.draftMode==='edit')ProjectUI.draftEditor?.focus();
    else document.getElementById('projectDraftReading')?.focus({preventScroll:true});
  }
  function rememberDraftDetails(el){
    if(!el.isConnected)return;
    if(el.id==='projectDraftAssist')ProjectUI.assistOpen=el.open;
    if(el.id==='projectDraftContents')ProjectUI.outlineOpen=el.open;
  }
  function setDraftMode(el,full=false){
    const mode=typeof el==='string'?el:el.dataset.mode;
    if(!['read','edit'].includes(mode))return;
    if(mode==='edit'&&!full&&currentSceneDocument()){openSceneEditor();return;}
    ProjectUI.draftMode=mode;
    if(document.getElementById('projectDraftRelease'))document.getElementById('projectDraftRelease').open=false;
    syncDraftView();
    syncDraftOutline();updateMarketingFlow();
    if(mode==='edit'&&S.section==='results')ProjectUI.draftEditor?.focus();
  }
  function syncDraftView(){
    const editor=document.getElementById('projectDraftRichHost'),reading=document.getElementById('projectDraftReading');
    if(!editor||!reading)return;
    const editing=ProjectUI.draftMode==='edit';
    editor.hidden=!editing;
    reading.hidden=editing;
    document.querySelectorAll('.manuscript-view-switch [data-mode]').forEach(button=>{
      button.setAttribute('aria-pressed',String(button.dataset.mode===ProjectUI.draftMode));
    });
    syncDraftStatus();
  }
  function syncDraftStatus(){
    const draft=document.getElementById('projectDraft'),status=document.getElementById('projectDraftStatus');
    if(!draft||!status||!S.project)return;
    const p=S.project,hasDraft=Boolean(draft.value.trim());
    const used=new Set(p.draft_asset_ids||[]);
    const scoped=explicitDraftScope(p),missingRefs=scoped&&!used.size;
    const ready=Boolean(p.draft_review)&&!p.draft_outdated&&!(p.items||[]).some(i=>(!scoped||used.has(i.asset_id))&&materialPending(i));
    status.textContent=S.dirty?'有修改待保存':!hasDraft?'尚无稿件':p.draft_outdated?'引用待核对':missingRefs?'暂无引用':ready?'已审核':'待审核';
    status.dataset.tone=S.dirty?'dirty':ready?'approved':'neutral';
    document.getElementById('projectDraftSave').hidden=ProjectUI.draftMode!=='edit'&&!S.dirty;
    document.getElementById('projectDraftRelease').hidden=!hasDraft;
    const approved=ready&&!S.dirty;
    const actions=document.getElementById('projectDraftReleaseActions');
    const key=approved?'approved':p.draft_outdated||missingRefs?'references':'review';
    if(actions.dataset.state!==key){
      actions.dataset.state=key;
      actions.innerHTML=(approved?btn('导出已审核稿','exportProject',{mode:'approved'},'sm ghost'):
        key==='references'?btn('核对当前稿引用','openDraftReferenceReview',{},'sm ghost'):btn('审核稿件','approveProject',{},'sm ghost'))+
        btn('导出审阅稿','exportProject',{mode:'review'},'sm ghost');
    }
  }
  function draftDisplayLabel(p,id){
    return p.draft_display_labels?p.draft_display_labels[id]:p.draft_generation?.source_labels?.[id];
  }
  function readableDraftMarkers(text,p){
    if(!text)return '';
    const idsByLabel=new Map(Object.entries(p?.draft_generation?.source_labels||{}).map(([id,label])=>[label,id]));
    return String(text).replace(/\[(S[1-9]\d*)\]/g,(_,label)=>{
      const id=idsByLabel.get(label),display=id&&draftDisplayLabel(p,id);
      return display?'出处 '+display.slice(1):id?'旧出处':'未识别的出处';
    });
  }
  function currentSceneDocument(){
    return S.project?.kind==='marketing'?MarketingScenes.split(document.getElementById('projectDraft')?.value,S.project.brief?.marketing_task==='channel'?S.project.brief.channels:undefined):null;
  }
  function selectedDraftScene(document){
    let saved='';try{saved=sessionStorage.getItem('bookworld.draft-scene:'+S.project.id)||'';}catch(_){}
    const key=ProjectUI.draftScene||saved;
    const part=document.parts.find(p=>p.key===key)||document.parts[0];ProjectUI.draftScene=part.key;return part;
  }
  function selectDraftScene(el){
    const parsed=currentSceneDocument();if(!parsed?.parts.some(p=>p.key===el.dataset.scene))return;
    ProjectUI.draftScene=el.dataset.scene;
    try{sessionStorage.setItem('bookworld.draft-scene:'+S.project.id,ProjectUI.draftScene);}catch(_){}
    closeMaterialDetail();syncDraftOutline();
    document.querySelector('#projectSceneViews [aria-pressed="true"]')?.focus({preventScroll:true});
  }
  const CHANNEL_VIEWS={小红书:['发布正文','配图提示词'],达人讲书:['讲书稿','讲述提示']};
  function channelDelivery(part){
    const content=MarketingScenes.cleanPart(part,Object.values(S.project.draft_generation?.source_labels||{}));
    const end=content.indexOf('\n');
    if(end<0)return null;
    const parts=MarketingScenes.deliveryParts(part.key,content.slice(end+1));
    return parts?{...parts,title:content.slice(0,end),labels:CHANNEL_VIEWS[part.key]}:null;
  }
  function channelViewKey(part){return 'bookworld.draft-delivery:'+S.project.id+':'+part.key;}
  function channelView(part){try{return sessionStorage.getItem(channelViewKey(part))==='support'?'support':'main';}catch(_){return 'main';}}
  function selectChannelDelivery(el){
    const parsed=currentSceneDocument();if(!parsed)return;
    const part=selectedDraftScene(parsed),view=el.dataset.delivery;
    if(!channelDelivery(part)||!['main','support'].includes(view))return;
    try{sessionStorage.setItem(channelViewKey(part),view);}catch(_){}
    syncDraftOutline();
    document.querySelector('#projectSceneViews [data-delivery="'+view+'"]')?.focus({preventScroll:true});
  }
  async function copyDraftScene(el){
    const parsed=currentSceneDocument();if(!parsed)return;
    const part=selectedDraftScene(parsed),delivery=channelDelivery(part);
    const content=MarketingScenes.cleanPart(part,Object.values(S.project.draft_generation?.source_labels||{})).replace(/^#\s+/,'');
    let text=content,label=MarketingScenes.label(part.key);
    if(part.key==='短视频'){text=VideoScript.narration(content)||content;label='口播稿';}
    if(delivery){
      const index=el?.dataset.card;
      if(index!==undefined){text=MarketingScenes.pictureCards(delivery.support)[Number(index)]?.prompt;label='生图提示词';}
      else if(channelView(part)==='support'){text=delivery.support;label=delivery.labels[1];}
      else{text=MarketingScenes.deliveryCopy(part.key,'# '+content);label=delivery.labels[0];}
    }
    if(!text)return;
    try{await navigator.clipboard.writeText(text);toast('已复制'+label);}catch(_){toast('复制失败，请在稿件中选择文本复制',true);}
  }
  function openSceneEditor(full=false){
    const parsed=currentSceneDocument(),p=S.project;if(!parsed||!p)return;
    const part=selectedDraftScene(parsed),source=document.getElementById('projectDraft').value;
    const clean=MarketingScenes.cleanPart(part,Object.values(p.draft_generation?.source_labels||{}));
    const firstBreak=clean.indexOf('\n'),title=(firstBreak<0?clean:clean.slice(0,firstBreak)).replace(/^#\s+/,''),body=firstBreak<0?'':clean.slice(firstBreak+1).trim();
    const videoEdit=part.key==='短视频'?VideoScript.prepareEdit(body):null,videoOutline=!full&&videoEdit?VideoScript.prepareOutlineEdit(body):null;
    const delivery=channelDelivery(part),view=delivery?channelView(part):null,editBody=delivery?delivery[view]:videoEdit?videoEdit.body:body;
    ProjectUI.sceneEdit={project:p.id,hash:location.hash,source,part,title,body,editBody,videoEdit,videoOutline,delivery,view};
    const editor=videoOutline?videoOutline.map((voice,i)=>'<label class="studio-field"><span>第 '+(i+1)+' 段</span><textarea name="voiceover" rows="3" required>'+e(voice.text)+'</textarea></label>').join('')+'<details class="video-outline-more"><summary>更多编辑方式</summary><button type="button" class="btn ghost sm" onclick="Studio.editFullScene(this.form)">编辑完整制作稿</button></details>':(videoEdit?'<p class="muted" id="videoEditHint">修改镜头中的口播，配音稿同步更新。</p>':'')+'<label class="studio-field"><span>正文</span><textarea name="body" rows="16" required'+(videoEdit?' aria-describedby="videoEditHint"':'')+'>'+e(editBody)+'</textarea></label>';
    const editLabel=delivery?delivery.labels[view==='main'?0:1]:videoOutline?'口播稿':MarketingScenes.label(part.key);
    const titleField=view==='support'?'<input type="hidden" name="title" value="'+e(title)+'">':'<label class="studio-field"><span>标题</span><input name="title" required maxlength="300" value="'+e(title)+'"></label>';
    openModal(modalX()+'<h2>编辑'+e(editLabel)+'</h2><form id="marketingSceneEditor" onsubmit="event.preventDefault();Studio.applySceneEdits(this)">'+titleField+editor+'<div class="modal-actions"><button type="button" class="btn ghost" onclick="closeModal()">取消</button><button type="submit" class="btn primary">完成修改</button></div></form>',true);
    document.querySelector('#marketingSceneEditor [name=title]')?.focus();
  }
  function applySceneEdits(form){
    const edit=ProjectUI.sceneEdit,draft=document.getElementById('projectDraft');
    if(!edit||!draft||S.project?.id!==edit.project||location.hash!==edit.hash||draft.value!==edit.source){toast('稿件已有变化，请重新打开编辑。',true);return;}
    const data=new FormData(form),fields=Object.fromEntries(data),title=String(fields.title||'').trim(),editBody=edit.videoOutline?VideoScript.finishOutlineEdit(edit.body,data.getAll('voiceover')):String(fields.body||'').trim();
    if(!title||!editBody||/[\r\n]/.test(title)){toast('请填写标题和正文。',true);return;}
    if(title!==edit.title||editBody.trim()!==(edit.videoOutline?edit.body:edit.editBody).trim()){
      const delivery=edit.delivery;
      const body=delivery?'#### '+delivery.names[0]+'\n\n'+(edit.view==='main'?editBody:delivery.main)+'\n\n#### '+delivery.names[1]+'\n\n'+(edit.view==='support'?editBody:delivery.support):edit.videoOutline?editBody:edit.videoEdit?VideoScript.finishEdit(editBody,edit.videoEdit.voiceIndex,edit.videoEdit.sectionCount):editBody;
      if(body===null){toast('请保留各部分小标题，以及每个镜头的口播与剪辑栏目，以便同步配音稿。修改内容仍在，可以继续编辑。',true);return;}
      if(delivery&&!MarketingScenes.deliveryParts(edit.part.key,body)){toast('请保留两部分的结构，当前修改仍可继续编辑。',true);return;}
      const header=edit.part.raw.split('\n')[0],known=new Set(Object.values(S.project.draft_generation?.source_labels||{}));
      const labels=Array.from(header.matchAll(/\[(S[1-9]\d*)\]/g),x=>x[1]).filter(x=>known.has(x));
      const replacement='### '+edit.part.key+'：'+title+(labels.length?' '+labels.map(x=>'['+x+']').join(' '):'')+'\n'+body+'\n\n';
      const candidate=edit.source.slice(0,edit.part.start)+replacement+edit.source.slice(edit.part.end);
      const channels=S.project.brief?.marketing_task==='channel'?S.project.brief.channels:undefined;
      const before=MarketingScenes.split(edit.source,channels),after=MarketingScenes.split(candidate,channels);
      const updated=after?.parts.find(x=>x.key===edit.part.key);
      if(!before||!after||updated?.raw!==replacement||before.parts.length!==after.parts.length||before.parts.some(x=>x.key!==edit.part.key&&after.parts.find(y=>y.key===x.key)?.raw!==x.raw)){
        toast('正文中的小标题与原稿分段冲突，请换一个小标题后再保存。',true);return;
      }
      draft.value=candidate;
      markDirty();
    }
    ProjectUI.sceneEdit=null;closeModal();ProjectUI.draftMode='read';syncDraftView();syncDraftOutline();
  }
  function editFullScene(form){applySceneEdits(form);if(!ProjectUI.sceneEdit)openSceneEditor(true);}
  function draftSliceView(part,references){
    const view=ManuscriptReader.build(part.raw,references);
    return {html:view.html.replace(/data-draft-heading="(\d+)"/g,(_,n)=>'data-draft-heading="'+(Number(n)+part.start)+'"'),sections:view.sections.map(x=>({...x,at:x.at+part.start}))};
  }
  function pictureDeliveryView(support){
    const cards=MarketingScenes.pictureCards(support);
    if(!cards.length||cards.some(card=>!card))return ManuscriptReader.build(support,new Map());
    const html=cards.map((card,index)=>'<section class="marketing-picture-card"><div class="marketing-picture-heading"><h3>'+e(card.title)+'</h3>'+btn('复制生图提示词','copyDraftScene',{card:index},'sm ghost')+'</div>'+
      ManuscriptReader.build(card.details,new Map()).html+'<details><summary>查看生图提示词</summary><p>'+e(card.prompt)+'</p></details></section>').join('');
    return {html,sections:[]};
  }
  function syncDraftOutline(){
    const draft=document.getElementById('projectDraft'),outline=document.getElementById('projectDraftOutline'),count=document.getElementById('projectDraftCount'),reading=document.getElementById('projectDraftReading');if(!draft||!outline||!reading)return;
    const p=S.project,references=new Map(),labels=p.draft_generation?.source_labels||{};
    if(S.section==='results')loadNameChecks(document.getElementById('projectDraftNameChecks'),p);
    const items=new Map((p.items||[]).map(i=>[i.asset_id,i])),cited=new Set(p.draft_asset_ids||[]);
    const issues=new Set((p.draft_reference_issues||[]).map(i=>i.asset_id));
    for(const [id,label] of Object.entries(labels)){
      const item=items.get(id);
      const warning=item?.status==='not_fit'?'已取消采用':!cited.has(id)?'未确认引用':
        issues.has(id)||!draftReferenceEligible(item)?'需核对':'';
      const displayLabel=cited.has(id)&&item?.status==='adopted'?draftDisplayLabel(p,id):null;
      references.set(label,{id,title:item?.snapshot?.title||'材料',warning,displayLabel});
    }
    const host=document.getElementById('projectDraftRichHost');
    if(ProjectUI.draftEditorHost!==host){
      ProjectUI.draftEditorHost=host;
      ProjectUI.draftEditor=host?ManuscriptEditor.mount(host,draft,references,markDirty):null;
    }else ProjectUI.draftEditor?.sync(references);
    let documentView=ManuscriptReader.build(draft.value,references),shared='';
    const sceneDocument=currentSceneDocument(),sceneHost=document.getElementById('projectSceneViews'),editing=ProjectUI.draftMode==='edit';
    const videoCurrent=videoBrief(p)&&(!sceneDocument||selectedDraftScene(sceneDocument).key==='短视频');
    const editButton=document.querySelector('.manuscript-view-switch [data-mode="edit"]');if(editButton)editButton.textContent=videoCurrent?'编辑口播稿':sceneDocument?'编辑'+sceneWorkflow(p).noun:'编辑';
    if(sceneHost){
      sceneHost.hidden=!sceneDocument;
      if(sceneDocument){
        const part=selectedDraftScene(sceneDocument);
        const delivery=channelDelivery(part),view=delivery?channelView(part):'main';
        if(part.key==='短视频'&&sceneDocument.parts.length===1&&!editing)sceneHost.hidden=true;
        if(delivery&&editButton)editButton.textContent='编辑'+delivery.labels[view==='main'?0:1];
        const deliverTabs=delivery?'<div class="studio-tabs" role="group" aria-label="选择稿件内容">'+['main','support'].map((name,index)=>'<button type="button" class="'+(name===view?'on':'')+'" aria-pressed="'+(name===view)+'" data-delivery="'+name+'" onclick="Studio.selectChannelDelivery(this)">'+e(delivery.labels[index])+'</button>').join('')+'</div>':'';
        const copyLabel=delivery?delivery.labels[view==='main'?0:1]:sceneDocument.parts.length===1?sceneWorkflow(p).noun:'本场景';
        const hint=delivery?(view==='main'?(part.key==='小红书'?'复制这份文案到发布页。':'复制逐字稿，用于试讲或提词。'):MarketingScenes.nextStep([part.key])):MarketingScenes.nextStep([part.key]);
        sceneHost.innerHTML=editing?'<p>正在核对原稿中的引用。完成后切回阅读。</p>':
          (sceneDocument.parts.length>1?'<div class="studio-tabs" role="group" aria-label="选择成果场景">'+sceneDocument.parts.map(x=>'<button type="button" class="'+(x.key===part.key?'on':'')+'" aria-pressed="'+(x.key===part.key)+'" data-scene="'+e(x.key)+'" onclick="Studio.selectDraftScene(this)">'+e(MarketingScenes.label(x.key))+'</button>').join('')+'</div>':'')+
          '<div class="manuscript-scene-bar">'+deliverTabs+btn('复制'+copyLabel,'copyDraftScene',{},'sm ghost')+'</div>'+(part.key==='短视频'?'':'<p class="muted">'+e(hint)+'</p>');
        if(!editing){
          const content=MarketingScenes.cleanPart(part,Object.values(labels));
          const video=part.key==='短视频'?VideoScript.render(content,'draft:'+p.id):'';
          if(video)documentView={html:video,sections:[]};
          else if(delivery&&view==='support'&&part.key==='小红书')documentView=pictureDeliveryView(delivery.support);
          else documentView=ManuscriptReader.build(delivery?(view==='main'?delivery.title+'\n\n'+delivery.main:delivery.support):content,new Map());
          shared='';
        }
      }
    }
    const sources=document.getElementById('marketingSourceContext');if(sources){const context=(sceneDocument?.context||[]).filter(x=>String(x.raw||'').trim());sources.hidden=!context.length;sources.innerHTML=context.map(x=>draftSliceView(x,references).html).join('');}
    const active=outline.querySelector('[aria-current="location"]')?.dataset.offset;
    reading.innerHTML=(documentView.html?documentView.html+shared:'<div class="manuscript-empty"><h3>还没有工作稿</h3><p>可直接编写，也可先生成建议并选择应用。</p>'+btn('开始编写','setDraftMode',{mode:'edit'},'primary')+'</div>');
    if(videoCurrent&&!editing){
      const single=(p.brief.channels||[]).length===1;
      reading.insertAdjacentHTML('beforeend','<div class="video-outline-next"'+(single?' data-video-records-row'+(S.assistProgress?.videoPromptCount?'':' hidden'):'')+'><div><button type="button" class="btn ghost" data-video-prompts-records onclick="VideoPrompts.showRecords()"'+(S.assistProgress?.videoPromptCount?'':' hidden')+'>查看已生成内容</button>'+(single||!draft.value.trim()?'':'<button type="button" class="btn primary" data-video-prompts-start onclick="VideoPrompts.open()">确认内容，选择呈现方式</button>')+'</div></div>');
    }
    outline.innerHTML=documentView.sections.length?documentView.sections.map(x=>'<button type="button" data-offset="'+x.at+'" onclick="Studio.jumpDraft(this)"'+(String(x.at)===active?' aria-current="location"':'')+'>'+e(x.title)+'</button>').join(''):'<p>暂无章节</p>';
    if(count){const part=sceneDocument?selectedDraftScene(sceneDocument):null;count.hidden=!editing&&(videoCurrent||!!(part&&channelDelivery(part)));count.textContent=part&&!editing?MarketingScenes.label(part.key)+' · '+MarketingScenes.cleanPart(part,Object.values(labels)).length.toLocaleString('zh-CN')+' 字符':draft.value.length.toLocaleString('zh-CN')+' 字符';}
  }
  function jumpDraft(el){
    const d=document.getElementById('projectDraft');if(!d)return;
    const offset=Math.min(d.value.length,Number(el.dataset.offset)||0);
    el.closest('nav').querySelector('[aria-current="location"]')?.removeAttribute('aria-current');
    el.setAttribute('aria-current','location');
    if(ProjectUI.draftMode==='read'){
      const target=document.querySelector('#projectDraftReading [data-draft-heading="'+offset+'"]');
      if(target){target.focus({preventScroll:true});target.scrollIntoView({block:'start',behavior:'instant'});}
      return;
    }
    ProjectUI.draftEditor?.focusOffset(offset);
  }
  function draftReferenceEligible(item){
    return item?.status==='adopted'&&!item.stale&&item.evidence_valid&&
      !['missing','rejected'].includes(item.current_status)&&!(item.quality_issues||[]).length;
  }
  function nameCheckForm(check){
    const note=check.review?.note||'',name=check.name||'',manual=!name;
    const heading=manual?'记录本段名称所指':(check.review?.cat==='ignore'?'本段已略过 · ':note?'已核对 · ':'核对名称所指 · ')+name;
    return '<details class="source-name-check"><summary>'+e(heading)+'</summary>'+
      '<form data-code="'+e(check.code)+'" data-anchor="'+e(check.anchor)+'" data-revision="'+e(check.revision||'')+'" onsubmit="event.preventDefault();Studio.saveNameCheck(this)">'+
      (manual?'<label>原文里的名称<input name="name" required maxlength="64" placeholder="例如 宣宗"></label>':'<input type="hidden" name="name" value="'+e(name)+'">')+
      (check.quote?'<blockquote>'+e(check.quote)+'</blockquote>':'')+
      '<label>在这一段里指什么<textarea name="note" required maxlength="240" rows="2" placeholder="写下你从这段原文核对到的所指">'+e(note)+'</textarea></label>'+
      '<div class="card-actions">'+btn('查看原文 ↗','materialSource',{code:check.code,anchor:check.anchor},'sm ghost')+
      '<button type="submit" class="btn sm ghost">保存核对说明</button></div><p role="status" data-name-status></p></form></details>';
  }
  async function loadNameChecks(host,p,asset=''){
    if(!host)return;
    const draft=document.getElementById('projectDraft');
    const currentDraft=()=>!draft||draft.value===(p.draft||'');
    if(!p.draft||(p.draft_asset_ids||[]).length===0||!currentDraft()){
      host.hidden=true;delete host.dataset.checkKey;return;
    }
    const key=[p.id,p.revision,asset].join(':');
    if(host.dataset.checkKey===key)return;
    host.hidden=true;
    host.dataset.checkKey=key;
    try{
      const result=await request('/api/projects/'+p.id+'/name-checks'+(asset?'?'+new URLSearchParams({asset}):''));
      if(!host.isConnected||host.dataset.checkKey!==key||S.project?.id!==p.id||S.project?.revision!==result.revision||!currentDraft())return;
      const rows=result.items||[];
      host.hidden=!rows.length;
      if(!rows.length)return;
      if(asset){host.innerHTML='<h3>这份稿件用到的名称</h3>'+rows.map(nameCheckForm).join('');return;}
      const count=rows.filter(row=>!row.review?.note&&row.review?.cat!=='ignore').length;
      host.innerHTML='<details class="source-name-check"><summary>'+e(count?count+' 处名称可核对':'查看名称核对记录')+'</summary><ul>'+rows.map(row=>'<li>'+btn(e(row.name)+' · '+(row.review?.cat==='ignore'?'已略过':row.review?.note?'已核对':'看出处'),'openMaterialDetail',{id:row.asset_id},'sm ghost')+'</li>').join('')+'</ul></details>';
    }catch(_){if(host.dataset.checkKey===key)delete host.dataset.checkKey;}
  }
  async function saveNameCheck(form){
    const button=form.querySelector('button[type=submit]'),status=form.querySelector('[data-name-status]');
    const fields=new FormData(form),name=String(fields.get('name')||'').trim(),note=String(fields.get('note')||'').trim();
    if(!name||!note)return;
    const {code,anchor}=form.dataset;
    button.disabled=true;
    try{
      const found=form.dataset.revision|| (await request('/api/book/name-check?'+new URLSearchParams({code,anchor,name}))).revision;
      if(!form.isConnected)return;
      await request('/api/book/name-check',{code,anchor,name,note,revision:found});
      if(!form.isConnected)return;
      form.closest('details').querySelector('summary').textContent='已核对 · '+name;
      status.textContent='已保存，供下次使用同一段原文时查看。';
      const summary=document.getElementById('projectDraftNameChecks');
      if(summary){delete summary.dataset.checkKey;if(S.section==='results')loadNameChecks(summary,S.project);}
    }catch(error){if(form.isConnected)status.textContent=error.message||'暂时保存不了，请重试。';}
    finally{button.disabled=false;}
  }
  function openDraftReferenceReview(){
    const p=S.project,draft=document.getElementById('projectDraft');
    if(!p||!draft?.value.trim()){toast('有稿件正文后再核对引用',true);return;}
    if(S.saving){toast('正在保存，请稍后打开核对引用。');return;}
    if(p.kind!=='marketing')closeMaterialDetail();
    const cited=new Set(p.draft_asset_ids||[]);
    const issues=p.draft_reference_issues||[],adopted=(p.items||[]).filter(i=>i.status==='adopted');
    const issueRows=issues.map(i=>'<li>'+(i.title?'<strong>'+e(readableDraftMarkers(i.title,p))+'</strong> ':'')+e(readableDraftMarkers(i.reason,p))+'</li>').join('');
    const choices=adopted.map(i=>{
      const existing=cited.has(i.asset_id),eligible=draftReferenceEligible(i);
      return '<label class="draft-reference-choice"><input type="checkbox" name="asset_ids" value="'+e(i.asset_id)+'"'+
        (eligible&&existing?' checked':'')+(!eligible?' disabled':'')+'><span><strong>'+e(projectMaterialTitle(i.snapshot))+'</strong><small data-reference-state></small></span></label>';
    }).join('');
    openModal(modalX()+'<form id="draftReferenceReview" data-project="'+e(p.id)+'" data-revision="'+e(p.revision)+'" onsubmit="event.preventDefault();Studio.submitDraftReferences(this)" onchange="Studio.updateDraftReferenceReview(this,event.target)">'+
      '<h2>核对当前稿引用</h2><p>勾选并保存会更新本稿的出处清单。要在正文使用新材料，请先编辑正文，再勾选对应出处。</p>'+
      (issueRows?'<div class="draft-reference-issues"><strong>需要处理</strong><ul>'+issueRows+'</ul></div>':'')+
      '<fieldset class="draft-reference-choices"><legend>本稿引用材料</legend>'+(choices||'<p>项目暂无采用材料。</p>')+'</fieldset>'+
      '<div class="draft-reference-findings" data-findings aria-live="polite"></div>'+
      '<p class="draft-reference-save-help">核对完正文和出处后，请勾选下方确认项，再点「保存正文与引用」。</p>'+
      '<label class="draft-reference-attest"><input type="checkbox" name="reviewed">我已逐段核对，正文与所选出处一致，被排除材料的相关表述已经处理。</label>'+
      '<p class="draft-reference-error" data-error role="alert" hidden></p>'+
      '<div class="modal-actions">'+btn('去项目材料','goDraftReferenceMaterials',{},'ghost')+btn('编辑正文','editDraftReferenceText',{},'ghost')+
      '<button type="submit" class="btn primary" disabled>保存正文与引用</button></div></form>');
    updateDraftReferenceReview(document.getElementById('draftReferenceReview'));
  }
  function draftReferenceFindings(p,body,selected){
    const labels=p.draft_generation?.source_labels||{},items=new Map((p.items||[]).map(i=>[i.asset_id,i]));
    const byLabel=new Map(Object.entries(labels).map(([id,label])=>[label,id]));
    const markers=[...new Set(Array.from(body.matchAll(/\[(S[1-9]\d*)\]/g),match=>match[1]))]
      .map(label=>({token:'['+label+']',id:byLabel.get(label)})).filter(m=>!selected.has(m.id))
      .map(m=>({...m,title:items.get(m.id)?.snapshot?.title||'无对应材料'}));
    const titles=(p.draft_asset_ids||[]).filter(id=>!selected.has(id)).map(id=>items.get(id)?.snapshot?.title||'')
      .filter((title,i,rows)=>title.length>=2&&body.includes(title)&&rows.indexOf(title)===i);
    return {markers,titles};
  }
  function describeDraftReferenceChoice(p,draft,input,cited){
    const id=input.value,existing=cited.has(id);
    if(input.disabled)return existing?'本次不引用 · 来源待处理':'来源待处理，暂不能登记';
    if(!input.checked)return existing?'本次不引用 · 待保存':'已采用，本次未引用';
    if(!existing)return '待加入出处';
    const label=draftDisplayLabel(p,id),marker=p.draft_generation?.source_labels?.[id];
    const prefix=label?'出处 '+label.slice(1)+' · ':'';
    const raw=marker&&draft.includes('['+marker+']')?' · 正文已标注出处':' · 正文未标注出处';
    return prefix+'已登记'+raw;
  }
  function updateDraftReferenceReview(form,changed){
    const p=S.project,draft=document.getElementById('projectDraft');
    if(!p||!draft||!form||form.dataset.project!==p.id)return;
    if(changed?.name==='asset_ids')form.elements.namedItem('reviewed').checked=false;
    const fields=new FormData(form),selected=new Set(fields.getAll('asset_ids'));
    const cited=new Set(p.draft_asset_ids||[]);
    for(const input of form.querySelectorAll('input[name=asset_ids]')){
      input.closest('label').querySelector('[data-reference-state]').textContent=describeDraftReferenceChoice(p,draft.value,input,cited);
    }
    const {markers,titles}=draftReferenceFindings(p,draft.value,selected);
    const locate=token=>btn('定位正文','editDraftReferenceText',{token},'sm ghost');
    form.querySelector('[data-findings]').innerHTML=
      (markers.length?'<p><strong>先处理正文里仍保留的出处标记</strong></p><ul>'+markers.map(m=>'<li><span>'+e(m.title)+' · '+e(readableDraftMarkers(m.token,p))+'</span>'+locate(m.token)+'</li>').join('')+'</ul>':'')+
      (titles.length?'<p>正文仍提到以下标题，请核实相关段落是否需要改写。</p><ul>'+titles.map(s=>'<li><span>'+e(s)+'</span>'+locate(s)+'</li>').join('')+'</ul>':'')+
      (!selected.size?'<p>可以保存为暂不引用材料。稿件审核至少需要一条有效引用。</p>':'');
    form.querySelector('[type=submit]').disabled=Boolean(S.saving)||!fields.get('reviewed')||markers.length>0;
  }
  function editDraftReferenceText(el){
    closeModal();setDraftMode('edit',true);focusDraft();
    const draft=document.getElementById('projectDraft'),token=el.dataset.token;
    if(token){const offset=draft.value.indexOf(token);if(offset>=0)ProjectUI.draftEditor?.focusOffset(offset,token.length);}
  }
  function goDraftReferenceMaterials(){
    closeModal();openProjectSection('materials');showMaterialMode('selected');
  }
  async function submitDraftReferences(form){
    const p=S.project,draft=document.getElementById('projectDraft'),brief=document.getElementById('projectBrief');
    if(!p||!draft||!brief||form.dataset.project!==p.id||S.saving)return;
    const error=form.querySelector('[data-error]');
    const fields=new FormData(form),selected=new Set(fields.getAll('asset_ids')),text=draft.value;
    if(!fields.get('reviewed')||draftReferenceFindings(p,text,selected).markers.length)return updateDraftReferenceReview(form);
    if(Number(form.dataset.revision)!==p.revision){error.hidden=false;error.textContent='项目已更新，请关闭后重新打开核对引用。';return;}
    form.querySelector('[type=submit]').disabled=true;error.hidden=true;
    const pending=(async()=>{
      const d=await request('/api/projects/'+p.id,{action:'reconcile_draft_refs',revision:p.revision,draft:text,asset_ids:[...selected]});
      if(S.project?.id!==p.id||document.getElementById('projectDraft')!==draft)return;
      S.project=d.project;S.draftAssetIds=null;S.draftRebuilt=false;
      S.dirty=projectFieldsChanged(S.project,brief,draft)||Object.keys(ProjectUI.notes).length>0;
      if(form.isConnected)closeModal();
      document.getElementById('projectSaveState').textContent=S.dirty?'有修改待保存':'已保存';
      const next=document.getElementById('projectNextStep');if(next)next.outerHTML=projectNext(S.project);updateMarketingFlow();
      syncProjectIntent();refreshProjectLabels();renderMaterialRows();syncDraftOutline();
      if(window.ProjectAssist)ProjectAssist.projectSaved(S.project,S.dirty);
      if(window.ProjectHistory)ProjectHistory.mount(document.getElementById('projectHistory'),S.project);
      toast(S.dirty?'已保存提交时的正文和引用，其余修改待保存':'已保存当前稿正文与引用');
    })();
    S.saving=pending;
    try{await pending;}catch(err){
      if(form.isConnected){error.hidden=false;error.textContent=readableDraftMarkers(err.message,p);}
      else report(err);
    }finally{
      if(S.saving===pending)S.saving=null;
      if(form.isConnected)updateDraftReferenceReview(form);
    }
  }
  function showMaterialMode(value){
    if(!S.project)return;if(S.project.kind==='marketing'){openProjectSection('materials');return;}const mode=typeof value==='string'?value:value.dataset.mode;if(!['selected','recommended'].includes(mode))return;materialState().mode=mode;
    const selected=document.getElementById('projectSelectedMaterials'),discovery=document.getElementById('projectDiscovery');if(selected)selected.hidden=mode!=='selected';if(discovery)discovery.hidden=mode!=='recommended';
    document.querySelectorAll('.project-material-modes button').forEach(b=>{const on=b.dataset.mode===mode;b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on));});
  }
  function materialPending(it){return it.status==='adopted'&&(it.stale||it.current_status!=='approved'||!it.evidence_valid||(it.quality_issues||[]).length);}
  function projectMaterialTitle(asset,fallback='材料'){
    const a=asset||{};
    if(a.source_type==='graph_relation')return a.title||fallback;
    return S.project?.kind==='marketing'?ProjectAssist.materialTitleText(a,fallback):a.title||fallback;
  }
  function projectMaterialRow(it){
    const a=it.snapshot||{};
    const relation=a.source_type==='graph_relation';
    const type=relation?(a.kind_label||'关系材料'):(K[a.kind]||'内容成果');
    const note=ProjectUI.notes[it.asset_id]===undefined?it.note:ProjectUI.notes[it.asset_id];
    const preview=relation?(a.evidence||[]).find(ev=>ev.quote)?.quote||a.text:note||a.text;
    const pending=materialPending(it)||(relation&&it.status==='selected'&&(it.stale||it.current_status!=='approved'||!it.evidence_valid));
    const source=[a.book||a.code,type,relation&&(a.relation_basis_label||a.origin)].filter(Boolean).join(' · ');
    return '<button type="button" class="project-material-row" data-id="'+e(it.asset_id)+'" onclick="Studio.openMaterialDetail(this)">'+
      '<span class="project-material-row-content"><b>'+e(projectMaterialTitle(a,type))+'</b><small>'+e(source)+'</small><span>'+e(clip(preview||'待补充本次用途',90))+'</span></span>'+
      '<span class="project-material-row-state">'+badge(it.status)+(pending?'<small class="material-needs-check">待核对</small>':it.status==='adopted'?'<small>内容已确认</small>':'')+'</span><span class="project-material-row-open">查看与处理 ↗</span></button>';
  }
  function renderMaterialRows(){
    const host=document.getElementById('projectMaterialRows');if(!host||!S.project)return;const ui=materialState(),query=ui.q.toLocaleLowerCase();
    const items=(S.project.items||[]).filter(it=>{const a=it.snapshot||{};return (!ui.filter||(ui.filter==='pending'?materialPending(it):it.status===ui.filter))&&(!query||[a.title,a.text,a.book,it.note,ProjectUI.notes[it.asset_id]].join(' ').toLocaleLowerCase().includes(query));});
    const limit=MATERIAL_PAGE_SIZE;if(ui.offset>=items.length)ui.offset=Math.max(0,Math.ceil(items.length/limit)-1)*limit;
    host.innerHTML=items.length?'<div class="project-material-list">'+items.slice(ui.offset,ui.offset+limit).map(projectMaterialRow).join('')+'</div><div class="project-material-pagination"><span>'+items.length+' 条材料 · 第 '+(Math.floor(ui.offset/limit)+1)+' / '+Math.ceil(items.length/limit)+' 页</span><div><button class="btn sm ghost" data-step="-1" onclick="Studio.materialPage(this)"'+(!ui.offset?' disabled':'')+'>上一页</button><button class="btn sm ghost" data-step="1" onclick="Studio.materialPage(this)"'+(ui.offset+limit>=items.length?' disabled':'')+'>下一页</button></div></div>':empty(ui.q||ui.filter?'没有符合条件的材料':'还没有收集材料',ui.q||ui.filter?'调整关键词或材料状态后再试。':'按任务发现材料，或从内容成果中选取。',ui.q||ui.filter?'':btn('发现材料','showMaterialMode',{mode:'recommended'},'primary'));
  }
  function filterMaterials(el){const ui=materialState();if(el.tagName==='SELECT')ui.filter=el.value;else ui.q=el.value;ui.offset=0;renderMaterialRows();}
  function materialPage(el){const ui=materialState();ui.offset=Math.max(0,ui.offset+Number(el.dataset.step)*MATERIAL_PAGE_SIZE);renderMaterialRows();}
  function rememberEditorialRelationDetail(project,assetId){
    const current=parse();
    if(project?.kind!=='editorial'||current.view!=='projects'||current.arg!==project.id)return;
    const visit={...history.state};
    if(assetId)visit.__editorialRelationDetail={projectId:project.id,assetId,section:S.section};
    else if(visit.__editorialRelationDetail)delete visit.__editorialRelationDetail;
    else return;
    history.replaceState(visit,'',location.href);
  }
  function restoreEditorialRelationDetail(project){
    const saved=history.state?.__editorialRelationDetail;
    if(saved?.projectId!==project.id||saved.section!==S.section)return;
    if((project.items||[]).some(item=>item.asset_id===saved.assetId&&item.snapshot?.source_type==='graph_relation')){
      openMaterialDetail({dataset:{id:saved.assetId}});
    }
  }
  function materialDetailDescriptor(id){
    return {type:'project-material',projectId:S.project.id,assetId:id,section:S.section||'materials'};
  }
  function openMaterialDetail(el,rendering,historyOptions={}){
    if(S.project?.kind==='marketing'&&!rendering&&window.MarketingOverlay){
      if(!(S.project.items||[]).some(x=>x.asset_id===el.dataset.id)&&!historyOptions.restore)return;
      MarketingOverlay.open('material:'+el.dataset.id,()=>openMaterialDetail(el,true),clearMaterialDetail,
        {...historyOptions,descriptor:materialDetailDescriptor(el.dataset.id)});return;
    }
    const p=S.project,it=p&&(p.items||[]).find(x=>x.asset_id===el.dataset.id),root=document.getElementById('projectSidePanelRoot');if(!p||!root)return;
    const previous=ProjectUI.detail;
    const returnTo=el.matches?.('.draft-citation,.project-material-row')?el:previous?.id===el.dataset.id?previous.returnTo:null;
    ProjectUI.detail={project:p.id,id:el.dataset.id,section:S.section,returnTo};
    const closeLabel=p.kind==='marketing'&&S.section==='review'?'← 返回交付前检查':'关闭 ×';
    if(!it){
      root.innerHTML='<button class="project-panel-backdrop" type="button" aria-label="关闭材料详情" onclick="Studio.closeMaterialDetail()"></button><aside class="project-side-panel" role="dialog" aria-modal="true" aria-labelledby="projectMaterialTitle"><div class="project-side-panel-head"><span>项目材料</span>'+btn(closeLabel,'closeMaterialDetail',{},'sm ghost')+'</div><div class="project-side-panel-body"><h2 id="projectMaterialTitle">这条材料已移出项目</h2><p>返回当前页面，查看现有素材与稿件引用。</p></div></aside>';
      root.querySelector('.project-side-panel-head button').focus({preventScroll:true});return;
    }
    const a=it.snapshot||{},note=ProjectUI.notes[it.asset_id]===undefined?it.note:ProjectUI.notes[it.asset_id];
    const replacement=it.replacement,archived=it.archived===true;
    const relation=a.source_type==='graph_relation';
    const type=relation?(a.kind_label||'关系材料'):(K[a.kind]||'内容成果');
    if(p.kind==='editorial')rememberEditorialRelationDetail(p,relation?it.asset_id:'');
    const unavailable=['missing','rejected'].includes(it.current_status);
    const usable=!unavailable&&!it.stale&&it.evidence_valid&&!(it.quality_issues||[]).length;
    const canConfirm=it.current_status==='review'&&!it.stale&&it.evidence_valid&&!(it.quality_issues||[]).length;
    const checkNames=usable&&it.status==='adopted'&&(p.draft_asset_ids||[]).includes(it.asset_id);
    const confirmAction=canConfirm?btn('确认内容与出处','confirmMaterial',{id:it.asset_id,revision:it.asset_revision},'primary'):'';
    const outsideAngle=p.topic_angle&&!p.topic_angle.asset_ids.includes(it.asset_id);
    const canAddToAngle=outsideAngle&&it.status==='adopted'&&!it.stale&&it.evidence_valid&&
      it.current_status!=='rejected'&&!(it.quality_issues||[]).length;
    const adoptAction=!usable?'':canAddToAngle?btn('加入本次组稿','itemStatus',{id:it.asset_id,status:'adopted'},'ghost'):
      it.status==='adopted'?'':btn('本项目采用','itemStatus',{id:it.asset_id,status:'adopted'},canConfirm?'ghost':'primary');
    const notFitAction=it.status==='not_fit'?'':btn('本项目不采用','itemStatus',{id:it.asset_id,status:'not_fit'},'ghost');
    const canceledRef=it.status==='not_fit'&&(p.draft_asset_ids||[]).includes(it.asset_id);
    const sourceStatus=it.current_status==='missing'?'来源已缺失':it.current_status==='rejected'?'内容已停用':it.stale?'引用版本待更新':'';
    const sourceHelp=archived?'这是本稿采用的已核对版本。':
      replacement?'本稿的旧版出处需处理。请核对正文，再调整稿件引用。':
      it.current_status==='missing'?'原成果已不存在。这里保留项目原引用，请更换素材，并核对稿件中对应的内容与出处。':
      it.current_status==='rejected'?'这条内容已停用，不能用于定稿。请更换素材，并核对稿件中对应的内容与出处。':
      it.stale?'这里显示项目保存的旧引用，不能直接确认。先查看当前成果，再更新引用并重新选择是否采用；已有稿件还需核对对应正文与引用。':
      !it.evidence_valid?'原文出处需要处理，请打开内容成果核对后再确认。':
      relation&&a.relation_basis==='interpretation'?'这条关系是根据原文整理的解释。采用前请核对原文能否支持关系表述。':'';
    const source=[a.book||a.code,relation&&(a.relation_basis_label||a.origin)].filter(Boolean).join(' · ');
    const title=a.kind==='marketing'&&a.marketing_key==='summary'?'图书简介':a.title||'材料详情';
    const body=relation&&a.text===a.title?'':'<div class="project-material-fulltext">'+e(a.text||'')+'</div>';
    const compare=replacement?'<div class="card-actions">'+btn('查看新版简介','detail',{id:replacement.id,queue:'true',preview:'true',material:it.asset_id},'sm ghost')+'</div>':'';
    root.innerHTML='<button class="project-panel-backdrop" type="button" aria-label="关闭材料详情" onclick="Studio.closeMaterialDetail()"></button><aside class="project-side-panel" role="dialog" aria-modal="true" aria-labelledby="projectMaterialTitle"><div class="project-side-panel-head"><span>项目材料 · '+e(type)+'</span>'+btn(closeLabel,'closeMaterialDetail',{},'sm ghost')+'</div><div class="project-side-panel-body"><h2 id="projectMaterialTitle">'+e(title)+'</h2><p class="muted">'+e(source)+'</p><div class="card-actions">'+(sourceStatus?'<span class="studio-badge review">'+e(sourceStatus)+'</span>':badge(it.current_status||a.status))+badge(it.status)+'</div>'+(sourceHelp?'<p class="banner">'+e(sourceHelp)+'</p>':'')+(canConfirm?'<p class="review-scope">对照原文核实后，点下方「确认内容与出处」。本次核对可供其他项目沿用。</p>':'')+body+compare+
      (checkNames?'<div data-material-name-checks hidden></div>':'')+
      ((a.evidence||[]).length?'<h3>'+(it.stale?'原引用位置':relation?'原文依据':'引用位置')+'</h3>'+(a.evidence||[]).map(ev=>'<div class="project-material-evidence"><p>'+e(ev.quote||'')+'</p>'+btn('查看原文 ↗','materialSource',{code:a.code,anchor:ev.anchor||ev.seg||''},'sm ghost')+(relation&&ev.quote?btn('复制摘录','copyMaterialQuote',{quote:ev.quote},'sm ghost'):'')+(checkNames&&(ev.anchor||ev.seg)?nameCheckForm({code:a.code,anchor:ev.anchor||ev.seg}):'')+'</div>').join(''):'')+
      ((it.quality_issues||[]).length?'<div class="banner">'+it.quality_issues.map(x=>e(typeof x==='string'?x:x.message||x.reason||'请核对来源')).join('<br>')+'</div>':'')+
      (canceledRef?'<div class="banner">旧稿仍使用过这条材料。审核前请处理正文并核对引用。'+btn('核对当前稿引用','openDraftReferenceReview',{},'sm ghost')+'</div>':'')+
      '<label class="studio-field"><span>本项目采用理由 / 用途备注</span><textarea rows="5" data-item="'+e(it.asset_id)+'" oninput="Studio.noteMaterial(this)" placeholder="这条材料用于什么，仍需补充什么？">'+e(note||'')+'</textarea></label><p class="project-note-save">备注随项目一起保存，切换材料会保留输入。</p><div class="card-actions">'+btn('保存备注','save',{},'sm ghost')+(archived||it.current_status==='missing'||(relation&&!it.stale)?'':btn(it.stale?'查看当前成果':'打开内容成果','detail',{id:it.asset_id,purpose:p.title},'sm ghost'))+(it.stale&&!unavailable?btn('更新引用','refreshItem',{id:it.asset_id},'sm ghost'):'')+'</div></div><div class="project-side-panel-footer">'+confirmAction+adoptAction+notFitAction+'</div></aside>';
    root.querySelector('.project-side-panel-head button').focus({preventScroll:true});
    if(checkNames)loadNameChecks(root.querySelector('[data-material-name-checks]'),p,it.asset_id);
  }
  function noteMaterial(el){ProjectUI.notes[el.dataset.item]=el.value;markDirty();}
  function closeMaterialDetail(){
    if(document.querySelector('.project-side-panel')&&S.project?.kind==='marketing'&&window.MarketingOverlay&&MarketingOverlay.close())return;
    clearMaterialDetail();
  }
  function clearMaterialDetail(){
    const root=document.getElementById('projectSidePanelRoot'),focus=ProjectUI.detail?.returnTo;
    if(root)root.innerHTML='';
    if(S.project?.kind==='editorial')rememberEditorialRelationDetail(S.project,'');
    ProjectUI.detail=null;
    if(focus?.isConnected)focus.focus({preventScroll:true});
  }
  function materialSource(el){
    // Keep the material visit in history; closing it first would erase the return target.
    go('book',el.dataset.code,'text',el.dataset.anchor||'');
  }
  async function copyMaterialQuote(el){
    try{await navigator.clipboard.writeText(el.dataset.quote);toast('已复制原文摘录');}
    catch(_){toast('复制失败，可以选中摘录后手动复制。',true);}
  }
  function restoreMaterialDetail(saved,context){
    if(saved?.type!=='project-material'||!/^prj-[a-f0-9]{16}$/.test(saved.projectId||'')||
      typeof saved.assetId!=='string'||!saved.assetId||saved.assetId.length>300||/[\x00-\x1f]/.test(saved.assetId)||!SECTIONS.includes(saved.section))return;
    const current=parse();
    if(!context.isCurrent()||current.view!=='campaigns'||current.arg!==saved.projectId||
      (current.tab||S.section)!==saved.section||S.project?.id!==saved.projectId||S.project.kind!=='marketing')return;
    // The route has already read the project. Restore only the detail, leaving local edits intact.
    openMaterialDetail({dataset:{id:saved.assetId}},false,context.options);
  }
  async function restoreSummaryPreview(saved,context){
    const project=S.project;
    if(!context.isCurrent()||project?.kind!=='marketing'||project.id!==saved.projectId||S.section!==saved.section)return;
    const item=project.items.find(row=>row.asset_id===saved.assetId);
    if(!item?.replacement?.id){history.back();return;}
    await detail({dataset:{id:item.replacement.id,queue:'true',preview:'true',material:item.asset_id}},
      {...context.options,isCurrent:context.isCurrent});
  }
  function markDirty(){S.dirty=true;refreshProjectLabels();syncProjectIntent();clearTimeout(ProjectUI.outlineTimer);ProjectUI.outlineTimer=setTimeout(syncDraftOutline,180);if(window.ProjectAssist)ProjectAssist.projectEdited();const n=document.getElementById('projectSaveState');if(n)n.textContent='有修改待保存';const next=document.getElementById('projectNextStep');if(next&&S.project&&S.project.draft_review)next.outerHTML=projectNext(S.project);cacheLocalDraft();updateMarketingFlow();}
  function projectFieldsChanged(p,form,draft){
    const fields=projectFormFields(form),title=fields.title;delete fields.title;
    return S.draftRebuilt||title!==p.title||draft.value!==(p.draft||'')||JSON.stringify(comparableBrief(Object.assign({},p.brief||{},fields),p.kind==='marketing'))!==JSON.stringify(comparableBrief(p.brief,p.kind==='marketing'));
  }
  async function saveCurrent(quiet){
    if(S.saving){await S.saving;return saveCurrent(quiet);}
    const pending=saveProjectAndNotes(quiet);S.saving=pending;
    try{return await pending;}finally{if(S.saving===pending)S.saving=null;}
  }
  async function saveProjectAndNotes(quiet){
    const p=S.project;if(!p)return;const form=document.getElementById('projectBrief'),draft=document.getElementById('projectDraft');if(!form||!draft)return p;
    const same=()=>S.project&&S.project.id===p.id&&document.getElementById('projectBrief')===form;
    const fields=projectFormFields(form),title=fields.title;delete fields.title;
    if(!title.trim())throw new Error('项目名称不能为空');
    if(projectFieldsChanged(p,form,draft)){
      const body={action:'save',revision:p.revision,title,brief:Object.assign({},p.brief||{},fields),draft:draft.value};
      if(S.draftAssetIds)body.draft_asset_ids=S.draftAssetIds;if(S.draftRebuilt)body.rebuild_draft=true;
      const d=await request('/api/projects/'+p.id,body);if(!same())return d.project;
      S.project=d.project;S.draftRebuilt=false;
    }
    // Notes remain in memory when closing a material or moving between local pages.
    // Flush with current revisions before any dependent operation or navigation.
    for(const [id,note] of Object.entries(ProjectUI.notes)){
      if(!same())return S.project;
      const item=(S.project.items||[]).find(x=>x.asset_id===id);
      if(item&&note!==(item.note||'')){
        const d=await request('/api/projects/'+p.id,{action:'update_item',revision:S.project.revision,asset_id:id,note});
        if(!same())return d.project;S.project=d.project;
      }
      if(ProjectUI.notes[id]===note)delete ProjectUI.notes[id];
    }
    if(same()){
      S.dirty=projectFieldsChanged(S.project,form,draft)||Object.keys(ProjectUI.notes).length>0;
      const saved=document.getElementById('projectSaveState');if(saved)saved.textContent=S.dirty?'有修改待保存':'已保存';
      const next=document.getElementById('projectNextStep');if(next)next.outerHTML=projectNext(S.project);
      syncProjectIntent();refreshProjectLabels();renderMaterialRows();if(window.ProjectNav)ProjectNav.update(S.project,S.section);
      if(JSON.stringify(p.draft_display_labels)!==JSON.stringify(S.project.draft_display_labels))syncDraftOutline();
      else if(S.section==='results')loadNameChecks(document.getElementById('projectDraftNameChecks'),S.project);
      if(window.ProjectAssist)ProjectAssist.projectSaved(S.project,S.dirty);
      if(!S.dirty)clearLocalDraft();else cacheLocalDraft();updateMarketingFlow();
      if(!quiet)toast(S.dirty?'已保存提交时的内容，新修改仍待保存':'项目已保存');
    }
    return S.project;
  }
  async function save(){try{await saveCurrent(false);}catch(err){report(err);}}
  async function mutate(body,rerender){
    const origin=S.project&&S.project.id,form=document.getElementById('projectBrief');
    await saveCurrent(true);const p=S.project;if(!p||p.id!==origin||document.getElementById('projectBrief')!==form)throw new Error('项目已切换，请回原项目继续操作');
    const draft=document.getElementById('projectDraft'),version=JSON.stringify(projectFormFields(form))+'\n'+draft.value,notes=JSON.stringify(ProjectUI.notes);
    const d=await request('/api/projects/'+p.id,Object.assign({revision:p.revision},body));
    if(!S.project||S.project.id!==origin||document.getElementById('projectBrief')!==form)return d;
    if(d.project)S.project=d.project;
    const editing=S.dirty||version!==JSON.stringify(projectFormFields(form))+'\n'+draft.value||notes!==JSON.stringify(ProjectUI.notes);
    if(rerender!==false&&!editing)projectDetail(document.getElementById('view'));
    else{if(editing)S.dirty=true;syncProjectIntent();refreshProjectLabels();renderMaterialRows();const next=document.getElementById('projectNextStep');if(next)next.outerHTML=projectNext(S.project);if(window.ProjectAssist)ProjectAssist.projectSaved(S.project,S.dirty);if(window.ProjectHistory)ProjectHistory.mount(document.getElementById('projectHistory'),S.project);}
    return d;
  }
  async function itemStatus(el){
    const id=S.project?.id,aid=el.dataset.id,status=el.dataset.status;
    try{
      const d=await mutate({action:'update_item',asset_id:aid,status});
      if(S.project?.id!==id)return;
      if(status==='not_fit'&&(d.project?.draft_asset_ids||[]).includes(aid)){
        const main=document.getElementById('projectNextStep');
        if(ProjectUI.detail?.id===aid){closeMaterialDetail();main?.querySelector('button')?.focus({preventScroll:true});}
        syncDraftOutline();
        toast('已取消采用，请核对当前稿中仍有关联的段落与出处');
      }else toast('项目选择已保存');
    }catch(err){report(err);}
  }
  async function confirmMaterial(el){
    const detail=ProjectUI.detail;
    if(!detail||detail.id!==el.dataset.id||S.reviewBusy)return;
    S.reviewBusy=true;el.disabled=true;
    try{
      const d=await mutate({action:'confirm_collected_material',asset_id:detail.id,asset_revision:el.dataset.revision},false);
      if(S.project?.id!==detail.project)return;
      if(ProjectUI.detail===detail)openMaterialDetail({dataset:{id:detail.id}});
      const item=d.project.items.find(x=>x.asset_id===detail.id);
      const confirmed=item.current_status==='approved'&&!item.stale;
      toast(confirmed?'内容与出处已确认':'材料已变化，请重新核对',!confirmed);
    }catch(err){if(S.project?.id===detail.project)report(err);}
    finally{S.reviewBusy=false;el.disabled=false;}
  }
  async function itemNote(el){noteMaterial(el);await save();}
  async function refreshItem(el){try{await mutate({action:'refresh_asset',asset_id:el.dataset.id});toast('已更新引用，请重新核对');}catch(err){report(err);}}
  async function findForProject(){try{await saveCurrent(true);S.filters.q='';S.filters.kind='';S.filters.code='';S.filters.offset=0;S.filters.status='';if(S.project)go('content','pick:'+S.project.id);}catch(err){report(err);}}
  async function compose(){
    try{await saveCurrent(true);const p=S.project,b=p.brief||{},used=(p.items||[]).filter(function(it){return it.status==='adopted';});
      if(!used.length){toast('请先选择项目采用的材料',true);return;}
      const marketing=p.kind==='marketing',hypothesis=marketing&&!b.source_code&&!b.new_book_brief;
      let lines=['# '+p.title,'','## '+(hypothesis?'营销方向假设':marketing?'营销素材包':'选题资料包'),'',(marketing?'内容给谁看：':'目标读者：')+(b.audience||'待明确'),'主题：'+(b.topic||'待明确'),'工作目标：'+(b.goal||'待补充')];
      if(marketing)lines.push('使用渠道：'+(b.channel||'待明确'),'新书确认资料：'+(b.new_book_brief|| (b.source_code?'基于所选已出版图书':'待补充，当前仅供方向讨论')));
      lines.push('','## 已选材料与依据','');
      used.forEach(function(it,i){const a=it.snapshot||{};lines.push('### '+(i+1)+'. '+(a.title||K[a.kind]||'材料'),a.text||'','采用理由：'+(it.note||'待补充'),'来源：'+(a.book||a.code||''));(a.evidence||[]).forEach(function(ev){lines.push('> '+(ev.quote||'')+'（'+(ev.anchor||ev.seg||'出处待补')+'）');});lines.push('');});
      lines.push('## '+(marketing?'传播表达与使用安排':'编辑判断与内容组织'),'待补充：结合本次目标，写明内容组织和使用方式。','','## 待核对与资料缺口','请核对来源、适用范围及尚未得到证实的判断。');
      document.getElementById('projectDraft').value=lines.join('\n');S.draftAssetIds=used.map(function(x){return x.asset_id;});S.draftRebuilt=true;markDirty();await saveCurrent(true);toast('资料草稿已整理并保存，请补充判断后审核');
    }catch(err){report(err);}
  }
  async function approveProject(){try{await mutate({action:'review',approved:true});toast(S.dirty?'提交时的稿件已审核，新修改仍需保存并重新审核':'当前稿件已审核');}catch(err){report(err);}}
  async function exportProject(el){
    const id=S.project?.id,hash=location.hash,form=document.getElementById('projectBrief');
    const modalRoot=document.getElementById('modalRoot'),modal=modalRoot?.firstElementChild;
    if(!id||S.exporting)return;
    const current=()=>S.project?.id===id&&location.hash===hash&&document.getElementById('projectBrief')===form;
    S.exporting=true;el.disabled=true;
    try{
      const {export:entry,text}=await mutate({action:'export',mode:el.dataset.mode},false);
      if(!current()||modalRoot?.firstElementChild!==modal)return;
      if(!entry?.id)throw new Error('导出记录未返回，请在交付记录中查看');
      if(entry.content_kind==='channel_content'&&typeof text==='string'){ExportCopies.set(id+':'+entry.id,{export:entry,text});while(ExportCopies.size>40)ExportCopies.delete(ExportCopies.keys().next().value);}
      if(document.getElementById('projectDraftRelease'))document.getElementById('projectDraftRelease').open=false;
      const delivery=MarketingScenes.deliveryInfo(entry),name=delivery?.title||(entry.mode==='approved'?'已审核交付稿':'审阅稿'),data={id:entry.id,project:id};
      const channel=entry.channels?.length===1?entry.channels[0]:'',structured=entry.content_kind==='marketing_plan'||!!CHANNEL_VIEWS[channel];
      const copyLabel=CHANNEL_VIEWS[channel]?.[0]||MarketingScenes.workflow({marketing_task:'channel',channels:entry.channels}).noun;
      const hasCopy=entry.content_kind==='channel_content';
      openModal('<section id="projectExportDownload" class="project-export-download" role="dialog" aria-modal="true" aria-labelledby="projectExportDownloadTitle" onkeydown="if(event.key===\'Escape\')closeModal()">'+modalX()+
        '<h2 id="projectExportDownloadTitle">'+(delivery?'':'下载')+e(name)+'</h2><p>'+e(delivery?.next||'该版本已记入交付记录，可选择下载格式。')+'</p><div class="modal-actions">'+
        (hasCopy?btn('复制'+copyLabel,'copyExport',data,structured?'ghost':'primary'):'')+
        btn('下载排版 PDF','downloadExport',Object.assign({format:'pdf'},data),!hasCopy||structured?'primary':'ghost')+
        (structured?'':btn('下载 Markdown','downloadExport',Object.assign({format:'md'},data),'ghost'))+'</div></section>');
      document.querySelector(hasCopy&&!structured?'#projectExportDownload [onclick*=copyExport]':'#projectExportDownload [data-format="pdf"]')?.focus();
    }catch(err){if(current())report(err);}
    finally{S.exporting=false;el.disabled=false;}
  }
  async function copyExport(el,snapshot){
    const p=S.project,id=el.dataset.id||el.dataset.export,entry=p?.exports?.find(item=>item.id===id);
    if(!entry||entry.content_kind!=='channel_content'||el.dataset.project!==p.id||el.disabled)return;
    const hash=location.hash,controller=new AbortController();
    const current=()=>S.project?.id===p.id&&location.hash===hash&&el.isConnected;
    const abort=()=>{if(!current())controller.abort();};
    el.disabled=true;window.addEventListener('hashchange',abort);
    try{
      let frozen=snapshot||ExportCopies.get(p.id+':'+id);
      if(!frozen){
        const response=await fetch('/api/projects/'+encodeURIComponent(p.id)+'/exports/'+encodeURIComponent(id),{signal:controller.signal,credentials:'same-origin'});
        if(!response.ok)throw new Error('暂时无法读取这份稿件，请重试。');
        frozen=await response.json();
      }
      if(!current())return;
      if(frozen?.ok===false||frozen?.export?.id!==id||frozen.export.project_id!==p.id||frozen.export.content_kind!=='channel_content'||typeof frozen.text!=='string'||!frozen.text.trim())throw new Error('这份稿件暂时无法复制，请重新打开后重试。');
      const channel=entry.channels?.length===1?entry.channels[0]:'';
      await navigator.clipboard.writeText(MarketingScenes.deliveryCopy(channel,frozen.text));
      if(current())toast('已复制这份'+MarketingScenes.workflow({marketing_task:'channel',channels:entry.channels}).noun);
    }catch(err){if(err.name!=='AbortError'&&current())toast(err.message||'复制失败，请重试。',true);}
    finally{window.removeEventListener('hashchange',abort);controller.abort();el.disabled=false;}
  }
  async function downloadExport(el){
    const p=S.project,id=el.dataset.id||el.dataset.export,format=el.dataset.format;
    const entry=p?.exports?.find(item=>item.id===id);
    if(!entry||el.dataset.project!==p.id||!['pdf','md'].includes(format)||el.disabled)return;
    const hash=location.hash,controller=new AbortController();
    const current=()=>S.project?.id===p.id&&location.hash===hash&&el.isConnected;
    const abort=()=>{if(!current())controller.abort();};
    el.disabled=true;
    window.addEventListener('hashchange',abort);
    try{
      const url='/api/projects/'+encodeURIComponent(p.id)+'/exports/'+encodeURIComponent(id)+'?format='+format;
      const response=await fetch(url,{signal:controller.signal,credentials:'same-origin'});
      if(!response.ok){
        const error=await response.json().catch(()=>null);
        throw new Error(error?.error||'下载失败，请重试（HTTP '+response.status+'）');
      }
      const mime=response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
      const expected=format==='pdf'?['application/pdf']:['text/markdown','text/plain'];
      if(!expected.includes(mime))throw new Error('收到的文件格式不正确，请重试');
      const blob=await response.blob();
      if(!current())return;
      if(!blob.size)throw new Error('稿件文件为空，请重试');
      const file=entry.filename||(entry.mode==='approved'?'已审核交付稿':'审阅稿');
      const link=document.createElement('a'),objectUrl=URL.createObjectURL(blob);
      link.href=objectUrl;link.download=file.replace(/\.(?:md|pdf)$/i,'')+'.'+format;link.target='_self';
      document.body.appendChild(link);
      try{link.click();}finally{link.remove();setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);}
    }catch(err){if(err.name!=='AbortError'&&current())report(err instanceof TypeError?new Error('下载失败，请检查连接后重试'):err);}
    finally{window.removeEventListener('hashchange',abort);controller.abort();el.disabled=false;}
  }
  async function feedback(){
    const form=document.getElementById('projectFeedback');if(!form||!S.project||form.dataset.project!==S.project.id){toast('请回到对应项目的交付记录填写反馈',true);return;}
    const d=projectFormFields(form);
    if(!String(d.note||'').trim()){toast('请记录具体使用情况或修改原因',true);return;}
    try{await mutate(Object.assign({action:'feedback'},d));toast('使用反馈已保存');}catch(err){report(err);}
  }
  async function generate(el){
    el.disabled=true;try{const d=await request('/api/books/generate',{code:el.dataset.code,kind:el.dataset.kind||'marketing'});toast((el.dataset.kind==='summaries'?'章节摘要':'营销资料')+'生成任务已创建');go('job',d.job.id);}catch(err){report(err);el.disabled=false;}
  }
  function peekAssistContext(){
    if(!S.project)return null;
    const p=JSON.parse(JSON.stringify(S.project)),form=document.getElementById('projectBrief'),draft=document.getElementById('projectDraft');
    if(form&&draft){
      const fields=projectFormFields(form),title=fields.title;delete fields.title;
      if(title!==undefined)p.title=title;
      p.brief=Object.assign({},p.brief||{},fields);p.draft=draft.value;
      if(S.draftAssetIds)p.draft_asset_ids=S.draftAssetIds.slice();
    }
    return p;
  }
  async function assistContext(){return saveCurrent(true);}
  async function assistMutate(body,rerender,expectedId){
    const p=await assistContext();if(!p||(expectedId&&p.id!==expectedId))throw new Error('项目已切换，请回到原项目继续');
    const view=document.getElementById('projectAssist'),form=document.getElementById('projectBrief'),draft=document.getElementById('projectDraft');
    const formVersion=form&&draft?JSON.stringify(projectFormFields(form))+'\n'+draft.value:'';
    const d=await request('/api/projects/'+p.id,Object.assign({revision:p.revision},body));
    if(!S.project||S.project.id!==p.id||document.getElementById('projectAssist')!==view)return d;
    if(d.project)S.project=d.project;
    if(body.action==='apply_generation'){S.draftAssetIds=null;S.draftRebuilt=false;}
    const editing=S.dirty||Object.keys(ProjectUI.notes).length>0||form&&draft&&formVersion!==JSON.stringify(projectFormFields(form))+'\n'+draft.value;
    if(rerender!==false&&!editing)projectDetail(document.getElementById('view'));
    else if(window.ProjectAssist){if(rerender!==false)ProjectAssist.mount(S.project);else ProjectAssist.projectSaved(S.project,editing);if(editing){S.dirty=true;ProjectAssist.projectEdited();toast('操作已保存；刚输入的修改仍保留在编辑区，请继续保存');}}
    return d;
  }
  async function beforeNavigate(){S.request++;rememberNavigation();if(S.dirty&&S.project?.kind!=='marketing')await saveCurrent(true);}
  function upload(){openUpload();}
  function reload(){route();}
  window.addEventListener('keydown',function(ev){if(ev.key==='Escape'&&!document.querySelector('#modalRoot .modal')&&document.querySelector('.project-side-panel')){ev.preventDefault();closeMaterialDetail();}if(ev.key==='Tab'&&!document.querySelector('#modalRoot .modal')){const panel=document.querySelector('.project-side-panel');if(!panel)return;const all=Array.from(panel.querySelectorAll('button:not(:disabled),textarea,input,a[href]')).filter(x=>x.getClientRects().length);if(!all.length)return;const first=all[0],last=all[all.length-1];if(ev.shiftKey&&document.activeElement===first){ev.preventDefault();last.focus();}else if(!ev.shiftKey&&document.activeElement===last){ev.preventDefault();first.focus();}}});
  window.addEventListener('beforeunload',function(ev){if(S.dirty){ev.preventDefault();ev.returnValue='';}});
  window.MarketingOverlay?.register?.('project-material',restoreMaterialDetail);
  window.MarketingOverlay?.register?.('project-summary-preview',restoreSummaryPreview);
  return {syncNavigation:updateMarketingFlow,returnToSourceOrigin,rememberNavigation,editWritingNotes,marketingNext,marketingStepBack,showLocalRecovery,updateAssistProgress,selectDraftScene,selectChannelDelivery,copyDraftScene,applySceneEdits,editFullScene,marketingTaskChange,editProjectBrief,showMaterialMode,filterMaterials,materialPage,prepareMarketingMaterialList,prepareRelationMaterialList,advanceLocalDraftAfterRelation,openMaterialDetail,noteMaterial,closeMaterialDetail,materialSource,copyMaterialQuote,confirmMaterial,saveNameCheck,openDraftReferenceReview,updateDraftReferenceReview,submitDraftReferences,editDraftReferenceText,goDraftReferenceMaterials,jumpDraft,setDraftMode,rememberDraftDetails,render,openProjectSection,projectSection,focusDraft,continueProject,switchProject,searchProjects,switchProjectPage,retryProjectSwitch,switchToProject,peekAssistContext,assistContext,assistMutate,beforeNavigate,nav,create,submitCreate,detail,review,source,rememberReview,closeReviewSource,chooseProject,addAsset,addToCurrent,returnToProject,filterKind,filter,resetFilters,paginate,save,markDirty,itemStatus,itemNote,refreshItem,findForProject,compose,approveProject,exportProject,copyExport,downloadExport,feedback,generate,upload,reload};
})();
