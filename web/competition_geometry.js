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
function competitionGeometryEditor(g,u,expanded) {
  var box=el('div','geometry-editor'),scope=competitionDraftScope(g),d=u.competitionDraftScope===scope?u.competitionDraft:null;
  var busy=tSessRunning() || !!state.trialPending;
  var bar=el('div','grp-row');
  var toggle=el('input');toggle.type='checkbox';toggle.checked=!!u.geometryEnabled;toggle.disabled=busy || !d;toggle.setAttribute('data-option','competitionGeometry');
  toggle.onchange=function(){u.geometryEnabled=toggle.checked;competitionChanged(u);persist();renderGroups();};
  var label=el('label','chk');label.appendChild(toggle);label.appendChild(el('span',null,'使用编辑后的正赛航点（保留原 YAML）'));bar.appendChild(label);box.appendChild(bar);
  var file=el('input');file.type='file';file.accept='.yaml,.yml';file.hidden=true;
  var importBtn=el('button','btn btn-sm','导入完整场地 YAML');importBtn.disabled=busy;
  importBtn.onclick=function(){file.click();};file.onchange=function(){if(file.files[0]){
    if(file.files[0].size>1048576){toast('warn','YAML 最大1MiB');return;}
    file.files[0].text().then(function(text){return competitionRead(g,text);});
  }};box.appendChild(importBtn);box.appendChild(file);
  var reset=el('button','btn btn-sm','重置为刚读取的 YAML');reset.disabled=busy || !u.competitionSummary || u.competitionSummaryScope!==competitionScope(g);
  reset.onclick=function(){u.competitionDraft=JSON.parse(JSON.stringify(u.competitionSummary.values.geometry));u.competitionDraftScope=scope;u.geometryEnabled=false;competitionChanged(u);try{localStorage.removeItem('competitionDraft:'+scope);}catch(e){}renderGroups();};box.appendChild(reset);
  if(!d){box.appendChild(el('div','tiny muted','先读取所选 YAML 或导入完整场地文件。'));return box;}
  var message=el('div','tiny muted');box.appendChild(message);
  if(!expanded){
    var zoom=el('button','btn btn-sm','放大地图编辑');zoom.onclick=function(){
      var dialog=document.createElement('dialog');dialog.setAttribute('aria-label','正赛航点大地图');
      dialog.style.cssText='width:min(1000px,95vw);max-height:90vh;overflow:auto;background:#14283b;color:#e8f0f8;border:1px solid #56758c';
      var close=el('button','btn btn-sm','关闭大地图');close.onclick=function(){dialog.close();};dialog.appendChild(close);
      dialog.appendChild(competitionGeometryEditor(g,u,true));dialog.onclose=function(){dialog.remove();renderGroups();};document.body.appendChild(dialog);dialog.showModal();
    };box.appendChild(zoom);
  }
  box.appendChild(el('div','tiny muted','XY单位m，相对起飞点；向右+X、向上+Y。黄色=高位搜索，蓝色=走廊，红色=H。高度是飞控中心离地参考高度。'));
  if(u.competitionSummary && !u.competitionSummary.values.site_confirmed)box.appendChild(el('div','warn-line','源文件场地未确认；编辑不会自动确认场地，飞行仍受原入口检查约束。'));
  var map=el('div'),fields=el('div');box.appendChild(map);box.appendChild(fields);
  var selected=u.competitionSelected || {kind:'survey',index:0};
  function points(kind){return kind==='survey'?d.survey_xy:kind==='corridor'?d.corridor_waypoints:null;}
  function point(){var p=points(selected.kind);return p?p[selected.index]:selected.kind==='staging'?d.staging_xy:d.landing_xy;}
  function xy(p){return Array.isArray(p)?p:[p.x,p.y];}
  function edit(x,y){var p=point();if(!p){if(selected.kind==='landing')d.landing_xy=[x,y];else throw Error('请先选择航点');}
    else if(Array.isArray(p)){p[0]=x;p[1]=y;}else {p.x=x;p.y=y;} changed();}
  function persist(){try{localStorage.setItem('competitionDraft:'+scope,JSON.stringify({geometry:d,enabled:!!u.geometryEnabled}));}catch(e){message.textContent='浏览器无法保存草稿，请导出JSON备份';}}
  function changed(){competitionChanged(u);u.geometryValues=JSON.parse(JSON.stringify(d));persist();message.textContent='草稿已改动，请重新生成坐标命令。';draw();renderFields();}
  function button(text,fn){var b=el('button','btn btn-sm',text);b.disabled=busy;b.onclick=function(){try{fn();}catch(e){message.textContent=e.message;}};return b;}
  function renderFields(){fields.replaceChildren();
    var selector=el('select');selector.setAttribute('data-competition','selection');selector.disabled=busy;
    [['survey','搜索'],['corridor','走廊']].forEach(function(pair){(points(pair[0]) || []).forEach(function(p,i){var o=el('option',null,pair[1]+' '+(i+1));o.value=pair[0]+':'+i;selector.appendChild(o);});});
    [['staging','准备点'],['landing','H中心']].forEach(function(pair){var o=el('option',null,pair[1]);o.value=pair[0]+':0';selector.appendChild(o);});
    selector.value=selected.kind+':'+selected.index;selector.onchange=function(){var p=selector.value.split(':');selected={kind:p[0],index:Number(p[1])};u.competitionSelected=selected;draw();renderFields();};fields.appendChild(selector);
    function input(title,value,fn,key){var l=el('label','geometry-field');l.appendChild(el('span',null,title));var f=el('input');f.type='number';f.step='0.01';f.value=value;f.disabled=busy;f.setAttribute('data-competition',key || title);
      f.onchange=function(){if(!Number.isFinite(f.valueAsNumber)){message.textContent='请输入有限数值';return;}fn(f.valueAsNumber);};l.appendChild(f);fields.appendChild(l);}
    var p=point();if(p){var v=xy(p);input('X',v[0],function(x){edit(x,xy(point())[1]);},'x');input('Y',v[1],function(y){edit(xy(point())[0],y);},'y');
      if(selected.kind==='corridor')input('走廊 FC AGL',p.agl,function(z){point().agl=z;changed();},'agl');}
    input('高位搜索 FC AGL',d.high_agl,function(z){d.high_agl=z;changed();},'high_agl');
    input('H 接近 FC AGL',d.landing_transit_agl,function(z){d.landing_transit_agl=z;changed();},'landing_transit_agl');
    input('H 识别 FC AGL',d.landing_capture_agl,function(z){d.landing_capture_agl=z;changed();},'landing_capture_agl');
    ['survey','corridor'].forEach(function(kind){fields.appendChild(button('添加'+(kind==='survey'?'搜索点':'走廊点'),function(){var b=d.search_center_bounds || d.flight_bounds;var p=[(b[0]+b[1])/2,(b[2]+b[3])/2];
      if(kind==='survey' && d.survey_xy.length>=8)throw Error('高位搜索最多8个点');
      points(kind).push(kind==='survey'?p:{x:p[0],y:p[1],agl:d.landing_transit_agl});selected={kind:kind,index:points(kind).length-1};u.competitionSelected=selected;changed();}));});
    if(points(selected.kind)){
      [-1,1].forEach(function(delta){fields.appendChild(button(delta<0?'上移':'下移',function(){var a=points(selected.kind),i=selected.index,j=i+delta;if(j<0 || j>=a.length)return;var t=a[i];a[i]=a[j];a[j]=t;selected.index=j;changed();}));});
      fields.appendChild(button('删除选中点',function(){points(selected.kind).splice(selected.index,1);selected.index=Math.max(0,selected.index-1);changed();}));
    }
    fields.appendChild(el('div','tiny muted','点击图上航点选择，拖动修改XY；H未设置时选择“H中心”并点击地图设置。')); 
    [['flight_bounds','飞行范围'],['search_center_bounds','搜索中心范围'],['target_bounds','目标范围'],['coverage_bounds','覆盖范围']].forEach(function(pair){
      var l=el('label','geometry-field');l.appendChild(el('span',null,pair[1]+' [xmin,xmax,ymin,ymax]'));var f=el('input');f.value=(d[pair[0]] || []).join(', ');f.disabled=busy;
      f.onchange=function(){var values=f.value.split(/[\s,，]+/).filter(Boolean).map(Number);if(values.length!==4 || values.some(function(v){return !Number.isFinite(v);})){message.textContent='范围需要4个有限数值';return;}d[pair[0]]=values;changed();};l.appendChild(f);fields.appendChild(l);
    });
    var wall=el('label','geometry-field');wall.appendChild(el('span',null,'墙面几何 JSON（axis、wall_coordinates、entry_waypoints；null 表示无）'));
    var w=el('textarea');w.value=JSON.stringify(d.corridor_speed_schedule);w.disabled=busy;w.onchange=function(){try{d.corridor_speed_schedule=JSON.parse(w.value);changed();}catch(e){message.textContent='墙面JSON格式无效';}};wall.appendChild(w);fields.appendChild(wall);
  }
  function draw(){map.replaceChildren();var b=d.flight_bounds;if(!b || b.length!==4 || b[1]<=b[0] || b[3]<=b[2])return;
    var ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg'),scale=Math.max(b[1]-b[0],b[3]-b[2]),pad=scale*.08;
    svg.setAttribute('viewBox',[b[0]-pad,-b[3]-pad,b[1]-b[0]+pad*2,b[3]-b[2]+pad*2].join(' '));svg.setAttribute('aria-label','独立正赛航点地图');svg.style.width='100%';svg.style.height=expanded?'520px':'340px';svg.style.background='#14283b';svg.style.touchAction='none';
    function item(name,attrs){var e=document.createElementNS(ns,name);Object.keys(attrs).forEach(function(k){e.setAttribute(k,attrs[k]);});svg.appendChild(e);return e;}
    item('rect',{x:b[0],y:-b[3],width:b[1]-b[0],height:b[3]-b[2],fill:'none',stroke:'#9ab0c6','stroke-width':scale*.004});
    var sb=d.search_center_bounds;if(sb && sb[1]>sb[0] && sb[3]>sb[2])item('rect',{x:sb[0],y:-sb[3],width:sb[1]-sb[0],height:sb[3]-sb[2],fill:'none',stroke:'#728da4','stroke-width':scale*.003,'stroke-dasharray':scale*.02});
    var schedule=d.corridor_speed_schedule;if(schedule && Array.isArray(schedule.wall_coordinates))schedule.wall_coordinates.forEach(function(v){item('line',{x1:schedule.axis===0?v:b[0],y1:schedule.axis===1?-v:-b[2],x2:schedule.axis===0?v:b[1],y2:schedule.axis===1?-v:-b[3],stroke:'#c48772','stroke-width':scale*.003,'stroke-dasharray':scale*.015});});
    item('text',{x:0,y:0,fill:'#fff','font-size':scale*.026}).textContent='起飞(0,0)';
    function mark(p,kind,i,color,label){if(!p)return;var v=xy(p),active=selected.kind===kind && selected.index===i;
      var c=item('circle',{cx:v[0],cy:-v[1],r:scale*(active?.019:.012),fill:color,stroke:active?'white':color,'stroke-width':scale*.004});c.dataset.kind=kind;c.dataset.index=i;
      item('text',{x:v[0]+scale*.016,y:-v[1]-scale*.014,fill:color,'font-size':scale*.024,'pointer-events':'none'}).textContent=label;
    }
    [['survey',d.survey_xy,'#ffc65b','S'],['corridor',d.corridor_waypoints,'#69bdff','C']].forEach(function(a){var ps=a[1] || [];
      item('polyline',{points:ps.map(function(p){var v=xy(p);return v[0]+','+-v[1];}).join(' '),fill:'none',stroke:a[2],'stroke-width':scale*.004});ps.forEach(function(p,i){mark(p,a[0],i,a[2],a[3]+(i+1)+(a[0]==='corridor'?' '+p.agl+'m':''));});});
    mark(d.staging_xy,'staging',0,'#7fe0a5','准备');mark(d.landing_xy,'landing',0,'#ff8e97','H');
    var drag=null;
    function location(e){var p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;var v=p.matrixTransform(svg.getScreenCTM().inverse());return [Math.round(v.x*100)/100,Math.round(-v.y*100)/100];}
    svg.onpointerdown=function(e){if(busy)return;var kind=e.target.dataset.kind;if(!kind)return;
      selected={kind:kind,index:Number(e.target.dataset.index)};u.competitionSelected=selected;drag={id:e.pointerId,x:e.clientX,y:e.clientY,marker:e.target};svg.setPointerCapture(e.pointerId);renderFields();};
    svg.onpointermove=function(e){if(!drag)return;var p=location(e);drag.marker.setAttribute('cx',p[0]);drag.marker.setAttribute('cy',-p[1]);};
    svg.onpointerup=function(e){if(busy)return;if(drag){var moved=Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>3;drag=null;if(moved){var p=location(e);edit(p[0],p[1]);}else draw();}
      else if(selected.kind==='landing' || selected.kind==='staging'){var p=location(e);edit(p[0],p[1]);}};
    svg.onpointercancel=function(){drag=null;draw();};map.appendChild(svg);
  }
  draw();renderFields();
  box.appendChild(button('生成并预览正赛坐标命令',function(){
    if(!u.geometryEnabled)throw Error('请先勾选使用编辑后的正赛航点');
    u.geometryValues=JSON.parse(JSON.stringify(d));u.geometryRevision=Date.now().toString(36);u.geometryPlans={};var revision=u.geometryRevision;
    message.textContent='正在生成命令（不启动节点）…';
    var requests=[trialBody(g,'preview',true),trialBody(g,'preview',false),trialBody(g,'flight',false)];
    Promise.all(requests.map(function(body){delete body.expected_body;delete body.confirm;
      return fetch('/api/trial/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
        .then(function(r){return r.json().then(function(v){if(!r.ok || !v.ok)throw Error(v.error || '命令生成失败');return [geometryPlanKey(g,body.mode,body.real_release,!!body.check_config,body.capture_speed,body),v];});});
    })).then(function(plans){if(u.geometryRevision!==revision || competitionDraftScope(g)!==scope)return;
      plans.forEach(function(p){u.geometryPlans[p[0]]=p[1];});persist();message.textContent='命令已生成；关闭地图后进行配置检查。';renderGroups();
    }).catch(function(e){message.textContent=e.message;u.geometryPlans={};});
  }));
  box.appendChild(button('导出坐标草稿 JSON',function(){var blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='competition_waypoints.json';a.click();setTimeout(function(){URL.revokeObjectURL(url);},1000);}));
  box.appendChild(el('div','tiny muted',Object.keys(u.geometryPlans || {}).length?'命令已生成。点击原配置检查核对，再按原预览/实投流程启动。':'执行时生成独立YAML并校验；源文件变更会拒绝旧草稿，须重新读取。'));
  return box;
}
