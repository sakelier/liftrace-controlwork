"""Workbench service compatibility and stop ordering, no SSH/ROS/hardware."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wb_servo_debug as servo

SET='/SetServoDuty';STOP='/servo_debug/stop';SHUTDOWN='/servo_debug/shutdown'


class ServoIntegrationTests(unittest.TestCase):
    def test_service_fields_and_boundaries(self):
        for slot in (1,2,3):
            for duty in (500000,1800000,2500000):
                self.assertEqual(servo.validate_set(dict(confirm='舵机调试',slot=slot,duty_cycle_ns=duty,hold=True)),
                                 dict(action='set',slot=slot,duty_cycle_ns=duty,hold=True))

    def test_invalid_requests_never_reach_board(self):
        for change in ({'slot':True},{'slot':4},{'duty_cycle_ns':499999},{'duty_cycle_ns':2500001},{'hold':'false'},{'confirm':''}):
            body=dict(confirm='舵机调试',slot=1,duty_cycle_ns=1800000,hold=False);body.update(change)
            with self.assertRaises(ValueError):servo.validate_set(body)

    def remote(self,action,registered=None,type_overrides=None,query_error=False,exit_service=True,**fields):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);pwm=root/'pwm';pwm.mkdir()
            for device in ('febf0000.pwm','febf0020.pwm','febf0010.pwm'):
                p=pwm/device/'pwmchip0'/'pwm0';p.mkdir(parents=True)
                for name,val in dict(duty_cycle='1800000',enable='1',period='20000000',polarity='normal').items():(p/name).write_text(val)
            calibration=root/'patrol_uav_ws-patrol_planner/src/actuator_pwm/include/actuator_pwm/SlotCalibration.h'
            calibration.parent.mkdir(parents=True)
            calibration.write_text('kInitialDutyNs[] = {1700000,1000000,1100000};\nkReleaseDutyNs[] = {2100000,2100000,2100000};')
            source=servo.REMOTE.replace("pathlib.Path('/sys/class/pwm').glob('pwmchip*')",'pathlib.Path(%r).glob("*/pwmchip*")'%str(pwm))
            services={SET:['debug'],STOP:['debug'],SHUTDOWN:['debug']} if registered is None else dict(registered)
            def state():
                if query_error:raise OSError('master unreachable')
                return ([],[],list(services.items()))
            graph=types.SimpleNamespace(Master=lambda name:types.SimpleNamespace(getSystemState=state))
            calls=[]
            def proxy(name,kind):
                def invoke(*args):
                    calls.append([name,list(args)])
                    if name==SET:
                        return types.SimpleNamespace(success=True,message='accepted',actual_duty_ns=args[1])
                    for path in pwm.glob('*/pwmchip*/pwm0'):(path/'enable').write_text('0')
                    if name==SHUTDOWN and exit_service:services.clear()
                    return types.SimpleNamespace(success=True,message='disabled')
                return invoke
            kinds={SET:'patrol_control/SetServoDuty',STOP:'std_srvs/Trigger',SHUTDOWN:'std_srvs/Trigger',**(type_overrides or {})}
            modules={'rosgraph':graph,
                'rospy':types.SimpleNamespace(init_node=lambda *a,**k:None,get_name=lambda:'/test',wait_for_service=lambda *a,**k:None,ServiceProxy=proxy),
                'rosservice':types.SimpleNamespace(get_service_type=lambda name:kinds.get(name)),
                'patrol_control':types.ModuleType('patrol_control'),
                'patrol_control.srv':types.SimpleNamespace(SetServoDuty=object),
                'std_srvs':types.ModuleType('std_srvs'),'std_srvs.srv':types.SimpleNamespace(Trigger=object)}
            old=os.getcwd();out=io.StringIO()
            try:
                os.chdir(root)
                with patch.object(sys,'argv',['client',json.dumps(dict(action=action,**fields))]),patch.dict(sys.modules,modules),patch('subprocess.check_output',return_value=''),contextlib.redirect_stdout(out):
                    if action=='close' and not exit_service:
                        with patch('time.monotonic',side_effect=[0,4]):exec(source,{})
                    else:exec(source,{})
            finally:os.chdir(old)
            result=json.loads(out.getvalue().strip().splitlines()[-1]);result['_service_calls']=calls
            duties=[(p/'duty_cycle').read_text() for p in pwm.glob('*/pwmchip*/pwm0')]
            enables=[(p/'enable').read_text() for p in pwm.glob('*/pwmchip*/pwm0')]
            return result,duties,enables

    def test_stop_uses_service_and_preserves_duty(self):
        result,duties,enables=self.remote('stop')
        self.assertTrue(result['ok']);self.assertEqual(result['_service_calls'],[[STOP,[]]])
        self.assertEqual(duties,['1800000']*3);self.assertEqual(enables,['0']*3)

    def test_status_uses_board_calibration_without_writes(self):
        result,_,enables=self.remote('status')
        self.assertEqual(result['initial_ns'][0],1700000);self.assertEqual(result['release_ns'][0],2100000)
        self.assertTrue(result['control_ready']);self.assertEqual(enables,['1']*3)

    def test_set_exact_fields_all_slots_and_hold_modes(self):
        for slot in (1,2,3):
            for hold in (False,True):
                result,_,_=self.remote('set',slot=slot,duty_cycle_ns=1800000,hold=hold)
                self.assertTrue(result['ok']);self.assertEqual(result['_service_calls'],[[SET,[slot,1800000,hold]]])

    def test_legacy_and_provider_mismatch_disable_sends(self):
        for services in [{SET:['debug']},{SET:['debug'],STOP:['other'],SHUTDOWN:['debug']}]:
            result,_,_=self.remote('status',registered=services);self.assertFalse(result['control_ready'])
            with self.assertRaises(ValueError):self.remote('set',registered=services,slot=1,duty_cycle_ns=1800000,hold=False)

    def test_wrong_service_type_and_raw_conflict_disable_sends(self):
        result,_,_=self.remote('status',type_overrides={STOP:'std_srvs/Empty'});self.assertFalse(result['control_ready'])
        registered={SET:['debug'],STOP:['debug'],SHUTDOWN:['debug'],'/legacy/Servo_raw':['raw']}
        result,_,_=self.remote('status',registered=registered);self.assertFalse(result['control_ready'])
        with self.assertRaises(ValueError):self.remote('set',registered=registered,slot=1,duty_cycle_ns=1800000,hold=False)
        self.assertTrue(self.remote('stop',registered=registered)[0]['ok'])

    def test_query_failure_is_not_idle(self):
        result,_,_=self.remote('probe',query_error=True);self.assertFalse(result['query_ok'])

    def test_close_confirms_service_disappearance(self):
        self.assertTrue(self.remote('close')[0]['ok'])
        self.assertFalse(self.remote('close',exit_service=False)[0]['ok'])


class HostTests(unittest.TestCase):
    def make(self,managed=False):
        sessions={'servo_debug':types.SimpleNamespace(state='running')} if managed else {}
        closed=[]
        w=types.SimpleNamespace(connection={'state':'ok'},orchestration={},_require_command_transport=lambda:None,
            _journal=lambda item:None,sessions=types.SimpleNamespace(get=sessions.get,close=lambda sid:closed.append(sid)))
        debug=servo.ServoDebug(w)
        return debug,closed

    def test_disconnected_rejects_without_ssh(self):
        debug,_=self.make();debug.w.connection['state']='unknown'
        with self.assertRaises(ValueError):debug.action('status',{})

    def test_external_reuse_is_active_and_blocks_trial_or_initialization(self):
        debug,_=self.make()
        debug.run=lambda request:dict(ok=True,query_ok=True,debug_active=True,control_ready=True)
        self.assertEqual(debug.action('start',{'confirm':'舵机调试'})['backend_source'],'external')
        self.assertTrue(debug.active())
        for raw in [False,True]:
            with self.assertRaises(ValueError):debug.assert_idle(include_raw=raw)

    def test_failed_query_blocks_admission_and_failed_close_keeps_session(self):
        debug,closed=self.make()
        debug.run=lambda request:dict(ok=True,query_ok=False)
        with self.assertRaises(ValueError):debug.assert_idle()
        debug.run=lambda request:dict(ok=False,message='disable failure')
        self.assertFalse(debug.action('close',{'confirm':'舵机调试'})['ok']);self.assertFalse(closed)

    def test_stop_bypasses_send_and_acknowledges_only_after_late_send_drained(self):
        debug,_=self.make();entered=threading.Event();release=threading.Event();stops=[];output={'enabled':False}
        def run(request):
            if request['action']=='set':
                entered.set()
                if not release.wait(2):raise AssertionError('stop blocked behind send')
                output['enabled']=True
                return dict(ok=True)
            stops.append(request['action']);output['enabled']=False;release.set();return dict(ok=True)
        debug.run=run
        errors=[]
        def send():
            try:debug.action('set',dict(confirm='舵机调试',slot=1,duty_cycle_ns=1800000,hold=True))
            except Exception as exc:errors.append(exc)
        thread=threading.Thread(target=send);thread.start();self.assertTrue(entered.wait(1))
        result=debug.action('stop',{'confirm':'舵机调试'});thread.join(1)
        self.assertFalse(thread.is_alive());self.assertFalse(errors);self.assertTrue(result['ok'])
        self.assertEqual(stops,['stop','stop']);self.assertFalse(output['enabled'])


if __name__=='__main__':unittest.main()
