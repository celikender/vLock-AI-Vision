'use strict';
const $=id=>document.getElementById(id);
let status=null, points=[], zoneSize=null, drawing=false, drag=-1, liveImage=null;
let previewBusy=false, cameraHealthy=false, busy=false, dirty=false, resultKey='', renderToken=0;
let toastTimer;

function message(text,error=false){
  $('message').textContent=text;$('message').classList.toggle('error',error);$('message').hidden=false;
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('message').hidden=true,6500);
}
function markDirty(){dirty=true;$('saveState').textContent='Unsaved changes';summary();}
function summary(){
  const target=$('target').value.trim()||'Object', zone=$('zoneName').value.trim()||'the zone';
  const condition={mask_overlaps_zone:'overlaps',mask_inside_zone:'is inside',object_absent:'is absent from'}[$('condition').value];
  $('summary').textContent=`${target} ${condition} ${zone} → ${$('action').value==='warning'?'Trigger warning event':'Record event'}`;
  $('zoneLabel').textContent=points.length?`${zone} · ${points.length} vertices`:'No monitoring zone';
  $('finish').disabled=!drawing||points.length<3||busy||!!status?.busy;
  $('overlap').disabled=busy||!!status?.busy||$('condition').value==='mask_inside_zone';
}
function hydrate(config){
  $('cameraName').value=config.camera.name;$('cameraUrl').value=config.camera.url;
  $('target').value=config.sam_prompt;$('zoneName').value=config.zone.name;
  $('condition').value=config.rule.condition;$('overlap').value=config.rule.min_overlap_ratio*100;
  $('duration').value=config.rule.persistence_seconds;$('action').value=config.rule.action;
  points=config.zone.polygon.map(p=>p.slice());zoneSize=config.zone.frame_size?.slice()||null;
  dirty=false;drawing=false;$('drawBadge').hidden=true;
  $('saveState').textContent='Configuration is saved on this PC.';
  $('credentialsHint').textContent=config.camera.credentials_configured?'Credentials saved. Leave the fields blank to keep them.':'No saved credentials.';
  summary();drawLive();
}
function payload(){
  return {camera:{name:$('cameraName').value,url:$('cameraUrl').value,
    username:$('username').value,password:$('password').value,clear_credentials:$('clearCredentials').checked},
    sam_prompt:$('target').value,zone:{name:$('zoneName').value,polygon:points,frame_size:zoneSize},
    rule:{condition:$('condition').value,min_overlap_ratio:Number($('overlap').value)/100,
      persistence_seconds:Number($('duration').value),action:$('action').value}};
}
async function post(action,data){
  const response=await fetch('/api/monitoring/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:AbortSignal.timeout(12000)});
  const value=await response.json();if(!response.ok)throw Error(value.error||'Request failed.');return value;
}
async function control(operation){
  if(busy)return;busy=true;controls();
  try{await operation();}catch(error){message(error.message,true);}finally{busy=false;controls();}
}
function controls(){
  const locked=busy||!!status?.busy;
  for(const id of ['cameraName','cameraUrl','username','password','clearCredentials','zoneName','condition','duration','action','connect','save'])$(id).disabled=locked;
  for(const id of ['draw','undo','clearZone'])$(id).disabled=locked||!cameraHealthy;
  $('canvasDraw').disabled=locked||!cameraHealthy;
  $('canvasDraw').hidden=drawing;$('canvasFinish').hidden=!drawing;
  $('canvasFinish').disabled=locked||points.length<3;
  $('finish').disabled=locked||!drawing||points.length<3;
  $('target').disabled=busy||!!status?.busy&&!status?.running;
  $('applyPrompt').hidden=!status?.running;$('applyPrompt').disabled=busy;
  $('startMonitoring').hidden=!!status?.running;
  $('startMonitoring').disabled=locked||!status?.connected||points.length<3||drawing;
  $('stopMonitoring').hidden=!status?.running;$('stopMonitoring').disabled=busy;
  summary();
}
$('setup').addEventListener('input',markDirty);
$('setup').addEventListener('change',markDirty);
$('connect').onclick=()=>control(async()=>{
  const data=await post('connect',{camera:payload().camera});status=data;
  $('username').value='';$('password').value='';$('clearCredentials').checked=false;
  points=data.config.zone.polygon.map(p=>p.slice());zoneSize=data.config.zone.frame_size?.slice()||null;
  $('cameraMessage').textContent='Connected. Camera configuration saved.';
  $('credentialsHint').textContent=data.config.camera.credentials_configured?'Credentials saved on this PC.':'No credentials required.';
  drawing=false;show(data);message('Camera connected. Draw your monitoring zone.');
});
$('save').onclick=()=>control(async()=>{
  if(drawing)throw Error('Finish drawing the polygon before saving.');
  const data=await post('save',payload());hydrate(data.config);show(data);
  $('username').value='';$('password').value='';$('clearCredentials').checked=false;message('Monitoring setup saved.');
});
$('setup').onsubmit=event=>{event.preventDefault();control(async()=>{
  if(drawing)throw Error('Finish the polygon before starting.');
  const saved=await post('save',payload());hydrate(saved.config);
  const data=await post('start',{});show(data);$('state').scrollIntoView({behavior:'smooth',block:'center'});message('Monitoring started with local SAM. Waiting for fresh results.');
});};
$('stopMonitoring').onclick=()=>control(async()=>{show(await post('stop',{}));message('Monitoring stopped. In-flight results will be discarded.');});
$('applyPrompt').onclick=()=>control(async()=>{const data=await post('prompt',{sam_prompt:$('target').value});dirty=false;$('saveState').textContent='Target saved. The monitoring zone is unchanged.';show(data);message('Detection target updated. The saved zone is unchanged.');});
$('draw').onclick=()=>{if(!liveImage)return;points=[];zoneSize=[$('live').width,$('live').height];drawing=true;$('drawBadge').hidden=false;$('zoneHint').textContent='Click at least three points, then Finish. Drag vertices after finishing.';markDirty();controls();drawLive();$('live').scrollIntoView({behavior:'smooth',block:'center'});};
$('finish').onclick=()=>{if(points.length>=3){drawing=false;$('drawBadge').hidden=true;markDirty();controls();drawLive();}};
$('undo').onclick=()=>{points.pop();if(points.length<3)drawing=true;$('drawBadge').hidden=!drawing;markDirty();controls();drawLive();};
$('clearZone').onclick=()=>{points=[];drawing=false;zoneSize=null;$('drawBadge').hidden=true;markDirty();controls();drawLive();};
$('canvasDraw').onclick=()=>$('draw').click();$('canvasFinish').onclick=()=>$('finish').click();
function position(event){const canvas=$('live'),rect=canvas.getBoundingClientRect();return [Math.max(0,Math.min(canvas.width-1,(event.clientX-rect.left)*canvas.width/rect.width)),Math.max(0,Math.min(canvas.height-1,(event.clientY-rect.top)*canvas.height/rect.height))];}
$('live').onpointerdown=event=>{
  if(busy||status?.busy||!cameraHealthy)return;const p=position(event);
  if(drawing){if(points.length>=32)return message('A zone supports at most 32 vertices.',true);points.push(p);markDirty();controls();drawLive();}
  else{const radius=14*$('live').width/$('live').getBoundingClientRect().width;drag=points.findIndex(v=>Math.hypot(v[0]-p[0],v[1]-p[1])<radius);if(drag>=0)$('live').setPointerCapture(event.pointerId);}
};
$('live').onpointermove=event=>{if(drag<0)return;points[drag]=position(event);markDirty();drawLive();};
$('live').onpointerup=$('live').onpointercancel=()=>{drag=-1;};
function polygon(ctx,vertices,name,editing=false,closed=true){
  if(!vertices.length)return;ctx.save();ctx.beginPath();ctx.moveTo(...vertices[0]);vertices.slice(1).forEach(p=>ctx.lineTo(...p));
  if(closed&&vertices.length>=3){ctx.closePath();ctx.fillStyle='#7ee4c22b';ctx.fill();}
  ctx.strokeStyle='#7ee4c2';ctx.lineWidth=Math.max(2,ctx.canvas.width/350);if(!closed)ctx.setLineDash([7,5]);ctx.stroke();ctx.setLineDash([]);
  if(editing)for(const [x,y]of vertices){ctx.beginPath();ctx.arc(x,y,Math.max(5,ctx.canvas.width/120),0,2*Math.PI);ctx.fillStyle='#c5ffeb';ctx.fill();ctx.strokeStyle='#17382f';ctx.stroke();}
  const x=Math.min(vertices[0][0]+8,ctx.canvas.width-150),y=Math.max(18,vertices[0][1]-10);ctx.font=`${Math.max(12,ctx.canvas.width/50)}px system-ui`;ctx.fillStyle='#bcffe9';ctx.fillText(name,Math.max(5,x),y);ctx.restore();
}
function drawLive(){const canvas=$('live'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);if(liveImage)ctx.drawImage(liveImage,0,0);if(zoneSize?.[0]===canvas.width&&zoneSize?.[1]===canvas.height)polygon(ctx,points,$('zoneName').value,true,!drawing);}
async function preview(){
  if(status?.connected&&!previewBusy){previewBusy=true;
    try{const r=await fetch('/api/monitoring/snapshot',{signal:AbortSignal.timeout(3500)});if(!r.ok)throw Error();const bitmap=await createImageBitmap(await r.blob());
      liveImage?.close();liveImage=bitmap;cameraHealthy=true;const canvas=$('live');canvas.width=bitmap.width;canvas.height=bitmap.height;drawLive();
      $('placeholder').hidden=true;$('liveStatus').textContent='Live camera feed · zone editor';$('resolution').textContent=`${bitmap.width} × ${bitmap.height}`;
      if(zoneSize&&(zoneSize[0]!==bitmap.width||zoneSize[1]!==bitmap.height))$('zoneHint').textContent='Camera resolution changed. Reconnect and redraw the zone.';
    }catch(error){cameraHealthy=false;liveImage?.close();liveImage=null;drawLive();$('placeholder').hidden=false;$('placeholder').querySelector('p').textContent='Camera unavailable. Check the Pi connection.';$('liveStatus').textContent='Camera unavailable';setState('Unknown');}
    finally{previewBusy=false;controls();cameraBadge();}
  }setTimeout(preview,150);
}
function cameraBadge(){const ok=status?.connected&&cameraHealthy;$('cameraBadge').textContent=ok?'Connected':'Not connected';$('cameraBadge').classList.toggle('connected',!!ok);}
function setState(state){$('state').className='state '+state.toLowerCase();$('state').querySelector('span').textContent=state;}
function drawResult(result,config){
  const key=String(result.output_id);if(key===resultKey)return;resultKey=key;const token=++renderToken;
  const image=new Image();image.onload=()=>{
    if(token!==renderToken)return;const c=$('analyzed');c.width=result.width;c.height=result.height;const ctx=c.getContext('2d');ctx.drawImage(image,0,0);
    polygon(ctx,config.zone.polygon,config.zone.name);
    for(const obj of result.objects){if(!obj.bbox_xywh)continue;const [x,y,w,h]=obj.bbox_xywh;ctx.strokeStyle='#ffe39b';ctx.lineWidth=2;ctx.strokeRect(x*c.width,y*c.height,w*c.width,h*c.height);ctx.font=`${Math.max(12,c.width/50)}px system-ui`;ctx.fillStyle='#ffe39b';ctx.fillText(`${result.prompt} #${obj.object_id}${obj.score===null?'':' · '+obj.score.toFixed(2)}`,Math.max(2,x*c.width+3),Math.max(16,y*c.height-6));}
    c.hidden=false;$('resultEmpty').hidden=true;
  };image.src=result.annotated_image;
}
function show(data){
  status=data;setState(data.state);cameraBadge();$('cameraTitle').textContent=data.config.camera.name;
  $('activeTarget').textContent=data.config.sam_prompt;$('reason').textContent=data.reason;
  if(data.result){const r=data.result;drawResult(r,data.config);$('objectCount').textContent=r.stale?'—':r.count;$('age').textContent=r.age_seconds.toFixed(1)+'s';
    $('resultMeta').textContent=`Frame ${r.frame_sequence} · ${r.elapsed_seconds}s window processing · ${r.peak_vram_mb} MiB peak GPU memory${r.stale?' · STALE':''} · ${r.zone_detections.map(d=>Math.round(d.overlap_ratio*100)+'% overlap').join(', ')}`;
  }else{renderToken++;resultKey='';$('analyzed').hidden=true;$('resultEmpty').hidden=false;$('objectCount').textContent='—';$('age').textContent='—';$('resultMeta').textContent='';}
  const items=data.events.slice(-20).reverse();$('eventCount').textContent=data.events.length+' events';
  $('events').replaceChildren(...items.map(e=>{const li=document.createElement('li'),dot=document.createElement('span'),body=document.createElement('div'),name=document.createElement('strong'),reason=document.createElement('p'),time=document.createElement('time');
    dot.className='event-dot '+(e.type==='warning'?'warning':'');name.textContent={warning:'Warning triggered',rule_triggered:'Rule event recorded',cleared:'Condition cleared',started:'Monitoring started',stopped:'Monitoring stopped',prompt_changed:'Target changed',unavailable:'Observation unavailable'}[e.type]||e.type;
    reason.textContent=`${e.prompt} · ${e.zone} · ${e.reason}`;time.textContent=new Date(e.time).toLocaleTimeString();time.dateTime=e.time;body.append(name,reason);li.append(dot,body,time);return li;}));
  if(!items.length){const li=document.createElement('li');li.className='empty';li.textContent='No events yet.';$('events').append(li);}
  controls();
}
async function poll(){
  try{const response=await fetch('/api/monitoring/status',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error();const data=await response.json();if(!status)hydrate(data.config);if(!busy)show(data);}
  catch(error){setState('Unknown');$('reason').textContent='Application unavailable. Monitoring status is unknown.';}
  setTimeout(poll,1000);
}
summary();poll();preview();
