/* Preflight parameters use the same reviewed command API as waypoint drafts. */
(function(){
 'use strict';
 const dropFolders=['01_visual_interrupt','02_high_view_revisit','05_low_multi','06_high_priority','08_full_mission'];
 const hFolders=['03_h_landing','04_corridor_landing','05_low_multi','08_full_mission'];
 function supported(g){return g.channel==='competition'||g.channel==='module'&&(dropFolders.includes(g.folder)||hFolders.includes(g.folder));}
 function scope(g){const c=state.connection||{};return 'flight-settings:'+JSON.stringify([c.host,c.board_root,c.site_dir,g.id,g.site_config]);}
 function restore(g,U){if(!supported(g))return;const key=scope(g);if(U.flightScope===key)return;U.flightScope=key;U.flightSettings=null;U.flightCurrentRead=null;U.geometryPlans={};try{U.flightSettings=JSON.parse(localStorage.getItem(key))||null;}catch(e){U.flightStorageError=e.message;}}
 function readBody(g,U){return {group_id:g.id,...(g.channel==='competition'&&U.competitionConfig!=null?{competition_config:U.competitionConfig}:{}),...(U.speedProfile?{speed_profile:U.speedProfile}:{}),...(U.geometryEnabled&&U.geometryValues?{site_geometry:U.geometryValues}:{})};}
 function lookup(object,key){return key.split('.').reduce((v,k)=>v==null?undefined:v[k],object);}
 async function generate(g,U,status){
  if(tSessRunning())throw Error('任务运行中不能修改参数');
  status.textContent='正在生成完整命令…';
  const requests=[trialBody(g,'preview',true),trialBody(g,'preview',false),trialBody(g,'flight',false)];
  const signature=JSON.stringify(requests);
  const plans=await Promise.all(requests.map(async body=>{
   delete body.confirm;delete body.expected_body;
   const r=await fetch('/api/trial/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok||!v.ok)throw Error(v.error||'参数校验失败');
   return [geometryPlanKey(g,body.mode,body.real_release,!!body.check_config,body.capture_speed,body),v];
  }));
  const current=[trialBody(g,'preview',true),trialBody(g,'preview',false),trialBody(g,'flight',false)];
  // expected_body changes as caches fill; compare requested options only.
  const strip=values=>values.map(v=>{const q={...v};delete q.confirm;delete q.expected_body;return q;});
  if(JSON.stringify(strip(current))!==JSON.stringify(strip(JSON.parse(signature))))throw Error('参数已变化，请重新生成');
  plans.forEach(([k,v])=>{U.geometryPlans=U.geometryPlans||{};U.geometryPlans[k]=v;});renderGroups();
 }
 function button(g,U){
  const wrap=document.createElement('div');wrap.className='waypoint-entry';
  const edit=document.createElement('button');edit.className='btn btn-sm';edit.textContent='投递 / H 降落参数';edit.disabled=tSessRunning();edit.onclick=()=>open(g,U);wrap.append(edit);
  const status=document.createElement('p');status.className='tiny muted';status.textContent=U.flightSettings?'已启用飞行参数覆盖；需要生成完整命令并执行配置检查。':'继承当前工程参数；可在飞行前设置模式、高度及允许范围。';wrap.append(status);
  if(U.flightCurrentRead&&U.flightCurrentRead.request===JSON.stringify(readBody(g,U))){
   const v=U.flightCurrentRead.values, current=document.createElement('p');current.className='flight-current-summary';
   current.textContent=[v.drop_descent_mode!=null?'原配置投递：水平'+v.drop_horizontal_compensation_mode+' / 下降'+v.drop_descent_mode+'，目标'+v.drop_agl+'m，释放'+v.release_min_agl+'～'+v.release_max_agl+'m':'',v.landing_descent_mode!=null?'原配置H：'+v.landing_alignment_mode+' / 下降'+v.landing_descent_mode+' / '+v.landing_handoff_mode:''].filter(Boolean).join('；');wrap.append(current);
  }
  if(U.flightSettings){
   const summary=document.createElement('pre');summary.className='cmd-pre';summary.textContent=JSON.stringify(U.flightSettings,null,2);wrap.append(summary);
   const build=document.createElement('button');build.className='btn btn-sm';build.textContent='生成参数命令（不连接飞机）';build.disabled=tSessRunning();build.onclick=()=>{build.disabled=true;generate(g,U,status).catch(e=>status.textContent=e.message).finally(()=>build.disabled=false);};wrap.append(build);
   const reset=document.createElement('button');reset.className='btn btn-sm';reset.textContent='继承原飞行参数';reset.disabled=tSessRunning();reset.onclick=()=>{U.flightSettings=null;U.geometryPlans={};U.armedOk=false;U.realConfirm='';try{localStorage.removeItem(scope(g));}catch(e){}renderGroups();};wrap.append(reset);
  }
  return wrap;
 }
 function open(g,U){
  const openedScope=scope(g);
  const openedRequest=JSON.stringify(readBody(g,U));
  const dialog=document.createElement('dialog');dialog.className='flight-settings-dialog';dialog.setAttribute('aria-label','飞行前投递与H降落参数');
  const title=document.createElement('h2');title.textContent=g.name+' · 飞行前参数';dialog.append(title);
  const note=document.createElement('p');note.textContent='打开时读取所选板端配置并显示现有值；本机覆盖单独标注。只保存修改的参数，留空或“继承”保留原配置。高度为飞控中心离地 AGL（m）。';dialog.append(note);
  const readStatus=document.createElement('p');readStatus.className='flight-read-status';readStatus.setAttribute('role','status');dialog.append(readStatus);
  const readButton=document.createElement('button');readButton.className='btn';readButton.textContent='重新读取现有参数';dialog.append(readButton);
  const sourceBox=document.createElement('details'),sourceTitle=document.createElement('summary'),sourceText=document.createElement('pre');sourceTitle.textContent='参数来源与H位置范围';sourceBox.append(sourceTitle,sourceText);sourceText.className='flight-source-text';dialog.append(sourceBox);
  const fields={},hints={},dirty=new Set();let inherited={},readVersion=0,loading=false;const old=U.flightSettings||{};
  function hint(key){const base=inherited[key],own=lookup(old,key);hints[key].textContent=dirty.has(key)?'待修改；原配置：'+(base==null?'尚未读取':base):own!=null?'本机覆盖：'+own+'；原配置：'+(base==null?'尚未读取':base):base!=null?'现有值：'+base:'尚未读取，留空继承';}
  function field(key,label,choices,placeholder,min,max){
   const row=document.createElement('label');row.className='flight-settings-row';const text=document.createElement('span');text.textContent=label;row.append(text);
   const input=document.createElement(choices?'select':'input');input.dataset.flightField=key;
   if(choices){[['','继承原配置'],...choices].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;input.append(o);});}
   else{input.type=key==='landing_xy'?'text':'number';input.step='any';if(min!=null)input.min=min;if(max!=null)input.max=max;input.placeholder=placeholder||'留空继承';}
   const value=lookup(old,key);input.value=value==null?'':Array.isArray(value)?value.join(', '):String(value);fields[key]=input;row.append(input);const help=document.createElement('small');help.className='flight-value-source';hints[key]=help;row.append(help);dialog.append(row);hint(key);
   const changed=()=>{dirty.add(key);hint(key);};input.addEventListener('input',changed);input.addEventListener('change',changed);
  }
  function heading(text){const h=document.createElement('h3');h.textContent=text;dialog.append(h);}
  const desc=[[1,'1 · XYZ位置下降'],[2,'2 · 冻结XY + Z轨迹'],[3,'3 · 零水平速度 + Z轨迹'],[4,'4 · 冻结XY + 垂直速度']];
  if(g.channel==='competition'||dropFolders.includes(g.folder)){
   heading('投递下降');
   field('drop_horizontal_compensation_mode','水平调整模式',[[1,'1 · 双XY≤4cm，速度≤0.1m/s，持续1s'],[2,'2 · 当前补偿达标即下降']]);
   field('drop_descent_mode','下降模式',desc);
   field('drop_agl','下降目标高度（m）',null,'例如 0.40',g.folder==='05_low_multi'?.15:.35,1);
   field('release_min_agl','释放高度下限（m）',null,'例如 0.35',.001,1.1);
   field('release_max_agl','释放高度上限（m）',null,'例如 0.45',.001,1.1);
   field('drop_descent_speed_mps','模式2/3下降速度（m/s）',null,'例如 0.20',.001,1);
   field('drop_descent_mode4_speed_mps','模式4最大下降速度（m/s）',null,'例如 0.60',.001,1);
   field('drop_descent_acceleration_mps2','模式4加速度（m/s²）',null,'例如 0.60',.001,2);
   field('drop_descent_braking_mps2','模式4制动加速度（m/s²）',null,'例如 0.60',.001,2);
   field('drop_descent_hold_tolerance_m','模式4终点切换距离（m）',null,'例如 0.015',.001,.03);
   const p=document.createElement('p');p.className='tiny muted';p.textContent='释放高度窗口用于正常释放。当前控制器的20秒下降超时兜底会忽略XY和高度；原许可及反馈有效性仍须满足。';dialog.append(p);
  }
  if(g.channel==='competition'||hFolders.includes(g.folder)){
   heading('H 字降落');
   field('landing_alignment_mode','水平调整模式',[['non_vh','non_vh · 连续十帧捕获'],['vh','vh · ≤6cm、速度<0.1m/s、持续1s']]);
   field('landing_descent_mode','下降模式',desc.map(v=>v[0]===4?[4,'4 · OFFBOARD下降至触地']:v));
   field('landing_handoff_mode','末段交接',[['POSCTL','POSCTL · 飞手完成降落'],['AUTO.LAND','AUTO.LAND'],['OFFBOARD','OFFBOARD · 模式4']]);
   field('landing_descent_speed_mps','模式2/3下降速度（m/s）',null,'例如 0.20',.001,1);
   field('landing_offboard.descent_speed','模式4下降速度（m/s）',null,'例如 0.30',.001,1);
   field('landing_offboard.touchdown_overtravel','模式4触地越程（m）',null,'例如 0.04',.001,.1);
   fields.landing_descent_mode.onchange=()=>{if(fields.landing_descent_mode.value==='4')fields.landing_handoff_mode.value='OFFBOARD';else if(fields.landing_descent_mode.value&&fields.landing_handoff_mode.value==='OFFBOARD')fields.landing_handoff_mode.value='POSCTL';dirty.add('landing_handoff_mode');hint('landing_handoff_mode');};
  }
  const error=document.createElement('p');error.className='err-line';dialog.append(error);
  const save=document.createElement('button');save.className='btn';save.textContent='保存并生成命令';
  async function loadValues(){
   if(state.connection?.state!=='ok'){readStatus.textContent='请先连接板端，再读取现有参数；当前仅显示本机覆盖。';return;}
   const request=readBody(g,U),version=++readVersion;loading=true;save.disabled=true;readButton.disabled=true;readStatus.textContent='正在只读读取模块、现场配置与所选速度档…';
   try{
    const response=await fetch('/api/flight-settings/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)}),data=await response.json();
    if(!response.ok||!data.ok)throw Error(data.error||'读取参数失败');
    if(version!==readVersion||dialog.isConnected===false)return;
    if(scope(g)!==openedScope||JSON.stringify(readBody(g,U))!==JSON.stringify(request)||JSON.stringify(request)!==openedRequest)throw Error('配置来源已变化，请重新打开参数面板');
    inherited=data.values||{};
    Object.entries(fields).forEach(([key,input])=>{if(!dirty.has(key)){const value=lookup(old,key)??inherited[key];input.value=value==null?'':String(value);}hint(key);hints[key].title=data.origins?.[key]||'';});
    const d=data.details||{},p=d.landing_posctl;sourceText.textContent='读取文件：\n'+(data.sources||[]).join('\n')+'\n\n'+(data.description||'')+(d.landing_xy!==undefined?'\nH中心 XY：'+JSON.stringify(d.landing_xy)+' m':'')+(d.landing_descent_target_agl!=null?'\n'+(d.touchdown_target_agl!=null?'OFFBOARD下降暂驻':'H下降目标')+' / 交接触发 AGL：'+d.landing_descent_target_agl+' / '+d.handoff_trigger_agl+' m':'')+(d.touchdown_target_agl!=null?'\nOFFBOARD触地目标 AGL：'+d.touchdown_target_agl+' m':'')+(d.landing_transit_agl!=null?'\nH过渡 / 捕获 AGL：'+d.landing_transit_agl+' / '+d.landing_capture_agl+' m':'')+(p?'\nPOSCTL目标 / 交接触发 AGL：'+p.target_agl+' / '+p.trigger_agl+' m\nPOSCTL水平 / 高度容差：'+p.xy_tolerance_m+' / '+p.height_tolerance_m+' m\n水平速度上限 / 稳定时间：'+p.max_horizontal_speed_mps+' m/s / '+p.stable_duration_sec+' s':'')+'\n投递目标XY：视觉靶心与投口杆臂补偿动态生成。';
    readStatus.textContent='已读取现有参数'+(Object.keys(old).length?'，表单叠加本机覆盖':'')+'。'+(data.warnings||[]).join('；');
    U.flightCurrentRead={...data,request:JSON.stringify(request)};renderGroups();
   }catch(e){if(version===readVersion)readStatus.textContent=e.message;}
   finally{if(version===readVersion){loading=false;save.disabled=false;readButton.disabled=false;}}
  }
  readButton.onclick=loadValues;
  save.onclick=async()=>{
   try{
    if(loading)throw Error('正在读取参数，请稍候');
    if(tSessRunning())throw Error('任务运行中不能修改参数');
    const patch={};Object.entries(fields).forEach(([key,input])=>{
     if(!input.value.trim())return;
     const path=key.split('.');let value;
     if(key==='landing_xy'){value=input.value.trim().split(/[\s,，]+/).map(Number);if(value.length!==2||!value.every(Number.isFinite))throw Error('H中心需填写两个有限XY数值');}
     else if(input.tagName==='SELECT'&&['landing_alignment_mode','landing_handoff_mode'].includes(key))value=input.value;
     else{value=Number(input.value);if(!Number.isFinite(value))throw Error('无效数字 '+key);}
     // Reading inherited values does not turn them into pinned overrides.
     if(inherited[key]!==undefined&&JSON.stringify(value)===JSON.stringify(inherited[key]))return;
     let target=patch;path.slice(0,-1).forEach(p=>{target[p]=target[p]||{};target=target[p];});target[path[path.length-1]]=value;
    });
    // Keep release limits paired when changing a bound or target height.
    if(['release_min_agl','release_max_agl','drop_agl'].some(key=>key in patch)&&fields.release_min_agl?.value&&fields.release_max_agl?.value){patch.release_min_agl=Number(fields.release_min_agl.value);patch.release_max_agl=Number(fields.release_max_agl.value);}
    // Validate on the local server before persisting anything.
    const body={group_id:g.id,mode:'preview',check_config:true,flight_settings:patch};
    if(!Object.keys(patch).length){
     if(tSessRunning()||scope(g)!==openedScope||JSON.stringify(readBody(g,U))!==openedRequest)throw Error('任务或配置来源已变化，请重新打开参数设置');
     localStorage.removeItem(scope(g));U.flightSettings=null;U.geometryPlans={};U.armedOk=false;U.realConfirm='';renderGroups();dialog.close();dialog.remove();return;
    }
    const r=await fetch('/api/trial/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...trialBody(g,'preview',true),...body,expected_body:undefined})});const v=await r.json();if(!r.ok||!v.ok)throw Error(v.error||'参数校验失败');
    if(tSessRunning()||scope(g)!==openedScope||JSON.stringify(readBody(g,U))!==openedRequest)throw Error('任务或配置来源已变化，请重新打开参数设置');
    localStorage.setItem(scope(g),JSON.stringify(patch));U.flightSettings=patch;U.geometryPlans={};U.armedOk=false;U.realConfirm='';
    await generate(g,U,error);dialog.close();dialog.remove();
   }catch(e){error.textContent=e.message;}
  };
  const close=document.createElement('button');close.className='btn';close.textContent='关闭';close.onclick=()=>{dialog.close();dialog.remove();};dialog.append(save,close);document.body.append(dialog);dialog.showModal();dialog.addEventListener('cancel',()=>dialog.remove());
  loadValues();
 }
 window.FlightSettings={supported,restore,button};
})();
