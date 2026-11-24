/* Stage one shows only narration, projected from the current manuscript. */
'use strict';
window.VideoScript=(function(){
  const names=new Set(['配音稿','镜头脚本','准备素材','生成提示词','发布文案']),legacyNames=new Set([...names].filter(x=>x!=='生成提示词')),views=new Map();let serial=0;
  function parseDocument(value,expected){
    const source=String(value||''),heads=[];let offset=0,fence=null;
    for(const line of source.split('\n')){
      const marker=line.match(/^ {0,3}(`{3,}|~{3,})/);
      if(marker){if(!fence)fence=marker[1];else if(marker[1][0]===fence[0]&&marker[1].length>=fence.length&&!line.slice(marker[0].length).trim())fence=null;}
      else if(!fence){const h=line.match(/^####[ \t]+(.+?)\s*$/);if(h)heads.push({name:h[1],start:offset,body:offset+line.length+1});}
      offset+=line.length+1;
    }
    // Unknown or incomplete structures stay in the normal full-text reader.
    if(heads.length!==expected.size||new Set(heads.map(x=>x.name)).size!==expected.size||heads.some(x=>!expected.has(x.name)))return null;
    const parts=heads.map((h,i)=>{const end=heads[i+1]?.start??source.length,body=source.slice(h.body,end);return {...h,end,contentStart:h.body+body.length-body.trimStart().length,raw:body.trim()};});
    if(parts.some(x=>!x.raw))return null;
    return {intro:source.slice(0,heads[0].start).trim(),parts};
  }
  function parse(value){return parseDocument(value,names)||parseDocument(value,legacyNames);}
  function voiceSegments(document){
    const part=document?.parts.find(x=>x.name==='镜头脚本'),script=part?.raw;if(!script)return null;
    const heads=Array.from(script.matchAll(/^#####\s+镜头\s+\d+\s*[·・].+$/gm));
    if(!heads.length||script.slice(0,heads[0].index).trim()||Array.from(script.matchAll(/^#####\s+/gm)).length!==heads.length)return null;
    const voices=[];
    for(let i=0;i<heads.length;i++){
      const shot=script.slice(heads[i].index+heads[i][0].length,heads[i+1]?.index??script.length);
      const starts=Array.from(shot.matchAll(/^\*\*口播：\*\*[ \t]*/gm));
      if(starts.length!==1)return null;
      const tail=shot.slice(starts[0].index+starts[0][0].length),end=tail.search(/^\*\*[^\n*]+：\*\*/m);
      if(end<0)return null;
      const text=tail.slice(0,end).trim();if(!text)return null;
      const raw=tail.slice(0,end),start=part.contentStart+heads[i].index+heads[i][0].length+starts[0].index+starts[0][0].length+raw.length-raw.trimStart().length;
      voices.push({text,start,end:start+text.length,title:heads[i][0].replace(/^#####\s*/,'')});
    }
    return voices;
  }
  function voiceover(document){const voices=voiceSegments(document);return voices?voices.map(x=>x.text).join('\n\n'):null;}
  function prepareOutlineEdit(value){return voiceSegments(parse(value));}
  function finishOutlineEdit(value,values){
    const source=String(value||''),voices=prepareOutlineEdit(source);
    if(!voices||voices.length!==values.length||values.some(x=>!String(x).trim()))return null;
    let changed=source;
    for(let i=voices.length-1;i>=0;i--)changed=changed.slice(0,voices[i].start)+String(values[i]).trim()+changed.slice(voices[i].end);
    return synchronize(changed);
  }
  function prepareEdit(value){
    const source=String(value||''),document=parse(source);if(!document||!voiceover(document))return null;
    const index=document.parts.findIndex(x=>x.name==='配音稿'),part=document.parts[index];
    return {body:source.slice(0,part.start)+source.slice(part.end),voiceIndex:index,sectionCount:document.parts.length};
  }
  function finishEdit(value,index=0,sectionCount){
    const source=String(value||''),document=parseDocument(source,new Set([...names].filter(x=>x!=='配音稿')))||parseDocument(source,new Set([...legacyNames].filter(x=>x!=='配音稿'))),voice=voiceover(document);
    if(!document||!voice||!Number.isInteger(index)||index<0||index>document.parts.length||(sectionCount!==undefined&&document.parts.length!==sectionCount-1))return null;
    const at=document.parts[index]?.start??source.length;
    return source.slice(0,at)+(at===source.length?'\n\n':'')+'#### 配音稿\n\n'+voice+'\n\n'+source.slice(at);
  }
  function synchronize(value){const edit=prepareEdit(value);return edit?finishEdit(edit.body,edit.voiceIndex,edit.sectionCount):null;}
  function formatted(text){return ManuscriptReader.build(text,new Map(),{frozen:true}).html;}
  function narration(source){const document=parse(source);return document?(voiceover(document)||document.parts.find(x=>x.name==='配音稿').raw):null;}
  function render(source,key){
    const document=parse(source);if(!document)return '';
    const voice=voiceover(document)||document.parts.find(x=>x.name==='配音稿').raw;
    const title=document.intro.match(/^#{1,3}\s+(.+)$/m)?.[1]||'',duration=document.intro.match(/计划\s*(\d+)\s*秒/)?.[1];
    const count=Array.from(voice.match(/[\p{L}\p{N}]/gu)||[]).length;
    const previous=views.get(key),entry={id:previous?.id||'video-script-'+(++serial),key,source,voice};
    views.delete(key);views.set(key,entry);while(views.size>40)views.delete(views.keys().next().value);
    return '<section class="video-script" data-video-script="'+esc(key)+'">'+(title?'<h1>'+esc(title)+'</h1>':'')+'<div class="video-script-use"><p>口播稿 · '+count+' 字（不含标点）'+(duration?' · 计划 '+esc(duration)+' 秒':'')+'</p><button type="button" class="btn ghost sm" onclick="VideoScript.copy(this)">复制口播稿</button></div><div class="video-script-section">'+formatted(voice)+'</div></section>';
  }
  function context(el){const root=el?.closest('[data-video-script]');return root?.isConnected?{root,entry:views.get(root.dataset.videoScript)}:null;}
  async function copyText(el,text,label){
    const ctx=context(el);if(!ctx?.entry||el.disabled)return;
    const {root,entry}=ctx,hash=location.hash;
    const current=()=>root.isConnected&&el.isConnected&&location.hash===hash&&views.get(entry.key)===entry;
    el.disabled=true;
    try{await navigator.clipboard.writeText(text);if(current())toast('已复制'+label);}
    catch(_){if(current())toast('复制失败，请选择这部分文字后复制。',true);}
    finally{el.disabled=false;}
  }
  function copy(el){const ctx=context(el);if(ctx?.entry)return copyText(el,ctx.entry.voice,'口播稿');}
  return {parse,render,copy,narration,prepareEdit,finishEdit,synchronize,prepareOutlineEdit,finishOutlineEdit};
})();
