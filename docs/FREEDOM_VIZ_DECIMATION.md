# FreeDOM RViz 点云降载

## 目的

FreeDOM 的 `/freedom/static_pointcloud` 是规划输入，必须保持原始内容、发布节奏和订阅关系。RViz 直接订阅该话题会把完整静态地图持续序列化和传输，增加不必要的 CPU 与带宽负载。

本分支新增仅供可视化使用的 `/freedom/static_pointcloud_viz`：

- 只有存在订阅者时才构建；
- 默认最大发布频率为 `0.5 Hz`；
- 默认使用 `0.20 m` 体素降采样；
- 消息保留 `map_tf_frame`，并在发布时写入 ROS 时间戳；
- 不改变 `/freedom/static_pointcloud` 及任何规划订阅者。

## 参数

参数位于 `freedom` 节点私有命名空间：

```yaml
visualization:
  static_pointcloud_viz_max_rate_hz: 0.5
  static_pointcloud_viz_voxel_size: 0.20
```

两个参数必须是有限正数。无效值会回退到上述默认值并输出警告。节流使用墙钟，因此 Gazebo `/clock` 暂停或回拨不会造成可视化消息突发。

## 运行检查

启动正常建图链后，可进行只读检查：

```bash
rostopic hz /freedom/static_pointcloud_viz
rostopic bw /freedom/static_pointcloud_viz
rostopic echo -n 1 /freedom/static_pointcloud_viz/header
rostopic info /freedom/static_pointcloud
```

预期 `_viz` 频率不超过配置值，header 中具有时间戳和地图 frame；Fast-Planner 仍订阅原始 `/freedom/static_pointcloud`。

## 本分支验证

- `catkin_make -DROS_EDITION=ROS1 -DCATKIN_WHITELIST_PACKAGES=freedom -j1`：通过；
- `catkin_make -DROS_EDITION=ROS1 -DCATKIN_WHITELIST_PACKAGES=freedom run_tests_freedom -j1`：节流测试全部通过；
- `git diff --check`：通过。

本次未启动 Gazebo。实际点云压缩比、话题带宽和建图线程瞬时耗时仍需在统一仿真 run 中测量，不能由编译和单元测试代替。
