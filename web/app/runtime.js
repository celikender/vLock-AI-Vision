'use strict';
let diagnostics={};
let capabilities={};
let samStatus=null;
let adapters={};
let apiBusy=false;
let applicationReady=false;
let refreshingRuntime=false;
async function appApi(path,body,timeout=8000){
 const response=await fetch('/api/app/'+path,{cache:'no-store',signal:AbortSignal.timeout(timeout),...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
 if(response.status===401){location.replace('/login');throw new Error('Log in to continue.');}
 const data=await response.json();if(!response.ok)throw new Error(data.error||'Application request failed.');return data;
}
const shownNotices=new Set();
function showNotices(notices){
 // Recovery notices (damaged files kept aside) stay on screen longer than ordinary toasts.
 for(const notice of notices||[]){if(shownNotices.has(notice))continue;shownNotices.add(notice);toast(notice);clearTimeout(timer);timer=setTimeout(()=>$('toast').hidden=true,15000);}
}
function applySession(data){if(!data.session)return;const changed=data.session.role!==session.role;session=data.session;renderSession();if(changed)refreshAdmin();}
function applyWorkspace(data){
 showNotices(data.notices);applySession(data);
 const previous=new Map(workspace.zones.map(z=>[z.id,z]));
 diagnostics=data.diagnostics||diagnostics;
 capabilities=data.capabilities||capabilities;
 samStatus=data.sam??samStatus;
 adapters=data.integrations||adapters;
 workspace=data.workspace;
 for(const z of workspace.zones){z.step=2;const old=previous.get(z.id);for(const key of ['showArea','guideExpanded','sourceExpanded','helperQuestion','preview'])if(old&&key in old)z[key]=old[key];}
 applicationReady=true;dirtyFlag=false;render();
}
async function saveWorkspace(quiet=false){
 if(apiBusy||!applicationReady)return false;
 // Only an admin changes configuration; operators continue with the saved workspace.
 if(!canDo('admin')){if(!quiet)toast('Your role ('+session.role+') cannot change the configuration.');return !dirtyFlag||quiet;}
 apiBusy=true;
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
async function configureZone(z){
 if(!z.areaSelected)return toast('Draw and select an area first.');
 if(!await saveWorkspace(true))return;
 apiBusy=true;
 try{applyWorkspace(await appApi('zones/'+z.id+'/configure',{}));const zone=workspace.zones.find(item=>item.id===z.id);zone.step=2;render();toast('Zone rule saved. Enable monitoring to start local SAM.');}
 catch(error){toast(error.message);}finally{apiBusy=false;}
}
async function restartSam(){
 try{const data=await appApi('sam/restart',{});samStatus=data.sam;refreshZoneControls();toast('Starting the SAM worker…');}
 catch(error){toast(error.message);}
}
async function setMonitoring(z,enabled){
 if(apiBusy||!z)return;apiBusy=true;
 try{applyWorkspace(await appApi('zones/'+z.id+'/enable',{enabled}));}
 catch(error){toast(error.message);await refreshStatus(true);}finally{apiBusy=false;}
}
async function refreshStatus(force=false){
 if(refreshingRuntime||apiBusy&&!force)return;refreshingRuntime=true;
 try{
  const data=await appApi('workspace');
  applySession(data);
  diagnostics=data.diagnostics||diagnostics;
  samStatus=data.sam??samStatus;
  adapters=data.integrations||adapters;
  if(!applicationReady){applyWorkspace(data);return;}
  for(const z of workspace.zones){const remote=data.workspace.zones.find(r=>r.id===z.id);if(remote){z.tag_path=remote.tag_path;z.runtime=remote.runtime;z.connected=remote.connected;z.localEnabled=remote.localEnabled;z.events=remote.events;if(!dirtyFlag)z.configured=remote.configured;}}
  // Keep draft inputs and polygon handles stable while editing.
  if(location.hash.startsWith('#zone/'))refreshZoneResults();else if(['#outputs','#integrations','#system'].includes(location.hash)){await refreshOutputSnapshot();refreshConnectionViews();}else if(!dirtyFlag)render();
 }catch(error){for(const z of workspace.zones){z.connected=false;z.runtime={state:'Unknown',valid:false,value:null,reason:'Application unavailable. Last values are not current.'};}outputSnapshot=null;outputReadState='Local API unavailable · values are not current';if(applicationReady){if(location.hash.startsWith('#zone/'))refreshZoneResults();else if(['#outputs','#integrations','#system'].includes(location.hash))refreshConnectionViews();else render();}$('saved').textContent='Application offline';}
 finally{refreshingRuntime=false;}
}
// Observe rendered previews and cancel their fetch when a view is removed.
const previewPumps=new Map();
function syncCameraPreviews(){
 for(const [image,pump] of previewPumps){if(!image.isConnected){pump.stop();previewPumps.delete(image);}}
 for(const image of document.querySelectorAll('.camera-frame')){
  if(previewPumps.has(image))continue;
  const pump=createCameraPreview(image,{onFrame:(connected,metrics)=>{const z=workspace.zones.find(item=>item.id===image.dataset.zone);if(z)z.preview={connected,...metrics};}});
  previewPumps.set(image,pump);
 }
}
new MutationObserver(syncCameraPreviews).observe(document.documentElement,{childList:true,subtree:true});
syncCameraPreviews();
refreshStatus().finally(()=>setInterval(()=>refreshStatus(),1500));

let analyzedView=null,analyzedElement=null;
function syncAnalyzedPreview(){
 const image=document.querySelector('[data-analyzed-zone]');
 if(image!==analyzedElement){analyzedView?.stop();analyzedView=null;analyzedElement=image;if(image)analyzedView=createAnalyzedPreview(image,{onStatus:message=>{const caption=document.querySelector('[data-analyzed-caption]');if(caption)caption.textContent=message;}});}
 if(image){const z=workspace.zones.find(item=>item.id===image.dataset.analyzedZone);const id=z?.runtime?.output_id;analyzedView.update(id?'/api/app/zones/'+encodeURIComponent(z.id)+'/analyzed?output='+id:null);}
}
new MutationObserver(()=>{if(document.querySelector('[data-analyzed-zone]')!==analyzedElement)syncAnalyzedPreview();}).observe(document.documentElement,{childList:true,subtree:true});
syncAnalyzedPreview();
