import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import test from 'node:test';

const context={window:{},esc:value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
runInNewContext(readFileSync(new URL('../static/marketing-purpose.js',import.meta.url),'utf8'),context);
const ui=context.window.MarketingPurpose;

test('legacy empty purpose stays optional, without inferring a purchase decision-maker from age',()=>{
  const values=ui.values({audience:'11—14岁'});
  assert.deepEqual(JSON.parse(JSON.stringify(values)),{purpose:'',book_readers:'',decision_maker:''});
  const fields=ui.fields({audience:'11—14岁'});assert.match(fields,/data-purchase-role hidden/);assert.match(fields,/name="decision_maker" value=""/);assert.doesNotMatch(fields,/required/);
});

test('explicit viewers/readers/buyers stay separate and switching purpose does not erase the saved buyer',()=>{
  const data={audience:'家长',book_readers:'孩子',purpose:'purchase',decision_maker:'祖父母'};
  assert.match(ui.fields(data),/name="decision_maker" value="祖父母"/);assert.doesNotMatch(ui.fields(data),/data-purchase-role hidden/);assert.match(ui.readers(data),/value="孩子"/);
  const changed=ui.values({...data,purpose:'teaching'});assert.equal(changed.decision_maker,'祖父母');assert.match(ui.fields(changed),/data-purchase-role hidden/);
  const group={hidden:true},field={value:'purchase',closest:()=>({querySelector:()=>group})};ui.change(field);assert.equal(group.hidden,false);field.value='inform';ui.change(field);assert.equal(group.hidden,true);
});

test('purpose choices have stable supported values and user-provided role text is escaped',()=>{
  const html=ui.fields({purpose:'unknown',decision_maker:'"<img src=x>'});
  assert.deepEqual(Array.from(html.matchAll(/<option value="([^"]*)"/g),m=>m[1]),['','inform','reading','purchase','teaching']);
  assert.match(html,/&quot;&lt;img/);assert.doesNotMatch(html,/<img/);
});
