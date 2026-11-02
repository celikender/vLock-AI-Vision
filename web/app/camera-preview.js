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
