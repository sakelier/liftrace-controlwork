# FreeDOM 飞行建图记录（2026-10-15）

日志页 `/logs` 的“FreeDOM 飞行建图记录”区提供轮次状态、分卷取回和整轮下载。板端与工作台需配套升级；历史普通 bag 不会被补标为完整建图记录。

## 自动记录

已接入专项 `run_trial.py`、正式入口共用的 `hardware_session.py` 和低空观察 `flight.py`。只有 flight 入口启动新记录，preview / 配置检查不启动。每轮目录为板端 `logs/<本轮目录>/mapping/`，有独立 UUID、进程身份和清单。低空观察没有地图消息时标记“不适用”；若确实收到外部地图，仍检查建图证据是否完整。

新记录进程仅订阅话题、读取参数和写文件，不调用飞行或地图控制服务，不改变控制参数、解锁、模式切换或飞行时序。模块导入、启动、空间不足、超限、写入、收尾异常均打印 `MAPPING_RECORDING_WARNING`，只停止或标记新记录；既有飞行入口检查保持原有行为。

完整档不做点云降频：

- 输入采用 `/freedom/pointcloud_topic` 的实际值，默认 `/cloud_registered_body`；发现变化后补充订阅，并保守标记可能存在覆盖缺口。
- 输出订阅 `/freedom/static_pointcloud`、`/sdf_map/occupancy`、`/sdf_map/occupancy_inflate`。
- 上下文订阅 `/tf`、`/tf_static`、`/Odometry`、`/laserMapping/realtime`、MAVROS 的 vision/local pose、local odom、state，以及 `/board_trials/run_metadata`。
- 保存原始 ROS 序列化消息和连接头，保留消息内时间戳；bag 的记录时间为本机收到消息时的 ROS 时间。
- 保留启动配置、已生成 runtime/control/overrides/profile 等配置、run_metadata、实际 ROS 参数、源码 HEAD 与记录模块版本指纹。

参数快照范围为 `/freedom`、`/laserMapping`、`/common`、`/preprocess`、`/mapping`、`/publish`、`/lio_external_pose`，每秒更新。动态配置最终以 `configs/` 和 `effective_parameters.json` 为准。这里的输入是 FreeDOM 消费的注册点云，适合复核地图输入和结果。

## 容量与异常策略

板端需要现有 ROS1 Noetic Python 环境，以及 rosbag、roslib、roslz4；工作台复用已有 rosbags 依赖。默认每轮 LZ4 bag 分卷约 512 MiB、应用队列 64 MiB、单消息上限 32 MiB，最低剩余磁盘 2 GiB，每轮累计约 8 GiB 后只停新记录。空间与总量每秒检查，可能有一个采样周期和写入块的余量；不会自动删除历史数据。

可在对应板端 settings / 观察 profiles YAML 的顶层调整以下字节数。错误配置只使新记录失败并告警：

```yaml
mapping_recording:
  input_topic: /cloud_registered_body
  buffer_bytes: 67108864
  max_message_bytes: 33554432
  split_bytes: 536870912
  min_free_bytes: 2147483648
  max_total_bytes: 8589934592
```

独立低优先级进程写入，非阻塞占用 `logs/.freedom_mapping_recording.lock` 防止重复完整档。订阅接收队列和应用队列有界，过载会丢弃并统计；点云 Header.seq 的可见跳号另记为缺口。原频订阅不等于在任意负载下保证零丢包，Orange Pi 5 Plus 的实际负载和带宽需现场验收。

bag 写入 `.bag.active`，成功封闭索引后才改名 `.bag` 并列入下载清单。退出会排空队列和封闭分卷；监督器最多等候约 30 秒，未结束的写入进程继续持锁收尾，不强杀。监督器消失由子进程检查 PID/启动时间后收尾；断电、SIGKILL 的活动文件保留未封闭状态。清单检测到原进程已不存在，会在查询结果中标记不完整，不把活动文件当作封闭 bag。

`complete` 只表示记录自身的消息覆盖/落盘检查通过；缺少输入、TF 静态变换或静态地图、序列缺口、丢弃、写入或封闭失败会标记 `partial` / `failed`。不据此判断飞行、定位或地图精度合格。

## 下载与 PCD

1. 在工作台连接设备，进入“日志录制与下载”，查看建图轮次与说明；每页 20 轮，独立于旧日志的 150 文件列表。
2. 录制中可以“准备此文件”取回已经封闭的分卷；结束收尾后可以“准备整轮下载”。
3. 后台先将数据流式写到 PC profile 的 `mapping_downloads/<任务ID>/`，显示字节进度。长度、源文件身份和 SHA256 全部通过后才发布本机文件；中断或校验失败保留 `.part`，不会提供下载链接。重试会建立新任务。
4. 整轮取回后在 PC 读取静态地图，生成 `final_map.pcd` / `final_map.json`，连同原 bag、清单、配置和 `download_report.json` 打包成 ZIP64。PCD 为最后收到的非空静态地图的有限 XYZ 点，保留 frame 和 bag 时间；FreeDOM 内部状态的完整恢复仍需另行实现。
5. 本机任务标为“可下载”后，点击文件链接保存到浏览器下载目录。浏览器与 SSH 两段都按块传输，无多 GB JavaScript Blob。退出页面不停止任务，工作台进程重启会把未完成任务标记为中断。

每次只运行一个准备任务；完整包开始前检查 PC 至少约原数据两倍加 1 GiB 空间。PCD 生成失败会明确告警，已校验的原始资料仍可作为整轮包下载。任务固定绑定 host、port、日志根目录；切换设备后旧目录请求会被拒绝，已取回的本机文件仍可下载。

默认飞行日志 Wi-Fi 同步排除 `mapping/`；需要时在这个独立区域手动下载。现有手工 bag、飞控 ULog 入口保持原有用途。

## 验证与版本边界

本轮只改源码与文档，未编译、部署、连接设备、启动 ROS 节点或执行仿真/飞行动作。板端原生 rosbag/LZ4 运行、真实话题覆盖和 Orange Pi 满负载性能尚未验收。

离线验证与完整输出见 [验证报告](docs/verification/mapping_recording_20261015/REPORT.md)。实施前已修改的既有文件原件保存在各仓库被忽略的 `logs/mapping_feature_20261015/before/`；对应基线信息在旁边的 `index.json`。


## 源码交付与配套版本

2026-10-15 按用户授权提交、推送源码和文档：工作台为 [WorkBench 分支](https://github.com/sakelier/liftrace-controlwork/tree/WorkBench)，板端为 [liftrace_board_trial_20260928 分支](https://github.com/sakelier/liftrace-controlwork/tree/liftrace_board_trial_20260928)。[板端操作说明与环境要求](https://github.com/sakelier/liftrace-controlwork/blob/liftrace_board_trial_20260928/docs/FREEDOM_MAPPING_RECORDING.md) 已配套补齐。提交推送不会部署到香橙派；本轮仍未编译、运行 ROS 或进行实机验收。
