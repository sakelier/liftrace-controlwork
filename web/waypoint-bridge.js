/* A map draft enters the existing geometry-command pipeline, never a flight API. */
(function(){
  'use strict';
  const supported=g=>g.channel==='module'&&['04_corridor_landing','05_low_multi','08_full_mission'].includes(g.folder);
  const scope=g=>JSON.stringify([state.connection?.host,state.connection?.board_root,state.connection?.site_dir,g.id,g.site_config]);
  let dialog,frame,active;
  async function request(path,body){const r=await fetch('/api/waypoints/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok||data.ok===false)throw Error(data.error||'航点读取失败');return data;}
  function populate(g,U,data){
    const p=data.patch;U.geometryEnabled=true;U.geometryValues=p;U.geometryRevision=data.revision;U.geometryPlans={};U.surveyEnabled=false;U.surveyPreview=null;U.pattern='';
    U.geometryPoints=p.corridor_waypoints.map(v=>[v.x,v.y,v.agl].join(', ')).join('\n');U.geometryLanding=p.landing_xy.join(', ');
    U.geometrySearch=(p.search_waypoints_xy||[]).map(v=>v.join(', ')).join('\n');
    U.geometryArea=JSON.stringify(p.flight_area,null,2);U.geometryAxis=String(p.corridor_geometry?.wall_axis??1);U.geometryWalls=(p.corridor_geometry?.wall_coordinates||[]).join(', ');U.geometryEntry=String(p.corridor_geometry?.entry_waypoints??1);
    U.waypointDraftScope=scope(g);U.waypointServerScope=data.scope;U.waypointDraftApplied=true;U.armedOk=false;U.realConfirm='';
  }
  function generate(g){const button=document.querySelector('[data-waypoint-command="'+g.id+'"]');if(button)button.click();}
  function restore(g,U){
    if(!supported(g))return;const key=scope(g);if(U.waypointLoadedScope===key)return;U.waypointLoadedScope=key;
    // Changing board/root never transfers the preceding board's map draft.
    if(U.waypointDraftScope&&U.waypointDraftScope!==key){U.geometryEnabled=false;U.geometryValues=null;U.geometryRevision=null;U.geometryPlans={};U.waypointDraftApplied=false;U.geometryPoints=U.geometryLanding=U.geometryWalls=U.geometryArea='';U.waypointServerScope=null;}
    request('draft',{group_id:g.id}).then(data=>{if(U.waypointLoadedScope!==key||scope(g)!==key)return;if(data.draft&&data.draft.enabled!==false){populate(g,U,data.draft);renderGroups();generate(g);}}).catch(e=>{U.waypointLoadError=e.message;});
  }
  function close(){if(dialog){dialog.close();dialog.remove();}dialog=frame=active=null;}
  function sendContext(){if(active?.context&&frame)frame.contentWindow.postMessage({type:'waypoint-context',context:active.context},location.origin);}
  async function open(g,U,localFile){
    if(tSessRunning()){alert('任务正在运行，请结束后再调整航点。');return;}
    close();dialog=document.createElement('dialog');dialog.className='waypoint-dialog';dialog.setAttribute('aria-label','飞行前调整航点');
    const head=document.createElement('div');head.className='waypoint-dialog-head';const title=document.createElement('strong');title.textContent=g.name+' · 地图调整';const cancel=document.createElement('button');cancel.className='btn';cancel.textContent='关闭';cancel.onclick=close;head.append(title,cancel);
    const note=document.createElement('p');note.className='waypoint-dialog-note';note.textContent='正在读取所选现场配置与本机草稿…';
    frame=document.createElement('iframe');frame.title='航点地图与坐标微调';frame.src='/static/waypoint-map.html';
    dialog.append(head,note,frame);document.body.append(dialog);dialog.showModal();dialog.addEventListener('cancel',close);
    const key=scope(g);active={g,U,key,note,localFile};
    try{const context=await request('context',{group_id:g.id,...(U.geometryEnabled&&U.geometryValues?{site_geometry:U.geometryValues}:{})});if(!active||active.key!==key)return;active.context=context;note.textContent=context.origin+' · '+context.source;sendContext();}
    catch(e){if(active){note.textContent=e.message;note.classList.add('error');}}
  }
  window.addEventListener('message',async event=>{
    if(!active||event.origin!==location.origin||event.source!==frame?.contentWindow)return;
    if(event.data?.type==='waypoint-ready')return sendContext();
    if(event.data?.type==='waypoint-context-ready'){if(active.localFile&&!active.fileSent){active.fileSent=true;frame.contentWindow.postMessage({type:'waypoint-load-local',...active.localFile},location.origin);}return;}
    if(event.data?.type==='waypoint-cancel')return close();
    if(event.data?.type==='waypoint-imported'){active.importName=event.data.name;active.note.textContent=event.data.name?'本机导入：'+event.data.name+' · 尚待保存用于本组；原现场配置路径保留。':active.context?active.context.origin+' · '+active.context.source:'正在读取所选现场配置…';return;}
    if(event.data?.type!=='waypoint-apply')return;
    const task=active;
    try{
      if(scope(task.g)!==task.key)throw Error('连接设置已变化，请重新打开地图');
      if(tSessRunning())throw Error('任务正在运行，请结束后再应用航点');
      const data=await request('save',{group_id:task.g.id,scope:task.context.scope,site:event.data.site,import_name:event.data.import_name});
      if(active!==task||scope(task.g)!==task.key)return;
      populate(task.g,task.U,data);close();renderGroups();generate(task.g);
    }catch(e){frame?.contentWindow.postMessage({type:'waypoint-error',error:e.message},location.origin);}
  });
  function button(g,U){const wrap=document.createElement('div');wrap.className='waypoint-entry';const openButton=document.createElement('button');openButton.className='btn btn-sm waypoint-open';openButton.textContent='地图调整航点';openButton.disabled=tSessRunning();openButton.onclick=()=>open(g,U);wrap.append(openButton);
    const fileInput=document.createElement('input');fileInput.type='file';fileInput.accept='.yaml,.yml';fileInput.hidden=true;const importButton=document.createElement('button');importButton.className='btn btn-sm';importButton.textContent='从本机导入航点 YAML';importButton.disabled=tSessRunning();importButton.onclick=()=>fileInput.click();fileInput.onchange=async()=>{const file=fileInput.files[0];if(!file)return;try{if(file.size>2*1024*1024)throw Error('配置文件不能超过2MiB');await open(g,U,{name:file.name,text:await file.text()});}catch(e){alert(e.message);}fileInput.value='';};wrap.append(importButton,fileInput);
    const note=document.createElement('p');note.className='tiny muted';note.textContent=U.waypointDraftApplied&&U.geometryEnabled?'已应用本机地图草稿；请核对下方命令并运行配置检查。':'点击地图布点，或从PC导入航点与地图YAML；地图窗口也可导出备份。';wrap.append(note);
    if(U.waypointDraftApplied){const reset=document.createElement('button');reset.className='btn btn-sm';reset.textContent='使用原现场配置';reset.disabled=tSessRunning();reset.onclick=async()=>{try{await request('disable',{group_id:g.id,scope:U.waypointServerScope});U.geometryEnabled=false;U.geometryValues=null;U.geometryPlans={};U.geometryRevision=null;U.waypointDraftApplied=false;U.armedOk=false;U.realConfirm='';renderGroups();}catch(e){alert(e.message);}};wrap.append(reset);}return wrap;}
  window.WaypointWorkbench={supported,restore,button};
})();
