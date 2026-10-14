"""Read-only preflight values; never connect to a board or start ROS."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wb_flight_parameters as reader
import wb_board
ROOT=Path('F:/UAV/代码/liftrace-controlwork')

class CurrentParameterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope={};exec(reader.READ_SOURCE,cls.scope);cls.read=staticmethod(cls.scope['read_current_files'])
    @unittest.skipUnless(ROOT.exists(),'source checkout not present')
    def test_real_module_and_source_defaults(self):
        result=self.read(str(ROOT),'deployment/board_trials_4x4/08_full_mission/site_20261007_221730.yaml','08_full_mission')
        v=result['values'];self.assertEqual(v['drop_horizontal_compensation_mode'],2);self.assertEqual(v['drop_descent_mode'],1)
        self.assertEqual(v['landing_descent_mode'],2);self.assertEqual(v['landing_alignment_mode'],'vh')
        self.assertEqual(v['release_min_agl'],.35);self.assertEqual(v['landing_offboard.descent_speed'],.30)
        self.assertEqual(result['details']['landing_xy'],[7.7,-3.45]);self.assertEqual(result['warnings'],[])
    @unittest.skipUnless(ROOT.exists(),'source checkout not present')
    def test_site_then_speed_overlay_order_and_no_writes(self):
        self.read(str(ROOT),'deployment/board_trials_4x4/08_full_mission/site_20261007_221730.yaml','08_full_mission')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'deployment/board_trials_4x4/08_full_mission';folder.mkdir(parents=True)
            settings=yaml.safe_load((ROOT/'deployment/board_trials_4x4/08_full_mission/settings.yaml').read_text(encoding='utf-8'))
            settings.update(drop_agl=.6,release_min_agl=.55,release_max_agl=.65)
            (folder/'settings.yaml').write_text(yaml.safe_dump(settings))
            (root/'site.yaml').write_text(yaml.safe_dump(dict(landing_descent_mode=3,landing_alignment_mode='non_vh',landing_xy=[2,1])))
            (folder/'competition_speed.yaml').write_text(yaml.safe_dump(dict(drop_agl=.42,release_min_agl=.37,release_max_agl=.47)))
            before={p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            result=self.read(str(root),'site.yaml','08_full_mission','competition',{'landing_xy':[3,2]})
            self.assertEqual(result['values']['drop_agl'],.42);self.assertEqual(result['values']['landing_descent_mode'],3)
            self.assertEqual(result['details']['landing_xy'],[3,2]);self.assertIn('competition_speed.yaml',result['origins']['drop_agl'])
            self.assertEqual(before,{p.relative_to(root):p.read_bytes() for p in root.rglob('*') if p.is_file()})
    @unittest.skipUnless(ROOT.exists(),'source checkout not present')
    def test_competition_custom_source(self):
        result=self.read(str(ROOT),'deployment/competition/field.example.yaml','competition')
        self.assertTrue(result['sources'][0].endswith('field.example.yaml'));self.assertEqual(result['values']['drop_agl'],.4)
    def test_task2_speed_does_not_replace_drop_or_h_values(self):
        for speed in (None,'competition'):
            result=self.read(str(ROOT),'deployment/board_trials_4x4/05_low_multi/site.yaml','05_low_multi',speed)
            values=result['values']
            self.assertEqual(values['drop_agl'],.30)
            self.assertEqual(values['release_min_agl'],.28)
            self.assertEqual(values['release_max_agl'],.35)
            self.assertEqual(values['landing_handoff_mode'],'POSCTL')
            self.assertEqual(values['landing_alignment_mode'],'vh')
            self.assertEqual(values['landing_descent_mode'],2)
        from wb_flight_settings import validate_patch
        validate_patch({'drop_agl':.30,'release_min_agl':.28,'release_max_agl':.35,'landing_descent_mode':2},'05_low_multi')

    def test_disconnected_or_unsupported_does_not_run(self):
        config=wb_board.load_config(str(Path(__file__).resolve().parents[1]/'workbench.yaml'))
        def refuse(*a,**kw):raise AssertionError('must not run')
        workbench=SimpleNamespace(config=config,connection={'state':'unknown'},target=SimpleNamespace(transport='ssh'),board=SimpleNamespace(run=refuse))
        with self.assertRaises(ValueError):reader.read(workbench,{'group_id':'mod08'})
        with self.assertRaises(ValueError):reader.read(workbench,{'group_id':'observation_hover'})
if __name__=='__main__':unittest.main()
