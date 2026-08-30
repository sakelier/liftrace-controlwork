# FreeDOM RViz 点云降载

## 目的

FreeDOM 的 `/freedom/static_pointcloud` 是规划输入，必须保持原始内容、发布节奏和订阅关系。RViz 直接订阅该话题会把完整静态地图持续序列化和传输，增加不必要的 CPU 与带宽负载。

本分支新增独立进程 `static_pointcloud_viz_node`，输出仅供可视化使用的
`/freedom/static_pointcloud_viz`：

- 输出无人订阅时主动断开原始点云输入，不接收也不处理全图；
- 有订阅者时使用输入队列 1，只处理节流时刻的最新一帧；
- 默认最大发布频率为 `0.5 Hz`；
- 默认使用 `0.20 m` 体素降采样；
- 默认保留输入坐标和 frame，输入时间戳为零时补当前 ROS 时间；
- 不改变 `/freedom/static_pointcloud` 及任何规划订阅者。

体素过滤不在 `freedom_node` 建图回调内执行。两个节点进程隔离，因此降采样计算
不会同步阻塞 FreeDOM 的地图集成与原始点云发布路径。统一 launch 默认启动 relay，
也可用 `enable_static_pointcloud_viz:=false` 关闭。

## 参数

参数位于 `static_pointcloud_viz` 节点私有命名空间，默认配置文件为
`FreeDOM/config/static_pointcloud_viz.yaml`：

```yaml
input_topic: /freedom/static_pointcloud
output_topic: /freedom/static_pointcloud_viz
input_queue_size: 1
output_queue_size: 1
max_rate_hz: 0.5
voxel_leaf_size: 0.20
frame_policy: preserve_input
frame_id_override: ""
stamp_policy: now_if_zero
```

`frame_policy` 可选 `preserve_input` 或 `override`；后者要求设置
`frame_id_override`，且仅用于已有正确 TF 的场景，不执行坐标变换。
`stamp_policy` 可选 `preserve_input`、`now_if_zero` 或 `now`。

话题不得相同，队列必须为正整数，频率和体素尺寸必须是有限正数；配置错误时节点
直接退出，避免静默采用错误坐标契约。节流使用单调墙钟，不依赖 Gazebo `/clock`。
可通过 launch 参数 `static_pointcloud_viz_config` 替换整份配置文件。

## 运行检查

启动正常建图链后，可进行只读检查：

```bash
rostopic hz /freedom/static_pointcloud_viz
rostopic bw /freedom/static_pointcloud_viz
rostopic echo -n 1 /freedom/static_pointcloud_viz/header
rostopic info /freedom/static_pointcloud
```

预期 `_viz` 频率不超过配置值，header 中具有时间戳和地图 frame；Fast-Planner
real/sim launch 仍订阅原始 `/freedom/static_pointcloud`。关闭所有 `_viz` 订阅者后，
`rostopic info /freedom/static_pointcloud` 中不应再出现 relay 输入连接。

## 本分支验证

- `catkin_make -DROS_EDITION=ROS1 -DCATKIN_WHITELIST_PACKAGES=freedom -j1`：通过；
- `catkin_make -DROS_EDITION=ROS1 -DCATKIN_WHITELIST_PACKAGES=freedom run_tests_freedom -j1`：坐标、header、无订阅门控、节流与参数策略测试全部通过；
- `roslaunch --dump-params freedom run_freedom_mid360.launch`：通过，relay 参数正确落入 `/static_pointcloud_viz/*`；
- `git diff --check`：通过。

本次未启动 Gazebo。实际点云压缩比、relay 输入/输出带宽、进程 CPU 和原建图频率
仍需在统一仿真 run 中测量，不能由编译和单元测试代替。
