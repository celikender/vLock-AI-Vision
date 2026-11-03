'use strict';
const assert=require('node:assert/strict');
const {createCameraPreview}=require('./app/camera-preview.js');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){const badge={textContent:''};return {badge,image:{isConnected:true,dataset:{zone:'zone_a'},attributes:{},closest:()=>({querySelector:()=>badge}),setAttribute(name,value){this.attributes[name]=value;},removeAttribute(name){delete this.attributes[name];}}};}
const response=sequence=>({ok:true,blob:async()=>({}),headers:{get:()=>String(sequence)}});
(async()=>{
 const {image,badge}=fixture(),requests=[],waits=[],revoked=[];
 const pump=createCameraPreview(image,{fetchFrame:()=>{const request=deferred();requests.push(request);return request.promise;},wait:ms=>{const pause=deferred();waits.push({ms,...pause});return pause.promise;},createURL:()=> 'blob:frame',revokeURL:url=>revoked.push(url)});
 assert.equal(requests.length,1);
 await settle();assert.equal(requests.length,1,'No second request while the first is pending');
 requests[0].resolve(response(1));await settle();
 assert.equal(image.attributes.href,'blob:frame');assert.match(badge.textContent,/frame 1/);
 assert.equal(requests.length,1,'Wait between completed requests');
 assert.ok(waits[0].ms<=50,'Healthy preview pacing must not regress to the old 250 ms delay');
 waits[0].resolve();await settle();assert.equal(requests.length,2,'Refresh does not depend on SVG load events');
 requests[1].reject(new Error('Camera lost'));await settle();
 assert.equal(image.attributes.href,undefined,'Never leave an old frame visible on failure');
 assert.match(badge.textContent,/unavailable/);assert.equal(waits[1].ms,1000);
 waits[1].resolve();await settle();assert.equal(requests.length,3);
 pump.stop();requests[2].resolve(response(3));await pump.done;
 assert.deepEqual(revoked,['blob:frame']);assert.equal(image.attributes.href,undefined);
 const removed=fixture(),pending=deferred();let created=0;
 const other=createCameraPreview(removed.image,{fetchFrame:()=>pending.promise,createURL:()=>{created++;return 'blob:unused';},revokeURL:()=>{}});
 removed.image.isConnected=false;pending.resolve(response(4));await other.done;
 assert.equal(created,0,'A removed view cannot publish a late frame');
 console.log('Camera preview checks passed: sequential refresh, loss, retry, stop and removed view.');
})().catch(error=>{console.error(error);process.exitCode=1;});
