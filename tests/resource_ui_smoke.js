// Render the actual resource card with fixture telemetry; no browser/network/ROS.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class Element {
 constructor(tag,cls='',text=''){this.tag=tag;this.className=cls;this.textContent=text;this.children=[];this.classList={toggle:(name,on)=>{if(on)this.className+=' '+name;}};}
 appendChild(node){this.children.push(node);return node;}
 setAttribute(name,value){this[name]=value;}
}
const source=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
const segment=source.slice(source.indexOf('function resourceSection()'),source.indexOf('function renderMonitor()'));
let now=100;
const context={state:{connection:{state:'ok'},telemetry:{at:100,master:false,probe:{host:'orangepi'},resources:{age_seconds:0,
 cpu:{status:'ok',percent:0},gpu:{status:'unavailable',reason:'permission denied'},npu:{status:'ok',percent:50,cores:[{name:'Core0',percent:0},{name:'Core1',percent:100}]},
 memory:{used_bytes:3e9,total_bytes:16e9,percent:18.75},disks:[{mount:'/',used_bytes:32e9,total_bytes:64e9,percent:50}],
 network:[{name:'eth0',rx_bytes_per_sec:125000,tx_bytes_per_sec:250000,link_mbps:1000}]}}},
 el:(tag,cls,text)=>new Element(tag,cls||'',text||''),secHead:(title,subtitle)=>new Element('head','',title+' '+subtitle),
 document:{createElement:tag=>new Element(tag)},nowSec:()=>now,hhmmss:()=> '12:00:00'};
vm.createContext(context);vm.runInContext(segment,context);
function all(node){return [node,...node.children.flatMap(all)];}
let card=vm.runInContext('resourceSection()',context),text=all(card).map(n=>n.textContent).join(' ');
assert(text.includes('0.0%'));assert(text.includes('不可读'));assert(text.includes('3.0GB / 16.0GB'));
assert(text.includes('接收 1.00 Mb/s'));assert(text.includes('发送 2.00 Mb/s'));assert(text.includes('Core0 0.0%'));
assert(all(card).find(n=>n.title==='permission denied'));
now=104;card=vm.runInContext('resourceSection()',context);text=all(card).map(n=>n.textContent).join(' ');
assert(text.includes('已过期'));assert(!text.includes('3.0GB'));assert(!all(card).some(n=>n.tag==='progress'));
context.state.connection.state='unknown';card=vm.runInContext('resourceSection()',context);
assert(all(card).some(n=>n.textContent==='未连接远端设备'));
console.log('PASS: resource formatting, zero load, unreadable, master-independent freshness, stale/disconnected state');
