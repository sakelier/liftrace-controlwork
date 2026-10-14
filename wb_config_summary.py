"""Read-only competition YAML switch summaries; never generate or launch ROS."""
import inspect
import json
import shlex
import yaml
import hashlib


def summarize(settings):
    if not isinstance(settings, dict):
        raise ValueError('场地 YAML 必须为对象')
    required = ('flight_bounds', 'search_center_bounds', 'target_bounds', 'coverage_bounds',
                'staging_xy', 'survey_xy', 'corridor_waypoints', 'high_agl',
                'landing_transit_agl', 'landing_capture_agl')
    if any(key not in settings for key in required):
        raise ValueError('需要完整独立正赛场地 YAML，不能导入专项地图片段')
    for key in required[:4]:
        value = settings[key]
        if not isinstance(value, list) or len(value) != 4 or not all(type(x) in (int, float) for x in value):
            raise ValueError('无效场地范围：' + key)
    if not isinstance(settings['survey_xy'], list) or not isinstance(settings['corridor_waypoints'], list):
        raise ValueError('搜索与走廊航点必须为列表')
    result = {}
    for name, block, key, default in (
            ('motion_optimization', 'motion_optimization', 'enabled', False),
            ('resume_survey', 'survey_policy', 'resume_survey_enabled', False),
            ('obstacle_columns', None, 'obstacle_columns_enabled', None)):
        values = settings if block is None else settings.get(block, {})
        if not isinstance(values, dict):
            raise ValueError('无效配置块：' + str(block))
        value = values.get(key, default)
        if value is not None and type(value) is not bool:
            raise ValueError('配置开关必须为布尔值：' + key)
        result[name] = {'value': value, 'configured': key in values,
                        'key': (block + '.' if block else '') + key}
    geometry_keys = ('flight_bounds', 'search_center_bounds', 'target_bounds', 'coverage_bounds',
                     'staging_xy', 'survey_xy', 'corridor_waypoints', 'landing_xy', 'high_agl', 'low_agl',
                     'landing_transit_agl', 'landing_capture_agl', 'map_size')
    result['geometry'] = {key: settings.get(key) for key in geometry_keys}
    schedule = settings.get('corridor_speed_schedule') or {}
    result['geometry']['corridor_speed_schedule'] = ({key: schedule.get(key, 1 if key == 'entry_waypoints' else None)
        for key in ('axis', 'wall_coordinates', 'entry_waypoints')} if schedule else None)
    result['geometry']['_source_digest'] = hashlib.sha256(json.dumps(settings, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    result['site_confirmed'] = settings.get('site_confirmed') is True
    result['max_agl'] = settings.get('max_agl')
    return result


def parse(text):
    return summarize(yaml.safe_load(text))


def read_command(root, path):
    # Inline the same parser so reading board values requires no tool deployment.
    script = 'import json,pathlib,sys,yaml,hashlib\n' + inspect.getsource(summarize) + '''
root=pathlib.Path(sys.argv[1]).resolve()
path=pathlib.Path(sys.argv[2])
path=(root/path).resolve()
if root not in path.parents:raise ValueError("场地 YAML 必须位于当前工程内")
if path.stat().st_size>1048576:raise ValueError("场地 YAML 过大")
print(json.dumps(summarize(yaml.safe_load(path.read_text(encoding="utf-8"))),ensure_ascii=False))
'''
    return 'python3 -c ' + shlex.quote(script) + ' ' + shlex.quote(root) + ' ' + shlex.quote(path)


def load(workbench, body):
    from pathlib import Path
    group = next((g for g in workbench.config.get('groups', [])
                  if g['id'] == body.get('group_id') and g.get('channel') == 'competition'), None)
    if group is None:raise ValueError('仅支持独立正赛配置')
    path = body.get('competition_config', group.get('site_config'))
    if not isinstance(path, str) or not path.strip() or any(c in path for c in '\r\n\x00'):
        raise ValueError('请填写场地 YAML 路径')
    path = path.strip()
    if 'yaml_text' in body:
        text = body['yaml_text']
        if not isinstance(text, str) or len(text.encode()) > 1048576:raise ValueError('YAML 最大1MiB')
        values = parse(text);source = 'local_import'
    elif workbench.connection.get('state') == 'ok' and workbench.target.transport != 'local':
        code, output = workbench.board.run(read_command(workbench.config['connection']['board_root'], path), timeout=15.)
        if code:raise ValueError('板端 YAML 读取失败：' + output[-1000:])
        try:values = json.loads(output.strip().splitlines()[-1])
        except (ValueError, IndexError):raise ValueError('板端 YAML 返回格式无效')
        source = 'board_yaml'
    else:
        tool = Path(__file__).resolve().parent
        root = tool.parents[1]
        candidate = (root / path).resolve()
        if root not in candidate.parents:raise ValueError('场地 YAML 必须位于当前工程内')
        source = 'pc_yaml'
        if not candidate.is_file():
            reference = (tool / 'competition_templates' / path).resolve()
            if (tool / 'competition_templates').resolve() not in reference.parents or not reference.is_file():
                raise ValueError('本地没有此 YAML，请连接板端读取或导入完整 YAML')
            candidate = reference;source = 'offline_reference'
        if candidate.stat().st_size > 1048576:raise ValueError('YAML 最大1MiB')
        values = parse(candidate.read_text(encoding='utf-8-sig'))
    return {'ok': True, 'path': path, 'source': source, 'values': values}


def browse_directory(root, directory):
    """Read only immediate folders and YAML files, contained in the project."""
    from pathlib import Path
    root = Path(root).resolve()
    path = (root / directory).resolve()
    if path != root and root not in path.parents:
        raise ValueError('只能浏览当前工程内的文件夹')
    if not path.is_dir():
        raise ValueError('文件夹不存在，请选择其他目录')
    entries = []
    for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
        resolved = item.resolve()
        if resolved != root and root not in resolved.parents:
            continue
        if item.is_dir() or (item.is_file() and item.suffix.lower() in ('.yaml', '.yml')):
            entries.append({'name': item.name, 'path': item.relative_to(root).as_posix(),
                            'kind': 'folder' if item.is_dir() else 'yaml'})
        if len(entries) >= 500:
            break
    relative = path.relative_to(root).as_posix()
    parent = path.parent.relative_to(root).as_posix() if path != root else None
    return {'directory': relative, 'parent': parent, 'entries': entries}


def list_files(workbench, body):
    from pathlib import Path
    if not any(g['id'] == body.get('group_id') and g.get('channel') == 'competition'
               for g in workbench.config.get('groups', [])):
        raise ValueError('仅支持独立正赛配置')
    directory = body.get('directory', 'deployment/competition')
    if not isinstance(directory, str) or any(c in directory for c in '\r\n\x00'):
        raise ValueError('无效文件夹')
    if workbench.connection.get('state') == 'ok' and workbench.target.transport != 'local':
        script = 'import json,sys\n' + inspect.getsource(browse_directory) + '\nprint(json.dumps(browse_directory(sys.argv[1],sys.argv[2]),ensure_ascii=False))'
        command = 'python3 -c ' + shlex.quote(script) + ' ' + shlex.quote(workbench.config['connection']['board_root']) + ' ' + shlex.quote(directory)
        code, output = workbench.board.run(command, timeout=15.)
        if code:
            raise ValueError('板端文件夹读取失败：' + output[-1000:])
        try:
            result = json.loads(output.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise ValueError('板端文件列表格式无效')
        source = 'board_yaml'
    else:
        tool = Path(__file__).resolve().parent
        root = tool.parents[1]
        # Embedded workbench uses its source checkout; standalone uses bundled references.
        if not (root / 'deployment/competition').is_dir():
            root = tool / 'competition_templates'
            source = 'offline_reference'
        else:
            source = 'pc_yaml'
        result = browse_directory(root, directory)
    return dict(result, ok=True, source=source)
