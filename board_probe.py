#!/usr/bin/env python3
"""板端只读遥测探针（试飞工作台使用）。

边界（重要）：
  * 只订阅话题、读节点/服务列表和系统资源计数器；
  * 不发布任何话题、不调用任何服务、不改飞控模式、不解锁、不碰舵机；
  * 进程名固定为 flight_workbench_probe，不在 run_trial.py 的冲突节点集合里。

每 interval 秒向 stdout 打印一行 JSON，由笔记本侧工作台解析。master 未起来时也保持
存活并周期性报告 {"master": false}，这样工作台可以在 roscore 之前就启动探针。

用法（板端，先 source 现场环境）：
    python3 board_probe.py --interval 1.0 --topics /mavros/state,/camera/image_raw
"""
import argparse
import fcntl
import importlib
import json
import math
import os
from pathlib import Path
import re
import threading
import socket
import sys
import tempfile
import time


OBSERVE_TYPES = {
    'fc_pose': ('geometry_msgs.msg', 'PoseStamped'),
    'lio_pose': ('nav_msgs.msg', 'Odometry'),
    'ev_pose': ('geometry_msgs.msg', 'PoseStamped'),
    'setpoint': ('geometry_msgs.msg', 'PoseStamped'),
    'battery': ('sensor_msgs.msg', 'BatteryState'),
    'rc_out': ('mavros_msgs.msg', 'RCOut'),
    'actuator_target': ('mavros_msgs.msg', 'ActuatorControl'),
    'esc_status': ('mavros_msgs.msg', 'ESCStatus'),
    'esc_telemetry': ('mavros_msgs.msg', 'ESCTelemetry'),
    'low_hover': ('std_msgs.msg', 'String'),
}


def observe_topics(text):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('observe-topics must be a JSON mapping')
    if not isinstance(value, dict) or set(value) - set(OBSERVE_TYPES):
        raise argparse.ArgumentTypeError('unknown observe topic key')
    types = {}
    for key, topic in value.items():
        if not isinstance(topic, str) or not topic.startswith('/') or any(c.isspace() for c in topic):
            raise argparse.ArgumentTypeError('observe topics must be absolute topic names')
        if topic in types and types[topic] != OBSERVE_TYPES[key]:
            raise argparse.ArgumentTypeError('one observe topic cannot have conflicting wire types')
        types[topic] = OBSERVE_TYPES[key]
    return value


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topics", default="")
    parser.add_argument("--services", default="")
    parser.add_argument("--terminal-hover-topic", default="")
    parser.add_argument("--lio-realtime-topic", default="")
    parser.add_argument("--observe-topics", type=observe_topics, default={})
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--nodes-interval", type=float, default=5.0)
    parser.add_argument("--node-name", default="flight_workbench_probe")
    parser.add_argument("--lock-path", default="", help="可配置的探针独占锁文件")
    parser.add_argument("--once", action="store_true", help="打印一行后退出（自检用）")
    return parser.parse_args()


class ResourceSampler(object):
    """Read-only Linux counters; never changes clocks, drivers or permissions."""
    def __init__(self, proc_root='/proc', sys_root='/sys', disk_path=None,
                 monotonic=time.monotonic, statvfs=os.statvfs, stat=os.stat):
        self.proc_root, self.sys_root = Path(proc_root), Path(sys_root)
        self.disk_path = disk_path or os.getcwd()
        self.clock, self.statvfs, self.stat = monotonic, statvfs, stat
        self.previous_cpu, self.previous_net = {}, {}
        self.last_at = None
        self.disk_at, self.disk_cache = None, []

    @staticmethod
    def read(path):
        try:
            return path.read_text().strip()
        except (OSError, UnicodeError):
            return None

    @staticmethod
    def unavailable(reason):
        return dict(status='unavailable', reason=reason)

    @staticmethod
    def percent(text):
        if text is None:
            return None
        # Rockchip devfreq: "42@800000000Hz"; Mali utilisation: "42".
        match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:%|@\d+Hz)?\s*', text)
        value = float(match.group(1)) if match else None
        return value if value is not None and 0 <= value <= 100 else None

    def cpu(self):
        current, usages = {}, {}
        for line in (self.read(self.proc_root/'stat') or '').splitlines():
            parts = line.split()
            if not parts or not re.fullmatch(r'cpu\d*', parts[0]):
                continue
            try:
                values = [int(x) for x in parts[1:9]]  # guest counters already included in user/nice
                if len(values) < 4 or any(x < 0 for x in values):
                    continue
                total, idle = sum(values), values[3] + (values[4] if len(values)>4 else 0)
                current[parts[0]] = (total, idle)
                previous = self.previous_cpu.get(parts[0])
                if previous:
                    delta, idle_delta = total-previous[0], idle-previous[1]
                    if delta > 0 and 0 <= idle_delta <= delta:
                        usages[parts[0]] = round(100*(delta-idle_delta)/delta, 1)
            except ValueError:
                continue
        self.previous_cpu = current
        if 'cpu' not in current:
            return self.unavailable('无法读取/proc/stat')
        return dict(status='ok' if 'cpu' in usages else 'sampling',
                    percent=usages.get('cpu'), cores=[dict(name=name, percent=usages.get(name))
                        for name in sorted(current) if name!='cpu'])

    def memory(self):
        values = {}
        for line in (self.read(self.proc_root/'meminfo') or '').splitlines():
            parts = line.replace(':',' ').split()
            if len(parts)>1:
                try:values[parts[0]]=int(parts[1])*1024
                except ValueError:pass
        total = values.get('MemTotal',0)
        available = values.get('MemAvailable')
        if available is None and total and 'MemFree' in values:
            available = (values.get('MemFree',0)+values.get('Buffers',0)+values.get('Cached',0)
                         +values.get('SReclaimable',0)-values.get('Shmem',0))
        if total <= 0 or available is None or not 0 <= available <= total:
            return self.unavailable('无法读取内存容量')
        used=total-available
        return dict(status='ok', used_bytes=used, total_bytes=total, percent=round(used/total*100,1),
                    swap_used_bytes=max(0,values.get('SwapTotal',0)-values.get('SwapFree',0)),
                    swap_total_bytes=values.get('SwapTotal',0))

    def accelerator(self, kind):
        paths=[]
        if kind=='npu':
            paths.extend([self.sys_root/'kernel/debug/rknpu/load', self.proc_root/'rknpu/load'])
        try:
            paths.extend(sorted((self.sys_root/'class/devfreq').glob('*'+kind+'*/load')))
            if kind=='gpu':
                for name in ('utilisation','utilization','load'):
                    paths.extend(sorted((self.sys_root/'devices/platform').glob('*gpu*/'+name)))
        except OSError:
            pass
        for path in paths:
            text=self.read(path)
            if kind=='npu' and text:
                pairs=re.findall(r'Core(\d+)\s*:\s*(\d*(?:\.\d+)?)\s*%',text)
                cores=[dict(name='Core'+index,percent=float(value or '0')) for index,value in pairs]
                if cores and all(0 <= c['percent'] <= 100 for c in cores):
                    return dict(status='ok',percent=round(sum(c['percent'] for c in cores)/len(cores),1),
                                cores=cores,source=str(path))
                single=re.fullmatch(r'NPU load:\s*(\d*(?:\.\d+)?)\s*%\s*,?',text)
                if single:text=(single.group(1) or '0')+'%'
            value=self.percent(text)
            if value is not None:
                return dict(status='ok',percent=value,cores=[],source=str(path))
        return self.unavailable('驱动未提供可读负载接口，或当前SSH用户无读取权限')

    def disks(self, now):
        if self.disk_at is not None and now-self.disk_at<10:
            return self.disk_cache
        mounts=['/', self.disk_path]
        for line in (self.read(self.proc_root/'mounts') or '').splitlines():
            parts=line.split()
            if len(parts)>=3 and parts[0].startswith('/dev/') and parts[2] not in ('squashfs','tmpfs','devtmpfs'):
                mounts.append(re.sub(r'\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),parts[1]))
        output,seen=[],set()
        for mount in dict.fromkeys(mounts):
            try:
                device=self.stat(mount).st_dev
                if device in seen:continue
                info=self.statvfs(mount)
                size=info.f_frsize or info.f_bsize
                total=info.f_blocks*size;used=(info.f_blocks-info.f_bfree)*size
                if total<=0:continue
                seen.add(device)
                output.append(dict(status='ok',mount=mount,used_bytes=used,total_bytes=total,
                    available_bytes=info.f_bavail*size,percent=round(used/total*100,1)))
            except OSError:
                output.append(dict(status='unavailable',mount=mount,reason='容量不可读'))
            if len(output)>=8:break
        self.disk_at,self.disk_cache=now,output
        return output

    def network(self, elapsed):
        current,output={},[]
        for line in (self.read(self.proc_root/'net/dev') or '').splitlines():
            if ':' not in line:continue
            name,raw=line.split(':',1);name=name.strip()
            if name=='lo' or not re.fullmatch(r'[\w.:-]+',name):continue
            fields=raw.split()
            if len(fields)<16:continue
            try:rx,tx=int(fields[0]),int(fields[8])
            except ValueError:continue
            if min(rx,tx)<0:continue
            base=self.sys_root/'class/net'/name
            if self.read(base/'operstate') not in ('up','unknown'):continue
            previous=self.previous_net.get(name)
            current[name]=(rx,tx)
            rx_rate=tx_rate=None
            if previous is not None and elapsed and elapsed>0 and rx>=previous[0] and tx>=previous[1]:
                rx_rate=(rx-previous[0])/elapsed;tx_rate=(tx-previous[1])/elapsed
            try:speed=int(self.read(base/'speed'))
            except (TypeError,ValueError):speed=None
            output.append(dict(name=name,status='ok' if rx_rate is not None else 'sampling',
                rx_bytes_per_sec=rx_rate,tx_bytes_per_sec=tx_rate,link_mbps=speed if speed and speed>0 else None))
        self.previous_net=current
        return output

    def sample(self):
        now=self.clock();elapsed=None if self.last_at is None else now-self.last_at
        self.last_at=now
        result=dict(sampled_at=round(time.time(),3),interval_s=elapsed)
        for name,call in [('cpu',self.cpu),('gpu',lambda:self.accelerator('gpu')),
                          ('npu',lambda:self.accelerator('npu')),('memory',self.memory),
                          ('disks',lambda:self.disks(now)),('network',lambda:self.network(elapsed))]:
            try:result[name]=call()
            except Exception as exc:
                result[name]=[] if name in ('disks','network') else self.unavailable('采样失败：'+str(exc)[:100])
        return result


class ResourceMonitor(object):
    """Keep potentially slow filesystem/driver reads off the ROS probe loop."""
    def __init__(self, interval=1.0):
        self.sampler=ResourceSampler()
        self.interval=max(.5,float(interval))
        self.lock=threading.Lock();self.value=None;self.sample_at=None
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,name='resource-monitor',daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            started=time.monotonic()
            value=self.sampler.sample()
            with self.lock:self.value=value;self.sample_at=started
            self.stop.wait(max(.05,self.interval-(time.monotonic()-started)))

    def snapshot(self):
        with self.lock:
            if self.value is None:return None
            return dict(self.value,age_seconds=round(time.monotonic()-self.sample_at,3))


class Tracker(object):
    def __init__(self, topics):
        self.stats = {}
        for topic in topics:
            self.stats[topic] = {"count": 0, "window": 0, "last": None, "window_start": time.time()}

    def observe(self, topic):
        now = time.time()
        row = self.stats.setdefault(topic, {"count": 0, "window": 0, "last": None,
                                            "window_start": now})
        row["count"] += 1
        row["window"] += 1
        row["last"] = now

    def snapshot(self):
        now = time.time()
        out = {}
        for topic, row in self.stats.items():
            span = max(now - row["window_start"], 1e-6)
            out[topic] = {
                "count": row["count"],
                "hz": round(row["window"] / span, 2),
                "age": None if row["last"] is None else round(now - row["last"], 3),
            }
            row["window"] = 0
            row["window_start"] = now
        return out


def subscribe(rospy, topics, tracker, payloads, extractors, subscriptions=None):
    """已注册类型的话题解析成 dict/str；其余只统计新鲜度。"""
    subscriptions = {} if subscriptions is None else subscriptions
    for topic in topics:
        if subscriptions.get(topic, {}).get('subscribed'):
            continue  # rospy reconnects when a publisher appears/restarts.
        extractor = extractors.get(topic)

        def make_callback(name, extract):
            last_error = [None]
            def callback(msg):
                tracker.observe(name)
                if extract is None:
                    return
                try:
                    payloads[name] = extract(msg)
                    last_error[0] = None
                except Exception as error:
                    payloads[name] = None
                    reason = "%s: %s" % (type(error).__name__, str(error)[:180])
                    if reason != last_error[0]:
                        sys.stderr.write("PROBE_PARSE_ERROR topic=%s type=%s reason=%s\n" %
                                         (name, type(msg).__name__, reason))
                        sys.stderr.flush()
                        last_error[0] = reason
            return callback

        message_type = getattr(extractor, "msg_type", None) or rospy.AnyMsg
        try:
            handle = rospy.Subscriber(topic, message_type, make_callback(topic, extractor), queue_size=1)
            subscriptions[topic] = dict(handle=handle, subscribed=True, typed=extractor is not None)
        except Exception as error:  # 类型不可用时退回通用订阅
            try:
                handle = rospy.Subscriber(topic, rospy.AnyMsg, make_callback(topic, None), queue_size=1)
                subscriptions[topic] = dict(handle=handle, subscribed=True, typed=False)
            except Exception:
                subscriptions[topic] = dict(subscribed=False, typed=False)
                sys.stderr.write("probe: cannot subscribe %s: %s\n" % (topic, error))
    return subscriptions


def read_payload(value):
    """把订阅到的值整理成可 JSON 序列化的结果（dict / JSON 字符串 / 短文本）。"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return None
    if not text.startswith("{"):
        return text[:2000]
    try:
        return json.loads(text)
    except ValueError:
        return text[:2000]


def state_extractor():
    def extract(msg):
        return {"connected": bool(msg.connected), "armed": bool(msg.armed),
                "mode": str(msg.mode), "guided": bool(getattr(msg, "guided", False)),
                "system_status": int(getattr(msg, "system_status", 0))}
    return extract


def extended_extractor():
    def extract(msg):
        return {"landed_state": int(getattr(msg, "landed_state", 0)),
                "vtol_state": int(getattr(msg, "vtol_state", 0))}
    return extract


def string_extractor():
    def extract(msg):
        return getattr(msg, "data", None)
    return extract


def diagnostic_extractor():
    def extract(msg):
        return [{"name": str(s.name), "level": int(s.level), "message": str(s.message),
                 "values": {str(kv.key): str(kv.value) for kv in s.values}}
                for s in msg.status]
    return extract


def finite_number(value):
    try:
        if isinstance(value, bool) or value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def pose_extractor(clock, odometry=False):
    def extract(msg):
        pose = msg.pose.pose if odometry else msg.pose
        p, q = pose.position, pose.orientation
        xyz = [finite_number(v) for v in (p.x, p.y, p.z)]
        quat = [finite_number(v) for v in (q.x, q.y, q.z, q.w)]
        stamp = finite_number(msg.header.stamp.to_sec())
        now = finite_number(clock())
        if None in xyz + quat or stamp is None or now is None or not math.isfinite(now-stamp):
            return None
        norm = math.hypot(*quat)
        if not math.isfinite(norm) or norm < 1e-12:
            return None
        x, y, z, w = [v / norm for v in quat]
        return dict(frame=str(msg.header.frame_id), stamp=stamp, source_age=now-stamp,
                    x=xyz[0], y=xyz[1], z=xyz[2],
                    roll_deg=math.degrees(math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y))),
                    pitch_deg=math.degrees(math.asin(max(-1., min(1., 2*(w*y-z*x))))),
                    yaw_deg=math.degrees(math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))))
    return extract


def battery_extractor():
    def extract(msg):
        return {key: finite_number(getattr(msg, key, None))
                for key in ('voltage', 'current', 'percentage')}
    return extract


def rc_out_extractor():
    def extract(msg):
        channels = list(msg.channels)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in channels):
            return None
        return {'channels': channels}
    return extract


def actuator_target_extractor():
    def extract(msg):
        return {'group_mix': int(msg.group_mix),
                'controls': [finite_number(v) for v in msg.controls]}
    return extract


def observation_diagnostic(topic, stats, publishers, subscription, value):
    """Publisher registration and actual packet reception are separate facts."""
    nodes = None if publishers is None else list(publishers.get(topic, []))
    age = stats.get('age')
    if not subscription.get('subscribed'):
        status = 'subscription_failed'
    elif not subscription.get('typed'):
        status = 'unsupported_type'
    elif nodes == []:
        status = 'no_publisher'
    elif not stats.get('count'):
        status = 'waiting_message'
    elif age is None or age < 0 or age > 2:
        status = 'stale'
    elif value is None:
        status = 'parse_error'
    else:
        status = 'receiving'
    return dict(topic=topic, status=status, publishers=nodes,
                count=stats.get('count', 0), hz=stats.get('hz', 0), age=age)


def esc_extractor(field):
    def extract(msg):
        entries = []
        for slot, item in enumerate(getattr(msg, field)):
            index = getattr(item, 'index', None)
            entry = {'index': index if isinstance(index, int) and not isinstance(index, bool) else None,
                     'slot': slot}  # Array position only; never a physical motor/channel identity.
            entry.update({key: finite_number(getattr(item, key, None))
                          for key in ('rpm', 'voltage', 'current', 'temperature')})
            entries.append(entry)
        return {'entries': entries}
    return extract


def low_hover_extractor():
    def extract(msg):
        value = json.loads(msg.data)
        return value if isinstance(value, dict) else None
    return extract


def json_safe(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    return value


def reexec_probe(delay):
    """Reset partial rospy initialization without restarting any device node.

    The current executable and argv survive; the probe lock is released by its
    close-on-exec descriptor and reacquired by main(). Ctrl+C interrupts the delay.
    """
    time.sleep(delay)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    args = parse_args()
    lock_path = args.lock_path or os.path.join(
        tempfile.gettempdir(), args.node_name.replace('/', '_') + '.lock')
    try:
        probe_lock = open(lock_path, 'a')
        try:
            fcntl.flock(probe_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            probe_lock.close()
            raise
    except OSError as error:
        sys.stderr.write("PROBE_LOCK_UNAVAILABLE: %s\n" % error)
        return 75  # Existing owner must not be replaced by a duplicate ROS node.
    with probe_lock:
        return run_probe(args)


def run_probe(args):
    topics = [t for t in args.topics.split(",") if t.strip()]
    services = [s for s in args.services.split(",") if s.strip()]
    payloads = {}
    extractors = {}

    import rospy  # noqa: E402  (延迟导入：无 master 时也可打印结构化错误)

    try:
        from mavros_msgs.msg import State, ExtendedState
        extractors["/mavros/state"] = state_extractor()
        extractors["/mavros/state"].msg_type = State
        extractors["/mavros/extended_state"] = extended_extractor()
        extractors["/mavros/extended_state"].msg_type = ExtendedState
    except Exception:
        pass
    try:
        from std_msgs.msg import String
        for topic in ("/navigation/mission_status", "/uav_high_view/probe_status",
                      "/board_trials/auto_land_status", args.terminal_hover_topic):
            if not topic:
                continue
            extractor = string_extractor()
            extractor.msg_type = String
            extractors[topic] = extractor
    except Exception:
        pass

    if args.lio_realtime_topic:
        try:
            from diagnostic_msgs.msg import DiagnosticArray
            extractor = diagnostic_extractor()
            extractor.msg_type = DiagnosticArray
            extractors[args.lio_realtime_topic] = extractor
        except ImportError:
            pass

    observe_registered = set()
    for key, topic in args.observe_topics.items():
        if topic not in topics:
            topics.append(topic)
        try:
            module, name = OBSERVE_TYPES[key]
            msg_type = getattr(importlib.import_module(module), name)
            if key in ('fc_pose', 'lio_pose', 'ev_pose', 'setpoint'):
                extractor = pose_extractor(lambda: rospy.Time.now().to_sec(), key == 'lio_pose')
            elif key == 'battery':
                extractor = battery_extractor()
            elif key == 'rc_out':
                extractor = rc_out_extractor()
            elif key == 'actuator_target':
                extractor = actuator_target_extractor()
            elif key in ('esc_status', 'esc_telemetry'):
                extractor = esc_extractor(key)
            else:
                extractor = low_hover_extractor()
            extractor.msg_type = msg_type
            extractors[topic] = extractor
            observe_registered.add(key)
        except Exception:
            # Count available packets using AnyMsg; do not manufacture typed data.
            pass

    for topic in list(extractors):
        if topic not in topics:
            topics.append(topic)
    for topic in extractors:
        payloads[topic] = None

    resources = ResourceMonitor(args.interval)
    hostname = socket.gethostname()
    tracker = Tracker(topics)
    nodes = []
    node_read = 0.0
    started = False
    subscriptions = {}
    publishers = None

    def emitter(master, extra=None):
        row = {
            "t": round(time.time(), 3),
            "master": bool(master),
            "resources": resources.snapshot(),
            "probe": {"node": "/" + args.node_name, "host": hostname, "pid": os.getpid()},
            "topics": tracker.snapshot(),
            "observe": {key: None for key in args.observe_topics},
            "observe_status": {},
        }
        if master:
            def fresh_payload(topic):
                age = (row["topics"].get(topic) or {}).get("age")
                if age is None or age < 0 or age > 2:
                    return None
                return read_payload(payloads.get(topic))

            row["nodes"] = list(nodes)
            row["services"] = service_types
            row["state"] = fresh_payload("/mavros/state")
            row["extended"] = fresh_payload("/mavros/extended_state")
            row["mission"] = fresh_payload("/navigation/mission_status")
            row["probe_status"] = fresh_payload("/uav_high_view/probe_status")
            row["auto_land"] = fresh_payload("/board_trials/auto_land_status")
            row["terminal_hover"] = fresh_payload(args.terminal_hover_topic)
            row["lio_realtime"] = fresh_payload(args.lio_realtime_topic)
            for key, topic in args.observe_topics.items():
                value = fresh_payload(topic) if key in observe_registered else None
                if key in ('fc_pose', 'lio_pose', 'ev_pose', 'setpoint') and isinstance(value, dict):
                    value = dict(value)
                    try:
                        value['source_age'] = finite_number(rospy.Time.now().to_sec() - value['stamp'])
                    except Exception:
                        value['source_age'] = None
                row['observe'][key] = value
                row['observe_status'][key] = observation_diagnostic(
                    topic, row['topics'].get(topic, {}), publishers,
                    subscriptions.get(topic, {}), value)
        if extra:
            row.update(extra)
        try:
            line = json.dumps(json_safe(row), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            # 板端不允许因为一个不可序列化的字段就停止上报
            line = json.dumps(json_safe(row), ensure_ascii=False, default=str, allow_nan=False)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    service_types = {}
    interval = max(0.2, float(args.interval))
    while not rospy.is_shutdown():
        if not started:
            try:
                # This master read does not initialize rospy. Do not enter
                # init_node's irreversible state while roscore is still absent.
                import rosnode
                rosnode.get_node_names()
            except Exception as error:
                emitter(False, {"error": "waiting for ROS master: %s" % str(error)[:200]})
                if args.once:
                    return 1
                time.sleep(interval)
                continue
            try:
                rospy.init_node(args.node_name, disable_signals=True, disable_rosout=True, log_level=rospy.ERROR)
                subscribe(rospy, topics, tracker, payloads, extractors, subscriptions)
                started = True
            except Exception as error:
                # rospy sets _init_node_args before initializing ROS time. Once
                # an init fails, a same-argument retry may return false success.
                # Re-exec just this probe instead of retrying in poisoned globals.
                delay = max(2.0, interval)
                emitter(False, {"error": "ROS initialization failed: %s" % str(error)[:200],
                                "init_state": "failed" if args.once else "restarting",
                                "restart_delay": None if args.once else delay})
                if args.once:
                    return 1
                try:
                    reexec_probe(delay)
                except OSError as restart_error:
                    emitter(False, {"error": "probe re-exec failed: %s" % str(restart_error)[:200]})
                return 1
        now = time.time()
        if now - node_read >= float(args.nodes_interval):
            node_read = now
            # Only retry failed registrations; healthy subscribers remain registered
            # while MAVROS is offline and reconnect through rospy publisher updates.
            subscribe(rospy, topics, tracker, payloads, extractors, subscriptions)
            try:
                import rosgraph
                publishers = dict(rosgraph.Master('/' + args.node_name).getSystemState()[0])
            except Exception:
                publishers = None
            try:
                import rosnode
                nodes = sorted(rosnode.get_node_names())
            except Exception:
                pass
            try:
                import rosservice
                listed = set(rosservice.get_service_list())
                service_types = {}
                for service in services:
                    if service in listed:
                        try:
                            service_types[service] = rosservice.get_service_type(service)
                        except Exception:
                            service_types[service] = "unknown"
            except Exception:
                pass
        emitter(True)
        if args.once:
            return 0
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Preserve an operator's Ctrl+C intent; only the workbench may reconnect.
        sys.stderr.write("PROBE_STOPPED reason=keyboard_interrupt\n")
        sys.stderr.flush()
        sys.exit(130)
