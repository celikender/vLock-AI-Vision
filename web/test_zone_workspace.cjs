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
assert.equal(run('tagRows().length'),0,'No fixed tags before the first saved rule');
assert.match(run('scadaOutputs()'),/tags appear when the rule is first saved/);
run("zone.tagKey='Test-area';outputSnapshot={zones:[{TagKey:'Test-area',Active:false,State:'Clear',Count1:0,Score1:null,OutputName:'present'}]}");
assert.equal(run("tagRows().find(r=>r[1]==='Bridge/Zones/Test-area/Active')[3]"),false);
assert.equal(run("tagRows().find(r=>r[1].endsWith('/Count1'))[3]"),0);
assert.equal(run("tagRows().find(r=>r[1].endsWith('/Score1'))[3]"),null);
assert.equal(run("tagFolderFor('Bridge/Zones/Test-area/Active')"),'vLock / Zones / Test-area / Active');
run("zone.output='renamed_output'");
assert.ok(run("tagRows().every(r=>r[1].startsWith('Bridge/Zones/Test-area/'))"),'Renaming the output keeps the tag paths');
assert.match(run('scadaOutputs()'),/vlock\/v1\/zones\/Test-area\/state|zones\/Test-area\/state/);
assert.match(run('scadaOutputs()'),/Download Ignition UDT/);
run('outputSnapshot=null');
assert.equal(run("tagRows().find(r=>r[1].endsWith('/Active'))[3]"),null);
assert.match(run('tagMonitor()'),/Not sent · enable OPC UA/);
run("adapters={opcua:{status:'running'}}");assert.match(run('tagMonitor()'),/OPC UA server · live/);run('adapters={}');
assert.match(run('integrationProfiles()'),/Existing|Host address/);
assert.doesNotMatch(run('cameraFields(zone)'),/data-field="cameraPassword"/,'Pi cameras show no login fields');
run("zone.cameraType='RTSP';zone.cameraUsername='viewer';zone.cameraPasswordSet=true");
html=run('cameraFields(zone)');
assert.match(html,/rtsp:\/\/192\.168\.1\.64:554\/stream2/);
assert.match(html,/data-field="cameraPassword" type="password" value=""/,'The saved password is never sent back into the page');
assert.match(html,/Saved · type to replace/);
run("zone.cameraType='Pi / HTTP';delete zone.cameraUsername;delete zone.cameraPasswordSet");
run("workspace.integration={opcMode:'server',opcPort:4845,security:'Basic256Sha256 / SignAndEncrypt'}");
assert.match(run('integrationProfiles()'),/No security · this PC only \(127\.0\.0\.1\) · read-only/);
assert.doesNotMatch(run('integrationProfiles()'),/SignAndEncrypt/,'Server mode never claims encryption');
run("capabilities={opcua:{adapters:[{address:'172.26.224.1',adapter:'vEthernet (WSL)'},{address:'192.168.1.236',adapter:'Wi-Fi'}],login_ready:false}}");
run("workspace.integration={opcMode:'server',opcAccess:'Network',opcHost:'127.0.0.1',opcPort:4845}");
html=run('integrationProfiles()');
assert.equal(run('workspace.integration.opcHost'),'192.168.1.236','Network picks the real adapter, not the WSL one');
assert.match(html,/opc\.tcp:\/\/192\.168\.1\.236:4845\/vlock\//);
assert.match(html,/Sign &amp; Encrypt · username login · read-only/);
assert.match(html,/<b>missing<\/b>/,'A missing login is shown');
assert.doesNotMatch(html,/No security/);
run("capabilities.opcua.login_ready=true");assert.match(run('integrationProfiles()'),/Login: set in \.env/);
run("workspace.integration.opcAccess='This PC only'");run('integrationProfiles()');
assert.equal(run('workspace.integration.opcHost'),'127.0.0.1','This PC only always listens on loopback');
run("workspace.integration.opcMode='client'");assert.match(run('integrationProfiles()'),/SignAndEncrypt/);run('workspace.integration={}');run('capabilities={}');

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
assert.match(run('observationHolder.innerHTML'),/OBSERVATION/);
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
 run("zone.extraConditions=[{object:'dog',relation:'entirely inside area'}];zone.ruleJoin='ANY (OR)';zone.outputType='condition'");
 assert.match(run('ruleSentence(zone)'),/OR dog is entirely inside the selected area/);
 assert.match(run('simpleConfigure(zone)'),/data-second="object" value="dog"/);
 assert.doesNotMatch(run('supportedDraftWarning(zone)'),/not wired/,'Two objects are a supported draft');
 run('zone.validity=10');assert.match(run('simpleConfigure(zone)'),/15 s or more/);
 run('zone.validity=15');assert.doesNotMatch(run('simpleConfigure(zone)'),/15 s or more/);
 run("zone.runtime={objects:2,check_ms:6800}");assert.match(run('observationMetrics(zone)'),/2 OBJECTS[\s\S]*6\.8 s/);
 console.log('Zone workspace checks passed: preview-free dashboard, single camera, controls, editing locks, stable runtime polling and two-object rules.');
})().catch(error=>{console.error(error);process.exitCode=1;});
