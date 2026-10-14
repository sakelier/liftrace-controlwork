// Inherited values must be visible without becoming pinned overrides.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.value='';}
 append(...nodes){this.children.push(...nodes);}setAttribute(){}addEventListener(){}showModal(){}close(){}remove(){this.removed=true;}
}
const base={drop_horizontal_compensation_mode:2,drop_descent_mode:1,drop_agl:.4,release_min_agl:.35,release_max_agl:.45,drop_descent_speed_mps:.2,drop_descent_mode4_speed_mps:.6,drop_descent_acceleration_mps2:.6,drop_descent_braking_mps2:.6,drop_descent_hold_tolerance_m:.015,landing_alignment_mode:'vh',landing_descent_mode:2,landing_handoff_mode:'POSCTL',landing_descent_speed_mps:.2,'landing_offboard.descent_speed':.3,'landing_offboard.touchdown_overtravel':.04};
const g={id:'mod08',folder:'08_full_mission',channel:'module',site_config:'field.yaml',name:'08'},ui={},requests=[],store=new Map();
const context={console,window:{},document:{createElement:t=>new Element(t),body:new Element('body')},
 state:{connection:{state:'ok',host:'board',board_root:'/project'},trialPending:false},
 localStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
 tSessRunning:()=>false,renderGroups:()=>{},groupUI:()=>ui,shellArgQuote:s=>s,REAL_RELEASE_FOLDERS:['08_full_mission'],FlightLogSync:{options:()=>({})},
 fetch:async(url,options)=>{const body=JSON.parse(options.body);requests.push({url,body});return {ok:true,json:async()=>url.endsWith('/current')?{ok:true,values:{...base},sources:['settings.yaml','field.yaml'],origins:{},details:{landing_xy:[7.7,-3.45]},warnings:[]}:{ok:true,body:'reviewed '+JSON.stringify(body)}};}};
vm.createContext(context);const root=path.resolve(__dirname,'..'),app=fs.readFileSync(path.join(root,'web/app.js'),'utf8');
function segment(a,b){return app.slice(app.indexOf(a),app.indexOf(b,app.indexOf(a)));}
vm.runInContext(segment('function groupCommandBody(','function buildTrialCommand('),context);
vm.runInContext(segment('function trialBody(','function geometryFromDraft('),context);
vm.runInContext(fs.readFileSync(path.join(root,'web/flight-settings.js'),'utf8'),context);context.FlightSettings=context.window.FlightSettings;
const all=node=>[node,...node.children.flatMap(all)],settle=()=>new Promise(resolve=>setImmediate(resolve));
async function open(){context.FlightSettings.button(g,ui).children[0].onclick();await settle();const dialog=context.document.body.children.at(-1);const fields=Object.fromEntries(all(dialog).filter(n=>n.dataset.flightField).map(n=>[n.dataset.flightField,n]));return {dialog,fields,save:all(dialog).find(n=>n.textContent==='保存并生成命令')};}
async function run(){
 context.FlightSettings.restore(g,ui);let form=await open();assert.strictEqual(form.fields.drop_agl.value,'0.4');assert.strictEqual(form.fields.landing_alignment_mode.value,'vh');
 await form.save.onclick();assert(form.dialog.removed);assert.strictEqual(ui.flightSettings,null);assert.strictEqual(requests.filter(r=>r.url.includes('/trial/')).length,0);
 form=await open();form.fields.drop_descent_mode.value='2';await form.save.onclick();assert.deepStrictEqual(JSON.parse(JSON.stringify(ui.flightSettings)),{drop_descent_mode:2});
 const commandRequests=requests.filter(r=>r.url.includes('/trial/'));assert.strictEqual(commandRequests.length,4);commandRequests.forEach(r=>assert.deepStrictEqual(JSON.parse(JSON.stringify(r.body.flight_settings)),{drop_descent_mode:2}));
 form=await open();assert.strictEqual(form.fields.drop_descent_mode.value,'2');form.fields.release_min_agl.value='0.36';await form.save.onclick();assert.strictEqual(ui.flightSettings.release_min_agl,.36);assert.strictEqual(ui.flightSettings.release_max_agl,.45);
 console.log('PASS: inherited-value fill, view-only save, single-field patch, draft overlay and coupled release window');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
