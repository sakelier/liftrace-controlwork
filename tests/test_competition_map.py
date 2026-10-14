"""Schema adapter regression for the same module-08 map component."""
import sys,copy,unittest
from pathlib import Path
from types import SimpleNamespace as N
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wb_competition_map as adapter
import wb_config_summary
import wb_board
import yaml

class SharedMapTests(unittest.TestCase):
    def setUp(self):
        tool=Path(__file__).resolve().parents[1]
        self.raw=yaml.safe_load((tool/'competition_templates/deployment/competition/field_20261007_validated.yaml').read_text(encoding='utf-8'))
        self.p=wb_config_summary.summarize(self.raw)['geometry']
        self.site=adapter.to_site(self.p,self.raw['max_agl'])
    def test_roundtrip_keeps_competition_schema_and_digest(self):
        self.assertEqual(adapter.to_patch(self.site),self.p)
        self.site['flight_area']['survey_xy'][0]=[1.2,-1.4]
        self.site['landing_xy']=[7.6,-3.45]
        p=adapter.to_patch(self.site)
        self.assertEqual(p['survey_xy'][0],[1.2,-1.4]);self.assertEqual(p['landing_xy'],[7.6,-3.45])
        self.assertEqual(p['_source_digest'],self.p['_source_digest']);self.assertNotIn('flight_area',p)
    def test_preview_bounds_and_field_injection(self):
        self.assertEqual(adapter.preview({'site':self.site})['errors'],[])
        self.site['landing_xy']=[200,0]
        self.assertTrue(adapter.preview({'site':self.site})['errors'])
        self.site['actuator_mode']='mock'
        self.assertTrue(adapter.preview({'site':self.site})['errors'])
    def test_import_export_keeps_source_policy_authority(self):
        imported=dict(self.raw,landing_xy=[7.6,-3.45],actuator_mode='mock',site_confirmed=True)
        result=adapter.import_yaml({'base_site':self.site,'text':yaml.safe_dump(imported)})
        self.assertIn('actuator_mode',result['ignored_fields'])
        self.assertEqual(adapter.to_patch(result['site'])['_source_digest'],self.p['_source_digest'])
        exported=adapter.export_yaml({'site':result['site']})['yaml']
        self.assertNotIn('_source_digest',exported);self.assertNotIn('actuator_mode',exported)
        restored=adapter.import_yaml({'base_site':self.site,'text':exported})
        self.assertEqual(adapter.to_patch(restored['site'])['landing_xy'],[7.6,-3.45])
    def test_save_checks_scope_and_running_task(self):
        cfg=wb_board.load_config();group=next(g for g in cfg['groups'] if g['channel']=='competition')
        wb=N(config=cfg,target=N(host='host'),board=N(root='/root'),sessions=N(get=lambda _:None))
        import json
        body=dict(group_id=group['id'],site=self.site,scope=json.dumps(['host','/root',group['id'],group['site_config']],ensure_ascii=True))
        self.assertEqual(adapter.save(wb,body)['patch'],self.p)
        with self.assertRaises(ValueError):adapter.save(wb,dict(body,scope='wrong'))
        wb.sessions.get=lambda _:N(state='running')
        with self.assertRaises(ValueError):adapter.save(wb,body)
if __name__=='__main__':unittest.main(verbosity=2)
