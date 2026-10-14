"""Read inherited preflight values without ROS, file writes or flight actions."""
import base64
import json
import wb_board
from wb_flight_settings import DROP_FOLDERS, H_FOLDERS

READ_SOURCE = r'''
def read_current_files(root, source, folder, speed_profile=None, geometry=None):
    import copy, pathlib, sys, yaml
    root=pathlib.Path(root).resolve();sources=[];labels={};warnings=[]
    def load(relative):
        path=pathlib.Path(relative)
        if not path.is_absolute():path=root/path
        path=path.resolve()
        if root not in path.parents:raise ValueError('参数文件不在所选工程内')
        if path.stat().st_size>2*1024*1024:raise ValueError('参数文件超过2MiB')
        data=yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}
        if not isinstance(data,dict):raise ValueError('参数文件顶层必须是对象')
        sources.append(str(path));return data,str(path)
    def update(settings,data,label):
        for key,value in data.items():settings[key]=copy.deepcopy(value);labels[key]=label
    sys.path[:0]=[str(root/'deployment/board_trials_4x4/common/uav_board_trials/scripts'),str(root/'patrol_uav_ws-patrol_planner/src/uav_mission/src'),str(root/'vision_ws/src/uav_high_view/src')]
    settings={}
    if folder=='competition':
        raw,label=load(source);update(settings,raw,label)
    else:
        raw,label=load('deployment/board_trials_4x4/'+folder+'/settings.yaml');update(settings,raw,label)
        raw,label=load(source)
        from trial_config import apply_site_profile
        apply_site_profile(settings,copy.deepcopy(raw));labels.update({key:label for key in raw})
        if speed_profile=='competition':
            if folder not in ('05_low_multi','08_full_mission'):raise ValueError('该任务不支持08速度档')
            raw,label=load('deployment/board_trials_4x4/08_full_mission/competition_speed.yaml')
            if folder=='05_low_multi':
                for key in ('drop_agl','release_min_agl','release_max_agl','resume_survey_enabled'):raw.pop(key,None)
            update(settings,raw,label)
    if geometry:
        geometry_keys = (('flight_bounds','search_center_bounds','target_bounds','coverage_bounds',
                          'staging_xy','survey_xy','landing_xy','corridor_waypoints','corridor_speed_schedule',
                          'high_agl','landing_transit_agl','landing_capture_agl') if folder=='competition' else
                         ('flight_area','landing_xy','corridor_waypoints','corridor_geometry','search_waypoints_xy'))
        for key in geometry_keys:
            if key in geometry:
                settings[key]=(dict(settings.get(key,{}) or {},**geometry[key]) if key in ('flight_area','corridor_speed_schedule') and geometry[key] is not None else copy.deepcopy(geometry[key]))
                labels[key]='本机地图坐标草稿'
    values={};origins={}
    def put(key,value,default='机载代码默认'):
        values[key]=value;origins[key]=labels.get(key,default)
    drop=folder in ('01_visual_interrupt','02_high_view_revisit','05_low_multi','06_high_priority','08_full_mission','competition')
    land=folder in ('03_h_landing','04_corridor_landing','05_low_multi','08_full_mission','competition')
    drop_fields=('drop_horizontal_compensation_mode','drop_descent_mode','drop_agl','release_min_agl','release_max_agl','drop_descent_speed_mps','drop_descent_mode4_speed_mps','drop_descent_acceleration_mps2','drop_descent_braking_mps2','drop_descent_hold_tolerance_m')
    h_fields=('landing_alignment_mode','landing_descent_mode','landing_handoff_mode','landing_descent_speed_mps')
    for key in (drop_fields if drop else ())+(h_fields if land else ()):
        if key in settings:put(key,settings[key])
    if land and isinstance(settings.get('landing_offboard'),dict):
        for key in ('descent_speed','touchdown_overtravel'):
            if key in settings['landing_offboard']:put('landing_offboard.'+key,settings['landing_offboard'][key],labels.get('landing_offboard','配置文件'))
    if drop:
        try:
            from uav_mission.drop_descent_config import drop_descent_parameters,drop_horizontal_compensation_mode
            from uav_mission.drop_height_config import release_heights
            descent=drop_descent_parameters(settings);put('drop_horizontal_compensation_mode',drop_horizontal_compensation_mode(settings))
            for key,inner in [('drop_descent_mode','mode'),('drop_descent_speed_mps','speed_mps'),('drop_descent_mode4_speed_mps','velocity_speed_mps'),('drop_descent_acceleration_mps2','acceleration_mps2'),('drop_descent_braking_mps2','braking_mps2'),('drop_descent_hold_tolerance_m','hold_tolerance_m')]:
                if inner in descent:put(key,descent[inner])
            lower,upper,_,_=release_heights(settings)
            put('release_min_agl',lower,'机载代码按投递高度计算');put('release_max_agl',upper,'机载代码按投递高度计算')
        except (ImportError,ValueError,KeyError,TypeError) as error:warnings.append('部分投递默认参数无法解析：'+str(error))
    details={key:settings[key] for key in ('landing_xy','landing_transit_agl','landing_capture_agl') if land and key in settings}
    if land:
        put('landing_handoff_mode',settings.get('landing_handoff_mode','AUTO.LAND'),'机载入口默认')
        try:
            from uav_mission.landing_posctl_config import landing_alignment_mode,landing_descent_parameters,validate_landing_posctl,landing_control_parameters
            from uav_mission.landing_offboard_config import validate_landing_offboard
            put('landing_alignment_mode',landing_alignment_mode(settings));descent=landing_descent_parameters(settings)
            put('landing_descent_mode',descent['mode']);put('landing_descent_speed_mps',descent['speed_mps'])
            offboard=validate_landing_offboard(settings)
            for key in ('descent_speed','touchdown_overtravel'):put('landing_offboard.'+key,offboard[key],labels.get('landing_offboard','配置文件') if key in settings.get('landing_offboard',{}) else '机载代码默认')
            details['landing_posctl']=validate_landing_posctl(settings)
            rig,_=load('patrol_uav_ws-patrol_planner/src/uav_mission/config/competition/known_rig.yaml' if folder=='competition' else 'deployment/board_trials_4x4/common/uav_board_trials/config/known_rig.yaml')
            target,trigger,_=landing_control_parameters(settings,0.,float(rig['fc_ground_clearance']))
            details.update(landing_descent_target_agl=target,handoff_trigger_agl=trigger)
            if values['landing_handoff_mode']=='OFFBOARD':details['touchdown_target_agl']=float(rig['fc_ground_clearance'])-offboard['touchdown_overtravel']
        except (ImportError,ValueError,KeyError,TypeError,OSError) as error:warnings.append('部分H降落默认参数无法解析：'+str(error))
    return dict(values=values,origins=origins,sources=sources,details=details,warnings=warnings,description='所选启动配置的继承参数；不是飞行中的ROS参数快照')
'''


def read(workbench, body):
    group=next((g for g in workbench.config.get('groups',[]) if g['id']==body.get('group_id')),None)
    if not group or not (group.get('channel')=='competition' or group.get('channel')=='module' and group.get('folder') in DROP_FOLDERS+H_FOLDERS):raise ValueError('该组没有投递/H参数编辑功能')
    if workbench.connection.get('state')!='ok' or workbench.target.transport=='local':raise ValueError('请先连接板端再读取现有参数；未连接时仅显示本机覆盖，不使用示例值代替')
    folder='competition' if group.get('channel')=='competition' else group['folder']
    source=body.get('competition_config') if folder=='competition' else None
    if source is None:source=group.get('site_config') or '{site_dir}/test_area.yaml'
    if not isinstance(source,str) or not source.strip():raise ValueError('请选择有效现场配置路径')
    source=wb_board.substitute(source.strip(),wb_board.group_variables(workbench.config,group));speed=body.get('speed_profile')
    if speed not in (None,'','limited','competition') or speed=='competition' and folder not in ('05_low_multi','08_full_mission'):raise ValueError('无效速度档')
    geometry=body.get('site_geometry')
    if geometry is not None:
        if folder=='competition':
            import wb_competition_geometry
            geometry=wb_competition_geometry.validate_patch(geometry)
        else:
            import wb_geometry
            geometry=wb_geometry.validate_geometry(geometry)
    request=dict(root=workbench.board.root,source=source,folder=folder,speed_profile=speed,geometry=geometry)
    script=READ_SOURCE+'\nimport json\nrequest='+repr(request)+'\nprint("WB_FLIGHT_PARAMETERS="+json.dumps(read_current_files(**request),ensure_ascii=True))\n'
    snippet='import base64;exec(base64.b64decode(%r))'%base64.b64encode(script.encode()).decode()
    command='%s -c %s'%(wb_board.quote(workbench.config['connection'].get('board_python','/usr/bin/python3')),wb_board.quote(snippet))
    code,output=workbench.board.run(command,timeout=25)
    lines=[line for line in output.splitlines() if line.startswith('WB_FLIGHT_PARAMETERS=')]
    if code or not lines:raise ValueError('读取现有参数失败，请核对板端现场配置路径及Python环境；表单未填入猜测值')
    result=json.loads(lines[-1].split('=',1)[1]);result.update(ok=True,group_id=group['id'],source=source,speed_profile=speed)
    return result
