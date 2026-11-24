/* 查人物与关系
 * 按关键词查找对象，在对象详情中比较关系、回查原文。
 */
(function () {
  'use strict';
  const esc = window.esc || (s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));
  const jget = window.jget, go = window.go, toast = window.toast || (m => console.log(m));
  const $ = id => document.getElementById(id);

  const SUGS = [
    { q: '院士', t: '院士', h: 'B59 人物' },
    { q: '狐狸', t: '狐狸', h: 'B58 小王子' },
    { q: '植物', t: '植物', h: 'B56 图鉴' },
    { q: '廉洁', t: '廉洁', h: 'B60 主题' },
    { q: '乡土', t: '乡土', h: 'B66 篇章' },
    { q: '秋夜', t: '秋夜', h: 'YC 野草' }
  ];
  const LOOKUPS = [
    { q: '钱塘江大桥', t: '钱塘江大桥的修建和修复', d: '从工程出发，查书里写了谁主持修建、谁受命修复。' },
    { q: '叶企孙', t: '叶企孙与华罗庚', d: '从人物出发，查看叶企孙如何推动华罗庚破格任教。' },
    { q: '差序格局', t: '费孝通怎样解释差序格局', d: '从概念出发，查看《乡土中国》所举的例子及原文。' },
    { q: '狐狸', t: '《小王子》中的狐狸', d: '搜索“狐狸”，查看相关对象与原文线索。' },
    { q: '植物', t: '药用植物与分类', d: '搜索“植物”，进入图鉴查看科与物种记录。' },
    { q: '廉洁', t: '廉洁主题与人物', d: '搜索“廉洁”，按篇目查看主题与人物索引。' }
  ];
  const BASIS_HINTS = {
    explicit: '书中明确写出了这条关系。',
    field: '根据学科、籍贯等字段归类。',
    interpretation: '使用前需要核对原文能否支持这条解释。',
    structure: '根据书中篇章和目录位置整理。'
  };

  let ac = null, data = null, byId = {}, edgeById = {}, viewEl = null, bodyEl = null, searchEl = null;
  let debounce = 0;
  const state = { view: 'home', q: '', book: '', type: '全部', nodeId: '', edgeId: '', mode: 'cards', relationMode: 'list' };

  function edgeKey(edge) {
    const code = edge.code || String(edge.source || '').split(':')[0];
    const id = edge.edge_id || edge.id || '';
    return code && id && !id.startsWith(code + ':') ? code + ':' + id : id;
  }
  function rememberSelection(hash) {
    const selection = { edgeId: state.edgeId, bookCode: state.book, type: state.type, mode: state.mode, relationMode: state.relationMode };
    if (window.RelationMaterials?.remember) window.RelationMaterials.remember(hash || location.hash, selection);
    else if (hash) history.replaceState(history.state, '', hash);
  }
  function openResult(hash) {
    if (hash !== location.hash) AppHistory.push({ relationSelection: {}, relationSaved: null });
    rememberSelection(hash);
    renderBody();
    bodyEl.querySelector('.kl-main h2')?.focus();
  }
  function searchHash() { return '#/kglab' + (state.q ? '/q=' + encodeURIComponent(state.q) : ''); }

  function headHTML() {
    return `<div class="kl-wrap">
      <div class="kl-headrow">
        <div><h1>查人物与关系</h1></div>
        <div class="sub">用人物、事件、概念或书名查关系，再回原文核对。</div>
        <div class="sp">
          <button class="kl-link" data-act="home">查找首页</button>
          <button class="kl-link" data-act="graph">浏览关系图谱 ↗</button>
        </div>
      </div>
      <div class="kl-search">
        <span class="ico">⌕</span>
        <input id="klq" aria-label="查找人物、事件、概念或书名" placeholder="搜人物、事件、概念或书名，如钱塘江大桥" autocomplete="off">
        <button class="go" data-act="search">搜索</button>
      </div>
      <div class="kl-sugs">${SUGS.map(s => `<span class="kl-sug" data-q="${esc(s.q)}"><b>${esc(s.t)}</b> · ${esc(s.h)}</span>`).join('')}</div>
      <div id="klBody" class="kl-body"><div class="kl-empty" role="status">正在加载可查找的人物与关系…</div></div>
    </div>`;
  }

  async function render(view, arg) {
    destroy();
    ac = new AbortController();
    const signal = ac.signal;
    view.className = 'view kglab-page';
    view.innerHTML = headHTML();
    viewEl = view; bodyEl = $('klBody'); searchEl = $('klq');
    state.view = 'home'; state.q = ''; state.book = ''; state.type = '全部'; state.nodeId = ''; state.edgeId = ''; state.mode = 'cards'; state.relationMode = 'list';
    bind();
    try {
      const result = await jget('/api/kg/view');
      if (signal.aborted) return;
      data = result;
      byId = {}; data.nodes.forEach(n => byId[n.id] = n);
      edgeById = {}; (data.edges || []).forEach(e => { if (edgeKey(e)) edgeById[edgeKey(e)] = e; });
      if (arg && String(arg).startsWith('q=')) {
        state.q = String(arg).slice(2);
        state.view = state.q ? 'search' : 'home';
        if (searchEl) searchEl.value = state.q;
      } else if (arg) {
        const parts = String(arg).split('/');
        const code = parts[0], raw = parts.slice(1).join('/');
        if (data.meta.books.some(b => b.code === code)) state.book = code;
        if (raw) {
          const n = findNode(code, raw);
          if (n && n.kind !== 'book') { state.nodeId = n.id; state.view = 'entity'; }
          else state.view = 'book';
        } else if (state.book) state.view = 'book';
      }
      const saved = window.RelationMaterials?.selection() || {};
      if (saved.bookCode && data.meta.books.some(b => b.code === saved.bookCode)) state.book = saved.bookCode;
      if (saved.type) state.type = saved.type;
      if (saved.mode === 'table') state.mode = 'table';
      if (saved.relationMode === 'graph') state.relationMode = 'graph';
      const matches = saved.edgeId ? (data.edges || []).filter(e => [e.source, e.target].includes(state.nodeId) && (edgeKey(e) === saved.edgeId || e.id === saved.edgeId)) : [];
      if (state.view === 'entity' && matches.length === 1) state.edgeId = edgeKey(matches[0]);
      renderBody();
    } catch (e) {
      if (!signal.aborted) bodyEl.innerHTML = `<div class="kl-empty"><b>关系数据加载失败</b>${esc(e.message)}</div>`;
    }
  }

  function destroy() {
    if (ac) { ac.abort(); ac = null; }
    clearTimeout(debounce);
    data = null; byId = {}; edgeById = {}; viewEl = null; bodyEl = null; searchEl = null;
  }

  function bind() {
    viewEl.addEventListener('click', ev => {
      const edge = ev.target.closest('[data-edge]');
      if (edge) {
        clearTimeout(debounce);
        ev.preventDefault(); ev.stopPropagation();
        const selected = edgeById[edge.dataset.edge];
        if (!selected || ![selected.source, selected.target].includes(state.nodeId)) return;
        state.edgeId = edgeKey(selected); rememberSelection(); renderBody();
        const evidence = bodyEl.querySelector('[data-relation-evidence]');
        if (evidence) { evidence.scrollIntoView({ block: 'nearest' }); evidence.focus({ preventScroll: true }); }
        return;
      }
      const n = ev.target.closest('[data-nid]');
      if (n) { selectNode(n.dataset.nid); return; }
      const book = ev.target.closest('[data-book]');
      if (book) {
        clearTimeout(debounce);
        const c = book.dataset.book;
        if (c === 'all') { state.book = ''; state.type = '全部'; state.view = state.q ? 'search' : 'home'; state.nodeId = ''; state.edgeId = ''; rememberSelection(searchHash()); renderBody(); }
        else selectBook(c);
        return;
      }
      const type = ev.target.closest('[data-type]');
      if (type) { state.type = type.dataset.type || '全部'; rememberSelection(); renderBody(); return; }
      const q = ev.target.closest('[data-q]');
      if (q) { doSearch(q.dataset.q, true); return; }
      const anchor = ev.target.closest('[data-act="anchor"]');
      if (anchor) { go('book', anchor.dataset.code, 'text', anchor.dataset.anchor); return; }
      const act = ev.target.closest('[data-act]');
      if (!act) return;
      const a = act.dataset.act;
      if (a === 'graph') go('kg', state.book || undefined);
      else if (a === 'search') doSearch(searchEl.value.trim(), true);
      else if (a === 'book') go('book', act.dataset.code);
      else if (a === 'full') go('kg', act.dataset.code);
      else if (a === 'show-node') go('kg', state.nodeId.replace(':', '/'));
      else if (a === 'copy') {
        const text = act.dataset.text || '';
        if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast('已复制')).catch(() => toast('复制失败'));
        else toast('已复制');
      } else if (a === 'csv') exportCSV();
      else if (a === 'mode') { state.mode = act.dataset.mode; rememberSelection(); renderBody(); }
      else if (a === 'relation-mode' && act.dataset.mode !== state.relationMode) {
        state.relationMode = act.dataset.mode;
        rememberSelection();
        renderBody();
        bodyEl.querySelector('[data-act="relation-mode"][aria-pressed="true"]')?.focus({ preventScroll: true });
      }
      else if (a === 'home') { clearTimeout(debounce); state.view = 'home'; state.q = ''; state.book = ''; state.nodeId = ''; state.edgeId = ''; if (searchEl) searchEl.value = ''; rememberSelection('#/kglab'); renderBody(); }
    }, { signal: ac.signal });

    searchEl.addEventListener('input', () => {
      clearTimeout(debounce);
      const v = searchEl.value;
      debounce = setTimeout(() => {
        state.q = v;
        state.nodeId = ''; state.edgeId = '';
        if (v.trim()) { state.view = 'search'; state.book = ''; state.type = '全部'; }
        else state.view = state.book ? 'book' : 'home';
        rememberSelection(searchHash());
        renderBody();
      }, 150);
    }, { signal: ac.signal });
    searchEl.addEventListener('keydown', ev => {
      if (ev.key === 'Enter') { clearTimeout(debounce); doSearch(searchEl.value.trim(), true); }
      if (ev.key === 'Escape') { searchEl.value = ''; state.q = ''; state.view = state.book ? 'book' : 'home'; state.nodeId = ''; state.edgeId = ''; rememberSelection('#/kglab' + (state.book ? '/' + state.book : '')); renderBody(); }
    }, { signal: ac.signal });
  }

  function findNode(code, raw) {
    const dec = decodeURIComponent(raw || '');
    return data.nodes.find(n => n.kind !== 'book' && n.code === code && (n.id.endsWith(':' + dec) || n.label === dec)) ||
      data.nodes.find(n => n.kind !== 'book' && (n.id.endsWith(':' + dec) || n.label === dec));
  }

  function doSearch(q, all) {
    clearTimeout(debounce);
    state.q = q; state.nodeId = ''; state.edgeId = '';
    if (all) { state.book = ''; state.type = '全部'; }
    state.view = q ? 'search' : (state.book ? 'book' : 'home');
    if (searchEl) searchEl.value = q;
    rememberSelection(searchHash());
    renderBody();
  }

  function selectNode(id) {
    clearTimeout(debounce);
    const n = byId[id];
    if (!n) return;
    if (n.kind === 'book') { selectBook(n.code); return; }
    state.nodeId = id; state.edgeId = ''; state.view = 'entity'; state.relationMode = 'list';
    state.book = n.code || state.book; state.type = '全部'; state.q = '';
    if (searchEl) searchEl.value = '';
    const raw = n.id.split(':').slice(1).join(':');
    openResult('#/kglab/' + (n.code || '') + '/' + encodeURIComponent(raw));
  }

  function selectBook(code) {
    clearTimeout(debounce);
    state.book = code; state.view = 'book'; state.type = '全部'; state.nodeId = ''; state.edgeId = ''; state.q = '';
    if (searchEl) searchEl.value = '';
    openResult('#/kglab/' + code);
  }

  function renderBody() {
    if (!bodyEl || !data) return;
    if (state.view === 'entity' && byId[state.nodeId]) bodyEl.innerHTML = entityHTML(byId[state.nodeId]);
    else if (state.view === 'book' && state.book) bodyEl.innerHTML = bookHTML(state.book);
    else if (state.view === 'search' && state.q.trim()) bodyEl.innerHTML = searchHTML();
    else bodyEl.innerHTML = homeHTML();
  }

  function typeColor(t) { return RELATION_TYPE_COLORS[t] || '#A4B5CF'; }
  function typeDot(t) { return `<i style="background:${typeColor(t)}"></i>`; }

  function bookEntities(code) { return data.nodes.filter(n => n.kind !== 'book' && n.code === code); }
  function bookTypes(code) {
    const ns = bookEntities(code); const cnt = {};
    ns.forEach(n => cnt[n.type] = (cnt[n.type] || 0) + 1);
    return (data.meta.types || []).filter(t => cnt[t.name]).map(t => ({ name: t.name, count: cnt[t.name] }));
  }
  function scopeTypes() {
    const ns = state.book ? bookEntities(state.book) : data.nodes.filter(n => n.kind !== 'book');
    const cnt = {}; ns.forEach(n => cnt[n.type] = (cnt[n.type] || 0) + 1);
    return (data.meta.types || []).filter(t => cnt[t.name]).map(t => ({ name: t.name, count: cnt[t.name] }));
  }
  function scopeEntities() {
    return data.nodes.filter(n => n.kind !== 'book' &&
      (!state.book || n.code === state.book) &&
      (state.type === '全部' || n.type === state.type));
  }
  function hay(n) {
    return [n.label, n.type, n.role, n.achievement, n.place, n.quote, (n.disciplines || []).join(' '), n.code]
      .filter(Boolean).join(' ').toLowerCase();
  }
  function scoreNode(n, q) {
    const label = String(n.label || '').toLowerCase();
    const body = [n.role, n.achievement, n.quote, n.place, (n.disciplines || []).join(' ')].filter(Boolean).join(' ').toLowerCase();
    let s = 0;
    if (label === q) s += 100;
    else if (label.startsWith(q)) s += 70;
    else if (label.includes(q)) s += 50;
    if (body.includes(q)) s += 40;
    if (String(n.type || '').toLowerCase().includes(q)) s += 15;
    if (String(n.book || '').toLowerCase().includes(q)) s += 5;
    if (n.kind === 'book') s += 20;
    return s + Math.min(15, n.degree || 0);
  }
  function searchNodes() {
    const q = state.q.trim().toLowerCase();
    if (!q) return [];
    const base = data.nodes.filter(n =>
      (!state.book || n.code === state.book || n.kind === 'book') &&
      (state.type === '全部' || n.type === state.type));
    return base.filter(n => hay(n).includes(q) || String(n.book || '').toLowerCase().includes(q))
      .sort((a, b) => scoreNode(b, q) - scoreNode(a, q)).slice(0, 100);
  }

  function railHTML() {
    const types = scopeTypes();
    const qn = state.q ? searchNodes().length : 0;
    return `<div class="kl-rail">
      <div class="grp"><h3>书 <span class="n">${data.meta.books.length}</span></h3>
        <div class="kl-booklist">
          <button data-book="all" class="${state.book ? '' : 'on'}"><span class="dot" style="background:#B0B1A6"></span>全部书</button>
          ${data.meta.books.map(b => `<button data-book="${esc(b.code)}" class="${state.book === b.code ? 'on' : ''}" title="${esc(b.title)}"><span class="dot"></span>${esc((b.short || b.title).length > 11 ? (b.short || b.title).slice(0, 11) + '…' : (b.short || b.title))}</button>`).join('')}
        </div>
      </div>
      <div class="grp"><h3>类型 <span class="n">${types.length}</span></h3>
        <div class="kl-types">
          <button class="kl-type ${state.type === '全部' ? 'on' : ''}" data-type="全部">全部</button>
          ${types.map(t => `<button class="kl-type ${state.type === t.name ? 'on' : ''}" data-type="${esc(t.name)}">${typeDot(t.name)}${esc(t.name)}</button>`).join('')}
        </div>
      </div>
      ${state.q ? `<div class="rescount">搜索「${esc(state.q)}」 · ${qn} 个结果</div>` : ''}
      <div class="hint">先选一本书，或输入关键词查找。</div>
    </div>`;
  }

  function homeHTML() {
    const n = data.nodes.filter(x => x.kind !== 'book').length;
    const e = (data.edges || []).filter(x => x.kind !== 'in_book').length;
    return `<div class="kl-home">
      <div class="kl-stats"><span><b>${data.meta.books.length}</b>本书</span><span><b>${n}</b>个对象</span><span><b>${e}</b>条关系</span></div>
      <div class="kl-qhead"><h2>查找示例</h2><span>点击示例试搜，也可以输入自己的关键词。</span></div>
      <div class="kl-qgrid">
        ${LOOKUPS.map(q => `<button type="button" class="kl-qcard" data-q="${esc(q.q)}"><span class="q">${esc(q.t)}</span><span class="a">${esc(q.d)}</span></button>`).join('')}
      </div>
      <div class="kl-qhead" style="margin-top:24px"><h2>按图书浏览</h2><span>每本书已整理的对象和关系不同</span></div>
      <div class="kl-books">
        ${data.meta.books.map(b => {
          const bn = byId['BOOK:' + b.code] || {};
          const cnt = (bn.counts || {});
          return `<div class="kl-bookcard" data-book="${esc(b.code)}"><div class="spine"></div><div class="code">${esc(b.code)}</div><b>${esc(b.title)}</b><div class="meta">${esc(b.form || '')}</div><div class="num">${cnt.nodes || ''}${cnt.nodes ? ' 个节点 / ' + (cnt.edges || 0) + ' 条边' : ''}</div></div>`;
        }).join('')}
      </div>
      <div class="kl-footnote">查看对象详情与直接关联，点开关系可核对已有出处；也可切换表格浏览。</div>
    </div>`;
  }

  function searchHTML() {
    const nodes = searchNodes();
    return `<div class="kl-grid">
      ${railHTML()}
      <div class="kl-main">
        <div class="kl-panel">
          <div class="kl-mainhead">
            <h2>搜索「${esc(state.q)}」</h2><span class="sub">${nodes.length} 个结果${state.book ? ' · ' + esc((data.meta.books.find(b => b.code === state.book) || {}).short || '') : ''}</span>
            <div class="right"><button class="kl-btn" data-act="csv">导出 CSV</button></div>
          </div>
          ${nodes.length ? tableHTML(nodes, 100) : `<div class="kl-empty"><b>图里没有这个名字</b>试试「院士」「狐狸」「植物」「廉洁」「乡土」「秋夜」。<div class="kl-sugs" style="justify-content:center">${SUGS.map(s => `<span class="kl-sug" data-q="${esc(s.q)}"><b>${esc(s.t)}</b></span>`).join('')}</div></div>`}
        </div>
        ${nodes.length ? `<div class="kl-note">点一行进入实体页；实体页里再展开关系。搜索结果里也可能出现「书」，点进去是这本书的书内世界。</div>` : ''}
      </div>
      <div class="kl-aside">
        <div class="box"><h4>搜索范围</h4><div class="qtext">${state.book ? '当前：' + esc((data.meta.books.find(b => b.code === state.book) || {}).title || '') : '全部 ' + data.meta.books.length + ' 本书'}</div><div class="meta">在左侧切书或切类型，可以收窄。</div></div>
        <div class="box"><h4>直接进书</h4><div class="kl-actions">${data.meta.books.slice(0, 7).map(b => `<button class="kl-btn" data-book="${esc(b.code)}">${esc((b.short || b.title).slice(0, 12))}</button>`).join('')}</div></div>
      </div>
    </div>`;
  }

  function bookHTML(code) {
    const b = data.meta.books.find(x => x.code === code);
    if (!b) return homeHTML();
    const bn = byId['BOOK:' + code] || {};
    const types = bookTypes(code);
    let ns = bookEntities(code);
    if (state.type !== '全部') ns = ns.filter(n => n.type === state.type);
    ns = ns.slice().sort((x, y) => (y.degree || 0) - (x.degree || 0));
    const total = ns.length, shown = Math.min(total, 60);
    const rows = ns.slice(0, shown);
    return `<div class="kl-grid">
      ${railHTML()}
      <div class="kl-main">
        <div class="kl-panel">
          <div class="kl-bookhead">
            <div class="cover">${esc((b.title || '书').slice(0, 1))}</div>
            <div><div class="code" style="font-size:9.5px;color:#A2A398">${esc(b.code)} · ${esc(b.form || '')}</div><h2 tabindex="-1">${esc(b.title)}</h2><div class="sub">${esc((bn.counts && bn.counts.nodes) || 0)} 个节点 · ${esc((bn.counts && bn.counts.edges) || 0)} 条关系</div></div>
            <div class="num"><b>${types.length}</b>种类型<br><b>${total}</b>个实体</div>
          </div>
          <div class="kl-tabs">
            <button class="kl-type ${state.type === '全部' ? 'on' : ''}" data-type="全部">全部</button>
            ${types.map(t => `<button class="kl-type ${state.type === t.name ? 'on' : ''}" data-type="${esc(t.name)}">${typeDot(t.name)}${esc(t.name)} <span style="opacity:.55">${t.count}</span></button>`).join('')}
          </div>
          <div class="kl-toolbar"><span class="count">${state.type === '全部' ? '全部实体' : esc(state.type)} · ${total} 个，显示 ${shown}</span><div class="right"><button class="kl-btn ${state.mode === 'cards' ? 'on' : ''}" data-act="mode" data-mode="cards">卡片</button><button class="kl-btn ${state.mode === 'table' ? 'on' : ''}" data-act="mode" data-mode="table">表格</button><button class="kl-btn" data-act="csv">导出</button></div></div>
          ${state.mode === 'table' ? tableHTML(rows, shown) : `<div class="kl-cards">${rows.map(cardHTML).join('')}</div>`}
          ${total > shown ? `<div class="kl-note">还有 ${total - shown} 个没有显示；切类型或用搜索收窄。</div>` : ''}
          <div class="kl-book-actions"><button class="kl-btn gold" data-act="full" data-code="${esc(code)}">打开完整图谱 ↗</button><button class="kl-btn" data-act="book" data-code="${esc(code)}">打开图书档案</button></div>
        </div>
      </div>
      <div class="kl-aside">
        <div class="box"><h4>这本书的图</h4><div class="qtext">${esc(b.form || '')}</div><div class="meta">${esc((bn.counts && bn.counts.nodes) || 0)} 节点 · ${esc((bn.counts && bn.counts.edges) || 0)} 关系</div></div>
        <div class="box"><h4>类型</h4><div class="kl-types">${types.map(t => `<span class="kl-type" data-type="${esc(t.name)}">${typeDot(t.name)}${esc(t.name)} ${t.count}</span>`).join('')}</div><div class="meta">点类型只看这一类；物种/条目多时用表格。</div></div>
        <div class="box"><h4>动作</h4><div class="kl-actions"><button class="kl-btn" data-act="book" data-code="${esc(code)}">打开图书档案</button><button class="kl-btn" data-act="full" data-code="${esc(code)}">浏览关系图谱</button></div></div>
      </div>
    </div>`;
  }

  function cardHTML(n) {
    const d = n.role || n.quote || (n.count ? '包含 ' + n.count + ' 项' : '');
    return `<div class="kl-card" data-nid="${esc(n.id)}"><div class="top">${typeDot(n.type)}<span class="ty">${esc(n.type)}</span></div><b>${esc(n.label)}</b><div class="desc">${esc(d || '—')}</div><div class="foot">${n.degree || 0} 条关系</div></div>`;
  }

  function entityHTML(n) {
    const rels = (data.edges || []).filter(e => e.kind !== 'in_book' && (e.source === n.id || e.target === n.id))
      .sort((a, b) => Number(b.relation_basis === 'explicit') - Number(a.relation_basis === 'explicit'));
    const edge = state.edgeId ? rels.find(e => edgeKey(e) === state.edgeId) : null;
    const neighbors = [];
    const seen = new Set();
    const graphRelations = edge ? [edge, ...rels.filter(e => e !== edge)] : rels;
    graphRelations.forEach(e => {
      const o = e.source === n.id ? byId[e.target] : byId[e.source];
      if (o && o.id !== n.id && !seen.has(o.id)) { seen.add(o.id); neighbors.push({ n: o, e }); }
    });
    const b = data.meta.books.find(x => x.code === n.code);
    const tags = (n.disciplines || []).slice(0, 8);
    const visible = neighbors.slice(0, 10);
    const visibleIds = new Set(visible.map(x => x.n.id));
    return `<div class="kl-grid">
      ${railHTML()}
      <div class="kl-main">
        <div class="kl-panel">
          <div class="kl-entityhead">
            <span class="type">${typeDot(n.type)}${esc(n.type)}</span>
            <h2 tabindex="-1">${esc(n.label)}</h2>
            <div class="sub">${esc(n.book || (b && b.title) || '')}${n.place ? ' · ' + esc(n.place) : ''}${n.code ? ' · ' + esc(n.code) : ''}</div>
            ${tags.length ? `<div class="kl-tags">${tags.map(t => `<span class="kl-tag">${esc(t)}</span>`).join('')}</div>` : ''}
          </div>
          <div class="kl-facts">
            <div class="kl-fact"><div class="k">类型</div><div class="v">${esc(n.type)}</div></div>
            <div class="kl-fact"><div class="k">书</div><div class="v">${esc((b && (b.short || b.title)) || n.book || '—')}</div></div>
            <div class="kl-fact"><div class="k">关系</div><div class="v">${rels.length}</div></div>
            <div class="kl-fact"><div class="k">${n.count != null ? '包含' : '领域'}</div><div class="v">${n.count != null ? n.count + ' 项' : esc((tags[0] || '—'))}</div></div>
          </div>
          <section class="kl-sec" aria-labelledby="klRelationTitle">
            <div class="kl-relhead">
              <h3 id="klRelationTitle">直接关系 <span>${rels.length} 条</span></h3>
              ${rels.length ? `<div role="group" aria-label="关系视图">
                <button type="button" class="kl-btn ${state.relationMode === 'list' ? 'on' : ''}" data-act="relation-mode" data-mode="list" aria-pressed="${state.relationMode === 'list'}">关系列表</button>
                <button type="button" class="kl-btn ${state.relationMode === 'graph' ? 'on' : ''}" data-act="relation-mode" data-mode="graph" aria-pressed="${state.relationMode === 'graph'}">局部图</button>
              </div>` : ''}
            </div>
            ${!rels.length ? '<div class="kl-empty">这条记录还没有关系。</div>' : state.relationMode === 'graph'
              ? miniGraph(n, visible, neighbors.length) + relationList(rels.filter(e => visibleIds.has(e.source === n.id ? e.target : e.source)), edge)
              : relationList(rels, edge)}
          </section>
          ${n.role ? `<div class="kl-sec"><h4>说明</h4><div class="kl-p">${esc(n.role)}</div></div>` : ''}
          ${n.achievement ? `<div class="kl-sec"><h4>主要成就</h4><div class="kl-p" style="max-height:170px;overflow:auto">${esc(n.achievement)}</div></div>` : ''}
          ${n.quote ? `<div class="kl-sec"><h4>原文摘录</h4><div class="kl-quote">${esc(n.quote)}</div></div>` : ''}
        </div>
      </div>
      <div class="kl-aside">
        ${asideEvidence(n, edge)}
      </div>
    </div>`;
  }

  function basisBadge(edge) {
    const key = Object.hasOwn(BASIS_HINTS, edge.relation_basis) ? edge.relation_basis : 'interpretation';
    return `<span class="kl-basis" data-basis="${key}" title="${esc(BASIS_HINTS[key])}">${esc(edge.relation_basis_label || '依据待核对')}</span>`;
  }

  function asideEvidence(n, edge) {
    const anchor = n.anchors && n.anchors[0];
    let html = '';
    if (edge) {
      const a = byId[edge.source], b = byId[edge.target];
      const excerpts = edge.evidence?.excerpts?.length ? edge.evidence.excerpts : [
        { quote: edge.evidence?.text || edge.note, anchor: edge.evidence?.anchor }
      ];
      html += `<div class="box" data-relation-evidence="${esc(edgeKey(edge))}" tabindex="-1">
        <h4>关系与依据</h4>
        <div class="qtext"><b>${esc(a?.label || '')}</b> —${esc(edge.rel || '关系')}→ <b>${esc(b?.label || '')}</b></div>
        ${basisBadge(edge)}
        <p class="meta">${esc(BASIS_HINTS[edge.relation_basis] || BASIS_HINTS.interpretation)}</p>
        ${excerpts.map(excerpt => `<div class="kl-quote">${esc(excerpt.quote || '当前没有可展示的关系依据。')}
          ${excerpt.anchor ? `<div><button type="button" class="kl-link" data-act="anchor" data-code="${esc(edge.code || n.code)}" data-anchor="${esc(excerpt.anchor)}">查看原文 ↗</button></div>` : ''}
        </div>`).join('')}${window.RelationMaterials?.render(edge) || ''}</div>`;
    } else {
      html += `<div class="box"><h4>原文证据</h4><div class="kl-quote">${esc((n.raw || n.quote || '这条记录暂时没有原文摘录。').slice(0, 320))}${anchor ? `<div><span class="a" data-act="anchor" data-code="${esc(n.code || '')}" data-anchor="${esc(anchor.id)}">${esc(anchor.label || '原文锚点')} · 在原文中打开 ↗</span></div>` : ''}</div><div class="meta">${esc(n.code || '')}${anchor ? ' · ' + esc(anchor.id) : ''}</div></div>`;
    }
    html += `<div class="box"><h4>动作</h4><div class="kl-actions">
      <button class="kl-btn gold" data-act="book" data-code="${esc(n.code || '')}">打开图书档案</button>
      <button class="kl-btn" data-act="show-node">在图谱中看此对象 ↗</button>
      <button class="kl-btn" data-act="copy" data-text="${esc(n.label + ' · ' + (n.book || ''))}">复制名称与书名</button>
    </div></div>`;
    return html;
  }

  function miniGraph(n, list, total) {
    if (!list.length) return `<div class="kl-mini"><div class="kl-empty">还没有关系</div></div>`;
    const W = 380, H = 300, cx = 190, cy = 150, r = 98;
    let s = `<div class="kl-mini"><svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
    list.forEach((x, i) => {
      const ang = -Math.PI / 2 + i * Math.PI * 2 / list.length;
      const x1 = cx + Math.cos(ang) * r, y1 = cy + Math.sin(ang) * r;
      const selected = edgeKey(x.e) === state.edgeId;
      s += `<line x1="${cx}" y1="${cy}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" stroke="${selected ? '#3159ce' : '#A1AFC5'}" stroke-width="${selected ? 3 : 1.5}"/>`;
    });
    s += `<circle cx="${cx}" cy="${cy}" r="18" fill="${typeColor(n.type)}" stroke="#fff" stroke-width="3"/><circle cx="${cx}" cy="${cy}" r="23" fill="none" stroke="#8099E8"/>`;
    s += `<text x="${cx}" y="${cy + 34}" text-anchor="middle" font-size="10" fill="#4A473B" font-family="Songti SC, serif">${esc(n.label.length > 8 ? n.label.slice(0, 8) + '…' : n.label)}</text>`;
    list.forEach((x, i) => {
      const ang = -Math.PI / 2 + i * Math.PI * 2 / list.length;
      const x1 = cx + Math.cos(ang) * r, y1 = cy + Math.sin(ang) * r;
      const c = typeColor(x.n.type);
      const label = x.n.label.length > 7 ? x.n.label.slice(0, 7) + '…' : x.n.label;
      s += `<g data-nid="${esc(x.n.id)}" style="cursor:pointer"><circle cx="${x1.toFixed(1)}" cy="${y1.toFixed(1)}" r="7" fill="${c}" stroke="#fff" stroke-width="1.5"/><text x="${x1.toFixed(1)}" y="${(y1 + 17).toFixed(1)}" text-anchor="middle" font-size="8.5" fill="#5B5E54" font-family="-apple-system,PingFang SC,sans-serif">${esc(label)}</text></g>`;
    });
    s += `</svg><div class="cap">${total > list.length ? `图中显示 ${list.length} 个对象，全部 ${total} 个对象可在关系列表中查看。` : '图中显示直接关联的对象。'}在下方点「看依据」可核对关系。</div></div>`;
    return s;
  }

  function relationList(rels, selected) {
    const actor = node => node.id === state.nodeId ? `<b>${esc(node.label)}</b>`
      : `<button type="button" data-nid="${esc(node.id)}">${esc(node.label)}</button>`;
    return `<ul class="kl-rellist">` +
      rels.map(e => {
        const a = byId[e.source], b = byId[e.target];
        if (!a || !b) return '';
        return `<li class="kl-relrow">
          <span class="kl-rpath">
            ${actor(a)}
            <span>${esc(e.rel || '关系')} →</span>
            ${actor(b)}
          </span>
          <span class="kl-reltools">${basisBadge(e)}
            <button type="button" class="kl-btn" data-edge="${esc(edgeKey(e))}" aria-pressed="${selected === e}">看依据</button>
          </span>
        </li>`;
      }).join('') + `</ul>`;
  }

  function tableHTML(nodes, limit) {
    const rows = nodes.slice(0, limit || 80);
    return `<table class="kl-table"><thead><tr><th>名称</th><th>类型</th><th>书</th><th>关系</th><th>原文</th><th></th></tr></thead><tbody>` +
      rows.map(n => {
        const aid = n.anchors && n.anchors[0];
        return `<tr data-nid="${esc(n.id)}"><td class="nm">${esc(n.label)}</td><td class="ty">${typeDot(n.type)} ${esc(n.type)}</td><td class="ty">${esc(n.book || (n.kind === 'book' ? '书' : ''))}</td><td class="deg">${n.degree || 0}</td><td class="ev">${esc(aid ? aid.label : (n.role || n.quote || ''))}</td><td class="go">→</td></tr>`;
      }).join('') + `</tbody></table>`;
  }

  function currentRows() {
    if (state.view === 'search') return searchNodes();
    if (state.view === 'entity' && byId[state.nodeId]) return [byId[state.nodeId]];
    if (state.view === 'book') {
      let ns = bookEntities(state.book);
      if (state.type !== '全部') ns = ns.filter(n => n.type === state.type);
      return ns;
    }
    return data.nodes.filter(n => n.kind !== 'book');
  }

  function exportCSV() {
    const rows = currentRows();
    const head = ['名称', '类型', '书', '关系数', '说明', '锚点'];
    const body = rows.map(n => [
      n.label, n.type, n.book || '', n.degree || 0,
      (n.role || n.quote || '').replace(/\s+/g, ' ').slice(0, 200),
      (n.anchors && n.anchors[0] && n.anchors[0].id) || ''
    ]);
    const csv = '\ufeff' + [head, ...body].map(r => r.map(x => '"' + String(x == null ? '' : x).replace(/"/g, '""') + '"').join(',')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    a.download = '图谱实体_' + (state.book || '全部') + '.csv';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast('已导出 ' + rows.length + ' 行');
  }

  window.KGLAB = { render, destroy };
})();
