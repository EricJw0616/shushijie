/* Keep content viewers, book readers and purchase decision-makers distinct. */
'use strict';
window.MarketingPurpose=(function(){
  const options=[['','暂不单独选择'],['inform','知识传播'],['reading','引导阅读'],['purchase','选书与购买'],['teaching','教学使用']];
  function values(data){return {purpose:options.some(x=>x[0]===data?.purpose)?data.purpose:'',book_readers:String(data?.book_readers||''),decision_maker:String(data?.decision_maker||'')};}
  function fields(data){
    const v=values(data);
    return '<div class="marketing-purpose-fields"><label class="studio-field"><span>这次主要做什么（选填）</span><select name="purpose" onchange="MarketingPurpose.change(this)">'+options.map(([value,label])=>'<option value="'+value+'"'+(value===v.purpose?' selected':'')+'>'+label+'</option>').join('')+'</select></label><div data-purchase-role'+(v.purpose==='purchase'?'':' hidden')+'><label class="studio-field"><span>由谁决定选书或购买（选填）</span><input name="decision_maker" value="'+esc(v.decision_maker)+'" placeholder="例如：读者本人、家长或学校采购人员；不清楚可留空"></label></div></div>';
  }
  function readers(data){return '<label class="studio-field"><span>这本书希望谁来读（选填）</span><input name="book_readers" value="'+esc(values(data).book_readers)+'" placeholder="与内容观众不同时再填，例如：内容给教师看，书给学生读"></label>';}
  function change(el){const host=el.closest('.marketing-purpose-fields');if(host)host.querySelector('[data-purchase-role]').hidden=el.value!=='purchase';}
  return {values,fields,readers,change};
})();
