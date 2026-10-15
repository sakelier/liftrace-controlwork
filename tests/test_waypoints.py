"""Flight-before-edit contracts; no board or flight operations."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wb_board
import wb_waypoints as waypoints


class WaypointTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.profile = patch.object(wb_board, 'DEFAULT_PROFILE_DIR', self.directory.name)
        self.profile.start()
        config = wb_board.load_config(str(Path(__file__).resolve().parents[1]/'workbench.yaml'))
        self.wb = SimpleNamespace(config=config, target=SimpleNamespace(host='test-host', transport='local'),
            connection={'state':'unknown'}, sessions=SimpleNamespace(get=lambda key: None))
        self.wb.board = wb_board.BoardClient(config, self.wb.target)

    def tearDown(self):
        self.profile.stop();self.directory.cleanup()

    def save(self, site=None):
        context = waypoints.context(self.wb, {'group_id':'mod08'})
        value = copy.deepcopy(site or context['site'])
        value['corridor_waypoints'][3]['y'] = -.85
        return waypoints.save(self.wb, dict(group_id='mod08',scope=context['scope'],site=value))

    def test_persistence_and_return_to_original_without_deleting_draft(self):
        data = self.save()
        self.assertEqual(waypoints.draft(self.wb,{'group_id':'mod08'})['draft']['patch']['corridor_waypoints'][3]['y'],-.85)
        waypoints.disable(self.wb, dict(group_id='mod08',scope=data['scope']))
        context = waypoints.context(self.wb, {'group_id':'mod08'})
        self.assertFalse(context['draft']['enabled'])
        self.assertEqual(context['site']['corridor_waypoints'][3]['y'],-.9)

    def test_board_root_and_group_isolation(self):
        self.save()
        self.wb.target.host = 'other-host'
        self.assertIsNone(waypoints.draft(self.wb, {'group_id':'mod08'})['draft'])
        self.wb.target.host = 'test-host'
        self.assertIsNone(waypoints.draft(self.wb, {'group_id':'mod04'})['draft'])
        self.wb.config['connection']['board_root'] = '/other/project'
        self.assertIsNone(waypoints.draft(self.wb, {'group_id':'mod08'})['draft'])

    def test_active_task_and_stale_source_rejected(self):
        context = waypoints.context(self.wb, {'group_id':'mod08'})
        body = dict(group_id='mod08',scope=context['scope'],site=context['site'])
        self.wb.sessions = SimpleNamespace(get=lambda key:SimpleNamespace(state='running'))
        with self.assertRaises(ValueError):waypoints.save(self.wb, body)
        self.wb.sessions = SimpleNamespace(get=lambda key:None)
        self.wb.target.host = 'other-host'
        with self.assertRaises(ValueError):waypoints.save(self.wb, body)

    def test_preserves_other_business_and_builds_the_actual_start_overlay(self):
        data = self.save()
        self.assertEqual(set(data['patch']),set(waypoints.FIELDS)|{'high_agl','low_agl','max_agl'})
        group = next(g for g in self.wb.config['groups'] if g['id']=='mod08')
        for mode,check in [('preview',True),('preview',False),('flight',False)]:
            command,_ = wb_board.build_group_command(self.wb.config,group,mode,route='module',check_config=check,
                site_geometry=data['patch'],geometry_revision=data['revision'])
            self.assertIn('site_overlays/08_full_mission_',command)
            self.assertNotIn('--survey-pattern',command)
            self.assertIn(' && bash deployment/board_trials_4x4/08_full_mission/start.sh',command)

    def test_task2_low_xy_map_persists_and_uses_own_overlay_and_speed(self):
        context=waypoints.context(self.wb,{'group_id':'site2'})
        self.assertEqual(context['folder'],'05_low_multi')
        site=copy.deepcopy(context['site'])
        site['search_waypoints_xy']=[[.6,0.],[1.2,1.],[2.4,-1.]]
        saved=waypoints.save(self.wb,dict(group_id='site2',scope=context['scope'],site=site))
        self.assertEqual(saved['patch']['search_waypoints_xy'],site['search_waypoints_xy'])
        self.assertEqual(waypoints.context(self.wb,{'group_id':'site2'})['site']['search_waypoints_xy'],site['search_waypoints_xy'])
        group=next(g for g in self.wb.config['groups'] if g['id']=='site2')
        command,_=wb_board.build_group_command(self.wb.config,group,'preview',route='module',check_config=True,
            site_geometry=saved['patch'],geometry_revision=saved['revision'],speed_profile='competition')
        self.assertIn('site_overlays/05_low_multi_',command)
        self.assertIn('--speed-profile competition',command)
        self.assertNotIn('--survey-pattern',command)
        exported=waypoints.export_yaml({'site':site})['yaml']
        imported=waypoints.import_yaml({'text':exported,'base_site':context['site']})
        self.assertEqual(imported['site']['search_waypoints_xy'],site['search_waypoints_xy'])
        self.assertIsNone(waypoints.draft(self.wb,{'group_id':'mod08'})['draft'])
        import wb_geometry
        with self.assertRaises(ValueError):wb_geometry.overlay_command('field.yaml','08_full_mission',saved['patch'],'revision')

    def test_task2_invalid_low_points_and_missing_corridor_are_rejected(self):
        context=waypoints.context(self.wb,{'group_id':'site2'})
        for patch in ({'search_waypoints_xy':[[99,0.],[1.,0.]]}, {'search_waypoints_xy':[[.6,0.]]}, {'corridor_waypoints':[]}):
            site=copy.deepcopy(context['site']);site.update(patch)
            with self.assertRaises(ValueError):waypoints.save(self.wb,dict(group_id='site2',scope=context['scope'],site=site))

    def test_source_module_accepts_adjusted_geometry(self):
        repository=Path('F:/UAV/代码/liftrace-controlwork')
        if not repository.exists():self.skipTest('source repository not available')
        for path in ['deployment/board_trials_4x4/common/uav_board_trials/scripts',
                     'patrol_uav_ws-patrol_planner/src/uav_mission/src','vision_ws/src/uav_high_view/src']:
            sys.path.insert(0,str(repository/path))
        from trial_config import apply_site_profile,validate_settings
        settings=yaml.safe_load((repository/'deployment/board_trials_4x4/08_full_mission/settings.yaml').read_text(encoding='utf-8'))
        original_modes={key:settings[key] for key in ('drop_descent_mode','landing_descent_mode')}
        base=yaml.safe_load((repository/'deployment/board_trials_4x4/08_full_mission/site_20261007_221730.yaml').read_text(encoding='utf-8'))
        merged=waypoints.merge(base,self.save()['patch'])
        apply_site_profile(settings,merged);validate_settings(settings)
        for key,value in original_modes.items():self.assertEqual(settings[key],value)

    def test_local_partial_import_export_roundtrip(self):
        base=waypoints.context(self.wb,{'group_id':'mod08'})['site'];before=copy.deepcopy(base)
        patch={'flight_area':{'center_bounds':[-.35,9,-4,2.7],'target_bounds':[-.35,9,-4,2.7],'map_size':[20,12,4]},
               'corridor_waypoints':[dict(x=6.5,y=1.9,agl=.9)]+[dict(x=8.14,y=y,agl=.9) for y in (1.9,-.7,-3.45)],'landing_xy':[8.14,-3.45]}
        imported=waypoints.import_yaml({'text':yaml.safe_dump(patch),'base_site':base})
        self.assertEqual(base,before);self.assertEqual(len(imported['site']['corridor_waypoints']),4)
        self.assertEqual(imported['site']['flight_area']['search_bounds'],base['flight_area']['search_bounds'])
        exported=waypoints.export_yaml({'site':imported['site']})['yaml']
        again=waypoints.import_yaml({'text':exported,'base_site':base})
        self.assertEqual(waypoints.patch_from_site(imported['site']),waypoints.patch_from_site(again['site']))

    def test_import_ignores_other_flight_parameters(self):
        base=waypoints.context(self.wb,{'group_id':'mod08'})['site']
        result=waypoints.import_yaml({'text':yaml.safe_dump({'landing_xy':[8,-3.4],'high_agl':2.2,'drop_descent_mode':4}),'base_site':base})
        self.assertEqual(result['site']['high_agl'],2.2)
        self.assertNotIn('drop_descent_mode',result['site'])
        self.assertEqual(set(result['ignored_fields']),{'drop_descent_mode'})

    def test_invalid_import_is_not_saved(self):
        base=waypoints.context(self.wb,{'group_id':'mod08'})['site']
        for text in ('[1, 2]','flight_area: [2, 3]','corridor_waypoints: []','a: [','foo: 1'):
            with self.subTest(text=text),self.assertRaises(ValueError):waypoints.import_yaml({'text':text,'base_site':base})
        self.assertIsNone(waypoints.draft(self.wb,{'group_id':'mod08'})['draft'])

    def test_import_provenance_only_saved_after_apply(self):
        context=waypoints.context(self.wb,{'group_id':'mod08'})
        site=waypoints.import_yaml({'text':'landing_xy: [8.0, -3.4]','base_site':context['site']})['site']
        self.assertIsNone(waypoints.draft(self.wb,{'group_id':'mod08'})['draft'])
        data=waypoints.save(self.wb,dict(group_id='mod08',scope=context['scope'],site=site,import_name='local.yaml'))
        self.assertEqual(data['import_name'],'local.yaml')


if __name__=='__main__':unittest.main()
