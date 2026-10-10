
from pathlib import Path
import sys,subprocess,json,yaml,roslaunch,rospkg
root=Path('/home/orangepi/liftrace_board_trials_20260928');base=root/'deployment/board_trials_4x4';scripts=base/'common/uav_board_trials/scripts'
sys.path.insert(0,str(scripts))
from trial_config import generate,validate_settings
from trial_manager import BoardManager
from unittest.mock import patch
profile=yaml.safe_load((root/'deployment/site_20260928/test_area.yaml').read_text())
rig=yaml.safe_load((base/'common/uav_board_trials/config/known_rig.yaml').read_text())
results=[]
for folder in ['01_visual_interrupt','05_low_multi','07_memory_only','02_high_view_revisit','06_high_priority']:
    settings=yaml.safe_load((base/folder/'settings.yaml').read_text());settings.update(profile)
    out=root/'deployment_results/site_generated'/folder;ref=generate(root,out,settings,(0,0,0),rig)
    for enabled in ('false','true'):
        args=['enable_control_output:='+enabled,'mode:='+settings['mode'],'model_path:='+str(root/'runtime_models/flight_5cls_20260928_fp16.rknn'),'generated_dir:='+str(out),'ground_z:='+str(ref['ground_z']),'low_z:='+str(ref['low_z'])]
        cfg=roslaunch.config.load_config_default([(str(base/'common/uav_board_trials/launch/application.launch'),args)],11311,verbose=False)
        vals={k:v.value for k,v in cfg.params.items()}
        assert vals['/fast_planner_node/sdf_map/search_region/max_x']==6.
        assert vals['/fast_planner_node/sdf_map/search_region/max_y']==1.5
        assert vals['/fast_planner_node/sdf_map/map_size_x']==16.
        assert vals['/fast_planner_node/manager/max_vel']==.5
        assert vals['/fast_planner_node/sdf_map/virtual_ceil_height']==-.1
        assert vals['/navigation/mission_manager/high_view_full/grid/bounds']==[-.35,6.,-1.5,1.5]
        assert not any(n.package in ('gazebo_ros','actuator_pwm') for n in cfg.nodes)
        if enabled=='true' and folder!='07_memory_only':
            assert vals['/guarded_servo_proxy/raw_service_name']=='/board_trials/mock_servo'
        (out/(enabled+'_params.yaml')).write_text(yaml.safe_dump(vals,sort_keys=True))
        results.append(dict(folder=folder,control_output=enabled,pass_=True,nodes=len(cfg.nodes)))
    completed=subprocess.run(['bash',str(base/folder/'start.sh'),'preview','--site-config',str(root/'deployment/site_20260928/test_area.yaml'),'--check-config'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert completed.returncode==0,completed.stderr
    print(folder,completed.stdout.strip())
(root/'deployment_results/site_validation.json').write_text(json.dumps(results,indent=2))
for n in ('rosmaster','roslaunch','rosout','mavros_node','patrol_control'):
    p=subprocess.run(['pgrep','-x',n],stdout=subprocess.PIPE,text=True)
    print(n,p.stdout.strip() or 'not_running')
