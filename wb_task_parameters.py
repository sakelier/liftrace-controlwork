"""Other flight/task parameter page for module 08 and independent competition."""
from wb_flight_parameters import read


def fields(folder):
    if folder not in ('competition','08_full_mission'):
        raise ValueError('仅支持独立正赛和模块08')
    rows=[]
    def add(key,label,section,unit,lower,upper,default,kind='number',help=''):
        rows.append(dict(key=key,label=label,section=section,unit=unit,min=lower,max=upper,default=default,kind=kind,help=help))
    add('cruise_speed','巡航速度上限','飞行与导航','m/s',.1,1.2,None,help='08限速档仍受原生产校验限制：速度、加速度不得超过0.5。')
    add('cruise_acceleration','巡航加速度上限','飞行与导航','m/s²',.1,1.,None,help='运动优化制动模型需与所选加速度相容，以配置检查结果为准。')
    if folder=='08_full_mission':
        add('ordinary_waypoint_dwell_enabled','普通航点停稳等待','飞行与导航','',None,None,False,'bool','开启后位置达标持续0.3秒再推进；不检查速度，不影响投递/H判定。')
    add('initialization_timeout','初始化等待上限','任务时限','s',30,300,90)
    add('motion_action_timeout','单个运动动作时限','任务时限','s',.001,600,90 if folder=='competition' else 30)
    if folder=='competition':
        add('target_action_timeout','单个目标动作时限','任务时限','s',.001,600,120)
        add('lane_spacing','低位覆盖航线间距','搜索与复核','m',.2,1.2,None)
        add('survey_policy.resume_budget_seconds','高位续扫预算','搜索与复核','s',10,180,90,help='续扫开关仍由任务卡片控制，此处设置已开启续扫时的预算。')
    for key,label,unit,lo,hi,default,kind in [
      ('coarse_min_confidence','高位粗识别置信度','',0,1,.6 if folder=='competition' else .75,'number'),
      ('recheck_observe_seconds','低位复核观察时间','s',3,15,5,'number'),
      ('recheck_shift_after_seconds','复核换点等待','s',.5,1,1,'number'),
      ('recheck_shift_radius_m','复核换点半径','m',.4,.6,.5,'number'),
      ('max_uncertainty_m','候选位置最大不确定度','m',.25,.5,.45,'number'),
      ('descent_radius_m','下降候选搜索半径','m',.001,2,1.5 if folder=='competition' else 1.,'number'),
      ('descent_max_candidates','下降候选数量上限','',1,25,25 if folder=='competition' else 9,'int'),
      ('survey_stall_seconds','搜索停滞判定时间','s',3,20,8,'number'),
      ('survey_progress_m','搜索有效进展距离','m',.05,.3,.15,'number')]:
        add('survey_policy.'+key,label,'搜索与复核',unit,lo,hi,default,kind)
    return rows


def current(workbench,body):
    group=next((g for g in workbench.config['groups'] if g['id']==body.get('group_id')),None)
    if not group:raise ValueError('未知任务组')
    folder='competition' if group.get('channel')=='competition' else group.get('folder')
    specs=fields(folder)
    result=read(workbench,dict(body,task_fields=specs))
    result['fields']=specs
    return result


def schema(workbench,body):
    group=next((g for g in workbench.config['groups'] if g['id']==body.get('group_id')),None)
    if not group:raise ValueError('未知任务组')
    return dict(ok=True,fields=fields('competition' if group.get('channel')=='competition' else group.get('folder')))
