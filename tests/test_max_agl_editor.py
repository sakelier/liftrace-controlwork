import copy
from pathlib import Path
import sys
import tempfile
import unittest
import yaml
TOOL=Path(__file__).resolve().parents[1]
ROOT=Path('F:/UAV/代码/liftrace-controlwork')
sys.path[:0]=[str(TOOL),str(ROOT/'deployment/board_trials_4x4/common/uav_board_trials/scripts'),str(ROOT/'patrol_uav_ws-patrol_planner/src/uav_mission/src'),str(ROOT/'vision_ws/src/uav_high_view/src')]
import wb_waypoints,wb_competition_map,wb_config_summary,wb_geometry
from trial_config import load_trial_settings,apply_site_profile,validate_settings,generate


class MaxAltitudeEditorTests(unittest.TestCase):
    def test_module_save_export_import_and_runtime_generation(self):
        site=yaml.safe_load((TOOL/'waypoint_templates/module08.yaml').read_text(encoding='utf-8'))
        site['max_agl']=3.2
        patch=wb_waypoints.patch_from_site(site)
        self.assertEqual(patch['max_agl'],3.2)
        text=wb_waypoints.export_yaml({'site':site})['yaml']
        imported=wb_waypoints.import_yaml({'text':text,'base_site':site})
        self.assertEqual(imported['site']['max_agl'],3.2)
        settings=load_trial_settings(ROOT,'08_full_mission');apply_site_profile(settings,patch)
        rig=yaml.safe_load((ROOT/'deployment/board_trials_4x4/common/uav_board_trials/config/known_rig.yaml').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            generate(ROOT,td,settings,(0.,0.,0.),rig)
            output=yaml.safe_load((Path(td)/'overrides.yaml').read_text())
            self.assertEqual(output['/external_planner_max_command_z'],2.98)

    def test_competition_roundtrip_retains_cap(self):
        settings=yaml.safe_load((TOOL/'competition_templates/deployment/competition/field_10x10_default.yaml').read_text(encoding='utf-8'))
        site=wb_competition_map.to_site(wb_config_summary.summarize(settings)['geometry'],settings['max_agl'])
        site['max_agl']=3.4
        patch=wb_competition_map.to_patch(site)
        self.assertEqual(patch['max_agl'],3.4)
        exported=wb_competition_map.export_yaml({'site':site})['yaml']
        site['max_agl']=3.2
        imported=wb_competition_map.import_yaml({'base_site':site,'text':exported})
        self.assertEqual(imported['site']['max_agl'],3.4)

    def test_invalid_caps_and_other_task_limits_remain(self):
        for value in (True,float('nan'),1.9,3.6):
            with self.assertRaises(ValueError):wb_geometry.validate_geometry({'max_agl':value})
        settings=load_trial_settings(ROOT,'02_high_view_revisit');settings['max_agl']=3.2
        with self.assertRaisesRegex(ValueError,'invalid max_agl'):validate_settings(settings)

if __name__=='__main__':unittest.main()
