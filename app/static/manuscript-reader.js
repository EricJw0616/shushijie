/* Shared manuscript formatting. Text from drafts and snapshots is always escaped. */
'use strict';
window.ManuscriptReader=(function(){
  const heading=/^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$/;
  const list=/^([ \t]*)(?:([-+*])|(\d+)\.)[ \t]+(.+)$/;
  const quote=/^\s*> ?(.*)$/;
  const fence=/^[ \t]*(`{3,}|~{3,})(.*)$/;
  const rule=/^\s*(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$/;
  const emptyReferences=new Map();

  function citation(token,label,source,options){
    const displayLabel=source?.displayLabel||(options.frozen?label:null);
    const display=displayLabel?'出处 '+displayLabel.slice(1):source?'旧出处':'出处待核对';
    const title=source?.title||(options.frozen?display:'需要核对对应材料');
    const warning=options.frozen?'':source?.warning||(!source?'未关联材料':'');
    const css='draft-citation'+(warning?' draft-citation-warning':'');
    if(options.editing){
      return '<span class="'+css+'" contenteditable="false" data-citation-token="'+esc(token)+'" title="'+esc(title)+'">'+esc(display)+'</span>';
    }
    if(options.frozen||warning){
      return '<span class="'+css+'" title="'+esc(title)+'">'+esc(warning&&source?display+' · '+warning:display)+'</span>';
    }
    return '<button type="button" class="'+css+'" data-id="'+esc(source.id)+'" onclick="Studio.openMaterialDetail(this)" aria-label="'+esc(display+'，'+title)+'" title="'+esc(title)+'">'+esc(display)+'</button>';
  }

  function inline(text,references=emptyReferences,options={}){
    const pattern=/`([^`\n]+)`|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|\[(S[1-9]\d*)\]|(\*\*\*|___)(.+?)\5|(\*\*|__)(.+?)\7|~~([^~\n]+)~~|\*([^*\n]+)\*|(?<![\w_])_([^_\n]+)_(?![\w_])/g;
    text=String(text??'');
    let html='',last=0;
    for(const match of text.matchAll(pattern)){
      const [token,code,linkText,url,label,combined,emphasis,strong,bold,deleted,italic,underlined]=match;
      const render=value=>inline(value,references,options);
      html+=esc(text.slice(last,match.index));
      if(code!==undefined)html+='<code>'+esc(code)+'</code>';
      else if(url)html+='<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(linkText)+'</a>';
      else if(label)html+=citation(token,label,references.get(label),options);
      else if(combined)html+='<strong><em>'+render(emphasis)+'</em></strong>';
      else if(strong)html+='<strong>'+render(bold)+'</strong>';
      else if(deleted)html+='<del>'+render(deleted)+'</del>';
      else html+='<em>'+render(italic||underlined)+'</em>';
      last=match.index+token.length;
    }
    return html+esc(text.slice(last));
  }

  function tableCells(line){
    return line.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(cell=>cell.trim().replace(/\\\|/g,'|'));
  }

  function tableStarts(lines,i){
    return lines[i]?.includes('|')&&lines[i+1]?.includes('|')&&
      tableCells(lines[i+1]).every(cell=>/^:?-{3,}:?$/.test(cell))&&
      tableCells(lines[i]).length===tableCells(lines[i+1]).length;
  }

  function build(source,references=emptyReferences,options={}){
    source=String(source??'');
    const lines=source.split('\n');
    let offset=0;
    const offsets=lines.map(line=>{const start=offset;offset+=line.length+1;return start;});
    const sections=[], blocks=[], rendered=[];
    const format=text=>inline(text,references,options);
    let i=0;
    while(i<lines.length){
      const start=offsets[i],line=lines[i],head=line.match(heading),item=line.match(list),opening=line.match(fence);
      let html;
      if(!line.trim()){
        i++;
        continue;
      }
      if(opening){
        const code=[];
        const close=new RegExp('^\\s*'+opening[1][0]+'{'+opening[1].length+',}\\s*$');
        while(++i<lines.length&&!close.test(lines[i]))code.push(lines[i]);
        if(i<lines.length)i++;
        html='<pre><code>'+esc(code.join('\n'))+'</code></pre>';
      }else if(head){
        const level=head[1].length;
        const title=head[2].replace(/\s*\[S[1-9]\d*\]/g,'').replace(/\*\*|__|`/g,'').trim();
        sections.push({level,at:start,title});
        html='<h'+level+' data-draft-heading="'+start+'" tabindex="-1">'+format(head[2])+'</h'+level+'>';
        i++;
      }else if(rule.test(line)){
        html='<hr>';
        i++;
      }else if(item){
        const renderList=(indent,ordered)=>{
          const tag=ordered?'ol':'ul',items=[];
          const first=lines[i].match(list)[3];
          let next;
          while(i<lines.length&&(next=lines[i].match(list))&&next[1].length===indent&&Boolean(next[3])===ordered){
            i++;
            let text=format(next[4]),child;
            while(i<lines.length&&(child=lines[i].match(list))&&child[1].length>indent){
              text+=renderList(child[1].length,Boolean(child[3]));
            }
            items.push('<li>'+text+'</li>');
          }
          const initial=first&&first!=='1'?' start="'+esc(first)+'"':'';
          return '<'+tag+initial+'>'+items.join('')+'</'+tag+'>';
        };
        html=renderList(item[1].length,Boolean(item[3]));
      }else if(quote.test(line)){
        const quoted=[];
        while(i<lines.length&&quote.test(lines[i]))quoted.push(format(lines[i++].match(quote)[1]));
        html='<blockquote>'+quoted.join('<br>')+'</blockquote>';
      }else if(tableStarts(lines,i)){
        const columns=tableCells(line),body=[];
        i+=2;
        while(i<lines.length&&lines[i].trim()&&lines[i].includes('|')&&tableCells(lines[i]).length===columns.length){
          body.push('<tr>'+tableCells(lines[i++]).map(cell=>'<td>'+format(cell)+'</td>').join('')+'</tr>');
        }
        html='<div class="manuscript-table"><table><thead><tr>'+columns.map(cell=>'<th scope="col">'+format(cell)+'</th>').join('')+'</tr></thead><tbody>'+body.join('')+'</tbody></table></div>';
      }else{
        const paragraph=[format(lines[i++])];
        while(i<lines.length&&lines[i].trim()&&!heading.test(lines[i])&&!list.test(lines[i])&&!quote.test(lines[i])&&!fence.test(lines[i])&&!rule.test(lines[i])&&!tableStarts(lines,i)){
          paragraph.push(format(lines[i++]));
        }
        html='<p>'+paragraph.join('<br>')+'</p>';
      }
      if(options.editing){
        const end=i<lines.length?offsets[i]-1:source.length;
        html=html.replace(/^<([a-z][a-z0-9]*)/, '$& data-manuscript-block="'+blocks.length+'" data-source-offset="'+start+'"');
        blocks.push({raw:source.slice(start,end),start,end});
      }
      rendered.push(html);
    }
    const main=sections.filter(section=>section.level===2);
    return {html:rendered.join(''),sections:main.length?main:sections,blocks};
  }
  return {build,inline};
})();
