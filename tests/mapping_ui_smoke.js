/* Actual UI with fake DOM and responses; no browser/network/ROS. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class Element {
 constructor(tag,text=''){this.tag=tag;this.textContent=text;this.children=[];this.disabled=false;}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
}
const nodes={},all=n=>[n,...n.children.flatMap(all)],text=n=>all(n).map(x=>x.textContent).join(' ');
let online=true,source='board-one',fail=false,pending=null;
const context={document:{hidden:false},window:{addEventListener:()=>{}},setInterval:()=>{},Date,encodeURIComponent,
 logNode:(tag,text)=>new Element(tag,text),logById:id=>nodes[id]||(nodes[id]=new Element('div')),
 logSize:n=>n+' bytes',logAPI:async(url,body)=>{
  if(url==='/api/snapshot')return {connection:{state:online?'ok':'unknown',host:source,board_root:'/board'}};
  if(url.endsWith('/jobs'))return {jobs:[{id:'a'.repeat(32),run:'run1',host:'board-one',state:pending?'downloading':'ready',
   transferred:5,total:10,warnings:['partial fixture'],artifacts:['mapping_run1.zip']}]};
  if(url.includes('/catalog')){if(fail)throw Error('query fixture');return {source_id:source,runs:[{run:'run1',active:!!pending,
   manifest:{status:pending?'recording':'partial',reason:'lost topic',total_bytes:10},files:[{name:'test.bag',size:10}]}],has_more:true};}
  if(url.endsWith('/prepare'))return {};
 }};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/mapping-recordings.js'),'utf8'),context);
(async()=>{
 await vm.runInContext('mappingRefresh()',context);
 assert(text(nodes['mapping-runs']).includes('不完整'));assert(text(nodes['mapping-runs']).includes('lost topic'));
 assert(all(nodes['mapping-jobs']).some(n=>n.tag==='a'&&n.href.includes('/file?id=')&&n.download==='mapping_run1.zip'));
 pending=true;await vm.runInContext('mappingRefresh()',context);
 assert(all(nodes['mapping-runs']).filter(n=>n.tag==='button').every(n=>n.disabled));
 pending=null;source='board-two';vm.runInContext('mappingState.page=3',context);await vm.runInContext('mappingRefresh()',context);
 assert.strictEqual(vm.runInContext('mappingState.page',context),0);
 fail=true;await vm.runInContext('mappingRefresh()',context);
 assert(text(nodes['mapping-message']).includes('query fixture'));assert.strictEqual(vm.runInContext('mappingState.runs.length',context),0);
 online=false;fail=false;await vm.runInContext('mappingRefresh()',context);
 assert(nodes['mapping-refresh'].disabled);assert(text(nodes['mapping-runs']).includes('连接后'));
 assert(all(nodes['mapping-jobs']).some(n=>n.tag==='a')); // Local downloads survive disconnect.
 console.log('PASS: mapping partial/active state, job progress, native download, target switch and offline/error state');
})().catch(error=>{console.error(error);process.exitCode=1;});
