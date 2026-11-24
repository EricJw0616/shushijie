'use strict';

window.XhsWriting = (() => {
  const brief = {title: '', materials: '', audience: '', instructions: '', count: 1};
  const materialLimit = 16000;
  const imageLimit = 220 * 1024;
  const referenceLimit = 5;
  const imageTypes = new Set(['image/jpeg', 'image/png', 'image/webp']);
  const segmenter = window.Intl.Segmenter ? new Intl.Segmenter('zh', {granularity: 'grapheme'}) : null;
  let cover = null;
  let references = [];
  const imports = [];
  let notes = [];
  let active = 0;
  let bookSource = 'library';
  let generatedFrom = null;
  let generation = null;
  let pending = '';
  let error = '';
  let refresh = () => {};

  function characters(value, countSpaces = false) {
    const visible = countSpaces ? value.trim() : value.replace(/\s/g, '');
    return segmenter ? Array.from(segmenter.segment(visible)).length : Array.from(visible).length;
  }

  function noteText(note, markdown = false) {
    const tags = note.tags.map(tag => `#${tag}`).join(' ');
    return [markdown ? `# ${note.title.trim()}` : note.title.trim(), note.body.trim(), tags]
      .filter(Boolean).join('\n\n');
  }

  async function readJson(response, fallback) {
    const result = await response.json().catch(() => null);
    if (!response.ok || !result || result.ok === false) throw new Error(result?.error || fallback);
    return result;
  }

  function dataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('无法读取图片。'));
      reader.readAsDataURL(blob);
    });
  }

  async function prepareImage(blob, name) {
    const extension = /\.(jpe?g|png|webp)$/i.test(name);
    if ((!imageTypes.has(blob.type) && !(extension && (!blob.type || blob.type === 'application/octet-stream'))) || !blob.size) {
      throw new Error('请选择 JPEG、PNG 或 WebP 图片。');
    }
    const url = URL.createObjectURL(blob);
    try {
      const image = new Image();
      image.src = url;
      await image.decode().catch(() => { throw new Error('图片无法打开，请检查文件是否完整。'); });
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      const longest = Math.max(image.naturalWidth, image.naturalHeight);
      for (const [size, quality, format] of [[1200, .84, 'image/webp'], [960, .77, 'image/webp'], [760, .73, 'image/jpeg'], [540, .7, 'image/jpeg']]) {
        const scale = Math.min(1, size / longest);
        canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
        if (format === 'image/jpeg') {
          ctx.fillStyle = '#fff';
          ctx.fillRect(0, 0, canvas.width, canvas.height);
        }
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        const imageBlob = await new Promise(resolve => canvas.toBlob(resolve, format, quality));
        if (imageBlob && imageBlob.size <= imageLimit) return {name, data: await dataUrl(imageBlob)};
      }
      throw new Error('图片压缩后仍过大，请改用尺寸较小的图。');
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function imagePlanHtml(plan) {
    const items = Array.isArray(plan) ? plan : [plan];
    const lines = items.map(item => {
      if (typeof item === 'string') return item.trim();
      if (!item || typeof item !== 'object') return '';
      return Object.values(item).filter(value => typeof value === 'string').join(' · ');
    }).filter(Boolean);
    if (!lines.length) return '';
    return `<details class="xhs-evidence"><summary>配图建议 (${lines.length})</summary>
      <ul>${lines.map(line => `<li>${esc(line)}</li>`).join('')}</ul></details>`;
  }

  function download() {
    const text = notes.map(note => noteText(note, true)).join('\n\n---\n\n');
    const url = URL.createObjectURL(new Blob([text + '\n'], {type: 'text/markdown;charset=utf-8'}));
    const link = document.createElement('a');
    const name = generatedFrom.title.replace(/[\\/:*?"<>|\x00-\x1f]/g, '').slice(0, 50);
    link.href = url;
    link.download = `${name || '图书'}-小红书笔记.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function render(host) {
    host.innerHTML = `<div class="xhs-screen">
      <header class="page-head xhs-head">
        <div><h1>小红书笔记</h1><p>网页可写文案、核对资料、获取配图建议并导出 Markdown。</p></div>
        <section class="xhs-native" aria-labelledby="xhs-native-title">
          <div><h2 id="xhs-native-title">原版完整创作 · macOS</h2><p>实拍图、图解和海报 · Word 导出</p>
            <p class="xhs-field-message" data-native-status role="status">正在检查桌面版…</p></div>
          <button type="button" class="btn sm" data-native-open disabled>打开桌面版</button>
        </section>
      </header>
      <div class="xhs-workspace">
        <section class="xhs-panel" aria-labelledby="xhs-brief-heading">
          <h2 id="xhs-brief-heading">创作资料</h2>
          <form class="xhs-form">
            <section class="xhs-book-entry" aria-labelledby="xhs-book-heading">
              <h3 id="xhs-book-heading">图书来源</h3>
              <div class="xhs-book-sources" role="group" aria-label="图书来源">
                <button type="button" class="btn" data-book-source="library" aria-controls="xhs-library" aria-pressed="false">从书库选书</button>
                <button type="button" class="btn" data-book-source="manual" aria-controls="xhs-book-title" aria-pressed="false">手动填写</button>
              </div>
              <div class="xhs-library" id="xhs-library" hidden>
                <label class="xhs-field" for="xhs-book-search"><span>搜索书库</span>
                  <input id="xhs-book-search" type="search" placeholder="输入书名、作者或书码" autocomplete="off"></label>
                <ul class="xhs-book-results" data-library-books aria-label="书库图书" hidden></ul>
                <p class="xhs-field-message" data-library-status role="status" hidden></p>
                <button class="btn sm" type="button" data-library-retry hidden>重试加载书库</button>
                <div class="xhs-library-preview" data-library-preview hidden></div>
              </div>
              <label class="xhs-field" for="xhs-book-title"><span>书名</span><input id="xhs-book-title" name="title" required maxlength="200" placeholder="输入要推广的图书"></label>
            </section>
            <div class="xhs-field">
              <div class="xhs-field-line"><label for="xhs-materials">图书资料</label>
                <button type="button" class="xhs-link" data-import>上传内文</button></div>
              <textarea id="xhs-materials" name="materials" rows="7" required maxlength="${materialLimit}"
                placeholder="粘贴内容简介、书中片段、作者或版本信息。保留可核对的原句，方便回查。"></textarea>
              <input type="file" accept=".txt,.md,.markdown,.docx,.pdf" data-material-file multiple hidden>
              <p class="xhs-field-message">支持 TXT、Markdown、Word（DOCX）和 PDF。最多使用 ${materialLimit.toLocaleString('zh-CN')} 字。</p>
              <p class="xhs-field-message" data-import-status role="status" hidden></p>
              <ul class="xhs-import-results" data-import-results hidden></ul>
            </div>
            <section class="xhs-media" aria-labelledby="xhs-media-heading">
              <h3 id="xhs-media-heading">配图参考 <small>选填</small></h3>
              <p class="xhs-field-message">用于生成配图建议。支持 JPEG、PNG、WebP。</p>
              <div class="xhs-media-actions">
                <button class="btn sm" type="button" data-cover-pick>上传封面</button>
                <button class="btn sm" type="button" data-reference-pick>上传参考图</button>
                <input type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" data-cover-file hidden>
                <input type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" data-reference-files multiple hidden>
              </div>
              <p class="xhs-field-message" data-media-status role="status" hidden></p>
              <div class="xhs-media-grid" data-images hidden></div>
            </section>
            <label class="xhs-field"><span>目标读者 <small>选填</small></span>
              <input name="audience" maxlength="400" placeholder="例如想找亲子共读故事的家长"></label>
            <label class="xhs-field"><span>创作要求 <small>选填</small></span>
              <textarea name="instructions" rows="2" maxlength="1500" placeholder="例如突出送礼场景，语气轻松，保留悬念"></textarea></label>
            <div class="xhs-form-actions">
              <div class="xhs-count">
                <label for="xhs-count">生成篇数</label>
                <div class="xhs-stepper">
                  <button type="button" data-count-step="-1" aria-label="减少一篇">−</button>
                  <input type="number" id="xhs-count" name="count" inputmode="numeric" min="1" max="20" step="1" required aria-describedby="xhs-count-range">
                  <button type="button" data-count-step="1" aria-label="增加一篇">＋</button>
                </div>
                <span id="xhs-count-range">1–20 篇</span>
              </div>
              <button class="btn primary" type="submit">生成笔记</button>
            </div>
          </form>
        </section>
        <section class="xhs-panel xhs-output" aria-labelledby="xhs-output-heading">
          <div class="xhs-panel-heading"><h2 id="xhs-output-heading">笔记草稿</h2>
            <button class="btn sm" type="button" data-download hidden>导出 Markdown</button></div>
          <p class="xhs-status" role="status" hidden></p>
          <p class="xhs-error" role="alert" hidden></p>
          <p class="xhs-field-message" data-vision-status hidden></p>
          <ul class="xhs-import-results" data-note-failures hidden></ul>
          <div class="xhs-notes"></div>
        </section>
      </div>
      <dialog class="xhs-image-dialog" aria-labelledby="xhs-image-dialog-title">
        <div class="xhs-panel-heading"><h2 id="xhs-image-dialog-title"></h2><button class="btn sm" type="button" data-image-close>关闭</button></div>
        <img alt="">
      </dialog>
    </div>`;
    const form = host.querySelector('.xhs-form');
    const fileInput = form.querySelector('[data-material-file]');
    const importButton = form.querySelector('[data-import]');
    const importStatus = form.querySelector('[data-import-status]');
    const importResults = form.querySelector('[data-import-results]');
    const library = form.querySelector('.xhs-library');
    const sourceButtons = form.querySelectorAll('[data-book-source]');
    const bookSearch = form.querySelector('#xhs-book-search');
    const bookList = form.querySelector('[data-library-books]');
    const libraryStatus = form.querySelector('[data-library-status]');
    const libraryRetry = form.querySelector('[data-library-retry]');
    const libraryPreview = form.querySelector('[data-library-preview]');
    const coverFile = form.querySelector('[data-cover-file]');
    const referencesFiles = form.querySelector('[data-reference-files]');
    const coverPick = form.querySelector('[data-cover-pick]');
    const referencesPick = form.querySelector('[data-reference-pick]');
    const imagesGrid = form.querySelector('[data-images]');
    const mediaStatus = form.querySelector('[data-media-status]');
    const imageDialog = host.querySelector('.xhs-image-dialog');
    const results = host.querySelector('.xhs-notes');
    const progress = host.querySelector('.xhs-status');
    const warning = host.querySelector('.xhs-error');
    const nativeButton = host.querySelector('[data-native-open]');
    const nativeStatus = host.querySelector('[data-native-status]');
    const visionStatus = host.querySelector('[data-vision-status]');
    const failuresList = host.querySelector('[data-note-failures]');
    const downloadButton = host.querySelector('[data-download]');
    const generateButton = form.querySelector('button[type="submit"]');
    const count = form.elements.count;
    const decrease = form.querySelector('[data-count-step="-1"]');
    const increase = form.querySelector('[data-count-step="1"]');
    let bookListLoaded = false;
    let bookListLoading = false;
    let books = [];
    let chosenCode = '';
    let bookRequest = 0;
    let importing = false;
    let loadingImages = false;
    for (const [name, value] of Object.entries(brief)) form.elements[name].value = value;
    form.addEventListener('input', (event) => {
      const field = event.target;
      if (Object.hasOwn(brief, field.name)) brief[field.name] = field.name === 'count' ? Number(field.value) : field.value;
      if (field === count) syncCount();
    });

    function syncCount() {
      decrease.disabled = count.valueAsNumber <= Number(count.min);
      increase.disabled = count.valueAsNumber >= Number(count.max);
    }

    for (const button of [decrease, increase]) {
      button.addEventListener('click', () => {
        const current = Number.isFinite(count.valueAsNumber) ? count.valueAsNumber : Number(count.min);
        count.value = Math.min(Number(count.max), Math.max(Number(count.min), Math.round(current) + Number(button.dataset.countStep)));
        count.dispatchEvent(new Event('input', {bubbles: true}));
        if (button.disabled) count.focus();
      });
    }
    syncCount();

    function showMessage(node, message, failed = false) {
      node.textContent = message;
      node.hidden = !message;
      node.classList.toggle('xhs-field-error', failed);
    }

    async function loadNativeStatus() {
      try {
        const result = await readJson(await fetch('/api/xhs-writing/native'), '暂时无法检查桌面版。');
        if (!host.isConnected) return;
        nativeButton.disabled = !result.available;
        showMessage(nativeStatus, result.available ? '' : result.reason || '当前环境无法启动桌面版。');
      } catch (err) {
        if (host.isConnected) showMessage(nativeStatus, err.message, true);
      }
    }

    nativeButton.addEventListener('click', async () => {
      nativeButton.disabled = true;
      showMessage(nativeStatus, '正在打开桌面版…');
      try {
        const result = await post('/api/xhs-writing/native/open', {});
        if (!host.isConnected) return;
        showMessage(nativeStatus, '');
        toast(result.message || '已打开桌面版。');
      } catch (err) {
        if (host.isConnected) showMessage(nativeStatus, err.message, true);
      } finally {
        if (host.isConnected) nativeButton.disabled = false;
      }
    });
    loadNativeStatus();

    function appendMaterials(value) {
      const text = value.replace(/\r\n?/g, '\n').trim();
      const current = form.elements.materials.value;
      const separator = current ? '\n\n' : '';
      const available = Math.max(0, materialLimit - current.length - separator.length);
      const addedText = text.slice(0, available).replace(/[\uD800-\uDBFF]$/, '').trimEnd();
      if (!addedText) return {added: false, truncated: Boolean(text)};
      brief.materials = form.elements.materials.value = current + separator + addedText;
      return {added: true, truncated: available < text.length};
    }

    async function loadLibrary() {
      if (bookListLoaded || bookListLoading) return;
      bookListLoading = true;
      libraryRetry.hidden = true;
      showMessage(libraryStatus, '正在加载书库…');
      try {
        const result = await readJson(await fetch('/api/books'), '无法加载书库，请重试。');
        if (!host.isConnected) return;
        books = (result.books || []).filter(book => book.code && book.book);
        bookListLoaded = true;
        paintBookList();
      } catch (err) {
        if (!host.isConnected) return;
        showMessage(libraryStatus, err.message, true);
        libraryRetry.hidden = false;
      } finally {
        bookListLoading = false;
      }
    }

    function paintBookList() {
      if (!bookListLoaded) return;
      const words = bookSearch.value.normalize('NFKC').toLowerCase().trim().split(/\s+/).filter(Boolean);
      const matching = books.filter(book => {
        const value = [book.book, book.author, book.code].join(' ').normalize('NFKC').toLowerCase();
        return words.every(word => value.includes(word));
      });
      const focusCode = matching.some(book => book.code === chosenCode) ? chosenCode : matching[0]?.code;
      bookList.innerHTML = matching.map(book => `<li><button class="xhs-book-option" type="button" data-book-code="${esc(book.code)}"
        aria-pressed="${book.code === chosenCode}" tabindex="${book.code === focusCode ? '0' : '-1'}">
        <span>${esc(book.book)}</span><small>${[book.author, book.code].filter(Boolean).map(esc).join(' · ')}</small>
      </button></li>`).join('');
      bookList.hidden = !matching.length;
      const message = matching.length ? '' : books.length ? '没有匹配的图书，请换个关键词。' : '书库暂无可选图书，可手动填写。';
      showMessage(libraryStatus, message);
    }

    function paintBookSource() {
      for (const button of sourceButtons) button.setAttribute('aria-pressed', String(button.dataset.bookSource === bookSource));
      library.hidden = bookSource !== 'library';
      if (!library.hidden) loadLibrary();
    }

    function focusBookOption(button) {
      if (!button) return;
      bookList.querySelector('[tabindex="0"]')?.setAttribute('tabindex', '-1');
      button.tabIndex = 0;
      button.focus();
    }

    for (const button of sourceButtons) {
      button.addEventListener('click', () => {
        bookSource = button.dataset.bookSource;
        paintBookSource();
        (bookSource === 'library' ? bookSearch : form.elements.title).focus();
      });
    }
    bookSearch.addEventListener('input', paintBookList);
    bookSearch.addEventListener('keydown', event => {
      if (event.isComposing || !['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return;
      event.preventDefault();
      const options = bookList.querySelectorAll('button');
      if (!options.length) return;
      const option = event.key === 'ArrowUp' ? options[options.length - 1] : options[0];
      focusBookOption(option);
      if (event.key === 'Enter') option.click();
    });
    bookList.addEventListener('keydown', event => {
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      const options = Array.from(bookList.querySelectorAll('button'));
      const current = options.indexOf(event.target);
      const positions = {Home: 0, End: options.length - 1, ArrowDown: current + 1, ArrowUp: current - 1};
      event.preventDefault();
      focusBookOption(options[Math.max(0, Math.min(options.length - 1, positions[event.key]))]);
    });
    bookList.addEventListener('click', event => {
      const button = event.target.closest('[data-book-code]');
      if (button) loadBookPreview(button);
    });
    libraryRetry.addEventListener('click', () => { bookSearch.focus(); loadLibrary(); });

    async function loadBookPreview(button) {
      const token = ++bookRequest;
      chosenCode = button.dataset.bookCode;
      for (const item of bookList.querySelectorAll('[data-book-code]')) item.setAttribute('aria-pressed', String(item === button));
      focusBookOption(button);
      libraryPreview.hidden = true;
      showMessage(libraryStatus, '正在读取图书资料…');
      try {
        const book = await readJson(await fetch('/api/xhs-writing/book?code=' + encodeURIComponent(chosenCode)), '无法读取这本书的资料。');
        if (token !== bookRequest || !host.isConnected) return;
        libraryPreview.innerHTML = `<h4 tabindex="-1">${esc(book.title)}</h4>
          ${book.materials ? `<details><summary>预览可用资料</summary><p class="xhs-library-text">${esc(book.materials)}</p></details>` : '<p class="xhs-field-message">这本书暂无可用资料。</p>'}
          ${book.truncated ? '<p class="xhs-field-message">已截取较长的书库资料。</p>' : ''}
          <div class="xhs-media-actions">
            ${book.materials ? '<button type="button" class="btn primary sm" data-use-materials>使用书名和资料</button>' : ''}
            <button type="button" class="btn sm" data-use-title>只用书名</button>
            ${book.cover_url ? '<button type="button" class="btn sm" data-use-cover>使用书库封面</button>' : ''}
          </div>`;
        libraryPreview.hidden = false;
        showMessage(libraryStatus, '');
        if (document.activeElement === button) libraryPreview.querySelector('h4').focus();
        const useTitle = libraryPreview.querySelector('[data-use-title]');
        function applyTitle() {
          brief.title = form.elements.title.value = book.title.slice(0, 200).replace(/[\uD800-\uDBFF]$/, '');
          useTitle.disabled = true;
        }
        useTitle.addEventListener('click', () => {
          applyTitle();
          showMessage(libraryStatus, '已填入书名，仍可手动编辑。');
          form.elements.title.focus();
        });
        libraryPreview.querySelector('[data-use-materials]')?.addEventListener('click', event => {
          applyTitle();
          const {added, truncated} = appendMaterials(book.materials);
          event.currentTarget.disabled = added;
          const message = added ? '已填入书名并追加资料。' + (truncated ? '超出上限的内容已截取。' : '') : '已填入书名。资料已达上限，调整后可重新追加。';
          showMessage(libraryStatus, message, !added);
          if (added) form.elements.materials.focus();
        });
        const useCover = libraryPreview.querySelector('[data-use-cover]');
        if (useCover) useCover.addEventListener('click', () => adoptBookCover(book, useCover));
      } catch (err) {
        if (token !== bookRequest || !host.isConnected) return;
        showMessage(libraryStatus, err.message + ' 可切换或重新选择图书。', true);
        chosenCode = '';
        button.setAttribute('aria-pressed', 'false');
      }
    }
    paintBookSource();

    function paintImports() {
      importResults.innerHTML = imports.map(item => `<li${item.failed ? ' class="xhs-field-error"' : ''}>
        <strong>${esc(item.name)}</strong><span>${esc(item.message)}</span></li>`).join('');
      importResults.hidden = !imports.length;
    }

    paintImports();
    importButton.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
      const files = Array.from(fileInput.files);
      fileInput.value = '';
      if (!files.length || importing) return;
      importing = importButton.disabled = true;
      paintStatus();
      imports.length = 0;
      paintImports();
      for (const [index, file] of files.entries()) {
        if (!host.isConnected) return;
        showMessage(importStatus, `正在提取文件（${index + 1}/${files.length}）…`);
        try {
          if (!/\.(txt|md|markdown|docx|pdf)$/i.test(file.name)) throw new Error('文件类型不受支持。');
          if (file.size > 40 * 1024 * 1024) throw new Error('文件超过 40 MB。');
          const data = new FormData();
          data.append('file', file);
          const imported = await readJson(await fetch('/api/xhs-writing/materials', {method: 'POST', body: data}), '无法提取文件，请重试。');
          if (!host.isConnected) return;
          if (!imported.text?.trim()) throw new Error('没有可追加的文字。');
          const {added, truncated} = appendMaterials(imported.text);
          if (!added) throw new Error('图书资料已达上限，未追加文字。');
          imports.push({name: imported.filename || file.name, message: imported.truncated || truncated ? '已追加，较长内容已截取' : '已追加到图书资料'});
        } catch (err) {
          if (!host.isConnected) return;
          imports.push({name: file.name, message: err.message, failed: true});
        }
        paintImports();
      }
      showMessage(importStatus, '');
      importing = importButton.disabled = false;
      paintStatus();
    });

    function paintImages() {
      coverPick.textContent = cover ? '更换封面' : '上传封面';
      referencesPick.textContent = `上传参考图（${references.length}/${referenceLimit}）`;
      coverPick.disabled = loadingImages;
      referencesPick.disabled = loadingImages || references.length >= referenceLimit;
      const items = [...(cover ? [{...cover, key: 'cover', label: '封面'}] : []),
        ...references.map((item, index) => ({...item, key: String(index), label: `参考图 ${index + 1}`}))];
      imagesGrid.innerHTML = items.map(item => `<article class="xhs-image-card">
        <button class="xhs-thumbnail" type="button" data-preview-image="${item.key}" aria-label="预览${item.label} ${esc(item.name)}"><img src="${esc(item.data)}" alt=""></button>
        <div><span class="xhs-image-category">${item.label}</span><span class="xhs-image-name">${esc(item.name)}</span>
          <button class="xhs-link" type="button" data-remove-image="${item.key}" aria-label="删除${item.label} ${esc(item.name)}">删除</button></div></article>`).join('');
      imagesGrid.hidden = !items.length;
    }

    function imageBusy(value) {
      loadingImages = value;
      paintImages();
      paintStatus();
    }

    async function adoptBookCover(book, button) {
      if (loadingImages) return;
      button.disabled = true;
      imageBusy(true);
      showMessage(mediaStatus, '正在载入书库封面…');
      try {
        const url = new URL(book.cover_url, location.href);
        if (url.origin !== location.origin) throw new Error('无法读取书库封面。');
        const response = await fetch(url);
        if (!response.ok) throw new Error('无法读取书库封面。');
        const blob = await response.blob();
        const image = await prepareImage(blob, book.title + ' · 书库封面');
        if (!host.isConnected) return;
        cover = image;
        showMessage(mediaStatus, '已使用书库封面。');
      } catch (err) {
        showMessage(mediaStatus, err.message, true);
      } finally {
        button.disabled = false;
        if (host.isConnected) imageBusy(false);
      }
    }

    async function addImages(input, replaceCover) {
      const files = Array.from(input.files);
      input.value = '';
      if (!files.length || loadingImages) return;
      imageBusy(true);
      showMessage(mediaStatus, '正在读取图片…');
      const problems = [];
      for (const file of files) {
        if (!replaceCover && references.length >= referenceLimit) {
          problems.push('已达到 5 张参考图上限。');
          break;
        }
        try {
          const image = await prepareImage(file, file.name);
          if (!host.isConnected) return;
          if (replaceCover) cover = image;
          else references.push(image);
        } catch (err) {
          problems.push(`${file.name}：${err.message}`);
        }
      }
      if (!host.isConnected) return;
      showMessage(mediaStatus, problems.join(' '), Boolean(problems.length));
      imageBusy(false);
    }

    coverPick.addEventListener('click', () => coverFile.click());
    referencesPick.addEventListener('click', () => referencesFiles.click());
    coverFile.addEventListener('change', () => addImages(coverFile, true));
    referencesFiles.addEventListener('change', () => addImages(referencesFiles, false));
    imagesGrid.addEventListener('click', event => {
      const preview = event.target.closest('[data-preview-image]');
      if (preview) {
        const key = preview.dataset.previewImage;
        const image = key === 'cover' ? cover : references[Number(key)];
        if (!image) return;
        imageDialog.querySelector('h2').textContent = image.name;
        imageDialog.querySelector('img').src = image.data;
        imageDialog.showModal();
        return;
      }
      const remove = event.target.closest('[data-remove-image]');
      if (!remove || loadingImages) return;
      if (remove.dataset.removeImage === 'cover') cover = null;
      else references.splice(Number(remove.dataset.removeImage), 1);
      showMessage(mediaStatus, '已移除图片。');
      paintImages();
      (remove.dataset.removeImage === 'cover' ? coverPick : referencesPick).focus();
    });
    imageDialog.querySelector('[data-image-close]').addEventListener('click', () => imageDialog.close());
    paintImages();
    downloadButton.addEventListener('click', download);

    function paintNote() {
      const note = notes[active];
      if (!note) {
        results.innerHTML = `<div class="xhs-empty">
          <svg class="icon" aria-hidden="true"><use href="#i-editor"></use></svg>
          <p>生成后的标题、正文和资料依据会显示在这里。</p></div>`;
        return;
      }
      const label = (item, index) => `第 ${Number.isInteger(item.number) ? item.number : index + 1} 篇`;
      const switcher = notes.length > 1 ? `<div class="xhs-note-switch" role="group" aria-label="切换草稿">${notes.map((item, index) =>
        `<button class="btn sm" type="button" data-note-index="${index}" aria-pressed="${index === active}">${label(item, index)}</button>`).join('')}</div>` : '';
      results.innerHTML = `${switcher}
        <p class="xhs-angle"><span>${esc(generatedFrom.title)}</span> ${esc(note.angle)}</p>
        <label class="xhs-field"><span class="xhs-field-line">标题 <small data-title-length></small></span>
          <input id="xhs-note-title" value="${esc(note.title)}" maxlength="120"></label>
        <label class="xhs-field"><span class="xhs-field-line">正文 <small data-body-length></small></span>
          <textarea id="xhs-note-body" rows="12" maxlength="3000"></textarea></label>
        <label class="xhs-field"><span>标签 <small>用空格分隔</small></span>
          <input id="xhs-note-tags" value="${esc(note.tags.join(' '))}" maxlength="200"></label>
        <div class="xhs-note-actions">
          <button class="btn sm" type="button" data-copy>复制笔记</button>
          <button class="btn sm" type="button" data-revise-open aria-controls="xhs-revise" aria-expanded="false">修改所选文字</button>
        </div>
        <form class="xhs-revise" id="xhs-revise" hidden>
          <p class="xhs-selection" data-selection></p>
          <label class="xhs-field"><span>修改要求</span>
            <textarea name="instructions" required rows="2" maxlength="1500" placeholder="例如语气更轻松，保持原意"></textarea></label>
          <div class="xhs-note-actions"><button class="btn primary sm" type="submit">应用修改</button>
            <button class="btn sm" type="button" data-revise-close>取消</button></div>
        </form>
        ${imagePlanHtml(note.image_plan)}
        <details class="xhs-evidence"><summary>初稿资料依据 (${note.evidence.length})</summary>
          <ul>${note.evidence.map(entry => `<li>${esc(entry)}</li>`).join('')}</ul></details>`;
      const title = results.querySelector('#xhs-note-title');
      const body = results.querySelector('#xhs-note-body');
      const tags = results.querySelector('#xhs-note-tags');
      const editor = results.querySelector('.xhs-revise');
      const reviseButton = results.querySelector('[data-revise-open]');
      body.value = note.body;
      let selection = null;

      function updateCounts() {
        const titleCount = characters(note.title, true);
        const bodyCount = characters(note.body);
        const titleLabel = results.querySelector('[data-title-length]');
        const bodyLabel = results.querySelector('[data-body-length]');
        titleLabel.textContent = `${titleCount} / 20 字`;
        bodyLabel.textContent = `${bodyCount} 字 · 建议 380–600 字`;
        titleLabel.classList.toggle('xhs-count-warning', titleCount > 20);
        bodyLabel.classList.toggle('xhs-count-warning', bodyCount < 380 || bodyCount > 600);
      }

      function closeEditor() {
        editor.hidden = true;
        reviseButton.setAttribute('aria-expanded', 'false');
        selection = null;
        editor.reset();
      }

      updateCounts();
      title.addEventListener('input', () => { note.title = title.value; updateCounts(); });
      body.addEventListener('input', () => { note.body = body.value; updateCounts(); closeEditor(); });
      tags.addEventListener('input', () => {
        note.tags = [...new Set(tags.value.split(/[\s,，、]+/).map(tag => tag.replace(/^#+/, '')).filter(Boolean))];
      });
      results.querySelectorAll('[data-note-index]').forEach(button => {
        button.addEventListener('click', () => {
          active = Number(button.dataset.noteIndex);
          paintNote();
          paintStatus();
          results.querySelector('[aria-pressed="true"]').focus();
        });
      });
      results.querySelector('[data-copy]').addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(noteText(note));
          toast('已复制笔记');
        } catch (_) {
          toast('复制失败，可下载 Markdown 文件。', true);
        }
      });
      reviseButton.addEventListener('click', () => {
        const {selectionStart: start, selectionEnd: end, value} = body;
        const text = value.slice(start, end);
        if (!text.trim()) {
          toast('请先在正文里选中要修改的文字。', true);
          body.focus();
          return;
        }
        selection = {before: value.slice(0, start), text, after: value.slice(end)};
        editor.querySelector('[data-selection]').textContent = text;
        editor.hidden = false;
        reviseButton.setAttribute('aria-expanded', 'true');
        editor.elements.instructions.focus();
      });
      editor.querySelector('[data-revise-close]').addEventListener('click', () => {
        closeEditor();
        reviseButton.focus();
      });
      editor.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!selection || pending) return;
        const target = selection;
        await request('正在修改选中文字…', async () => {
          const response = await post('/api/xhs-writing/revise', {
            title: generatedFrom.title, materials: generatedFrom.materials,
            note: {title: note.title, body: note.body, tags: note.tags},
            selection: target, instructions: editor.elements.instructions.value.trim(),
          });
          note.body = (target.before + response.replacement + target.after).replace(/\r\n?/g, '\n');
          closeEditor();
        });
      });
    }

    function paintStatus() {
      const completed = generation?.notes?.length || 0;
      const failures = generation?.failures || [];
      const resultLine = generation && ['done', 'partial'].includes(generation.status) ? `已生成 ${completed} / ${generation.count} 篇。`
        : generation?.status === 'failed' && !completed && notes.length ? '已保留此前的草稿。' : '';
      showMessage(progress, pending || resultLine);
      showMessage(warning, error || generation?.error || (generation?.status === 'failed' ? '这次未生成可用草稿。' : ''), true);
      showMessage(visionStatus, generation?.vision?.message || '', generation?.vision?.status === 'unavailable');
      failuresList.innerHTML = failures.map(item => `<li class="xhs-field-error"><strong>第 ${Number(item.number)} 篇未生成</strong><span>${esc(item.error)}</span></li>`).join('');
      failuresList.hidden = !failures.length;
      downloadButton.hidden = !notes.length;
      generateButton.disabled = Boolean(pending || importing || loadingImages);
      results.querySelectorAll('input,textarea,button:not([data-note-index])').forEach(control => { control.disabled = Boolean(pending); });
    }

    refresh = (redraw) => {
      if (!host.isConnected) return;
      if (redraw) paintNote();
      paintStatus();
    };
    paintNote();
    paintStatus();

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (pending || importing || loadingImages) return;
      const {title, materials, ...rest} = brief;
      if (!title.trim() || !materials.trim()) {
        toast('请填写书名和图书资料。', true);
        return;
      }
      const snapshot = {...rest, count: count.valueAsNumber, title: title.trim(), materials: materials.trim()};
      await generate(snapshot, {...snapshot, ...(cover ? {cover: cover.data} : {}), references: references.map(item => item.data)});
    });
  }

  async function generate(snapshot, payload) {
    generation = null;
    await request('正在提交写作任务…', async () => {
      let job = await post('/api/xhs-writing/jobs', payload);
      if (!job.id) throw new Error('未收到写作任务编号，请重试。');
      let observedNotes = 0;
      let failuresInARow = 0;
      for (;;) {
        generation = job;
        const newNotes = job.notes || [];
        const changed = newNotes.length > observedNotes;
        if (changed) {
          if (observedNotes === 0) {
            active = 0;
            generatedFrom = snapshot;
            notes = [];
          }
          notes.push(...newNotes.slice(observedNotes).map(note => ({...note, body: note.body.replace(/\r\n?/g, '\n')})));
          observedNotes = newNotes.length;
        }
        if (['done', 'partial', 'failed'].includes(job.status)) break;
        const processed = Number.isInteger(job.completed) ? job.completed : observedNotes;
        const phase = job.status === 'queued' ? '任务等待中' : '正在撰写并核对资料';
        pending = `${phase}，已生成 ${observedNotes} / ${job.count} 篇${processed > observedNotes ? `（已处理 ${processed} 篇）` : ''}。`;
        refresh(changed);
        for (;;) {
          await new Promise(resolve => setTimeout(resolve, 1500));
          try {
            job = await readJson(await fetch('/api/xhs-writing/jobs/' + encodeURIComponent(job.id)), '暂时无法读取写作进度。');
            failuresInARow = 0;
            break;
          } catch (err) {
            failuresInARow += 1;
            if (failuresInARow >= 4) throw new Error(err.message + ' 已获取的草稿仍可查看或导出。');
            pending = '连接暂时中断，正在重试…';
            refresh(false);
          }
        }
      }
      if (job.status === 'failed') throw new Error(job.error || '这次未生成可用草稿。');
    });
  }

  async function request(message, action) {
    error = '';
    pending = message;
    refresh(false);
    let redraw = false;
    try {
      await action();
      redraw = true;
    } catch (err) {
      error = err.message;
    } finally {
      pending = '';
      refresh(redraw);
    }
  }

  return {render};
})();
