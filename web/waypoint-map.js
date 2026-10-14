'use strict';
let lowMulti=false, competition=false, searchHeightEditable=false;
function mapApi(action){return (competition?'/api/competition-map/':'/api/waypoints/')+action;}
function searchPoints(){return lowMulti?site.search_waypoints_xy:site.flight_area.survey_xy;}
let site, mode='corridor', selected=null, history=[], drag=null, previewTimer, previewVersion=0;
const $=id=>document.getElementById(id), map=$('map');
const colors={survey:'#1769a4',corridor:'#ca6821',staging:'#667c8e',landing:'#107c72'};
const names={survey:'搜索航点',corridor:'走廊航点',staging:'准备点',landing:'H 降落点',select:'选择 / 拖动'};
let scale=1, left=0, bottom=0;
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,5000);}
function remember(){history.push(JSON.stringify({site,importName}));if(history.length>80)history.shift();}
function points(kind){if(kind==='survey')return searchPoints();if(kind==='corridor')return site.corridor_waypoints.map(p=>[p.x,p.y]);return [kind==='staging'?site.flight_area.staging_xy:site.landing_xy].filter(Boolean);}
function activeKind(){return mode==='select'?(selected?.kind||'corridor'):mode;}
function updatePoint(kind,i,x,y){if(kind==='survey')searchPoints()[i]=[x,y];else if(kind==='corridor')Object.assign(site.corridor_waypoints[i],{x,y});else site[kind==='landing'?'landing_xy':'flight_area']=kind==='landing'?[x,y]:{...site.flight_area,staging_xy:[x,y]};}
function screen(x,y){return [left+x*scale,bottom-y*scale];}
function world(event){const p=map.createSVGPoint();p.x=event.clientX;p.y=event.clientY;const q=p.matrixTransform(map.getScreenCTM().inverse());return [(q.x-left)/scale,(bottom-q.y)/scale];}
function snapped(v){const step=Number($('snap').value);return +(step?Math.round(v/step)*step:v).toFixed(3);}
function svg(tag,attrs,text){const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))el.setAttribute(key,value);if(text!=null)el.textContent=text;map.append(el);return el;}
function draw(){
  const a=site.flight_area,b=competition?a.center_bounds:(a.target_bounds||a.center_bounds);
  const boxValid=box=>Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)&&box[0]<box[1]&&box[2]<box[3]&&Math.max(...box.map(Math.abs))<1000;
  // Keep the last map visible while a partially edited range is invalid.
  if(![b,a.center_bounds,a.search_bounds].every(boxValid))return;
  map.replaceChildren();
  const x0=b[0]-.8,x1=b[1]+.8,y0=b[2]-.8,y1=b[3]+.8;
  scale=Math.min(860/(x1-x0),610/(y1-y0));left=70+(860-(x1-x0)*scale)/2-x0*scale;bottom=665-(610-(y1-y0)*scale)/2+y0*scale;
  const rect=(box,attrs)=>{const [x,y]=screen(box[0],box[3]);svg('rect',{x,y,width:(box[1]-box[0])*scale,height:(box[3]-box[2])*scale,...attrs});};
  rect(a.center_bounds,{fill:'#f3f7fa',stroke:'#8d9fab','stroke-width':1.5});rect(a.search_bounds,{fill:'#dfeef9','fill-opacity':.45,stroke:'#80abc9','stroke-dasharray':'6 5'});
  const step=scale<45?1:.5;
  for(let x=Math.ceil(x0/step)*step;x<=x1;x+=step){const p=screen(x,y0),q=screen(x,y1);svg('line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:'#d8e3ea','stroke-width':.7});svg('text',{x:p[0],y:693,'text-anchor':'middle',fill:'#718695','font-size':12},+x.toFixed(1));}
  for(let y=Math.ceil(y0/step)*step;y<=y1;y+=step){const p=screen(x0,y),q=screen(x1,y);svg('line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:'#d8e3ea','stroke-width':.7});svg('text',{x:49,y:p[1]+4,'text-anchor':'end',fill:'#718695','font-size':12},+y.toFixed(1));}
  svg('text',{x:922,y:720,fill:'#405e72','font-size':13},'X / m · 向前');svg('text',{x:18,y:28,fill:'#405e72','font-size':13},'Y / m · 向左');
  const g=site.corridor_geometry;if(g){for(const w of g.wall_coordinates){if(!Number.isFinite(w))continue;const p=screen(g.wall_axis===1?b[0]:w,g.wall_axis===1?w:b[2]),q=screen(g.wall_axis===1?b[1]:w,g.wall_axis===1?w:b[3]);svg('line',{x1:p[0],y1:p[1],x2:q[0],y2:q[1],stroke:'#92a2ad','stroke-width':2,'stroke-dasharray':'9 6'});svg('text',{x:q[0]+8,y:q[1]-7,fill:'#728794','font-size':11},(g.wall_axis===1?'Y':'X')+'='+w);}}
  for(const kind of ['survey','corridor']){const ps=points(kind);if(ps.length>1)svg('polyline',{points:ps.map(p=>screen(...p).join(',')).join(' '),fill:'none',stroke:colors[kind],'stroke-width':2.5,'stroke-linejoin':'round','stroke-opacity':.8});}
  const origin=screen(0,0);svg('path',{d:`M${origin[0]-7},${origin[1]}h14 M${origin[0]},${origin[1]-7}v14`,stroke:'#3d5669','stroke-width':2});svg('text',{x:origin[0]+11,y:origin[1]+20,fill:'#405e72','font-size':12},'起飞 (0, 0)');
  for(const kind of ['survey','corridor','staging','landing'])points(kind).forEach((p,i)=>{
    const [x,y]=screen(...p);if(selected?.kind===kind&&selected.i===i)svg('circle',{cx:x,cy:y,r:20,fill:'none',stroke:colors[kind],'stroke-width':2,'stroke-opacity':.5});
    const circle=svg('circle',{cx:x,cy:y,r:kind==='landing'?15:13,fill:kind==='survey'?'white':colors[kind],stroke:colors[kind],'stroke-width':2,'data-kind':kind,'data-index':i});circle.style.cursor='grab';if(kind==='survey' && searchHeightEditable){const t=document.createElementNS('http://www.w3.org/2000/svg','title');const h=site[lowMulti?'low_agl':'high_agl'];t.textContent='搜索点 '+(i+1)+' · FC AGL '+(Number.isFinite(h)?h.toFixed(2)+' m':'未读取');circle.append(t);}
    svg('text',{x,y:y+4,'text-anchor':'middle',fill:kind==='survey'?colors[kind]:'white','font-size':kind==='landing'?14:12,'font-weight':600,'pointer-events':'none'},kind==='landing'?'H':kind==='staging'?'S':i+1);
  });
}
function list(){
  const kind=activeKind();$('list-title').textContent=names[kind];$('count').textContent=points(kind).length+' 个';$('points').replaceChildren();
  $('list-note').textContent=selected?.kind===kind?'已选中'+names[kind]+(['survey','corridor'].includes(kind)?' '+(selected.i+1):'')+'，可直接输入 X、Y'+(kind==='corridor'?' 和 AGL':'')+' 微调，地图与导出配置同步更新。':'按编号依次飞行，点击地图上的点可输入坐标微调。AGL 为飞控中心离地高度。';
  $('default-agl').parentElement.hidden=kind!=='corridor';$('clear').hidden=!['survey','corridor'].includes(kind);$('close-route').hidden=kind!=='survey';$('join-h').hidden=kind!=='corridor';
  const ps=points(kind);if(!ps.length){const p=document.createElement('p');p.className='empty';p.textContent='在左侧地图点击，按飞行顺序添加航点。';$('points').append(p);}
  ps.forEach((p,i)=>{
    const row=document.createElement('div');row.className='point'+(selected?.kind===kind&&selected.i===i?' selected':'');
    const top=document.createElement('div');top.className='point-top';const title=document.createElement('strong');title.textContent=['staging','landing'].includes(kind)?names[kind]:names[kind]+' '+(i+1);top.append(title);
    title.onclick=()=>{selected={kind,i};draw();list();};const buttons=document.createElement('div');
    if(['survey','corridor'].includes(kind))for(const [label,delta]of [['上移',-1],['下移',1],['删除',0]]){const button=document.createElement('button');button.textContent=label;button.disabled=delta!==0&&(i+delta<0||i+delta>=ps.length);button.onclick=()=>{remember();const arr=kind==='survey'?searchPoints():site.corridor_waypoints;if(delta){[arr[i],arr[i+delta]]=[arr[i+delta],arr[i]];selected={kind,i:i+delta};}else{arr.splice(i,1);selected=null;}render();};buttons.append(button);}
    top.append(buttons);row.append(top);const coords=document.createElement('div');coords.className='coords';
    for(const [label,value,index]of [['X',p[0],0],['Y',p[1],1],...(kind==='corridor'?[['AGL',site.corridor_waypoints[i].agl??1.4,2]]:[])]){const lab=document.createElement('label');lab.textContent=label+' / m';const input=document.createElement('input');input.type='number';input.step=index===2?'0.05':'0.01';input.value=value;input.setAttribute('aria-label',title.textContent+' '+label);input.oninput=()=>{if(!Number.isFinite(input.valueAsNumber))return;if(!input.dataset.editStarted){remember();input.dataset.editStarted='1';}const current=points(kind)[i];if(index===2)site.corridor_waypoints[i].agl=input.valueAsNumber;else updatePoint(kind,i,index===0?input.valueAsNumber:current[0],index===1?input.valueAsNumber:current[1]);selected={kind,i};draw();preview();document.getElementById('undo').disabled=false;};input.onblur=()=>{delete input.dataset.editStarted;};lab.append(input);coords.append(lab);}
    if(kind==='survey' && searchHeightEditable){const altitude=document.createElement('div');altitude.className='point-search-height';const height=site[lowMulti?'low_agl':'high_agl'];altitude.textContent=Number.isFinite(height)?'搜索 AGL '+height.toFixed(2)+' m':'搜索高度尚未读取';row.append(altitude);}
    row.append(coords);$('points').append(row);
  });
}
function geometry(){
  $('geometry').replaceChildren();for(const [label,key]of [['飞行边界','center_bounds'],['目标范围','target_bounds'],['搜索范围','search_bounds'],['地图尺寸 X / Y / Z','map_size']]){const lab=document.createElement('label');lab.className='geometry-row';lab.textContent=label+' / m';const input=document.createElement('input');input.value=site.flight_area[key].join(', ');input.onchange=()=>{remember();site.flight_area[key]=input.value.split(/[,，\s]+/).filter(Boolean).map(Number);render();};lab.append(input);$('geometry').append(lab);}
  for(const [label,key]of (competition?[['H接近FC AGL','landing_transit_agl'],['H识别FC AGL','landing_capture_agl']]:[])){const lab=document.createElement('label');lab.textContent=label+' / m';const input=document.createElement('input');input.type='number';input.step='.1';input.value=site[key];input.onchange=()=>{remember();site[key]=input.valueAsNumber;render();};lab.append(input);$('geometry').append(lab);}
  if(competition){const lab=document.createElement('label');lab.className='geometry-row';lab.textContent='覆盖范围 / m';const input=document.createElement('input');input.value=site.coverage_bounds.join(', ');input.onchange=()=>{remember();site.coverage_bounds=input.value.split(/[,，\s]+/).filter(Boolean).map(Number);render();};lab.append(input);$('geometry').append(lab);}
  const g=site.corridor_geometry||{wall_axis:1,wall_coordinates:[0,-1.4],entry_waypoints:1};$('wall-axis').value=g.wall_axis;$('walls').value=g.wall_coordinates.join(', ');$('entry').value=g.entry_waypoints;
}
function searchHeights(){
  $('search-altitude').hidden=!searchHeightEditable;
  if(!searchHeightEditable)return;
  $('high-height-field').hidden=lowMulti;
  $('low-height-label').textContent=lowMulti?'低空搜索 AGL':'低位复核 AGL';
  $('search-height-note').textContent=lowMulti?'低空搜索点共同高度':'高位航线 / 低位复核';
  const field=(id,key)=>{const input=$(id);if(document.activeElement!==input)input.value=Number.isFinite(site[key])?site[key]:'';input.disabled=!(key in site);};
  field('search-high-agl','high_agl');field('search-low-agl','low_agl');
  $('search-high-agl').max=competition?Math.min(3,site.max_agl):Math.min(2.8,site.max_agl);
  $('height-cap').textContent=Number.isFinite(site.max_agl)?'当前 FC 高度上限 '+site.max_agl.toFixed(2)+' m':'高度上限尚未读取';
}
for(const [id,key]of [['search-high-agl','high_agl'],['search-low-agl','low_agl']])$(id).oninput=()=>{
  const input=$(id);
  if(!input.dataset.editStarted){remember();input.dataset.editStarted='1';}
  site[key]=Number.isFinite(input.valueAsNumber)?input.valueAsNumber:null;draw();list();preview();$('undo').disabled=false;
};
for(const id of ['search-high-agl','search-low-agl'])$(id).onblur=()=>{delete $(id).dataset.editStarted;searchHeights();};
async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});if(!r.ok){const e=await r.json();throw new Error(e.error||'读取失败');}return r;}
function preview(){const version=++previewVersion;clearTimeout(previewTimer);$('export').disabled=true;previewTimer=setTimeout(async()=>{try{const data=await(await api(mapApi('preview'),{site})).json();if(version!==previewVersion)return;$('preview').textContent=data.yaml;$('validation').className=data.errors.length?'invalid':'';$('validation').replaceChildren();for(const text of data.errors.length?data.errors:['坐标检查通过，可保存到工作台']){const p=document.createElement('div');p.textContent=text;$('validation').append(p);}$('export').disabled=!!data.errors.length;}catch(e){if(version!==previewVersion)return;$('validation').className='invalid';$('validation').textContent=e.message;}},180);}
function render(){draw();list();geometry();searchHeights();preview();$('undo').disabled=!history.length;$('import-status').hidden=!importName;if(importName)$('import-status').textContent='当前地图来源：'+importName+'。点击“保存并用于本组”后应用；飞行参数仍沿用工作台设置。';window.parent.postMessage({type:'waypoint-imported',name:importName},location.origin);}
map.addEventListener('pointerdown',event=>{const target=event.target.closest('[data-kind]');if(target){selected={kind:target.dataset.kind,i:Number(target.dataset.index)};mode='select';document.querySelectorAll('[data-mode]').forEach(button=>button.classList.toggle('active',button.dataset.mode==='select'));$('hint').textContent='已选中'+names[selected.kind]+'，在坐标面板输入数值微调，也可继续拖动。';drag={...selected,start:world(event),moved:false};map.setPointerCapture(event.pointerId);draw();list();return;}if(mode==='select')return;const [x,y]=world(event).map(snapped);remember();if(mode==='corridor'){site.corridor_waypoints.push({x,y,agl:Number($('default-agl').value)});selected={kind:mode,i:site.corridor_waypoints.length-1};}else if(mode==='survey'){searchPoints().push([x,y]);selected={kind:mode,i:searchPoints().length-1};}else{updatePoint(mode,0,x,y);selected={kind:mode,i:0};}render();});
map.addEventListener('pointermove',event=>{const coords=world(event);$('cursor').textContent='X '+coords[0].toFixed(2)+' m　Y '+coords[1].toFixed(2)+' m';if(!drag)return;if(!drag.moved&&Math.hypot(coords[0]-drag.start[0],coords[1]-drag.start[1])<.02)return;if(!drag.moved){remember();drag.moved=true;}updatePoint(drag.kind,drag.i,...coords.map(snapped));draw();list();});
function endDrag(event){if(drag?.moved)render();else if(drag&&event.type==='pointerup'){const row=$('points').querySelector('.selected');if(row){row.scrollIntoView({block:'nearest',behavior:'instant'});const input=row.querySelector('input');input?.focus({preventScroll:true});input?.select();}}drag=null;}map.addEventListener('pointerup',endDrag);map.addEventListener('pointercancel',endDrag);
document.querySelectorAll('[data-mode]').forEach(button=>button.onclick=()=>{mode=button.dataset.mode;selected=null;document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b===button));$('hint').textContent=mode==='select'?'点击已有点选择，拖动调整位置。':'点击空白处设置'+names[mode]+'，拖动已有点调整位置。';draw();list();});
$('undo').onclick=()=>{if(history.length){const previous=JSON.parse(history.pop());site=previous.site;importName=previous.importName;selected=null;render();}};
$('clear').onclick=()=>{const kind=activeKind();if(!confirm('清空'+names[kind]+'？可撤销。'))return;remember();if(kind==='survey'){if(lowMulti)site.search_waypoints_xy=[];else site.flight_area.survey_xy=[];}else site.corridor_waypoints=[];selected=null;render();};
$('close-route').onclick=()=>{const ps=searchPoints();if(!ps.length)return;if(ps.length>=(lowMulti?100:8)){toast('搜索航点数达到上限，请先删除一个点');return;}if(JSON.stringify(ps[0])===JSON.stringify(ps.at(-1)))return;remember();ps.push([...ps[0]]);render();};
$('join-h').onclick=()=>{if(!site.landing_xy||!site.corridor_waypoints.length)return;remember();const p=site.corridor_waypoints.at(-1);[p.x,p.y]=site.landing_xy;render();};
for(const id of ['wall-axis','walls','entry'])$(id).onchange=()=>{remember();site.corridor_geometry={wall_axis:Number($('wall-axis').value),wall_coordinates:$('walls').value.split(/[,，\s]+/).filter(Boolean).map(Number),entry_waypoints:Number($('entry').value)};render();};
$('reset').onclick=()=>{if(!initialSite)return;remember();site=structuredClone(initialSite);importName=initialImportName;selected=null;render();};
let importName=null,importVersion=0;
async function importLocal(text,name){
  if(!site)throw new Error('地图尚未就绪，请稍候再导入');
  const version=++importVersion;
  const result=await(await api(mapApi('import'),{text,base_site:site})).json();
  if(version!==importVersion)return;
  remember();site=result.site;importName=name;selected=null;render();
  $('import-status').hidden=false;$('import-status').textContent='已从本机导入 '+name+'。航点和地图已载入，点击“保存并用于本组”后应用。'+(result.ignored_fields.length?'文件中的其他字段未作为飞行参数导入，模式和速度沿用工作台设置。':'');
  window.parent.postMessage({type:'waypoint-imported',name},location.origin);toast('已载入本机 YAML');
}
$('import').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{if(file.size>2*1024*1024)throw new Error('配置文件不能超过 2MiB');await importLocal(await file.text(),file.name);}catch(e){toast(e.message);}event.target.value='';};
$('download-map').onclick=async()=>{try{const data=await(await api(mapApi('export'),{site})).json();const url=URL.createObjectURL(new Blob([data.yaml],{type:'application/yaml;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download='waypoint_map.yaml';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);toast('已导出 waypoint_map.yaml');}catch(e){toast(e.message);}};
let initialSite=null,initialImportName=null;
$('export').onclick=()=>{if(!site)return;$('export').disabled=true;window.parent.postMessage({type:'waypoint-apply',site,import_name:importName},location.origin);};
$('cancel-map').onclick=()=>window.parent.postMessage({type:'waypoint-cancel'},location.origin);
window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==window.parent)return;
  if(event.data?.type==='waypoint-context'){
    if(initialSite){window.parent.postMessage({type:'waypoint-context-ready'},location.origin);return;}
    competition=event.data.context.folder==='competition';
    searchHeightEditable=competition || ['05_low_multi','08_full_mission'].includes(event.data.context.folder);
    if(competition){$('default-agl').max='1.8';$('entry').max='100';}
    lowMulti=event.data.context.folder==='05_low_multi';
    if(lowMulti){names.survey='低空搜索航点';document.querySelector('[data-mode=survey]').textContent='低空搜索航点';document.querySelector('[data-mode=staging]').hidden=true;}
    site=event.data.context.site;initialSite=structuredClone(site);importName=event.data.context.draft?.enabled!==false?event.data.context.draft?.import_name||null:null;initialImportName=importName;history=[];selected=null;render();
    window.parent.postMessage({type:'waypoint-context-ready'},location.origin);
  }else if(event.data?.type==='waypoint-load-local'){importLocal(event.data.text,event.data.name).catch(e=>toast(e.message));
  }else if(event.data?.type==='waypoint-error'){toast(event.data.error);preview();}
});
window.parent.postMessage({type:'waypoint-ready'},location.origin);
