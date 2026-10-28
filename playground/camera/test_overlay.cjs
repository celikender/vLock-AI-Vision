// Offline geometry check. No browser camera or model is accessed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'static','overlay.js'),'utf8'),sandbox);
const drawn = [];
const context = {drawImage() {}, strokeRect(...coordinates) {drawn.push(coordinates);}};
const canvas = {getContext() {return context;}};
sandbox.drawEyeBoxes(canvas, {width:1920,height:1080},
  [{x1:100,y1:100,x2:140,y2:120}], 960,540);
assert.equal(canvas.width,1920);
assert.equal(canvas.height,1080);
assert.deepEqual(drawn[0],[192,172,96,96]);
drawn.length = 0;
sandbox.drawEyeBoxes(canvas,{width:640,height:480},[{x1:0,y1:0,x2:40,y2:20}],640,480);
assert.deepEqual(drawn[0],[0,0,48,48]);
drawn.length = 0;
sandbox.drawEyeBoxes(canvas,{width:640,height:480},[],640,480);
assert.equal(drawn.length,0);
console.log('PASS: overlay scaling, square geometry, edge bounds, and empty detections.');
