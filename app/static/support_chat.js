(()=>{
const panel=document.getElementById('supportChat');if(!panel)return;
document.body.append(panel);
const staff=panel.dataset.staff==='1',base=staff?'/admin-console/chat':'/support/chat';
const list=document.getElementById('chatMessages'),body=document.getElementById('chatBody'),status=document.getElementById('chatStatus'),older=document.getElementById('chatOlder');
let tid=0,version=0,last=0,first=0,busy=false,sending=false,rows=[],seenUnread=0,nonce='',draft='',drafts={};
const badge=document.getElementById('supportChatBadge');
async function api(path,data){const r=await fetch(base+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/x-www-form-urlencoded'}:{},body:data?new URLSearchParams(data):undefined});if(!r.ok||r.redirected)throw Error('เชื่อมต่อไม่ได้ กรุณาลองอีกครั้ง หรือเข้าสู่ระบบใหม่');return r.json();}
function notify(n){if(badge){badge.hidden=!n;badge.textContent=n>99?'99+':n;}if(n>seenUnread&&panel.hidden&&window.showToast)window.showToast('มีข้อความใหม่จากเจ้าหน้าที่ กดไอคอนแชทเพื่ออ่าน');seenUnread=n;}
function render(m,prepend=false){if(document.getElementById('chat-msg-'+m.id))return;const box=document.createElement('div');box.id='chat-msg-'+m.id;box.className='chat-message'+(m.mine?' mine':'');const meta=document.createElement('small');meta.textContent=(m.staff?'เจ้าหน้าที่ · ':'')+m.sender+' · '+new Date(m.time).toLocaleString('th-TH');const text=document.createElement('div');text.textContent=m.body;box.append(meta,text);prepend?list.prepend(box):list.append(box);}
async function read(){if(!last||panel.hidden||document.hidden)return;try{await api('/read',{tenant_id:tid,last_id:last});notify(0);}catch{}}
async function load(previous=false){if(busy)return;busy=true;const current=version;try{const atBottom=list.scrollHeight-list.scrollTop-list.clientHeight<60;const data=await api('/messages?tenant_id='+tid+(previous?'&before='+first:last?'&after='+last:''));if(current!==version)return;
const initial=!first,height=list.scrollHeight;if(previous)data.messages.slice().reverse().forEach(m=>render(m,true));else data.messages.forEach(m=>render(m));
if(data.messages.length){first=first?Math.min(first,data.messages[0].id):data.messages[0].id;last=Math.max(last,data.messages.at(-1).id);}
if(previous)list.scrollTop+=list.scrollHeight-height;else if(atBottom)list.scrollTop=list.scrollHeight;
if(previous||initial)older.hidden=!data.more;status.textContent=last?'':'ยังไม่มีข้อความ เริ่มพิมพ์สอบถามได้เลย';notify(data.unread);
if(!previous&&atBottom)await read();
}catch(e){if(current===version)status.textContent=e.message;}finally{busy=false;}}
async function open(id=0,name='แชทติดต่อเจ้าหน้าที่'){
if(sending)return;drafts[tid]=body.value;tid=id;version++;last=0;first=0;list.replaceChildren();body.value=drafts[tid]||'';nonce='';draft='';older.hidden=true;document.getElementById('chatTitle').textContent=name;panel.hidden=false;status.textContent='กำลังโหลด…';
// An older request may still be returning from another school.
while(busy)await new Promise(r=>setTimeout(r,30));await load();body.focus();}
document.getElementById('supportChatOpen')?.addEventListener('click',()=>open());
document.querySelectorAll('[data-open-support-chat]').forEach(b=>b.addEventListener('click',()=>open()));
document.getElementById('chatClose').onclick=()=>{panel.hidden=true;document.getElementById('supportChatOpen')?.focus();};
panel.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('chatClose').click();});
older.onclick=()=>load(true);
document.getElementById('chatForm').addEventListener('submit',async e=>{e.preventDefault();if(sending||!body.value.trim())return;sending=true;const button=document.getElementById('chatSend');button.disabled=true;body.disabled=true;const text=body.value.trim();if(text!==draft||!nonce){draft=text;nonce=crypto.randomUUID?crypto.randomUUID():Date.now()+'-'+Math.random();}
try{await api('/send',{tenant_id:tid,body:text,nonce});body.value='';drafts[tid]='';nonce='';status.textContent='ส่งแล้ว';await load();list.scrollTop=list.scrollHeight;await read();}catch(e){status.textContent=e.message+' · ข้อความยังอยู่ กดส่งเพื่อลองใหม่';}finally{sending=false;button.disabled=false;body.disabled=false;body.focus();}});
function showInbox(){const target=document.getElementById('chatInbox'),q=document.getElementById('chatSearch').value.trim().toLowerCase();target.replaceChildren();rows.filter(r=>r.name.toLowerCase().includes(q)).forEach(r=>{const b=document.createElement('button'),title=document.createElement('strong'),preview=document.createElement('small');title.textContent=r.name+(r.unread?' · ยังไม่อ่าน '+r.unread:'');preview.textContent=r.preview||'เริ่มบทสนทนา';b.append(title,preview);b.onclick=()=>open(r.id,r.name);target.append(b);});}
async function inbox(){try{const r=await fetch('/admin-console/chat/inbox');if(!r.ok||r.redirected)throw Error();rows=await r.json();showInbox();document.getElementById('inboxStatus').textContent=rows.length?'':'ยังไม่มีโรงเรียน';}catch{document.getElementById('inboxStatus').textContent='โหลดรายชื่อไม่ได้ กรุณาลองใหม่';}}
if(staff){document.getElementById('chatSearch').oninput=showInbox;inbox();}
async function poll(){if(document.hidden)return;if(staff)await inbox();if(!panel.hidden)await load();else if(!staff){try{notify((await api('/messages?summary=true')).unread);}catch{}}}
poll();setInterval(poll,15000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
})();
