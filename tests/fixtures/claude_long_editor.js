// A large synthetic review with real WebKit contenteditable semantics.
const requireState=(value,label)=>{if(!value)throw Error(label);};
document.documentElement.dataset.twosFixtureProvider='Claude';
document.body.innerHTML='<main><div data-testid="composer"><div role="textbox" contenteditable="true" style="white-space:pre-wrap"></div><button aria-label="Send">Send</button></div><button data-testid="accounts-profile-button">Account</button></main>';
const editor=document.querySelector('[contenteditable=true]');
const send=document.querySelector('[aria-label=Send]');
let clicks=0,editEvents=0,oversizeEdits=0;
editor.addEventListener('input',event=>{
 editEvents++;
 if((event.data?.length||0)>1024 || event.inputType==='insertFromPaste'){
  oversizeEdits++;editor.textContent='';addPaste();
 }
});
function addPaste(){
 const chip=document.createElement('button');
 chip.setAttribute('aria-label','移除 粘贴的文本, 已粘贴, 1 行');
 editor.parentElement.append(chip);return chip;
}
send.onclick=()=>{clicks++;};
const request={provider:'Claude',id:'qa-long',targetURL:location.href,teamReview:true,teamWireVersion:1,allowTeamMode:true,
 text:'Office study  𠮷 and 123\n'.repeat(4500),draftOnly:true};
const expected='[TWOS handoff qa-long] '+JSON.stringify({instruction:request.text});
const draft=await transfer(request);
requireState(draft.state==='draft' && draft.reason==='EXACT_DRAFT_CONFIRMED_NO_MESSAGE_SENT' && editor.innerText===expected,'Exact long draft '+JSON.stringify(draft));
requireState(editEvents>100 && !oversizeEdits && !clicks,'Editing side effects');
editor.textContent='';
const chip=addPaste();
const inspection=await transfer({...request,inspectOnly:true,inspectRetainedDraft:true});
requireState(inspection.state==='retained_attachment','Pasted document must be preserved '+JSON.stringify(inspection));
const blocked=await transfer(request);
requireState(blocked.state==='draft_conflict' && chip.isConnected && !editor.innerText && !clicks,'Foreign attachment protection');
chip.remove();
const bytes=new TextEncoder().encode(request.text);
const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
const file={id:request.id,name:'TWOS-instruction-'+request.id+'.txt',size:bytes.length,mime:'text/plain',hash,base64:btoa(Array.from(bytes,b=>String.fromCharCode(b)).join(''))};
const wire={...request,teamWireVersion:2,hash,files:[file]};
const upload=document.createElement('input');
upload.type='file';editor.parentElement.append(upload);
let captured=null;
upload.onchange=async()=>{
 captured=new Uint8Array(await upload.files[0].arrayBuffer());
 const card=document.createElement('button');
 card.setAttribute('aria-label',file.name+', document');editor.parentElement.append(card);
};
const first=await transfer(wire);
requireState(first.reason==='EXACT_DRAFT_CONFIRMED_NO_MESSAGE_SENT' && captured?.length===bytes.length &&
 captured.every((byte,i)=>byte===bytes[i]) && editor.innerText.includes(hash) && editor.innerText.length<300 && !clicks,'Exact document upload '+JSON.stringify(first));
const cover=editor.innerText, msg=document.createElement('div');
msg.dataset.testid='user-message';msg.textContent=cover;document.querySelector('main').prepend(msg);
const unverified=await transfer({...wire,inspectOnly:true});
requireState(unverified.state==='unknown','Missing sent attachment');
const sentFile=document.createElement('button');sentFile.setAttribute('aria-label',file.name);msg.prepend(sentFile);
const turn=document.createElement('article');msg.before(turn);turn.append(sentFile,msg);
const confirmed=await transfer({...wire,inspectOnly:true});
requireState(confirmed.state==='sent' && !clicks,'Exact cover and file in original user turn '+JSON.stringify(confirmed));
const different=document.createElement('div');different.dataset.testid='user-message';different.textContent='separate turn';turn.prepend(different);
requireState((await transfer({...wire,inspectOnly:true})).state==='unknown','Different user turn does not supply the file');
// ChatGPT renders a sent file card beside its user bubble. The short cover
// and exact document bytes use the same immutable native manifest.
document.documentElement.dataset.twosFixtureProvider='ChatGPT';
turn.remove();editor.textContent='';editor.id='prompt-textarea';
for(const b of editor.parentElement.querySelectorAll('button'))if(b!==send)b.remove();
captured=null;
const other={...wire,id:'qa-gpt',provider:'ChatGPT',files:[{...file,id:'qa-gpt',name:'TWOS-instruction-qa-gpt.txt'}]};
upload.onchange=async()=>{
 const f=upload.files[0];captured=new Uint8Array(await f.arrayBuffer());
 const button=document.createElement('button');button.setAttribute('aria-label',f.name);editor.parentElement.append(button);
};
const result=await transfer(other);
requireState(result.reason==='EXACT_DRAFT_CONFIRMED_NO_MESSAGE_SENT' && captured?.length===bytes.length && editor.innerText.endsWith(hash),'ChatGPT document draft '+JSON.stringify(result));
const posted=document.createElement('article'), text=document.createElement('div'), card=document.createElement('button');
text.dataset.userMessageBubble='';text.textContent=editor.innerText;card.setAttribute('aria-label',other.files[0].name);
posted.append(card,text);document.querySelector('main').prepend(posted);
requireState((await transfer({...other,inspectOnly:true})).state==='sent' && !clicks,'ChatGPT receipt with exact attachment');
return 'matched';
