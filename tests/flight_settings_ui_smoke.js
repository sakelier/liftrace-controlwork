// DOM contract smoke test: no browser, network, server or hardware operations.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'..');
class Element {
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';this.className='';}
 append(...nodes){this.children.push(...nodes);} setAttribute(){} addEventListener(){} showModal(){this.open=true;} close(){this.open=false;} remove(){this.removed=true;}
}
const store=new Map(),ui={},requests=[];
const g={id:'mod08',folder:'08_full_mission',channel:'module',site_config:'field.yaml',name:'08',speed_profile_options:[{}]};
const context={console,window:{},document:{createElement:t=>new Element(t),body:new Element('body')},
 localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
 state:{connection:{host:'board1',board_root:'/project1',site_dir:'site'},trialPending:false},
 tSessRunning:()=>false,renderGroups:()=>{},groupUI:()=>ui,
 shellArgQuote:s=>s,REAL_RELEASE_FOLDERS:['08_full_mission'],FlightLogSync:{options:()=>({})},
 fetch:async(url,opts)=>{const body=JSON.parse(opts.body);requests.push(body);return {ok:true,json:async()=>({ok:true,body:'reviewed '+JSON.stringify(body),note:'test'})};}};
vm.createContext(context);
const app=fs.readFileSync(path.join(root,'web/app.js'),'utf8');
function segment(start,end){return app.slice(app.indexOf(start),app.indexOf(end,app.indexOf(start)));}
vm.runInContext(segment('function groupCommandBody(', 'function buildTrialCommand('),context);
vm.runInContext(segment('function trialBody(', 'function geometryFromDraft('),context);
vm.runInContext(fs.readFileSync(path.join(root,'web/flight-settings.js'),'utf8'),context);
context.FlightSettings=context.window.FlightSettings;
function all(node){return [node,...node.children.flatMap(all)];}
async function run(){
 context.FlightSettings.restore(g,ui);assert.strictEqual(ui.flightSettings,null);
 assert(!context.FlightSettings.supported({channel:'module',folder:'07_memory_only'}));
 const button=context.FlightSettings.button(g,ui);button.children[0].onclick();
 const dialog=context.document.body.children[0];const inputs=Object.fromEntries(all(dialog).filter(n=>n.dataset.flightField).map(n=>[n.dataset.flightField,n]));
 assert(!inputs.landing_xy);assert(inputs.drop_agl&&inputs.release_min_agl&&inputs.release_max_agl);
 inputs.landing_descent_mode.value='4';inputs.landing_descent_mode.onchange();assert.strictEqual(inputs.landing_handoff_mode.value,'OFFBOARD');
 inputs.drop_horizontal_compensation_mode.value='2';inputs.drop_descent_mode.value='4';inputs.drop_agl.value='0.4';inputs.release_min_agl.value='0.35';inputs.release_max_agl.value='0.45';
 const save=all(dialog).find(n=>n.textContent==='保存并生成命令');await save.onclick();
 assert(dialog.removed,'dialog must close after command generation');assert.strictEqual(requests.length,4);
 requests.forEach(r=>assert.strictEqual(r.flight_settings.drop_descent_mode,4));
 assert(context.trialBody(g,'preview',true).expected_body,'generated command must be used');
 assert.strictEqual(ui.flightSettings.landing_descent_mode,4);assert.strictEqual(ui.flightSettings.landing_handoff_mode,'OFFBOARD');
 const restored={};context.FlightSettings.restore(g,restored);assert.strictEqual(restored.flightSettings.drop_agl,.4);
 context.state.connection.host='board2';context.FlightSettings.restore(g,restored);assert.strictEqual(restored.flightSettings,null,'other board must inherit its own settings');
 context.state.connection.host='board1';context.FlightSettings.restore(g,ui);
 const reset=context.FlightSettings.button(g,ui).children.find(n=>n.textContent==='继承原飞行参数');reset.onclick();assert.strictEqual(ui.flightSettings,null);assert.strictEqual(store.size,0);
 console.log('PASS: mode coupling, height window, command preview, persistence, board isolation and reset');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
