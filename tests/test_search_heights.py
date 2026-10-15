"""Search-height edits reach the same runtime overlay, without altering drop/H modes."""
import copy,sys,os,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace as N
import yaml
TOOL=Path(__file__).resolve().parents[1];ROOT=Path(os.environ.get('LIFTRACE_BOARD_FIXTURE_ROOT','F:/UAV/代码/liftrace-controlwork'))
sys.path[:0]=[str(TOOL),str(ROOT/'deployment/board_trials_4x4/common/uav_board_trials/scripts'),str(ROOT/'patrol_uav_ws-patrol_planner/src/uav_mission/src'),str(ROOT/'vision_ws/src/uav_high_view/src')]
import wb_geometry,wb_waypoints,wb_config_summary,wb_competition_map
import wb_board

class SearchHeightTests(unittest.TestCase):
    def test_competition_height_roundtrip_keeps_h_parameters(self):
        settings=yaml.safe_load((TOOL/'competition_templates/deployment/competition/field_10x10_default.yaml').read_text(encoding='utf-8'))
        p=wb_config_summary.summarize(settings)['geometry'];site=wb_competition_map.to_site(p,settings['max_agl'])
        site['high_agl']=2.7;site['low_agl']=1.5
        result=wb_competition_map.to_patch(site)
        self.assertEqual((result['high_agl'],result['low_agl']),(2.7,1.5))
        for key in p.keys()-{'high_agl','low_agl'}:self.assertEqual(result[key],p[key],key)
        for invalid in (0,1.9,float('nan')):
            with self.assertRaises(ValueError):wb_geometry.validate_geometry({'low_agl':invalid})
    def test_module_08_overlay_generation_uses_search_heights(self):
        from trial_config import load_trial_settings,apply_site_profile,generate
        cfg=wb_board.load_config();wb=N(config=cfg,target=N(host='test',transport='local'),connection={'state':'unknown'},sessions=N(get=lambda _:None));wb.board=wb_board.BoardClient(cfg,wb.target)
        site=wb_waypoints.context(wb,{'group_id':'mod08'})['site'];site['high_agl']=2.2;site['low_agl']=1.5
        patch=wb_waypoints.patch_from_site(site)
        self.assertEqual((patch['high_agl'],patch['low_agl']),(2.2,1.5))
        original=load_trial_settings(ROOT,'08_full_mission');settings=copy.deepcopy(original);apply_site_profile(settings,patch)
        rig=yaml.safe_load((ROOT/'deployment/board_trials_4x4/common/uav_board_trials/config/known_rig.yaml').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            generate(ROOT,td,settings,(0.,0.,0.),rig)
            runtime=yaml.safe_load((Path(td)/'runtime.yaml').read_text())
        self.assertEqual(runtime['high_view_probe']['config']['high_agl'],2.2)
        self.assertEqual(runtime['high_view_probe']['config']['low_agl'],1.5)
        for key in ('drop_agl','drop_descent_mode','landing_descent_mode','landing_alignment_mode','landing_posctl'):self.assertEqual(settings[key],original[key])
if __name__=='__main__':unittest.main(verbosity=2)
