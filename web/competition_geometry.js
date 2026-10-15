/* Independent competition geometry. Uses the existing command/confirmation lane. */
function competitionScope(g) {
  var c=state.connection || {},u=groupUI(g);
  return JSON.stringify([c.host,c.board_root,c.state,c.transport,u.competitionConfig || g.site_config]);
}
function competitionDraftScope(g) {
  var c=state.connection || {},u=groupUI(g);
  return JSON.stringify([c.host,c.board_root,u.competitionConfig || g.site_config]);
}
function competitionChanged(u) {
  u.geometryPlans={};u.geometryRevision=null;u.armedOk=false;u.realConfirm='';
}
function competitionRead(g,text) {
  var u=groupUI(g),scope=competitionScope(g),body={group_id:g.id,competition_config:u.competitionConfig || g.site_config};
  if(text!==undefined)body.yaml_text=text;
  u.competitionReadScope=scope;u.competitionLoading=true;u.competitionError='';
  return fetch('/api/competition/config-summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json().then(function(v){if(!r.ok || !v.ok)throw Error(v.error || '配置读取失败');return v;});})
    .then(function(v){if(competitionScope(g)!==scope)return;
      u.competitionSummary=v;u.competitionSummaryScope=scope;
      // Refreshing a source never silently replaces an edited geometry draft.
      if(!u.competitionDraft || u.competitionDraftScope!==competitionDraftScope(g)) {
        u.competitionDraft=JSON.parse(JSON.stringify(v.values.geometry));u.competitionDraftScope=competitionDraftScope(g);
        u.geometryEnabled=false;competitionChanged(u);
      }
      if(text!==undefined){u.competitionDraft=JSON.parse(JSON.stringify(v.values.geometry));u.competitionDraftScope=competitionDraftScope(g);u.geometryEnabled=false;competitionChanged(u);}
    }).catch(function(e){if(competitionScope(g)===scope)u.competitionError=e.message;})
    .finally(function(){if(competitionScope(g)===scope){u.competitionLoading=false;renderGroups();}});
}
function competitionSwitchText(u,key,override) {
  var v=u.competitionSummary && u.competitionSummary.values[key];
  if(!v)return 'YAML：尚未读取';
  var raw=v.value===null?'未配置':(v.value?'开启':'关闭');
  if(!v.configured && v.value!==null)raw+='（缺省值）';
  return 'YAML：'+raw+' → 本次：'+(override==='on'?'显式开启':override==='off'?'显式关闭':'继承，'+raw);
}
function competitionOptionsPanel(g,u) {
  var box=el('div','geometry-editor');
  if(!u.competitionDraft || u.competitionDraftScope!==competitionDraftScope(g)) {
    try {var saved=JSON.parse(localStorage.getItem('competitionDraft:'+competitionDraftScope(g)) || 'null');
      if(saved){u.competitionDraft=saved.geometry;u.competitionDraftScope=competitionDraftScope(g);u.geometryEnabled=!!saved.enabled;u.geometryValues=saved.geometry;u.geometryPlans={};u.geometryRevision=null;}
    } catch(e) {}
  }
  if(u.competitionReadScope!==competitionScope(g))competitionRead(g);
  var current=u.competitionSummaryScope===competitionScope(g);
  box.appendChild(el('div','tiny muted',u.competitionLoading?'正在只读读取所选 YAML…':u.competitionError ||
    (current?({'board_yaml':'板端所选 YAML','pc_yaml':'PC仓库 YAML（未核对板端）','offline_reference':'随包离线参考（未核对板端）','local_import':'本机导入 YAML（执行前核对板端源文件）'}[u.competitionSummary.source]):'尚未读取当前配置')));
  if(current){
    [['运动优化','motion_optimization',u.motionOptimization],['障碍柱','obstacle_columns',u.obstacleColumns],['高位续扫','resume_survey',u.resume]].forEach(function(p){
      box.appendChild(el('div','tiny',p[0]+' · '+competitionSwitchText(u,p[1],p[2])));
    });
    box.appendChild(el('div','tiny muted','这是文件值与本次请求；已生成的实际值仍以配置检查输出为准。'));
  }
  var read=el('button','btn btn-sm','重新读取所选 YAML');read.disabled=!!u.competitionLoading;
  read.onclick=function(){competitionRead(g);};box.appendChild(read);
  box.appendChild(el('div','tiny muted','运动优化：走廊衔接/共线点合并、恢复与边界减速等策略；不会直接提高速度上限。'));
  box.appendChild(el('div','tiny muted','障碍柱：启用配置的竖直障碍区域，限制从上方越过；关闭后真实点云避障仍保留。'));
  box.appendChild(el('div','tiny muted','高位续扫：投递中断高位搜索后，条件允许时回高位续扫，最多一次，仍受任务预算限制。'));
  return box;
}
function competitionGeometryEditor(g,u) {
  var box=el('div','waypoint-entry'),dialog,frame,context,key=competitionDraftScope(g);
  function request(action,body){return fetch('/api/competition-map/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){return r.json().then(function(v){if(!r.ok || !v.ok)throw Error(v.error || '地图请求失败');return v;});});}
  function close(){if(dialog){dialog.close();dialog.remove();}window.removeEventListener('message',message);dialog=frame=null;}
  function send(){if(context && frame)frame.contentWindow.postMessage({type:'waypoint-context',context:context},location.origin);}
  function generate(){var requests=[trialBody(g,'preview',true),trialBody(g,'preview',false),trialBody(g,'flight',false)],revision=u.geometryRevision;
    Promise.all(requests.map(function(body){delete body.confirm;delete body.expected_body;return fetch('/api/trial/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(function(r){return r.json().then(function(v){if(!r.ok || !v.ok)throw Error(v.error || '命令生成失败');return [geometryPlanKey(g,body.mode,body.real_release,!!body.check_config,body.capture_speed,body),v];});});}))
      .then(function(plans){if(competitionDraftScope(g)!==key || u.geometryRevision!==revision)return;plans.forEach(function(p){u.geometryPlans[p[0]]=p[1];});renderGroups();}).catch(function(e){toast('warn',e.message);});
  }
  var localFile=null,fileSent=false;
  function message(event){if(!frame || event.origin!==location.origin || event.source!==frame.contentWindow)return;
    if(event.data.type==='waypoint-ready')return send();
    if(event.data.type==='waypoint-context-ready' && localFile && !fileSent){fileSent=true;frame.contentWindow.postMessage({type:'waypoint-load-local',name:localFile.name,text:localFile.text},location.origin);}
    if(event.data.type==='waypoint-cancel')return close();
    if(event.data.type!=='waypoint-apply')return;
    if(tSessRunning() || key!==competitionDraftScope(g)){frame.contentWindow.postMessage({type:'waypoint-error',error:'任务/连接状态已改变，请重新打开地图'},location.origin);return;}
    request('save',{group_id:g.id,competition_config:u.competitionConfig || g.site_config,scope:context.scope,site:event.data.site}).then(function(v){
      if(key!==competitionDraftScope(g))return;
      u.geometryEnabled=true;u.geometryValues=v.patch;u.geometryRevision=v.revision;u.geometryPlans={};u.competitionDraft=v.patch;u.competitionDraftScope=key;u.armedOk=false;u.realConfirm='';
      try{localStorage.setItem('competitionDraft:'+key,JSON.stringify({geometry:v.patch,enabled:true}));}catch(e){}
      close();renderGroups();generate();
    }).catch(function(e){if(frame)frame.contentWindow.postMessage({type:'waypoint-error',error:e.message},location.origin);});
  }
  function open(file){if(tSessRunning()){toast('warn','任务运行中不能修改航点');return;}
    close();localFile=file;fileSent=false;context=null;dialog=document.createElement('dialog');dialog.className='waypoint-dialog';dialog.setAttribute('aria-label','飞行前调整航点');
    var head=el('div','waypoint-dialog-head');head.appendChild(el('strong',null,g.name+' · 地图调整'));var cancel=el('button','btn','关闭');cancel.onclick=close;head.appendChild(cancel);
    var note=el('p','waypoint-dialog-note','正在读取所选场地配置与本机草稿…');frame=document.createElement('iframe');frame.title='航点地图与坐标微调';frame.src='/static/waypoint-map.html';
    dialog.appendChild(head);dialog.appendChild(note);dialog.appendChild(frame);document.body.appendChild(dialog);window.addEventListener('message',message);dialog.addEventListener('cancel',close);dialog.showModal();
    request('context',{group_id:g.id,competition_config:u.competitionConfig || g.site_config,...(u.geometryEnabled && u.geometryValues ? {site_geometry:u.geometryValues}:{})}).then(function(v){if(!dialog || key!==competitionDraftScope(g))return;context=v;note.textContent=v.origin+' · '+v.source;send();}).catch(function(e){note.textContent=e.message;note.classList.add('error');});
  }
  var button=el('button','btn btn-sm waypoint-open','地图调整航点');button.disabled=tSessRunning();button.onclick=function(){open();};box.appendChild(button);
  var input=el('input');input.type='file';input.accept='.yaml,.yml';input.hidden=true;var importButton=el('button','btn btn-sm','从本机导入航点 YAML');importButton.disabled=tSessRunning();importButton.onclick=function(){input.click();};
  input.onchange=function(){var f=input.files[0];if(!f)return;if(f.size>2097152){toast('warn','YAML最大2MiB');return;}f.text().then(function(text){open({name:f.name,text:text});});input.value='';};box.appendChild(importButton);box.appendChild(input);
  box.appendChild(el('p','tiny muted',u.geometryEnabled?'已应用本机地图草稿；请核对下方命令并运行配置检查。':'点击地图布点，或导入正赛航点YAML；操作窗口与任务08相同。'));
  if(u.geometryEnabled){var reset=el('button','btn btn-sm','使用原现场配置');reset.disabled=tSessRunning();reset.onclick=function(){u.geometryEnabled=false;competitionChanged(u);try{localStorage.setItem('competitionDraft:'+key,JSON.stringify({geometry:u.competitionDraft,enabled:false}));}catch(e){}renderGroups();};box.appendChild(reset);}
  return box;
}


function competitionFilePicker(g) {
  if(tSessRunning()){toast('warn','任务运行中不能切换配置');return;}
  var u=groupUI(g),connectionKey=JSON.stringify(state.connection || {});
  var dialog=el('dialog','competition-file-dialog');dialog.setAttribute('aria-label','选择场地 YAML');
  var head=el('div','waypoint-dialog-head');head.appendChild(el('strong',null,'选择场地 YAML'));
  var close=el('button','btn','关闭');close.onclick=function(){dialog.close();dialog.remove();};head.appendChild(close);dialog.appendChild(head);
  var shortcuts=el('div','competition-file-shortcuts');
  [['正赛配置','deployment/competition'],['已生成配置','logs/flight_workbench/site_overlays'],['工程目录','.']].forEach(function(pair){var b=el('button','btn btn-sm',pair[0]);b.onclick=function(){load(pair[1]);};shortcuts.appendChild(b);});dialog.appendChild(shortcuts);
  var origin=el('p','tiny muted'),nav=el('div','competition-file-nav'),list=el('div','competition-file-list');
  dialog.appendChild(origin);dialog.appendChild(nav);dialog.appendChild(list);document.body.appendChild(dialog);
  dialog.addEventListener('cancel',function(){dialog.remove();});dialog.showModal();
  var serial=0;
  function load(directory){
    var requestId=++serial;origin.textContent='正在读取文件夹…';list.replaceChildren();nav.replaceChildren();
    fetch('/api/competition/config-files',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group_id:g.id,directory:directory})})
      .then(function(r){return r.json().then(function(v){if(!r.ok || !v.ok)throw Error(v.error || '文件夹读取失败');return v;});})
      .then(function(v){if(!dialog.isConnected || requestId!==serial)return;
        if(connectionKey!==JSON.stringify(state.connection || {}))throw Error('连接已改变，请关闭后重新选择');
        origin.textContent=({'board_yaml':'香橙派工程文件','pc_yaml':'PC工程文件（未核对板端）','offline_reference':'随包参考文件（未核对板端）'}[v.source])+'。选择后将读取配置，执行前请配置检查。';
        if(v.parent!==null){var up=el('button','btn btn-sm','上一级');up.onclick=function(){load(v.parent);};nav.appendChild(up);}
        nav.appendChild(el('span',null,v.directory==='.'?'工程目录':v.directory));
        if(!v.entries.length)list.appendChild(el('p','muted','此目录没有文件夹或 YAML 文件。'));
        v.entries.forEach(function(item){
          var row=el('button','competition-file-item');row.type='button';
          row.appendChild(el('span','competition-file-kind',item.kind==='folder'?'文件夹':'YAML'));
          row.appendChild(el('span','competition-file-name',item.name));
          row.onclick=function(){if(item.kind==='folder')return load(item.path);
            if(tSessRunning() || connectionKey!==JSON.stringify(state.connection || {})){toast('warn','任务或连接状态已改变，请重新选择');return;}
            u.competitionConfig=item.path;u.geometryEnabled=false;competitionChanged(u);u.competitionReadScope=null;
            dialog.close();dialog.remove();renderGroups();
          };list.appendChild(row);
        });
      }).catch(function(e){if(dialog.isConnected && requestId===serial){origin.textContent=e.message;list.replaceChildren();}});
  }
  var selected=u.competitionConfig || g.site_config || '';var split=selected.lastIndexOf('/');
  load(split>=0?selected.slice(0,split):'deployment/competition');
}
