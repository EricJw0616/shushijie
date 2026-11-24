'use strict';

window.CreatorMatch = (() => {
  const drafts = new Map();
  const shortlists = new Map();
  const storagePrefix = 'bookworld.creator-match.shortlist.';
  const samples = {
    sample: {
      label: '3–6 岁情绪绘本',
      title: '小熊的情绪练习',
      synopsis: '一本给 3–6 岁孩子的亲子情绪管理绘本。小熊在玩具被抢、比赛输了和想念妈妈时，练习辨认情绪、说出感受，并和家长一起找到平静下来的方法。书后附亲子共读问题。',
      audience: '3–6 岁孩子的家长与幼儿园老师',
      goal: 'content',
    },
    'sample-iraq': {
      label: '伊拉克社会纪实',
      title: '走进伊拉克',
      synopsis: '从伊拉克城市街区和居民的日常出发，讲述战后普通人如何恢复生活，以及外界想象与实地观察之间的差异。',
      audience: '关注中东当代社会与旅行纪实的读者',
      goal: 'content',
    },
  };
  const goals = {content: '内容种草', sales: '带货成交'};
  const audienceModes = {ai: 'AI 分析', library: '书库解析', manual: '手动填写'};

  function bookInputs(draft) {
    return {title: draft.title.trim(), synopsis: draft.synopsis.trim(), goal: draft.goal};
  }

  function audienceSelection(draft) {
    if (draft.audienceMode === 'manual') return draft.audience.trim();
    const source = draft.audienceMode === 'ai' ? draft.aiAudience : draft.libraryAudience;
    return source?.options.filter((_, index) => source.selected.has(index)).map(choice => choice.text.trim()).join('；') || '';
  }

  function payload(draft) {
    const values = {...bookInputs(draft), audience: audienceSelection(draft)};
    if (draft.bookCode) values.book_code = draft.bookCode;
    return values;
  }

  function extractLibraryAudiences(detail) {
    const rows = Array.isArray(detail.marketing_rows) ? detail.marketing_rows : [];
    const options = rows.filter(row => row.key === 'audience' && row.status !== 'rejected')
      .map(row => ({text: row.text || row.main, provenance: row.status === 'approved' ? '营销资料 · 已审核' : '营销资料 · 待确认'}));
    const readerFields = ['目标读者', '适读对象', '适读人群'];
    for (const source of [detail.book, detail.cip]) {
      for (const field of readerFields) {
        const values = Array.isArray(source?.[field]) ? source[field] : [source?.[field]];
        for (const text of values) options.push({text, provenance: `图书档案 · ${field}`});
      }
    }
    const seen = new Set();
    return options.filter(({text}) => {
      if (typeof text !== 'string' || !text.trim() || seen.has(text.trim())) return false;
      seen.add(text.trim());
      return true;
    });
  }

  function shortlistKey(draft, values = payload(draft)) {
    if (draft.sample) return draft.sample;
    if (values.book_code) return `library:${values.book_code}`;
    const title = values.title.normalize('NFKC').replace(/[《》]/g, '').replace(/\s+/g, '').toLowerCase();
    return title ? `manual:${title}` : '';
  }

  function shortlist(key) {
    if (!key) return [];
    if (!shortlists.has(key)) {
      let saved = [];
      try {
        const data = JSON.parse(localStorage.getItem(storagePrefix + key) || '[]');
        if (Array.isArray(data)) saved = data.filter(item => typeof item?.handle === 'string' && item.handle);
      } catch (_) {}
      shortlists.set(key, saved);
    }
    return shortlists.get(key);
  }

  function toggleSave(key, match) {
    const saved = shortlist(key);
    const index = saved.findIndex(item => item.handle === match.handle);
    const added = index < 0;
    if (added) saved.push(match);
    else saved.splice(index, 1);
    let persistent = true;
    try { localStorage.setItem(storagePrefix + key, JSON.stringify(saved)); }
    catch (_) { persistent = false; }
    return {added, persistent};
  }

  function screenHtml() {
    return `<div class="cm-screen" aria-labelledby="cm-title">
      <header class="cm-head">
        <h1 id="cm-title">图书达人匹配</h1>
        <p>从图书内容和抖音达人的实际作品中找合作切入点。</p>
      </header>
      <div class="cm-layout">
        <section class="cm-brief" aria-labelledby="cm-brief-title">
          <header class="cm-section-head">
            <h2 class="cm-panel-title" id="cm-brief-title">图书信息</h2>
            <button type="button" class="cm-sample" data-cm-action="sample">试用示例</button>
          </header>
          <div class="cm-source-switch" role="group" aria-label="图书信息来源">
            <button type="button" class="cm-source-button" data-cm-action="library">从书库选书</button>
            <button type="button" class="cm-source-button" data-cm-action="manual">手动填写</button>
          </div>
          <div class="cm-library" hidden>
            <div class="cm-book-select">
              <button type="button" class="cm-book-trigger" data-cm-action="toggle-books" aria-expanded="false" aria-controls="cm-book-dropdown">
                <span class="cm-book-value">查找图书</span><span class="cm-book-chevron" aria-hidden="true"></span>
              </button>
              <div class="cm-book-dropdown" id="cm-book-dropdown" hidden>
                <input id="cm-book-search" class="cm-input" type="search" aria-label="筛选图书" placeholder="书名、作者或书码" autocomplete="off">
                <div class="cm-book-list" role="group" aria-label="书库图书"></div>
              </div>
            </div>
            <p class="cm-library-notice" role="status" hidden></p>
          </div>
          <form class="cm-form">
            <p class="cm-sample-label" data-cm-sample-label hidden></p>
            <label class="cm-field" for="cm-book-title">
              <span>书名</span>
              <input id="cm-book-title" class="cm-input" name="title" placeholder="输入待推广的书名" required maxlength="200">
            </label>
            <label class="cm-field" for="cm-synopsis">
              <span>内容简介</span>
              <textarea id="cm-synopsis" class="cm-textarea" name="synopsis" rows="4" maxlength="3000" placeholder="填入主要内容和细分主题，帮助找到方向更合适的达人。"></textarea>
            </label>
            <fieldset class="cm-goals" aria-labelledby="cm-goal-label">
              <legend>
                <span id="cm-goal-label">推广目标</span>
                <button type="button" class="cm-goal-help-button" aria-label="解释推广目标" aria-expanded="false" aria-controls="cm-goal-help">?</button>
              </legend>
              ${Object.entries(goals).map(([value, label]) => `<label class="cm-goal"><input type="radio" name="goal" value="${value}"><span>${label}</span></label>`).join('')}
            </fieldset>
            <dl class="cm-goal-help" id="cm-goal-help" hidden>
              <dt>内容种草</dt><dd>请博主讲一段书里的故事或观点，让人想去读。</dd>
              <dt>带货成交</dt><dd>请博主讲清这本书适合谁、怎么买，让观众能直接下单。</dd>
            </dl>
            <fieldset class="cm-audience">
              <legend>目标受众 <small>选填</small></legend>
              <div class="cm-audience-modes" role="group" aria-label="受众来源">
                ${Object.entries(audienceModes).map(([value, label]) => `<button type="button" class="cm-audience-mode" data-cm-action="audience-mode" data-mode="${value}">${label}</button>`).join('')}
              </div>
              <div class="cm-audience-panel" data-audience-panel="ai" hidden>
                <div class="cm-audience-head">
                  <p>按书名、简介和推广目标生成建议，可勾选多项用于匹配。</p>
                  <button type="button" class="cm-audience-analyze" data-cm-action="analyze-audience">分析受众</button>
                </div>
                <p class="cm-audience-feedback" role="status" aria-live="polite" hidden></p>
                <div class="cm-audience-options" role="group" aria-label="AI 受众建议"></div>
              </div>
              <div class="cm-audience-panel" data-audience-panel="library" hidden>
                <p class="cm-audience-feedback" role="status" aria-live="polite"></p>
                <div class="cm-audience-options" role="group" aria-label="书库受众选项"></div>
              </div>
              <div class="cm-audience-panel" data-audience-panel="manual" hidden>
                <label class="cm-field" for="cm-audience">
                  <span>想触达的人群</span>
                  <input id="cm-audience" class="cm-input" name="audience" maxlength="400" placeholder="如 3–6 岁孩子的家长">
                </label>
              </div>
            </fieldset>
            <div class="cm-form-footer">
              <button type="submit" class="cm-submit">匹配达人</button>
              <p class="cm-panel-hint">书还没入库时，可以直接填写书名和简介。</p>
            </div>
          </form>
        </section>
        <section class="cm-results" aria-labelledby="cm-results-title">
          <header class="cm-results-head">
            <div>
              <h2 id="cm-results-title" class="cm-panel-title" tabindex="-1">匹配结果</h2>
              <p class="cm-panel-hint" data-cm-results-context>按书查看匹配依据和待核验项。</p>
              <p class="cm-panel-hint cm-results-audience" data-cm-results-audience hidden></p>
            </div>
            <div class="cm-results-actions">
              <button type="button" class="cm-works-add" data-cm-action="search-works">自动查作品</button>
              <div class="cm-tabs" role="group" aria-label="查看结果范围">
                <button type="button" class="cm-tab" data-cm-action="results">全部候选</button>
                <button type="button" class="cm-tab" data-cm-action="shortlist">备选名单</button>
              </div>
              <button type="button" class="cm-work-manual" data-cm-action="add-work">手动补充</button>
            </div>
            <div class="cm-content-notice cm-work-search-status" data-cm-work-search hidden>
              <p id="cm-work-search-message" data-cm-work-search-message></p>
              <button type="button" class="cm-work-manual" data-cm-action="fill-work-brief" hidden>去补图书信息</button>
            </div>
          </header>
          <p class="cm-live" role="status" aria-live="polite" aria-atomic="true"></p>
          <p class="cm-live" data-cm-work-search-announcement role="status" aria-live="polite" aria-atomic="true"></p>
          <p class="cm-content-notice cm-work-save-notice" data-cm-work-notice role="status" hidden></p>
          <div class="cm-results-body"></div>
        </section>
      </div>
      <dialog class="cm-work-dialog" aria-labelledby="cm-work-dialog-title">
        <form class="cm-work-form">
          <header class="cm-work-dialog-head">
            <h2 id="cm-work-dialog-title">补充达人作品</h2>
            <p>添加抖音账号的实际作品。文案、转写和原链接能帮助核对作品内容。</p>
          </header>
          <fieldset class="cm-work-fields">
            <label class="cm-field" for="cm-work-handle">
              <span>抖音号</span>
              <input id="cm-work-handle" class="cm-input" name="handle" required maxlength="128" autocomplete="off" placeholder="填写达人库里已有的账号">
            </label>
            <label class="cm-field" for="cm-work-title">
              <span>作品标题</span>
              <input id="cm-work-title" class="cm-input" name="title" required maxlength="180">
            </label>
            <label class="cm-field" for="cm-work-text">
              <span>作品文案或转写 <small>选填</small></span>
              <textarea id="cm-work-text" class="cm-textarea" name="text" rows="4" maxlength="5000"></textarea>
            </label>
            <label class="cm-field" for="cm-work-url">
              <span>原链接 <small>选填，仅 HTTPS</small></span>
              <input id="cm-work-url" class="cm-input" name="url" type="url" maxlength="1200" placeholder="https://">
            </label>
            <label class="cm-field" for="cm-work-published">
              <span>发布日期 <small>选填</small></span>
              <input id="cm-work-published" class="cm-input" name="published" type="date">
            </label>
          </fieldset>
          <p class="cm-work-feedback" role="alert" hidden></p>
          <div class="cm-work-dialog-actions">
            <button type="button" class="cm-work-cancel" data-cm-action="close-work">取消</button>
            <button type="submit" class="cm-work-submit">保存作品</button>
          </div>
        </form>
      </dialog>
    </div>`;
  }

  function stateHtml(title, text, tone = '', action = '') {
    return `<div class="cm-state${tone ? ` cm-state-${tone}` : ''}">
      <h3>${title}</h3><p>${text}</p>${action}
    </div>`;
  }

  function matchResponse(data) {
    return {
      matches: data.matches.filter(item => typeof item?.handle === 'string' && item.handle),
      contentStatus: data.content_status,
      summary: typeof data.summary === 'string' ? data.summary : '',
      contentNotice: typeof data.content_notice === 'string' ? data.content_notice : '',
    };
  }

  function audienceChoices(source) {
    return (source?.options || []).map((choice, index) => `<label class="cm-audience-choice">
      <input type="checkbox" name="audience_choice" value="${index}"${source.selected.has(index) ? ' checked' : ''}>
      <span class="cm-audience-choice-copy">
        ${choice.label && choice.label !== choice.text ? `<span class="cm-audience-choice-label">${esc(choice.label)}</span>` : ''}
        <span class="cm-audience-choice-text">${esc(choice.text)}</span>
        ${choice.provenance ? `<span class="cm-audience-choice-status">${esc(choice.provenance)}</span>` : ''}
      </span>
    </label>`).join('');
  }

  function workUrl(value) {
    if (typeof value !== 'string' || !value.trim()) return '';
    try {
      const url = new URL(value.trim());
      if (url.protocol === 'https:' && !url.username && !url.password) return url.href;
    } catch (_) {}
    return '';
  }

  function contentEvidence(match) {
    const content = match.content_match;
    if (typeof content?.book_point !== 'string' || !content.book_point.trim() ||
        typeof content.connection !== 'string' || !content.connection.trim() || !Array.isArray(content.works)) return null;
    const works = content.works.filter(work => typeof work?.title === 'string' && work.title.trim());
    return works.length ? {...content, works} : null;
  }

  function workHtml(work) {
    const metadata = [work.source, work.published].filter(value => typeof value === 'string' && value.trim()).join(' · ');
    const summary = typeof work.text === 'string' ? clip(work.text, 180) : '';
    const url = workUrl(work.url);
    return `<div class="cm-work">
      ${url ? `<a class="cm-work-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(work.title)}</a>` : `<strong class="cm-work-title">${esc(work.title)}</strong>`}
      ${metadata || !url ? `<span class="cm-work-meta">${esc([metadata, url ? '' : '暂未提供原链接'].filter(Boolean).join(' · '))}</span>` : ''}
      ${summary ? `<p class="cm-work-text">${esc(summary)}</p>` : ''}
    </div>`;
  }

  function scoreHtml(content) {
    const details = Array.isArray(content.score_details) ? content.score_details : [];
    return `<div class="cm-score-detail">
      <h4>内容匹配分依据</h4>
      ${content.score_reason ? `<p>${esc(content.score_reason)}</p>` : ''}
      ${details.length ? `<ul>${details.map(item => `<li>
        <strong>${esc(item.label)}</strong>
        <span>${esc(item.reason)}</span>
        <span class="cm-score-points">${esc(item.score)} / ${esc(item.max)}</span>
      </li>`).join('')}</ul>` : ''}
    </div>`;
  }

  function cardHtml(match, key, expanded, index, shortlistView = false) {
    const saved = shortlist(key).some(item => item.handle === match.handle);
    const open = expanded.has(match.handle);
    const detailId = `cm-evidence-${index}`;
    const reasonList = list => list.map(reason => `<li class="cm-reason"><strong>${esc(reason.label)}</strong><span>${esc(reason.text)}</span></li>`).join('');
    const reasons = Array.isArray(match.reasons) ? match.reasons : [];
    const domains = Array.isArray(match.domains) ? match.domains : [];
    const categories = Array.isArray(match.product_categories) ? match.product_categories : [];
    const checks = Array.isArray(match.checks) ? match.checks : [];
    const content = contentEvidence(match);
    const hasScore = Number.isFinite(content?.score) && content.score >= 0 && content.score <= 100;
    const suggestBackup = hasScore && content.score_state === 'strong' && (content.recommend_backup === true || match.recommend_backup === true);
    const workLabel = content?.score_state === 'weak'
      ? (hasScore && content.score >= 60 ? '作品依据待核对' : '作品关联较弱')
      : '有作品依据';
    const name = match.name || match.handle;
    return `<article class="cm-card">
      <header class="cm-card-head">
        <div><h3 class="cm-card-title">${esc(name)}</h3><span class="cm-handle">${esc('@' + match.handle.replace(/^@/, ''))}</span></div>
        <div class="cm-card-markers">
          <span class="cm-tier ${content ? (content.score_state === 'weak' ? 'cm-tier-weak' : 'cm-tier-work') : 'cm-tier-profile'}">${content ? workLabel : '画像初筛'}</span>
          ${hasScore ? `<span class="cm-score-pill">内容匹配 <strong>${esc(content.score)}</strong> 分</span>` : ''}
        </div>
      </header>
      ${content ? `<dl class="cm-content-evidence" aria-label="内容匹配依据">
        <div><dt>书中要点</dt><dd>${esc(content.book_point)}</dd></div>
        <div><dt>已有作品</dt><dd>${workHtml(content.works[0])}</dd></div>
        <div><dt>关联依据</dt><dd>${esc(content.connection)}</dd></div>
      </dl>` : `<div class="cm-profile-evidence">
        ${reasons.length ? `<ul class="cm-reasons" aria-label="初筛依据">${reasonList(reasons.slice(0, 1))}</ul>` : ''}
        <p class="cm-profile-note">当前结果暂无可核对的相关作品。</p>
      </div>`}
      <div class="cm-card-actions">
        <button type="button" class="cm-detail-toggle" data-cm-action="detail" data-handle="${esc(match.handle)}" aria-controls="${detailId}" aria-expanded="${open}">${open ? '收起依据' : '查看依据'}</button>
        <button type="button" class="cm-detail-toggle cm-work-search-button" data-cm-action="search-works" data-handle="${esc(match.handle)}">自动查作品</button>
        <button type="button" class="cm-save" data-cm-action="save" data-handle="${esc(match.handle)}" aria-pressed="${saved}">${shortlistView ? '移出备选' : saved ? '已加入备选' : '加入备选'}</button>
        ${suggestBackup ? `<span class="cm-score-recommend"${saved ? ' hidden' : ''}>可加入备选</span>` : ''}
      </div>
      <p class="cm-card-search-status" id="cm-card-search-${index}" data-cm-card-search hidden></p>
      <div class="cm-detail" id="${detailId}"${open ? '' : ' hidden'}>
        ${content?.works.length > 1 ? `<div class="cm-more-works"><h4>其他相关作品</h4>${content.works.slice(1).map(workHtml).join('')}</div>` : ''}
        ${content?.angle ? `<div class="cm-angle"><h4>可尝试的内容切入点</h4><p>${esc(content.angle)}</p></div>` : ''}
        ${hasScore && (content.score_reason || content.score_details?.length) ? scoreHtml(content) : ''}
        <dl class="cm-evidence">
          ${match.topic ? `<div><dt>匹配主题</dt><dd>${esc(match.topic)}</dd></div>` : ''}
          <div><dt>原商品类</dt><dd>${categories.length ? esc(categories.join('、')) : '暂未提供'}</dd></div>
          <div><dt>画像推断</dt><dd>${domains.length ? esc(domains.join('、')) : '暂未提供'}</dd></div>
        </dl>
        ${checks.length ? `<div class="cm-checks"><h4>待核验</h4><ul>${checks.map(check => `<li>${esc(check)}</li>`).join('')}</ul></div>` : ''}
        <button type="button" class="cm-work-manual" data-cm-action="add-work" data-handle="${esc(match.handle)}">手动补充作品</button>
      </div>
    </article>`;
  }

  function render(host, bookCode = '') {
    const routeKey = String(bookCode || '');
    const sampleRoute = Object.hasOwn(samples, routeKey);
    const firstVisit = !drafts.has(routeKey);
    if (firstVisit) {
      drafts.set(routeKey, {
        title: '', synopsis: '', audience: '', goal: 'content', sample: false,
        audienceMode: routeKey && !sampleRoute ? 'library' : 'manual',
        aiAudience: null, aiAudienceStale: false, libraryAudience: null,
        bookCode: '', source: 'manual', libraryOpen: false, libraryQuery: '', bookLimit: 10,
        expanded: new Set(), tab: 'results', result: null, workSearch: null,
      });
    }
    const draft = drafts.get(routeKey);
    draft.libraryOpen = false;
    host.innerHTML = screenHtml();
    const root = host.querySelector('.cm-screen');
    const form = root.querySelector('form');
    const goalHelp = root.querySelector('#cm-goal-help');
    const goalHelpButton = root.querySelector('.cm-goal-help-button');
    function toggleGoalHelp(open) {
      goalHelp.hidden = !open;
      goalHelpButton.setAttribute('aria-expanded', String(open));
      if (open) goalHelp.scrollIntoView({block: 'nearest', behavior: 'instant'});
    }
    goalHelpButton.addEventListener('click', () => toggleGoalHelp(goalHelp.hidden));
    goalHelpButton.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !goalHelp.hidden) {
        event.preventDefault();
        toggleGoalHelp(false);
      }
    });
    const action = name => root.querySelector(`[data-cm-action="${name}"]`);
    const getField = name => form.elements.namedItem(name);
    const library = root.querySelector('.cm-library');
    const bookTrigger = action('toggle-books');
    const bookDropdown = root.querySelector('#cm-book-dropdown');
    const bookSearch = root.querySelector('#cm-book-search');
    const bookList = root.querySelector('.cm-book-list');
    const bookOptions = () => Array.from(bookList.querySelectorAll('.cm-book-option'));
    const resultsPanel = root.querySelector('.cm-results');
    const resultsBody = root.querySelector('.cm-results-body');
    const resultsTitle = root.querySelector('#cm-results-title');
    const context = root.querySelector('[data-cm-results-context]');
    const resultAudience = root.querySelector('[data-cm-results-audience]');
    const live = root.querySelector('.cm-live');
    const workNotice = root.querySelector('[data-cm-work-notice]');
    const searchStatus = root.querySelector('[data-cm-work-search]');
    const searchMessage = root.querySelector('[data-cm-work-search-message]');
    const searchAnnouncement = root.querySelector('[data-cm-work-search-announcement]');
    const workDialog = root.querySelector('.cm-work-dialog');
    const workForm = workDialog.querySelector('form');
    const workSubmit = workForm.querySelector('.cm-work-submit');
    const workFeedback = workForm.querySelector('.cm-work-feedback');
    const workField = name => workForm.elements.namedItem(name);
    let workTrigger = null;
    let workSaving = false;

    function renderLibrary() {
      library.hidden = draft.source !== 'library';
      action('library').setAttribute('aria-pressed', String(draft.source === 'library'));
      action('manual').setAttribute('aria-pressed', String(draft.source === 'manual'));
      const selectedBook = draft.selectedBook?.book || draft.bookCode;
      const notice = root.querySelector('.cm-library-notice');
      const message = draft.pendingBook ? '正在读取书目信息…' : draft.bookError;
      notice.textContent = message || '';
      notice.hidden = !message;
      bookTrigger.querySelector('.cm-book-value').textContent = selectedBook || '查找图书';
      bookTrigger.setAttribute('aria-label', selectedBook ? `查找图书，已选${selectedBook}` : '查找图书');
      bookTrigger.setAttribute('aria-expanded', String(draft.libraryOpen));
      bookDropdown.hidden = !draft.libraryOpen;
      if (draft.libraryOpen) renderBookList();
    }

    function renderBookList() {
      if (draft.libraryError) {
        bookList.innerHTML = '<p>暂时无法读取书库。</p><button type="button" class="cm-book-change" data-cm-action="retry-library">重新加载</button>';
      } else if (!draft.books) {
        bookList.innerHTML = '<p role="status">正在加载书库…</p>';
      } else {
        const query = draft.libraryQuery.toLocaleLowerCase().trim();
        const found = draft.books.filter(book => [book.book, book.author, book.code].some(value => String(value || '').toLocaleLowerCase().includes(query)));
        bookList.innerHTML = found.slice(0, draft.bookLimit).map(book => `<button type="button" class="cm-book-option" data-cm-action="pick-book" data-code="${esc(book.code)}"${book.code === draft.bookCode ? ' aria-current="true"' : ''}>
          <strong>${esc(book.book)}</strong>${book.author ? `<span>${esc(book.author)}</span>` : ''}
        </button>`).join('') || '<p>没有找到图书，可以换个关键词或手动填写。</p>';
        if (found.length > draft.bookLimit) bookList.insertAdjacentHTML('beforeend', '<button type="button" class="cm-book-change" data-cm-action="more-books">查看更多图书</button>');
      }
    }

    function openBookDropdown() {
      draft.libraryOpen = true;
      draft.libraryQuery = '';
      draft.bookLimit = 10;
      bookSearch.value = '';
      renderLibrary();
      bookList.scrollTop = 0;
      bookSearch.focus();
      document.addEventListener('pointerdown', dismissBookDropdown, true);
      window.addEventListener('hashchange', closeBookDropdown);
      loadLibrary();
    }

    function closeBookDropdown(restoreFocus = false) {
      document.removeEventListener('pointerdown', dismissBookDropdown, true);
      window.removeEventListener('hashchange', closeBookDropdown);
      if (!draft.libraryOpen) return;
      draft.libraryOpen = false;
      bookTrigger.setAttribute('aria-expanded', 'false');
      bookDropdown.hidden = true;
      if (restoreFocus === true) bookTrigger.focus();
    }

    function dismissBookDropdown(event) {
      if (!root.isConnected || !library.contains(event.target)) closeBookDropdown();
    }

    function renderForm() {
      ['title', 'synopsis', 'audience', 'goal'].forEach(name => { getField(name).value = draft[name]; });
      const sampleLabel = root.querySelector('[data-cm-sample-label]');
      sampleLabel.hidden = !draft.sample;
      sampleLabel.textContent = draft.sample ? `示例图书 · ${samples[draft.sample].label}` : '';
      getField('title').setCustomValidity('');
      renderLibrary();
      renderAudience();
      renderSubmit();
    }

    const displayTitle = title => `《${title.replace(/^《|》$/g, '')}》`;

    function renderAudience() {
      const mode = draft.audienceMode;
      root.querySelectorAll('.cm-audience-mode').forEach(button => {
        button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
      });
      root.querySelectorAll('.cm-audience-panel').forEach(panel => { panel.hidden = panel.dataset.audiencePanel !== mode; });
      if (mode === 'manual') return;
      const panel = root.querySelector(`[data-audience-panel="${mode}"]`);
      const feedback = panel.querySelector('.cm-audience-feedback');
      const choices = panel.querySelector('.cm-audience-options');
      let message = '';
      let error = '';
      let source = null;
      if (mode === 'ai') {
        source = draft.aiAudience;
        const button = action('analyze-audience');
        button.disabled = Boolean(source?.loading || draft.pendingBook);
        button.textContent = source?.loading ? '正在分析…' : source?.error ? '重试分析' : source ? '重新分析' : '分析受众';
        if (source?.loading) message = '正在分析受众…';
        else if (source?.error) error = source.error;
        else if (source && !source.options.length) message = '暂未生成受众建议。可以补充简介后再试。';
        else if (draft.aiAudienceStale) message = '书名、简介或推广目标已更改，请重新分析。';
      } else if (!draft.bookCode) {
        message = '请先从书库选书，再选择已有的受众资料。';
      } else if (draft.pendingBook) {
        message = '正在读取书库受众…';
      } else if (draft.bookError) {
        message = '暂未读到书库受众，可以重新选书或手动填写。';
      } else {
        source = draft.libraryAudience;
        message = source?.options.length
          ? `勾选${displayTitle(draft.selectedBook?.book || draft.title)}的受众，可多选。`
          : '这本书暂无已解析的受众资料，可用 AI 分析或手动填写。';
      }
      feedback.hidden = !(message || error);
      feedback.setAttribute('role', error ? 'alert' : 'status');
      feedback.textContent = error || message;
      choices.innerHTML = audienceChoices(source);
    }

    function renderSubmit() {
      const submit = form.querySelector('button[type="submit"]');
      const loading = draft.result?.loading;
      submit.disabled = Boolean(loading || draft.pendingBook);
      submit.textContent = loading ? '正在匹配…' : '匹配达人';
    }

    function searchInEmptyResults() {
      const {result, workSearch: search} = draft;
      return draft.tab === 'results' && result && !result.loading && !result.matches?.length &&
        search && !search.handle && ['loading', 'empty', 'error'].includes(search.state);
    }

    function renderResults() {
      const {result} = draft;
      const key = result?.key;
      const title = result ? displayTitle(result.values.title) : '';
      const audience = result?.values.audience;
      resultAudience.hidden = !audience;
      resultAudience.textContent = audience ? `目标受众 · ${audience}` : '';
      action('results').setAttribute('aria-pressed', String(draft.tab === 'results'));
      action('shortlist').setAttribute('aria-pressed', String(draft.tab === 'shortlist'));
      const search = draft.workSearch;
      const searchingEmptyResults = searchInEmptyResults();
      resultsPanel.setAttribute('aria-busy', String(draft.tab === 'results' && Boolean(result?.loading || (searchingEmptyResults && search.state === 'loading'))));
      if (draft.tab === 'shortlist') {
        context.textContent = title ? `${title}的备选达人` : '按书保存备选达人';
        const saved = shortlist(key);
        const refreshed = new Map((result?.matches || []).filter(contentEvidence).map(match => [match.handle, match]));
        resultsBody.innerHTML = saved.length
          ? `<div class="cm-cards">${saved.map((match, index) => cardHtml(refreshed.get(match.handle) || match, key, draft.expanded, index, true)).join('')}</div>`
          : stateHtml('还没有备选达人', '在匹配结果中选择“加入备选”，即可在这里继续核验。');
        return;
      }
      if (!result) {
        context.textContent = '按书查看匹配依据和待核验项。';
        resultsBody.innerHTML = stateHtml('从一本书开始', '从书库选一本书，或直接填写书名和简介。');
        return;
      }
      context.textContent = `${result.sample ? '示例图书' : '图书'}${title} · ${goals[result.values.goal]}`;
      if (result.loading) {
        resultsBody.innerHTML = stateHtml('正在核对已收录的作品', '先查作品资料库。如果没有命中，会继续查找公开作品。', 'loading');
      } else if (searchingEmptyResults) {
        if (search.state === 'loading') {
          resultsBody.innerHTML = stateHtml('正在查找公开作品', esc(search.message), 'loading');
        } else {
          const titles = {
            unverified_owner: '找到作品，暂未核对到库内账号',
            no_content_overlap: '已核对作品，内容依据不足',
            missing_work_content: '已核对到账号，作品内容不足',
            no_public_works: '本次未搜到可核对的抖音作品',
            search_unavailable: '公开作品查询暂不可用',
            search_unconfigured: '服务器尚未开通公开作品查询',
            analysis_unavailable: '作品内容分析未完成',
          };
          const heading = titles[search.reason] || (search.state === 'error' ? '本次查询未完成' : '本次未找到可推荐的作品');
          const detail = search.terms?.length ? `<p class="cm-search-detail">检索词 · ${esc(search.terms.join('、'))}</p>` : '';
          const coverage = Number.isInteger(search.linkCount) && Number.isInteger(search.verifiedCount) &&
            ['unverified_owner', 'no_content_overlap', 'missing_work_content'].includes(search.reason)
            ? `<p class="cm-search-detail">找到 ${search.linkCount} 条作品链接，其中 ${search.verifiedCount} 条可核对到库内账号。</p>` : '';
          const retry = search.reason === 'search_unconfigured' ? '' : '<button type="button" class="cm-retry" data-cm-action="retry-search">重新查找作品</button>';
          resultsBody.innerHTML = stateHtml(heading, esc(search.message), search.state === 'error' ? 'error' : '', detail + coverage + retry);
        }
      } else if (result.error) {
        resultsBody.innerHTML = stateHtml('暂时无法匹配', esc(result.error), 'error', '<button type="button" class="cm-retry" data-cm-action="retry-match">重试匹配</button>');
      } else if (!result.matches.length) {
        if (result.contentStatus === 'missing_synopsis') {
          resultsBody.innerHTML = stateHtml('还需要图书简介', esc(result.contentNotice), '',
            '<button type="button" class="cm-retry" data-cm-action="fill-synopsis">去补内容简介</button>');
        } else {
          const failed = ['analysis_unavailable', 'works_unavailable'].includes(result.contentStatus);
          resultsBody.innerHTML = stateHtml(failed ? '本次匹配未完成' : '已收录的作品暂未匹配到这本书',
            esc(result.contentNotice || result.summary || '可以查找公开作品。'), failed ? 'error' : '',
            failed ? '<button type="button" class="cm-retry" data-cm-action="retry-match">重试匹配</button>' : '');
        }
      } else {
        const notice = result.contentNotice || (result.matches.some(contentEvidence) ? '' : '当前只有画像初筛结果。可自动查找相关作品，再核对作品与图书内容。');
        resultsBody.innerHTML = `${notice ? `<p class="cm-content-notice">${esc(notice)}</p>` : ''}<div class="cm-cards">${result.matches.map((match, index) => cardHtml(match, key, draft.expanded, index)).join('')}</div>`;
      }
    }

    draft.paintForm = () => {
      if (root.isConnected) renderForm();
    };
    draft.paintAudience = () => {
      if (root.isConnected) renderAudience();
    };
    draft.paintWorkNotice = () => {
      if (!root.isConnected) return;
      workNotice.textContent = draft.workNotice || '';
      workNotice.hidden = !draft.workNotice;
    };
    function renderWorkSearch() {
      const search = draft.workSearch;
      const loading = search?.state === 'loading';
      for (const button of root.querySelectorAll('[data-cm-action="search-works"]')) {
        const handle = button.dataset.handle || '';
        const active = search?.handle === handle;
        const waiting = loading && search.waitingHandle === handle && !active;
        const inline = button.closest('.cm-card')?.querySelector('[data-cm-card-search]');
        const message = active ? search.message : waiting ? '已有作品查询在进行，请等当前查询完成。' : '';
        button.setAttribute('aria-disabled', String(loading || Boolean(draft.result?.loading)));
        button.textContent = loading && active ? '正在查找…' : '自动查作品';
        if (inline) {
          inline.hidden = !message;
          inline.textContent = message;
          inline.dataset.state = message ? search.state : '';
        }
        if (message || (!inline && search?.message)) button.setAttribute('aria-describedby', inline ? inline.id : searchMessage.id);
        else button.removeAttribute('aria-describedby');
      }
      const messageInResults = searchInEmptyResults();
      searchStatus.hidden = !search?.message || Boolean(messageInResults);
      if (messageInResults) renderResults();
      searchMessage.textContent = search?.message || '';
      searchStatus.dataset.state = search?.state || '';
      action('fill-work-brief').hidden = !search?.inputField;
      const announce = loading && search.waitingHandle !== undefined && search.waitingHandle !== search.handle
        ? '已有作品查询在进行，请等当前查询完成。' : search?.message || '';
      if (searchAnnouncement.textContent !== announce) searchAnnouncement.textContent = announce;
    }

    function revealWorkSearch(trigger) {
      const status = trigger.closest('.cm-card')?.querySelector('[data-cm-card-search]') || searchStatus;
      const bottom = Math.min(window.innerHeight, resultsPanel.getBoundingClientRect().bottom);
      if (!status.hidden && status.getBoundingClientRect().bottom > bottom) {
        status.scrollIntoView({block: 'nearest', behavior: 'instant'});
      }
    }

    draft.paintWorkSearch = () => {
      if (root.isConnected) renderWorkSearch();
    };
    draft.paintResults = (result, announce = true) => {
      if (!root.isConnected) return;
      renderSubmit();
      renderResults();
      renderWorkSearch();
      if (announce && draft.tab === 'results') live.textContent = result.matches?.length ? '已更新匹配结果' : resultsBody.querySelector('h3')?.textContent || '';
      if (result.scrollPosition !== undefined && document.activeElement === resultsTitle && Math.abs(window.scrollY - result.scrollPosition) < 20) {
        resultsPanel.scrollIntoView({block: 'start', behavior: 'instant'});
      }
    };

    async function loadLibrary() {
      if (draft.books || draft.libraryLoading) return;
      draft.libraryError = false;
      draft.libraryLoading = true;
      try {
        const data = await jget('/api/books');
        draft.books = Array.isArray(data.books) ? data.books : [];
      } catch (_) {
        draft.libraryError = true;
      } finally {
        draft.libraryLoading = false;
        draft.paintForm();
      }
    }

    async function pickBook(code, row) {
      closeBookDropdown();
      if (code === draft.bookCode && !draft.bookError && !draft.pendingBook) {
        renderLibrary();
        return;
      }
      invalidateAiAudience();
      const selection = {touched: new Set()};
      Object.assign(draft, {
        sample: false, source: 'library', bookCode: code, selectedBook: row, libraryOpen: false,
        title: row?.book || '', synopsis: '', bookError: '', pendingBook: selection, libraryAudience: null,
      });
      draft.paintForm();
      try {
        const detail = await jget(`/api/book?${new URLSearchParams({code})}`);
        if (draft.pendingBook !== selection) return;
        const approved = (detail.marketing_rows || []).filter(item => item.status === 'approved');
        const approvedValue = item => item?.text || item?.main;
        const synopsis = [detail.book?.内容简介, detail.cip?.内容提要, approvedValue(approved.find(item => item.key === 'summary'))].find(value => typeof value === 'string' && value.trim());
        draft.selectedBook = detail.row || row;
        if (!selection.touched.has('title')) draft.title = detail.row?.book || detail.record?.book || draft.title;
        if (!selection.touched.has('synopsis') && typeof synopsis === 'string') draft.synopsis = synopsis.slice(0, 3000);
        draft.libraryAudience = {options: extractLibraryAudiences(detail), selected: new Set()};
      } catch (_) {
        if (draft.pendingBook === selection) draft.bookError = '暂时无法读取这本书的详情，可以补充书名和简介。';
      } finally {
        if (draft.pendingBook === selection) {
          draft.pendingBook = null;
          draft.paintForm();
          if (draft.workSearch?.waitingFor === 'book') {
            draft.workSearch = null;
            draft.paintWorkSearch();
          }
        }
      }
    }

    function titleEntered(title) {
      if (title) return true;
      getField('title').setCustomValidity('请填写书名。');
      getField('title').reportValidity();
      return false;
    }

    function invalidateAiAudience() {
      if (!draft.aiAudience) return;
      draft.aiAudience.controller?.abort();
      draft.aiAudience = null;
      draft.aiAudienceStale = true;
    }

    async function analyzeAudience() {
      if (draft.aiAudience?.loading || draft.pendingBook) return;
      const values = bookInputs(draft);
      if (!titleEntered(values.title)) return;
      const run = {values, controller: new AbortController(), loading: true, options: [], selected: new Set()};
      draft.aiAudience = run;
      draft.aiAudienceStale = false;
      renderAudience();
      try {
        const response = await fetch('/api/creator-match/audiences', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(values), signal: run.controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !Array.isArray(data.audiences)) throw new Error(data.error || '暂时无法分析受众，请重试。');
        run.options = data.audiences.filter(item => typeof item?.text === 'string' && item.text.trim())
          .map(item => ({label: typeof item.label === 'string' ? item.label.trim() : '', text: item.text.trim()}));
      } catch (error) {
        run.error = error.message || '暂时无法分析受众，请重试。';
      } finally {
        run.loading = false;
        run.controller = null;
        if (draft.aiAudience === run && draft.audienceMode === 'ai') draft.paintAudience();
      }
    }

    async function runMatch(scroll = false, retry = null) {
      if (draft.result?.loading || (!retry && draft.pendingBook)) return;
      const values = retry?.values || payload(draft);
      if (!titleEntered(values.title)) return;
      if (draft.workSearch?.state === 'loading' && !draft.workSearch.handle &&
          JSON.stringify(values) === JSON.stringify(draft.result?.values)) return;
      draft.workSearch?.controller?.abort();
      draft.workSearch = null;
      const result = {loading: true, values, sample: retry?.sample ?? draft.sample, key: retry?.key ?? shortlistKey(draft, values)};
      draft.result = result;
      draft.tab = 'results';
      draft.expanded.clear();
      draft.workNotice = '';
      draft.paintWorkNotice();
      live.textContent = '正在匹配达人';
      renderSubmit();
      renderResults();
      renderWorkSearch();
      if (scroll && resultsPanel.getBoundingClientRect().top > window.innerHeight * 0.6) {
        resultsTitle.focus({preventScroll: true});
        resultsPanel.scrollIntoView({block: 'start', behavior: 'instant'});
        result.scrollPosition = window.scrollY;
      }
      try {
        const response = await fetch('/api/creator-match', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !Array.isArray(data.matches)) throw new Error(data.error || '达人匹配服务暂不可用，请稍后重试。');
        Object.assign(result, matchResponse(data));
      } catch (error) {
        result.error = error.message || '请检查连接后重试。';
      } finally {
        result.loading = false;
        if (draft.result === result) {
          if (draft.workSearch?.waitingFor === 'match') draft.workSearch = null;
          if (!result.error && !result.matches.length && values.synopsis && ['no_works', 'no_match'].includes(result.contentStatus)) {
            renderSubmit();
            await searchWorks(action('search-works'), true);
          } else {
            draft.paintResults(result);
          }
        }
      }
    }

    async function searchWorks(trigger, afterLocalMiss = false) {
      const base = draft.result;
      const handle = trigger.dataset.handle || '';
      if (draft.workSearch?.state === 'loading') {
        draft.workSearch.waitingHandle = handle;
        draft.paintWorkSearch();
        revealWorkSearch(trigger);
        return;
      }
      const snapshot = base;
      const waitingFor = base?.loading ? 'match' : !snapshot && draft.pendingBook ? 'book' : '';
      if (waitingFor) {
        const message = waitingFor === 'book'
          ? '正在读取书库图书信息，请等读取完成后再查作品。'
          : '正在匹配图书，请等匹配完成后再查作品。';
        draft.workSearch = {handle, state: 'waiting', waitingFor, message};
        draft.paintWorkSearch();
        revealWorkSearch(trigger);
        return;
      }
      const values = snapshot?.values || payload(draft);
      if (!values.title || !values.synopsis) {
        const message = snapshot
          ? '上次匹配缺少书名或简介。请补齐图书信息，点击「匹配达人」后再查作品。'
          : '请先填写书名和内容简介，再自动查找作品。';
        draft.workSearch = {handle, state: 'input', inputField: !values.title ? 'title' : 'synopsis', message};
        draft.paintWorkSearch();
        revealWorkSearch(trigger);
        return;
      }
      const name = trigger.closest('.cm-card')?.querySelector('.cm-card-title')?.textContent;
      const topic = name ? `「${name}」的` : '与这本书相关的';
      const search = {
        handle, state: 'loading', controller: new AbortController(),
        message: afterLocalMiss ? '资料库里的作品没有命中。正在按本书主题查找公开作品，并核对发布账号。' : `正在查找${topic}公开作品，并核对出处。可能需要几十秒。`,
      };
      draft.workSearch = search;
      draft.paintWorkSearch();
      revealWorkSearch(trigger);
      const submitted = {values, key: snapshot?.key ?? shortlistKey(draft, values), sample: snapshot?.sample ?? draft.sample};
      const progressTimer = window.setTimeout(() => {
        if (draft.workSearch !== search || search.state !== 'loading') return;
        search.message = `仍在查找${topic}公开作品，请稍候。`;
        draft.paintWorkSearch();
      }, 10000);
      try {
        const response = await fetch('/api/creator-match/works/search', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(handle ? {...values, handle} : values), signal: search.controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !Array.isArray(data.matches)) {
          const message = typeof data.error === 'string' && data.error !== 'not found' ? data.error : '公开作品查询暂不可用，可稍后重试。';
          throw new Error(message);
        }
        if (draft.workSearch !== search || draft.result !== base) return;
        const matching = matchResponse(data);
        const notice = typeof data.search_notice === 'string' ? data.search_notice : '';
        search.reason = data.search_reason;
        search.terms = Array.isArray(data.search_terms) ? data.search_terms.filter(term => typeof term === 'string') : [];
        search.linkCount = data.public_work_count;
        search.verifiedCount = data.verified_work_count;
        const targeted = handle ? matching.matches.find(match => match.handle === (data.target_handle || handle)) : null;
        const hasEvidence = handle ? Boolean(targeted && contentEvidence(targeted)) : matching.matches.some(contentEvidence);
        if (data.search_state === 'empty' || !hasEvidence) {
          search.state = ['search_unavailable', 'search_unconfigured', 'analysis_unavailable'].includes(search.reason) ? 'error' : 'empty';
          search.message = notice || '暂未查到可核对的相关作品。';
          if (!base && !handle) {
            draft.result = {...submitted, ...matching};
            draft.paintResults(draft.result, false);
          }
          return;
        }
        if (targeted) {
          const current = base?.matches || [];
          matching.matches = current.some(match => match.handle === targeted.handle)
            ? current.map(match => match.handle === targeted.handle ? targeted : match)
            : [...current, targeted];
        }
        search.state = data.search_state === 'indexed' ? 'indexed' : 'found';
        search.message = notice || (search.state === 'indexed' ? '已按现有作品资料重新匹配。' : '已按查到的公开作品更新匹配结果。');
        const focused = document.activeElement === trigger;
        draft.result = {...submitted, ...matching};
        draft.workNotice = '';
        draft.paintWorkNotice();
        draft.paintResults(draft.result, false);
        if (focused && !trigger.isConnected && root.isConnected) {
          const refreshed = Array.from(resultsBody.querySelectorAll('[data-cm-action="search-works"]')).find(button => button.dataset.handle === handle);
          const nextTrigger = refreshed || action('search-works');
          nextTrigger.focus({preventScroll: true});
          revealWorkSearch(nextTrigger);
        }
      } catch (error) {
        if (draft.workSearch !== search || draft.result !== base) return;
        search.state = 'error';
        search.message = error instanceof TypeError || !error?.message
          ? '无法连接作品查询服务，可稍后重试。' : error.message;
      } finally {
        window.clearTimeout(progressTimer);
        if (draft.workSearch === search) {
          search.controller = null;
          draft.paintWorkSearch();
          if (document.activeElement === trigger) revealWorkSearch(trigger);
        }
      }
    }

    function setWorkFeedback(message) {
      workFeedback.textContent = message;
      workFeedback.hidden = !message;
    }

    function openWorkDialog(trigger) {
      if (workDialog.open) return;
      workTrigger = trigger;
      workForm.reset();
      workForm.querySelectorAll('input').forEach(input => input.setCustomValidity(''));
      setWorkFeedback('');
      workField('handle').value = trigger.dataset.handle || '';
      workDialog.showModal();
      workField(trigger.dataset.handle ? 'title' : 'handle').focus();
    }

    function validateWorkField(field, value, message) {
      if (value) return true;
      field.setCustomValidity(message);
      field.reportValidity();
      return false;
    }

    function setWorkSaving(saving) {
      workSaving = saving;
      workSubmit.disabled = saving;
      workSubmit.textContent = saving ? '正在保存…' : '保存作品';
      workForm.querySelector('.cm-work-fields').disabled = saving;
      action('close-work').disabled = saving;
    }

    async function saveWork(event) {
      event.preventDefault();
      if (workSaving) return;
      const handle = workField('handle').value.trim().replace(/^@/, '').trim();
      const title = workField('title').value.trim();
      const url = workField('url').value.trim();
      const validUrl = workUrl(url);
      if (!validateWorkField(workField('handle'), handle, '请填写达人库内的抖音号。') ||
          !validateWorkField(workField('title'), title, '请填写作品标题。') ||
          (url && !validateWorkField(workField('url'), validUrl, '请填写 HTTPS 原链接。'))) return;
      const work = {title};
      const text = workField('text').value.trim();
      const published = workField('published').value;
      if (text) work.text = text;
      if (validUrl) work.url = validUrl;
      if (published) work.published = published;
      setWorkFeedback('');
      setWorkSaving(true);
      try {
        const response = await fetch('/api/creator-match/works', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({handle, works: [work]}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.ok !== true) {
          const fallback = response.status === 404 ? '达人库里没有找到这个抖音号，请核对后重试。' : '暂时无法保存作品，请重试。';
          setWorkFeedback(typeof data.error === 'string' && data.error !== 'not found' ? data.error : fallback);
          return;
        }
        draft.workNotice = '作品已保存。点击「匹配达人」可用当前图书信息重新匹配。';
        if (workDialog.open) workDialog.close();
        draft.paintWorkNotice();
      } catch (_) {
        setWorkFeedback('连接失败，请重试保存作品。');
      } finally {
        setWorkSaving(false);
      }
    }

    workForm.addEventListener('submit', saveWork);
    workForm.addEventListener('input', event => event.target.setCustomValidity(''));
    workDialog.addEventListener('cancel', event => { if (workSaving) event.preventDefault(); });
    workDialog.addEventListener('close', () => {
      (workTrigger?.isConnected ? workTrigger : action('add-work'))?.focus();
      workTrigger = null;
    });

    function useSample(autoRun, scroll = false) {
      invalidateAiAudience();
      const sample = sampleRoute ? routeKey : 'sample';
      const {title, synopsis, audience, goal} = samples[sample];
      Object.assign(draft, {
        title, synopsis, audience, goal, sample, source: 'manual', bookCode: '', selectedBook: null, bookError: '', pendingBook: null,
        audienceMode: 'manual', libraryAudience: null, aiAudienceStale: false,
      });
      draft.paintForm();
      if (autoRun) runMatch(scroll);
    }

    form.addEventListener('input', event => {
      const input = event.target;
      if (input.name === 'audience_choice') {
        const source = draft.audienceMode === 'ai' ? draft.aiAudience : draft.libraryAudience;
        const index = Number(input.value);
        if (!source?.options[index]) return;
        if (input.checked) source.selected.add(index);
        else source.selected.delete(index);
        return;
      }
      draft[input.name] = input.value;
      draft.pendingBook?.touched.add(input.name);
      if (['title', 'synopsis'].includes(input.name) && draft.sample) {
        draft.sample = false;
        root.querySelector('[data-cm-sample-label]').hidden = true;
      }
      if (input.name === 'title') input.setCustomValidity('');
      if (draft.aiAudience && JSON.stringify(bookInputs(draft)) !== JSON.stringify(draft.aiAudience.values)) {
        invalidateAiAudience();
        renderAudience();
      }
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      runMatch(true);
    });
    bookSearch.addEventListener('input', () => {
      draft.libraryQuery = bookSearch.value;
      draft.bookLimit = 10;
      renderBookList();
      bookList.scrollTop = 0;
    });

    library.addEventListener('focusout', event => {
      if (event.relatedTarget && !library.contains(event.relatedTarget)) closeBookDropdown();
    });
    library.addEventListener('keydown', event => {
      if (event.isComposing) return;
      if (event.key === 'Escape' && draft.libraryOpen) {
        event.preventDefault();
        closeBookDropdown(true);
        return;
      }
      if (event.target === bookTrigger && event.key === 'ArrowDown') {
        event.preventDefault();
        if (draft.libraryOpen) bookSearch.focus();
        else openBookDropdown();
        return;
      }
      if (!draft.libraryOpen) return;
      if (event.target === bookSearch && event.key === 'Enter') {
        event.preventDefault();
        bookOptions()[0]?.click();
        return;
      }
      if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
      const options = bookOptions();
      const index = options.indexOf(event.target);
      if (index < 0 && event.target !== bookSearch) return;
      event.preventDefault();
      const nextIndex = index + (event.key === 'ArrowDown' ? 1 : -1);
      if (index === 0 && nextIndex < 0) bookSearch.focus();
      else options[nextIndex]?.focus();
    });

    root.addEventListener('click', event => {
      const button = event.target.closest('[data-cm-action]');
      if (!button) return;
      switch (button.dataset.cmAction) {
        case 'library':
          draft.source = 'library';
          renderLibrary();
          bookTrigger.focus();
          break;
        case 'toggle-books':
          if (draft.libraryOpen) closeBookDropdown(true);
          else openBookDropdown();
          break;
        case 'manual':
          if (draft.bookCode) {
            invalidateAiAudience();
            Object.assign(draft, {bookCode: '', selectedBook: null, pendingBook: null, bookError: '', libraryAudience: null});
          }
          draft.source = 'manual';
          renderLibrary();
          renderAudience();
          renderSubmit();
          getField('title').focus();
          break;
        case 'retry-library': loadLibrary(); renderBookList(); break;
        case 'more-books': {
          const next = draft.bookLimit;
          draft.bookLimit += 10;
          renderBookList();
          bookOptions()[next]?.focus();
          break;
        }
        case 'pick-book': {
          const row = draft.books.find(book => book.code === button.dataset.code);
          if (row) {
            pickBook(row.code, row);
            bookTrigger.focus();
          }
          break;
        }
        case 'sample':
          if (!sampleRoute && !draft.sample && [draft.title, draft.synopsis, draft.audience].some(value => value.trim())) {
            go('creator-match', 'sample');
          } else useSample(true, true);
          break;
        case 'audience-mode':
          draft.audienceMode = button.dataset.mode;
          renderAudience();
          break;
        case 'analyze-audience': analyzeAudience(); break;
        case 'search-works': searchWorks(button); break;
        case 'retry-search': searchWorks(action('search-works')); break;
        case 'fill-synopsis': getField('synopsis').focus(); break;
        case 'fill-work-brief': getField(draft.workSearch?.inputField || 'title').focus(); break;
        case 'add-work': openWorkDialog(button); break;
        case 'close-work': if (!workSaving) workDialog.close(); break;
        case 'retry-match': runMatch(true, draft.result); break;
        case 'results':
        case 'shortlist': draft.tab = button.dataset.cmAction; renderResults(); renderWorkSearch(); break;
        case 'detail': {
          const handle = button.dataset.handle;
          const open = button.getAttribute('aria-expanded') !== 'true';
          if (open) draft.expanded.add(handle);
          else draft.expanded.delete(handle);
          button.setAttribute('aria-expanded', String(open));
          button.textContent = open ? '收起依据' : '查看依据';
          root.querySelector(`#${button.getAttribute('aria-controls')}`).hidden = !open;
          break;
        }
        case 'save': {
          const inShortlist = draft.tab === 'shortlist';
          const key = draft.result?.key;
          const candidates = inShortlist ? shortlist(key) : draft.result?.matches || [];
          const handle = button.dataset.handle;
          const index = candidates.findIndex(item => item.handle === handle);
          const match = candidates[index];
          if (!key || !match) return;
          const {added, persistent} = toggleSave(key, match);
          if (inShortlist) {
            renderResults();
            renderWorkSearch();
            const remaining = resultsBody.querySelectorAll('.cm-save');
            (remaining[Math.min(index, remaining.length - 1)] || action('shortlist')).focus();
          } else {
            button.setAttribute('aria-pressed', String(added));
            button.textContent = added ? '已加入备选' : '加入备选';
            const suggestion = button.closest('.cm-card').querySelector('.cm-score-recommend');
            if (suggestion) suggestion.hidden = added;
          }
          live.textContent = `${match.name || match.handle}${added ? '已加入备选' : '已移出备选'}${persistent ? '' : '，变更保留至本次使用结束'}`;
          break;
        }
      }
    });

    draft.paintForm();
    draft.paintWorkNotice();
    renderResults();
    renderWorkSearch();
    if (firstVisit && sampleRoute) useSample(true);
    else if (firstVisit && routeKey) pickBook(routeKey);
  }

  return {render};
})();
