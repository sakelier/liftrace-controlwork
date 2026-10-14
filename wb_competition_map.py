"""Adapt independent competition geometry to the existing module-08 map UI."""
import copy
import json
import uuid
import yaml
import wb_config_summary
import wb_competition_geometry


def to_site(patch, max_agl):
    p = copy.deepcopy(patch)
    walls = p.get('corridor_speed_schedule')
    return dict(flight_area=dict(center_bounds=p['flight_bounds'], target_bounds=p['target_bounds'],
                search_bounds=p['search_center_bounds'], staging_xy=p['staging_xy'],
                survey_xy=p['survey_xy'], map_size=p['map_size']),
                corridor_waypoints=p['corridor_waypoints'], landing_xy=p['landing_xy'],
                corridor_geometry=(dict(wall_axis=walls['axis'],wall_coordinates=walls['wall_coordinates'],
                entry_waypoints=walls['entry_waypoints']) if walls else None),
                high_agl=p['high_agl'], max_agl=max_agl,
                landing_transit_agl=p['landing_transit_agl'],landing_capture_agl=p['landing_capture_agl'],
                coverage_bounds=p['coverage_bounds'],_competition_geometry=p)


def to_patch(site, complete=True):
    if not isinstance(site, dict) or not isinstance(site.get('_competition_geometry'),dict):
        raise ValueError('请从独立正赛卡片打开地图')
    allowed={'flight_area','corridor_waypoints','landing_xy','corridor_geometry','high_agl','max_agl',
             'landing_transit_agl','landing_capture_agl','coverage_bounds','_competition_geometry'}
    if set(site)-allowed:raise ValueError('地图中含不支持的字段')
    p=copy.deepcopy(site['_competition_geometry']);area=site['flight_area']
    for src,dst in (('center_bounds','flight_bounds'),('target_bounds','target_bounds'),('search_bounds','search_center_bounds'),
                    ('staging_xy','staging_xy'),('survey_xy','survey_xy'),('map_size','map_size')):
        p[dst]=copy.deepcopy(area[src])
    for key in ('corridor_waypoints','landing_xy','high_agl','landing_transit_agl','landing_capture_agl','coverage_bounds'):
        p[key]=copy.deepcopy(site[key])
    walls=site.get('corridor_geometry')
    p['corridor_speed_schedule']=(dict(axis=walls['wall_axis'],wall_coordinates=walls['wall_coordinates'],entry_waypoints=walls['entry_waypoints']) if walls else None)
    p=wb_competition_geometry.validate_patch(p)
    def inside(v,b):return b[0]<=v[0]<=b[1] and b[2]<=v[1]<=b[3]
    outer=p['flight_bounds'];search=p['search_center_bounds']
    for key,container in (('search_center_bounds',outer),('target_bounds',outer),('coverage_bounds',search)):
        b=p[key]
        if not all(inside(v,container) for v in ([b[0],b[2]],[b[1],b[3]])):raise ValueError(key+' 必须位于上级范围内')
    if not inside([0,0],outer) or not inside(p['staging_xy'],search):raise ValueError('起飞原点/准备点超出范围')
    if any(not inside(v,search) for v in p['survey_xy']):raise ValueError('高位搜索点超出搜索中心范围')
    if complete and (len(p['corridor_waypoints'])<2 or p['landing_xy'] is None):raise ValueError('请填写至少两个走廊点和H中心')
    if (p['landing_xy'] is not None and not inside(p['landing_xy'],outer)) or any(not inside([v['x'],v['y']],outer) for v in p['corridor_waypoints']):raise ValueError('走廊/H点超出飞行范围')
    walls=p['corridor_speed_schedule']
    if complete and walls and walls['entry_waypoints']>len(p['corridor_waypoints']):raise ValueError('入口航点数不能超过走廊点数')
    size=p['map_size']
    if max(abs(outer[0]),abs(outer[1]))+.3>=size[0]/2 or max(abs(outer[2]),abs(outer[3]))+.3>=size[1]/2:raise ValueError('地图XY尺寸不足')
    if not 2<=p['high_agl']<=3 or p['high_agl']>site['max_agl'] or size[2]<site['max_agl']+.3:raise ValueError('高位高度或地图Z尺寸不符合原场地限制')
    return p


def preview(body):
    try:p=to_patch(body.get('site'));errors=[]
    except (ValueError,KeyError,TypeError) as error:p={};errors=[str(error)]
    return dict(ok=True,errors=errors,yaml=yaml.safe_dump({k:v for k,v in p.items() if k!='_source_digest'},allow_unicode=True,sort_keys=False))


def context(workbench, body):
    result=wb_config_summary.load(workbench,body)
    patch=result['values']['geometry'];draft=body.get('site_geometry')
    if draft is not None:
        draft=wb_competition_geometry.validate_patch(draft)
        if draft['_source_digest']!=patch['_source_digest']:raise ValueError('源YAML已变化，请使用原现场配置后重新打开地图')
        patch={**patch,**draft}
    scope=json.dumps([workbench.target.host,workbench.board.root,body.get('group_id'),result['path']],ensure_ascii=True)
    origin={'board_yaml':'板端所选场地配置','pc_yaml':'PC仓库配置（未核对板端）',
            'offline_reference':'随包离线参考（未核对板端）','local_import':'本机导入配置'}[result['source']]
    return dict(ok=True,folder='competition',site=to_site(patch,result['values']['max_agl']),scope=scope,
                source=result['path'],origin=origin,summary=result)


def save(workbench, body):
    group=next((g for g in workbench.config.get('groups',[]) if g['id']==body.get('group_id') and g.get('channel')=='competition'),None)
    if group is None:raise ValueError('仅支持独立正赛')
    trial=workbench.sessions.get('trial')
    if trial and trial.state in ('starting','running'):raise ValueError('任务运行中不能应用航点')
    source=body.get('competition_config',group['site_config'])
    scope=json.dumps([workbench.target.host,workbench.board.root,group['id'],source],ensure_ascii=True)
    if body.get('scope')!=scope:raise ValueError('连接/场地来源已改变，请重新打开地图')
    return dict(ok=True,patch=to_patch(body.get('site')),revision=uuid.uuid4().hex)


def import_yaml(body):
    text=body.get('text')
    if not isinstance(text,str) or not 0<len(text.encode())<=2*1024*1024:raise ValueError('YAML最大2MiB')
    raw=yaml.safe_load(text)
    if not isinstance(raw,dict):raise ValueError('YAML顶层必须为对象')
    base=body.get('base_site');p=to_patch(base,complete=False)
    keys=set(p)-{'_source_digest'};used=set(raw)&keys
    if not used:raise ValueError('需要独立正赛的地图字段，不接受专项flight_area格式')
    update={k:copy.deepcopy(raw[k]) for k in used}
    if isinstance(update.get('corridor_speed_schedule'),dict):
        schedule=update['corridor_speed_schedule']
        update['corridor_speed_schedule']={k:schedule.get(k,1 if k=='entry_waypoints' else None)
            for k in ('axis','wall_coordinates','entry_waypoints')}
    p.update(update);p=wb_competition_geometry.validate_patch(p)
    site=to_site(p,base['max_agl']);to_patch(site)
    return dict(ok=True,site=site,ignored_fields=[k for k in raw if k not in keys])


def export_yaml(body):
    p=to_patch(body.get('site'));p.pop('_source_digest')
    return dict(ok=True,yaml='# 独立正赛地图与航点；不含速度、投递模式或场地确认。\n'+yaml.safe_dump(p,allow_unicode=True,sort_keys=False))
