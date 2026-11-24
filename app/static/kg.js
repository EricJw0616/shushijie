/* 关系图谱：画布、类型筛选和关系详情。 */
(function () {
  'use strict';
  const typeColor = type => RELATION_TYPE_COLORS[type] || '#A4B5CF';
  const esc = window.esc || (s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));
  const jget = window.jget;
  const go = window.go;
  const $ = id => document.getElementById(id);
  const compactGraph = window.matchMedia('(max-width: 700px)');
  const MAX_SCOPE_BOOKS = 100;
  const BOOK_SECTION = { width: 560, height: 416, gap: 26, header: 58 };
  const COLORS = {
    light: {
      relation: '#7386a0', structure: '#899ab0', book: '#627eac', bookFocus: '#4169b4',
      focus: '#285fc5', selected: '#174dba', label: '#28364a', ink: '#1c3254',
      outline: '#f7f8f7', nodeBorder: '#fff', bookBorder: '#395ad0',
      section: '#ffffff', sectionBorder: '#cbd7e7', muted: '#566984', cross: '#7550ae',
    },
    dark: {
      relation: '#879ab8', structure: '#7288a5', book: '#718ba9', bookFocus: '#9ab8d8',
      focus: '#8dddec', selected: '#d2f5fc', label: '#d8e4f7', ink: '#f6f9ff',
      outline: '#101d32', nodeBorder: '#0c1629', bookBorder: '#c8d5ff',
      section: '#142138', sectionBorder: '#354c6e', muted: '#a9bcd7', cross: '#c8a5ff',
    },
  };
  const fullscreenElement = () => document.fullscreenElement || document.webkitFullscreenElement;
  const exitFullscreen = () => (document.exitFullscreen || document.webkitExitFullscreen)?.call(document);
  const graphColors = () => fullscreenElement() === els.fullscreenHost ? COLORS.dark : COLORS.light;
  const BASIS = {
    explicit: {label: '原文明确', note: '书中直接写明这条关系，可对照下方原文核对。', order: 0},
    interpretation: {label: '整理者解读', note: '这是整理者的解读；原文是分析依据，不等于书中直接作出了这项判断。', order: 1},
    field: {label: '字段归类', note: '根据书中字段整理，分类名称可能经过归并。', order: 2},
    structure: {label: '结构导航', note: '表示目录或内容位置，不作为人物关系或事实依据。', order: 3}
  };
  function relationBasis(edge) {
    const key = Object.hasOwn(BASIS, edge.relation_basis) ? edge.relation_basis : 'unknown';
    const item = BASIS[key] || {label: '依据待核对', note: '这条关系尚未标明依据类型，请先核对原文。', order: 4};
    return {...item, key, label: edge.relation_basis_label || item.label};
  }
  function basisChip(edge) {
    const basis = relationBasis(edge);
    return `<span class="kg-basis kg-basis-${basis.key}">${esc(basis.label)}</span>`;
  }

  let ac = null, ro = null, G = null, data = null, viewEl = null, els = {};
  let bookCatalog = [], bookScope = {codes: [], category: ''}, draftScope = null;

  function readScope(arg) {
    if (arg.startsWith('books=')) {
      const query = new URLSearchParams(arg);
      return {
        codes: [...new Set((query.get('books') || '').split(',').filter(Boolean))],
        category: query.get('clc') || '', nodeId: query.get('node') || ''
      };
    }
    const [code, node] = arg.split('/');
    return {codes: code ? [code] : null, category: '', nodeId: code && node ? `${code}:${node}` : ''};
  }

  function scopeArg(scope, nodeId = '') {
    if (scope.codes.length === 1 && !scope.category) {
      const [code] = scope.codes;
      return nodeId ? `${code}/${nodeId.slice(code.length + 1)}` : code;
    }
    const query = new URLSearchParams({books: scope.codes.join(',')});
    if (scope.category) query.set('clc', scope.category);
    if (nodeId) query.set('node', nodeId);
    return query.toString();
  }

  function scopeHash(nodeId = '') {
    const arg = scopeArg(bookScope, nodeId);
    return '#/kg/' + (arg.startsWith('books=') ? encodeURIComponent(arg) : arg.split('/').map(encodeURIComponent).join('/'));
  }

  function edgeKey(edge) {
    const code = edge.code || edge.s?.code || String(edge.source || '').split(':')[0];
    const id = edge.edge_id || edge.id || '';
    return code && id && !id.startsWith(code + ':') ? code + ':' + id : id;
  }
  function rememberSelection(hash) {
    if (!G) return;
    const selection = { edgeId: G.edgeSel ? edgeKey(G.edgeSel) : '', nodeId: G.sel?.id || '',
      detailsHidden: G.detailsHidden, kgViewMode: G.viewMode, typeHidden: [...G.typeHidden],
      overviewMode: G.overviewMode, showCross: G.showCross,
      contextNodeId: G.contextNodeId || '', bookCodes: [...bookScope.codes],
      bookCode: bookScope.codes.length === 1 ? bookScope.codes[0] : '' };
    if (window.RelationMaterials?.remember) window.RelationMaterials.remember(hash || location.hash, selection);
    else if (hash) history.replaceState(history.state, '', hash);
  }

  function shell() {
    return `<div class="kg-shell">
      <canvas id="kgCanvas"></canvas>
      <div class="kg-toolbar">
        <div class="kg-scope">
          <button type="button" class="kg-scope-trigger" data-kg-action="scope" aria-expanded="false" aria-controls="kgScopePanel" disabled>
            图书范围 <span class="kg-scope-summary">正在读取…</span><span aria-hidden="true">⌄</span>
          </button>
          <section class="kg-scope-panel" id="kgScopePanel" aria-labelledby="kgScopeTitle" hidden>
            <header><h2 id="kgScopeTitle">选择图谱中的书</h2><p>按分类缩小书目，可跨分类勾选多本。</p></header>
            <label class="kg-scope-field">中图分类<select id="kgScopeCategory"><option value="">全部分类</option></select></label>
            <label class="kg-scope-field">书名<input id="kgScopeQuery" type="search" placeholder="输入书名搜索" autocomplete="off"></label>
            <div class="kg-scope-books" id="kgScopeBooks"></div>
            <div class="kg-scope-footer">
              <p id="kgScopeCount" role="status"></p>
              <div>
                <button type="button" class="btn sm ghost" data-kg-action="clear-scope">清空</button>
                <button type="button" class="btn sm ghost" data-kg-action="cancel-scope">取消</button>
                <button type="button" class="btn sm primary" data-kg-action="apply-scope">应用</button>
              </div>
            </div>
          </section>
        </div>
        <div class="kg-view-layout" role="group" aria-label="图谱布局" hidden>
          <button type="button" data-layout="network" aria-pressed="true">关系网络</button>
          <button type="button" data-layout="books" aria-pressed="false">按书浏览</button>
        </div>
        <button type="button" class="kg-cross-toggle" aria-controls="kgCrossPanel" aria-expanded="false">跨书关联</button>
        <div class="kg-pill" id="kgTypes"></div>
        <div class="kg-pill kg-search">
          <input id="kgq" aria-label="搜索图谱节点" placeholder="搜人物 / 事件 / 概念" autocomplete="off">
          <div class="kg-sug" id="kgsug"></div>
        </div>
        <button class="kg-v2" data-kg-action="lookup">查人物与关系 ↗</button>
        <div class="kg-hint">滚轮缩放 · 拖拽平移 · 点节点看详情</div>
        <div class="kg-focus-bar" hidden>
          <span class="kg-focus-label"></span>
          <button type="button" data-kg-action="details" hidden>查看详情</button>
          <button type="button" data-kg-action="overview">返回全图</button>
        </div>
        <button type="button" data-kg-action="exit-fullscreen" hidden>退出全屏</button>
      </div>
      <section id="kgCrossPanel" class="kg-cross-panel" aria-label="跨书关联" hidden></section>
      <div class="kg-zoom">
        <button data-z="1.2" title="放大">＋</button>
        <button data-z="0.83" title="缩小">－</button>
        <button type="button" data-z="fit" title="适应画布" aria-label="适应画布">
          <svg class="kg-zoom-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <rect x="4.5" y="6" width="15" height="12" rx="1.5"/><path d="M9 12h6m-3-3v6"/>
          </svg>
        </button>
        <button type="button" data-kg-action="fullscreen" aria-pressed="false" title="全屏" aria-label="全屏">
          <svg class="kg-zoom-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <path data-expand d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5"/>
            <path data-collapse d="M4 9h5V4m6 0v5h5m0 6h-5v5m-6 0v-5H4"/>
          </svg>
        </button>
      </div>
      <div class="kg-legend" id="kglegend" aria-label="连线和节点图例"></div>
      <div class="kg-stats" id="kgstats"></div>
      <aside class="kg-panel" id="kgpanel" inert></aside>
    </div>`;
  }

  async function render(view, code) {
    destroy(true);
    ac = new AbortController();
    view.className = 'view kg-page';
    view.innerHTML = shell();
    viewEl = view;
    els = { cv: $('kgCanvas'), panel: $('kgpanel'), types: $('kgTypes'), q: $('kgq'), sug: $('kgsug'), legend: $('kglegend'), stats: $('kgstats'),
      shell: view.querySelector('.kg-shell'), toolbar: view.querySelector('.kg-toolbar'), focusBar: view.querySelector('.kg-focus-bar'),
      fullscreenHost: view.parentElement,
      layout: view.querySelector('.kg-view-layout'), crossToggle: view.querySelector('.kg-cross-toggle'), crossPanel: $('kgCrossPanel'),
      scopeTrigger: view.querySelector('[data-kg-action="scope"]'), scopePanel: $('kgScopePanel'), scopeCategory: $('kgScopeCategory'),
      scopeQuery: $('kgScopeQuery'), scopeBooks: $('kgScopeBooks'), scopeCount: $('kgScopeCount') };
    bindShell();
    await load(readScope(String(code || '')), ac.signal);
  }

  async function load(request, signal) {
    try {
      const saved = window.RelationMaterials?.selection() || {};
      const catalog = await jget('/api/kg/books?view=picker');
      if (signal.aborted) return;
      bookCatalog = (catalog.books || []).filter(book => book.status === '已建图');
      const initial = bookCatalog.find(book => book.code === 'B59') || bookCatalog[0];
      const wanted = request.codes || (saved.bookCode ? [saved.bookCode] : initial ? [initial.code] : []);
      bookScope = {codes: wanted.filter(code => bookCatalog.some(book => book.code === code)), category: request.category};
      updateScopeTrigger();
      const badge = $('navKgCount');
      if (badge) badge.textContent = String(bookCatalog.length);
      if (!bookScope.codes.length) {
        els.stats.textContent = wanted.length ? '所选书目已变动，请重新选书' : '暂无可浏览的图谱';
        return;
      }
      if (bookScope.codes.length < wanted.length) toast('部分图书已不在图谱书目中，已保留其余所选图书');
      if (bookScope.codes.length > MAX_SCOPE_BOOKS) {
        els.stats.textContent = `每次最多浏览 ${MAX_SCOPE_BOOKS} 本，请调整图书范围`;
        return;
      }
      els.stats.textContent = '正在加载所选图书…';
      const query = bookScope.codes.length === 1 ? {code: bookScope.codes[0]} : {codes: bookScope.codes.join(',')};
      const result = await jget('/api/kg/view?' + new URLSearchParams(query));
      if (signal.aborted) return;
      data = result;
      if (!data.meta.books.length) {
        els.cv.style.display = 'none';
        els.stats.textContent = '暂无图谱';
        return;
      }
      els.cv.style.display = '';
      const sameScope = !Array.isArray(saved.bookCodes) || (saved.bookCodes.length === bookScope.codes.length && saved.bookCodes.every(code => bookScope.codes.includes(code)));
      const restored = sameScope ? saved : {};
      initGraph(restored);
      const nodeId = request.nodeId || restored.nodeId;
      if (nodeId) {
        const colon = nodeId.indexOf(':');
        const n = data.nodes.find(x => x.id === nodeId || (x.kind === 'entity' && x.code === nodeId.slice(0, colon) && x.label === nodeId.slice(colon + 1)));
        if (n && G) G.selectNode(n, false);
      }
      const matches = restored.edgeId ? G.edges.filter(e => edgeKey(e) === restored.edgeId || (e.id === restored.edgeId && (!restored.bookCode || e.s.code === restored.bookCode))) : [];
      if (matches.length === 1) G.selectEdge(matches[0], false);
      if (restored.detailsHidden && (G.sel || G.edgeSel)) G.setDetails(false);
    } catch (e) {
      if (!signal.aborted) els.stats.textContent = '图谱加载失败，请刷新或重新选书';
    }
  }

  function updateScopeTrigger() {
    const titles = bookCatalog.filter(book => bookScope.codes.includes(book.code)).map(book => book.title);
    els.scopeTrigger.querySelector('.kg-scope-summary').textContent = titles.length === 1 ? titles[0] : `${titles.length} 本书`;
    els.scopeTrigger.title = titles.join('、');
    els.scopeTrigger.disabled = false;
  }

  function openScope() {
    draftScope = {codes: new Set(bookScope.codes)};
    const categories = new Map();
    for (const book of bookCatalog) {
      const code = book.clc_code || 'unclassified';
      const entry = categories.get(code) || {name: book.clc_name || '未分类', count: 0};
      entry.count++;
      categories.set(code, entry);
    }
    els.scopeCategory.innerHTML = '<option value="">全部分类</option>' + [...categories].sort(([a], [b]) => a.localeCompare(b))
      .map(([code, {name, count}]) => `<option value="${esc(code)}">${code === 'unclassified' ? '' : `${esc(code)} · `}${esc(name)}（${count}）</option>`).join('');
    els.scopeCategory.value = categories.has(bookScope.category) ? bookScope.category : '';
    els.scopeQuery.value = '';
    els.scopePanel.hidden = false;
    els.scopeTrigger.setAttribute('aria-expanded', 'true');
    renderScopeBooks();
    els.scopeCategory.focus({preventScroll: true});
  }

  function closeScope(restoreFocus = true) {
    draftScope = null;
    els.scopePanel.hidden = true;
    els.scopeTrigger.setAttribute('aria-expanded', 'false');
    if (restoreFocus) els.scopeTrigger.focus({preventScroll: true});
  }

  function renderScopeBooks() {
    const query = els.scopeQuery.value.trim().toLocaleLowerCase();
    const category = els.scopeCategory.value;
    const books = bookCatalog.filter(book => (!category || (book.clc_code || 'unclassified') === category) &&
      (!query || String(book.title || '').toLocaleLowerCase().includes(query)));
    els.scopeBooks.innerHTML = books.length ? books.map(book => `<label class="kg-scope-book">
      <input type="checkbox" value="${esc(book.code)}"${draftScope.codes.has(book.code) ? ' checked' : ''}>
      <span>${esc(book.title)}</span></label>`).join('') : `<p>${bookCatalog.length ? '当前筛选没有匹配的图书。' : '还没有可浏览的图谱图书。'}</p>`;
    updateScopeCount();
  }

  function updateScopeCount() {
    const visibleSelected = els.scopeBooks.querySelectorAll('input:checked').length;
    const count = draftScope.codes.size;
    const elsewhere = count - visibleSelected;
    els.scopeCount.textContent = count ? `已选 ${count} 本${elsewhere ? ` · ${elsewhere} 本不在当前筛选中` : ''}` : '请至少勾选一本书';
    if (count > MAX_SCOPE_BOOKS) els.scopeCount.textContent += ` · 每次最多 ${MAX_SCOPE_BOOKS} 本`;
    els.scopePanel.querySelector('[data-kg-action="apply-scope"]').disabled = count === 0 || count > MAX_SCOPE_BOOKS;
    els.scopePanel.querySelector('[data-kg-action="clear-scope"]').disabled = count === 0;
  }

  function applyScope() {
    if (!draftScope?.codes.size || draftScope.codes.size > MAX_SCOPE_BOOKS) return;
    const next = {codes: [...draftScope.codes], category: els.scopeCategory.value};
    const sameBooks = next.codes.length === bookScope.codes.length && next.codes.every(code => bookScope.codes.includes(code));
    closeScope();
    if (!sameBooks || next.category !== bookScope.category) go('kg', scopeArg(next));
  }

  function initGraph(restored = {}) {
    const cv = els.cv, ctx = cv.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    function fitCanvas() {
      const w = els.shell.clientWidth, h = els.shell.clientHeight;
      cv.width = Math.max(1, w * dpr); cv.height = Math.max(1, h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return [w, h];
    }
    let [W, H] = fitCanvas();

    const books = data.nodes.filter(n => n.kind === 'book');
    const showBooks = books.length > 1;
    const byId = {};
    const groups = new Map(books.map(book => {
      book.r = 10; book.x = 0; book.y = 0;
      byId[book.id] = book;
      return [book.code, { book, nodes: [], center: { x: 0, y: 0 }, frame: null, visibleCount: 0 }];
    }));

    const entities = data.nodes.filter(n => n.kind === 'entity' && groups.has(n.code));
    const keyTypes = new Set(['人物', '事件', '工程', '概念', '案例']);
    const labelOrder = [...entities].sort((a, b) =>
      Number(keyTypes.has(b.type)) - Number(keyTypes.has(a.type)) || (b.degree || 0) - (a.degree || 0));
    entities.forEach(n => {
      const group = groups.get(n.code), i = group.nodes.length;
      const ang = i * 2.399, rr = 60 + (i % 11) * 16;
      n.r = 4 + Math.sqrt(Math.max(1, n.size || 1)) * 1.5;
      n.x = Math.cos(ang) * rr;
      n.y = Math.sin(ang) * rr;
      n.vx = 0; n.vy = 0;
      group.nodes.push(n);
      byId[n.id] = n;
    });

    function arrangeBooks(initial = false) {
      const { width, height, gap, header } = BOOK_SECTION;
      const maxColumns = G.W >= 1100 ? 4 : G.W >= 680 ? 3 : 2;
      const columns = Math.min(books.length, maxColumns, Math.ceil(Math.sqrt(books.length * G.W / Math.max(1, G.H))));
      let i = 0;
      for (const group of groups.values()) {
        let x = G.W / 2, y = G.H / 2, scale = 1;
        if (showBooks) {
          const col = i % columns, row = Math.floor(i / columns);
          const first = row * columns, rowCount = Math.min(columns, books.length - first);
          const left = (col + (columns - rowCount) / 2) * (width + gap);
          const top = row * (height + gap);
          group.frame = { x: left, y: top, width, height };
          group.book.x = left + 30;
          group.book.y = top + header / 2;
          x = left + width / 2;
          y = top + (height + header) / 2;
          if (initial) {
            const rx = Math.max(1, ...group.nodes.map(n => Math.abs(n.x) + n.r));
            const ry = Math.max(1, ...group.nodes.map(n => Math.abs(n.y) + n.r));
            scale = Math.min(1, (width / 2 - 28) / rx, ((height - header) / 2 - 27) / ry);
          }
        }
        for (const n of group.nodes) {
          n.x = x + (n.x - group.center.x) * scale;
          n.y = y + (n.y - group.center.y) * scale;
        }
        group.center = { x, y };
        i++;
      }
    }

    const crossEdges = (data.cross_links || []).map(link => ({ ...link, kind: 'cross_book',
      rel: link.label, s: byId[link.source], t: byId[link.target] })).filter(e => e.s && e.t);
    const edges = data.edges.map(e => ({ ...e, s: byId[e.source], t: byId[e.target] }))
      .filter(e => e.s && e.t && (showBooks || e.kind !== 'in_book'));
    const adj = {};
    edges.forEach(e => {
      if (e.kind === 'in_book') return;
      (adj[e.s.id] = adj[e.s.id] || new Set()).add(e.t.id);
      (adj[e.t.id] = adj[e.t.id] || new Set()).add(e.s.id);
    });
    edges.push(...crossEdges);
    const pairs = new Map();
    for (const edge of edges) {
      if (edge.kind === 'in_book') continue;
      const key = [edge.s.id, edge.t.id].sort().join('\u0000');
      if (!pairs.has(key)) pairs.set(key, []);
      pairs.get(key).push(edge);
    }
    for (const parallel of pairs.values()) {
      parallel.forEach((edge, i) => {
        const lane = parallel.length === 1 ? 1 : 2 * i - parallel.length + 1;
        edge.lane = (edge.s.id < edge.t.id ? 1 : -1) * lane;
      });
    }

    const knownTypes = (data.meta.types || []).map(t => t.name);
    const hidden = new Set(Array.isArray(restored.typeHidden) ? restored.typeHidden.filter(t => knownTypes.includes(t)) : data.meta.defaultHidden || []);
    if (!Array.isArray(restored.typeHidden) && knownTypes.includes('籍贯')) hidden.add('籍贯');

    G = { cv, ctx, W, H, dpr, nodes: [...(showBooks ? books : []), ...entities], edges, adj, books, entities,
      overviewMode: restored.overviewMode === 'books' ? 'books' : 'network', showCross: Boolean(restored.showCross),
      typeHidden: hidden, allTypes: (data.meta.types || []).map(t => t.name),
      types: (data.meta.types || []).map(t => t.name),
      sel: null, hover: null, edgeSel: null, focusIds: null, detailsHidden: false,
      viewMode: restored.kgViewMode === 'list' ? 'list' : 'graph', contextNodeId: byId[restored.contextNodeId] ? restored.contextNodeId : '', cam: { x: W / 2, y: H / 2, k: 1 },
      drag: null, dragFrame: 0, alpha: 0, raf: 0 };
    const visible = n => n.kind === 'book' || !G.typeHidden.has(n.type);
    const edgeEnabled = edge => edge.kind !== 'cross_book' || G.showCross || G.sel === edge.s || G.sel === edge.t;
    const bookCards = () => showBooks && G.overviewMode === 'books';
    G.visible = visible;

    function repel(ns, a) {
      for (let i = 0; i < ns.length; i++) {
        const A = ns[i];
        for (let j = i + 1; j < ns.length; j++) {
          const B = ns[j];
          let dx = B.x - A.x, dy = B.y - A.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 9) d2 = 9;
          if (d2 > 120000) continue;
          const f = 1150 * a / d2;
          dx *= f; dy *= f;
          A.vx -= dx; A.vy -= dy; B.vx += dx; B.vy += dy;
        }
      }
    }

    function step(a) {
      for (const group of groups.values()) repel(group.nodes.filter(visible), a);
      for (const e of G.edges) {
        if (e.kind === 'in_book' || e.kind === 'cross_book' || e.s.code !== e.t.code) continue;
        if (!visible(e.s) || !visible(e.t)) continue;
        const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
        const d = Math.hypot(dx, dy) || 1;
        const len = e.kind === 'relation' ? 96 : 78;
        const f = (d - len) * .022 * a;
        e.s.vx += dx * f / d; e.s.vy += dy * f / d;
        e.t.vx -= dx * f / d; e.t.vy -= dy * f / d;
      }
      for (const n of G.entities) {
        if (!visible(n)) continue;
        if (G.drag?.node === n || n.pinned) { n.vx = 0; n.vy = 0; continue; }
        const { center, frame } = groups.get(n.code);
        const dx = n.x - center.x, dy = n.y - center.y;
        const d = Math.hypot(dx, dy) || 1;
        if (d > 170) { n.vx -= dx / d * (d - 170) * .05 * a; n.vy -= dy / d * (d - 170) * .05 * a; }
        n.vx -= dx * .024 * a;
        n.vy -= dy * .024 * a;
        n.vx *= .84; n.vy *= .84;
        n.x += n.vx; n.y += n.vy;
        keepInside(n, frame);
      }
    }

    function keepInside(n, frame) {
      if (!frame) return;
      const margin = Math.max(22, n.r + 8);
      n.x = Math.max(frame.x + margin, Math.min(n.x, frame.x + frame.width - margin));
      n.y = Math.max(frame.y + BOOK_SECTION.header + margin, Math.min(n.y, frame.y + frame.height - margin));
    }

    for (let k = 0; k < 220; k++) step(1 - k / 360);
    arrangeBooks(true);
    G.alpha = 0;

    const shown = n => visible(n) && (!G.focusIds || G.focusIds.has(n.id));
    const displayRadius = n => Math.max(n.r, (G.focusIds || n.kind === 'book' ? 5 : 2.2) / G.cam.k);

    function separateNodes() {
      const nodes = G.entities.filter(shown);
      const anchor = G.drag?.node;
      if (nodes.length < 2) return;
      const minGap = 3 / G.cam.k;
      const size = 2 * Math.max(...nodes.map(displayRadius)) + minGap;
      for (let pass = 0; pass < 3; pass++) {
        const grid = new Map();
        for (const n of nodes) {
          const col = Math.floor(n.x / size), row = Math.floor(n.y / size);
          for (let oy = -1; oy <= 1; oy++) {
            for (let ox = -1; ox <= 1; ox++) {
              for (const other of grid.get(`${col + ox},${row + oy}`) || []) {
                const dx = n.x - other.x, dy = n.y - other.y;
                const d = Math.hypot(dx, dy);
                const overlap = displayRadius(n) + displayRadius(other) + minGap - d;
                if (overlap <= 0) continue;
                const nx = d ? dx / d : 1, ny = d ? dy / d : 0;
                const share = n === anchor ? 0 : other === anchor ? 1 :
                  n.pinned === other.pinned ? .5 : n.pinned ? 0 : 1;
                n.x += nx * overlap * share; n.y += ny * overlap * share;
                other.x -= nx * overlap * (1 - share); other.y -= ny * overlap * (1 - share);
                if (bookCards()) {
                  keepInside(n, groups.get(n.code).frame);
                  keepInside(other, groups.get(other.code).frame);
                }
              }
            }
          }
          const key = `${Math.floor(n.x / size)},${Math.floor(n.y / size)}`;
          if (!grid.has(key)) grid.set(key, []);
          grid.get(key).push(n);
        }
      }
    }

    function updateFocusScope() {
      const edge = G.edgeSel;
      const node = G.sel?.kind === 'entity' ? G.sel : null;
      const local = Boolean(edge || node);
      G.focusIds = null;
      if (local) {
        if (edge) {
          G.focusIds = new Set([edge.s.id, edge.t.id]);
          els.focusBar.querySelector('.kg-focus-label').textContent = edge.kind === 'cross_book'
            ? `${edge.via} · ${edge.basis}` : `${edge.s.label} → ${edge.t.label}`;
        } else {
          const related = [...new Set([...linksFor(node).filter(e => visible(e.s) && visible(e.t)), ...nodeRelations(node)]
            .map(e => e.s === node ? e.t : e.s))];
          const neighbors = related.slice(0, compactGraph.matches ? 8 : 18);
          G.focusIds = new Set([node.id, ...neighbors.map(n => n.id)]);
          const count = related.length > neighbors.length ? `${neighbors.length}/${related.length}` : related.length;
          els.focusBar.querySelector('.kg-focus-label').textContent = `${node.label} · ${count} 个相关对象`;
        }
        const detailsButton = els.focusBar.querySelector('[data-kg-action="details"]');
        detailsButton.hidden = !G.detailsHidden;
        detailsButton.textContent = G.viewMode === 'list' ? '查看关系列表' : '查看详情';
      }
      els.shell.classList.toggle('kg-focused', Boolean(local));
      els.layout.hidden = !showBooks || local;
      els.focusBar.hidden = !local;
    }

    function fitView() {
      updateFocusScope();
      const vn = G.nodes.filter(shown);
      els.shell.style.setProperty('--kg-list-top', `${els.toolbar.offsetTop + els.toolbar.offsetHeight + 12}px`);
      if (!vn.length) return;
      const boxes = showBooks && !G.focusIds ? [...groups.values()].map(g => g.frame) : [];
      if (!boxes.length || !bookCards()) {
        boxes.push(...vn.map(n => ({ x: n.x - n.r, y: n.y - n.r, width: n.r * 2, height: n.r * 2 })));
      }
      const minx = Math.min(...boxes.map(b => b.x)), maxx = Math.max(...boxes.map(b => b.x + b.width));
      const miny = Math.min(...boxes.map(b => b.y)), maxy = Math.max(...boxes.map(b => b.y + b.height));
      const left = G.edgeSel?.kind === 'cross_book' ? Math.min(96, G.W * .14) : compactGraph.matches ? 22 : 32;
      const panelOpen = els.panel.classList.contains('open') && G.viewMode !== 'list';
      const right = !compactGraph.matches && panelOpen ? Math.max(left + 80, els.panel.offsetLeft - left) : G.W - left;
      const top = els.toolbar.offsetTop + els.toolbar.offsetHeight + 18;
      const footer = compactGraph.matches && panelOpen ? els.panel.offsetTop : els.legend.offsetTop;
      const bottom = Math.max(top + 34, footer - 30);
      const k = Math.min((right - left) / Math.max(maxx - minx, 44), (bottom - top) / Math.max(maxy - miny, 44), G.focusIds ? 2.35 : 1.25);
      G.cam.k = Math.max(.08, k);
      G.cam.x = (minx + maxx) / 2 + (G.W - left - right) / (2 * G.cam.k);
      G.cam.y = (miny + maxy) / 2 + (G.H - top - bottom) / (2 * G.cam.k);
    }
    G.fitView = fitView;
    fitView();
    separateNodes();

    function requestTick() { cancelAnimationFrame(G.raf); G.raf = requestAnimationFrame(tick); }
    function tick() {
      if (!G) return;
      if (G.alpha > .004 || G.drag) {
        G.alpha *= .97;
        step(G.alpha);
        draw();
        G.raf = requestAnimationFrame(tick);
      }
    }
    G.reheat = () => { if (!G) return; G.alpha = Math.max(G.alpha, .35); requestTick(); };

    const toWorld = (mx, my) => ({ x: (mx - G.W / 2) / G.cam.k + G.cam.x, y: (my - G.H / 2) / G.cam.k + G.cam.y });

    function bookSections(colors) {
      const { ctx, cam } = G;
      for (const group of groups.values()) {
        const { x, y, width, height } = group.frame;
        const book = group.book;
        const active = book === G.sel || book === G.hover;
        if (bookCards()) {
          ctx.beginPath();
          ctx.roundRect(x, y, width, height, Math.min(14, 8 / cam.k));
          ctx.fillStyle = colors.section;
          ctx.fill();
          ctx.lineWidth = (active ? 1.5 : 1) / cam.k;
          ctx.strokeStyle = active ? colors.focus : colors.sectionBorder;
          ctx.stroke();
        }
        if (width * cam.k < 64) continue;

        const count = `${group.visibleCount} 节点`;
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'right';
        ctx.font = `${11 / cam.k}px system-ui, sans-serif`;
        const showCount = width * cam.k >= 178;
        const right = x + width - 12 / cam.k;
        const countWidth = showCount ? ctx.measureText(count).width + 8 / cam.k : 0;
        ctx.fillStyle = colors.muted;
        if (showCount) ctx.fillText(count, right, book.y);

        const titleLeft = book.x + displayRadius(book) + 7 / cam.k;
        let title = book.label;
        const available = right - titleLeft - countWidth;
        ctx.textAlign = 'left';
        ctx.font = `600 ${13 / cam.k}px system-ui, sans-serif`;
        if (ctx.measureText(title).width > available) {
          const suffix = title.endsWith('》') ? '…》' : '…';
          if (suffix.endsWith('》')) title = title.slice(0, -1);
          while (title.length > 1 && ctx.measureText(title + suffix).width > available) title = title.slice(0, -1);
          title += suffix;
        }
        ctx.fillStyle = colors.ink;
        if (available > 20 / cam.k) ctx.fillText(title, titleLeft, book.y);
      }
      ctx.textBaseline = 'alphabetic';
    }

    function controlPoint(edge) {
      const { s, t } = edge;
      const dx = t.x - s.x, dy = t.y - s.y, length = Math.hypot(dx, dy) || 1;
      const lane = edge.lane ?? 1;
      const cross = edge.kind === 'cross_book';
      const offset = Math.sign(lane) * Math.min(length * (cross ? .22 : .32), Math.abs(lane) * (cross ? 92 : 30) / G.cam.k);
      return { x: (s.x + t.x) / 2 - dy * offset / length, y: (s.y + t.y) / 2 + dx * offset / length };
    }

    function trace(edge, control = controlPoint(edge)) {
      G.ctx.beginPath();
      G.ctx.moveTo(edge.s.x, edge.s.y);
      G.ctx.quadraticCurveTo(control.x, control.y, edge.t.x, edge.t.y);
      G.ctx.stroke();
    }

    function markSharedObject(edge, control, colors) {
      const { ctx, cam } = G;
      const x = (edge.s.x + 2 * control.x + edge.t.x) / 4;
      const y = (edge.s.y + 2 * control.y + edge.t.y) / 4 - 22 / cam.k;
      ctx.save();
      ctx.font = `600 ${13 / cam.k}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const half = ctx.measureText(edge.via).width / 2 + 10 / cam.k;
      ctx.beginPath();
      ctx.roundRect(x - half, y - 12 / cam.k, half * 2, 24 / cam.k, 7 / cam.k);
      ctx.fillStyle = colors.section;
      ctx.fill();
      ctx.strokeStyle = colors.cross;
      ctx.lineWidth = 1 / cam.k;
      ctx.stroke();
      ctx.fillStyle = colors.cross;
      ctx.fillText(edge.via, x, y);
      ctx.restore();
    }

    function draw() {
      if (!G) return;
      const { ctx, cam } = G;
      ctx.clearRect(0, 0, G.W, G.H);
      ctx.save();
      ctx.translate(G.W / 2, G.H / 2); ctx.scale(cam.k, cam.k); ctx.translate(-cam.x, -cam.y);
      const selectedEdge = G.edgeSel;
      const focus = selectedEdge ? null : G.sel || G.hover;
      const fadj = focus ? (G.adj[focus.id] || new Set()) : null;
      const colors = graphColors();
      ctx.lineCap = 'round';
      if (showBooks && !G.focusIds) bookSections(colors);

      if (showBooks && !G.focusIds && (focus || G.showBookLines)) {
        ctx.lineWidth = 1.25 / cam.k;
        ctx.setLineDash([5 / cam.k, 5 / cam.k]);
        for (const e of G.edges) {
          if (e.kind !== 'in_book' || !visible(e.s) || !visible(e.t)) continue;
          const touched = e.t === focus || (e.s === focus && groups.get(e.s.code).visibleCount <= 28);
          if (!touched && !G.showBookLines) continue;
          ctx.strokeStyle = touched ? colors.bookFocus : colors.book;
          ctx.globalAlpha = focus && !touched ? .3 : 1;
          trace(e);
        }
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);
      }
      for (const e of G.edges) {
        if (e.kind === 'in_book' || e === selectedEdge || !edgeEnabled(e)) continue;
        if (!shown(e.s) || !shown(e.t)) continue;
        const touch = focus && (e.s === focus || e.t === focus || (focus.kind === 'book' && e.s.code === focus.code));
        const structure = e.relation_basis === 'structure' && !G.focusIds;
        const cross = e.kind === 'cross_book';
        ctx.strokeStyle = cross ? colors.cross : touch ? colors.focus : structure ? colors.structure : colors.relation;
        ctx.globalAlpha = selectedEdge || (focus && !touch) ? .22 : 1;
        ctx.lineWidth = (cross || touch ? 2 : structure ? .85 : 1.25) / cam.k;
        trace(e);
      }
      ctx.globalAlpha = 1;

      if (selectedEdge) {
        const {s, t} = selectedEdge;
        const cross = selectedEdge.kind === 'cross_book';
        const control = controlPoint(selectedEdge);
        ctx.strokeStyle = cross ? colors.cross : colors.selected;
        ctx.lineWidth = 2.6 / cam.k;
        trace(selectedEdge, control);
        const length = Math.hypot(t.x - s.x, t.y - s.y);
        const head = 7 / cam.k;
        if (!cross && length > displayRadius(t) + displayRadius(s) + head * 2) {
          const tangent = Math.hypot(t.x - control.x, t.y - control.y) || 1;
          const dx = (t.x - control.x) / tangent, dy = (t.y - control.y) / tangent;
          const distance = displayRadius(t) + 4 / cam.k;
          const x = t.x - dx * distance, y = t.y - dy * distance;
          ctx.fillStyle = colors.selected;
          ctx.beginPath(); ctx.moveTo(x, y);
          ctx.lineTo(x - dx * head - dy * head * .6, y - dy * head + dx * head * .6);
          ctx.lineTo(x - dx * head + dy * head * .6, y - dy * head - dx * head * .6);
          ctx.closePath(); ctx.fill();
        }
        if (cross) markSharedObject(selectedEdge, control, colors);
      }

      for (const n of G.nodes) {
        if (!shown(n)) continue;
        const book = n.kind === 'book';
        const selected = n === G.sel || (selectedEdge && (n === selectedEdge.s || n === selectedEdge.t));
        const related = focus && (focus.kind === 'book' ? n.code === focus.code : n === focus || fadj?.has(n.id));
        const radius = displayRadius(n);
        ctx.globalAlpha = (focus || selectedEdge) && !selected && !related ? .24 : 1;
        ctx.beginPath(); ctx.arc(n.x, n.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = typeColor(n.type); ctx.fill();
        ctx.strokeStyle = book ? colors.bookBorder : colors.nodeBorder;
        ctx.lineWidth = (book ? 2.1 : 1.2) / Math.min(1, cam.k); ctx.stroke();
        if (selected) {
          ctx.strokeStyle = colors.selected; ctx.lineWidth = 1.6 / cam.k;
          ctx.beginPath(); ctx.arc(n.x, n.y, radius + 4 / cam.k, 0, Math.PI * 2); ctx.stroke();
          ctx.strokeStyle = colors.focus + '66'; ctx.lineWidth = 1 / cam.k;
          ctx.beginPath(); ctx.arc(n.x, n.y, radius + 8 / cam.k, 0, Math.PI * 2); ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }
      drawLabels(colors, focus);
      ctx.restore();
      updateStats();
    }
    G.draw = draw;

    function drawLabels(colors, focus) {
      const { ctx, cam } = G;
      const cells = new Map(), cellSize = 32;
      const xOffset = G.W / 2 - cam.x * cam.k;
      const yOffset = G.H / 2 - cam.y * cam.k;
      const toolbarBottom = els.toolbar.offsetTop + els.toolbar.offsetHeight;
      const panelOpen = els.panel.classList.contains('open');
      const right = panelOpen && !compactGraph.matches ? els.panel.offsetLeft - 5 : G.W - 5;
      const bottom = (panelOpen && compactGraph.matches ? els.panel.offsetTop : els.legend.offsetTop) - 4;
      const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w &&
        a.y < b.y + b.h && b.y < a.y + a.h;
      function inCells(box, visit) {
        for (let row = Math.floor(box.y / cellSize); row <= Math.floor((box.y + box.h) / cellSize); row++) {
          for (let col = Math.floor(box.x / cellSize); col <= Math.floor((box.x + box.w) / cellSize); col++) {
            if (visit(`${col},${row}`)) return true;
          }
        }
        return false;
      }
      function reserve(box) {
        inCells(box, key => {
          const cell = cells.get(key);
          if (cell) cell.push(box);
          else cells.set(key, [box]);
        });
      }
      for (const n of G.nodes) {
        if (!shown(n)) continue;
        const cx = n.x * cam.k + xOffset, cy = n.y * cam.k + yOffset;
        const r = displayRadius(n) * cam.k + 1;
        if (cx + r < 0 || cx - r > right || cy + r < toolbarBottom || cy - r > bottom) continue;
        reserve({ x: cx - r, y: cy - r, w: r * 2, h: r * 2 });
      }
      if (showBooks && !G.focusIds) {
        for (const {frame} of groups.values()) {
          reserve({ x: frame.x * cam.k + xOffset, y: frame.y * cam.k + yOffset,
            w: frame.width * cam.k, h: BOOK_SECTION.header * cam.k });
        }
      }

      const nodes = [G.sel, G.hover, G.edgeSel?.s, G.edgeSel?.t, ...labelOrder];
      for (const n of new Set(nodes)) {
        if (!n || n.kind === 'book' || !shown(n)) continue;
        const active = n === G.sel || n === G.hover || n === G.edgeSel?.s || n === G.edgeSel?.t;
        const cx = n.x * cam.k + xOffset, cy = n.y * cam.k + yOffset;
        if (cx < 0 || cx > right || cy < toolbarBottom || cy > bottom) continue;
        const limit = active || G.focusIds ? 15 : 9;
        const label = n.label.length > limit ? n.label.slice(0, limit) + '…' : n.label;
        const size = active ? 14 : 12;
        ctx.font = `${active ? '600 ' : ''}${size / cam.k}px system-ui, sans-serif`;
        const w = ctx.measureText(label).width * cam.k + 6, h = size + 4;
        const gap = displayRadius(n) * cam.k + 4;
        const west = cx - gap - w, east = cx + gap;
        const north = cy - gap - h, south = cy + gap;
        const centered = cx - w / 2;
        const shift = Math.min(16, w / 3);
        const candidates = [[centered, south], [east, cy - h / 2], [centered, north], [west, cy - h / 2],
          [centered - shift, south], [centered + shift, south], [centered - shift, north], [centered + shift, north],
          [east, south - 3], [west, south - 3], [east, north + 3], [west, north + 3]];
        const box = candidates.map(([x, y]) => ({ x, y, w, h })).find(candidate =>
          candidate.x >= 4 && candidate.x + w <= right && candidate.y >= toolbarBottom + 3 &&
          candidate.y + h <= bottom && !inCells(candidate, key => cells.get(key)?.some(other => overlaps(candidate, other))));
        if (!box) continue;
        reserve(box);
        ctx.globalAlpha = focus && !active && focus.code !== n.code ? .35 : 1;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.lineWidth = 3 / cam.k;
        ctx.strokeStyle = !G.focusIds && bookCards() ? colors.section : colors.outline;
        const world = toWorld(box.x + w / 2, box.y + h / 2);
        ctx.strokeText(label, world.x, world.y);
        ctx.fillStyle = active ? colors.ink : colors.label;
        ctx.fillText(label, world.x, world.y);
      }
      ctx.globalAlpha = 1;
    }

    function nodeAt(wx, wy) {
      let best = null, bd = 1e9;
      for (const n of G.nodes) {
        if (!shown(n)) continue;
        const d = Math.hypot(n.x - wx, n.y - wy);
        if (d < displayRadius(n) + (compactGraph.matches ? 9 : 5) / G.cam.k && d < bd) { best = n; bd = d; }
      }
      if (!best && showBooks && !G.focusIds) {
        for (const { book, frame } of groups.values()) {
          if (wx >= frame.x && wx <= frame.x + frame.width &&
              wy >= frame.y && wy < frame.y + BOOK_SECTION.header) return book;
        }
      }
      return best;
    }
    function edgeAt(wx, wy) {
      let best = null, bd = (compactGraph.matches ? 10 : 7) / G.cam.k;
      for (const e of G.edges) {
        if (e.kind === 'in_book' || !edgeEnabled(e) || !shown(e.s) || !shown(e.t)) continue;
        const {s, t} = e, c = controlPoint(e);
        if (wx < Math.min(s.x, c.x, t.x) - bd || wx > Math.max(s.x, c.x, t.x) + bd ||
            wy < Math.min(s.y, c.y, t.y) - bd || wy > Math.max(s.y, c.y, t.y) + bd) continue;
        let x = s.x, y = s.y;
        for (let i = 1; i <= 12; i++) {
          const f = i / 12, g = 1 - f;
          const nx = g * g * s.x + 2 * g * f * c.x + f * f * t.x;
          const ny = g * g * s.y + 2 * g * f * c.y + f * f * t.y;
          const dx = nx - x, dy = ny - y;
          const at = Math.max(0, Math.min(1, ((wx - x) * dx + (wy - y) * dy) / (dx * dx + dy * dy || 1)));
          const d = Math.hypot(wx - x - dx * at, wy - y - dy * at);
          if (d < bd) { bd = d; best = e; }
          x = nx; y = ny;
        }
      }
      return best;
    }

    function pointerWorld(ev) {
      const r = cv.getBoundingClientRect();
      return toWorld(ev.clientX - r.left, ev.clientY - r.top);
    }

    function moveNode(drag, point) {
      drag.node.x = point.x; drag.node.y = point.y;
      drag.node.pinned = true;
      if (bookCards()) keepInside(drag.node, groups.get(drag.node.code).frame);
      separateNodes();
      draw();
    }

    cv.addEventListener('pointermove', ev => {
      if (!G) return;
      const w = pointerWorld(ev);
      const drag = G.drag;
      if (drag) {
        if (drag.pointerId !== ev.pointerId) return;
        if (!drag.moved && Math.hypot(ev.clientX - drag.x, ev.clientY - drag.y) < 6) return;
        drag.moved = true;
        cv.classList.add('dragging');
        if (drag.node) {
          drag.point = w;
          if (!G.dragFrame) G.dragFrame = requestAnimationFrame(() => {
            G.dragFrame = 0;
            if (G.drag === drag) moveNode(drag, drag.point);
          });
        } else {
          G.cam.x -= (ev.clientX - drag.x) / G.cam.k;
          G.cam.y -= (ev.clientY - drag.y) / G.cam.k;
          drag.x = ev.clientX; drag.y = ev.clientY; draw();
        }
        return;
      }
      if (ev.pointerType !== 'mouse') return;
      const n = nodeAt(w.x, w.y);
      if (n !== G.hover) { G.hover = n; cv.style.cursor = n ? 'pointer' : 'grab'; draw(); }
    }, { signal: ac.signal });

    cv.addEventListener('pointerdown', ev => {
      if (!G || G.drag || ev.button !== 0) return;
      const w = pointerWorld(ev);
      const hit = nodeAt(w.x, w.y);
      const node = hit?.kind === 'entity' ? hit : null;
      G.drag = { pointerId: ev.pointerId, x: ev.clientX, y: ev.clientY, node, moved: false };
      cv.setPointerCapture(ev.pointerId);
    }, { signal: ac.signal });

    function endPointer(ev) {
      const drag = G?.drag;
      if (!drag || drag.pointerId !== ev.pointerId) return;
      if (G.dragFrame) cancelAnimationFrame(G.dragFrame);
      G.dragFrame = 0;
      if (drag.node && drag.moved && ev.type === 'pointerup') moveNode(drag, pointerWorld(ev));
      G.drag = null;
      cv.classList.remove('dragging');
      if (ev.type !== 'pointerup' || drag.moved) return;
      const w = pointerWorld(ev);
      const n = nodeAt(w.x, w.y);
      if (n) { selectNode(n); return; }
      const e = edgeAt(w.x, w.y);
      if (e) { selectEdge(e); return; }
      if (!G.focusIds) { clearSelection(); rememberSelection(scopeHash()); draw(); }
    }
    cv.addEventListener('pointerup', endPointer, { signal: ac.signal });
    cv.addEventListener('pointercancel', endPointer, { signal: ac.signal });
    cv.addEventListener('lostpointercapture', endPointer, { signal: ac.signal });
    cv.addEventListener('pointerleave', () => {
      if (!G?.drag && G?.hover) { G.hover = null; draw(); }
    }, { signal: ac.signal });

    cv.addEventListener('dblclick', () => { if (G) { G.alpha = .6; requestTick(); } }, { signal: ac.signal });

    cv.addEventListener('wheel', ev => {
      ev.preventDefault();
      if (!G) return;
      const r = cv.getBoundingClientRect();
      const mx = ev.clientX - r.left, my = ev.clientY - r.top;
      const before = toWorld(mx, my);
      const k = ev.deltaY < 0 ? 1.12 : .89;
      G.cam.k = Math.min(4, Math.max(.08, G.cam.k * k));
      const after = toWorld(mx, my);
      G.cam.x += before.x - after.x; G.cam.y += before.y - after.y;
      draw();
    }, { passive: false });

    function updateStats() {
      if (!G) return;
      const vn = G.nodes.filter(n => n.kind !== 'book' && shown(n)).length;
      const ve = G.edges.filter(e => e.kind !== 'in_book' && e.kind !== 'cross_book' && shown(e.s) && shown(e.t)).length;
      const counts = `${vn} 个知识节点 · ${ve} 条关系`;
      const label = G.focusIds ? `局部图 · ${counts}` : `${counts} · ${G.books.length} 本书`;
      if (els.stats.textContent !== label) els.stats.textContent = label;
    }
    G.updateStats = updateStats;

    function renderTypes() {
      G.types = G.allTypes;
      els.types.innerHTML = G.types.map(t => `<button type="button" class="kg-tchip ${G.typeHidden.has(t) ? 'off' : ''}" data-t="${esc(t)}" aria-pressed="${!G.typeHidden.has(t)}" style="--kg-type-color:${typeColor(t)}"><i aria-hidden="true"></i>${esc(t)}</button>`).join('');
      els.types.querySelectorAll('.kg-tchip').forEach(el => el.addEventListener('click', () => {
        const t = el.dataset.t;
        if (G.typeHidden.has(t)) G.typeHidden.delete(t); else G.typeHidden.add(t);
        const shown = !G.typeHidden.has(t);
        el.classList.toggle('off', !shown);
        el.setAttribute('aria-pressed', String(shown));
        renderLegend();
        if ((G.sel && !visible(G.sel)) || (G.edgeSel && (!visible(G.edgeSel.s) || !visible(G.edgeSel.t)))) { clearSelection(); rememberSelection(scopeHash()); }
        if (G.sel) openNode(G.sel);
        else if (G.edgeSel) openEdge(G.edgeSel);
        rememberSelection();
        G.fitView(); separateNodes(); draw();
      }, { signal: ac.signal }));
      renderLegend();
    }
    function renderLegend() {
      const types = showBooks ? [...G.types, '书'] : G.types;
      for (const group of groups.values()) group.visibleCount = group.nodes.filter(visible).length;
      const nodes = showBooks && G.typeHidden.size ? G.entities.filter(visible) : [];
      // Limit always-visible book spokes to small filtered views where they help locate isolated nodes.
      G.showBookLines = nodes.length > 0 && nodes.length <= 28 &&
        nodes.filter(n => ![...(G.adj[n.id] || [])].some(id => visible(byId[id]))).length >= Math.ceil(nodes.length / 3);
      const line = (kind, label, color, title) =>
        `<span class="kg-line-key ${kind}" title="${title}"><b aria-hidden="true" style="--kg-line-color:${color}"></b>${label}</span>`;
      const colors = graphColors();
      const lineKeys = line('solid', '直接关系', colors.relation, '点实线可查看关系和依据') +
        (showBooks ? line('dashed', '收录于', colors.book, '虚线连接对象和收录它的图书') : '') +
        (crossEdges.some(edgeEnabled) ? line('solid', '跨书关联', colors.cross, '点紫色曲线查看两本书各自的依据') : '');
      els.legend.innerHTML = lineKeys + types.map(t => {
        const hidden = G.typeHidden.has(t);
        return `<span class="${hidden ? 'off' : ''}"${hidden ? ` aria-label="${esc(t)}，已隐藏"` : ''}><i aria-hidden="true" style="background:${typeColor(t)}"></i>${esc(t)}</span>`;
      }).join('');
    }
    G.refreshLegend = renderLegend;
    renderTypes();
    if (showBooks) viewEl.querySelector('.kg-hint').textContent = '拖动节点整理版面 · 点节点看详情';

    function linksFor(node) {
      return crossEdges.filter(e => e.s === node || e.t === node);
    }

    function crossRows(matches) {
      return matches.map(edge => `<article class="kg-cross-row">
        <p>${esc(edge.basis)} · ${esc(edge.via)}</p>
        <h3>${esc(edge.title)}</h3><p>${esc(edge.s.book)} · ${esc(edge.t.book)}</p>
        <button type="button" class="btn sm ghost" data-cross-id="${esc(edge.id)}">看两书依据</button>
      </article>`).join('');
    }

    function openCrossPanel() {
      const prompt = crossEdges.length ? '比较所选图书的原文。紫色曲线表示两书通过同一人物或机构关联。'
        : bookScope.codes.length < 2 ? '用中图分类缩小范围，选择至少两本书一起查找。'
          : '所选书目中暂没有已核对的跨书关联。可以调整图书范围继续找。';
      els.crossPanel.innerHTML = `<header><div><h2>跨书关联</h2><p>${prompt}</p></div>
          <button type="button" data-cross-close aria-label="关闭跨书关联">×</button></header>
          <div class="kg-cross-results">${crossRows(crossEdges)}</div>
          <div class="kg-cross-actions">
          <button type="button" class="btn sm ghost" data-cross-scope>调整图书范围</button>
          ${crossEdges.length ? `<label><input type="checkbox" data-cross-visibility ${G.showCross ? 'checked' : ''}>在图中显示跨书连线</label>` : ''}
          </div>`;
      els.crossPanel.hidden = false;
      els.crossToggle.setAttribute('aria-expanded', 'true');
      els.crossPanel.querySelector('[data-cross-close]')?.focus({preventScroll: true});
    }

    function closeCrossPanel() {
      els.crossPanel.hidden = true;
      els.crossToggle.setAttribute('aria-expanded', 'false');
    }
    G.closeCrossPanel = closeCrossPanel;

    els.crossToggle.textContent = `跨书关联${crossEdges.length ? ' ' + crossEdges.length : ''}`;
    els.crossToggle.addEventListener('click', () => {
      if (!els.crossPanel.hidden) closeCrossPanel();
      else {
        if (draftScope) closeScope(false);
        openCrossPanel();
      }
    }, {signal: ac.signal});
    els.crossPanel.addEventListener('click', ev => {
      if (ev.target.closest('[data-cross-close]')) {
        closeCrossPanel();
        els.crossToggle.focus({preventScroll: true});
      } else if (ev.target.closest('[data-cross-scope]')) {
        ev.stopPropagation();
        closeCrossPanel();
        openScope();
      } else {
        const id = ev.target.closest('[data-cross-id]')?.dataset.crossId;
        if (id) selectEdge(crossEdges.find(edge => edge.id === id));
      }
    }, {signal: ac.signal});
    els.crossPanel.addEventListener('change', ev => {
      if (!ev.target.matches('[data-cross-visibility]')) return;
      G.showCross = ev.target.checked;
      renderLegend(); rememberSelection(); draw();
    }, {signal: ac.signal});
    for (const button of els.layout.querySelectorAll('[data-layout]')) {
      button.setAttribute('aria-pressed', String(button.dataset.layout === G.overviewMode));
      button.addEventListener('click', () => {
        G.overviewMode = button.dataset.layout;
        els.layout.querySelector('[aria-pressed="true"]')?.setAttribute('aria-pressed', 'false');
        button.setAttribute('aria-pressed', 'true');
        if (bookCards()) {
          for (const n of G.entities) keepInside(n, groups.get(n.code).frame);
        }
        fitView(); separateNodes(); rememberSelection(); draw();
      }, {signal: ac.signal});
    }

    els.q.addEventListener('input', () => {
      const v = els.q.value.trim();
      if (!v) { els.sug.classList.remove('on'); return; }
      const hits = G.nodes.filter(n => n.kind === 'entity' && n.label.includes(v)).slice(0, 8);
      if (!hits.length) { els.sug.innerHTML = '<div style="color:#7B94B5">图里没有这个名字</div>'; els.sug.classList.add('on'); return; }
      els.sug.innerHTML = hits.map(n => `<div data-id="${esc(n.id)}">${esc(n.label)}<span class="st">${esc(n.type)} · ${esc(n.book || n.code)}</span></div>`).join('');
      els.sug.classList.add('on');
    }, { signal: ac.signal });
    els.sug.addEventListener('click', ev => {
      const row = ev.target.closest('[data-id]'); if (!row) return;
      els.sug.classList.remove('on'); els.q.value = '';
      const n = G.nodes.find(x => x.id === row.dataset.id);
      if (n) selectNode(n, true, true);
    }, { signal: ac.signal });
    els.q.addEventListener('keydown', ev => {
      if (ev.key === 'Enter') {
        const v = els.q.value.trim();
        const n = v && G.nodes.find(x => x.kind === 'entity' && x.label.includes(v));
        if (n) selectNode(n, true, true);
        els.sug.classList.remove('on');
      }
    }, { signal: ac.signal });

    function selectNode(n, remember = true, center = false) {
      if (!G || !n) return;
      closeCrossPanel();
      G.typeHidden.delete(n.type); renderTypes();
      G.sel = n; G.edgeSel = null; G.contextNodeId = '';
      renderLegend();
      openNode(n);
      fitView();
      separateNodes();
      if (remember) rememberSelection(scopeHash(n.kind === 'entity' ? n.id : ''));
      draw();
    }
    function selectEdge(e, remember = true) {
      if (!G || !e || !e.s || !e.t) return;
      closeCrossPanel();
      if (e.kind === 'cross_book') G.showCross = true;
      const contextId = G.sel?.kind === 'entity' ? G.sel.id : G.contextNodeId;
      G.contextNodeId = contextId === e.s.id || contextId === e.t.id ? contextId : '';
      G.edgeSel = e; G.sel = null;
      G.typeHidden.delete(e.s.type); G.typeHidden.delete(e.t.type); renderTypes();
      openEdge(e);
      fitView();
      separateNodes();
      if (remember) rememberSelection(scopeHash());
      draw();
    }
    G.selectNode = selectNode;
    G.selectEdge = selectEdge;

    function openPanel(html) {
      const selected = G.sel?.kind === 'entity' || G.edgeSel;
      const modes = selected ? `<div class="kg-view-switch" role="group" aria-label="关系查看方式">
        <button type="button" data-kg-view="graph" aria-pressed="${G.viewMode === 'graph'}">局部图</button>
        <button type="button" data-kg-view="list" aria-pressed="${G.viewMode === 'list'}">关系列表</button></div>` : '';
      els.panel.innerHTML = modes + `<div class="kg-panel-content">${html}</div><button type="button" class="close" data-close aria-label="收起详情">×</button>`;
      els.panel.scrollTop = 0;
      setPanelOpen(true);
      els.panel.querySelector('[data-close]').addEventListener('click', () => {
        if (G.focusIds) { G.setDetails(false); rememberSelection(); }
        else G.clearSelection();
      });
      els.panel.querySelectorAll('[data-kg-view]').forEach(button => button.addEventListener('click', () => {
        if (!G.sel && !G.edgeSel) return;
        G.viewMode = button.dataset.kgView === 'list' ? 'list' : 'graph';
        if (G.edgeSel) openEdge(G.edgeSel); else openNode(G.sel);
        fitView(); rememberSelection(); draw();
        els.panel.querySelector(`[data-kg-view="${G.viewMode}"]`)?.focus({preventScroll: true});
      }));
      els.panel.querySelectorAll('[data-edge]').forEach(x => x.addEventListener('click', ev => {
        ev.preventDefault(); ev.stopPropagation();
        const edge = G.edges.find(y => edgeKey(y) === x.dataset.edge);
        if (edge) selectEdge(edge);
      }));
      els.panel.querySelectorAll('[data-cross-id]').forEach(x => x.addEventListener('click', () => {
        selectEdge(crossEdges.find(edge => edge.id === x.dataset.crossId));
      }));
      els.panel.querySelectorAll('[data-nid]').forEach(x => x.addEventListener('click', () => {
        const n = G.nodes.find(y => y.id === x.dataset.nid);
        if (n) selectNode(n, true, true);
      }));
      els.panel.querySelectorAll('[data-anchor]').forEach(x => x.addEventListener('click', () => {
        if (x.dataset.anchor) go('book', x.dataset.code, 'text', x.dataset.anchor);
      }));
      els.panel.querySelectorAll('[data-book]').forEach(x => x.addEventListener('click', () => go('book', x.dataset.book)));
      els.panel.querySelectorAll('[data-booksel]').forEach(x => x.addEventListener('click', () => {
        go('kg', x.dataset.booksel);
      }));
    }
    function setPanelOpen(open) {
      els.panel.classList.toggle('open', open);
      els.panel.inert = !open;
      G.detailsHidden = !open;
      els.shell.classList.toggle('kg-list-mode', Boolean(open && G.viewMode === 'list' && (G.edgeSel || G.sel?.kind === 'entity')));
    }
    function clearSelection() {
      const wasFocused = Boolean(G.focusIds);
      closeCrossPanel();
      G.sel = null; G.edgeSel = null; G.hover = null; G.contextNodeId = ''; G.viewMode = 'graph';
      setPanelOpen(false); G.detailsHidden = false;
      els.panel.innerHTML = '';
      renderLegend();
      if (wasFocused) fitView();
    }
    G.setDetails = open => { setPanelOpen(open); fitView(); draw(); };
    G.clearSelection = () => { clearSelection(); rememberSelection(scopeHash()); draw(); };

    const typeChip = t => `<span class="type"><i style="background:${typeColor(t)}"></i>${esc(t)}</span>`;

    function nodeRelations(node, includeHidden = false) {
      return G.edges.filter(edge => edge.kind !== 'in_book' && edge.kind !== 'cross_book' && (edge.s === node || edge.t === node) &&
        (includeHidden || (visible(edge.s) && visible(edge.t))))
        .sort((a, b) => relationBasis(a).order - relationBasis(b).order || String(a.rel).localeCompare(String(b.rel), 'zh-CN'));
    }

    function relationRows(node, edges) {
      return `<div class="kg-relation-rows">${edges.map(edge => {
        const endpoint = item => item === node ? `<span class="kg-current-node">${esc(item.label)}</span>` :
          `<button type="button" class="kg-related-node" data-nid="${esc(item.id)}">${esc(item.label)}</button><span class="kg-related-type">${esc(item.type)}</span>`;
        const location = edge.evidence?.label || edge.evidence?.anchor || '暂无原文位置';
        return `<article class="kg-relation-row">
          <div class="kg-relation-direction">${endpoint(edge.s)}
            <span class="kg-direction">—${esc(edge.rel || '关系')}→</span>${endpoint(edge.t)}</div>
          <div class="kg-relation-source">${basisChip(edge)}<span>${esc(edge.s.book || '')}${edge.s.book ? ' · ' : ''}${esc(location)}</span></div>
          <button type="button" class="btn sm ghost kg-evidence-action" data-edge="${esc(edgeKey(edge))}" aria-label="查看${esc(edge.s.label)}到${esc(edge.t.label)}的${esc(edge.rel || '关系')}依据">看依据</button>
        </article>`;
      }).join('')}</div>`;
    }

    function openNode(n) {
      if (!n) return;
      if (n.kind === 'book') {
        const c = n.counts || {};
        openPanel(`<div>${typeChip('书')}</div><h3>${esc(n.label)}</h3><div class="sub">${esc(n.form || '')}</div>
          <div class="stat"><div><b>${c.nodes || 0}</b><span>知识节点</span></div><div><b>${c.edges || 0}</b><span>关系</span></div></div>
          <div class="acts"><button class="btn gold" data-book="${esc(n.code)}">打开图书档案</button><button class="btn ghost" data-booksel="${esc(n.code)}">只看这本书</button></div>`);
        return;
      }
      const rels = nodeRelations(n), total = nodeRelations(n, true).length;
      const displayed = G.viewMode === 'list' ? rels : rels.slice(0, 4);
      let h = `<div>${typeChip(n.type)}</div><h3>${esc(n.label)}</h3>
        <div class="sub">${esc(n.book || '')}</div>`;
      const across = linksFor(n);
      if (across.length) h += `<div class="h4">跨书关联（${across.length}）</div>${crossRows(across)}`;
      h += `<div class="h4">书中关系（${rels.length}）</div>`;
      if (rels.length !== total) h += `<p class="kg-list-note">按当前类型筛选显示 ${rels.length} / ${total} 条关系。</p>`;
      h += rels.length ? relationRows(n, displayed) : '<p class="kg-list-note">当前类型筛选下没有可展示的直接关系。</p>';
      if (displayed.length < rels.length) h += `<button type="button" class="btn ghost kg-list-more" data-kg-view="list">查看全部 ${rels.length} 条关系 →</button>`;
      const a = (n.anchors || [])[0];
      if (n.role || n.achievement || n.raw || a) {
        h += `<details class="kg-node-background"><summary>${n.type === '人物' ? '人物介绍与原文' : '对象说明与原文'}</summary>`;
        if (n.role) h += `<p class="p">${esc(n.role)}</p>`;
        if (n.achievement) h += `<div class="h4">主要成就</div><p class="p">${esc(n.achievement)}</p>`;
        if (a) h += `<div class="quote">${esc((n.raw || '').slice(0, 360))}${(n.raw || '').length > 360 ? '…' : ''}
          <div><button type="button" class="a" data-anchor="${esc(a.id)}" data-code="${esc(n.code)}">${esc(a.label || a.id)} · 在原文中打开 ↗</button></div></div>`;
        h += '</details>';
      }
      h += `<div class="acts"><button type="button" class="btn ghost" data-book="${esc(n.code)}">打开图书档案</button></div>`;
      openPanel(h);
    }

    function edgeEvidence(edge) {
      const evidence = edge.evidence || {};
      const excerpts = Array.isArray(evidence.excerpts) && evidence.excerpts.length ? evidence.excerpts :
        [{anchor: evidence.anchor, quote: evidence.text || edge.note || '', label: evidence.label}];
      return excerpts.map(excerpt => `<div class="quote kg-evidence-excerpt">${esc(excerpt.quote || excerpt.text || '')}
        ${excerpt.anchor ? `<div><button type="button" class="a" data-anchor="${esc(excerpt.anchor)}" data-code="${esc(edge.code || edge.s.code)}">${esc(excerpt.label || (excerpt.anchor === evidence.anchor ? evidence.label : '') || excerpt.anchor)} · 在原文中打开 ↗</button></div>` : ''}</div>`).join('');
    }

    function openEdge(e) {
      if (e.kind === 'cross_book') {
        const context = G.entities.find(n => n.id === G.contextNodeId);
        openPanel(`${context ? `<button type="button" class="kg-context-back" data-nid="${esc(context.id)}">← 返回${esc(context.label)}的关系</button>` : ''}
          <div><span class="kg-basis kg-basis-field">${esc(e.basis)} · ${esc(e.via)}</span></div>
          <h3>${esc(e.title)}</h3><p class="kg-basis-note">${esc(e.reason || e.label)}</p>
          <div class="h4">两本书的原文依据</div>
          <div class="kg-cross-evidence">${e.evidence.map(excerpt => `<div class="quote kg-evidence-excerpt">
            <b>${esc(groups.get(excerpt.code)?.book.label || excerpt.code)}</b><p>${esc(excerpt.quote)}</p>
            <button type="button" class="a" data-anchor="${esc(excerpt.anchor)}" data-code="${esc(excerpt.code)}">${esc(excerpt.label || excerpt.anchor)} · 查看原文 ↗</button>
          </div>`).join('')}</div>
          <div class="h4">查看各书对象</div><div class="kg-endpoints">
            <button type="button" class="btn ghost" data-nid="${esc(e.s.id)}">${esc(e.s.label)}</button>
            <button type="button" class="btn ghost" data-nid="${esc(e.t.id)}">${esc(e.t.label)}</button>
          </div>`);
        return;
      }
      const a = e.s, b = e.t, basis = relationBasis(e);
      const context = G.entities.find(n => n.id === G.contextNodeId && (n === a || n === b));
      openPanel(`${context ? `<button type="button" class="kg-context-back" data-nid="${esc(context.id)}">← 返回${esc(context.label)}的关系</button>` : ''}
        <div>${basisChip(e)}</div>
        <h3>${esc(a.label)} <span class="kg-relation-name">—${esc(e.rel || '关系')}→</span> ${esc(b.label)}</h3>
        <div class="sub">${[a.book, e.relation_origin].filter(Boolean).map(esc).join(' · ')}</div>
        <p class="kg-basis-note kg-basis-note-${basis.key}">${esc(basis.note)}</p>
        <div class="h4">原文依据</div>
        ${edgeEvidence(e)}
        ${window.RelationMaterials?.render(e) || ''}
        <div class="h4">关系两端</div><div class="kg-endpoints">
          <button type="button" class="btn ghost" data-nid="${esc(a.id)}">${esc(a.label)} · ${esc(a.type)}</button>
          <button type="button" class="btn ghost" data-nid="${esc(b.id)}">${esc(b.label)} · ${esc(b.type)}</button>
        </div>`);
    }

    viewEl.querySelectorAll('.kg-zoom [data-z]').forEach(b => b.addEventListener('click', () => {
      if (!G) return;
      const v = b.dataset.z;
      if (v === 'fit') { G.fitView(); draw(); }
      else { G.cam.k = Math.min(4, Math.max(.08, G.cam.k * parseFloat(v))); draw(); }
    }, { signal: ac.signal }));

    ro = new ResizeObserver(() => {
      if (!G) return;
      const [w, h] = fitCanvas();
      G.W = w; G.H = h;
      arrangeBooks();
      G.alpha = 0; G.fitView(); separateNodes(); draw();
    });
    ro.observe(els.shell);
    ro.observe(els.toolbar);

    draw();
  }

  function bindShell() {
    bindFullscreen();
    viewEl.querySelector('[data-kg-action="lookup"]').addEventListener('click', () => {
      const code = G?.sel?.code || G?.edgeSel?.s.code || (bookScope.codes.length === 1 ? bookScope.codes[0] : '');
      go('kglab', code || undefined);
    }, { signal: ac.signal });
    els.scopeTrigger.addEventListener('click', () => {
      G?.closeCrossPanel();
      if (draftScope) closeScope();
      else openScope();
    }, { signal: ac.signal });
    els.scopeCategory.addEventListener('change', renderScopeBooks, { signal: ac.signal });
    els.scopeQuery.addEventListener('input', renderScopeBooks, { signal: ac.signal });
    els.scopeBooks.addEventListener('change', ev => {
      const box = ev.target.closest('input[type="checkbox"]');
      if (!box || !draftScope) return;
      if (box.checked) draftScope.codes.add(box.value);
      else draftScope.codes.delete(box.value);
      updateScopeCount();
    }, { signal: ac.signal });
    els.scopePanel.querySelector('[data-kg-action="clear-scope"]').addEventListener('click', () => {
      if (!draftScope) return;
      draftScope.codes.clear();
      renderScopeBooks();
    }, { signal: ac.signal });
    els.scopePanel.querySelector('[data-kg-action="cancel-scope"]').addEventListener('click', () => closeScope(), { signal: ac.signal });
    els.scopePanel.querySelector('[data-kg-action="apply-scope"]').addEventListener('click', applyScope, { signal: ac.signal });
    viewEl.querySelector('[data-kg-action="overview"]').addEventListener('click', () => G?.clearSelection(), { signal: ac.signal });
    viewEl.querySelector('[data-kg-action="details"]').addEventListener('click', () => {
      if (!G?.focusIds) return;
      G.setDetails(true);
      rememberSelection();
    }, { signal: ac.signal });
    document.addEventListener('keydown', ev => {
      if (ev.key !== 'Escape') return;
      if (fullscreenElement() === els.fullscreenHost) return;
      if (draftScope) { ev.preventDefault(); closeScope(); }
      else if (!els.crossPanel.hidden) { G?.closeCrossPanel(); els.crossToggle.focus({preventScroll: true}); }
      else G?.clearSelection();
    }, { signal: ac.signal });
    document.addEventListener('click', ev => {
      if (!ev.target.closest('.kg-search') && els.sug) els.sug.classList.remove('on');
      if (draftScope && !ev.target.closest('.kg-scope')) closeScope(false);
    }, { signal: ac.signal });
  }

  function bindFullscreen() {
    const host = els.fullscreenHost;
    const enter = host.requestFullscreen || host.webkitRequestFullscreen;
    const button = viewEl.querySelector('[data-kg-action="fullscreen"]');
    const exit = viewEl.querySelector('[data-kg-action="exit-fullscreen"]');
    const options = {signal: ac.signal};
    host.classList.add('kg-fullscreen-host');
    button.disabled = !enter || (document.fullscreenEnabled === false && !document.webkitFullscreenEnabled);
    function sync() {
      const active = fullscreenElement() === host;
      button.setAttribute('aria-pressed', String(active));
      button.title = button.disabled ? '当前浏览器不支持图谱全屏' : active ? '退出全屏（Esc）' : '全屏';
      if (button.disabled) button.setAttribute('aria-label', button.title);
      exit.hidden = !active;
      G?.refreshLegend();
      G?.draw();
    }
    sync();
    const toggle = async () => {
      try {
        if (fullscreenElement() === host) await exitFullscreen();
        else {
          await enter.call(host);
          if (els.fullscreenHost !== host && fullscreenElement() === host) await exitFullscreen();
        }
      } catch (_) {
        toast('浏览器未能切换全屏，请重试。', true);
      }
    };
    button.addEventListener('click', toggle, options);
    exit.addEventListener('click', () => {
      if (fullscreenElement() === host) toggle();
    }, options);
    document.addEventListener('fullscreenchange', sync, options);
    document.addEventListener('webkitfullscreenchange', sync, options);
  }

  function destroy(keepFullscreen = false) {
    const host = els.fullscreenHost;
    if (host && !keepFullscreen) {
      host.classList.remove('kg-fullscreen-host');
      if (fullscreenElement() === host) Promise.resolve(exitFullscreen()).catch(() => {});
    }
    if (G) {
      cancelAnimationFrame(G.raf);
      cancelAnimationFrame(G.dragFrame);
    }
    if (ro) { ro.disconnect(); ro = null; }
    if (ac) { ac.abort(); ac = null; }
    G = null; data = null; viewEl = null; els = {};
    bookCatalog = []; bookScope = {codes: [], category: ''}; draftScope = null;
  }

  window.KG = { render, destroy };
})();
