'use strict';
// Signed-in user, users and audit (admin) and OPC UA client trust (admin). The server enforces every role.
let session={user:null,role:null};
let adminData={users:[],entries:[],clients:{pending:[],trusted:[]}};
const roleRank=role=>['viewer','operator','admin'].indexOf(role);
function canDo(role){return roleRank(session.role)>=roleRank(role);}
function sessionBadge(){return session.user?`<div class="session-badge"><span>${esc(session.user)} · ${esc(session.role)}</span><button class="button small quiet" data-action="logout">Log out</button></div>`:'';}
function renderSession(){const host=document.querySelector('.sidebar');if(!host)return;let badge=host.querySelector('.session-slot');if(!badge){badge=document.createElement('div');badge.className='session-slot';host.appendChild(badge);}patchMarkup(badge,sessionBadge());}
async function adminGet(path){const response=await fetch('/api/app/'+path,{cache:'no-store'});if(response.status===401){location.replace('/login');return null;}if(!response.ok)return null;return response.json();}
async function refreshAdmin(){
 if(!canDo('admin'))return;
 const [users,audit,clients]=await Promise.all([adminGet('users'),adminGet('audit'),adminGet('opcua/clients')]);
 if(users)adminData.users=users.users;if(audit)adminData.entries=audit.entries;if(clients)adminData.clients=clients;
 const panel=document.getElementById('admin-panel');if(panel)patchMarkup(panel,adminPanel());
 const trust=document.getElementById('opc-clients');if(trust)patchMarkup(trust,clientPanel());
}
function adminPanel(){
 if(!canDo('admin'))return `<p class="helper">Signed in as ${esc(session.user||'')} (${esc(session.role||'')}). Users and the audit log are managed by an admin.</p>`;
 const users=adminData.users.map(u=>`<tr><td>${esc(u.username)}</td><td>${esc(u.role)}</td><td>${u.username===session.user?'<small>you</small>':`<button class="button small quiet" data-action="user-delete" data-user="${esc(u.username)}">Delete</button>`}</td></tr>`).join('');
 const entries=adminData.entries.slice(0,40).map(e=>`<tr><td><small>${esc(e.time)}</small></td><td>${esc(e.user)}</td><td>${esc(e.action)}</td><td>${esc(e.target)}</td><td>${esc(e.result)}</td><td><small>${esc(e.detail)}</small></td></tr>`).join('');
 return `<table><thead><tr><th>USER</th><th>ROLE</th><th></th></tr></thead><tbody>${users}</tbody></table>
 <div class="admin-form"><div class="field-pair"><label>New username<input id="new-user" maxlength="32" autocomplete="off"></label><label>Role<select id="new-role"><option>viewer</option><option>operator</option><option>admin</option></select></label></div>
 <label>Password<input id="new-password" type="password" maxlength="200" autocomplete="new-password"><small>10+ characters. Viewer reads; operator also connects cameras and switches monitoring; admin also configures.</small></label>${btn('Add user','user-add','small')}</div>
 <div class="admin-form"><label>Change my password<input id="my-password" type="password" maxlength="200" autocomplete="new-password"></label>${btn('Change password','password-change','small')}</div>
 <h3 class="admin-heading">Audit log · latest 40 of ${adminData.entries.length}</h3><div class="tag-table-wrap"><table class="tag-table"><thead><tr><th>TIME (UTC)</th><th>USER</th><th>ACTION</th><th>TARGET</th><th>RESULT</th><th>DETAIL</th></tr></thead><tbody>${entries||'<tr><td colspan="6">No entries yet.</td></tr>'}</tbody></table></div>`;
}
function clientPanel(){
 if(!canDo('admin'))return '<p class="helper">An admin approves which SCADA clients may connect in Network mode.</p>';
 const row=(c,state)=>`<tr><td>${esc(c.name||'(no name)')}<small>${esc(c.application_uri)}</small></td><td><small>${esc(c.id)}</small></td><td>${state==='pending'?btn('Trust','client-trust','small primary','data-client="'+esc(c.id)+'"'):''} <button class="button small quiet" data-action="client-remove" data-client="${esc(c.id)}">Remove</button></td></tr>`;
 const pending=adminData.clients.pending.map(c=>row(c,'pending')).join(''),trusted=adminData.clients.trusted.map(c=>row(c,'trusted')).join('');
 return `<p class="helper">Network mode accepts only client certificates trusted here. A refused SCADA client appears under Waiting; compare its SHA-1 with the client's own certificate before trusting it.</p>
 <table><thead><tr><th>WAITING CLIENT</th><th>SHA-1</th><th></th></tr></thead><tbody>${pending||'<tr><td colspan="3">None</td></tr>'}</tbody></table>
 <table><thead><tr><th>TRUSTED CLIENT</th><th>SHA-1</th><th></th></tr></thead><tbody>${trusted||'<tr><td colspan="3">None</td></tr>'}</tbody></table>`;
}
async function adminPost(path,body,done){
 try{const data=await appApi(path,body);if(done)toast(done);await refreshAdmin();return data;}catch(error){toast(error.message);return null;}
}
document.addEventListener('click',async event=>{
 const target=event.target.closest('[data-action]');if(!target)return;const action=target.dataset.action;
 if(action==='logout'){await fetch('/api/app/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});location.replace('/login');}
 if(action==='user-add'){const ok=await adminPost('users',{username:$('new-user').value.trim(),role:$('new-role').value,password:$('new-password').value},'User added.');if(ok){$('new-user').value='';$('new-password').value='';}}
 if(action==='user-delete'&&confirm('Delete user '+target.dataset.user+'?'))await adminPost('users/delete',{username:target.dataset.user},'User deleted.');
 if(action==='password-change'){const ok=await adminPost('password',{password:$('my-password').value},'Password changed.');if(ok)$('my-password').value='';}
 if(action==='client-trust')await adminPost('opcua/clients',{id:target.dataset.client,action:'trust'},'Client trusted. It can connect on its next attempt.');
 if(action==='client-remove')await adminPost('opcua/clients',{id:target.dataset.client,action:'remove'},'Client removed.');
});
window.addEventListener('hashchange',()=>{if(['#settings','#integrations'].includes(location.hash))refreshAdmin();});
