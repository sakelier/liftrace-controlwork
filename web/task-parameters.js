/* Other task parameters share the existing flight override and command authority. */
(function(){
'use strict';
function supported(g){return g.channel==='competition'||g.channel==='module'&&g.folder==='08_full_mission';}
function lookup(value,key){return key.split('.').reduce((v,k)=>v==null?undefined:v[k],value);}
function remove(value,key){const path=key.split('.');if(path.length===1)delete value[key];else if(value[path[0]]){delete value[path[0]][path[1]];if(!Object.keys(value[path[0]]).length)delete value[path[0]];}}
function set(value,key,item){const path=key.split('.');if(path.length===1)value[key]=item;else{value[path[0]]=value[path[0]]||{};value[path[0]][path[1]]=item;}}
function button(g,U){const b=el('button','btn btn-sm task-parameters-open','飞行与任务参数');b.disabled=tSessRunning();b.onclick=()=>open(g,U);return b;}
async function request(action,body){const r=await fetch('/api/task-parameters/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok||!v.ok)throw Error(v.error||'参数读取失败');return v;}
function open(g,U){
 const openedScope=FlightSettings.scope(g),openedBody=JSON.stringify(FlightSettings.readBody(g,U));
 const dialog=el('dialog','task-parameters-dialog');dialog.setAttribute('aria-label','飞行与任务参数');
 const head=el('header','task-parameters-head'),title=el('div');title.append(el('h2',null,'飞行与任务参数'),el('p','muted',g.name));
 const close=el('button','btn','关闭');close.onclick=()=>{dialog.close();dialog.remove();};head.append(title,close);dialog.append(head);
 const note=el('p','task-parameters-intro','只修改本次任务参数，原 YAML 保留。航点、投递和 H 降落请使用各自入口；保存后先执行配置检查。');dialog.append(note);
 const tools=el('div','task-parameters-tools'),search=el('input');search.type='search';search.placeholder='搜索参数名称或配置键';search.setAttribute('aria-label','搜索参数');
 const reload=el('button','btn btn-sm','读取板端现有值');tools.append(search,reload);dialog.append(tools);
 const readStatus=el('p','flight-read-status');readStatus.setAttribute('role','status');dialog.append(readStatus);
 const nav=el('nav','task-parameters-nav');nav.setAttribute('aria-label','参数分类');dialog.append(nav);
 const sections=el('div','task-parameters-sections');dialog.append(sections);
 const source=el('details','task-parameters-source');source.append(el('summary',null,'参数来源与固定导航策略'));const sourceText=el('pre','flight-source-text');source.append(sourceText);dialog.append(source);
 const footer=el('footer','task-parameters-footer'),error=el('p','err-line');error.setAttribute('role','status');
 const count=el('span','muted','未修改'),reset=el('button','btn','本页全部继承'),save=el('button','btn','保存并生成命令');footer.append(error,count,reset,save);dialog.append(footer);
 document.body.append(dialog);dialog.showModal();dialog.addEventListener('cancel',()=>dialog.remove());
 let specs=[],inherited={},fields={},dirty=new Set(),loading=false,version=0;const old=JSON.parse(JSON.stringify(U.flightSettings||{}));
 function same(){return !tSessRunning()&&openedScope===FlightSettings.scope(g)&&openedBody===JSON.stringify(FlightSettings.readBody(g,U));}
 function updateHint(f){const input=fields[f.key].input,hint=fields[f.key].hint,value=lookup(old,f.key),base=inherited[f.key];
  hint.textContent=(base===undefined?'原配置：尚未读取':'原配置：'+(base===null?'未设置':base))+(value!==undefined?'；本机覆盖：'+value:'')+(dirty.has(f.key)?'；待修改':'');
  count.textContent=dirty.size?'已编辑 '+dirty.size+' 项':'未修改';
 }
 function filter(){const term=search.value.trim().toLowerCase();Object.values(fields).forEach(row=>{row.row.hidden=!row.row.textContent.toLowerCase().includes(term);});sections.querySelectorAll('section').forEach(s=>{s.hidden=![...s.querySelectorAll('.task-parameter-row')].some(r=>!r.hidden);});}
 search.oninput=filter;
 function build(){sections.replaceChildren();nav.replaceChildren();fields={};const groups={};
  specs.forEach(f=>{if(!groups[f.section]){const section=el('section'),id='task-parameters-'+Object.keys(groups).length;section.id=id;section.append(el('h3',null,f.section));groups[f.section]=section;sections.append(section);const tab=el('button','btn btn-sm',f.section);tab.onclick=()=>{search.value='';filter();section.scrollIntoView({behavior:'auto',block:'start'});};nav.append(tab);}
   const row=el('div','task-parameter-row'),label=el('label'),id='task-field-'+f.key.replaceAll('.','-');label.htmlFor=id;label.append(el('strong',null,f.label),el('small','muted',f.key));
   const control=el('div','task-parameter-control'),input=el(f.kind==='bool'?'select':'input');input.id=id;input.dataset.taskField=f.key;
   if(f.kind==='bool'){[['','继承原配置'],['true','开启'],['false','关闭']].forEach(([value,text])=>{const o=el('option',null,text);o.value=value;input.append(o);});}
   else{input.type='number';input.step=f.kind==='int'?'1':'any';input.min=f.min;input.max=f.max;input.placeholder='留空继承';}
   const value=lookup(old,f.key);input.value=value===undefined?'':String(value);
   const unit=el('span','task-parameter-unit',f.unit||'');control.append(input,unit);
   const hint=el('small','task-parameter-hint');row.append(label,control,hint);
   const help=el('small','task-parameter-help',f.help||(f.kind!=='bool'?'范围 '+f.min+'～'+f.max+(f.unit?' '+f.unit:''):''));row.append(help);groups[f.section].append(row);fields[f.key]={row,input,hint};
   input.oninput=input.onchange=()=>{dirty.add(f.key);updateHint(f);};updateHint(f);
  });filter();
 }
 async function load(){if(state.connection?.state!=='ok'){readStatus.textContent='尚未连接香橙派。当前仅显示已保存的本机覆盖，原配置值需连接后读取。';return;}
  const current=++version;loading=true;reload.disabled=save.disabled=true;readStatus.textContent='正在读取所选配置、现场文件与速度档…';
  try{const data=await request('current',FlightSettings.readBody(g,U));if(!dialog.isConnected||current!==version)return;if(!same())throw Error('任务或配置来源已变化，请重新打开此页');inherited=data.values||{};
   specs.forEach(f=>{const row=fields[f.key];if(!dirty.has(f.key)){const value=lookup(old,f.key)??inherited[f.key];row.input.value=value==null?'':String(value);}row.hint.title=data.origins?.[f.key]||'';updateHint(f);});
   readStatus.textContent='已读取板端继承值。仅修改项会保存为本机覆盖；原文件保持。';sourceText.textContent=(data.sources||[]).join('\n')+'\n\n'+data.description+'\n'+(data.details?.navigation_lead||'');
  }catch(e){if(current===version)readStatus.textContent=e.message;}finally{if(current===version){loading=false;reload.disabled=save.disabled=false;}}
 }
 reload.onclick=load;
 reset.onclick=()=>{specs.forEach(f=>{fields[f.key].input.value='';dirty.add(f.key);updateHint(f);});};
 save.onclick=async()=>{try{
  error.textContent='';if(loading)throw Error('正在读取参数，请稍候');if(!same())throw Error('任务或配置来源已变化，请重新打开此页');
  const patch=JSON.parse(JSON.stringify(U.flightSettings||{}));specs.forEach(f=>{remove(patch,f.key);const input=fields[f.key].input,raw=input.value.trim();if(!raw)return;let value;
   if(f.kind==='bool')value=raw==='true';else{if(!input.validity.valid)throw Error(f.label+' 超出范围或格式无效');value=Number(raw);if(!Number.isFinite(value)||f.kind==='int'&&!Number.isInteger(value))throw Error(f.label+' 格式无效');}
   if(inherited[f.key]!==undefined&&JSON.stringify(value)===JSON.stringify(inherited[f.key]))return;set(patch,f.key,value);
  });
  save.disabled=true;
  const body={...trialBody(g,'preview',true),flight_settings:Object.keys(patch).length?patch:undefined,expected_body:undefined};
  const r=await fetch('/api/trial/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),v=await r.json();if(!r.ok||!v.ok)throw Error(v.error||'参数校验失败');
  if(!same())throw Error('任务或配置来源已变化，请重新打开此页');const key=FlightSettings.scope(g);if(Object.keys(patch).length)localStorage.setItem(key,JSON.stringify(patch));else localStorage.removeItem(key);
  U.flightSettings=Object.keys(patch).length?patch:null;U.geometryPlans={};U.armedOk=false;U.realConfirm='';
  await FlightSettings.generate(g,U,error);dialog.close();dialog.remove();toast('info','已保存本机参数并生成命令，请执行配置检查');
 }catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
 save.disabled=true;request('schema',{group_id:g.id}).then(data=>{if(!dialog.isConnected)return;specs=data.fields;build();save.disabled=false;return load();}).catch(e=>{readStatus.textContent=e.message;});
}
window.TaskParameters={supported,button};
})();
