"""Read-only manifest catalog, bounded SSH downloads and PC-side map exports."""
import base64
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import threading
import time
import uuid
import zipfile

from wb_ssh import quote, run_bytes

MAX_FILE = 32*1024**3
REMOTE = r'''
import hashlib,json,os,pathlib,re,sys,time
request=json.loads(sys.argv[1])
base=pathlib.Path(request['root'])/'logs'
if base.is_symlink():raise ValueError('logs symlinks forbidden')
root=base.resolve()
def safe(parent,value):
    if not isinstance(value,str) or not value or '\\' in value or value.startswith('/'):
        raise ValueError('invalid relative path')
    path=parent
    for part in value.split('/'):
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}',part):raise ValueError('invalid path component')
        path=path/part
        if path.is_symlink():raise ValueError('symlinks forbidden')
    path.resolve().relative_to(parent.resolve())
    return path
def read(path):
    if not path.is_file() or path.stat().st_size>2*1024**2:return {}
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}
def signature(st):return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns]
def alive(owner):
    try:
        text=(pathlib.Path('/proc')/str(int(owner['pid']))/'stat').read_text().rsplit(')',1)[1].split()
        return text[0]!='Z' and text[19]==owner['start']
    except (OSError,ValueError,KeyError,IndexError):return False
def item(name):
    folder=safe(root,name)/'mapping'
    if folder.is_symlink():raise ValueError('mapping symlink forbidden')
    manifest=read(folder/'manifest.json')
    if manifest.get('version')!=1:raise ValueError('no supported mapping manifest')
    active=bool(manifest.get('active'))
    if active and not alive(read(folder/'owner.json')) and time.time()-manifest.get('started_at',0)>10:
        manifest=dict(manifest,status='partial',reason='recorder no longer alive; original manifest not finalized')
        active=False
    files=[]
    for info in manifest.get('files',[]):
        filename=info.get('name','')
        if '/' in filename or not filename.endswith('.bag') or not info.get('closed'):continue
        path=safe(folder,filename)
        if not path.is_file() or path.with_name(path.name+'.active').exists():continue
        st=path.stat()
        if st.st_size!=info.get('size') or st.st_size>32*1024**3:continue
        files.append(dict(name=filename,size=st.st_size,signature=signature(st),closed=True))
    allowed=['metadata.json'] if active else ['metadata.json','manifest.json','summary.json','effective_parameters.json','versions.json','recorder.log']
    if not active and (folder/'configs').is_dir() and not (folder/'configs').is_symlink():
        allowed.extend('configs/'+p.name for p in sorted((folder/'configs').iterdir()) if p.suffix in ('.json','.yaml','.txt'))
    for filename in allowed:
        path=safe(folder,filename)
        if path.is_file() and path.stat().st_size<=2*1024**2:
            st=path.stat();files.append(dict(name=filename,size=st.st_size,signature=signature(st),closed=True))
    manifest.pop('context',None);manifest.pop('settings',None)
    return dict(run=name,manifest=manifest,active=active,files=files)
operation=request['operation']
if operation=='catalog':
    entries=[]
    if root.is_dir():
        directories=[p for p in root.iterdir() if not p.is_symlink() and p.is_dir() and not p.name.startswith('.')]
        if len(directories)>10000:raise ValueError('too many run directories; archive old logs')
        names=[p.name for p in sorted(directories,key=lambda p:p.name,reverse=True) if (p/'mapping/manifest.json').is_file()]
    else:names=[]
    page=request.get('page',0)
    if type(page) is not int or page<0:raise ValueError('invalid page')
    for name in names[page*20:(page+1)*20]:
        try:entries.append(item(name))
        except (ValueError,OSError):continue
    result=dict(ok=True,runs=entries,has_more=len(names)>(page+1)*20,page=page)
    print('WB_MAPPING_JSON='+json.dumps(result,separators=(',',':')))
elif operation=='describe':
    print('WB_MAPPING_JSON='+json.dumps(dict(ok=True,**item(request['run'])),separators=(',',':')))
elif operation=='stream':
    row=item(request['run'])
    entry=next((f for f in row['files'] if f['name']==request['name']),None)
    if entry is None or entry['signature']!=request['signature']:raise ValueError('file unavailable or changed')
    path=safe(safe(root,request['run'])/'mapping',request['name'])
    with path.open('rb') as handle:
        before=os.fstat(handle.fileno())
        if signature(before)!=entry['signature']:raise ValueError('file changed before open')
        sys.stdout.buffer.write(b'WB_MAPPING_FILE '+json.dumps(entry,separators=(',',':')).encode()+b'\n')
        digest=hashlib.sha256()
        remaining=before.st_size
        while remaining:
            data=handle.read(min(remaining,1024*1024))
            if not data:raise ValueError('source truncated')
            remaining-=len(data)
            digest.update(data);sys.stdout.buffer.write(data)
        if signature(os.fstat(handle.fileno()))!=entry['signature'] or signature(path.stat())!=entry['signature']:
            raise ValueError('file changed during transfer')
        sys.stdout.buffer.write(b'\nWB_MAPPING_END '+digest.hexdigest().encode()+b'\n')
else:raise ValueError('unknown mapping operation')
'''


def relative(value):
    if not isinstance(value,str) or not value or len(value)>512 or '\\' in value:
        raise ValueError('非法建图路径')
    if any(not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}',part) for part in value.split('/')):
        raise ValueError('非法建图路径')
    return value


def local_path(root, value):
    path=root
    for part in relative(value).split('/'):
        path=path/part
        if path.is_symlink():raise ValueError('本地建图目录不允许符号链接')
    path.resolve().relative_to(root.resolve())
    return path


class Remote:
    def __init__(self, board):
        self.target=copy.copy(board.target)
        self.root=str(board.root)
        self.python=board.config['connection'].get('board_python','/usr/bin/python3')
        self.source_id=hashlib.sha256(json.dumps([self.target.host,self.target.port,self.root]).encode()).hexdigest()[:16]

    def command(self, operation, **values):
        source='import base64;exec(compile(base64.b64decode(%r),"mapping-read-only","exec"))'%base64.b64encode(REMOTE.encode()).decode()
        request=dict(root=self.root,operation=operation,**values)
        return '%s -c %s %s'%(quote(self.python),quote(source),quote(json.dumps(request,separators=(',',':'))))

    def request(self, operation, **values):
        code,data=run_bytes(self.target,self.command(operation,**values),timeout=30)
        if code:raise ValueError('板端建图查询失败：'+data[-600:].decode('utf-8','replace'))
        prefix=b'WB_MAPPING_JSON='
        rows=[line[len(prefix):] for line in data.splitlines() if line.startswith(prefix)]
        if len(rows)!=1:raise ValueError('板端未返回有效建图清单')
        result=json.loads(rows[0])
        if not result.get('ok'):raise ValueError('板端建图查询失败')
        return result

    def download(self, run, entry, stream):
        code,error=run_bytes(self.target,self.command('stream',run=run,name=entry['name'],signature=entry['signature']),
                            timeout=3600,sink=stream)
        if code:raise ValueError('建图下载失败：'+error[-500:].decode('utf-8','replace'))
        stream.finish()


class FileSink:
    """Checks framed SSH bytes and hashes without retaining the file in memory."""
    def __init__(self, handle, entry, progress=lambda size:None):
        self.handle,self.entry,self.progress=handle,entry,progress
        self.header=False;self.buffer=b'';self.count=0;self.digest=hashlib.sha256()

    def write(self, chunk):
        if not self.header:
            self.buffer+=chunk
            if b'\n' not in self.buffer:
                if len(self.buffer)>16384:raise ValueError('下载头过大')
                return
            header,chunk=self.buffer.split(b'\n',1);self.buffer=b''
            if len(header)>16384:raise ValueError('下载头过大')
            if not header.startswith(b'WB_MAPPING_FILE '):raise ValueError('非法下载数据头')
            actual=json.loads(header[len(b'WB_MAPPING_FILE '):])
            if actual!=self.entry:raise ValueError('下载文件标识不匹配')
            self.header=True
        remaining=self.entry['size']-self.count
        data=chunk[:remaining]
        if data:
            self.handle.write(data);self.digest.update(data);self.count+=len(data);self.progress(len(data))
        self.buffer+=chunk[len(data):]
        if len(self.buffer)>200:raise ValueError('下载尾部数据超限')

    def finish(self):
        expected=b'\nWB_MAPPING_END '+self.digest.hexdigest().encode()+b'\n'
        if not self.header or self.count!=self.entry['size'] or self.buffer!=expected:
            raise ValueError('建图文件长度/校验不匹配，不发布不完整文件')


def cloud_points(msg):
    data=memoryview(msg.data).cast('B')
    width,height,point_step,row_step=int(msg.width),int(msg.height),int(msg.point_step),int(msg.row_step)
    if min(width,height,point_step,row_step)<0 or point_step<=0 or row_step<width*point_step or len(data)<height*row_step:
        raise ValueError('invalid PointCloud2 dimensions')
    fields={f.name:f for f in msg.fields}
    selected=[]
    for name in ('x','y','z'):
        f=fields.get(name)
        if f is None or f.datatype not in (7,8) or f.count<1:raise ValueError('PCD requires float XYZ fields')
        code,size=('f',4) if f.datatype==7 else ('d',8)
        if f.offset<0 or f.offset+size>point_step:raise ValueError('PointCloud2 field outside point_step')
        selected.append((int(f.offset),struct.Struct(('>' if msg.is_bigendian else '<')+code)))
    for row in range(height):
        for column in range(width):
            offset=row*row_step+column*point_step
            values=tuple(fmt.unpack_from(data,offset+field_offset)[0] for field_offset,fmt in selected)
            if all(math.isfinite(v) and abs(v)<=3.4028234e38 for v in values):yield values


def export_pcd(paths, output, topics):
    from rosbags.highlevel import AnyReader
    latest=None;latest_time=-1;latest_topic=None
    for path in paths:
        with AnyReader([path]) as bag:
            connections=[c for c in bag.connections if c.topic in topics and c.msgtype=='sensor_msgs/msg/PointCloud2']
            for connection,stamp,raw in bag.messages(connections=connections) if connections else []:
                msg=bag.deserialize(raw,connection.msgtype)
                if msg.width and msg.height and stamp>=latest_time:
                    latest,latest_time,latest_topic=msg,stamp,connection.topic
    if latest is None:raise ValueError('没有有效非空FreeDOM静态地图，未生成PCD')
    body=output.with_suffix('.points.part');count=0
    try:
        with body.open('wb') as stream:
            for point in cloud_points(latest):stream.write(struct.pack('<fff',*point));count+=1
        if not count:raise ValueError('静态地图没有有限XYZ点')
        header=('# .PCD v0.7\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH %d\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS %d\nDATA binary\n'%(count,count)).encode()
        temporary=output.with_name(output.name+'.part')
        with temporary.open('wb') as stream,body.open('rb') as source:
            stream.write(header);shutil.copyfileobj(source,stream,1024*1024)
        info=dict(topic=latest_topic,frame_id=latest.header.frame_id,bag_time_ns=latest_time,
                  points=count,meaning='last received nonempty static map; not an internal FreeDOM state archive')
        info_path=output.parent/'final_map.json'
        info_tmp=info_path.with_suffix('.json.part')
        info_tmp.write_text(json.dumps(info,ensure_ascii=False,indent=2))
        os.replace(str(info_tmp),str(info_path))
        os.replace(str(temporary),str(output))
        return info
    finally:
        body.unlink(missing_ok=True)


class MappingLibrary:
    def __init__(self, profile_dir):
        self.root=Path(profile_dir)/'mapping_downloads'
        if self.root.is_symlink():raise ValueError('建图缓存根目录不允许符号链接')
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.tasks={}
        for path in sorted(self.root.glob('*/task.json'),reverse=True)[:50]:
            if path.parent.is_symlink() or path.is_symlink():continue
            try:
                task=json.loads(path.read_text())
                if not re.fullmatch(r'[0-9a-f]{32}',task['id']):continue
                if task['state'] in ('downloading','exporting','packaging'):task.update(state='interrupted',error='工作台重启，请重新准备下载')
                self.tasks[task['id']]=task
            except (OSError,ValueError,KeyError):pass

    def jobs(self):
        with self.lock:return dict(ok=True,jobs=copy.deepcopy(list(self.tasks.values())[-50:]))

    def update(self, task, **values):
        with self.lock:
            task.update(values,updated_at=time.time())
            destination=local_path(self.root,task['id'])/'task.json'
            temporary=destination.with_suffix('.tmp')
            temporary.write_text(json.dumps(task,ensure_ascii=False,indent=2))
            os.replace(str(temporary),str(destination))

    def catalog(self, board, page=0):
        if type(page) is not int or page<0:raise ValueError('页码必须为非负整数')
        remote=Remote(board)
        return dict(remote.request('catalog',page=page),source_id=remote.source_id,host=remote.target.host,board_root=remote.root)

    def prepare(self, board, body):
        run=relative(body.get('run'))
        if '/' in run:raise ValueError('非法飞行目录')
        name=relative(body['file']) if body.get('file') else None
        remote=Remote(board)
        if body.get('source_id')!=remote.source_id:raise ValueError('设备或日志根目录已改变，请刷新建图记录后重试')
        with self.lock:
            for task in self.tasks.values():
                if task['state'] in ('downloading','exporting','packaging'):
                    if (task['source_id'],task['run'],task.get('file'))==(remote.source_id,run,name):return dict(ok=True,id=task['id'])
                    raise ValueError('请等待当前建图下载/导出任务完成')
            identifier=uuid.uuid4().hex
            folder=local_path(self.root,identifier);folder.mkdir()
            task=dict(id=identifier,run=run,file=name,source_id=remote.source_id,host=remote.target.host,
                      board_root=remote.root,state='downloading',transferred=0,total=0,created_at=time.time(),artifacts=[],warnings=[])
            self.tasks[identifier]=task;self.update(task)
            threading.Thread(target=self.worker,args=(task,remote),daemon=True,name='mapping-download').start()
            return dict(ok=True,id=identifier)

    def worker(self, task, remote):
        folder=local_path(self.root,task['id'])
        try:
            row=remote.request('describe',run=task['run'])
            if not task['file'] and row['active']:raise ValueError('整轮下载请等待记录收尾；录制中可单独下载已封闭分卷')
            selected=[f for f in row['files'] if not task['file'] or f['name']==task['file']]
            if not selected:raise ValueError('没有可下载的已封闭文件')
            total=sum(f['size'] for f in selected)
            if any(type(f['size']) is not int or not 0<=f['size']<=MAX_FILE for f in selected):raise ValueError('文件大小超限')
            required=total*(1 if task['file'] else 2)+1024**3
            if shutil.disk_usage(folder).free<required:raise ValueError('PC缓存空间不足，未开始下载')
            self.update(task,total=total)
            downloaded=[]
            for entry in selected:
                dest=local_path(folder,entry['name']);dest.parent.mkdir(parents=True,exist_ok=True)
                temporary=dest.with_name(dest.name+'.part')
                def progress(count):
                    # In-memory progress is cheap; task.json is updated per file.
                    with self.lock:task['transferred']+=count
                with temporary.open('wb') as stream:
                    remote.download(task['run'],entry,FileSink(stream,entry,progress))
                os.replace(str(temporary),str(dest));downloaded.append(dest)
                self.update(task)
            if task['file']:
                self.update(task,state='ready',artifacts=[task['file']]);return
            self.update(task,state='exporting')
            warnings=[]
            try:
                export_pcd([p for p in downloaded if p.suffix=='.bag'],folder/'final_map.pcd',['/freedom/static_pointcloud'])
                downloaded.extend([folder/'final_map.pcd',folder/'final_map.json'])
            except Exception as exc:warnings.append('PCD未生成：'+str(exc))
            (folder/'download_report.json').write_text(json.dumps(dict(source_manifest=row['manifest'],source=dict(host=remote.target.host,board_root=remote.root),warnings=warnings,
                completed_files=[p.relative_to(folder).as_posix() for p in downloaded]),ensure_ascii=False,indent=2))
            downloaded.append(folder/'download_report.json')
            self.update(task,state='packaging',warnings=warnings)
            archive=folder/('mapping_'+task['run']+'.zip')
            temporary=archive.with_suffix('.zip.part')
            with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as zipped:
                for path in downloaded:zipped.write(path,path.relative_to(folder).as_posix())
            os.replace(str(temporary),str(archive))
            artifacts=[archive.name]+(['final_map.pcd','final_map.json'] if not warnings else [])
            self.update(task,state='ready',artifacts=artifacts)
        except Exception as exc:self.update(task,state='failed',error=str(exc))

    def artifact(self, identifier, name):
        if not isinstance(identifier,str) or not re.fullmatch(r'[0-9a-f]{32}',identifier):raise ValueError('非法下载任务')
        with self.lock:
            task=self.tasks.get(identifier)
            if not task or task['state']!='ready' or name not in task['artifacts']:raise ValueError('文件尚未准备完成')
        path=local_path(local_path(self.root,identifier),name)
        if not path.is_file():raise ValueError('下载文件不存在')
        return path
