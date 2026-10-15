// Async UI regression: no browser, server, network, ROS or hardware.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const nodes=new Map();
for(const id of ['status','result','ground','refresh','start','stop','close','backend-log'])nodes.set('#'+id,{checked:true,textContent:'',disabled:false});
const status={ok:true,query_ok:true,control_ready:true,stop_available:true,shutdown_available:true,raw_active:false,backend_source:'external',channels:[],initial_ns:[1700000,1000000,1100000],release_ns:[2100000,2100000,2100000]};
let resolveSet,resolveStop;
const setResponse=new Promise(resolve=>resolveSet=resolve),stopResponse=new Promise(resolve=>resolveStop=resolve);
const response=value=>({ok:true,json:async()=>value});
const context={console,document:{querySelector:s=>nodes.get(s)},fetch:async url=>{
 if(url.endsWith('/set'))return setResponse;
 if(url.endsWith('/stop'))return stopResponse;
 return response(status);
}};
vm.createContext(context);
const source=fs.readFileSync(path.join(__dirname,'../web/servo.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('for(let i=0;i<3;i++)')),context);
context.statusFixture=status;
vm.runInContext('latest=statusFixture;rows.push({send:{},initial:{},release:{}});controls()',context);
async function run(){
 const sending=vm.runInContext("action('set',{slot:1,duty_cycle_ns:1800000,hold:true})",context);
 assert(vm.runInContext('rows[0].send.disabled',context));assert(!nodes.get('#stop').disabled,'stop must stay available during send');
 const stopping=vm.runInContext("action('stop')",context);
 assert(nodes.get('#stop').disabled);
 resolveStop(response({ok:true,message:'stop confirmed'}));await stopping;
 assert(vm.runInContext('rows[0].send.disabled',context),'old send is still pending');
 resolveSet(response({ok:true,message:'old send completed'}));await sending;
 assert(nodes.get('#result').textContent.includes('stop confirmed'));
 assert(!nodes.get('#result').textContent.includes('old send completed'));
 vm.runInContext('latest.control_ready=false;controls()',context);
 assert(vm.runInContext('rows[0].send.disabled',context),'legacy/not-ready backend must disable send');
 console.log('PASS: stop availability, pending requests, old response ordering and legacy disable');
}
async function continuousCards(){
 const cards=[],calls=[],confirms=[],elements=new Map();
 for(const id of ['status','result','ground','refresh','start','stop','close','backend-log'])elements.set('#'+id,{checked:true,textContent:'',disabled:false});
 elements.set('#channels',{append:card=>cards.push(card)});
 function card(){
  const parts=new Map();
  for(const selector of ['.actual','.send','.initial','.release','input[type=range]','input[type=number]'])parts.set(selector,{value:'1.5',textContent:'',disabled:false});
  return {className:'',innerHTML:'',querySelector:selector=>parts.get(selector)};
 }
 const fixture={...status,control_ready:true,channels:[1,2,3].map(slot=>({slot,duty_cycle_ns:2100000,enable_value:'1'}))};
 const full={console,document:{hidden:false,querySelector:selector=>elements.get(selector),createElement:card},
  window:{confirm:message=>{confirms.push(message);return true;}},setInterval:()=>{},fetch:async(url,options)=>{
   calls.push({url,body:JSON.parse(options.body)});
   return response(url.endsWith('/status')?fixture:{ok:true,message:'continuous PWM'});
  }};
 vm.createContext(full);vm.runInContext(source,full);await vm.runInContext('refresh()',full);
 async function settle(){for(let i=0;i<30;i++)await Promise.resolve();assert(!vm.runInContext('anyPending()',full));}
 assert.strictEqual(cards.length,3);
 for(const item of cards){
  assert(!item.innerHTML.includes('class="hold"'),'no short-pulse selector remains');
  assert(item.innerHTML.includes('持续输出'));
  const before=calls.length;
  item.querySelector('.release').onclick();
  assert.strictEqual(Number(item.querySelector('input[type=number]').value),2.1);
  item.querySelector('input[type=range]').value='2.2';item.querySelector('input[type=range]').oninput();
  assert.strictEqual(calls.length,before,'presets and slider must not send commands');
  item.querySelector('.release').onclick();item.querySelector('.send').onclick();await settle();
 }
 const sets=calls.filter(call=>call.url.endsWith('/set'));
 assert.strictEqual(sets.length,3);
 sets.forEach((call,i)=>{assert.strictEqual(call.body.slot,i+1);assert.strictEqual(call.body.duty_cycle_ns,2100000);assert.strictEqual(call.body.hold,true);});
 assert(confirms.every(message=>message.includes('持续输出')&&message.includes('关闭页面不会停止输出')));
 const before=calls.length;await vm.runInContext('refresh()',full);
 assert(calls.slice(before).every(call=>call.url.endsWith('/status')),'refresh must preserve ongoing output');
 elements.get('#stop').onclick();await settle();
 assert.strictEqual(calls.filter(call=>call.url.endsWith('/stop')).length,1);
 elements.get('#close').onclick();await settle();
 assert.strictEqual(calls.filter(call=>call.url.endsWith('/close')).length,1);
 assert.strictEqual(calls.filter(call=>call.url.endsWith('/set')).length,3,'no automatic reset command');
 console.log('PASS: three-channel presets/slider read-only, continuous PWM sends, refresh read-only, stop and shutdown retained');
}
run().then(continuousCards).catch(error=>{console.error(error);process.exitCode=1;});
