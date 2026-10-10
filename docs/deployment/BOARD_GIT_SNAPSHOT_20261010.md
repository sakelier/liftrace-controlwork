# 板端 Git 初始化与源码快照

日期：2026-10-10

来源目录：`/home/orangepi/liftrace_board_trials_20260928`，SSH 地址 `10.28.111.193`。

目录原先没有 Git 元数据，也没有嵌套 Git 仓库。本次初始化独立的源码快照分支
`liftrace_board_trial_20260928`，远程 `origin` 指向
`https://github.com/sakelier/liftrace-controlwork.git`。

提交现有源码、配置、脚本、部署说明和小型报告，不修改飞行、视觉、导航或舵机业务逻辑。
沿用既有 `.gitignore`，并补充 `*.elf`，将冻结的编译可执行文件留在板端。

原始资产仍保留在本机目录：`logs/` 为飞行日志/bag，`runtime_models/` 为 RKNN 权重，
`vision_ws/build/`、`vision_ws/devel/`、`patrol_uav_ws-patrol_planner/build/` 和
`patrol_uav_ws-patrol_planner/devel/` 为已有构建产物，根目录 `board_*.tar.gz` 为部署归档。
这些资产按忽略规则不入 Git，没有删除或移动。

验证范围：文件清单、忽略规则、Git 提交和目标分支推送。未编译，未运行仿真、硬件驱动或飞行任务。
该初始快照不代表新增实机验收。GitHub 认证沿用 WSL 已有凭据，不将凭据复制到板端。
