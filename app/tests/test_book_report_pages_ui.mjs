import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const source=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const reportSource=source.slice(source.indexOf('const ENT_CN='),source.indexOf('async function renderReport('));
const context={
  URLSearchParams,PROTO:{},num:n=>String(n),
  esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
};
runInNewContext(reportSource+'\nthis.api={reportPageIssues,reportHtml}',context);
const {reportPageIssues,reportHtml}=context.api;

test('legacy coverage stays unknown while an empty new record is reported explicitly',()=>{
  for(const value of [undefined,null,[],false]){
    const view=reportPageIssues({source_page_issues:value,source_pages:200});
    assert.equal(view.summary,'尚无逐页记录');
    assert.match(view.html,/暂不能列出/);
    assert.doesNotMatch(view.html,/0 页|没有记录待处理/);
  }
  const current=reportPageIssues({source_page_issues:{},source_pages:200});
  assert.equal(current.summary,'共 200 页 · 未记录待处理页');
  assert.match(current.html,/本次解析没有记录待处理的页面/);
  assert.doesNotMatch(current.html,/<a|<details/);
});

test('problem pages link to physical PDF pages and count shared reasons once',()=>{
  const view=reportPageIssues({code:'T01',has_original_pdf:true,source_pages:40,source_page_issues:{
    failed:[17],unavailable:[18],review:[9,8,8],layout_review:[8],no_text:[20],blank:[1,40],non_body:[39],
  }});
  assert.equal(view.summary,'共 40 页 · 5 页需查看');
  assert.match(view.html,/PDF 阅读器中的页序/);
  assert.match(view.html,/可能与书上印刷页码不同/);
  for(const page of [1,8,9,17,18,20,39,40]){
    assert.ok(view.html.includes(`href="/api/book/source?code=T01#page=${page}"`));
    assert.ok(view.html.includes(`aria-label="打开 PDF 第 ${page} 页"`));
  }
  for(const key of ['failed','unavailable','review','layout_review','no_text']){
    assert.ok(view.html.includes(`data-page-issue="${key}" open`));
  }
  for(const key of ['blank','non_body']){
    assert.ok(view.html.includes(`data-page-issue="${key}"><summary>`));
    assert.ok(!view.html.includes(`data-page-issue="${key}" open`));
  }
});

test('confirmed blank and isolated promotion pages do not inflate actionable counts',()=>{
  const view=reportPageIssues({code:'T01',has_original_pdf:true,source_page_issues:{blank:[1,2],non_body:[30]}});
  assert.equal(view.summary,'未记录待处理页');
  assert.match(view.html,/已确认空白页/);
  assert.match(view.html,/已分开的非正文页/);
  assert.doesNotMatch(view.summary,/需查看/);
});

test('missing original PDF leaves usable page numbers without broken source links',()=>{
  const view=reportPageIssues({code:'T01',has_original_pdf:false,source_page_issues:{review:[4]}});
  assert.match(view.html,/第 4 页/);
  assert.match(view.html,/原始 PDF 暂不可用/);
  assert.doesNotMatch(view.html,/<a |href=/);
});

test('invalid page entries cannot become links or misleading counts',()=>{
  const view=reportPageIssues({code:'T01"&',has_original_pdf:true,source_page_issues:{
    review:[2,2,0,-1,2.5,true,'3','<script>'],failed:'4',unsupported:[5],
  }});
  assert.equal(view.summary,'1 页需查看');
  assert.equal((view.html.match(/href=/g)||[]).length,1);
  assert.match(view.html,/code=T01%22%26#page=2/);
  assert.doesNotMatch(view.html,/<script>/);
});

test('shared modal and full-page report render the actionable section',()=>{
  const html=reportHtml({code:'T01',book:'页面测试',source_page_issues:{failed:[6]},has_original_pdf:true,
    identity:{found:[],missing:[],total:0},structure:{found:[],missing:[],total:0},
    content:{total:0,entity_counts:{},entity_total:0},usage:{},trust:{}});
  assert.match(html,/>1 页面检查</);
  assert.match(html,/文字识别失败/);
  assert.match(html,/#page=6/);
  assert.match(html,/>6 出处检查</);
});
