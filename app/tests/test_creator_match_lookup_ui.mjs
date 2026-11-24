// Run with node --test. Set PLAYWRIGHT_CHANNEL=chrome to use an installed Chrome.
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

const localPath = '/api/creator-match';
const searchPath = localPath + '/works/search';
const book = {code: 'test-hebei', book: '河北廉洁故事', author: '测试作者'};
const synopsis = '通过河北历史人物的故事讲述清廉与吏治。';
const audiences = ['喜欢读古代清官廉吏故事的历史爱好者', '关注廉洁文化与传统美德内容的短视频用户'];
const candidate = {
  handle: 'fixture-account', name: '作品证据测试账号',
  content_match: {book_point: '河北历史人物', connection: '这条作品讲述书中提及的人物。',
    works: [{title: '测试作品：地方志中的清官'}]},
};
const noLocalMatch = {content_status: 'no_match', matches: []};
const localHit = {content_status: 'matched', matches: [candidate]};

describe('one-click book and creator matching', {skip: !chromium && 'Playwright is required for browser tests'}, () => {
  let browser;
  before(async () => { browser = await chromium.launch({channel: process.env.PLAYWRIGHT_CHANNEL}); });
  after(async () => { await browser?.close(); });

  async function open(t, localMatch, publicSearch) {
    const page = await browser.newPage();
    page.setDefaultTimeout(4000);
    t.after(() => page.close());
    const requests = {local: [], public: []};
    await page.route('**/*', async route => {
      const {hostname, pathname} = new URL(route.request().url());
      if (hostname !== 'bookworld.test') return route.abort();
      if (pathname === '/' || pathname.startsWith('/static/')) {
        const asset = pathname === '/' ? 'index.html' : pathname.slice('/static/'.length);
        return route.fulfill({path: fileURLToPath(new URL('../static/' + asset, import.meta.url))});
      }
      if (pathname === localPath || pathname === searchPath) {
        const body = route.request().postDataJSON();
        if (pathname === localPath) {
          requests.local.push(body);
          return route.fulfill({json: localMatch(body)});
        }
        requests.public.push(body);
        return publicSearch(route, body);
      }
      const fixtures = {
        '/api/books': {books: [book]}, '/api/book': {row: book, book: {内容简介: synopsis}},
        '/api/creator-match/audiences': {audiences: audiences.map(text => ({text, label: '图书读者'}))},
      };
      return route.fulfill({json: fixtures[pathname] || {}});
    });
    await page.goto('http://bookworld.test/#/creator-match');
    const submit = page.locator('.cm-form button[type="submit"]');
    await submit.waitFor();
    return {page, requests, submit, body: page.locator('.cm-results-body')};
  }

  async function fill(page, title = book.book, summary = synopsis) {
    await page.locator('#cm-book-title').fill(title);
    await page.locator('#cm-synopsis').fill(summary);
  }

  it('uses the selected library book and both selected audiences for one public lookup', async t => {
    const {page, requests, submit, body} = await open(t, () => noLocalMatch, route =>
      route.fulfill({json: {...localHit, search_state: 'found', search_reason: 'found'}}));
    await page.getByRole('button', {name: '从书库选书'}).click();
    await page.getByRole('button', {name: '查找图书', exact: true}).click();
    await page.getByRole('button', {name: new RegExp(book.book)}).click();
    await page.getByRole('button', {name: 'AI 分析', exact: true}).click();
    await page.getByRole('button', {name: '分析受众', exact: true}).click();
    for (const text of audiences) await page.getByRole('checkbox', {name: new RegExp(text)}).check();
    await submit.click();
    await body.getByText(candidate.name, {exact: true}).waitFor();
    assert.equal(requests.local.length, 1);
    assert.deepEqual(requests.public, requests.local);
    assert.deepEqual(requests.public[0], {
      title: book.book, synopsis, audience: audiences.join('；'), goal: 'content', book_code: book.code,
    });
  });

  for (const scenario of [
    {name: 'work found without a verified author', outcome: {
      search_state: 'empty', search_reason: 'unverified_owner', search_notice: '查到了作品链接，暂时无法核对发布账号。',
      search_terms: ['地方志', '清廉'], public_work_count: 3, verified_work_count: 0,
    }, message: /账号/},
    {name: 'lookup failed', failure: true, message: /稍后|重试|失败|连接|查询暂不/},
  ]) {
    it('shows the outcome when the local library is empty: ' + scenario.name, async t => {
      const {page, requests, submit, body} = await open(t, () => ({matches: [], content_status: 'no_works'}),
        route => scenario.failure ? route.abort('failed') :
          route.fulfill({json: {...noLocalMatch, ...scenario.outcome}}));
      await fill(page);
      await submit.click();
      await body.getByText(scenario.message).first().waitFor();
      assert.equal(await body.locator('.cm-card').count(), 0);
      assert.equal(requests.public.length, 1);
      if (scenario.outcome?.search_terms) {
        assert.match(await body.innerText(), /地方志.*清廉/);
        assert.match(await body.innerText(), /3 条作品链接.*0 条/);
      }
    });
  }

  for (const [status, notice] of [
    ['missing_synopsis', '请补充图书简介。'], ['analysis_unavailable', '作品分析暂时不可用。'],
    ['works_unavailable', '作品资料暂时无法读取。'], ['matched', candidate.name],
  ]) {
    it('finishes locally for ' + status, async t => {
      const {page, requests, submit, body} = await open(t,
        () => status === 'matched' ? localHit : {matches: [], content_notice: notice, content_status: status},
        route => route.abort());
      await fill(page, book.book, status === 'missing_synopsis' ? '' : synopsis);
      await submit.click();
      await body.getByText(notice, {exact: true}).first().waitFor();
      assert.equal(requests.public.length, 0);
    });
  }

  it('retries the displayed book after the unsubmitted draft has changed', async t => {
    const empty = {...noLocalMatch, search_state: 'empty', search_reason: 'no_public_works',
      search_notice: '查询结束，未发现相关作品。'};
    const {page, requests, submit, body} = await open(t, () => noLocalMatch,
      route => route.fulfill({json: empty}));
    await fill(page);
    await submit.click();
    await body.getByText(empty.search_notice, {exact: true}).waitFor();
    await fill(page, '不同的新书', '新书的内容简介。');
    const again = page.waitForResponse(response => new URL(response.url()).pathname === searchPath);
    await body.getByRole('button', {name: '重新查找作品'}).click();
    await again;
    await body.getByText(empty.search_notice, {exact: true}).waitFor();
    assert.deepEqual(requests.public, [requests.local[0], requests.local[0]]);
    assert.match(await page.locator('[data-cm-results-context]').innerText(), new RegExp(book.book));
    assert.equal(await page.locator('#cm-book-title').inputValue(), '不同的新书');
  });

  it('keeps a pending lookup on the submitted book, and supersedes it on a new submission', async t => {
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    const {page, requests, submit, body} = await open(t,
      values => values.title === book.book ? noLocalMatch : localHit, async route => {
        await pending;
        await route.fulfill({json: {...noLocalMatch, search_state: 'empty', search_reason: 'no_public_works',
          search_notice: '旧书搜索完毕。'}});
      });
    try {
      await fill(page);
      const called = page.waitForRequest(req => new URL(req.url()).pathname === searchPath);
      await submit.click();
      await called;
      await submit.click();
      assert.equal(requests.local.length, 1);
      assert.equal(requests.public.length, 1);
      await fill(page, '下一本书', '讲述另一种主题。');
      const context = page.locator('[data-cm-results-context]');
      assert.match(await context.innerText(), new RegExp(book.book));
      await submit.click();
      await body.getByText(candidate.name, {exact: true}).waitFor();
      assert.match(await context.innerText(), /下一本书/);
      release();
      await page.waitForLoadState('networkidle');
      assert.match(await body.innerText(), new RegExp(candidate.name));
      assert.doesNotMatch(await page.locator('.cm-results').innerText(), /旧书搜索完毕/);
      assert.deepEqual(requests.local.map(entry => entry.title), [book.book, '下一本书']);
      assert.deepEqual(requests.public.map(entry => entry.title), [book.book]);
    } finally { release(); }
  });
});
