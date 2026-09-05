# 导航部署前基线与收口交接

日期：2026-09-05（2026-09-06 完成导航收口回填）
状态：`NAVIGATION_CLOSEOUT_READY / JOINT_GATE_PENDING`
职责边界：本文由导航侧维护；视觉 worktree 的清理由视觉组 Codex 独立负责。

## 1. 删除前冻结的唯一整场跑通组合

实际完成 r41 整场飞行的是以下两个 Git revision 的组合，不是各仓当前 feature tip：

| 角色 | 仓库 | 实跑 revision | 提交说明 |
| --- | --- | --- | --- |
| 视觉、相机模型、联合启动包装 | `Qinling-Melon-Farmers/liftrace-visionwork` | `8e53bd061dde75deff49c2621464bee56428e423` | `fix: 统一联合仿真源码权威` |
| 导航、任务、规划、控制 | `sakelier/liftrace-controlwork` | `35572154e27849d2f82c998c9528789622ab3a60` | `fix: 收敛外部任务执行链并稳定入门方向` |

配套输入固定为：

```text
world: toudi3_random.world
mission/class profile: r2026
field seed: 11
camera: KS2A543, 1280x720@30 Hz, HFOV about 82.85 deg
detector: 0714 merged_standard, six classes
selected delivery classes: panzer, bridge, red_cross
planner goal owner: /navigation/planner_bridge
```

r41 完成三次不同 stable ID 投递、三次恢复、投后路线 9/9、Wall_15/20/22、H 连续锁定、
AUTO.LAND、ON_GROUND 和 disarm；最高 `3.696886 m`，碰撞/越界/超高均为 0。从首个任务决策到
LAND 成功的 ROS 任务时钟为 `429.875 s`，其中 LAND 为 `32.73 s`。

历史 `gate_status.json` 的形式结果是 FAIL，唯一红项是误把 `1761.101 s` 主机墙钟当作比赛
600 秒；不得把它描述成原生 Gate PASS。准确结论是：**r41 业务与安全事实 PASS，历史 Gate
形式 FAIL，失败原因已由后继导航提交修正。**

`liftrace-sim` 没有参与 r41 飞行执行，因此不属于这组跑通 revision；它只用于后续策略研究。

## 2. r41 后继候选，不能冒充已实跑组合

| 仓库 | 当前候选 | 相对 r41 | 是否按精确组合整场实跑 |
| --- | --- | --- | --- |
| 视觉收口 | branch/docs tip `feat/vdeploy-final-closeout-plan@9ed1d463d97c8e5d2dfeb217d1a66f19e01d9861`；运行代码 `9324745ed6aec77125f21dd92804930232354551` | 已继承 KS2A543/r41 候选 `56f0667`，并由 `8dd996f` 非快进合入实机外参 `f0b1b8b`；正式 Phase-D 默认关闭 legacy bridge，并移除 bridge 的无效 `drop_ready` 订阅 | 否；视觉 worktree clean/pushed |
| 导航收口 | `feat/vcl06-local-full-mission@be85c423f13d840519f2c0af739394fcd557dcb1` | 在 `6c59e17` 后冻结基线、改用 typed H、关闭正式 legacy 视觉桥、删除视觉源码副本并修复空目录构建 | 否；空目录全量构建及纯测试 222/222 PASS |

最终联合 Gate 必须记录视觉运行代码 `9324745`、导航运行代码 `be85c42` 及两仓各自的仅文档
branch tip，不能只引用“r41”或某一个仓库的 tip。若候选代码在 Gate 后又发生变化，旧 PASS
不自动继承。

## 3. 证据可用性

r41 原目录曾记录为：

```text
/home/xhj/liftrace-worktrees/pr3-premerge-hygiene/logs/
  vcl06_full_competition_headless_r41_20260905_202359/
```

视觉侧上一轮 worktree 清理后，当前 WSL 工程树和已知归档中未找到该 run 的完整
`manifest.yaml`、`gate_status.json`、run.log 或原始 bag；只在视觉根仓
`logs/worktree_archive_20260905/pr3-premerge-hygiene/` 保留部分 ROS 节点日志。本文和既有报告
仍可作为结果记录，但不能称为完整可复现证据包。若团队另有外部备份可回填；否则最终候选需运行
一次新的完整 Gate，并先把结构化证据迁出临时 worktree 再清理。

导航三个现存 worktree 内均未发现 bag、Gate report、manifest、run.log 或录屏，因此本轮导航
磁盘清理不会删除 r41 原始证据。

## 4. 双仓源码与接口所有权

### 4.1 视觉负责

- `camera_sdk`、`uav_vision` 全部运行源码、消息定义、模型入口、内外参和视觉测试；
- 保留 legacy `detect_compat_bridge` 给旧 launch 回归，但正式 external 联合入口允许通过现有
  `start_legacy_compat:=false` 不启动它；
- 最终视觉 install 必须提供导航编译所需的 `TargetDetectionArray`、`TargetCandidate`、
  `DropOffset`、`DropReady`、`AlignmentTargetContext` 和 `ReleaseEvidenceContext`。

### 4.2 导航负责

- `uav_mission`、Mission Manager、Planner Bridge、`patrol_control` external mode、FAST-LIO、
  FreeDOM、Fast-Planner、走廊/H/LAND 控制和 Gate；
- 正式 external H 输入直接消费 `/uav_vision/detections_mapped` 的 `landing_pad` 地图点；
- 正式 external launch 关闭 legacy compat，并移除 `/detect/land_mark_point`、
  `/detect/landing_control` 对正式链和 Gate/rosbag 的依赖；
- legacy mode 继续保留旧话题和旧状态机，不改变 2025 回归入口；
- 导航仓删除自身跟踪的 `vision_ws/src/uav_vision` 副本，联合构建固定为先 source 视觉 install、
  再构建导航工作区。导航不复制或二次维护视觉运行源码。

## 5. 导航 worktree 清理边界

删除前导航 worktree 为：

| 路径 | 状态 | 处置 |
| --- | --- | --- |
| `/home/xhj/liftrace-controlwork-nav` | clean；本地 `main@a68925d` 落后 `origin/main@a182ca9` 26 个提交 | 保留仓库管理 checkout；不作为最终构建源 |
| `vcl06-local-full-mission` | 功能 revision `be85c42` clean/pushed；本文回填只追加文档 | 保留；build/devel/cache 已删除 |
| `vcl06-planner-stop-ack@c12ee0c` | 14 个 tracked 修改、7 个未跟踪协议文件 | 原样保留；不纳入最终链、不自动删除 |

本轮只删除了精确列出的 build、devel 和 Python cache。所有 Git 分支、远端引用、dirty
stop-ack 实验、原始资产和视觉 worktree 均未删除；实际结果见第 7 节。

## 6. 最终交接顺序

1. **已完成**：导航 typed H、正式 launch 关闭 legacy compat、删除导航视觉源码副本，以及
   纯测试、launch 静态展开和空目录全量编译。
2. **已完成（视觉侧）**：视觉最终分支已合入 KS2A543 候选和实机外参，清理默认旧话题及
   无效订阅，并将 clean/pushed branch tip 冻结为 `9ed1d46`、运行代码冻结为 `9324745`。
3. **已完成（源码级静态）**：按视觉 `9324745` 源码与导航 `be85c42` 展开正式 launch，确认
   typed H 存在、两个旧降落话题不存在；两视觉 revision 间消息 ABI 无变化。
4. 从两个 clean checkout 生成最终 install 和 `integration_manifest.yaml`，确认
   `rospack find uav_vision` 解析到视觉 install，且
   `/fastplanner/goal` 只有 `/navigation/planner_bridge` 一个发布者。
5. 经用户当轮明确授权后运行一次最终完整 SITL，保存 manifest、Gate、timeline、日志和必要 bag。
6. 只有候选 Gate PASS 后，才由人工将两个 PR 非快进合入 main、打 annotated tag，并用最终
   merge revision 更新 `integration_manifest.yaml`。

## 7. 本轮导航清理结果

### 7.1 源码与接口

- 导航功能收口提交：`be85c423f13d840519f2c0af739394fcd557dcb1`，已推送
  `origin/feat/vcl06-local-full-mission`。
- 从导航仓删除 `vision_ws` 下 78 个 tracked 视觉副本文件；正式构建只认视觉仓
  `uav_vision` devel/install。
- external `patrol_control` 直接订阅 `/uav_vision/detections_mapped`，H 证据必须同时满足
  `landing_pad`、`map_valid`、`geometry_verified`，并继续经过时间戳、frame、锚点距离和稳定帧检查。
- 正式 launch 明确 `start_legacy_compat:=false`；Gate/rosbag 不再依赖
  `/detect/landing_control`、`/detect/land_mark_point`。legacy launch 默认值仍为 true，旧工程回归
  没有被删。
- external 模式不再 advertise `/detect/control`、`/detect/landing_control`、
  `/detect/class_control`、`/detect/tank_control`、`/detect/servo_status` 和 `/cross/control`。
  `/detect/point_class` 仍被 release arbiter 与 Planner Bridge 实际消费，`/Servo` 仍是投递执行
  服务，两者不是冗余接口，本轮有意保留。

### 7.2 构建与静态验收

- 首次空目录构建暴露并修正两个导航上游遗漏：`local_sensing` 无效 `cmake_modules` 依赖、
  vendored `cv_bridge/src/CMakeLists.txt` 缺失。
- 删除旧 build/devel 后，source 视觉 devel 并执行全工作区
  `catkin_make -DROS_EDITION=ROS1 -j1`，从 0 到 100% PASS；typed H C++ 已实际编译链接。
- `uav_mission` 全量纯 Python 回归 `222 tests` PASS；`git diff --check` PASS。
- 先前空目录全量编译使用既有视觉 devel；随后只读 launch 展开已强制 `uav_vision` 指向最终视觉
  运行源码 `9324745`，889 行参数解析 PASS。展开结果含 `/uav_vision/detections_mapped`，不含
  `/detect/landing_control` 或 `/detect/land_mark_point`；`e5fdc68..9324745` 的消息定义无差异。
  该静态验证未连接 roscore、未启动节点，最终 clean install 联合构建仍列为 Gate 前置项。

### 7.3 本地清理与保护结果

- 完整任务 worktree 从约 `968 MiB` 降至 `446 MiB`，释放约 `522 MiB`；删除内容为本次验证
  生成的 build/devel、先前残留 build/devel 和 Python cache。
- 导航主 worktree 仍为 `main@a68925d`，约 `618 MiB`；本地 main 仍落后
  `origin/main@a182ca9` 26 个提交，未合并、未重置、未作为交付 revision。
- dirty `vcl06-planner-stop-ack@c12ee0c` 仍为 14 个 tracked 修改和 7 个未跟踪文件；清理前后
  `git status --porcelain -uall` 完全一致。
- 最终 `git worktree list` 只有上述 3 个保留项；没有删除分支、tag、远程引用或任何视觉 worktree。

### 7.4 给视觉侧 Codex 的接力项

1. **已完成**：视觉最终分支已整合 `56f0667` 与外参 `f0b1b8b`，唯一运行代码 revision 为
   `9324745`，clean/pushed 文档 tip 为 `9ed1d46`；运行 TF 与测量元数据的语义由视觉交付文档维护。
2. 从 clean checkout 产出视觉 install，至少包含本文第 4.1 节六类消息、Phase-D 节点、KS2A543 内参、实机外参
   profile 和 RKNN 模型入口；正式联合入口允许 `start_legacy_compat:=false`。
3. 与导航 `be85c42`（或本文档后继）共同生成 `integration_manifest.yaml`，先静态确认
   `rospack find uav_vision` 指向视觉 install，再在用户当轮明确授权后只跑一次完整 SITL Gate。
4. Gate 通过后才进入人工 PR/main/tag；`liftrace-sim` 单策略筛选和板端无桨 Stage A–C 仅列为
   后续计划，本轮未执行。
