import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const read=name=>readFileSync(new URL('../static/'+name,import.meta.url),'utf8');
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const source={id:'B01:marketing:summary:abc',kind:'marketing',code:'B01',book:'植物观察',title:'内容简介',text:'从日常植物学习观察方法。',status:'review',evidence:[{anchor:'B01-P01',quote:'观察身边的植物。'}]};

function setup(){
  const storage=new Map(),routes=[],writes=[],toasts=[];
  const host={innerHTML:'',classList:{add(){}}};
  let form=null,uuid=0;
  const context={esc:escape,state:{books:[{code:'B01',book:'植物观察'},{code:'B02',book:'城市故事'}]},
    location:{hash:'#/campaigns?material='+encodeURIComponent(source.id)},URLSearchParams,
    document:{getElementById:id=>id==='marketingEntry'?host:id==='marketingNewForm'?form:null},
    sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    crypto:{randomUUID:()=>`test-request-${String(++uuid).padStart(16,'0')}`},
    crumb(){},loading:()=>'<p>加载中</p>',addEventListener(){},closeModal(){},
    toast:(...args)=>toasts.push(args),go:(...args)=>routes.push(args),
    jget:async()=>({asset:structuredClone(source)}),
    post:async(url,body)=>{writes.push({url,body:structuredClone(body)});return {project:{id:'prj-0000000000000001'}};}
  };
  context.window=context;
  runInNewContext(['marketing-scenes.js','marketing-purpose.js','marketing-materials.js','marketing-entry.js'].map(read).join('\n'),context);
  function makeForm(data={}){
    const fields={primary_code:'B01',marketing_task:'general',topic:'身边的植物',audience:'城市青年',goal:'引导开始自然观察',title:'',writing_notes:'',purpose:'reading',book_readers:'',decision_maker:'',channel:'',new_book_brief:'',...data};
    const elements=[];
    for(const [name,value] of Object.entries(fields)){
      if(Array.isArray(value)){for(const item of value)elements.push({name,value:item,type:'checkbox',checked:true,disabled:false});continue;}
      const input={name,value,type:'text',disabled:false,options:[{textContent:''}]};elements.push(input);elements[name]=input;
    }
    const submit={textContent:'',disabled:false},alert={hidden:true,textContent:'',scrollIntoView(){}},note={textContent:''};
    const node={elements,dataset:{},isConnected:true,closest:()=>host,setAttribute(){},querySelectorAll:selector=>selector==='[data-entry-group]'?[]:elements.concat(submit),
      querySelector:selector=>selector==='[type=submit]'?submit:selector==='[role=alert]'?alert:selector==='[data-draft-note]'?note:null,alert};
    form=node;return node;
  }
  return {context,storage,routes,writes,toasts,host,makeForm,entry:context.MarketingEntry,materials:context.MarketingMaterials};
}

test('opening a seeded entry only reads material and keeps every scene link scoped to it',async()=>{
  const ui=setup();await ui.entry.render(ui.host);
  assert.equal(ui.writes.length,0);
  assert.match(ui.host.innerHTML,/尚未创建项目/);
  const links=Array.from(ui.host.innerHTML.matchAll(/href="(#\/campaigns\/new\/[^\"]+)"/g),m=>m[1]);
  assert.equal(links.length,6);
  assert.ok(links.every(link=>new URLSearchParams(link.split('?')[1]).get('material')===source.id));
  assert.match(ui.host.innerHTML,/href="#\/marketing\/B01"/);
});

test('a seed preselects its book without inventing audience, theme, or objective',async()=>{
  const ui=setup();await ui.entry.render(ui.host,'new','planning');
  assert.match(ui.host.innerHTML,/<option value="B01" selected>/);
  assert.match(ui.host.innerHTML,/name="topic"[^>]*value=""/);
  assert.match(ui.host.innerHTML,/name="audience"[^>]*value=""/);
  assert.match(ui.host.innerHTML,/<textarea[^>]*name="goal"[^>]*><\/textarea>/);
  assert.equal(ui.writes.length,0);
});

test('rejected or nonmarketing material cannot enter the creator',async()=>{
  for(const patch of [{status:'rejected'},{kind:'quote'}]){
    const ui=setup();ui.context.jget=async()=>({asset:{...source,...patch}});
    await ui.entry.render(ui.host,'new','planning');
    assert.match(ui.host.innerHTML,/暂时无法带入/);
    assert.doesNotMatch(ui.host.innerHTML,/id="marketingNewForm"/);
    assert.equal(ui.writes.length,0);
  }
});

test('scope checks distinguish deliberate reference collection from book-specific tasks',()=>{
  const ui=setup(),reason=ui.materials.scopeReason;
  assert.equal(reason({kind:'marketing',brief:{marketing_task:'general',source_code:'B02'}},source),'');
  assert.match(reason({kind:'marketing',brief:{marketing_task:'reposition',source_code:'B02'}},source),/推广图书/);
  assert.equal(reason({kind:'marketing',brief:{marketing_task:'theme',target_codes:['B02','B01']}},source),'');
  assert.match(reason({kind:'marketing',status:'paused'},source),/暂缓/);
  assert.match(reason({kind:'editorial'},source),/不属于/);
});

test('failed creation preserves the same idempotency key and never approves the material',async()=>{
  const ui=setup(),form=ui.makeForm();await ui.entry.render(ui.host,'new','planning');
  let fail=true;
  ui.context.post=async(url,body)=>{ui.writes.push({url,body:structuredClone(body)});if(fail)throw Error('暂时断网');return {project:{id:'prj-0000000000000001'}};};
  await ui.entry.submit(form);assert.match(form.alert.textContent,/暂时断网/);
  assert.equal(ui.routes.length,0);assert.equal(form.dataset.submitted,undefined);
  fail=false;await ui.entry.submit(form);
  assert.equal(ui.writes.length,2);
  assert.equal(ui.writes[0].body.request_id,ui.writes[1].body.request_id);
  assert.equal(ui.writes[0].body.marketing_asset_id,source.id);
  assert.equal(ui.writes[0].body.brief.source_code,'B01');
  assert.equal(ui.writes[0].body.status,undefined);
  assert.deepEqual(ui.routes,[['campaigns','prj-0000000000000001','materials']]);
});

test('confirmed success ends the attempt; deliberately starting again uses a new key',async()=>{
  const ui=setup(),first=ui.makeForm();await ui.entry.render(ui.host,'new','planning');await ui.entry.submit(first);
  const second=ui.makeForm();await ui.entry.render(ui.host,'new','planning');await ui.entry.submit(second);
  assert.equal(ui.writes.length,2);
  assert.notEqual(ui.writes[0].body.request_id,ui.writes[1].body.request_id);
});

test('mismatching the source book blocks creation before any POST',async()=>{
  const ui=setup(),form=ui.makeForm({primary_code:'B02'});await ui.entry.render(ui.host,'new','planning');await ui.entry.submit(form);
  assert.match(form.alert.textContent,/请将它保留/);
  assert.equal(ui.writes.length,0);
});

test('unsubmitted requirements stay isolated by source and do not leak into ordinary creation',async()=>{
  const ui=setup(),form=ui.makeForm({topic:'只属于植物资料的主题'});await ui.entry.render(ui.host,'new','planning');ui.entry.remember();
  const saved=JSON.parse(ui.storage.get('bookworld.marketing-new:planning:'+source.id));
  assert.equal(saved.topic,form.elements.topic.value);
  ui.context.location.hash='#/campaigns/new/planning';await ui.entry.render(ui.host,'new','planning');
  assert.doesNotMatch(ui.host.innerHTML,/value="只属于植物资料的主题"/);
  assert.ok(!ui.storage.has('bookworld.marketing-new:planning'));
});

test('a late source read cannot overwrite a newer ordinary entry',async()=>{
  const ui=setup();let finish;ui.context.jget=()=>new Promise(resolve=>finish=resolve);
  const late=ui.entry.render(ui.host,'new','planning');
  ui.context.location.hash='#/campaigns';await ui.entry.render(ui.host);
  finish({asset:structuredClone(source)});await late;
  assert.doesNotMatch(ui.host.innerHTML,/已带入 1 条/);
  assert.match(ui.host.innerHTML,/营销整体方案/);
});

test('adding an already collected material opens the project without another mutation',async()=>{
  const ui=setup(),feedback={hidden:true,textContent:'',classList:{add(){}}};
  const panel={dataset:{asset:source.id},isConnected:true,setAttribute(){},removeAttribute(){},querySelector:()=>feedback,querySelectorAll:()=>[]};
  const form={closest:()=>panel,elements:{project:{value:'prj-0000000000000001'}}};
  ui.context.jget=async url=>url.startsWith('/api/content-assets/')?{asset:source}:{project:{id:'prj-0000000000000001',kind:'marketing',brief:{source_code:'B01'},items:[{asset_id:source.id,status:'selected'}],revision:2}};
  await ui.materials.add(form);
  assert.equal(ui.writes.length,0);
  assert.deepEqual(ui.routes,[['campaigns','prj-0000000000000001','materials']]);
});

test('reopening previously declined material preserves that decision and reveals its source row',async()=>{
  const ui=setup(),feedback={hidden:true,textContent:'',classList:{add(){}}},landings=[];
  const panel={dataset:{asset:source.id},isConnected:true,setAttribute(){},removeAttribute(){},querySelector:()=>feedback,querySelectorAll:()=>[]};
  const form={closest:()=>panel,elements:{project:{value:'prj-0000000000000001'}}};
  ui.context.Studio={prepareMarketingMaterialList:(...args)=>landings.push(args)};
  ui.context.jget=async url=>url.startsWith('/api/content-assets/')?{asset:source}:{project:{id:'prj-0000000000000001',kind:'marketing',brief:{source_code:'B01'},items:[{asset_id:source.id,status:'not_fit'}],revision:2}};
  await ui.materials.add(form);
  assert.equal(ui.writes.length,0);
  assert.deepEqual(ui.routes,[['campaigns','prj-0000000000000001','sources']]);
  assert.equal(landings.length,1);
  assert.ok(landings[0].includes(source.id));
});

test('both seeded home and seeded form URLs retain their route and material parameter',()=>{
  const code=read('app.js'),parse=code.slice(code.indexOf('function parse(hash){'),code.indexOf('function workflowContext()'));
  const context={URLSearchParams,location:{hash:''}};runInNewContext(parse,context);
  const encoded=encodeURIComponent(source.id);
  for(const [hash,arg,tab] of [['#/campaigns?material='+encoded,'',''],['#/campaigns/new/planning?material='+encoded,'new','planning']]){
    const result=context.parse(hash);assert.equal(result.view,'campaigns');assert.equal(result.arg,arg);assert.equal(result.tab,tab);assert.equal(result.extra.get('material'),source.id);
  }
});
