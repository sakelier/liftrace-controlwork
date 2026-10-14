"""Offline production generation checks; no ROS or SSH sessions."""
import copy,json,os,sys,tempfile,unittest,subprocess
from pathlib import Path
import yaml
TOOL=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('LIFTRACE_SOURCE_ROOT','F:/UAV/代码/liftrace-controlwork'))
PATHS=[str(TOOL),str(ROOT/'patrol_uav_ws-patrol_planner/src/uav_mission/src'),str(ROOT/'vision_ws/src/uav_high_view/src'),str(ROOT/'deployment/board_trials_4x4/common/uav_board_trials/scripts')]
sys.path[:0]=PATHS
import wb_task_parameters,wb_flight_parameters,wb_flight_settings
from uav_mission.flight_settings import apply_patch
from uav_mission.competition_config import generate as competition_generate
from trial_config import load_trial_settings,apply_site_profile,generate

class TaskParameterTests(unittest.TestCase):
 def test_validation_and_scope(self):
  for folder in ('competition','08_full_mission'):
   good={'cruise_speed':.4,'survey_policy':{'descent_max_candidates':5,'recheck_observe_seconds':6.}}
   self.assertEqual(wb_flight_settings.validate_patch(good,folder),good)
   for patch in ({'cruise_speed':True},{'survey_policy':{'descent_max_candidates':2.5}},{'survey_policy':{'unknown':1}}, {'site_confirmed':True}):
    with self.assertRaises(ValueError):wb_flight_settings.validate_patch(patch,folder)
  with self.assertRaises(ValueError):wb_flight_settings.validate_patch({'cruise_speed':.4},'03_h_landing')
 def test_module_runtime_and_other_policies_preserved(self):
  base=load_trial_settings(ROOT,'08_full_mission')
  apply_site_profile(base,yaml.safe_load((ROOT/'deployment/board_trials_4x4/08_full_mission/site_20261007_221730.yaml').read_text(encoding='utf-8')))
  original=copy.deepcopy(base)
  changed=apply_patch(base,{'motion_action_timeout':75.,'ordinary_waypoint_dwell_enabled':True,'survey_policy':{'recheck_observe_seconds':6.,'descent_max_candidates':5}},'08_full_mission')
  self.assertEqual(base,original)
  for key in ('drop_agl','drop_descent_mode','landing_descent_mode','landing_posctl','landing_xy'):
   self.assertEqual(changed[key],original[key])
  rig=yaml.safe_load((ROOT/'deployment/board_trials_4x4/common/uav_board_trials/config/known_rig.yaml').read_text())
  with tempfile.TemporaryDirectory() as out:
   generate(ROOT,out,changed,(0.,0.,0.),rig)
   runtime=yaml.safe_load((Path(out)/'runtime.yaml').read_text(encoding='utf-8'))
   self.assertEqual(runtime['high_view_full']['policy']['recheck_observe_seconds'],6.)
   self.assertEqual(runtime['high_view_full']['policy']['descent_max_candidates'],5)
   self.assertEqual(runtime['mission']['motion_action_timeout'],75.)
 def test_competition_cli_accepts_overlay(self):
  with tempfile.TemporaryDirectory() as td:
   patch=Path(td)/'patch.yaml';patch.write_text(yaml.safe_dump({'motion_action_timeout':80.,'survey_policy':{'recheck_observe_seconds':6.}}))
   env=dict(os.environ,PYTHONPATH=os.pathsep.join(PATHS),PYTHONUTF8='1')
   cli=ROOT/'patrol_uav_ws-patrol_planner/src/uav_mission/scripts/competition_supervisor.py'
   result=subprocess.run([sys.executable,str(cli),'preview','--root',str(ROOT),'--flight-config',str(patch),'--check-config'],env=env,capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertEqual(json.loads(result.stdout)['motion_action_timeout'],80.)
 def test_module_cli_accepts_task_overlay(self):
  with tempfile.TemporaryDirectory() as td:
   patch=Path(td)/'patch.yaml';patch.write_text(yaml.safe_dump({'motion_action_timeout':75.,'survey_policy':{'recheck_observe_seconds':6.}}))
   env=dict(os.environ,PYTHONPATH=os.pathsep.join(PATHS),PYTHONUTF8='1')
   cli=ROOT/'deployment/board_trials_4x4/common/uav_board_trials/scripts/run_trial.py'
   out=Path(td)/'generated'
   result=subprocess.run([sys.executable,str(cli),'full_mission','preview','--root',str(ROOT),'--site-config',str(ROOT/'deployment/board_trials_4x4/08_full_mission/site_20261007_221730.yaml'),'--flight-config',str(patch),'--check-config','--generate-config',str(out),'--reference-fc','0','0','0'],env=env,capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   runtime=yaml.safe_load((out/'runtime.yaml').read_text(encoding='utf-8'))
   self.assertEqual(runtime['high_view_full']['policy']['recheck_observe_seconds'],6.)
 def test_competition_runtime_and_merge(self):
  base=yaml.safe_load((ROOT/'deployment/competition/field_10x10_default.yaml').read_text(encoding='utf-8'))
  base['site_confirmed']=True # Temporary in-memory fixture only.
  changed=apply_patch(base,{'lane_spacing':.6,'target_action_timeout':90.,'survey_policy':{'recheck_observe_seconds':6.}},'competition')
  self.assertEqual(changed['survey_policy']['resume_survey_enabled'],base['survey_policy']['resume_survey_enabled'])
  rig=yaml.safe_load((ROOT/'patrol_uav_ws-patrol_planner/src/uav_mission/config/competition/known_rig.yaml').read_text())
  with tempfile.TemporaryDirectory() as out:
   competition_generate(ROOT,out,changed,(0.,0.,0.),rig)
   runtime=yaml.safe_load((Path(out)/'runtime.yaml').read_text(encoding='utf-8'))
   self.assertEqual(runtime['high_view_full']['policy']['recheck_observe_seconds'],6.)
   self.assertEqual(runtime['mission']['target_action_timeout'],90.)
   self.assertEqual(runtime['search']['lane_spacing'],.6)
 def test_reader_effective_speed_and_exact_defaults(self):
  ns={};exec(wb_flight_parameters.READ_SOURCE,ns)
  data=ns['read_current_files'](str(ROOT),'deployment/board_trials_4x4/08_full_mission/site_20261007_221730.yaml','08_full_mission',speed_profile='competition',task_fields=wb_task_parameters.fields('08_full_mission'))
  self.assertEqual(data['values']['cruise_speed'],1.2)
  self.assertEqual(data['values']['survey_policy.descent_max_candidates'],9)
  data=ns['read_current_files'](str(ROOT),'deployment/competition/field_10x10_default.yaml','competition',task_fields=wb_task_parameters.fields('competition'))
  self.assertEqual(data['values']['target_action_timeout'],120.)

if __name__=='__main__':unittest.main(verbosity=2)
