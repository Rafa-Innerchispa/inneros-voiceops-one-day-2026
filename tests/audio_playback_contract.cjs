'use strict';
// Device-independent regression for the actual browser playback implementation.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const nodes=new Map();
function element(id){if(!nodes.has(id))nodes.set(id,{textContent:'',innerHTML:'',className:'',classList:{add(){},remove(){}},appendChild(){},append(){},querySelector(){return element('p')},querySelectorAll(){return []},addEventListener(){},lastElementChild:{querySelector(){return element('p')}},scrollTop:0,scrollHeight:0});return nodes.get(id);}
const spoken=[],starts=[],stopped=[];
const synth={cancel(){},resume(){},getVoices(){return []},speak(x){spoken.push(x.text)},speaking:false};
const context={console,Date,Math,Uint8Array,DataView,Int16Array,Float32Array,Map,Set,Promise,JSON,
 document:{addEventListener(){},getElementById:element,querySelectorAll(){return []},createElement(){return element('created')}},
 window:{speechSynthesis:synth,addEventListener(){}},location:{protocol:'https:',host:'test.invalid'},
 crypto:{randomUUID:()=> 'test-session'}, navigator:{}, WebSocket:{OPEN:1},
 SpeechSynthesisUtterance:class {constructor(text){this.text=text}},
 atob:x=>Buffer.from(x,'base64').toString('binary'),btoa:x=>Buffer.from(x,'binary').toString('base64'),
 setTimeout,clearTimeout,setInterval(){},requestAnimationFrame(){},cancelAnimationFrame(){},
 audioStub:{state:'running',currentTime:1,createBuffer(ch,n,rate){return {duration:n/rate,getChannelData(){return new Float32Array(n)}}},createBufferSource(){return {connect(){},start(t){starts.push(t)},stop(){stopped.push(true)}}}},spoken,starts,stopped};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/voiceops/web/app.js'),'utf8'),context);
vm.runInContext('audioContext = audioStub;',context);
const data=Buffer.alloc(4800).toString('base64');
vm.runInContext('handleHiggsServerEvent({type:"response.created",response:{id:"r1"}})',context);
vm.runInContext(`playPCM16AudioChunk('${data}');playPCM16AudioChunk('${data}');`,context);
assert.equal(starts.length,2);assert(starts[1]>=starts[0]+0.099,'PCM chunks must be scheduled sequentially');
vm.runInContext('triggerInstantBargeIn()',context);assert.equal(stopped.length,2);
vm.runInContext('handleHiggsServerEvent({type:"response.created",response:{id:"r2"}});handleHiggsServerEvent({type:"response.output_audio_transcript.delta",delta:"Hola "});handleHiggsServerEvent({type:"response.output_audio_transcript.delta",delta:"Rafael"})',context);
assert.equal(spoken.length,0,'Never speak partial transcript chunks');
vm.runInContext('handleHiggsServerEvent({type:"response.done",response:{status:"completed"}})',context);
assert.deepEqual(spoken,['Hola Rafael'],'Speak fallback once only if native audio did not arrive');
vm.runInContext('handleHiggsServerEvent({type:"response.created",response:{id:"r3"}});handleHiggsServerEvent({type:"response.output_audio_transcript.delta",delta:"Native"})',context);
vm.runInContext(`playPCM16AudioChunk('${data}');handleHiggsServerEvent({type:'response.done',response:{status:'completed'}})`,context);
assert.equal(spoken.length,1,'No duplicate browser TTS for native audio');
console.log('PASS: sequential PCM playback, cancellation, once-per-turn fallback, no double speech');
