import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const workspace=readFileSync(new URL('../static/workspace.js',import.meta.url),'utf8');
const source=workspace.slice(workspace.indexOf('  function sourceQuoteRange('),workspace.indexOf('  async function chooseProject('));

function setup(){
  const calls=[];
  const document={getElementById:()=>panel,activeElement:null};
  const heading={focus(){document.activeElement=this;}};
  const body={innerHTML:'',querySelector:()=>null};
  const panel={hidden:true,isConnected:true,querySelector:selector=>selector==='h3'?heading:body};
  const context={
    document,URLSearchParams,S:{},
    window:{matchMedia:()=>({matches:false})},
    e:text=>String(text).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
    loading:()=>'<loading>',
    btn:(_text,_action,data)=>JSON.stringify(data),
    request:url=>new Promise((resolve,reject)=>calls.push({url,resolve,reject})),
  };
  runInNewContext(source+'\nthis.api={sourcePassage,source,closeReviewSource}',context);
  return {api:context.api,body,panel,calls,document};
}

function evidence(quote){
  return {dataset:{code:'B01',anchor:'B01-01-P01',quote},pressed:'false',
    closest:()=>true,setAttribute(_name,value){this.pressed=value;},focus(){this.focused=true;}};
}

test('the selected quote alone is highlighted within its original paragraph',()=>{
  const {api}=setup();
  const hit={hit:true,文本:'他先找到了样本。随后记录\n石缝中的 <幼苗>。'};
  const first=api.sourcePassage(hit,'他先找到了样本');
  const second=api.sourcePassage(hit,'随后记录石缝中的 <幼苗>');
  assert.match(first,/<mark tabindex="-1">他先找到了样本<\/mark>/);
  assert.match(second,/<mark tabindex="-1">随后记录\n石缝中的 &lt;幼苗&gt;<\/mark>/);
  assert.doesNotMatch(second,/<mark[^>]*>他先|<幼苗>/);
  assert.doesNotMatch(api.sourcePassage({...hit,hit:false},'他先找到了样本'),/<mark/);
  const missing=api.sourcePassage(hit,'随后记录，石缝中的 <幼苗>');
  assert.match(missing,/仅定位到段落，未找到这条引文/);
  assert.doesNotMatch(missing,/<mark/);
});

test('rapidly selecting another quote in the same paragraph cannot render the older response',async()=>{
  const {api,body,calls,panel}=setup();
  const first=evidence('第一个句子'),second=evidence('第二个句子');
  const response={seg_id:'B01-01-P01',items:[{hit:true,文本:'第一个句子。第二个句子。'}]};
  const readFirst=api.source(first);
  const readSecond=api.source(second);
  assert.equal(calls[0].url,calls[1].url);
  calls[1].resolve(response);
  await readSecond;
  calls[0].resolve(response);
  await readFirst;
  assert.match(body.innerHTML,/<mark tabindex="-1">第二个句子<\/mark>/);
  assert.equal(first.pressed,'false');
  assert.equal(second.pressed,'true');

  const closedWhileLoading=api.source(second);
  api.closeReviewSource();
  calls[2].resolve(response);
  await closedWhileLoading;
  assert.equal(body.innerHTML,'<loading>');
  assert.equal(panel.hidden,true);
  assert.equal(second.pressed,'false');
  assert.equal(second.focused,true);
});

test('retry carries the selected quote through an unavailable source response',async()=>{
  const {api,body,calls}=setup();
  const result=api.source(evidence('引文内容'));
  calls[0].reject(Error('暂时不可用'));
  await result;
  assert.match(body.innerHTML,/"quote":"引文内容"/);
});
