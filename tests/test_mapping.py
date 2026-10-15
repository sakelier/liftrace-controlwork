"""Local file/wire fixtures only; no SSH connection, ROS nodes or compilation."""
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import wb_mapping as mapping
from wb_ssh import Target,run_bytes
import wb_native_ssh


def wire(entry,data):
    return b'WB_MAPPING_FILE '+json.dumps(entry,separators=(',',':')).encode()+b'\n'+data+b'\nWB_MAPPING_END '+hashlib.sha256(data).hexdigest().encode()+b'\n'

class FramingTests(unittest.TestCase):
    def test_every_two_chunk_boundary_and_byte_at_a_time(self):
        data=b'\x00\xff\nWB_MAPPING_END fake\n'*4
        entry=dict(name='freedom_00001.bag',size=len(data),signature=[1,2,len(data),4],closed=True)
        frame=wire(entry,data)
        for cut in range(len(frame)+1):
            output=io.BytesIO();sink=mapping.FileSink(output,entry)
            sink.write(frame[:cut]);sink.write(frame[cut:]);sink.finish();self.assertEqual(output.getvalue(),data)
        sink=mapping.FileSink(io.BytesIO(),entry)
        for byte in frame:sink.write(bytes([byte]))
        sink.finish()
    def test_corruption_truncation_wrong_identity_and_extra_bytes_rejected(self):
        entry=dict(name='test.bag',size=3,signature=[1,2,3,4],closed=True)
        good=wire(entry,b'abc')
        for data in [good[:-1],good.replace(b'abc',b'abx'),good+b'x',good.replace(b'test.bag',b'evil.bag')]:
            with self.subTest(data=data[-15:]),self.assertRaises((ValueError,json.JSONDecodeError)):
                sink=mapping.FileSink(io.BytesIO(),entry);sink.write(data);sink.finish()
    def test_payload_is_incremental_and_tail_bounded(self):
        entry=dict(name='large.bag',size=4*1024**2,signature=[],closed=True)
        class Counter:
            count=0
            def write(self,value):self.count+=len(value)
        output=Counter();sink=mapping.FileSink(output,entry);sink.write(b'WB_MAPPING_FILE '+json.dumps(entry).encode()+b'\n')
        for _ in range(64):sink.write(b'X'*65536);self.assertLessEqual(len(sink.buffer),200)
        sink.write(b'\nWB_MAPPING_END '+sink.digest.hexdigest().encode()+b'\n');sink.finish()
        self.assertEqual(output.count,entry['size'])
    def test_posix_transport_streams_sink_without_returning_file_bytes(self):
        class Counter:
            count=0
            def write(self,value):self.count+=len(value)
        sink=Counter()
        code,result=run_bytes(Target(transport='local'),"python3 -c 'import sys;sys.stdout.buffer.write(bytes(3000000))'",sink=sink)
        self.assertEqual((code,result,sink.count),(0,b'',3000000))
    def test_posix_sink_failure_returns_failure(self):
        sink=SimpleNamespace(write=lambda data:(_ for _ in ()).throw(OSError('disk full')))
        code,_=run_bytes(Target(transport='local'),"python3 -c 'print(123)'",sink=sink)
        self.assertNotEqual(code,0)
    def test_native_adapter_drains_into_sink(self):
        class Channel:
            closed=False
            chunks=[b'ab',b'cd']
            def exec_command(self,command):pass
            def recv_ready(self):return bool(self.chunks)
            def recv(self,count):return self.chunks.pop(0)
            def recv_stderr_ready(self):return False
            def exit_status_ready(self):return not self.chunks
            def recv_exit_status(self):return 0
            def close(self):self.closed=True
        channel=Channel();client=SimpleNamespace(get_transport=lambda:SimpleNamespace(open_session=lambda **kw:channel),close=lambda:None)
        sink=io.BytesIO()
        with patch('wb_native_ssh.connect',return_value=client):
            result=wb_native_ssh.run_bytes(Target(), 'read fixture',10,sink=sink)
        self.assertEqual(result,(0,b''));self.assertEqual(sink.getvalue(),b'abcd');self.assertTrue(channel.closed)

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'board';(self.root/'logs').mkdir(parents=True)
        self.board=SimpleNamespace(root=str(self.root),target=Target(transport='local',host='fixture@board'),config={'connection':{'board_python':sys.executable}})
        self.remote=mapping.Remote(self.board)
    def tearDown(self):self.tmp.cleanup()
    def make_run(self,name='board_20261015',active=False):
        folder=self.root/'logs'/name/'mapping';folder.mkdir(parents=True)
        (folder/'freedom_00001.bag').write_bytes(b'bag fixture')
        self.manifest=dict(version=1,started_at=time.time()-100,status='recording' if active else 'complete',active=active,
            total_bytes=11,files=[dict(name='freedom_00001.bag',size=11,closed=True)])
        (folder/'manifest.json').write_text(json.dumps(self.manifest))
        (folder/'metadata.json').write_text('{"run_id":"fixture"}')
        if active:
            identity=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19]
            (folder/'owner.json').write_text(json.dumps(dict(pid=os.getpid(),start=identity)))
        return folder
    def test_catalog_is_independent_of_150_files_and_paged(self):
        for i in range(25):self.make_run('board_%04d'%i)
        unrelated=self.root/'logs'/'unrelated';unrelated.mkdir()
        for i in range(170):(unrelated/('old_%d.log'%i)).touch()
        first=self.remote.request('catalog',page=0);second=self.remote.request('catalog',page=1)
        self.assertEqual(len(first['runs']),20);self.assertEqual(len(second['runs']),5)
        self.assertTrue(first['has_more']);self.assertFalse(second['has_more'])
        self.assertFalse(set(x['run'] for x in first['runs'])&set(x['run'] for x in second['runs']))
    def test_live_only_sealed_files_and_immutable_metadata(self):
        folder=self.make_run(active=True)
        (folder/'pending.bag.active').write_bytes(b'partial')
        (folder/'effective_parameters.json').write_text('{}')
        row=self.remote.request('describe',run=folder.parent.name)
        self.assertTrue(row['active']);self.assertEqual({f['name'] for f in row['files']},{'freedom_00001.bag','metadata.json'})
        (folder/'freedom_00001.bag.active').touch()
        row=self.remote.request('describe',run=folder.parent.name)
        self.assertEqual([f['name'] for f in row['files']],['metadata.json'])
    def test_dead_owner_derived_partial_without_modifying_manifest(self):
        folder=self.make_run(active=True);(folder/'owner.json').write_text('{"pid":99999999,"start":"0"}')
        row=self.remote.request('describe',run=folder.parent.name)
        self.assertFalse(row['active']);self.assertEqual(row['manifest']['status'],'partial')
        self.assertTrue(json.loads((folder/'manifest.json').read_text())['active'])
    def test_download_integrity_and_changed_source_rejected(self):
        folder=self.make_run();entry=self.remote.request('describe',run=folder.parent.name)['files'][0]
        output=io.BytesIO();self.remote.download(folder.parent.name,entry,mapping.FileSink(output,entry))
        self.assertEqual(output.getvalue(),b'bag fixture')
        (folder/entry['name']).write_bytes(b'changed!!!!')
        with self.assertRaises(ValueError):self.remote.download(folder.parent.name,entry,mapping.FileSink(io.BytesIO(),entry))
    def test_traversal_and_symlinks_refused(self):
        folder=self.make_run()
        for name in ['../secret','/etc/passwd','a\\b','a//b']:
            with self.assertRaises(ValueError):self.remote.request('describe',run=name)
        (folder/'freedom_00001.bag').unlink();(folder/'freedom_00001.bag').symlink_to(folder/'metadata.json')
        with self.assertRaises(ValueError):self.remote.request('describe',run=folder.parent.name)
    def prepare(self,library,body):
        with patch('threading.Thread.start'):
            result=library.prepare(self.board,dict(body,source_id=self.remote.source_id))
        task=library.tasks[result['id']]
        with patch('wb_mapping.shutil.disk_usage',return_value=SimpleNamespace(free=10**12)):
            library.worker(task,self.remote)
        return task
    def test_failed_transfer_never_publishes_artifact(self):
        folder=self.make_run();library=mapping.MappingLibrary(self.base/'profile')
        with patch.object(self.remote,'download',side_effect=ValueError('checksum fixture')):
            task=self.prepare(library,dict(run=folder.parent.name,file='freedom_00001.bag'))
        self.assertEqual(task['state'],'failed');self.assertEqual(task['artifacts'],[])
        self.assertFalse((library.root/task['id']/'freedom_00001.bag').exists())
        with self.assertRaises(ValueError):library.artifact(task['id'],'freedom_00001.bag')
    def test_active_full_download_refused_and_single_sealed_allowed(self):
        folder=self.make_run(active=True);library=mapping.MappingLibrary(self.base/'profile')
        task=self.prepare(library,dict(run=folder.parent.name));self.assertEqual(task['state'],'failed')
        task=self.prepare(library,dict(run=folder.parent.name,file='freedom_00001.bag'))
        self.assertEqual(task['state'],'ready');self.assertEqual(library.artifact(task['id'],task['file']).read_bytes(),b'bag fixture')
    def test_restart_marks_inflight_interrupted(self):
        folder=self.make_run();library=mapping.MappingLibrary(self.base/'profile')
        with patch('threading.Thread.start'):library.prepare(self.board,dict(run=folder.parent.name,source_id=self.remote.source_id))
        restored=mapping.MappingLibrary(self.base/'profile');self.assertEqual(restored.jobs()['jobs'][0]['state'],'interrupted')
    def test_same_request_deduplicated_other_request_rejected(self):
        self.make_run();library=mapping.MappingLibrary(self.base/'profile')
        with patch('threading.Thread.start'):
            first=library.prepare(self.board,dict(run='board_20261015',source_id=self.remote.source_id))
            self.assertEqual(first,library.prepare(self.board,dict(run='board_20261015',source_id=self.remote.source_id)))
            with self.assertRaises(ValueError):library.prepare(self.board,dict(run='other_run',source_id=self.remote.source_id))
    def test_changed_board_cannot_download_from_stale_catalog(self):
        self.make_run();library=mapping.MappingLibrary(self.base/'profile')
        catalog=library.catalog(self.board)
        self.assertEqual(catalog['source_id'],self.remote.source_id)
        self.board.target.host='fixture@other-board'
        with self.assertRaises(ValueError):library.prepare(self.board,dict(run='board_20261015',source_id=catalog['source_id']))
        self.assertFalse(library.tasks)

    def test_full_package_survives_pcd_unavailable_with_warning(self):
        folder=self.make_run();library=mapping.MappingLibrary(self.base/'profile')
        task=self.prepare(library,dict(run=folder.parent.name))
        self.assertEqual(task['state'],'ready');self.assertTrue(task['warnings'])
        with zipfile.ZipFile(library.artifact(task['id'],task['artifacts'][0])) as zipped:
            self.assertIn('freedom_00001.bag',zipped.namelist());self.assertIn('download_report.json',zipped.namelist())
        self.assertNotIn('final_map.pcd',task['artifacts'])

class PcdTests(unittest.TestCase):
    @staticmethod
    def cloud(endian=False):
        data=struct.pack(('>' if endian else '<')+'dddddd',1,2,3,float('nan'),0,0)+bytes(8)
        return SimpleNamespace(width=2,height=1,point_step=24,row_step=56,data=data,is_bigendian=endian,
            fields=[SimpleNamespace(name=n,offset=i*8,datatype=8,count=1) for i,n in enumerate('xyz')])
    def test_big_endian_double_row_padding_and_nan(self):
        for endian in (False,True):self.assertEqual(list(mapping.cloud_points(self.cloud(endian))),[(1,2,3)])
        msg=self.cloud();msg.row_step=1
        with self.assertRaises(ValueError):list(mapping.cloud_points(msg))
    def test_real_ros1_bag_exports_last_static_map(self):
        from rosbags.rosbag1 import Writer
        from rosbags.typesys import Stores,get_typestore
        import numpy as np
        ts=get_typestore(Stores.ROS1_NOETIC);types=ts.types
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'fixture.bag'
            msg=types['sensor_msgs/msg/PointCloud2'](types['std_msgs/msg/Header'](1,types['builtin_interfaces/msg/Time'](1,0),'camera_init'),
                1,1,[types['sensor_msgs/msg/PointField'](n,i*4,7,1) for i,n in enumerate('xyz')],False,12,12,
                np.frombuffer(struct.pack('<fff',1,2,3),dtype=np.uint8),True)
            with Writer(path) as bag:
                c=bag.add_connection('/freedom/static_pointcloud',msg.__msgtype__,typestore=ts)
                bag.write(c,100,ts.serialize_ros1(msg,msg.__msgtype__))
                msg.data=np.frombuffer(struct.pack('<fff',4,5,6),dtype=np.uint8)
                bag.write(c,200,ts.serialize_ros1(msg,msg.__msgtype__))
            info=mapping.export_pcd([path],root/'final_map.pcd',['/freedom/static_pointcloud'])
            self.assertEqual(info['bag_time_ns'],200);self.assertEqual(info['frame_id'],'camera_init')
            data=(root/'final_map.pcd').read_bytes();self.assertEqual(struct.unpack('<fff',data.split(b'DATA binary\n')[1]),(4,5,6))
            self.assertFalse(list(root.glob('*.part')))


class HttpTests(unittest.TestCase):
    def handler(self,path,body=None,connected=True):
        from server import Handler
        h=object.__new__(Handler);h.path=path;h.wfile=io.BytesIO()
        h.headers={'Host':'127.0.0.1:8792','Sec-Fetch-Site':'same-origin'}
        h.server=SimpleNamespace(server_address=('127.0.0.1',8792),server_port=8792)
        h.workbench=SimpleNamespace(options={'logs_only':True},connection={'state':'ok' if connected else 'unknown'},
            target=Target(),board='fixture',mapping=SimpleNamespace(jobs=lambda:dict(ok=True,jobs=[]),
            catalog=lambda board,page:dict(ok=True,runs=[],page=page),prepare=lambda board,body:dict(ok=True,id='fixture')))
        h.responses=[];h.response_headers={}
        h.send_response=lambda code:h.responses.append(code)
        h.send_header=lambda name,value:h.response_headers.update({name:value})
        h.end_headers=lambda:None
        payload=json.dumps(body or {}).encode();h.headers['Content-Length']=str(len(payload));h.rfile=io.BytesIO(payload)
        return h
    def test_logs_only_routes_and_disconnected_local_jobs(self):
        for path in ['/api/mapping-recordings/jobs','/api/mapping-recordings/catalog?page=2']:
            h=self.handler(path);h.do_GET();self.assertEqual(h.responses,[200]);self.assertTrue(json.loads(h.wfile.getvalue())['ok'])
        h=self.handler('/api/mapping-recordings/jobs',connected=False);h.do_GET();self.assertEqual(h.responses,[200])
        h=self.handler('/api/mapping-recordings/catalog',connected=False);h.do_GET();self.assertEqual(h.responses,[400])
    def test_prepare_origin_connection_and_body_validation(self):
        h=self.handler('/api/mapping-recordings/prepare',dict(run='board_test'));h.do_POST();self.assertEqual(h.responses,[200])
        h=self.handler('/api/mapping-recordings/prepare',connected=False);h.do_POST();self.assertEqual(h.responses,[400])
        h=self.handler('/api/mapping-recordings/prepare');h.headers['Origin']='https://other.example';h.do_POST();self.assertEqual(h.responses,[400])
    def test_file_stream_is_exact_native_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'mapping_board_test.zip';path.write_bytes(b'ZIP fixture'*100000)
            h=self.handler('/api/mapping-recordings/file?id='+('a'*32)+'&name='+path.name,connected=False)
            h.workbench.mapping.artifact=lambda identifier,name:path
            h.do_GET();self.assertEqual(h.responses,[200]);self.assertEqual(h.wfile.getvalue(),path.read_bytes())
            self.assertEqual(h.response_headers['Content-Length'],str(path.stat().st_size))
            self.assertIn('attachment',h.response_headers['Content-Disposition'])

if __name__=='__main__':unittest.main()
