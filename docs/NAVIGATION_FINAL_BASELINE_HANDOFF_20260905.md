# 导航部署前基线与收口交接

日期：2026-09-05  
状态：`PRE_CLEANUP_BASELINE_FROZEN`  
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
| 视觉 | `feat/vdeploy-final-closeout-plan@e5fdc6897d9ff76a95895d69de0863bffa6754bf` | 从 `8e53bd0` 到该提交只有 Roadmap/报告/变更记录；含 `56f0667`，尚不含 `f0b1b8b` | 否 |
| 视觉外参 | `feat/vdeploy-camera-extrinsic@f0b1b8be8df7a4ba716ff68b452eb522ef3b0c07` | 增加板端外参 profile/launch；当前运行值为 `body -> camera -0.16 m`，MID360 `-0.21 m` 只是测量元数据 | 否 |
| 导航 | `feat/vcl06-local-full-mission@6c59e1769c68255b68d00449248db807582014e8` | `3557215` 的直接子提交；修正 ROS/墙钟、LAND action deadline 和 passive audit 重复裁决 | 否；纯测试 220/220 PASS |

最终联合 Gate 必须记录新的视觉候选 HEAD 与导航 `6c59e17`，不能只引用“r41”或某一个仓库的
tip。若候选代码在 Gate 后又发生变化，旧 PASS 不自动继承。

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
| `vcl06-local-full-mission@6c59e17` | clean/pushed；最终导航候选 | 保留；只删除可再生 build/devel/cache |
| `vcl06-planner-stop-ack@c12ee0c` | 14 个 tracked 修改、7 个未跟踪协议文件 | 原样保留；不纳入最终链、不自动删除 |

本轮允许删除的导航本地产物只有精确列出的 build、devel 和 Python cache。所有 Git 分支、远端
引用、dirty stop-ack 实验、原始资产和视觉 worktree 都不删除。清理后的实际释放量和最终状态在
第 7 节回填。

## 6. 最终交接顺序

1. 导航完成 typed H、正式 launch 关闭 legacy compat、删除导航视觉源码副本，并做纯测试、
   launch 静态展开和编译检查。
2. 视觉侧独立完成视觉 worktree 清理，在最终 closeout 分支合入外参 revision；不得删除视觉
   权威 `uav_vision`。
3. 冻结精确双仓候选，确认 `rospack find uav_vision` 解析到视觉仓，且
   `/fastplanner/goal` 只有 `/navigation/planner_bridge` 一个发布者。
4. 经用户当轮明确授权后运行一次最终完整 SITL，保存 manifest、Gate、timeline、日志和必要 bag。
5. 只有候选 Gate PASS 后，才由人工将两个 PR 非快进合入 main、打 annotated tag，并生成
   `integration_manifest.yaml`。

## 7. 本轮导航清理结果

待本轮代码、接口和磁盘清理完成后回填；在此之前不得把状态改成 `CLOSEOUT_READY`。
