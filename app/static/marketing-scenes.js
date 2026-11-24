/* Scene labels and views of the CURRENT manuscript; generation history is never a source. */
'use strict';
window.MarketingScenes=(function(){
  const scenes={
    '公众号':{title:'公众号文章',output:'标题、正文与阅读引导',hint:'围绕图书内容写一篇有出处的文章。'},
    '短视频':{title:'短视频口播稿',output:'先写口播，再选择图片或视频展示',hint:'将图书内容写成可直接讲述的口播稿。'},
    '小红书':{title:'小红书笔记',output:'发布文案与逐张配图提示词',hint:'围绕读者关心的问题组织图文笔记。'},
    '达人讲书':{title:'达人讲书',output:'完整讲稿与试讲提示',hint:'为讲书者准备能直接试讲的逐字稿。'},
    '书店活动':{title:'书店活动',output:'活动主题、流程与讨论问题',hint:'围绕图书组织线下交流内容。'}
  };
  function label(key){return scenes[key]?.title||(key==='planning'?'营销整体方案':key);}
  const audienceGuides={
    planning:{label:'主要受众',goalLabel:'推广目标',
      hint:'方案会先抓住受众在意的期待或顾虑，再安排各渠道用哪些书中内容回应。',
      goalPlaceholder:'例如：让对这个题材感兴趣的人了解本书，并愿意进一步阅读',
      notesLabel:'执行条件与表达偏好',notesPlaceholder:'例如：上市后两周，已有公众号和书店资源；让初次接触这个题材的人感到容易亲近。'},
    '公众号':{hint:'文章会从读者在意的问题切入，用书中细节建立共鸣，再给出继续阅读的理由。',
      goalPlaceholder:'例如：让读者从一个书中故事得到共鸣，愿意继续阅读',
      notesPlaceholder:'例如：约600字，从读者熟悉的小事切入，让人感到被理解。'},
    '短视频':{hint:'口播会先抓住观众的好奇，再用书中内容讲清一个问题，留下惊喜、共鸣或启发。',
      goalPlaceholder:'例如：让观众从好奇进入内容，看懂一个问题并记住这本书',
      notesLabel:'制作要求',notesPlaceholder:'例如：手绘风格，约60秒；先让人好奇，再把书中的解释讲明白。'},
    '小红书':{hint:'笔记会围绕受众熟悉的生活场景，把书中内容写成值得共鸣、收藏或分享的收获。',
      goalPlaceholder:'例如：让读者找到与生活相关的阅读收获，愿意收藏或分享',
      notesLabel:'笔记篇幅与配图风格',notesPlaceholder:'例如：约200字、5张图，自然纪实插画；让忙碌的读者看到容易开始的阅读方式。'},
    '达人讲书':{label:'讲给谁听',placeholder:'例如：对这个题材感兴趣、希望听懂书中内容的观众',
      hint:'讲稿供讲书者使用，内容会围绕听众在意的问题建立共鸣；图书读者与选购者可另填。',
      goalPlaceholder:'例如：让听众听懂一个书中故事，判断是否适合自己阅读',
      notesLabel:'试讲时长与讲述风格',notesPlaceholder:'例如：约4分钟，让选科普书的家长看到孩子怎样参与思考。'},
    '书店活动':{label:'哪些人来参加',placeholder:'例如：对本书主题感兴趣、愿意交流阅读感受的读者',
      hint:'活动会从参与者愿意聊的经历或问题切入，让人愿意开口，也能听见不同想法。',
      goalPlaceholder:'例如：让参与者围绕书中问题分享经历，带着新想法离开',
      notesLabel:'活动条件与交流方式',notesPlaceholder:'例如：约45分钟、20人；用容易回答的问题开场，让第一次参加的读者也敢分享。'}
  };
  function audienceGuide(sceneOrBrief){
    const keys=typeof sceneOrBrief==='string'?[sceneOrBrief]:fromBrief(sceneOrBrief);
    const key=keys.length===1?keys[0]:'';
    return {label:'内容给谁看',placeholder:'例如：第一次接触这个题材的读者',goalLabel:'希望谁做什么',
      goalPlaceholder:'例如：让读者从书中获得新的理解，愿意进一步阅读',
      hint:'内容会围绕受众在意的问题和期待选取书中材料，再按各场景安排表达。',
      notesLabel:'补充写作要求',notesPlaceholder:'例如：用具体故事回应读者的顾虑，让人看见新的可能。',
      ...(audienceGuides[key]||{})};
  }
  const deliveryHeadings={'小红书':['发布正文','配图制作'],'达人讲书':['讲述正文','提词与翻页']};
  function deliveryParts(channel,body){
    const names=deliveryHeadings[channel];
    if(!names)return null;
    const lines=String(body||'').trim().split('\n');
    const divider=lines.indexOf('#### '+names[1]);
    if(lines[0]!=='#### '+names[0]||divider<2||lines.lastIndexOf('#### '+names[1])!==divider||lines.lastIndexOf(lines[0])!==0)return null;
    const main=lines.slice(1,divider).join('\n').trim(),support=lines.slice(divider+1).join('\n').trim();
    if(!main||!support)return null;
    return {names,main,support};
  }
  function pictureCards(support){
    return String(support||'').split(/^##### /m).slice(1).map(block=>{
      const lines=block.trim().split('\n'),title=lines.shift();
      const marker=lines.indexOf('**生图提示词**');
      if(marker<0)return null;
      const details=lines.slice(0,marker).join('\n').trim(),prompt=lines.slice(marker+1).join('\n').trim();
      return title&&prompt?{title,details,prompt}:null;
    });
  }
  function deliveryCopy(channel,text){
    const clean=String(text||'').trim();
    const end=clean.indexOf('\n');
    const parts=end>0?deliveryParts(channel,clean.slice(end+1)):null;
    if(!parts)return clean.replace(/^#[ \t]+/,'');
    if(channel==='达人讲书')return parts.main.replace(/^\*\*[^\n]+\*\*[ \t]*$/gm,'').replace(/\n{3,}/g,'\n\n').trim();
    return clean.slice(0,end).replace(/^#[ \t]+/,'').trim()+'\n\n'+parts.main;
  }
  function fromBrief(brief){
    return brief?.marketing_task==='channel'?(brief.channels||[]).filter(x=>Object.hasOwn(scenes,x)):['planning'];
  }
  function workflow(brief){
    const keys=fromBrief(brief).filter(key=>key!=='planning');
    if(!keys.length)return {scoped:false,title:'营销整体方案',noun:'方案',draft:'营销方案初稿',materials:'项目素材',select:'选入本次方案',generate:'用已选素材生成营销方案'};
    const title=keys.map(label).join('、'),single=keys.length===1;
    const nouns={'公众号':'文章','短视频':'口播稿','小红书':'笔记','达人讲书':'讲稿','书店活动':'活动方案'};
    const drafts={'公众号':'公众号初稿','短视频':'口播初稿','小红书':'小红书笔记初稿','达人讲书':'讲书稿初稿','书店活动':'活动方案初稿'};
    const noun=single?nouns[keys[0]]:'本次内容',draft=single?drafts[keys[0]]:'各场景初稿';
    return {scoped:true,title,noun,draft,materials:single?noun+'素材':'各场景素材',select:'选入'+noun,generate:'用已选素材生成'+draft};
  }
  const internalSections=new Set(['传播角度与受众价值','渠道内容与表达安排','各书在专题中的作用','材料怎样复用','需要补充','资料缺口','下一步验证','本次未使用的材料','来源索引']);
  function nextStep(keys){
    const steps={'公众号':'复制正文到公众号编辑器，配图、排版后发布。','短视频':'确认口播内容，再选择图片或视频展示。','小红书':'用配图提示词制作图片，配上发布文案。','达人讲书':'将逐字稿和讲述提示交给讲书者，试讲后录制。','书店活动':'将方案交给活动负责人，确认时间、场地和人员后执行。'};
    const selected=(keys||[]).filter(x=>Object.hasOwn(scenes,x));
    return selected.length===1?steps[selected[0]]:'各场景内容分别交给对应的运营或制作人员使用。';
  }
  function deliveryInfo(entry){
    if(entry?.content_kind==='marketing_plan')return {title:'营销整体方案'+(entry.mode==='approved'?'':' · 审阅稿'),next:'按推进安排分配工作，再分别制作需要的渠道内容。'};
    if(entry?.content_kind!=='channel_content')return null;
    const title=(entry.channels||[]).map(label).join('、')||'营销内容';
    return {title:title+' · '+(entry.mode==='approved'?'已审核':'待审核'),next:entry.mode==='approved'?nextStep(entry.channels):'供同事核对正文，确认后再导出。'};
  }
  function stripMarkers(source,knownLabels){
    const known=new Set(knownLabels||[]),definitions=new Set(),lines=String(source||'').split('\n');let fenced=null;
    const toggle=line=>{const match=line.match(/^ {0,3}(`{3,}|~{3,})/);if(!match)return false;if(!fenced)fenced=match[1];else if(new RegExp('^ {0,3}'+fenced[0]+'{'+fenced.length+',}\\s*$').test(line))fenced=null;return true;};
    for(const line of lines){if(toggle(line)||fenced)continue;const match=line.match(/^ {0,3}\[([^\]]+)\]:[ \t]*\S/);if(match)definitions.add(match[1].trim().replace(/\s+/g,' ').toLowerCase());}
    fenced=null;
    const strip=chunk=>chunk.replace(/(?<!\\)\[(S[1-9]\d*)\]/g,(match,id,offset)=>{
      const after=chunk.slice(offset+match.length),reference=after.match(/^[ \t]+\[([^\]]+)\]/);
      const linked=definitions.has(id.toLowerCase())||after.startsWith('[')||/^[ \t]*[(:]/.test(after)||(reference&&(!known.has(reference[1])||definitions.has(reference[1].toLowerCase())));
      return known.has(id)&&!linked?'':match;
    });
    return lines.map(line=>{
      if(toggle(line)||fenced||/^ {4}|^\t/.test(line))return line;
      return line.split(/(`+[^`]*`+|!?\[[^\]]*\]\([^)]*\)|!?\[[^\]]*\]\[[^\]]*\])/g).map((chunk,index)=>index%2?chunk:strip(chunk)).join('');
    }).join('\n');
  }
  function cleanPart(part,knownLabels){
    let raw=part.raw.replace(/^### [^：:]+[：:]\s*/, '# ');
    const paragraphs=raw.trimEnd().split(/\n\s*\n/);
    if(part.legacy&&paragraphs.length>1)paragraphs[paragraphs.length-1]=paragraphs[paragraphs.length-1].replace(/^行动引导[：:]\s*/, '');
    return stripMarkers(paragraphs.join('\n\n'),knownLabels).trim();
  }
  function split(source,channels){
    source=String(source||'');
    const headings=[];let offset=0,fenced=null;
    for(const line of source.split('\n')){
      const fence=line.match(/^\s*(`{3,}|~{3,})/);
      if(fence){if(!fenced)fenced=fence[1];else if(new RegExp('^\\s*'+fenced[0]+'{'+fenced.length+',}\\s*$').test(line))fenced=null;}
      else if(!fenced){const m=line.match(/^(#{1,3})[ \t]+(.+?)\s*$/);if(m)headings.push({level:m[1].length,title:m[2],start:offset});}
      offset+=line.length+1;
    }
    const starts=headings.filter(h=>h.level===2&&h.title==='渠道素材初稿');
    if(starts.length!==1)return null;
    const start=headings.indexOf(starts[0]);
    const legacy=headings.slice(0,start).some(h=>h.level===2&&internalSections.has(h.title));
    if(source.slice(0,headings[start].start).trim()&&!legacy)return null;
    const boundaryHeading=legacy?headings.slice(start+1).find(h=>h.level<=2&&internalSections.has(h.title)):null;
    const boundary=boundaryHeading?.start??source.length;
    const children=headings.slice(start+1).filter(h=>h.start<boundary&&h.level===3&&Object.hasOwn(scenes,h.title.match(/^([^：:]+)[：:]/)?.[1]));
    const introStart=source.indexOf('\n',headings[start].start)+1;
    if(!children.length||source.slice(introStart,children[0].start).trim())return null;
    const seen=new Set(),parts=[];
    for(let i=0;i<children.length;i++){
      const h=children[i],m=h.title.match(/^([^：:]+)[：:]\s*(.+)$/);
      if(!m||seen.has(m[1]))return null;
      seen.add(m[1]);const finish=children[i+1]?.start??boundary;
      parts.push({key:m[1],legacy,title:m[2].replace(/\s*\[S\d+\]/g,'').trim(),start:h.start,end:finish,raw:source.slice(h.start,finish)});
    }
    if(channels&&(parts.length!==channels.length||parts.some(p=>!channels.includes(p.key))))return null;
    return {parts,context:[{start:0,raw:source.slice(0,headings[start].start)},
      {start:introStart,raw:source.slice(introStart,children[0].start)},
      {start:boundary,raw:source.slice(boundary)}]};
  }
  return {scenes,label,audienceGuide,fromBrief,workflow,split,cleanPart,stripMarkers,nextStep,deliveryInfo,deliveryParts,pictureCards,deliveryCopy};
})();
