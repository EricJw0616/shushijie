/* Formatted project editor with a Markdown value kept outside the editing surface. */
'use strict';
window.ManuscriptEditor = (function(){
  const citation = /^\[S[1-9]\d*\]$/;
  const blocks = /^(?:DIV|P|H[1-6]|UL|OL|BLOCKQUOTE|PRE|TABLE|HR)$/;

  function inline(node){
    if(node.nodeType === Node.TEXT_NODE)return node.data.replace(/\u00a0/g,' ');
    if(node.nodeType !== Node.ELEMENT_NODE)return '';
    const token=node.dataset.citationToken;
    if(citation.test(token||''))return token;
    if(node.tagName==='BR')return '\n';
    if(blocks.test(node.tagName))return markdown(node)+'\n';
    const text=Array.from(node.childNodes,inline).join('');
    if(!text.trim())return text;
    if(['STRONG','B'].includes(node.tagName)||/^(bold|[6-9]00)$/.test(node.style.fontWeight))return '**'+text+'**';
    if(['EM','I'].includes(node.tagName)||node.style.fontStyle==='italic')return '*'+text+'*';
    if(['DEL','S','STRIKE'].includes(node.tagName))return '~~'+text+'~~';
    if(node.tagName==='CODE'&&!text.includes('`'))return '`'+text+'`';
    if(node.tagName==='A'&&/^https?:\/\//i.test(node.getAttribute('href')||'')){
      return '['+text.replace(/]/g,'\\]')+']('+node.getAttribute('href').replace(/\)/g,'%29').replace(/ /g,'%20')+')';
    }
    return text;
  }

  function inner(node){
    if(node.childNodes.length===1&&node.firstChild.nodeName==='BR')return '';
    return Array.from(node.childNodes,inline).join('').replace(/\n+$/,'');
  }

  function listMarkdown(node,indent=''){
    const ordered=node.tagName==='OL';
    const first=ordered?Number(node.getAttribute('start')||1):1;
    return Array.from(node.children).filter(child=>child.tagName==='LI').map((child,index)=>{
      const prefix=ordered?(first+index)+'. ':'- ';
      const children=Array.from(child.childNodes),nested=children.filter(n=>/^(UL|OL)$/.test(n.nodeName));
      const content=children.filter(n=>!nested.includes(n)).map(inline).join('').trimEnd();
      const continuation=indent+' '.repeat(prefix.length);
      const line=indent+prefix+content.replace(/\n/g,'\n'+continuation);
      return [line,...nested.map(x=>listMarkdown(x,continuation))].join('\n');
    }).join('\n');
  }

  function tableMarkdown(table){
    const rows=Array.from(table.rows,row=>Array.from(row.cells,cell=>inner(cell).replace(/\|/g,'\\|').replace(/\n+/g,' ')));
    if(!rows.length)return '';
    const count=Math.max(...rows.map(row=>row.length));
    const format=row=>'| '+Array.from({length:count},(_,i)=>row[i]||'').join(' | ')+' |';
    return [format(rows[0]),format(Array(count).fill('---')),...rows.slice(1).map(format)].join('\n');
  }

  function markdown(node){
    if(!blocks.test(node.nodeName))return inline(node);
    const tag=node.tagName;
    if(tag==='PRE'){
      const text=node.textContent.replace(/\n$/,'');
      const longest=Math.max(2,...Array.from(text.matchAll(/`+/g),match=>match[0].length));
      const fence='`'.repeat(longest+1);
      return fence+'\n'+text+'\n'+fence;
    }
    if(tag==='UL'||tag==='OL')return listMarkdown(node);
    if(tag==='TABLE')return tableMarkdown(node);
    if(tag==='HR')return '---';
    const text=inner(node);
    if(/^H[1-6]$/.test(tag))return text.trim()?'#'.repeat(Number(tag[1]))+' '+text.replace(/\n+/g,' '):'';
    if(tag==='BLOCKQUOTE')return text.split('\n').map(line=>line?'> '+line:'>').join('\n');
    return text;
  }

  function mount(host,backing,refs,onChange){
    host.innerHTML='<div role="toolbar" aria-label="稿件排版" class="manuscript-format-bar">'+
      '<button type="button" data-command="formatBlock" data-value="p">正文</button>'+
      '<button type="button" data-command="formatBlock" data-value="h2">标题</button>'+
      '<button type="button" data-command="formatBlock" data-value="h3">小标题</button>'+
      '<button type="button" data-command="bold">加粗</button>'+
      '<button type="button" data-command="insertUnorderedList">项目列表</button>'+
      '<button type="button" data-command="insertOrderedList">编号列表</button>'+
      '<select aria-label="插入出处" class="manuscript-citation-picker" hidden></select></div>'+
      '<div class="manuscript-rich-input manuscript-reading" contenteditable="true" role="textbox" aria-multiline="true" aria-label="编辑当前工作稿" spellcheck="false"></div>';
    const toolbar=host.querySelector('.manuscript-format-bar'),editor=host.querySelector('.manuscript-rich-input');
    const picker=host.querySelector('.manuscript-citation-picker');
    let originals=[],base='',lastRaw=null,referenceMap=refs,lastRange=null,referenceStamp;
    let composing=false;

    function render(){
      base=backing.value;
      lastRaw=base;
      lastRange=null;
      const doc=ManuscriptReader.build(base,referenceMap,{editing:true});
      editor.innerHTML=doc.html;
      originals=doc.blocks.map((block,index)=>{
        const element=editor.querySelector('[data-manuscript-block="'+index+'"]');
        return {...block,index,html:element?.outerHTML};
      });
    }

    function refreshReferences(){
      const stamp=JSON.stringify(Array.from(referenceMap,([id,ref])=>[id,ref.displayLabel,ref.title,ref.warning]));
      if(stamp===referenceStamp)return;
      referenceStamp=stamp;

      const choices=Array.from(referenceMap).filter(([id,ref])=>citation.test('['+id+']')&&ref.displayLabel&&!ref.warning);
      picker.replaceChildren(new Option('插入出处…',''));
      for(const [id,ref] of choices){
        picker.add(new Option('出处 '+ref.displayLabel.slice(1)+(ref.title?' · '+ref.title:''),id));
      }
      picker.hidden=!choices.length;

      const selector='[data-citation-token]';
      const tokens=new Set(Array.from(editor.querySelectorAll(selector),chip=>chip.dataset.citationToken));
      const template=document.createElement('template');
      template.innerHTML=ManuscriptReader.inline(Array.from(tokens).filter(token=>citation.test(token)).join(' '),referenceMap,{editing:true});
      const chips=new Map(Array.from(template.content.querySelectorAll(selector),chip=>[chip.dataset.citationToken,chip]));
      function applyLabels(container){
        for(const chip of container.querySelectorAll(selector)){
          const updated=chips.get(chip.dataset.citationToken);
          if(!updated)continue;
          if(chip.textContent!==updated.textContent)chip.textContent=updated.textContent;
          chip.title=updated.title;
          chip.className=updated.className;
        }
      }
      applyLabels(editor);
      for(const record of originals){
        if(!record.html?.includes('data-citation-token='))continue;
        template.innerHTML=record.html;
        applyLabels(template.content);
        record.html=template.content.firstElementChild.outerHTML;
      }
    }

    function collect(){
      const seen=new Set(),parts=[];
      for(const node of editor.childNodes){
        if(node.nodeType===Node.COMMENT_NODE)continue;
        const index=node.dataset?.manuscriptBlock;
        const record=index!==undefined&&!seen.has(index)?originals[Number(index)]:null;
        if(record)seen.add(index);
        const value=record&&record.html===node.outerHTML?record.raw:markdown(node);
        parts.push({node,record,value});
      }
      if(!parts.some(part=>part.value.trim()))return {text:'',parts:[]};
      let text=parts[0].record?.index===0?base.slice(0,parts[0].record.start):'';
      for(let i=0;i<parts.length;i++){
        const part=parts[i];
        const previous=parts[i-1]?.record;
        if(i){
          text+=previous&&part.record?.index===previous.index+1?
            base.slice(previous.end,part.record.start):'\n\n';
        }
        part.start=text.length;
        text+=part.value;
        part.end=text.length;
      }
      const tail=parts[parts.length-1].record;
      if(tail&&tail.index===originals.length-1)text+=base.slice(tail.end);
      return {text,parts};
    }

    function changed(){
      if(composing)return;
      const text=collect().text;
      if(text===lastRaw)return;
      backing.value=text;
      lastRaw=backing.value;
      onChange();
    }

    function rememberSelection(){
      const selection=window.getSelection();
      if(selection.rangeCount&&editor.contains(selection.anchorNode)&&editor.contains(selection.focusNode)){
        lastRange=selection.getRangeAt(0).cloneRange();
      }
    }

    function setSelection(range){
      const selection=window.getSelection();
      editor.focus({preventScroll:true});
      selection.removeAllRanges();
      selection.addRange(range);
      lastRange=range.cloneRange();
    }

    function restoreSelection(){
      if(lastRange&&editor.contains(lastRange.startContainer)&&editor.contains(lastRange.endContainer)){
        setSelection(lastRange);
      }else{
        const range=document.createRange();
        range.selectNodeContents(editor);
        range.collapse(false);
        setSelection(range);
      }
    }

    function focusOffset(offset,length=0){
      const {parts}=collect();
      const part=parts.find(p=>offset>=p.start&&offset<p.end)||
        parts.find(p=>p.start>=offset)||parts[parts.length-1];
      if(!part){editor.focus({preventScroll:true});return;}
      const node=part.node,text=backing.value.slice(offset,offset+length);
      const range=document.createRange();
      if(citation.test(text)&&node.nodeType===Node.ELEMENT_NODE){
        const earlier=part.value.slice(0,Math.max(0,offset-part.start));
        const index=earlier.split(text).length-1;
        const chip=Array.from(node.querySelectorAll('[data-citation-token]'))
          .filter(item=>item.dataset.citationToken===text)[index];
        if(chip)range.selectNode(chip);
        else {range.selectNodeContents(node);range.collapse(true);}
      }else if(text){
        const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);
        let candidate=node.nodeType===Node.TEXT_NODE?node:walker.nextNode();
        while(candidate&&!candidate.data.includes(text))candidate=walker.nextNode();
        if(candidate){
          const index=candidate.data.indexOf(text);
          range.setStart(candidate,index);
          range.setEnd(candidate,index+text.length);
        }else{range.selectNodeContents(node);range.collapse(true);}
      }else{
        range.selectNodeContents(node);
        range.collapse(true);
      }
      setSelection(range);
      const scrollTarget=node.nodeType===Node.ELEMENT_NODE?node:node.parentElement;
      scrollTarget?.scrollIntoView({block:'nearest',behavior:'instant'});
    }

    toolbar.addEventListener('mousedown',event=>{
      if(event.target.closest('button')){rememberSelection();event.preventDefault();}
    });
    toolbar.addEventListener('click',event=>{
      const button=event.target.closest('button[data-command]');
      if(!button)return;
      restoreSelection();
      document.execCommand(button.dataset.command,false,button.dataset.value||null);
      changed();
      rememberSelection();
    });
    picker.addEventListener('mousedown',rememberSelection);
    picker.addEventListener('change',()=>{
      const label=picker.value,ref=referenceMap.get(label),token='['+label+']';
      picker.value='';
      if(!citation.test(token)||!ref?.displayLabel||ref.warning)return;
      restoreSelection();
      const range=window.getSelection().getRangeAt(0),template=document.createElement('template');
      template.innerHTML=ManuscriptReader.inline(token,referenceMap,{editing:true});
      const chip=template.content.firstElementChild;
      range.deleteContents();
      const anchor=range.startContainer;
      const container=anchor.nodeType===Node.ELEMENT_NODE?anchor:anchor.parentElement;
      const inlineBoundary=container?.closest('pre, code, a, [data-citation-token]');
      if(inlineBoundary){
        range.setStartAfter(inlineBoundary.closest('pre')||inlineBoundary);
        range.collapse(true);
      }
      if(range.startContainer===editor){
        const paragraph=document.createElement('p');
        paragraph.append(chip);
        range.insertNode(paragraph);
      }else range.insertNode(chip);
      range.setStartAfter(chip);
      range.collapse(true);
      setSelection(range);
      changed();
    });
    editor.addEventListener('compositionstart',()=>{composing=true;});
    editor.addEventListener('compositionend',()=>{composing=false;changed();refreshReferences();});
    editor.addEventListener('input',()=>{changed();rememberSelection();});
    for(const event of ['keyup','mouseup','focusout'])editor.addEventListener(event,rememberSelection);
    editor.addEventListener('paste',event=>{
      event.preventDefault();
      const text=(event.clipboardData?.getData('text/plain')||'').replace(/\r\n?/g,'\n');
      if(!text)return;
      if(!document.execCommand('insertText',false,text)){
        const sel=window.getSelection();
        if(sel.rangeCount&&editor.contains(sel.getRangeAt(0).commonAncestorContainer)){
          const range=sel.getRangeAt(0);
          range.deleteContents();
          const node=document.createTextNode(text);
          range.insertNode(node);
          range.setStartAfter(node);
          range.collapse(true);
          setSelection(range);
        }
      }
      changed();
    });
    editor.addEventListener('drop',event=>event.preventDefault());
    render();
    refreshReferences();
    return {
      focus(){restoreSelection();},
      focusOffset,
      sync(next=referenceMap){
        referenceMap=next;
        if(composing)return;
        if(backing.value!==lastRaw)render();
        refreshReferences();
      }
    };
  }
  return {mount};
})();
