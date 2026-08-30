# NAV VCL06 确定性任务核心

## 范围

`uav_mission.mission_core` 是不依赖 ROS 的导航任务策略层。它只接收显式候选快照、
当前位置、任务时钟和 `NavigationResult` 对应的事实，不直接发布规划目标，也不调用投递
机构。ROS 消息转换、话题所有权及执行桥留给独立运行层。

本核心使用 `competition_profiles.yaml/r2026`，正式类别固定为 `tent、pillbox、bridge、
panzer、red_cross`；`tank` 和未知类别以 `profile_excluded` 拒绝。高权重搜索中断集合由
profile 确定为 `red_cross、panzer、bridge`。

## 候选准入和身份

候选只有同时满足下列条件才进入持久队列：

- `state == CONFIRMED(2)`，连续有效观测不少于 3 帧；
- 地图点、关联和 map frame 有效，且无视觉拒绝原因；
- 候选年龄和 TF 年龄均不超过 0.5 秒；
- 置信度/地图质量位于 `[0, 1]`，位置与时间均为有限值；
- 高度不超过 4 m，类别属于当前 profile。

目标实例键为 `(target_id, first_seen_ns)`。`target_id=0` 按合同是合法 ID；纳秒时间键避免
ROS epoch 浮点秒精度丢失。队列按“权重、可达性、地图质量、类别置信度、距离、首次出现
时间、ID”稳定排序，同一类别只让最佳实例竞争槽位，已投类别不重复投递。

## 搜索、时限和槽位

- 只在 `SEARCH` 阶段允许高权重目标中断；执行中的新候选只入队，不抢占当前任务。
- 低权重目标在覆盖路线结束，或进入动态时间兜底窗口后才参与投递。
- 动态估时包含保守路径系数、单槽服务时间、返航路径、返航/降落储备和决策 guard。
- 预计无法在 510 秒前完成当前投递，或无法在 600 秒内完成返航降落的候选不启动。
- 510 秒是硬返航边界；三槽一经提交完毕立即返航。
- 未提交失败释放槽位；可重试候选冷却 20 秒，最多尝试 2 次。

## 结果 reducer 与不可逆边界

结果按 `mission_id + executor_id + event_seq` 去重，并逐字段核对 `decision_seq、command、
target_id、target_first_seen、target_class、attempt、payload_slot`。执行器在任务中途改变、
重复/乱序事件或身份不一致均不能改变队列。

payload 的唯一提交事件为非终态 `PROGRESS/RELEASE`，并同时满足：

```text
payload_committed=true
retryable=false
reason=release_ack_success
evidence_source 非空
```

提交后槽位和类别不可回滚。后续必须以 `RECOVERY` 终态收尾；恢复失败会保留已提交槽位、
标记任务失败并立即返航。未见提交 ACK 的成功终态以 `success_without_payload_commit`
拒绝。语义非法的事件不会消耗 event sequence，因此同序号的修正事件仍可被接收。

## 验证边界

`test/test_mission_core.py` 以系统 Python 执行确定性回归，不启动 ROS master、Gazebo、PX4
或执行机构。它覆盖准入拒绝、权重排序、搜索中断边界、覆盖/时间兜底、冷却重试、硬返航、
结果幂等、三槽完成，以及释放提交后恢复失败等核心状态转换。

尚未在本阶段完成：ROS manager 运行桥、planner 遥测消费、搜索路线游标恢复、统一仿真与
真实执行代理。它们必须在合同和本核心之上独立实现，不能回退为直接调用舵机。
