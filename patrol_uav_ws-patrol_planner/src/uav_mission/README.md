# uav_mission

导航任务、规划执行和投递安全层。正式 VCL06 入口为：

```text
navigation_search_delivery_vcl06.launch
  -> random_field_spawner + planner_anchor_spawner
  -> navigation_mission_start_gate
  -> navigation_mission_manager（唯一任务策略）
  -> navigation_planner_bridge（唯一 /fastplanner/goal 发布者）
  -> patrol_control 外部任务模式
  -> guarded release / mock Servo
```

该入口实现起飞完成后启动、覆盖搜索、候选中断、同 stable ID 的
APPROACH/CAPTURE/ALIGN/RELEASE/RECOVERY 事务、三次投递、三门走廊路线和最终 H 降落。
旧 `coverage_search_manager.py`、视觉侧临时 manager 和
`navigation_visual_delivery_adapter.py` 均不在正式图中。

## 比赛 profile

正式 profile 固定为 `r2026`：

```text
red_cross=10.0
panzer=2.5
bridge=2.0
pillbox=1.5
tent=1.0
interrupt_top_k=3
```

因此 red_cross、panzer、bridge 都可中断搜索。tank 不进入比赛候选/投递队列。
`coverage_toudi3_random.yaml` 的历史文件名仅为 launch 兼容，内容只负责随机场生成几何；
搜索、权重和中断策略只由 `competition_profiles.yaml`、
`vcl06_random_field_runtime.yaml` 和 MissionCore 管理。

## 投递边界

```text
/uav_vision/release_evidence + frozen context + align mode + UAV pose
  -> release_permission_arbiter
  -> /mission/release_permission
  -> guarded_servo_proxy (/Servo)
  -> /legacy/Servo_raw
  -> /mission/release_result
```

`patrol_control` 仍调用 `/Servo`，顺序槽位 `1/2/3` 和服务返回语义保持兼容。
仿真使用 `release_guard_sim.launch` 的纯软件 mock；本包不启动真实 `actuator_pwm`、PWM 或舵机。

## 视觉运行依赖

导航仓只携带构建正式任务链所需的两条视觉上下文消息：

```text
uav_vision/AlignmentTargetContext
uav_vision/ReleaseEvidenceContext
```

完整仿真必须叠加视觉冻结分支
`liftrace-visionwork:feat/vcl06-local-full-mission@34ce0c3`，并让它的
`uav_vision` 包优先。导航仓自己的旧 `phase_d.launch` 不具备正式运行合同；不得通过删除
`class_profile` 或 `require_alignment_context` 参数来绕过依赖检查。正确 overlay 顺序、构建命令、
现有 r9 阻塞和后续 Gate 条件见
`docs/导航组本地完整任务联调HANDOFF_20260902.md`。

## 当前验收边界

代码同步后，`plan_manage;patrol_control;uav_mission` Catkin 构建和 219 项测试通过；使用上述视觉
overlay 时完整 launch 可递归解析。尚未在导航 fork 分支重跑完整 SITL。最近一次 r9 实跑只完成
panzer 首投与恢复，随后在 red_cross 接近前遇到 planner 目标接受竞态，并以高度
`4.002849 m` 触发硬 Gate；第二/第三投、完整三门走廊和 H/LAND 仍需联合仿真验证。
