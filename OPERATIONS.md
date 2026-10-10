# 现场试飞操作手册（2026-10-01）

适用：香橙派 `/home/orangepi/liftrace_board_trials_20260928` 的现场专项入口。不是完整比赛启动说明，也不使用 Desktop 历史副本。本文仅整理既有操作，没有修改程序。

## 到底开几个终端

**从板端所有节点都未启动开始，需要6个常驻终端；建议另开第7个用于监测。** 每个终端可以是独立SSH窗口，也可以是一个tmux会话里的窗口。已经运行的设备节点不重复启动。起飞后不需要另外开终端发送任务开始服务。

| 终端 | 常驻内容 | 意义 |
|---|---|---|
| 1 | roscore | ROS通信主节点 |
| 2 | MAVROS | 与飞控通信 |
| 3 | MID360驱动 | 雷达数据 |
| 4 | 相机 | 下视图像 |
| 5 | 舵机服务 | 提供真实释放接口，不因启动服务就释放 |
| 6 | 专项flight入口 | 定位、地图、视觉、规划、任务、控制及bag |
| 7（建议） | 状态监测 | READY、飞控模式、任务进度 |

飞机应已回到起飞点、未解锁、机头朝场内+X；有投递的组别重新装好对应槽位。不要同时运行旧整机launch与本入口。

## 每个终端的公共准备

电脑通过当前IP登录；最后使用的地址如下，换网络后以实际地址为准：

```bash
ssh orangepi@192.168.43.59
cd /home/orangepi/liftrace_board_trials_20260928
source deployment/site_20260928/environment.sh
```

以下命令均在香橙派执行。每个新终端都先执行cd和source。环境脚本使用板内127.0.0.1通信，不将Wi-Fi地址写入ROS节点通信。

## 按顺序启动

终端1：

```bash
roscore
```

终端2：

```bash
roslaunch mavros px4.launch
```

终端3：

```bash
roslaunch uav_mission mid360_driver2.launch \
  user_config_path:="$PWD/deployment/site_20260928/MID360_config.json"
```

雷达专网是板端192.168.1.100、雷达192.168.1.175，不要替换为Wi-Fi网段。

终端4：

```bash
bash deployment/board_trials_4x4/start_camera.sh 
```

终端5（实际投递组需要）：

sudo bash patrol_uav_ws-patrol_planner/src/actuator_pwm/init_pwm.sh
roslaunch actuator_pwm launch_all.launch


```bash
/home/orangepi/liftrace_r64_onboard_405bda42/patrol_uav_ws-patrol_planner/devel/lib/actuator_pwm/pwm_node1 \
  /Servo:=/legacy/Servo_raw
```

这是现场已经使用的舵机可执行文件。地面手动试舵机不属于普通起飞步骤，本文不安排自动释放测试。

终端6，以第五组为例：

```bash
bash deployment/site_20260928/start_test.sh 5 flight
```

**等待明确的READY后，人工解锁。** 现场配置随后自动请求OFFBOARD、起飞到低空稳定高度、启动任务。它不会自动解锁。无需再手动调用`/navigation/start_mission`。旧README前半部分关于手动服务的描述属于早期操作，不适用于当前现场自动时序。

`INITIALIZING`、`MAPPING_READY`都不等于最终READY。若显示`fc_lio_disagreement`，需等飞控和LIO坐标一致且稳定，不应通过转动机身追逐数值或绕过检查。

终端7，可依次检查；用Ctrl+C结束当前echo再执行下一条：

```bash
rostopic echo /mavros/state
rostopic echo /navigation/mission_status
rostopic echo /uav_high_view/probe_status
rosservice type /legacy/Servo_raw
```

最后一条应为`patrol_control/Servo`。查看第6终端日志能直接看到READY与任务状态。

## 现场组号（不是原八组目录编号）

| 参数 | 内容 | 现场flight释放方式 |
|---|---|---|
| 1 | 低空直飞、视觉中断、单投 | 真实舵机 |
| 2 | 低空连续多投，默认两投 | 真实舵机 |
| 3 | 高位整圈，只记忆 | 不投递 |
| 4 | 高位整圈，记忆后逐个重访 | 真实舵机 |
| 5 | 高位满足支持条件提前中断，低空重访 | 真实舵机 |
| 6 | 高速拍摄专项 | 不投递；另核对该专项速度档 |

例如第三组为`start_test.sh 3 flight`。需要preview时使用`start_test.sh 5 preview`，它不接通飞行控制出口；结束preview后再启动flight，不能两者同时运行。

## 当前现场行为与结束步骤

- 场地范围前方6m、左右±1.5m；高位航线内收到前5.5m、左右±1.1m。
- 高位2m、低位1.4m，均为飞控中心AGL；正常巡航0.5m/s。投递高度独立配置。
- 正常完成后在结束位置下降至飞控中心离地30cm悬停，由飞手落地；不是自动返回起飞点，也不是完整比赛H降落。
- 障碍柱关闭，三维避障保留；虚拟顶棚关闭，静态TF，水平膨胀0.25m。
- 默认录压缩相机、视觉、位姿、任务和轨迹bag，不录独立MP4；累计地图点云默认不录。需要地图诊断时应显式启用`record_map_clouds`，不能拿轻量包解释缺失的地图。
- 飞手改模式后程序不自动抢回。出现异常由飞手接管，不在空中重启应用。
- 落地停机后等待`BAG_CLOSED`及应用退出，再断电。bag位于`logs/board_<专项>_<时间>/`；原包留板端可用U盘拷贝。
- 下一轮放回起飞点并静置，重新运行第6终端入口；设备1～5仍正常时不必重启。换电后需重新检查设备进程，不重复叠加。

## tmux方式

可以只保留一个SSH窗口，在tmux内建立以上6～7个窗口：

```bash
tmux new -s flight
# Ctrl+b 后按 c：新建窗口；Ctrl+b 后按数字：切换窗口
# Ctrl+b 后按 d：脱离会话，进程保留
# 重新登录后恢复：
tmux attach -t flight
```

每个窗口分别执行上面的准备与启动命令。tmux保留远程终端，不替代飞控失联处理或现场接管。

建议未来封装“设备启动”和“trial 5”两个入口：检查单实例、分窗口、等待READY、保留日志、统一退出。**目前没有交付新的tmux一键编排脚本**，不要把上述方案理解为现有功能。