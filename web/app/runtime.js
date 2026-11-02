'use strict';
let apiBusy=false;
let applicationReady=false;
let refreshingRuntime=false;
async function appApi(path,body){
 const response=await fetch('/api/app/'+path,{cache:'no-store',signal:AbortSignal.timeout(8000),...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
 const data=await response.json();if(!response.ok)throw new Error(data.error||'Application request failed.');return data;
}
function applyWorkspace(data){
 const old=new Map(workspace.zones.map(z=>[z.id,z]));
 workspace=data.workspace;
 for(const z of workspace.zones){const previous=old.get(z.id);z.step=z.connected?Math.min(previous?.step||2,z.configured?3:2):1;}
 applicationReady=true;dirtyFlag=false;render();
}
async function saveWorkspace(quiet=false){
 if(apiBusy||!applicationReady)return false;apiBusy=true;
 try{applyWorkspace(await appApi('workspace',workspace));if(!quiet)toast('Workspace saved by the application service.');return true;}
 catch(error){toast(error.message);return false;}finally{apiBusy=false;}
}
async function createZone(){
 if(apiBusy||!applicationReady)return;apiBusy=true;
 try{if(dirtyFlag){applyWorkspace(await appApi('workspace',workspace));}const data=await appApi('zones',{name:'New zone'});const id=data.workspace.zones.at(-1).id;applyWorkspace(data);location.hash='zone/'+id;}
 catch(error){toast(error.message);}finally{apiBusy=false;}
}
async function connectCamera(z){
 if(!await saveWorkspace(true))return;apiBusy=true;
 try{applyWorkspace(await appApi('zones/'+z.id+'/connect',{}));toast('Camera connected. Frames come from the camera service.');}
 catch(error){toast(error.message);await refreshStatus(true);}finally{apiBusy=false;}
}
async function disconnectCamera(z){
 if(apiBusy)return;apiBusy=true;
 try{applyWorkspace(await appApi('zones/'+z.id+'/disconnect',{}));}
 catch(error){toast(error.message);}finally{apiBusy=false;}
}
async function refreshStatus(force=false){
 if(refreshingRuntime||apiBusy&&!force)return;refreshingRuntime=true;
 try{
  const data=await appApi('workspace');
  if(!applicationReady){applyWorkspace(data);return;}
  for(const z of workspace.zones){const remote=data.workspace.zones.find(r=>r.id===z.id);if(remote){z.runtime=remote.runtime;z.connected=remote.connected;z.configured=remote.configured;}}
  // Keep draft inputs and polygon handles stable while editing.
  if(!dirtyFlag&&(current()?.step===3||!location.hash.startsWith('#zone/')))render();
 }catch(error){for(const z of workspace.zones){z.connected=false;z.runtime={state:'Unknown',valid:false,value:null,reason:'Application unavailable. Last values are not current.'};}if(applicationReady&&current()?.step!==2)render();$('saved').textContent='Application offline';}
 finally{refreshingRuntime=false;}
}
// Each image refresh waits for completion before asking for another frame.
// Removed DOM nodes never schedule another request. No browser frame queue.
function nextFrame(image,delay){setTimeout(()=>{if(!image.isConnected)return;image.setAttribute('href','/api/app/zones/'+encodeURIComponent(image.dataset.zone)+'/snapshot?t='+Date.now());},delay);}
document.addEventListener('load',event=>{const image=event.target;if(!image.matches?.('.camera-frame'))return;const badge=image.closest('.scene-wrap').querySelector('.frame-state');if(badge)badge.textContent='Camera frame received';nextFrame(image,250);},true);
document.addEventListener('error',event=>{const image=event.target;if(!image.matches?.('.camera-frame'))return;image.removeAttribute('href');const badge=image.closest('.scene-wrap')?.querySelector('.frame-state');if(badge)badge.textContent='Camera unavailable · last frame must not be used';nextFrame(image,1000);},true);
refreshStatus().finally(()=>setInterval(()=>refreshStatus(),1500));
