"""SSH bridge to the exclusive board-side servo transactions; no sysfs writes."""
import base64
from functools import wraps
import json
import threading
import time

import wb_board
from wb_ssh import quote

REMOTE = r'''
import json, os, pathlib, re, sys, time
root=pathlib.Path.cwd()
request=json.loads(sys.argv[1]); action=request['action']
devices=['febf0000.pwm','febf0020.pwm','febf0010.pwm']
paths=[]
for device in devices:
    matches=[p/'pwm0' for p in pathlib.Path('/sys/class/pwm').glob('pwmchip*') if '/'+device+'/' in p.resolve().as_posix()]
    paths.append(matches[0] if len(matches)==1 else None)
def read(path,name):
    try:return (path/name).read_text().strip()
    except (OSError,TypeError):return None
def channels():
    result=[]
    for i,p in enumerate(paths):
        try:duty=int(read(p,'duty_cycle'))
        except (TypeError,ValueError):duty=None
        enable=read(p,'enable')
        result.append(dict(slot=i+1,duty_cycle_ns=duty,enabled=enable=='1',enable_value=enable,
            initialized=read(p,'period')=='20000000' and read(p,'polarity')=='normal' and enable in ('0','1') and duty is not None))
    return result
SET='/SetServoDuty'; STOP='/servo_debug/stop'; SHUTDOWN='/servo_debug/shutdown'
def services():
    result=dict(query_ok=False,service_available=False,stop_available=False,shutdown_available=False,
        debug_active=False,raw_active=False,provider=None,blocking_reason='')
    try:
        import rosgraph, rosservice
        registered=dict(rosgraph.Master('/workbench_servo_status').getSystemState()[2])
        result['debug_active']=any(registered.get(name) for name in (SET,STOP,SHUTDOWN))
        result['raw_active']=any(registered.get(name) for name in ('/legacy/Servo_raw','/Servo'))
        provider=registered.get(SET,[])
        result['provider']=provider[0] if len(provider)==1 else None
        expected={SET:'patrol_control/SetServoDuty',STOP:'std_srvs/Trigger',SHUTDOWN:'std_srvs/Trigger'}
        typed={name:bool(registered.get(name)) and rosservice.get_service_type(name)==kind for name,kind in expected.items()}
        result['service_available']=typed[SET]
        for name,key in ((STOP,'stop_available'),(SHUTDOWN,'shutdown_available')):
            result[key]=bool(result['provider'] and typed[name] and registered.get(name)==provider)
        result['query_ok']=True
        if result['raw_active'] and result['debug_active']:result['blocking_reason']='正式舵机服务和调试服务同时存在，请退出冲突服务'
        elif result['raw_active']:result['blocking_reason']='正式舵机服务正在占用PWM，请先退出'
        elif result['debug_active'] and not all(result[k] for k in ('service_available','stop_available','shutdown_available')):
            result['blocking_reason']='调试服务类型/来源不匹配或缺少新版停止/退出接口，请升级板端'
        elif not result['debug_active']:result['blocking_reason']='调试服务尚未就绪，请启动调试后端'
    except Exception as exc:result['blocking_reason']='舵机服务查询失败：'+str(exc)
    return result
def require_query(state):
    if not state['query_ok']:raise ValueError(state['blocking_reason'])
def require_protocol(state,operation):
    require_query(state)
    required=('service_available','stop_available') if operation=='stop' else ('service_available','stop_available','shutdown_available')
    if not all(state[key] for key in required):raise ValueError(state['blocking_reason'] or '需要新版舵机调试服务')
    if operation=='set' and state['raw_active']:raise ValueError(state['blocking_reason'])
def grounded():
    import subprocess, rospy, rosgraph
    ps=subprocess.check_output(['ps','-eo','args'],text=True)
    if any(any(x in line for x in ('run_trial.py','competition_supervisor.py','/lib/patrol_control/patrol_control'))
           for line in ps.splitlines() if line.lstrip().startswith(('python','/usr/bin/python','/home/','/opt/'))):
        raise ValueError('任务控制进程正在运行；请结束飞行任务后调试')
    rospy.init_node('workbench_servo_debug_client',anonymous=True,disable_signals=True)
    if any(name=='/mavros/state' and nodes for name,nodes in rosgraph.Master(rospy.get_name()).getSystemState()[0]):
        from mavros_msgs.msg import State
        state=rospy.wait_for_message('/mavros/state',State,timeout=2)
        if state.armed:raise ValueError('飞控已解锁，禁止舵机地面调试')
if action=='probe':
    print(json.dumps(dict(ok=True,**services())))
elif action=='status':
    state=services(); values=channels();initial=[];release=[]
    try:
        text=(root/'patrol_uav_ws-patrol_planner/src/actuator_pwm/include/actuator_pwm/SlotCalibration.h').read_text()
        def calibration(name):
            match=re.search(name+r'\[\]\s*=\s*\{([^}]+)\}',text)
            if not match:raise ValueError('标定表无法解析')
            values=[int(x.strip()) for x in match.group(1).split(',')]
            if len(values)!=3:raise ValueError('标定表必须包含三通道')
            return values
        initial=calibration('kInitialDutyNs');release=calibration('kReleaseDutyNs')
    except Exception as exc:state['blocking_reason']='板端舵机标定表不可用：'+str(exc)
    ready=(state['query_ok'] and state['service_available'] and state['stop_available'] and state['shutdown_available']
        and not state['raw_active'] and len(initial)==3 and len(release)==3 and all(c['initialized'] for c in values))
    if not all(c['initialized'] for c in values):state['blocking_reason']='PWM未初始化或状态不可读，请先退出调试后执行原初始化'
    print(json.dumps(dict(ok=True,channels=values,initial_ns=initial,release_ns=release,control_ready=ready,**state)))
elif action=='guard':
    grounded();state=services();require_query(state)
    if state['debug_active'] or state['raw_active']:raise ValueError('PWM服务已存在，请退出后再启动调试')
    from patrol_control.srv import SetServoDuty
    from std_srvs.srv import Trigger
    script=root/'patrol_uav_ws-patrol_planner/src/actuator_pwm/scripts/servo_debug_node.py'
    if not script.exists():raise ValueError('板端尚未部署servo_debug_node.py')
    if not all(c['initialized'] and c['enable_value']=='0' for c in channels()):
        raise ValueError('请先通过原PWM初始化入口初始化并关闭三路输出')
elif action=='set':
    grounded();state=services();require_protocol(state,'set')
    if not all(c['initialized'] for c in channels()):raise ValueError('PWM周期/极性/读回无效；请退出调试并初始化')
    import rospy
    from patrol_control.srv import SetServoDuty
    rospy.wait_for_service(SET,timeout=2)
    result=rospy.ServiceProxy(SET,SetServoDuty)(request['slot'],request['duty_cycle_ns'],request['hold'])
    print(json.dumps(dict(ok=bool(result.success),message=result.message,actual_duty_ns=result.actual_duty_ns,channels=channels())))
elif action in ('stop','close'):
    state=services();require_protocol(state,action)
    import rospy
    from std_srvs.srv import Trigger
    rospy.init_node('workbench_servo_debug_stop',anonymous=True,disable_signals=True)
    endpoint=STOP if action=='stop' else SHUTDOWN
    rospy.wait_for_service(endpoint,timeout=2)
    result=rospy.ServiceProxy(endpoint,Trigger)()
    ok=bool(result.success);message=result.message
    if ok and not all(c['enable_value']=='0' for c in channels()):
        ok=False;message='板端回复后PWM关闭读回未全部确认'
    if ok and action=='close':
        deadline=time.monotonic()+3
        while True:
            remaining=services();require_query(remaining)
            if not remaining['debug_active']:break
            if time.monotonic()>=deadline:
                ok=False;message='PWM已关闭，但调试服务未退出，保留连接/会话';break
            time.sleep(.1)
    print(json.dumps(dict(ok=ok,message=message,channels=channels())))
else:raise ValueError('未知动作')
'''


def validate_set(body):
    if not isinstance(body, dict) or body.get('confirm') != '舵机调试':
        raise ValueError('请确认舵机调试动作')
    slot, duty, hold = body.get('slot'), body.get('duty_cycle_ns'), body.get('hold', False)
    if type(slot) is not int or not 1 <= slot <= 3:
        raise ValueError('slot必须为1、2或3')
    if type(duty) is not int or not 500000 <= duty <= 2500000:
        raise ValueError('脉宽必须为500000～2500000 ns（0.5～2.5 ms）')
    if type(hold) is not bool:
        raise ValueError('hold必须是布尔值')
    return dict(action='set',slot=slot,duty_cycle_ns=duty,hold=hold)


def exclusive_hardware_entry(function):
    """Serialize local start decisions with debug startup (stop never waits here)."""
    @wraps(function)
    def wrapped(workbench, *args, **kwargs):
        with workbench.servo_debug.lock:
            return function(workbench, *args, **kwargs)
    return wrapped


class ServoDebug:
    def __init__(self, workbench):
        self.w = workbench
        self.lock = threading.RLock()
        self.state_lock = threading.Lock()
        self.generation = 0
        self.stopping = 0
        self.inflight = 0
        self.drained = threading.Condition(self.state_lock)

    def command(self, request):
        encoded=base64.b64encode(REMOTE.encode()).decode()
        body=json.dumps(request,separators=(',',':'))
        script='import base64; exec(compile(base64.b64decode(%r),"servo_workbench","exec"))'%encoded
        return wb_board.terminal_wrapped_command(self.w.config,
            '%s -c %s %s'%(quote(self.w.config['connection'].get('board_python','/usr/bin/python3')),quote(script),quote(body)))

    def run(self, request):
        code, output=self.w.board.run(self.command(request),timeout=12)
        if code:raise ValueError('板端舵机接口失败：'+str(output)[-1500:])
        try:return json.loads(str(output).strip().splitlines()[-1])
        except (ValueError,IndexError):raise ValueError('板端没有返回有效舵机结果')

    def managed_active(self):
        session=self.w.sessions.get('servo_debug')
        return bool(session and session.state in ('starting','running'))

    def probe(self):
        result=self.run(dict(action='probe'))
        if not result.get('query_ok'):
            raise ValueError(result.get('blocking_reason') or '舵机服务查询失败')
        return result

    def active(self):
        options=getattr(self.w, 'options', {})
        if options.get('logs_only'):return False
        target=getattr(self.w, 'target', None)
        if getattr(target, 'transport', None)=='local' and not options.get('allow_local_commands'):return False
        if self.managed_active():return True
        if self.w.connection.get('state') != 'ok':return False
        return bool(self.probe().get('debug_active'))

    def assert_idle(self, include_raw=False):
        with self.state_lock:
            if self.stopping:raise ValueError('舵机停止/退出正在处理，请等待确认')
        if self.managed_active():raise ValueError('请先关闭PWM并退出调试后端')
        if self.w.connection.get('state') != 'ok':raise ValueError('请先连接板端以核对舵机互斥状态')
        state=self.probe()
        if state.get('debug_active'):raise ValueError('板端调试服务仍在运行，请先关闭PWM并退出调试后端')
        if include_raw and state.get('raw_active'):raise ValueError('正式舵机服务仍在运行，请先退出再初始化PWM')

    def action(self, name, body):
        self.w._require_command_transport()
        if self.w.connection.get('state') != 'ok':raise ValueError('请先连接板端')
        if name=='status':
            result=self.run(dict(action='status'))
            result['backend_source']='managed' if self.managed_active() else ('external' if result.get('debug_active') else 'none')
            session=self.w.sessions.get('servo_debug')
            if session:
                result['backend_state']=session.state
                result['backend_output']=''.join(text for _,text in session.history_since(0))[-2500:]
            return result
        if name=='set':request=validate_set(body)
        elif name in ('start','stop','close'):
            if not isinstance(body,dict) or body.get('confirm')!='舵机调试':raise ValueError('请确认舵机调试操作')
            request=dict(action=name)
        else:raise ValueError('未知舵机操作')
        if name in ('stop','close'):
            # Do not wait behind an SSH send; cancel queued local requests as well.
            with self.state_lock:
                self.generation+=1;self.stopping+=1
            try:
                # Interrupt immediately, then drain SSH calls that may not yet have
                # reached ROS. A second stop is the acknowledgement barrier.
                result=self.run(dict(action='stop'))
                if result.get('ok'):
                    deadline=time.monotonic()+14
                    with self.drained:
                        while self.inflight:
                            remaining=deadline-time.monotonic()
                            if remaining<=0:
                                raise ValueError('停止已提交，但旧发送尚未结束，不能确认关闭完成')
                            self.drained.wait(remaining)
                    result=self.run(request)
                if name=='close' and result.get('ok'):self.w.sessions.close('servo_debug')
                self.w._journal(dict(action='servo_debug_'+name,request=request,result=result))
                return result
            finally:
                with self.state_lock:self.stopping-=1
        with self.state_lock:
            if self.stopping:raise ValueError('正在关闭舵机输出，请等待确认')
            generation=self.generation
        with self.lock:
            with self.state_lock:
                if self.stopping or generation!=self.generation:raise ValueError('旧舵机请求已被停止操作取消')
            trial=self.w.sessions.get('trial')
            if trial and trial.state in ('starting','running'):raise ValueError('请结束当前试飞入口再调试舵机')
            if name=='start':
                if self.w.orchestration.get('running'):raise ValueError('设备启动流程正在运行，请等待完成')
                state=self.probe()
                if state.get('debug_active'):
                    status=self.action('status',{})
                    if not status.get('control_ready'):raise ValueError(status.get('blocking_reason') or '调试服务不兼容/尚未就绪')
                    return dict(ok=True,message='复用已核对类型和来源的板端调试服务',backend_source=status['backend_source'])
                if self.managed_active():raise ValueError('调试后端尚在启动，请刷新状态确认')
                if state.get('raw_active'):raise ValueError('请先退出正式舵机服务再启动调试')
                command=self.command(dict(action='guard'))+' && '+wb_board.terminal_wrapped_command(
                    self.w.config,'exec rosrun actuator_pwm servo_debug_node.py')
                self.w.sessions.open('servo_debug','舵机调试后端',command,self.w.target)
                return dict(ok=True,message='调试后端启动请求已提交；刷新状态确认服务就绪')
            with self.state_lock:
                if self.stopping or generation!=self.generation:
                    raise ValueError('旧舵机请求已被停止操作取消')
                self.inflight+=1
            try:
                result=self.run(request)
                self.w._journal(dict(action='servo_debug_'+name,request=request,result=result))
                return result
            finally:
                with self.drained:
                    self.inflight-=1
                    self.drained.notify_all()
