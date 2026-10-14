import copy,json,os,sys,tempfile,subprocess,unittest
from pathlib import Path
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wb_board,wb_flight_settings
ROOT=Path(os.environ.get('LIFTRACE_SOURCE_ROOT',str(Path(__file__).resolve().parents[2]/'liftrace-controlwork')))
PATHS=[str(ROOT/'patrol_uav_ws-patrol_planner/src/uav_mission/src'),str(ROOT/'vision_ws/src/uav_high_view/src'),str(ROOT/'deployment/board_trials_4x4/common/uav_board_trials/scripts')]
sys.path[:0]=PATHS
if ROOT.is_dir():
 from uav_mission.flight_settings import apply_patch
PATCH=dict(drop_horizontal_compensation_mode=1,drop_descent_mode=4,drop_agl=.42,release_min_agl=.37,release_max_agl=.47,drop_descent_mode4_speed_mps=.5,landing_alignment_mode='vh',landing_descent_mode=2,landing_handoff_mode='POSCTL',landing_descent_speed_mps=.15)
class FlightSettingsTests(unittest.TestCase):
 def setUp(self):
  self.config=wb_board.load_config(str(Path(__file__).resolve().parents[1]/'workbench.yaml'));self.group=next(g for g in self.config['groups'] if g['id']=='mod08')
 def test_commands_for_check_preview_mock_real_and_map(self):
  for mode,check,real in [('preview',True,False),('preview',False,False),('flight',False,False),('flight',False,True)]:
   cmd,_=wb_board.build_group_command(self.config,self.group,mode,check_config=check,real_release=real,flight_settings=PATCH)
   self.assertIn('--flight-config logs/flight_workbench/flight_overlays/',cmd);self.assertEqual(cmd.count('--flight-config '),1)
   self.assertIn('--check-config' if check else ('start_real.sh' if real else 'start.sh'),cmd)
  cmd,_=wb_board.build_group_command(self.config,self.group,'preview',check_config=True,flight_settings=PATCH,site_geometry={'corridor_waypoints':[dict(x=6,y=1,agl=.9),dict(x=7,y=1,agl=.9)],'landing_xy':[7,1]},geometry_revision='flighttest')
  self.assertIn('site_overlays/',cmd);self.assertIn('flight_overlays/',cmd)
 def test_invalid_types_ranges_modes_and_modules(self):
  for patch in [dict(drop_descent_mode=True),dict(drop_descent_mode=5),dict(drop_agl=float('nan')),dict(release_min_agl=.35),dict(release_min_agl=.5,release_max_agl=.4),dict(landing_descent_mode=4,landing_handoff_mode='POSCTL'),dict(landing_xy=[1,2]),dict(raw_servo_service='/evil')]:
   with self.assertRaises(ValueError):wb_flight_settings.validate_patch(patch,'08_full_mission')
  with self.assertRaises(ValueError):wb_flight_settings.validate_patch({'drop_descent_mode':1},'03_h_landing')
  with self.assertRaises(ValueError):wb_flight_settings.validate_patch({'landing_descent_mode':1},'07_memory_only')
 @unittest.skipUnless(ROOT.is_dir(),'set LIFTRACE_SOURCE_ROOT to the source checkout')
 def test_inheritance_and_mode4_coupling(self):
  base=yaml.safe_load((ROOT/'deployment/board_trials_4x4/08_full_mission/settings.yaml').read_text());before=copy.deepcopy(base)
  result=apply_patch(base,PATCH,'08_full_mission');self.assertEqual(base,before);self.assertEqual(result['landing_posctl'],base['landing_posctl'])
  with self.assertRaises(ValueError):apply_patch(base,{'landing_descent_mode':4},'08_full_mission')
  result=apply_patch(base,{'landing_descent_mode':4,'landing_handoff_mode':'OFFBOARD','landing_offboard':{'descent_speed':.25}},'08_full_mission');self.assertEqual(result['landing_offboard']['descent_speed'],.25)
 def test_remote_writer_compatibility_and_immutable_files(self):
  relative,cmd=wb_flight_settings.override_command(PATCH,'08_full_mission')
  with tempfile.TemporaryDirectory() as tmp:
   self.assertNotEqual(subprocess.run(cmd,shell=True,cwd=tmp,capture_output=True).returncode,0)
   entry=Path(tmp)/'deployment/board_trials_4x4/common/uav_board_trials/scripts/run_trial.py';entry.parent.mkdir(parents=True);entry.write_text('# --flight-config')
   for _ in range(2):
    result=subprocess.run(cmd,shell=True,cwd=tmp,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
   self.assertEqual(json.loads((Path(tmp)/relative).read_text()),PATCH);(Path(tmp)/relative).write_text('{}')
   self.assertNotEqual(subprocess.run(cmd,shell=True,cwd=tmp,capture_output=True).returncode,0)
 @unittest.skipUnless(ROOT.is_dir(),'set LIFTRACE_SOURCE_ROOT to the source checkout')
 def test_actual_cli_generation_and_speed_override_order(self):
  env=dict(os.environ,PYTHONPATH=os.pathsep.join(PATHS),PYTHONPYCACHEPREFIX='/tmp/flight-settings-pycache')
  with tempfile.TemporaryDirectory() as tmp:
   flight=Path(tmp)/'flight.yaml';flight.write_text(yaml.safe_dump(PATCH));out=Path(tmp)/'generated'
   cmd=[sys.executable,str(ROOT/'deployment/board_trials_4x4/common/uav_board_trials/scripts/run_trial.py'),'full_mission','preview','--root',str(ROOT),'--site-config',str(ROOT/'deployment/board_trials_4x4/08_full_mission/site_20261007_221730.yaml'),'--speed-profile','competition','--flight-config',str(flight),'--check-config','--generate-config',str(out),'--reference-fc','.03','-.02','.25']
   result=subprocess.run(cmd,env=env,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
   control=yaml.safe_load((out/'control.yaml').read_text());runtime=yaml.safe_load((out/'runtime.yaml').read_text());rig=yaml.safe_load((ROOT/'deployment/board_trials_4x4/common/uav_board_trials/config/known_rig.yaml').read_text());ground=.25-rig['fc_ground_clearance']
   self.assertEqual(control['drop_system']['descent']['mode'],4);self.assertEqual(control['drop_system']['pre_descent']['mode'],1)
   for key,val in [('release_setpoint_height',.42),('release_min_height',.37),('height_threshold',.47)]:self.assertAlmostEqual(control['drop_system'][key],ground+val)
   self.assertEqual(control['external_landing']['alignment_mode'],'vh');self.assertEqual(control['external_landing']['descent']['mode'],2);self.assertEqual(control['external_landing']['descent']['speed_mps'],.15)
   self.assertAlmostEqual(runtime['mission']['landing_xy'][0],7.73);self.assertAlmostEqual(runtime['mission']['landing_xy'][1],-3.47);self.assertEqual(runtime['mission']['nominal_speed'],1.2)
 def test_server_command_api_and_competition_entry(self):
  import server
  from types import SimpleNamespace
  wb=SimpleNamespace(config=self.config)
  body=dict(group_id='mod08',mode='preview',check_config=True,flight_settings=PATCH)
  preview=server.Workbench.trial_command(wb,body)
  expected,_=wb_board.build_group_command(self.config,self.group,'preview',check_config=True,flight_settings=PATCH)
  self.assertEqual(preview['body'],expected)
  competition=next(g for g in self.config['groups'] if g.get('channel')=='competition')
  command,_=wb_board.build_group_command(self.config,competition,'preview',check_config=True,flight_settings=PATCH)
  self.assertIn('competition/start.sh preview',command);self.assertIn('--flight-config ',command)
 @unittest.skipUnless(ROOT.is_dir(),'set LIFTRACE_SOURCE_ROOT to the source checkout')
 def test_schema_stays_in_sync(self):
  from uav_mission import flight_settings
  for name in ('DROP_FIELDS','H_FIELDS','DROP_FOLDERS','H_FOLDERS'):self.assertEqual(getattr(wb_flight_settings,name),getattr(flight_settings,name))
if __name__=='__main__':unittest.main()
