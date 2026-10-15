const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class Element{constructor(){this.children=[];this.value='';}append(...nodes){this.children.push(...nodes);}replaceChildren(){this.children=[];}setAttribute(k,v){this[k]=v;}}
const nodes=Object.fromEntries(['geometry','wall-axis','walls','entry'].map(k=>[k,new Element()]));
const source=fs.readFileSync(path.join(__dirname,'../web/waypoint-map.js'),'utf8');
const segment=source.slice(source.indexOf('function geometry()'),source.indexOf('function searchHeights()'));
let remember=0,render=0;
const site={flight_area:{center_bounds:[-.5,9.5,-5.5,5.5],target_bounds:[-.5,9.5,-5.5,5.5],search_bounds:[0,7,-4,4],map_size:[20,20,4]},max_agl:2.3,high_agl:2.6};
const context={site,competition:false,$:id=>nodes[id],document:{createElement:()=>new Element()},remember:()=>remember++,render:()=>render++};
vm.createContext(context);vm.runInContext(segment,context);context.geometry();
function all(node){return [node,...node.children.flatMap(all)];}
const cap=all(nodes.geometry).find(n=>n.id==='max-agl');assert(cap);assert.equal(cap.value,2.3);
cap.valueAsNumber=3.2;cap.onchange();assert.equal(site.max_agl,3.2);assert.equal(site.high_agl,2.6);assert.equal(remember,1);assert.equal(render,1);
console.log('PASS: max_agl editable, undo snapshot recorded, redraw requested, search height unchanged');
