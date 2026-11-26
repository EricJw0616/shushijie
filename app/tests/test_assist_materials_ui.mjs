import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const source=readFileSync(new URL('../static/assist.js',import.meta.url),'utf8');
const reader=readFileSync(new URL('../static/manuscript-reader.js',import.meta.url),'utf8');
const workspace=readFileSync(new URL('../static/workspace.js',import.meta.url),'utf8');
const app=readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function setup(asset){
  const context={esc:escape,document:{
    addEventListener(){},
    createElement(){
      const template={innerHTML:''};
      template.content={querySelectorAll:()=>[],get textContent(){return template.innerHTML.replace(/<[^>]+>/g,'').replace(/&(?:amp|lt|gt|quot|#39);/g,c=>({'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'"}[c]));}};
      return template;
    },
  },addEventListener(){}};
  context.window=context;
  runInNewContext(app.match(/^function clip\(.*$/m)[0]+'\n'+reader+'\n'+source.replace('return {editWritingNotes,','return {A,materialTitle,marketingMaterialRow,recommendationHtml,marketingGeneration,draftResult,editWritingNotes,'),context);
  const api=context.ProjectAssist;
  api.A.project={id:'test-project',kind:'marketing',items:[],brief:{marketing_task:'channel',channel:'公众号'}};
  const run={id:'existing-run',capability:'recommend',status:'done',snapshot:{materials:[asset]},result:{suggestions:[{asset_id:asset.id,proposed_use:'用于结尾的图书介绍。'}]}};
  const row={id:asset.id,asset,run:run.id,suggestion:run.result.suggestions[0]};
  return {api,context,card:()=>api.marketingMaterialRow(row,0,run),detail:()=>api.recommendationHtml(run,asset.id)};
}

test('book introduction has a compact type heading while detail preserves the complete content',()=>{
  const content='这本科学人物读物通过观察、提问和查找证据讲述研究过程。'.repeat(12)+'这是简介的最后一句。';
  const asset={id:'another-book:marketing:intro',kind:'marketing',marketing_key:'summary',book:'另一本图书',title:content.slice(0,240),text:content};
  const before=JSON.stringify(asset),ui=setup(asset),card=ui.card();
  assert.match(card,/<h3>内容简介<\/h3>/);
  assert.ok(!card.includes(content));
  assert.ok(ui.detail().includes(content),'opening the detail still exposes the full saved introduction');
  assert.equal(JSON.stringify(asset),before,'displaying a shorter heading does not rewrite the source');
});

test('editor can recheck an eligible failed copy and sees factual errors without an edit action',()=>{
  const {api}=setup({id:'source',kind:'quote',title:'原文'});
  const failed={id:'draft-a',project_id:'test-project',capability:'draft',status:'failed',error:'正文超出上限',
    review_issues:[{severity:'blocker',message:'实际325字，超过300字'}],
    recovery_draft:[{channel:'小红书',title:'候选标题',body:'<未检查正文>',ending:''}]};
  api.A.runs=[failed];
  assert.match(api.marketingGeneration(),/实际325字，超过300字/);
  assert.match(api.marketingGeneration(),/修改这份初稿/);
  assert.match(api.draftResult(failed),/&lt;未检查正文&gt;/);
  assert.match(api.draftResult(failed),/重新检查修改稿/);
  assert.doesNotMatch(api.draftResult(failed),/ProjectAssist\.apply\(/);
  const invalid={...failed,source_stale:true,recovery_draft:undefined,error:'原文依据无效',review_issues:undefined};
  api.A.runs=[invalid];
  assert.match(api.marketingGeneration(),/原文依据无效/);
  assert.doesNotMatch(api.marketingGeneration(),/修改这份初稿/);
  assert.doesNotMatch(api.draftResult(invalid),/重新检查修改稿/);
});

test('older recommendation snapshots without type metadata remain readable without regeneration',()=>{
  const content='没有类型字段的历史素材也应当保持正文。'.repeat(20)+'完整原文结束。';
  const ui=setup({id:'legacy:marketing:intro',kind:'marketing',book:'历史图书',title:content.slice(0,240),text:content});
  const heading=ui.card().match(/<h3>(.*?)<\/h3>/s)[1];
  assert.ok(heading.length<=49);
  assert.ok(heading.endsWith('…'));
  assert.ok(content.startsWith(heading.slice(0,-1)),'unknown material is shortened, not mislabeled as a book introduction');
  assert.ok(ui.detail().includes(content));
});

test('short meaningful titles stay intact and long excerpts are bounded and escaped',()=>{
  const short=setup({id:'other:marketing:gain',kind:'marketing',marketing_key:'gains',title:'认识作者的观察方法',text:'保留具体的观察方法。'});
  assert.match(short.card(),/<h3>认识作者的观察方法<\/h3>/);
  const quote='<script>不是网页标签</script>'+'这段原文用于展示。'.repeat(20);
  const ui=setup({id:'other:quote:long',kind:'quote',title:quote,text:quote});
  assert.equal(ui.api.materialTitle({kind:'quote',title:quote},'素材'),escape(quote.slice(0,48)+'…'));
  assert.ok(ui.detail().includes(escape(quote)));
  assert.ok(!ui.card().includes('<script>'));
});

test('marketing cards omit only an excerpt identical to the visible plain text heading',()=>{
  const quote='观察 < 比较 & 验证';
  const same=setup({id:'other:quote:same',kind:'quote',title:quote,text:quote});
  assert.match(same.card(),/<h3>观察 &lt; 比较 &amp; 验证<\/h3>/);
  assert.ok(!same.card().includes('<p>'),'the same text is shown once, even when it needs HTML escaping');
  const different=setup({id:'other:summary:detail',kind:'summary',title:'观察方法',text:'观察之后还需要比较证据。'});
  assert.match(different.card(),/<p>观察之后还需要比较证据。<\/p>/);
  const long='观察记录需要联系前后文，并与其他材料一起比较。'.repeat(5);
  const clipped=setup({id:'other:quote:clipped',kind:'quote',title:long,text:long});
  assert.ok(clipped.card().includes('<p>'+escape(long)+'</p>'),'a shortened heading must keep the longer excerpt');
});

test('marketing selection, source lists, review and reference choices reuse the same title without changing editorial lists',()=>{
  const content='这段图书简介应在详情完整展示，列表只保留清楚的名称。'.repeat(12);
  const asset={id:'new:marketing:intro',kind:'marketing',marketing_key:'summary',title:content,text:content,book:'不同图书'};
  const {context,card}=setup(asset),nodes={};
  for(const id of ['marketingPageTitle','marketingPageHint','marketingStepCount','projectDraft','marketingNext','marketingStepState','marketingReview','projectMaterialRows'])nodes[id]={innerHTML:'',textContent:'',dataset:{},toggleAttribute(){},value:'已生成稿件'};
  nodes.marketingReview.querySelector=()=>null;
  context.document.getElementById=id=>nodes[id]||null;
  context.document.querySelectorAll=()=>[];
  context.document.querySelector=()=>({textContent:''});
  context.MarketingScenes={workflow:()=>({scoped:true,title:'公众号文章'})};
  context.crumb=()=>{};context.modalX=()=>'';
  let modal='';context.openModal=html=>{modal=html;};
  runInNewContext(workspace.replace('return {syncNavigation:','return {S,renderMaterialRows,projectMaterialTitle,syncNavigation:'),context);
  const studio=context.Studio;
  studio.S.project={id:'test-project',kind:'marketing',brief:{marketing_task:'channel',channels:['公众号']},draft:'已生成稿件',draft_asset_ids:[asset.id],items:[{asset_id:asset.id,snapshot:asset,status:'adopted',current_status:'approved',evidence_valid:true}]};
  studio.S.section='review';
  assert.match(card(),/<h3>内容简介<\/h3>/);
  studio.renderMaterialRows();assert.match(nodes.projectMaterialRows.innerHTML,/<b>内容简介<\/b>/);
  studio.syncNavigation();assert.match(nodes.marketingReview.innerHTML,/<span>内容简介<\/span>/);
  assert.match(nodes.marketingReview.innerHTML,/<details class="marketing-confirmed-sources" data-confirmed-sources>/);
  studio.S.project.items[0].current_status='review';studio.syncNavigation();
  assert.match(nodes.marketingReview.innerHTML,/待核对素材 · 1 条/);
  assert.doesNotMatch(nodes.marketingReview.innerHTML,/data-confirmed-sources/);
  assert.equal(nodes.marketingNext.disabled,true);
  studio.S.project.items[0].current_status='approved';
  studio.openDraftReferenceReview();assert.match(modal,/<strong>内容简介<\/strong>/);
  for(const html of [nodes.projectMaterialRows.innerHTML,nodes.marketingReview.innerHTML,modal])assert.ok(!html.includes(content));
  studio.S.project.kind='editorial';studio.renderMaterialRows();assert.ok(nodes.projectMaterialRows.innerHTML.includes('<b>'+content+'</b>'));
  assert.equal(studio.S.project.items[0].snapshot.text,content);
});
