
import pathlib,sys,json,subprocess,yaml
root=pathlib.Path('/home/orangepi/liftrace_board_trials_20260928')
out=root/'deployment_results'
base=root/'deployment/board_trials_4x4'
sys.path.insert(0,str(base/'common/uav_board_trials/scripts'))
import trial_config as tc
rig=yaml.safe_load((base/'common/uav_board_trials/config/known_rig.yaml').read_text())
results=[]
for name,folder in tc.TRIAL_FOLDERS.items():
    settings=yaml.safe_load((base/folder/'settings.yaml').read_text())
    try:tc.validate_settings(settings)
    except ValueError as e:
        assert name in ['corridor_landing','full_mission'] and 'corridor_waypoints' in str(e)
        results.append(dict(trial=name,status='EXPECTED_BLOCKED',reason=str(e)));continue
    generated=out/'static_generated'/name
    ref=tc.generate(root,generated,settings,[0,0,0],rig)
    params=yaml.safe_load((generated/'overrides.yaml').read_text())
    assert params['/fast_planner_node/sdf_map/virtual_ceil_height']==-0.1
    assert params['/fast_planner_node/sdf_map/obstacles_inflation']==.25
    assert params['/fast_planner_node/sdf_map/obstacles_inflation_up']==.20
    assert params['/fast_planner_node/sdf_map/obstacles_inflation_down']==.10
    assert settings['alignment_mode']=='legacy_static' and settings['cruise_speed']==.5
    runtime=yaml.safe_load((generated/'runtime.yaml').read_text())
    assert runtime['high_view_full']['policy']['interrupt_refined_classes']==[]
    for mode in ['preview','flight']:
        args=['roslaunch','--dump-params','uav_board_trials','application.launch',
              'enable_control_output:='+str(mode=='flight').lower(),'mode:='+settings['mode'],
              'model_path:='+str(root/'runtime_models/flight_5cls_20260928_fp16.rknn'),
              'generated_dir:='+str(generated),'ground_z:='+str(ref['ground_z']),'low_z:='+str(ref['low_z'])]
        r=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        (generated/(mode+'_params.yaml')).write_text(r.stdout)
        if r.returncode:raise RuntimeError(name+' '+mode+': '+r.stderr)
        ps=yaml.safe_load(r.stdout)
        assert ps['/target_detector_rknn/model_path']==str(root/'runtime_models/flight_5cls_20260928_fp16.rknn')
        assert ps['/fast_planner_node/sdf_map/obstacles_inflation']==.25
        results.append(dict(trial=name,mode=mode,status='PASS',ground_z=ref['ground_z'],low_z=ref['low_z'],drop_z=ref['drop_z']))
for profile in ['low','high','corridor']:
    r=subprocess.run(['roslaunch','--dump-params','uav_board_trials','localization.launch','mapping_profile:='+profile],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    assert r.returncode==0,r.stderr
    ps=yaml.safe_load(r.stdout)
    assert ps['/cube_side_length']==20.0 and ps['/feature_extract_enable'] is True
    assert ps['/mapping/det_range']==6.0
    (out/('localization_'+profile+'.yaml')).write_text(r.stdout)
    results.append(dict(localization=profile,status='PASS'))
for package in ['uav_mission','uav_high_view','uav_vision','uav_board_trials','fast_lio','freedom','plan_manage','patrol_control','livox_ros_driver2','camera_sdk']:
    path=subprocess.check_output(['rospack','find',package],text=True).strip()
    assert pathlib.Path(path).resolve().is_relative_to(root) if hasattr(pathlib.Path(path),'is_relative_to') else str(pathlib.Path(path).resolve()).startswith(str(root)+'/')
    results.append(dict(package=package,path=path,status='PASS'))
(out/'static_validation.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
