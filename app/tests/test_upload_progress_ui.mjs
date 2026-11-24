import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../static/app.js', import.meta.url), 'utf8');
const context = {arr: value => Array.isArray(value) ? value : [], esc: String, num: String};
for (const name of ['probeLine', 'stepIcon', 'renderJob']) {
  const start = source.indexOf(`function ${name}(`);
  runInNewContext(source.slice(start, source.indexOf('\n}\n', start) + 2), context);
}

test('preflight reports page count and when scanning starts without showing sampled characters', () => {
  const message = context.probeLine({format: 'pdf', pages: 244, text: {han: 941},
    title: '我情愿做老儿童', title_source: '封面页'});
  assert.match(message, /文件共 244 页/);
  assert.match(message, /开始入库.*读取全文.*扫描页/);
  assert.match(message, /书名取自封面页/);
  assert.doesNotMatch(message, /941|汉字/);
});

test('OCR page progress is visible separately from overall import progress', () => {
  const view = {};
  const detail = '正在识别扫描页（OCR），已处理 5/13 页。';
  context.renderJob(view, {kind: 'upload', status: 'running', progress: 8,
    steps: [{key: 'parse', status: 'running', detail}]});
  assert.ok(view.innerHTML.includes(`<b>${detail}</b>`));
  assert.equal(view.innerHTML.split(detail).length, 2);
  assert.match(view.innerHTML, /总进度 8%/);
});
