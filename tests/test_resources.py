"""Linux resource counter fixtures; no SSH, ROS, drivers or native compilation."""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from board_probe import ResourceSampler
from wb_status import parse_probe_line


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.proc=self.root/'proc';self.sys=self.root/'sys'
        self.now=1.0
        self.sampler=ResourceSampler(str(self.proc),str(self.sys),'/project',monotonic=lambda:self.now,
            stat=lambda p:types.SimpleNamespace(st_dev=1 if p in ('/','/project') else 2),
            statvfs=lambda p:types.SimpleNamespace(f_frsize=1024,f_bsize=1024,f_blocks=1000,f_bfree=400,f_bavail=350))
        self.put(self.proc/'stat','cpu 100 0 50 850 0 0 0 0 10 0\ncpu0 100 0 50 850 0 0 0 0\n')
        self.put(self.proc/'meminfo','MemTotal: 16000000 kB\nMemAvailable: 12000000 kB\nSwapTotal: 1000 kB\nSwapFree: 500 kB\n')
        self.put(self.proc/'mounts','/dev/mmcblk0p2 / ext4 rw 0 0\n/dev/nvme0n1 /data ext4 rw 0 0\n/dev/loop1 /snap/example squashfs ro 0 0\n')
        self.put(self.sys/'class/net/eth0/operstate','up');self.put(self.sys/'class/net/eth0/speed','1000')
        self.network(1000,2000)

    def put(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)

    def network(self,rx,tx):
        fields=[rx,0,0,0,0,0,0,0,tx,0,0,0,0,0,0,0]
        self.put(self.proc/'net/dev','eth0: '+' '.join(map(str,fields))+'\nlo: '+' '.join(map(str,fields))+'\n')

    def test_cpu_delta_excludes_double_counted_guest_and_network_rates(self):
        first=self.sampler.sample()
        self.assertIsNone(first['cpu']['percent']);self.assertIsNone(first['network'][0]['rx_bytes_per_sec'])
        self.now=3
        self.put(self.proc/'stat','cpu 150 0 70 880 0 0 0 0 60 0\ncpu0 150 0 70 880 0 0 0 0\n')
        self.network(3000,10000)
        result=self.sampler.sample()
        self.assertEqual(result['cpu']['percent'],70.0)
        self.assertEqual(result['network'][0]['rx_bytes_per_sec'],1000)
        self.assertEqual(result['network'][0]['tx_bytes_per_sec'],4000)
        self.assertEqual(result['network'][0]['link_mbps'],1000)
        self.assertEqual(len(result['network']),1)
        json.dumps(result,allow_nan=False)

    def test_memory_and_physical_disks(self):
        result=self.sampler.sample()
        self.assertEqual(result['memory']['used_bytes'],4000000*1024)
        self.assertEqual(result['memory']['percent'],25)
        self.assertEqual([x['mount'] for x in result['disks']],['/','/data'])
        self.assertEqual(result['disks'][0]['percent'],60)
        self.assertEqual(result['disks'][0]['available_bytes'],350*1024)

    def test_rockchip_gpu_and_multicore_npu(self):
        self.put(self.sys/'class/devfreq/fb000000.gpu/load','42@800000000Hz')
        self.put(self.sys/'kernel/debug/rknpu/load','NPU load: Core0: 0%, Core1: 60%, Core2: 90%,')
        result=self.sampler.sample()
        self.assertEqual(result['gpu']['percent'],42)
        self.assertEqual(result['npu']['percent'],50)
        self.assertEqual([x['percent'] for x in result['npu']['cores']],[0,60,90])

    def test_single_npu_proc_fallback_and_zero_load(self):
        self.put(self.proc/'rknpu/load','NPU load: 0%')
        self.assertEqual(self.sampler.accelerator('npu')['percent'],0)
        self.put(self.proc/'rknpu/load','NPU load: 100%')
        self.assertEqual(self.sampler.accelerator('npu')['percent'],100)

    def test_driver_blank_precision_zero_is_supported(self):
        self.put(self.sys/'kernel/debug/rknpu/load','NPU load: Core0:  %, Core1:  %, Core2:  %,')
        result=self.sampler.accelerator('npu')
        self.assertEqual(result['percent'],0)
        self.assertEqual(len(result['cores']),3)

    def test_missing_available_memory_does_not_fabricate_full_usage(self):
        self.put(self.proc/'meminfo','MemTotal: 16000000 kB')
        self.assertEqual(self.sampler.memory()['status'],'unavailable')
        self.put(self.proc/'meminfo','MemTotal: 1000 kB\nMemFree: 200 kB\nCached: 300 kB\n')
        self.assertEqual(self.sampler.memory()['percent'],50)

    def test_invalid_and_unreadable_accelerators_are_not_zero(self):
        for text in ['999','800000000Hz','nonsense','-1%']:
            self.put(self.sys/'class/devfreq/fb000000.gpu/load',text)
            self.assertEqual(self.sampler.accelerator('gpu')['status'],'unavailable')
        self.assertEqual(self.sampler.accelerator('npu')['status'],'unavailable')

    def test_counter_reset_and_interface_disappearance_do_not_make_negative_rates(self):
        self.sampler.sample();self.now=2;self.network(1,1)
        result=self.sampler.sample();self.assertIsNone(result['network'][0]['rx_bytes_per_sec'])
        self.put(self.sys/'class/net/eth0/operstate','down');self.now=3
        self.assertEqual(self.sampler.sample()['network'],[])

    def test_no_proc_files_has_explicit_missing_metrics(self):
        empty=ResourceSampler(str(self.root/'missing'),str(self.root/'missing'),stat=lambda p:(_ for _ in ()).throw(OSError()))
        result=empty.sample()
        for key in ['cpu','memory','gpu','npu']:self.assertEqual(result[key]['status'],'unavailable')

    def test_resources_survive_master_false_and_bad_shapes_are_rejected(self):
        row=parse_probe_line(json.dumps(dict(master=False,resources=self.sampler.sample())))
        self.assertIn('memory',row['resources'])
        self.assertIsNone(parse_probe_line('{"master":false,"resources":[]}'))


if __name__=='__main__':unittest.main()
