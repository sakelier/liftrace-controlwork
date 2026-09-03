# VCL06 Fast-Planner 目标状态遥测

## 目的

`plan_manage` 在不改变规划行为的前提下发布 `/planning/goal_status`，让任务层能够把
目标请求、实际规划目标和每次规划尝试关联起来。本变更不增加超时、有限重试或新的
到达判定，也不修改目标、阈值、轨迹生成和 FSM 状态迁移。

节点使用私有参数 `~goal_status_topic` 配置输出话题，默认值为
`/planning/goal_status`。launch 中可按需设置：

```xml
<param name="goal_status_topic" value="/planning/goal_status" />
```

## 消息契约

话题类型为 `plan_manage/PlannerStatus`：

- 原始 `goal_seq` 取自 `/fastplanner/goal` 的 `PoseStamped.header.seq`，只表示该 ROS
  publisher 的传输序号；rospy/roscpp 都可能在序列化时重写它，不能直接作为任务代际。
- `event_seq` 是当前 planner 进程内单调递增的遥测事件序号；进程重启后从 1 开始。
- 顶层 `header.seq` 是 roscpp 管理的发布传输序号，发布时会被重写，不要求与
  `event_seq` 相等，也不得用于任务层排序或去重。
- `planning_attempt` 在每个新目标到来时清零，每次真实调用 kinodynamic replan 前递增。
- `requested_goal` 保存收到的目标；`effective_goal` 反映 preset 解析或避障调整后的目标。
- `distance_to_goal` 使用最新 odom 到 `effective_goal` 的欧氏距离；尚无 odom 时为 NaN。
- `FAILED_ATTEMPT` 只表示一次规划调用失败，明确为非终态；原 FSM 仍按既有逻辑重试。
- `TRAJECTORY_FINISHED` 只表示当前局部轨迹时间走完，不等价于任务层的速度/驻留到达判定。
- 活跃目标被新目标覆盖时，旧传输目标先发布 `CANCELLED`，随后新目标发布 `ACCEPTED`。

执行桥把导航决策的 `issued_at` 原样保存在 `/fastplanner/goal.header.stamp`；planner 在
`requested_goal/effective_goal` 中回传该时间戳。live bridge 以这个保留时间戳映射回当前或
待取消的 `decision_seq`，再进入任务生命周期归约。嵌套 `header.seq` 与原始 `goal_seq` 仍需
彼此一致，用于检查单条遥测内部没有撕裂，但不再承担任务身份。未知时间戳的旧 publisher
遥测按 foreign goal 忽略；从未收到 `ACCEPTED` 便超时的目标也不建立无法兑现的取消栅栏。

状态序列通常为：

```text
ACCEPTED
  -> PLANNING -> TRAJECTORY_READY
  -> REPLANNING -> TRAJECTORY_READY
  -> TRAJECTORY_FINISHED
```

单次失败会产生 `PLANNING/REPLANNING -> FAILED_ATTEMPT`，随后是否继续尝试完全沿用原 FSM。

## 验证

```bash
source /opt/ros/noetic/setup.bash
cd /home/xhj/liftrace-controlwork-worktrees/vcl06-planner-telemetry/patrol_uav_ws-patrol_planner
catkin_make -DROS_EDITION=ROS1 -DCATKIN_WHITELIST_PACKAGES=plan_manage -j1
catkin_make -DROS_EDITION=ROS1 -DCATKIN_WHITELIST_PACKAGES=plan_manage \
  run_tests_plan_manage_gtest_planner_status_schema_test -j1
catkin_test_results build/test_results/plan_manage
```

该验证只构建消息、节点和 schema/序列化测试，不启动 ROS master、Gazebo、PX4 或执行机构。

## 初始化安全修正

`KinoReplanFSM::init()` 显式把 `trigger_` 初始化为 `false`。原实现会在收到首个 goal 前由
INIT 状态读取该成员，未初始化值可能导致未定义分支；本修正不改变目标、轨迹或控制输出，
只固定启动状态。

## Catkin 下游依赖修正

`plan_manage` 只生成消息并构建可执行节点，没有名为 `plan_manage` 的库目标。因此
`catkin_package()` 不再导出不存在的同名库。该修正确保 `uav_mission` 等下游包可以通过
`find_package(catkin COMPONENTS plan_manage)` 使用 `PlannerStatus`，不会在 CMake 配置阶段
因虚假库导出而失败。
