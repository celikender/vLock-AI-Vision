'use strict';
// Setup page. Secrets are sent to the local server once and never come back: the page only learns "saved" or "not set".
let setupData=null;
const SAM_ENGINES={local:'Local GPU (NVIDIA, 8 GB or more)',meta_api:'Meta Model API, image (no GPU, one frame per check)',meta_api_video:'Meta Model API, video (no GPU, four frames per check, tracks objects)'};
function secretField(label,name,hint){
 const f=setupData.fields[name];
 const state=f.overridden?'Set outside .env':f.set?'Saved':'Not set';
 const remove=f.set&&!f.overridden?`<button class="button small quiet" data-action="setup-clear" data-name="${name}">Remove saved</button>`:'';
 return `<label>${label} <small class="setup-state ${f.set?'is-set':''}">${state}</small><input data-setup="${name}" type="password" autocomplete="new-password" spellcheck="false" placeholder="${f.set?'Leave empty to keep the saved value':'Paste here'}" ${f.overridden||!setupData.writable?'disabled':''}><small>${hint}</small></label>${remove}`;
}
function setupForm(){
 if(!setupData)return '<p class="helper">Only an admin can see the setup page.</p>';
 const f=setupData.fields,disabled=setupData.writable?'':'disabled',backend=f.VLOCK_SAM_BACKEND;
 const options=Object.entries(SAM_ENGINES).map(([value,label])=>`<option value="${value}" ${value===backend.value?'selected':''}>${esc(label)}</option>`).join('');
 const docker=setupData.writable?'':'<p class="helper"><b>Docker:</b> edit <code>.env</code> on the host, then run <code>docker compose up -d</code>. This page is read-only here.</p>';
 const restart=setupData.restartNeeded?`<p class="setup-restart"><b>Restart needed.</b> This app is running with ${esc(SAM_ENGINES[setupData.activeBackend]||setupData.activeBackend)}. Close its window and start it again to switch.</p>`:'';
 const hint=backend.value==='meta_api'?'Camera frames are sent to Meta. Each frame and object is one billed request: up to about $9 an hour per object while monitoring runs.':backend.value==='meta_api_video'?'Camera frames are sent to Meta. Each check and object is billed for at least 50 frames, about $0.01. The request limit is at least 6 seconds.':'Runs on this PC and camera frames stay here. Needs the local SAM runtime and approved Hugging Face access: see the install guide.';
 return docker+restart
 +panel('SAM 3.1 engine',`<label>Engine<select data-setup="VLOCK_SAM_BACKEND" ${backend.overridden?'disabled':''} ${disabled}>${options}</select><small>${hint}</small></label>
 <label>Request limit, ms<input data-setup="VLOCK_SAM_TIMEOUT_MS" type="number" min="500" max="30000" value="${esc(f.VLOCK_SAM_TIMEOUT_MS.value)}" ${disabled}><small>Meta Model API only. A slower answer makes the zone Unknown.</small></label>
 <label>Daily spending limit, USD<input data-setup="VLOCK_SAM_DAILY_LIMIT_USD" type="number" min="0.01" max="10000" step="0.01" value="${esc(f.VLOCK_SAM_DAILY_LIMIT_USD.value)}" ${disabled}><small>Meta Model API only. At the limit, paid requests stop and the zone goes Unknown until midnight UTC. ${samStatus?.backend?`Estimated today: $${esc(Number(samStatus.spend_today||0).toFixed(2))}. `:''}This is an estimate: your Meta account shows the real bill.</small></label>`)
 +panel('Meta Model API',secretField('API key','META_API_KEY','Used by Muse Spark, and by SAM 3.1 when the engine is the Meta Model API. It takes effect without a restart.')
 +btn('Test saved key','setup-test','small')+'<p class="helper" id="setup-test-result"></p>')
 +panel('OPC UA network access',`<p class="helper">Only needed when SCADA runs on another PC. Choose the access mode under Integrations.</p><label>Username<input data-setup="VLOCK_OPCUA_SERVER_USERNAME" autocomplete="off" spellcheck="false" value="${esc(f.VLOCK_OPCUA_SERVER_USERNAME.value)}" ${disabled}></label>`
 +secretField('Password','VLOCK_OPCUA_SERVER_PASSWORD','12 or more characters.'))
 +panel('SCADA REST API',secretField('Token','VLOCK_API_TOKEN','Optional. When set, REST clients must send it as a Bearer token.'))
 +(setupData.writable?btn('Save setup','setup-save','primary'):'');
}
function setupPage(){return heading('Setup','API keys and the SAM engine. Saved in the .env file on this PC, never shown again and never sent to the browser.')+`<div class="settings-width" id="setup-form">${setupForm()}</div>`;}
function showSetup(){const holder=document.getElementById('setup-form');if(holder)patchMarkup(holder,setupForm());}
async function loadSetup(){setupData=await adminGet('config');showSetup();}
async function setupPost(path,body){
 const response=await fetch('/api/app/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
 const data=await response.json();if(!response.ok)throw new Error(data.error||'Setup request failed.');return data;
}
document.addEventListener('click',async event=>{
 const target=event.target.closest('[data-action]');if(!target||!target.dataset.action.startsWith('setup-'))return;
 event.preventDefault();
 const action=target.dataset.action;
 try{
  if(action==='setup-save'){
   const values={};document.querySelectorAll('[data-setup]').forEach(input=>{if(!input.disabled)values[input.dataset.setup]=input.value;});
   setupData=await setupPost('config',{values});showSetup();toast('Setup saved.');
  }
  if(action==='setup-clear'&&confirm('Remove this saved value?')){setupData=await setupPost('config',{clear:[target.dataset.name]});showSetup();toast('Removed.');}
  if(action==='setup-test'){
   const result=document.getElementById('setup-test-result');result.textContent='Asking Meta…';
   const data=await setupPost('config/test-meta',{});
   result.textContent=`Key accepted. ${data.samModel}: ${data.sam?'available':'NOT available'}. ${data.museModel}: ${data.muse?'available':'NOT available'}.`;
  }
 }catch(error){
  const result=action==='setup-test'&&document.getElementById('setup-test-result');
  if(result)result.textContent=error.message;else toast(error.message);
 }
});
window.addEventListener('hashchange',()=>{if(location.hash==='#setup')loadSetup();});
window.addEventListener('DOMContentLoaded',()=>{if(location.hash==='#setup')loadSetup();});
