"""Real immutable overlay writer + production configuration, no SSH/ROS/flight."""
import copy,json,os,shlex,subprocess,sys,tempfile,unittest
from pathlib import Path
import yaml
TOOL=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('LIFTRACE_BOARD_FIXTURE_ROOT',TOOL.parents[1]))
sys.path.insert(0,str(TOOL))
import wb_config_summary as summary
import wb_competition_geometry as geometry
import wb_board


class CompetitionGeometryTests(unittest.TestCase):
    def setUp(self):
        self.field=ROOT/'deployment/competition/field_20261007_validated.yaml'
        if not self.field.exists():self.skipTest('set LIFTRACE_BOARD_FIXTURE_ROOT to the full source checkout')
        self.settings=yaml.safe_load(self.field.read_text(encoding='utf-8'))
        self.patch=summary.summarize(self.settings)['geometry']

    def test_switches_are_boolean_and_geometry_is_separate(self):
        v=summary.summarize(self.settings)
        self.assertIs(v['motion_optimization']['value'],self.settings['motion_optimization']['enabled'])
        self.assertIs(v['obstacle_columns']['value'],True)
        self.assertNotIn('actuator_mode',v['geometry'])
        with self.assertRaises(ValueError):summary.summarize(dict(self.settings,obstacle_columns_enabled='false'))

    def test_bounds_points_and_policy_injection(self):
        for changes in ({'actuator_mode':'mock'},{'site_confirmed':True},
                        {'high_agl':float('nan')},{'survey_xy':[[0,0]]*9},
                        {'flight_bounds':[1,0,0,1]}, {'corridor_waypoints':[{'x':0,'y':0,'agl':.2}]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):geometry.validate_patch(dict(self.patch,**changes))

    def test_plan_binds_source_revision_and_all_switches(self):
        config=wb_board.load_config();group=next(g for g in config['groups'] if g['channel']=='competition')
        a,_=wb_board.build_group_command(config,group,'preview',site_geometry=self.patch,geometry_revision='r1',motion_optimization='off')
        b,_=wb_board.build_group_command(config,group,'preview',site_geometry=self.patch,geometry_revision='r2',motion_optimization='on')
        self.assertNotEqual(a,b);self.assertIn('competition_',a);self.assertIn('--motion-optimization off',a)
        self.assertNotIn('board_trials_4x4',a)

    def test_real_writer_preserves_policy_and_source_and_rejects_drift(self):
        base=ROOT/'logs/flight_workbench/geometry_tests';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as td:
            source=Path(td)/'field.yaml';source.write_text(yaml.safe_dump(self.settings),encoding='utf-8')
            original=source.read_bytes();patch=copy.deepcopy(self.patch);patch['landing_xy']=[7.6,-3.45]
            relative,command=geometry.overlay_command(str(source),patch,'test')
            dest=ROOT/relative
            argv=shlex.split(command);argv[0]=sys.executable
            try:
                result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                saved=yaml.safe_load(dest.read_text(encoding='utf-8'))
                self.assertEqual(saved['landing_xy'],patch['landing_xy'])
                self.assertEqual(source.read_bytes(),original)
                for key in ('motion_optimization','survey_policy','drop_agl','actuator_mode','site_confirmed','landing_descent_mode'):
                    self.assertEqual(saved.get(key),self.settings.get(key))
                self.assertEqual(saved['corridor_speed_schedule']['open_lead_m'],self.settings['corridor_speed_schedule']['open_lead_m'])
                changed=copy.deepcopy(self.settings);changed['cruise_speed']=.4;source.write_text(yaml.safe_dump(changed),encoding='utf-8')
                result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0);self.assertIn('原场地 YAML 已改变',result.stderr)
            finally:
                if dest.exists():dest.unlink()

    def test_board_reader_is_same_parser_and_confines_paths(self):
        command=summary.read_command(str(ROOT),str(self.field));argv=shlex.split(command);argv[0]=sys.executable
        result=subprocess.run(argv,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['geometry'],self.patch)
        with tempfile.TemporaryDirectory() as td:
            outside=Path(td)/'outside.yaml';outside.write_text('a: 1')
            argv=shlex.split(summary.read_command(str(ROOT),str(outside)));argv[0]=sys.executable
            self.assertNotEqual(subprocess.run(argv,capture_output=True).returncode,0)

    def test_parameter_panel_reads_edited_competition_geometry(self):
        from wb_flight_parameters import READ_SOURCE
        namespace={};exec(READ_SOURCE,namespace)
        read_current_files=namespace['read_current_files']
        patch=copy.deepcopy(self.patch);patch['landing_capture_agl']=1.1;patch['landing_xy']=[7.6,-3.45]
        result=read_current_files(str(ROOT),'deployment/competition/field_20261007_validated.yaml','competition',geometry=patch)
        self.assertEqual(result['details']['landing_capture_agl'],1.1)
        self.assertEqual(result['details']['landing_xy'],[7.6,-3.45])
        self.assertEqual(result['values']['drop_agl'],self.settings['drop_agl'])


if __name__=='__main__':unittest.main(verbosity=2)
