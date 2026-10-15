"""Geometry-only overlays for the independent competition entry."""
import hashlib
import inspect
import json
import math
import shlex
import base64
from datetime import datetime, timedelta, timezone


def validate_patch(value):
    allowed = {'flight_bounds', 'search_center_bounds', 'target_bounds', 'coverage_bounds',
               'staging_xy', 'survey_xy', 'corridor_waypoints', 'landing_xy',
               'high_agl', 'low_agl', 'landing_transit_agl', 'landing_capture_agl',
               'corridor_speed_schedule', '_source_digest', 'map_size'}
    if not isinstance(value, dict) or not value or set(value) - allowed:
        raise ValueError('仅允许独立正赛的航点、范围、墙面和观察高度')
    def number(v):
        return type(v) in (int, float) and math.isfinite(v)
    def vector(v, n):
        return isinstance(v, list) and len(v) == n and all(number(x) for x in v)
    for key, v in value.items():
        if key == '_source_digest':
            if not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v):
                raise ValueError('请先读取场地 YAML')
        elif key.endswith('_bounds'):
            if not vector(v, 4) or v[0] >= v[1] or v[2] >= v[3]:raise ValueError('无效范围：' + key)
        elif key == 'map_size':
            if not vector(v, 3) or any(x <= 0 for x in v):raise ValueError('地图尺寸需三个正数')
        elif key in ('staging_xy', 'landing_xy'):
            if not (key == 'landing_xy' and v is None) and not vector(v, 2):raise ValueError('无效 XY：' + key)
        elif key == 'survey_xy':
            if not isinstance(v, list) or not 1 <= len(v) <= 8 or not all(vector(p, 2) for p in v):raise ValueError('高位搜索需1～8个XY点')
        elif key == 'corridor_waypoints':
            if not isinstance(v, list) or len(v) > 100:raise ValueError('无效走廊航点')
            for p in v:
                if not isinstance(p, dict) or set(p) != {'x', 'y', 'agl'} or not all(number(x) for x in p.values()) or not .5 <= p['agl'] <= 1.8:
                    raise ValueError('走廊点需有限x/y/agl，FC高度0.5～1.8m')
        elif key == 'corridor_speed_schedule':
            if v is None:continue
            if not isinstance(v, dict) or set(v) != {'axis', 'wall_coordinates', 'entry_waypoints'}:raise ValueError('墙面配置仅允许轴、墙位置和入口序号')
            if type(v['axis']) is not int or v['axis'] not in (0, 1) or not isinstance(v['wall_coordinates'], list) or not v['wall_coordinates'] or not all(number(x) for x in v['wall_coordinates']) or type(v['entry_waypoints']) is not int or v['entry_waypoints'] < 1:raise ValueError('无效墙面几何')
        elif key == 'low_agl':
            if not number(v) or not 1.0 <= v <= 1.8:raise ValueError('低位搜索/复核高度需1.0～1.8m')
        elif not number(v) or not 0 < v <= 4:raise ValueError('无效高度：' + key)
    if '_source_digest' not in value:raise ValueError('请先读取场地 YAML')
    return json.loads(json.dumps(value, allow_nan=False))


def overlay_command(source, geometry, revision, motion=None, columns=None, resume=None):
    for value in (motion, columns, resume):
        if value not in (None, 'on', 'off'):raise ValueError('开关仅支持on/off或继承')
    if not isinstance(revision, str) or not revision.isascii() or not revision.isalnum() or not 1 <= len(revision) <= 32:
        raise ValueError('请重新生成坐标命令')
    clean = validate_patch(geometry)
    data = json.dumps(clean, sort_keys=True, separators=(',', ':'), allow_nan=False)
    token = datetime.now(timezone(timedelta(hours=8))).strftime('%m%d-%H%M')
    relative = 'logs/flight_workbench/site_overlays/competition_' + token + '.yaml'
    script = 'import pathlib,sys,json,base64,hashlib,math,tempfile,yaml\n' + inspect.getsource(validate_patch) + '''
root=pathlib.Path.cwd().resolve()
source=(root/sys.argv[1]).resolve();dest=(root/sys.argv[2]).resolve()
if root not in source.parents or root not in dest.parents:raise ValueError("配置路径必须在当前工程内")
settings=yaml.safe_load(source.read_text(encoding="utf-8"))
patch=validate_patch(json.loads(base64.b64decode(sys.argv[3])))
digest=hashlib.sha256(json.dumps(settings,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
if patch.pop('_source_digest')!=digest:raise ValueError("原场地 YAML 已改变，请重新读取并生成命令")
for key,value in patch.items():
 if key=='corridor_speed_schedule' and value is not None:
  settings[key]=dict(settings.get(key) or {},**value)
 else:settings[key]=value
sys.path[:0]=[str(root/'patrol_uav_ws-patrol_planner/src/uav_mission/src'),str(root/'vision_ws/src/uav_high_view/src')]
from uav_mission.competition_config import validate,generate,apply_overrides
switches=json.loads(sys.argv[4])
effective=apply_overrides(settings,**switches)
validate(effective,flight=False)
if settings.get('site_confirmed') and len(settings['corridor_waypoints'])>=2 and settings['landing_xy'] is not None:
 rig=yaml.safe_load((root/'patrol_uav_ws-patrol_planner/src/uav_mission/config/competition/known_rig.yaml').read_text())
 with tempfile.TemporaryDirectory() as tmp:generate(root,tmp,effective,(0.,0.,0.),rig)
content=yaml.safe_dump(settings,sort_keys=False,allow_unicode=True)
dest.parent.mkdir(parents=True,exist_ok=True)
if dest.exists() and dest.read_text(encoding='utf-8')!=content:raise ValueError('同一分钟的运行配置已存在且内容不同，请下一分钟重新生成命令；原配置未覆盖')
if not dest.exists():
 with dest.open('x',encoding='utf-8') as handle:handle.write(content)
print('COMPETITION_SITE_OVERLAY='+str(dest))
'''
    switches = json.dumps(dict(motion=motion, columns=columns, resume=resume))
    command = 'python3 -c ' + shlex.quote(script) + ' ' + shlex.quote(source) + ' ' + shlex.quote(relative) + ' ' + shlex.quote(base64.b64encode(data.encode()).decode()) + ' ' + shlex.quote(switches)
    return relative, command
