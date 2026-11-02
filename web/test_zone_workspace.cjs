'use strict';
// UI contracts: one workspace, no dashboard camera requests, stable draft polling.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const context=vm.createContext({console,structuredClone,setTimeout,clearTimeout,AbortSignal,
 location:{hash:'#zone/test'},window:{addEventListener(){}},
 document:{addEventListener(){},getElementById(){return null;},querySelectorAll(){return [];}}});
function load(name,cut){let code=fs.readFileSync(path.join(__dirname,'app',name),'utf8');if(cut)code=code.slice(0,code.indexOf(cut));vm.runInContext(code,context);}
load('scene.js');load('ui.js');load('configuration.js');load('app.js',"$('save').addEventListener");
load('runtime.js','// Observe rendered previews');
vm.runInContext(`
const zone={id:'test',name:'Test area',cameraName:'Test camera',cameraAddress:'http://192.168.1.50:8080',
 connected:true,configured:true,areaSelected:true,target:'person',output:'present',outputType:'condition',
 firstRelation:'overlaps area',persistence:.5,validity:10,minConfidence:0,allowRemote:false,
 recheck:'None',unknownPolicy:'Keep Unknown + publish reason',extraConditions:[],zone:[[.1,.1],[.9,.1],[.9,.9],[.1,.9]],events:[],runtime:{enabled:false,state:'Disabled'}};
workspace.zones=[zone];
`,context);
const run=code=>vm.runInContext(code,context);
assert.doesNotMatch(run('zoneCard(zone)'),/camera-frame|<svg|<img/);
let html=run('zoneView(zone)');
assert.equal((html.match(/class="camera-frame"/g)||[]).length,1);
assert.match(html,/configuration-column/);assert.match(html,/id="zone-results"/);
assert.doesNotMatch(html,/data-step=|Next: Configure|Save rule &amp; open monitor/);
assert.match(html,/data-action="monitor-toggle"/);
assert.match(html,/3\. Observation/);assert.doesNotMatch(html,/Event → output flow/);
assert.match(html,/data-show-area/);assert.match(html,/data-analyzed-zone/);
run("outputSnapshot={assets:[]};zone.outputType='count';zone.runtime.value=0");
assert.equal(run("tagRows().find(r=>r[1].endsWith('/NumericValue'))[3]"),0);
run("zone.outputType='condition';zone.runtime.value=false");
assert.equal(run("tagRows().find(r=>r[1].endsWith('/Active'))[3]"),false);
run('outputSnapshot=null');
assert.equal(run("tagRows().find(r=>r[1].endsWith('/Active'))[3]"),null);
assert.match(run('tagMonitor()'),/Not sent by this app/);
assert.match(run('integrationProfiles()'),/Existing|Host address/);

assert.match(run('zoneControls(zone)'),/Rule saved/);
run('dirtyFlag=true');
assert.match(run('zoneControls(zone)'),/data-action="monitor-toggle" disabled/);
run('zone.runtime.enabled=true');
assert.doesNotMatch(run('zoneControls(zone)'),/data-action="monitor-toggle" disabled/);
assert.match(run('simpleConfigure(zone)'),/fieldset data-zone-editor disabled/);
assert.match(run('simpleCameraPane(zone)'),/fieldset data-zone-editor disabled/);
run('zone.runtime.enabled=false;zone.connected=false;dirtyFlag=false');
assert.match(run('simpleCameraPane(zone)'),/fieldset data-area-editor disabled/);
run('zone.runtime.busy=true');
assert.match(run('zoneControls(zone)'),/data-action="monitor-toggle" disabled/);
// Updating ages/events must never detach the persistent SAM viewer container.
run(`
const stableResults={replaceChildren(){throw new Error('SAM viewer was detached');},set innerHTML(v){throw new Error('SAM viewer was replaced');}};
const observationHolder={dataset:{},innerHTML:''},eventsHolder={dataset:{},innerHTML:''};
let viewerUpdates=0;
document.getElementById=id=>({'zone-results':stableResults,'observation-content':observationHolder,'zone-events':eventsHolder}[id]);
document.querySelector=()=>null;refreshZoneControls=()=>{};
function syncAnalyzedPreview(){viewerUpdates++;}
refreshZoneResults();zone.runtime.age_seconds=2;refreshZoneResults();
`);
assert.equal(run('viewerUpdates'),2);
assert.match(run('observationHolder.innerHTML'),/2.0 s/);
// Polling must update service state/results without replacing draft inputs or geometry.
run(`
zone.runtime.busy=false;zone.target='draft hand';zone.zone=[[.2,.2],[.8,.2],[.8,.8],[.2,.8]];
const draftPolygon=zone.zone;dirtyFlag=true;applicationReady=true;
let partialUpdates=0,fullRenders=0;
refreshZoneResults=()=>{partialUpdates++;};render=()=>{fullRenders++;};
appApi=async()=>({workspace:{zones:[{id:'test',target:'server person',configured:true,connected:true,
 localEnabled:false,events:[{state:'Unknown'}],runtime:{enabled:false,state:'Unknown',value:null}}]}});
`);
(async()=>{
 await run('refreshStatus()');
 assert.equal(run('zone.target'),'draft hand');
 assert.equal(run('zone.zone===draftPolygon'),true);
 assert.equal(run('zone.runtime.state'),'Unknown');
 assert.equal(run('partialUpdates'),1);assert.equal(run('fullRenders'),0);
 run("dirtyFlag=false;zone.configured=false");await run('refreshStatus()');
 assert.equal(run('zone.configured'),true);assert.equal(run('fullRenders'),0);
 run("appApi=async()=>{throw new Error('offline');};document.getElementById=()=>({textContent:''});");
 await run('refreshStatus()');
 assert.equal(run('zone.runtime.valid'),false);assert.equal(run('zone.runtime.value'),null);
 assert.equal(run('fullRenders'),0);assert.equal(run('zone.target'),'draft hand');
 console.log('Zone workspace checks passed: preview-free dashboard, single camera, controls, editing locks and stable runtime polling.');
})().catch(error=>{console.error(error);process.exitCode=1;});
