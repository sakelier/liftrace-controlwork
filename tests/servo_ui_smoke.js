// Async UI regression: no browser, server, network, ROS or hardware.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const nodes=new Map();
for(const id of ['status','result','ground','start','stop','close','backend-log'])nodes.set('#'+id,{checked:true,textContent:'',disabled:false});
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
run().catch(error=>{console.error(error);process.exitCode=1;});
