'use strict';
// Sequential original-JPEG fetches; SVG image load events are not a polling clock.
function createCameraPreview(image,options={}){
 const fetchFrame=options.fetchFrame||fetch;
 const wait=options.wait||(ms=>new Promise(resolve=>setTimeout(resolve,ms)));
 const createURL=options.createURL||(blob=>URL.createObjectURL(blob));
 const revokeURL=options.revokeURL||(url=>URL.revokeObjectURL(url));
 const controller=new AbortController();
 let stopped=false,objectURL=null;
 function label(text){const badge=image.closest('.scene-wrap')?.querySelector('.frame-state');if(badge)badge.textContent=text;}
 function stop(){stopped=true;controller.abort();if(objectURL){revokeURL(objectURL);objectURL=null;}}
 const done=(async()=>{
  while(!stopped&&image.isConnected){
   let delay=250;
   try{
    const response=await fetchFrame('/api/app/zones/'+encodeURIComponent(image.dataset.zone)+'/snapshot?t='+Date.now(),{cache:'no-store',signal:controller.signal});
    if(!response.ok)throw new Error('Camera request failed');
    const blob=await response.blob();
    if(stopped||!image.isConnected)break;
    const nextURL=createURL(blob),oldURL=objectURL;objectURL=nextURL;
    image.setAttribute('href',nextURL);if(oldURL)revokeURL(oldURL);
    label('Live preview · frame '+(response.headers.get('X-Frame-Sequence')||'received'));
    options.onFrame?.(true);
   }catch(error){
    if(stopped||controller.signal.aborted)break;
    image.removeAttribute('href');if(objectURL){revokeURL(objectURL);objectURL=null;}
    label('Camera unavailable · retrying');options.onFrame?.(false);delay=1000;
   }
   if(!stopped&&image.isConnected)await wait(delay);
  }
  stop();
 })();
 return {stop,done};
}
if(typeof module!=='undefined')module.exports={createCameraPreview};

// Keep the last decoded SAM image on screen while loading its replacement.
function createAnalyzedPreview(image,options={}){
 const fetchFrame=options.fetchFrame||fetch,createURL=options.createURL||(blob=>URL.createObjectURL(blob));
 const revokeURL=options.revokeURL||(url=>URL.revokeObjectURL(url));
 const decode=options.decode||(async url=>{const next=new Image();next.src=url;await next.decode();});
 let wanted=null,displayed=null,url=null,loading=false,stopped=false,generation=0,controller=null;
 function status(message){options.onStatus?.(message);}
 async function pump(){
  if(loading||stopped||!wanted||wanted===displayed)return;
  loading=true;const target=wanted,version=generation;let candidate=null;
  controller=new AbortController();status(url?'Updating · previous analyzed image shown':'Loading analyzed image…');
  try{
   const response=await fetchFrame(target,{cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(6000)])});
   if(!response.ok)throw new Error('Analyzed image unavailable');
   candidate=createURL(await response.blob());await decode(candidate);
   if(stopped||version!==generation||wanted!==target||!image.isConnected)return;
   const previous=url;image.src=candidate;url=candidate;candidate=null;displayed=target;
   image.hidden=false;image.dataset.stale='false';if(previous)revokeURL(previous);
   status('Latest analyzed image · masks belong to this image');
  }catch(error){if(!stopped&&version===generation){image.dataset.stale='true';status(url?'Image update unavailable · last image, not current':'No analyzed image available');}}
  finally{
   if(candidate)revokeURL(candidate);loading=false;
   if(!stopped&&wanted&&wanted!==target)pump();
  }
 }
 return {
  update(target){
   if(stopped)return;
   if(!target){wanted=null;generation++;controller?.abort();image.dataset.stale='true';status(url?'Last analyzed image · not current':'Save the rule and enable monitoring to see SAM results');return;}
   wanted=target;if(displayed===target&&url){image.dataset.stale='false';status('Latest analyzed image · masks belong to this image');}else pump();
  },
  stop(){stopped=true;generation++;controller?.abort();if(url){revokeURL(url);url=null;}}
 };
}
if(typeof module!=='undefined')module.exports.createAnalyzedPreview=createAnalyzedPreview;
