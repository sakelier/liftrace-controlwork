# 自动建图记录与下载离线验证 · 2026-10-15

实现范围：板端三个 flight 入口的独立原频记录、清单/封闭/异常处理，以及工作台分页清单、来源绑定、流式校验取回、PCD、ZIP64 和页面状态。保持既有飞行控制链、手工日志入口和 ULog 流程。

## 执行结果

| 检查 | 结果 | 输出 |
| --- | --- | --- |
| 新记录进程逻辑（纯 Python 模拟 bag） | 16 项通过 | board_tests.txt |
| 清单、分卷读取、SSH 流、任务、HTTP、真实微型 ROS1 bag 转 PCD | 22 项通过 | workbench_tests.txt |
| 飞行日志同步及入口夹具 | 16 项通过 | sync_tests.txt |
| 既有本机离线工作台 | 6 项通过 | offline_tests.txt |
| 新日志区 DOM 状态、来源切换、原生下载链接 | 通过 | ui_tests.txt |
| 修改/新增的 12 个 Python 文件 AST、package.xml 解析、Node --check | 通过，无构建产物 | 本报告 |
| 两仓 git diff --check 及新增文件空白检查 | 通过 | 本报告 |

共 60 项 Python 离线测试通过，另有前端 DOM 和语法检查。测试生成的 bag/PCD/临时锁均在临时目录，不是飞行数据。

板端覆盖：原始消息/连接头、分卷、队列/大消息/磁盘/累计限额、缺失话题与点云序列缺口、写入和封闭失败、停止排空、启动失败放行、日志关闭异常、进程退出状态、独立进程锁互斥/释放且 inode 不替换，以及观察入口有/无外部地图。

工作台覆盖：超过旧 150 文件限制后的分页、活跃记录只列封闭文件、死进程降级、路径和符号链接拒绝、源文件变化、逐字节分帧与校验失败、增量 sink 内存边界、POSIX 和模拟 Windows SSH、失败不发布、整轮/单卷策略、重复请求/重启中断、设备切换拒绝、PCD 不可用仍保留原始包、大小端与行填充/NaN、真实 rosbags 生成的 ROS1 bag 导出最后静态地图，以及日志独立模式下的 HTTP/同源/断连下载。

## 命令

工作台使用已有 `.venv/bin/python`，设置 `PYTHONDONTWRITEBYTECODE=1`：

```text
python -W error::ResourceWarning -m unittest discover -s tests -p test_mapping.py -v
python -m unittest discover -s tests -p test_flight_sync.py -v
python -m unittest discover -s tests -p test_offline_workbench.py -v
node tests/mapping_ui_smoke.js
node --check web/mapping-recordings.js
```

板端源码仓使用系统 Python 执行完全独立于 ROS 的测试：

```text
python3 patrol_uav_ws-patrol_planner/src/uav_mission/test/test_freedom_recording.py -v
```

初次夹具把 FakeBag 的位置参数命名成 raw，和真实 API 的 raw=True 冲突，已修正。初次流式检查发现 POSIX 管道未关闭，已修复并使用 ResourceWarning 严格检查重跑通过。既有 flight-sync 三项入口测试缺少新增舵机预检的模拟，曾触发被沙箱阻止的 SSH 尝试；没有连接设备。已补齐该模拟后全部通过，未放宽任何产品预检。

## 尚未执行

遵照用户要求未编译或部署。2026-10-15 用户已授权源码和文档提交、推送到 WorkBench 及板端 liftrace_board_trial_20260928 分支；这不代表完成板端部署或实机验收。未运行 ROS1 原生 Bag 写入、真实 LZ4、板端话题连通、Orange Pi 5 Plus 实时吞吐/CPU/磁盘性能，以及实机飞行。真实微型 bag 的测试使用 PC 已有 rosbags 库，不替代板端运行验收。

后续应先审核并配套升级板端和工作台，在地面只读回放/数据源下核对实际话题、分卷封闭、断开后的状态及空间阈值，再单独授权飞行验收。保留原件见各仓 `logs/mapping_feature_20261015/before/`。
