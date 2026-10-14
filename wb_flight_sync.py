"""Optional, bounded read-only SSH mirroring of one supervisor-confirmed run.

Growing bags are staging files. On close, compare every block and repair rewrites
(including chunk headers), then check the whole-file SHA256 before publication.
No recorder, ROS service, flight command or remote file is created here.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
import uuid

from wb_ssh import quote, run_bytes

BLOCK = 1024 * 1024
RATES = (128, 256, 512, 1024)
ACTIVE = {'waiting', 'syncing', 'finishing', 'retrying'}

# Standalone stdlib reader: no environment source, ROS import or board writes.
REMOTE = r'''
import hashlib,json,os,pathlib,sys
def safe(root, value):
    path=root
    for part in pathlib.PurePosixPath(value).parts:
        if part in ('', '.', '..') or part.startswith('.'):
            raise ValueError('Invalid path')
        path=path/part
        if path.is_symlink():raise ValueError('Symlinks forbidden')
    path.resolve().relative_to(root.resolve())
    return path
def token(stat):return [stat.st_dev,stat.st_ino]
def signature(stat):return [stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns]
def writing(path):
    # A suffix or rename alone is insufficient evidence of recorder closure.
    if path.name.endswith('.active'):return True
    if path.with_name(path.name+'.active').exists():return True
    for process in pathlib.Path('/proc').iterdir():
        if not process.name.isdigit():continue
        try:descriptors=list((process/'fd').iterdir())
        except OSError:continue
        for fd in descriptors:
            try:
                if fd.resolve()==path.resolve():
                    info=(process/'fdinfo'/fd.name).read_text()
                    flags=next(int(line.split()[1],8) for line in info.splitlines() if line.startswith('flags:'))
                    if flags & os.O_ACCMODE:return True
            except (OSError,StopIteration):continue
    return False
def handle(request):
    root=pathlib.Path(request['root']).resolve()/'logs'
    if root.is_symlink():raise ValueError('Logs root cannot be a symlink')
    operation=request['operation']
    if operation=='locate':
        marker=('WB_FLIGHT_SYNC_ID='+request['job_id']).encode()
        candidates=set()
        for process in pathlib.Path('/proc').iterdir():
            if not process.name.isdigit():continue
            try:
                if marker not in (process/'environ').read_bytes().split(b'\x00'):continue
                descriptors=list((process/'fd').iterdir())
            except OSError:continue
            for fd in descriptors:
                try:
                    path=fd.resolve()
                    if not path.name.endswith(('.bag','.bag.active')):continue
                    value=path.relative_to(root).as_posix()
                    parts=pathlib.PurePosixPath(value).parts
                    if len(parts)>1 and not parts[0].startswith('flight_workbench'):
                        safe(root,value);candidates.add(parts[0])
                except (OSError,ValueError):continue
        # Never guess "the latest run" or bind unrelated, untagged recordings.
        return {'run':next(iter(candidates)) if len(candidates)==1 else None},b''
    run=safe(root,request['run'])
    if operation=='list':
        if not run.is_dir():return {'files':[]},b''
        files=[];visited=0
        for directory,dirs,names in os.walk(run,followlinks=False):
            visited+=1;parent=pathlib.Path(directory)
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (parent/d).is_symlink())
            if len(parent.relative_to(run).parts)>=5:dirs[:]=[]
            if visited>256:raise ValueError('Run directory scan limit exceeded')
            for name in sorted(names):
                path=parent/name
                if name.startswith('.') or path.is_symlink() or not path.is_file():continue
                # ULog remains a separate, ground-only FC retrieval workflow.
                if not name.endswith(('.bag','.bag.active','.log','.txt','.json','.yaml','.csv')):continue
                stat=path.stat()
                if stat.st_size>32*1024**3:raise ValueError('File exceeds 32 GiB sync limit')
                files.append({'path':path.relative_to(run).as_posix(),'size':stat.st_size,
                              'identity':token(stat),'signature':signature(stat)})
                if len(files)>512:raise ValueError('Too many log files in run')
        return {'files':files},b''
    path=safe(run,request['path'])
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno())
        if token(before)!=request['identity']:raise ValueError('Source replaced')
        if operation=='hash':
            if writing(path):return {'writing':True},b''
            whole=hashlib.sha256();blocks=[]
            while True:
                chunk=stream.read(1024*1024)
                if not chunk:break
                whole.update(chunk);blocks.append(hashlib.sha256(chunk).hexdigest())
            after=path.stat()
            if signature(before)!=signature(after) or writing(path):raise ValueError('Source changed during verification')
            return {'blocks':blocks,'sha256':whole.hexdigest(),'signature':signature(after)},b''
        offset=request['offset'];length=request['length']
        if type(offset) is not int or type(length) is not int or offset<0 or not 0<length<=1024*1024:
            raise ValueError('Invalid chunk range')
        if 'signature' in request and signature(before)!=request['signature']:raise ValueError('Finalized source changed')
        if request.get('check_closed') and writing(path):raise ValueError('Source reopened for writing')
        stream.seek(offset);data=stream.read(min(length,max(0,before.st_size-offset)))
        after=os.fstat(stream.fileno())
        if token(before)!=token(after) or after.st_size<before.st_size:raise ValueError('Source truncated')
        return {'offset':offset,'size':before.st_size,'identity':token(before),
                'sha256':hashlib.sha256(data).hexdigest()},data
meta,data=handle(request)
header=json.dumps(meta,separators=(',',':')).encode()
sys.stdout.buffer.write(('WB_SYNC_'+request['nonce']+' '+str(len(header))+' '+str(len(data))+'\n').encode())
sys.stdout.buffer.write(header+data+('\nWB_SYNC_END_'+request['nonce']+'\n').encode())
'''


def relative(value):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or '\\' in value or ':' in value or value.startswith('/')
            or any(ord(c) < 32 for c in value)
            or any(not p or p.startswith('.') for p in value.split('/'))):
        raise ValueError('非法日志相对路径')
    return value


def local_path(root, value):
    path = root
    for part in PurePosixPath(relative(value)).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('同步目录不允许符号链接')
    path.resolve().relative_to(root.resolve())
    return path


def options(body):
    enabled = body.get('sync_logs', False)
    rate = body.get('sync_rate_kib', 256)
    if type(enabled) is not bool or type(rate) is not int or rate not in RATES:
        raise ValueError('日志同步需为布尔选项；限速请选择128/256/512/1024 KiB/s')
    if enabled and (body.get('mode', 'flight') != 'flight' or body.get('check_config', False)):
        raise ValueError('持续日志同步仅用于flight，preview/配置检查不启用')
    return enabled, rate


class FlightSync:
    def __init__(self, profile_dir):
        self.root = Path(profile_dir).resolve() / 'flight_sync'
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.ended = threading.Event()
        self.thread = None
        self.job = None
        self.board = None
        self.cursor = 0
        self.checkpoint_at = 0

    def snapshot(self):
        with self.lock:
            return {'ok': True, 'job': copy.deepcopy(self.job), 'directory': str(self.root)}

    def active(self):
        return self.thread is not None and self.thread.is_alive()

    def startup_failed(self, detail):
        with self.lock:
            if self.job and not self.active():
                self.job.update(state='paused', detail='同步未启动：'+detail)

    def _save(self):
        with self.lock:
            directory = self.root / self.job['id']
            temporary = directory / '.status.tmp'
            temporary.write_text(json.dumps(self.job, ensure_ascii=False), encoding='utf-8')
            temporary.replace(directory / 'status.json')

    def _state(self, state, detail):
        with self.lock:
            self.job.update(state=state, detail=detail, updated_at=time.time())
            self._save()

    def start(self, board, group_id, rate):
        with self.lock:
            if self.active():
                raise ValueError('上一轮日志仍在同步；请等待或暂停后再启动新一轮同步')
            if board.target.transport != 'ssh':
                raise ValueError('持续日志同步需要SSH连接')
            # Pin this job to the original connection. Credentials stay in memory.
            self.board = copy.copy(board)
            self.board.config = copy.deepcopy(board.config)
            self.board.target = copy.copy(board.target)
            self.job = dict(id=uuid.uuid4().hex, group_id=group_id, rate_kib=rate,
                            host=board.target.host, port=board.target.port, board_root=board.root,
                            state='waiting', detail='等待本轮入口确认日志目录', run=None,
                            files={}, transferred=0, created_at=time.time(), updated_at=time.time())
            directory = self.root / self.job['id']
            if self.root.is_symlink():
                raise ValueError('同步根目录不允许符号链接')
            (directory / 'files').mkdir(parents=True)
            self.job['local_directory'] = str(directory / 'files')
            self.stop.clear(); self.ended.clear()
            self._save()
            self.thread = threading.Thread(target=self._run, daemon=True, name='flight-log-sync')
            self.thread.start()

    def bind(self, run_dir):
        if not self.active() or not run_dir:
            return
        root = PurePosixPath(self.job['board_root']) / 'logs'
        try:
            path = PurePosixPath(str(run_dir).strip())
            if path.is_absolute():
                value = path.relative_to(root).as_posix()
            else:
                value = str(run_dir).strip()
                if value.startswith('logs/'):
                    value = value[5:]
            relative(value)
            with self.lock:
                if self.job['run'] is None:
                    self.job['run'] = value
                    self._save()
        except ValueError:
            self._state('waiting', '入口日志目录不在所选工程logs内，未同步其他目录')

    def finish(self):
        self.ended.set()

    def pause(self):
        self.stop.set()
        if self.job and self.active():
            self._state('pausing', '正在暂停；已接收的临时文件保留')

    def resume(self, board, identifier, running=False):
        with self.lock:
            if self.active():
                raise ValueError('同步线程尚未停止，请稍后重试')
            if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{32}', identifier):
                raise ValueError('非法同步编号')
            path = local_path(self.root, identifier + '/status.json')
            job = json.loads(path.read_text(encoding='utf-8'))
            if job.get('run') is not None:
                relative(job['run'])
            if (job['host'], job['port'], job['board_root']) != (board.target.host, board.target.port, board.root):
                raise ValueError('请连接创建此同步任务的板端与工程')
            if board.target.transport != 'ssh' or job['state'] == 'complete':
                raise ValueError('需要SSH且同步任务尚未完成')
            self.job = job
            self.job['local_directory'] = str(self.root / identifier / 'files')
            self.board = copy.copy(board)
            self.board.config = copy.deepcopy(board.config)
            self.board.target = copy.copy(board.target)
            self.stop.clear(); self.ended.clear()
            if not running:
                self.ended.set()
            self._state('waiting', '正在恢复同步')
            self.thread = threading.Thread(target=self._run, daemon=True, name='flight-log-sync')
            self.thread.start()

    def restore(self):
        if not self.root.is_dir() or self.root.is_symlink():
            return
        paths = [p for p in self.root.iterdir() if re.fullmatch('[0-9a-f]{32}', p.name) and not p.is_symlink()]
        for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                job = json.loads(local_path(path, 'status.json').read_text(encoding='utf-8'))
                if job.get('state') in ACTIVE | {'pausing'}:
                    job.update(state='paused', detail='服务已重启；连接原板端后可继续同步')
                self.job = job
                return
            except (OSError, ValueError):
                continue

    def _request(self, operation, **values):
        if self.stop.is_set():
            raise InterruptedError('同步已暂停')
        nonce = uuid.uuid4().hex
        request = dict(root=self.job['board_root'], run=self.job['run'], operation=operation,
                       nonce=nonce, job_id=self.job['id'], **values)
        source = 'request=' + repr(request) + '\n' + REMOTE
        code = 'import base64;exec(base64.b64decode(%r))' % base64.b64encode(source.encode()).decode()
        command = '%s -c %s' % (quote(self.board.config['connection'].get('board_python', '/usr/bin/python3')), quote(code))
        began = time.monotonic()
        status, output = run_bytes(self.board.target, command, timeout=45)
        if status:
            raise ValueError('SSH读取失败或超时（exit=%s），临时文件保留' % status)
        marker = ('WB_SYNC_' + nonce + ' ').encode()
        start = output.find(marker)
        if start < 0:
            raise ValueError('同步数据标记缺失')
        end = output.find(b'\n', start)
        sizes = output[start+len(marker):end].split()
        if len(sizes) != 2:
            raise ValueError('同步数据头无效')
        header_size, data_size = map(int, sizes)
        if not 0 <= header_size <= 4*BLOCK or not 0 <= data_size <= BLOCK:
            raise ValueError('同步数据长度无效')
        body = output[end+1:]
        if body[header_size+data_size:] != ('\nWB_SYNC_END_' + nonce + '\n').encode():
            raise ValueError('同步数据未完整收到')
        meta = json.loads(body[:header_size]); data = body[header_size:header_size+data_size]
        if data_size and hashlib.sha256(data).hexdigest() != meta['sha256']:
            raise ValueError('传输块校验失败')
        with self.lock:
            self.job['transferred'] += len(output)
        # Aggregate payload limit across requests; no burst of a full MiB at a
        # 128 KiB/s setting because live reads themselves use a smaller chunk.
        self.stop.wait(max(0, len(output)/(self.job['rate_kib']*1024) - (time.monotonic()-began)))
        if self.stop.is_set():
            raise InterruptedError('同步已暂停')
        return meta, data

    def _entry(self, item):
        source = relative(item['path'])
        logical = source[:-7] if source.endswith('.active') else source
        path = local_path(Path(self.job['local_directory']), logical + '.part')
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            entry = self.job['files'].get(logical)
            if not entry or entry['identity'] != item['identity'] or item['size'] < entry['received']:
                published = local_path(Path(self.job['local_directory']), logical)
                if published.exists():
                    published.replace(path.with_name(path.name + '.superseded-' + uuid.uuid4().hex))
                entry = dict(identity=item['identity'], received=0, size=item['size'], complete=False)
                self.job['files'][logical] = entry
                with path.open('wb'):
                    pass
            entry.update(source=source, size=item['size'])
        return logical, entry, path

    def _live(self, items):
        pending = []
        for item in items:
            logical, entry, path = self._entry(item)
            if not entry['complete'] and entry['received'] < item['size']:
                pending.append((item, entry, path))
        if not pending:
            return
        # Round robin prevents a growing bag starving text/metadata or split bags.
        self.cursor %= len(pending)
        item, entry, path = pending[self.cursor]; self.cursor += 1
        offset = entry['received']
        _, data = self._request('read', path=item['path'], identity=item['identity'], offset=offset,
                                length=min(self.job['rate_kib']*1024, item['size']-offset))
        with path.open('r+b') as target:
            target.seek(offset); target.write(data); target.flush()
        with self.lock:
            entry['received'] = offset + len(data)

    def _finalize(self, item):
        logical, entry, path = self._entry(item)
        if entry['complete'] and entry.get('signature') == item['signature']:
            return True
        manifest, _ = self._request('hash', path=item['path'], identity=item['identity'])
        if manifest.get('writing'):
            return False
        target = local_path(Path(self.job['local_directory']), logical)
        # A previously verified text log may have been changed after publication.
        if entry['complete']:
            target.replace(path)
            entry['complete'] = False
        total = manifest['signature'][2]
        with path.open('r+b') as stream:
            stream.truncate(total)
            for index, expected in enumerate(manifest['blocks']):
                if self.stop.is_set():
                    raise InterruptedError('同步已暂停')
                offset = index * BLOCK
                length = min(BLOCK, total-offset)
                stream.seek(offset); current = stream.read(length)
                if hashlib.sha256(current).hexdigest() != expected:
                    # Rate-sized reads also bound wire bursts during final repair.
                    data = bytearray()
                    while len(data) < length:
                        _, chunk = self._request('read', path=item['path'], identity=item['identity'],
                            offset=offset+len(data), length=min(self.job['rate_kib']*1024, length-len(data)),
                            signature=manifest['signature'])
                        if not chunk:
                            raise ValueError('封闭文件块长度不足')
                        data.extend(chunk)
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError('源文件块已变化，等待重新校验')
                    stream.seek(offset); stream.write(data)
            stream.flush(); os.fsync(stream.fileno())
            stream.seek(0); whole = hashlib.sha256()
            while True:
                chunk = stream.read(BLOCK)
                if not chunk:
                    break
                whole.update(chunk)
        if whole.hexdigest() != manifest['sha256']:
            raise ValueError('最终文件校验失败，未发布为完整日志')
        # Cheap stat recheck after transfer catches any reopened/modified source.
        current, _ = self._request('read', path=item['path'], identity=item['identity'], offset=total,
                                   length=1, signature=manifest['signature'], check_closed=True)
        path.replace(target)
        with self.lock:
            entry.update(received=total, size=total, complete=True,
                         sha256=manifest['sha256'], signature=manifest['signature'])
        self._save()
        return True

    def _run(self):
        errors = 0; ended_at = None; stable = None; scanned_at = 0; items = []
        try:
            while not self.stop.is_set():
                if self.ended.is_set() and ended_at is None:
                    ended_at = time.monotonic()
                if not self.job['run']:
                    try:
                        location, _ = self._request('locate')
                        if location.get('run'):
                            self.bind(location['run'])
                    except InterruptedError:
                        raise
                    except (ValueError, OSError):
                        pass  # The supervisor can still supply a confirmed path.
                    if ended_at is not None and time.monotonic()-ended_at > 30:
                        raise RuntimeError('入口未提供本轮日志目录，无法同步；可沿用原日志下载')
                    self.stop.wait(1)
                    continue
                try:
                    if self.ended.is_set() or time.monotonic()-scanned_at >= 5:
                        listing, _ = self._request('list')
                        items = listing['files']; scanned_at = time.monotonic()
                    if self.ended.is_set():
                        self._state('finishing', '入口已结束，等待录制封闭并校验补齐改写块')
                        ready = bool(items)
                        for item in items:
                            ready = self._finalize(item) and ready
                        signature = [(i['path'], i['signature']) for i in items]
                        if ready and stable == signature:
                            self._state('complete', '本轮日志已完整同步并通过SHA256校验')
                            return
                        stable = signature if ready else None
                    else:
                        self._state('syncing', '正在同步本轮日志；临时bag在录制结束后校验')
                        self._live(items)
                    errors = 0
                    if time.monotonic()-self.checkpoint_at > 5:
                        self._save(); self.checkpoint_at = time.monotonic()
                    if ended_at is not None and time.monotonic()-ended_at > 180 and not items:
                        raise RuntimeError('本轮目录没有可同步日志，保留记录供核查')
                    self.stop.wait(1 if self.ended.is_set() else .1)
                except InterruptedError:
                    raise
                except (ValueError, OSError) as error:
                    scanned_at = 0
                    errors += 1
                    self._state('retrying', str(error)+'；正在重试（%d/5）' % errors)
                    if errors >= 5:
                        raise RuntimeError('连续读取失败，已暂停；检查连接后点击继续同步')
                    self.stop.wait(5)
        except InterruptedError:
            pass
        except Exception as error:
            self._state('paused', str(error))
            return
        finally:
            if self.stop.is_set():
                self._state('paused', '同步已暂停；已接收的临时文件保留，可继续同步')
            self._save()
