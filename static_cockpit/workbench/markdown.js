'use strict';
// A deliberately small Markdown renderer. Raw HTML is always text; images never
// load remote resources. Only explicit HTTP(S)/mailto links or controller-bound artifact links become anchors.
window.twosMarkdown = (() => {
 const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function inline(text, depth=0, links={}) {
  if(depth>4)return escape(text);
  const tokens=/(`+)([^\n]*?)\1|\*\*([^\n]+?)\*\*|(?<![\p{L}\p{N}_])__([^\n]+?)__(?![\p{L}\p{N}_])|\*([^*\n]+?)\*|(?<![\p{L}\p{N}_])_([^_\n]+?)_(?![\p{L}\p{N}_])|(!?)\[([^\]\n]+)\]\(([^\s)]+)\)/gu;
  let result='', end=0;
  for(const m of text.matchAll(tokens)){
   result+=escape(text.slice(end,m.index));end=m.index+m[0].length;
   if(m[1])result+='<code>'+escape(m[2])+'</code>';
   else if(m[3]||m[4])result+='<strong>'+inline(m[3]||m[4],depth+1,links)+'</strong>';
   else if(m[5]||m[6])result+='<em>'+inline(m[5]||m[6],depth+1,links)+'</em>';
   else if(!m[7]){
    const bound=Object.hasOwn(links,m[9])&&/^\/api\/r2\/wb\/deliveries\/[^/]+\/files\//.test(links[m[9]])?links[m[9]]:null;
    const url=bound||(/^(https?:\/\/|mailto:)[^\x00-\x20\x7f]+$/i.test(m[9])?m[9]:null);
    result+=url?'<a href="'+escape(url)+'" target="_blank" rel="noopener noreferrer">'+inline(m[8],depth+1,links)+'</a>':escape(m[0]);
   }
   else result+=escape(m[0]);
  }
  return result+escape(text.slice(end));
 }
 function render(source, depth=0, links={}){
  if(depth>8)return '<p>'+escape(source)+'</p>';
  const lines=String(source).replace(/\r\n?/g,'\n').split('\n');let out='',i=0;
  const list=/^(\s*)([-+*]|\d+[.)])\s+(.*)$/;
  const special=line=>!line.trim()||/^\s*(`{3,}|~{3,})/.test(line)||/^ {0,3}(#{1,6})\s+/.test(line)||/^\s*>/.test(line)||list.test(line)||/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line);
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(v=>v.trim());
  while(i<lines.length){
   const line=lines[i];if(!line.trim()){i++;continue;}
   const fence=line.match(/^\s*(`{3,}|~{3,})([^`]*)$/);
   if(fence){const code=[];i++;const close=new RegExp('^\\s*'+fence[1][0]+'{'+fence[1].length+',}\\s*$');while(i<lines.length&&!close.test(lines[i]))code.push(lines[i++]);if(i<lines.length)i++;out+='<pre><code>'+escape(code.join('\n'))+'</code></pre>';continue;}
   const heading=line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*#*$/);
   if(heading){const n=heading[1].length;out+=`<h${n}>${inline(heading[2],0,links)}</h${n}>`;i++;continue;}
   if(/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)){out+='<hr>';i++;continue;}
   if(/^\s*>/.test(line)){const block=[];while(i<lines.length&&/^\s*>/.test(lines[i]))block.push(lines[i++].replace(/^\s*> ?/,''));out+='<blockquote>'+render(block.join('\n'),depth+1,links)+'</blockquote>';continue;}
   const item=line.match(list);
   if(item){const ordered=/\d/.test(item[2]),tag=ordered?'ol':'ul',indent=item[1].length;out+='<'+tag+(ordered?' start="'+parseInt(item[2],10)+'"':'')+'>';
    while(i<lines.length){const row=lines[i].match(list);if(!row||row[1].length!==indent||/\d/.test(row[2])!==ordered)break;
     const task=row[3].match(/^\[([ xX])\]\s+(.*)$/);out+='<li'+(task?' class="task-list-item"':'')+'>'+(task?'<input type="checkbox" disabled aria-label="'+escape(task[2])+'" '+(task[1]!==' '?'checked':'')+'>'+inline(task[2],0,links):inline(row[3],0,links));i++;
     const nested=[];while(i<lines.length&&lines[i].trim()&&/^\s/.test(lines[i])&&(lines[i].match(/^\s*/)[0].length>indent)){nested.push(lines[i++].slice(indent+2));}
     if(nested.length)out+=render(nested.join('\n'),depth+1,links);out+='</li>';
    }
    out+='</'+tag+'>';continue;
   }
   if(line.includes('|')&&i+1<lines.length&&cells(lines[i+1]).every(v=>/^:?-{3,}:?$/.test(v))){const heads=cells(line);out+='<div class="table-scroll"><table><thead><tr>'+heads.map(v=>'<th>'+inline(v,0,links)+'</th>').join('')+'</tr></thead><tbody>';i+=2;while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){const row=cells(lines[i++]);out+='<tr>'+heads.map((_,n)=>'<td>'+inline(row[n]||'',0,links)+'</td>').join('')+'</tr>';}out+='</tbody></table></div>';continue;}
   const paragraph=[line];i++;while(i<lines.length&&!special(lines[i]))paragraph.push(lines[i++]);out+='<p>'+paragraph.map(v=>inline(v,0,links)).join('<br>')+'</p>';
  }
  return out;
 }
 return (source,links={})=>render(source,0,links);
})();
