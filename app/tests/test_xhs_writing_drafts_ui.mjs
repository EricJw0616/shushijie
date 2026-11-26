import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {after, before, describe, it} from 'node:test';

const require = createRequire(import.meta.url);
let chromium;
try {
  ({chromium} = require('playwright'));
} catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND') throw error;
}

const books = [
  {code: 'fixture-wood', book: '悬铃木长街', materials: '木叶和凉棚。'},
  {code: 'fixture-sea', book: '早潮手记', materials: '海岸和灯标。'},
];
const firstNote = {number: 1, title: '第一篇草稿', body: '今日散步看书。', tags: ['读书'], angle: '随笔', evidence: ['今日散步']};
const secondNote = {...firstNote, number: 2, title: '第二篇草稿'};
const jobsPath = '/api/xhs-writing/jobs';
const url = 'http://bookworld.test/#/xhs-writing';

describe('quick Xiaohongshu drafts', {skip: !chromium && 'Playwright is required for browser tests'}, () => {
  let browser;
  before(async () => { browser = await chromium.launch({channel: process.env.PLAYWRIGHT_CHANNEL}); });
  after(async () => { await browser?.close(); });

  async function open(t, running = false) {
    const context = await browser.newContext();
    t.after(() => context.close());
    const requests = {submitted: [], polls: 0, done: false};
    await context.route('**/*', async route => {
      const {hostname, pathname, searchParams} = new URL(route.request().url());
      if (hostname !== 'bookworld.test') return route.abort();
      if (pathname === '/' || pathname.startsWith('/static/')) {
        const asset = pathname === '/' ? 'index.html' : pathname.slice('/static/'.length);
        return route.fulfill({path: fileURLToPath(new URL('../static/' + asset, import.meta.url))});
      }
      if (pathname === jobsPath) {
        const body = route.request().postDataJSON();
        requests.submitted.push(body);
        const id = String(requests.submitted.length).padStart(32, '0');
        return route.fulfill({json: {id, status: running ? 'running' : 'done', count: body.count, notes: [firstNote]}});
      }
      if (pathname.startsWith(jobsPath + '/')) {
        requests.polls++;
        const notes = requests.done ? [firstNote, secondNote] : [firstNote];
        return route.fulfill({json: {id: pathname.split('/').at(-1), status: requests.done ? 'done' : 'running', count: 2, notes}});
      }
      const book = books.find(item => item.code === searchParams.get('code'));
      const fixtures = {
        '/api/books': {books}, '/api/xhs-writing/book': {title: book?.book, materials: book?.materials},
        '/api/xhs-writing/materials': {text: '来自 Word 的手写札记。', filename: '外部札记.docx'},
      };
      return route.fulfill({json: fixtures[pathname] || {}});
    });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    await page.goto(url);
    return {page, context, requests};
  }

  async function choose(page, book) {
    const option = page.locator('[data-book-code="' + book.code + '"]');
    if (!await option.isVisible()) await page.getByRole('button', {name: '从书库选书'}).click();
    await option.click();
    await page.getByRole('button', {name: '使用书名和资料'}).click();
  }

  async function generate(page) {
    await page.getByRole('button', {name: '生成笔记'}).click();
    await page.locator('#xhs-note-title').waitFor();
  }

  async function refresh(page) {
    page.once('dialog', dialog => dialog.accept());
    await page.reload();
  }

  it('keeps two book drafts and a Word-based manual draft independent across switching and refresh', async t => {
    const {page, context, requests} = await open(t);
    const [a, b] = books;
    const materials = page.locator('#xhs-materials');
    const noteTitle = page.locator('#xhs-note-title');
    const noteBody = page.locator('#xhs-note-body');
    await choose(page, a);
    await generate(page);
    await noteTitle.fill('已改长街标题');
    await noteBody.fill('长街人工整理正文。');
    await choose(page, b);
    assert.equal(await materials.inputValue(), b.materials);
    assert.equal(await noteTitle.count(), 0);
    await generate(page);
    assert.deepEqual(requests.submitted.map(item => [item.title, item.materials]), books.map(item => [item.book, item.materials]));
    await noteTitle.fill('已改早潮标题');
    await refresh(page);
    assert.equal(await noteTitle.inputValue(), '已改早潮标题');
    assert.equal(await materials.inputValue(), b.materials);
    await choose(page, a);
    assert.equal(await noteTitle.inputValue(), '已改长街标题');
    assert.equal(await noteBody.inputValue(), '长街人工整理正文。');

    await page.getByRole('button', {name: '手动填写'}).click();
    const bookTitle = page.locator('#xhs-book-title');
    await bookTitle.fill('外部札记');
    await page.locator('[data-material-file]').setInputFiles({
      name: '外部札记.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      buffer: Buffer.from('fixture'),
    });
    await page.getByText('已追加到图书资料').waitFor();
    await generate(page);
    await noteTitle.fill('Word 笔记已编辑');
    await refresh(page);
    assert.equal(await bookTitle.inputValue(), '外部札记');
    assert.equal(await materials.inputValue(), '来自 Word 的手写札记。');
    assert.equal(await noteTitle.inputValue(), 'Word 笔记已编辑');
    assert.match(await page.locator('[data-save-status]').innerText(), /恢复/);

    const freshTab = await context.newPage();
    await freshTab.goto(url);
    assert.equal(await freshTab.locator('#xhs-book-title').inputValue(), '');
    assert.equal(await freshTab.locator('#xhs-note-title').count(), 0);
  });

  it('keeps the draft during same-tab navigation and warns before closing the tab', async t => {
    const {page} = await open(t);
    await choose(page, books[0]);
    await generate(page);
    const note = page.locator('#xhs-note-title');
    await note.fill('留在标签页的修改');
    await page.evaluate(() => { location.hash = '#/dashboard'; });
    await note.waitFor({state: 'hidden'});
    await page.goBack();
    assert.equal(await note.inputValue(), '留在标签页的修改');
    await page.locator('[data-save-status]').getByText(/关闭前/).waitFor();

    const closeWarning = page.waitForEvent('dialog');
    await page.close({runBeforeUnload: true});
    const dialog = await closeWarning;
    assert.equal(dialog.type(), 'beforeunload');
    await dialog.dismiss();
    assert.equal(await note.inputValue(), '留在标签页的修改');
  });

  it('resumes the existing job after a refresh and appends new results only once', async t => {
    const {page, requests} = await open(t, true);
    await choose(page, books[0]);
    await page.locator('#xhs-count').fill('2');
    await generate(page);
    requests.done = true;
    await refresh(page);
    await page.getByRole('button', {name: '第 2 篇'}).waitFor();
    assert.equal(await page.locator('[data-note-index]').count(), 2);
    assert.equal(requests.submitted.length, 1);
    assert.ok(requests.polls >= 1);
    await page.getByRole('button', {name: '第 2 篇'}).click();
    assert.equal(await page.locator('#xhs-note-title').inputValue(), secondNote.title);
  });
});
