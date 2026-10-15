'use strict';
const rows=[],statusLine=document.querySelector('#status'),resultBox=document.querySelector('#result');
const pending={set:0,start:0,stop:0,close:0};
let latest=null,actionSerial=0,resultSerial=0,refreshSerial=0;
const anyPending=()=>Object.values(pending).some(Boolean);
async function api(action,body={}){
 const response=await fetch('/api/servo/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const value=await response.json();
 if(!response.ok||value.ok===false)throw Error(value.error||value.message||'操作失败');
 return value;
}
function controls(){
 rows.forEach((row,i)=>{
  row.send.disabled=anyPending()||!latest?.control_ready||!document.querySelector('#ground').checked;
  row.initial.disabled=!Number.isFinite(latest?.initial_ns?.[i]);
  row.release.disabled=!Number.isFinite(latest?.release_ns?.[i]);
 });
 document.querySelector('#start').disabled=anyPending()||!latest?.query_ok||!!latest?.raw_active;
 // Stop remains available while a send is pending, and blocks new sends.
 document.querySelector('#stop').disabled=!!(pending.start||pending.stop||pending.close)||!latest?.stop_available;
 document.querySelector('#close').disabled=!!(pending.start||pending.stop||pending.close)||!latest?.shutdown_available;
}
async function refresh(){
 const serial=++refreshSerial;
 try{
  const value=await api('status');if(serial!==refreshSerial)return;latest=value;
  const source={managed:'工作台后端',external:'外部调试后端',none:'未启动'}[latest.backend_source]||'未知来源';
  statusLine.textContent=latest.control_ready?'调试服务已就绪 · '+source:(latest.blocking_reason||'调试服务尚未就绪');
  document.querySelector('#backend-log').textContent=latest.backend_output||'尚未启动工作台调试会话';
  latest.channels.forEach((channel,i)=>{
   const output=channel.enable_value==='1'?'开启':channel.enable_value==='0'?'关闭':'读回未确认';
   rows[i].actual.textContent='实际脉宽：'+(channel.duty_cycle_ns==null?'不可读':(channel.duty_cycle_ns/1e6).toFixed(3)+' ms')+' · 输出：'+output;
  });
 }catch(error){if(serial!==refreshSerial)return;latest=null;statusLine.textContent=error.message;}
 controls();
}
async function action(name,body={}){
 if(name==='stop'||name==='close'){
  if(pending.stop||pending.close||pending.start)return;
 }else if(anyPending())return;
 const serial=++actionSerial;resultSerial=serial;pending[name]++;controls();
 try{
  const result=await api(name,{confirm:'舵机调试',...body});
  if(serial===resultSerial)resultBox.textContent=JSON.stringify(result,null,2);
 }catch(error){if(serial===resultSerial)resultBox.textContent=error.message;}
 finally{pending[name]--;await refresh();controls();}
}
for(let i=0;i<3;i++){
 const card=document.createElement('section');card.className='servo-card';
 card.innerHTML='<h2>'+['1 · 后仓','2 · 右仓','3 · 左仓'][i]+'</h2><p class="actual">尚未读取实际状态</p><input type="range" min="0.5" max="2.5" step="0.01" value="1.5" aria-label="'+(i+1)+'号脉宽滑块"><label>脉宽 <input type="number" min="0.5" max="2.5" step="0.01" value="1.5" aria-label="'+(i+1)+'号脉宽毫秒"> ms</label><p>持续输出：发送后保持当前 PWM，需主动关闭输出或退出调试。</p><div><button class="send" disabled>发送到该舵机</button><button class="initial" disabled>填入归位值</button><button class="release" disabled>填入释放值</button></div>';
 document.querySelector('#channels').append(card);
 const range=card.querySelector('input[type=range]'),number=card.querySelector('input[type=number]');
 const row={actual:card.querySelector('.actual'),send:card.querySelector('.send'),initial:card.querySelector('.initial'),release:card.querySelector('.release')};rows.push(row);
 range.oninput=()=>number.value=range.value;number.oninput=()=>range.value=number.value;
 for(const [cls,key] of [['initial','initial_ns'],['release','release_ns']])row[cls].onclick=()=>{
  if(!Number.isFinite(latest?.[key]?.[i]))return;
  number.value=range.value=latest[key][i]/1e6;
 };
 row.send.onclick=()=>{
  if(row.send.disabled)return;
  const ms=Number(number.value);
  if(!Number.isFinite(ms)||ms<.5||ms>2.5){resultBox.textContent='脉宽须在0.5～2.5 ms之间';return;}
  if(!window.confirm('实际操作'+(i+1)+'号舵机：'+ms+' ms，持续输出直到主动发送新值、关闭输出或退出调试。关闭页面不会停止输出。确认执行？'))return;
  action('set',{slot:i+1,duty_cycle_ns:Math.round(ms*1e6),hold:true});
 };
}
document.querySelector('#ground').onchange=controls;
document.querySelector('#refresh').onclick=refresh;
document.querySelector('#start').onclick=()=>{if(window.confirm('仅启动板端调试节点；不会自动归位或释放。确认启动？'))action('start');};
document.querySelector('#stop').onclick=()=>action('stop');
document.querySelector('#close').onclick=()=>action('close');
controls();refresh();setInterval(()=>{if(!document.hidden&&!anyPending())refresh();},3000);
