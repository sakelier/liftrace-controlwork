"""Flight-before-edit drafts; reuse the existing immutable geometry overlay lane."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import threading
import uuid
import yaml
import wb_board
import wb_geometry
from wb_waypoint_validation import validate

LOCK = threading.RLock()
FOLDERS = {'04_corridor_landing': 'module04.yaml', '05_low_multi': 'module05.yaml', '08_full_mission': 'module08.yaml'}
FIELDS = ('flight_area', 'corridor_waypoints', 'landing_xy', 'corridor_geometry')
MAP_FIELDS = FIELDS + ('search_waypoints_xy', 'high_agl', 'low_agl', 'max_agl')
READ_SOURCE = '''import json,pathlib,sys,yaml
root=pathlib.Path(sys.argv[1]).resolve(); path=pathlib.Path(sys.argv[2])
if not path.is_absolute():path=root/path
path=path.resolve()
if root not in path.parents:raise ValueError("site outside project")
if path.stat().st_size>2*1024*1024:raise ValueError("site too large")
site=yaml.safe_load(path.read_text())
settings=yaml.safe_load((root/'deployment/board_trials_4x4'/sys.argv[3]/'settings.yaml').read_text())
for key in ('low_agl','high_agl','max_agl'):
 if key not in site and key in settings:site[key]=settings[key]
print("WB_WAYPOINT_SITE="+json.dumps(site,ensure_ascii=True))
'''


def describe(workbench, body):
    if not isinstance(body, dict): raise ValueError('请求体必须是对象')
    group = next((g for g in workbench.config.get('groups', []) if g['id'] == body.get('group_id')), None)
    if not group or group.get('channel') != 'module' or group.get('folder') not in FOLDERS:
        raise ValueError('地图调整支持任务二、模块04与模块08')
    source = wb_board.substitute(group.get('site_config') or '{site_dir}/test_area.yaml', wb_board.group_variables(workbench.config, group))
    key = [workbench.target.host, workbench.board.root, group['id'], source]
    scope = hashlib.sha256(json.dumps(key, ensure_ascii=True).encode()).hexdigest()[:24]
    path = Path(wb_board.profile_path('waypoint_drafts'))/(scope+'.json')
    return group, source, scope, path


def draft(workbench, body):
    group, source, scope, path = describe(workbench, body)
    with LOCK:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('scope') != scope: raise ValueError('草稿来源不匹配')
            data['patch'] = wb_geometry.validate_geometry(data['patch'])
        except (OSError, ValueError, KeyError): data = None
    return {'ok': True, 'scope': scope, 'source': source, 'draft': data}


def merge(site, patch):
    result = copy.deepcopy(site)
    for key in MAP_FIELDS:
        if key in patch:
            result[key] = dict(result.get(key, {}), **patch[key]) if key == 'flight_area' else copy.deepcopy(patch[key])
    return result


def context(workbench, body):
    group, source, scope, _ = describe(workbench, body)
    loaded = draft(workbench, body)
    if workbench.connection.get('state') == 'ok' and workbench.target.transport != 'local':
        encoded = base64.b64encode(READ_SOURCE.encode()).decode()
        snippet = 'import base64;exec(base64.b64decode(%r))' % encoded
        command = '%s -c %s %s %s %s' % (wb_board.quote(workbench.config['connection'].get('board_python', '/usr/bin/python3')),
                    wb_board.quote(snippet), wb_board.quote(workbench.board.root), wb_board.quote(source), wb_board.quote(group['folder']))
        code, output = workbench.board.run(command, timeout=20)
        lines = [line for line in output.splitlines() if line.startswith('WB_WAYPOINT_SITE=')]
        if code or not lines: raise ValueError('无法读取所选板端现场配置；请检查路径与连接，未使用示例代替板端文件')
        site = json.loads(lines[-1].split('=', 1)[1]); origin = '板端所选现场配置'
    else:
        site = yaml.safe_load((Path(__file__).parent/'waypoint_templates'/FOLDERS[group['folder']]).read_text(encoding='utf-8-sig'))
        origin = '离线参考模板；实际生效值需通过板端配置检查确认'
    if not isinstance(site, dict): raise ValueError('现场配置必须是对象')
    # Fill only missing display fields, with clear offline context; no flight values.
    if 'flight_area' not in site: raise ValueError('现场配置缺少flight_area，无法建立米制地图')
    if loaded['draft'] and loaded['draft'].get('enabled', True): site = merge(site, loaded['draft']['patch'])
    if body.get('site_geometry'): site = merge(site, wb_geometry.validate_geometry(body['site_geometry']))
    if group['folder']=='05_low_multi':
        site.setdefault('search_waypoints_xy',[[v,0.] for v in site.get('search_line_x',[.6,1.2,1.8,2.4,3.])])
        site.setdefault('corridor_waypoints',[])
        site.setdefault('landing_xy',None)
    return dict(ok=True, folder=group['folder'], site=site, source=source, scope=scope, origin=origin,
                name=group['name'], draft=loaded['draft'])


def patch_from_site(site):
    errors = validate(site)
    if errors: raise ValueError('；'.join(errors))
    patch = {key: copy.deepcopy(site[key]) for key in MAP_FIELDS if key in site}
    return wb_geometry.validate_geometry(patch)


def import_yaml(body):
    """Load local geometry into an editor snapshot, without saving or board writes."""
    text = body.get('text')
    if not isinstance(text, str) or not 0 < len(text.encode('utf-8')) <= 2*1024*1024:
        raise ValueError('YAML 文件大小须为 1B～2MiB')
    try:
        imported = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError('YAML 格式错误：'+str(error)) from error
    if not isinstance(imported, dict) or not any(key in imported for key in MAP_FIELDS):
        raise ValueError('需要含 flight_area、corridor_waypoints、landing_xy 或 corridor_geometry 的地图配置对象')
    base = body.get('base_site')
    if not isinstance(base, dict): raise ValueError('请先打开地图，再导入本机文件')
    patch = {key: imported[key] for key in MAP_FIELDS if key in imported}
    if 'flight_area' in patch and not isinstance(patch['flight_area'],dict): raise ValueError('flight_area 必须是配置对象')
    result = merge(base, patch)
    patch_from_site(result)
    ignored = [str(key) for key in imported if key not in MAP_FIELDS]
    return dict(ok=True, site=result, imported_fields=list(patch), ignored_fields=ignored)


def export_yaml(body):
    patch = patch_from_site(body.get('site'))
    return {'ok': True, 'yaml': '# 地图与航点配置；XY单位米，AGL为飞控中心离地高度。\n'+yaml.safe_dump(patch,allow_unicode=True,sort_keys=False)}


def save(workbench, body):
    group, source, scope, path = describe(workbench, body)
    if body.get('scope') != scope: raise ValueError('连接或现场配置已改变，请重新打开地图')
    trial = workbench.sessions.get('trial')
    if trial and trial.state in ('starting', 'running'): raise ValueError('任务运行期间不能应用航点；先结束当前任务')
    if group['folder']!='05_low_multi' and 'search_waypoints_xy' in (body.get('site') or {}):
        raise ValueError('低空搜索XY只适用于任务二')
    if group['folder']=='05_low_multi' and 'search_waypoints_xy' not in (body.get('site') or {}):
        raise ValueError('任务二必须填写低空搜索XY航点')
    patch = patch_from_site(body.get('site'))
    if group['folder']=='04_corridor_landing':
        # The corridor-only map has no search-height editor; keep its authority.
        patch.pop('high_agl',None);patch.pop('low_agl',None)
    import_name = body.get('import_name')
    if import_name is not None and (not isinstance(import_name,str) or len(import_name)>255 or any(c in import_name for c in '/\\\r\n')):
        raise ValueError('导入文件名不合法')
    data = dict(scope=scope, source=source, patch=patch, revision=uuid.uuid4().hex, enabled=True, import_name=import_name)
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    return dict(ok=True, **data)


def disable(workbench, body):
    _, _, scope, path = describe(workbench, body)
    trial = workbench.sessions.get('trial')
    if trial and trial.state in ('starting', 'running'): raise ValueError('任务运行期间不能切换航点来源')
    if body.get('scope') != scope: raise ValueError('现场配置来源已变化，请刷新任务组')
    with LOCK:
        data = draft(workbench, body)['draft']
        if data:
            data['enabled'] = False
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(path)
    return {'ok': True}
