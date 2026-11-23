const api=window.twosProviderDOM;
const assert=(condition,why)=>{if(!condition)throw Error(why);};
document.documentElement.dataset.twosFixtureProvider='Claude';
history.replaceState(null,'','/code/project/demo?thread=t1&tracking=fixture');
document.body.innerHTML=`
  <main><section id="project"><div data-testid="user-message">Project question</div>
    <div data-is-streaming="false">Private project reply</div><textarea placeholder="Ask Claude"></textarea>
    <button aria-label="Send">Send</button><button aria-label="Stop">Stop</button></section>
  <aside id="thread"><div data-testid="user-message">Discussion question</div>
    <div data-is-streaming="false" data-message-id="discussion-1">Discussion reply</div>
    <form><textarea placeholder="引导此讨论串…"></textarea><button type="button" aria-label="Send">Send</button></form></aside></main>`;
const project=document.querySelector('#project'),thread=document.querySelector('#thread');
project.querySelector('textarea').value='Project draft';
let sends=0;
thread.querySelector('button').onclick=()=>{
  sends++;
  const editor=thread.querySelector('textarea'),u=document.createElement('p'),r=document.createElement('p');
  u.dataset.testid='user-message';u.textContent=editor.value;editor.value='';
  r.dataset.isStreaming='false';r.dataset.messageId='reply-'+sends;r.textContent='Fixture reply '+sends;
  thread.querySelector('form').before(u,r);
};
project.querySelector('button').onclick=()=>{throw Error('Project composer was used');};
const stop=document.createElement('button');stop.setAttribute('aria-label','Stop');thread.append(stop);
assert(api.observe().state==='running' && api.isStop(stop) && !api.isStop(project.querySelector('[aria-label=Stop]')),'scope stop and generation');
stop.remove();
const url=api.conversationURL(location.href);
const request={provider:'Claude',targetURL:url,id:'discussion-1',text:'Synthetic discussion handoff'};
assert(api.conversationScope()===thread && api.latest().text==='Discussion reply','wrong source scope');
for(let i=1;i<=2;i++){
  const op={...request,id:'discussion-'+i,text:'Synthetic discussion handoff '+i};
  const reply=await transfer(op);
  assert(reply.state==='reply' && reply.reply==='Fixture reply '+i && reply.conversationURL===url,'wrong response '+reply.state);
  assert((await transfer({...op,inspectOnly:true})).state==='reply' && sends===i,'inspection replay');
}
assert(project.querySelector('textarea').value==='Project draft','project draft changed');
history.replaceState(null,'','?thread=t2');
assert(!api.composerSelection().element,'old editor survived a route switch');
assert(['target_changed','not_loaded'].includes((await transfer({...request,inspectOnly:true})).state),'cross-thread receipt');
history.replaceState(null,'','?thread=t1');
thread.querySelector('textarea').removeAttribute('placeholder');
assert(!api.composerSelection().element && (await transfer(request)).state==='not_loaded','unidentified scope');
return 'matched';
