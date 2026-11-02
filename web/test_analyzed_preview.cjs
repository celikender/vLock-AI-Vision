'use strict';
const assert=require('node:assert/strict');
const {createAnalyzedPreview}=require('./app/camera-preview.js');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<10;i++)await Promise.resolve();};
const response={ok:true,blob:async()=>({})};
(async()=>{
 const image={isConnected:true,hidden:true,dataset:{}},requests=[],decodes=[],revoked=[],messages=[];
 let counter=0;
 const view=createAnalyzedPreview(image,{
  fetchFrame:target=>{const pending=deferred();requests.push({target,...pending});return pending.promise;},
  createURL:()=>`blob:frame-${++counter}`,revokeURL:url=>revoked.push(url),
  decode:url=>{const pending=deferred();decodes.push({url,...pending});return pending.promise;},
  onStatus:message=>messages.push(message)
 });
 view.update('frame-a');requests[0].resolve(response);await settle();
 assert.equal(image.src,undefined,'Never display an image before decoding it');
 decodes[0].resolve();await settle();assert.equal(image.src,'blob:frame-1');assert.equal(image.hidden,false);
 view.update('frame-b');requests[1].resolve(response);await settle();
 assert.equal(image.src,'blob:frame-1','Previous decoded image stays visible during load');
 view.update('frame-c');assert.equal(requests.length,2,'Only one image request/decode runs at a time');
 decodes[1].resolve();await settle();
 assert.equal(image.src,'blob:frame-1','An obsolete pending frame is never displayed');
 assert.equal(requests[2].target,'frame-c');assert.ok(revoked.includes('blob:frame-2'));
 requests[2].resolve(response);await settle();decodes[2].resolve();await settle();
 assert.equal(image.src,'blob:frame-3');assert.ok(revoked.includes('blob:frame-1'));
 view.update('frame-c');assert.equal(requests.length,3,'Unchanged output does not reload');
 view.update(null);assert.equal(image.src,'blob:frame-3');assert.equal(image.dataset.stale,'true');
 assert.match(messages.at(-1),/not current/);
 view.update('frame-c');assert.equal(image.dataset.stale,'false');assert.equal(requests.length,3);
 view.update('frame-d');requests[3].reject(new Error('temporarily unavailable'));await settle();
 assert.equal(image.src,'blob:frame-3');assert.equal(image.dataset.stale,'true');
 view.update('frame-d');assert.equal(requests.length,5,'A failed update can retry');
 view.stop();requests[4].resolve(response);await settle();decodes.at(-1).resolve();await settle();
 assert.equal(image.src,'blob:frame-3','Stopped views cannot publish late frames');
 assert.ok(revoked.includes('blob:frame-3'));
 console.log('Analyzed preview checks passed: decoded swaps, stable last image, latest-only updates, stale labeling, retry and cleanup.');
})().catch(error=>{console.error(error);process.exitCode=1;});
