# 飞行工作台分发包

2026-10-14：第04/08组支持“从本机导入航点 YAML”，地图窗口新增“导出地图 YAML”。导出当前编辑的地图与航点为 `waypoint_map.yaml`，可再次导入；导入后需点击“保存并用于本组”才应用。完整现场文件中的其他飞行参数不通过地图导入。重启服务并刷新页面后可用，详情见 [地图调整说明](WAYPOINT_EDITOR.md)。

2026-10-13：新增可选“启动 flight 后持续同步日志到 PC”，默认关闭。支持限速、后台增量传输、暂停/续传，录制封闭后修复改写块并做 SHA256 校验；完整 bag 可直接进入本机离线分析。重启服务并刷新主页生效。使用与验证边界见 [飞行日志同步说明](FLIGHT_LOG_SYNC.md)。

本包只包含笔记本侧工作台。无需完整工程、ROS、模型或 WSL。启动监听 localhost，等待用户点击连接；不会自动 SSH、启动设备、解锁或起飞。

Bag 回放入口 `/replay` 可发现并播放已有结果，查看功能同样无需 ROS/WSL。
**Windows / Linux 均支持原生离线 ROS1 回放与投递/降落曲线分析**，无需 WSL、ROS Noetic 或 roscore。使用 Python 3.10+ 及 `requirements.txt`；视频生成另需 FFmpeg/ffprobe，曲线分析不依赖 FFmpeg。页面 `/replay` 可选择本机 bag 或导入文件，视频和曲线的输出文件夹分别选择，曲线只输出 PNG，成功后自动打开 HTML 报告。

## Windows 原生启动

使用已有 Windows Python 3.10+ 环境及 PyYAML、pexpect、Paramiko（版本范围见 requirements.txt）；离线 ULog 分析另需已有 numpy、matplotlib。pyulog 1.2.4 的读取源码及 BSD 许可随包提供，优先使用环境内已安装版本，无需另装 pyulog。pexpect 仅复用异常类型，Windows 不使用 Unix PTY。脚本检查依赖，不安装包或新建环境。本机已用 Windows Anaconda Python 3.12 验证，未在未安装 Python 的干净 Windows 上验证。

1. 完整解压 ZIP 到本地目录，例如 C:\flight_workbench；支持中文和空格目录。
2. 双击 start_windows.bat（start_windows.cmd 同效），或 PowerShell 执行：
   `./start_windows.ps1 -Python D:\Anaconda3\python.exe -Open`
3. 仅离线看页面：`./start_windows.ps1 -Transport local`。Windows local 模式禁止运行 Linux 设备命令。
4. 默认请求 8771；以终端实际打印的 URL 为准。日志链接 /logs 与实时观察 /observe 跟随当前页面 host/port。端口被占用会顺延；可用 -Port 指定。
5. 需要独立状态时用 `-ProfileDir C:\你的私有目录\workbench_state`。此处是 Windows 路径。包内没有密码、密钥或个人 profile。
6. 正常收尾后 Ctrl+C；不在设备会话运行时替换后端。独立日志后端可用 `-LogsOnly -Port 8772`，不启动探针或设备。

Windows 用 Paramiko SSH channel 复用终端、Ctrl+C、resize 和二进制下载。支持内存密码、已有密钥/可用 agent；known_hosts 位于本用户 ~/.ssh/known_hosts。只在配置 StrictHostKeyChecking=accept-new 时接受并保存新指纹，指纹变化拒绝连接。没有自动导入 PuTTY saved sessions 或完整 OpenSSH config；页面须填准确 user@host/端口。加密私钥单独解密和不兼容的 agent 未验收。

连接设置支持`identity_file`本机私钥路径：WSL/OpenSSH使用该文件并限制密钥选择，Windows/Paramiko将其作为key_filename；留空恢复默认密钥/agent。路径保存到使用者的本机profile，ZIP不含私钥或个人profile，Windows需填写Windows可访问路径，不能直接沿用WSL的/home路径。仅保存连接参数不自动连接、不启动探针或设备。

独立正赛环境的通用预检检查根内field.example.yaml的存在及site_confirmed文件声明，不要求08的test_area.yaml或专项模块；模板检查不代表现场确认或飞行配置验收。切独立根时model/metadata必须属于该根，根内绝对路径会转成相对路径，根外或越界路径拒绝保存。

Windows 无法核查远端 PTY 的 echo，因此不会自动填写 sudo 口令，5a 经确认后需终端手工认证；Linux 保留原有有限次数且确认 echo 关闭的应答。SSH 登录密码不出现在命令行、ZIP、终端日志或 URL。记住口令仍是用户明确可选操作，只写个人状态目录；不要把状态目录打包分享。

## Linux / WSL

使用已有 rl_drone：

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate rl_drone
bash start_workbench.sh
```

Linux 需要 Python 3.9+、pexpect、PyYAML、bash、OpenSSH，无需 Paramiko。可用 WORKBENCH_PYTHON 指向已有环境。脚本可复用系统纯 Python 依赖，不安装任何包。

## 比赛与测试

独立正赛卡片调用 deployment/competition/start.sh，默认 YAML 是 deployment/competition/field.example.yaml。入口和模板由整机工程提供，未随本工具包部署。10月8日晚候选为规划速度1.2m/s、加速度1.0m/s²，搜索前视1.0m、精调0.4m、走廊快/慢0.6/0.4m，投递FC离地0.35m、高位软件上限3.2m。基础模板FC高2.6m；矩形/双线候选镜头2.6m（FC2.76m）；三线候选镜头2m（FC2.16m）。具体有效参数以实际生成配置为准。

08整场卡新增“正赛速度验证”选择，默认仍选“有限场地速度”。两者均使用10月7日22:17:30成功轮现场坐标，搜索FC高2m、走廊0.9m、到H后观察1.2m，场地不因速度选择而改变。新投递补偿及H低位交接随同版板端代码生效；工作台ZIP不会自行更新板端代码。运动优化、高位续扫默认开启；尚未验收的脱困恢复默认关闭。

正赛模板必须按 10×10 场地实测填写并确认门口、H、边界及路线。昨晚成功轮属于测试场地，不能作为正赛默认坐标或正赛验收。复现测试时另填 F 代理提供的测试示例路径，完整命令会显示实际文件。

运动优化、高位续扫、障碍柱均有“继承所选 YAML / 显式开启 / 显式关闭”。继承不传覆盖参数；开启/关闭传 --motion-optimization on/off、--resume-survey on/off、--obstacle-columns on/off，须整机入口支持这些 CLI。正式模板默认开启运动优化与高位续扫，历史测试配置保留原值；二者独立。先用“配置检查”查看真实有效参数与来源。卡片分别显示所选请求、“离线配置检查”和“运行已生成配置”；没有监督器结果或改变路径/开关后显示“尚未确认”。不以 UI 选中冒称配置已经生效。障碍柱关闭仅移除配置柱，真实点云避障仍依入口配置。工作台不修改飞行数值。

保留配置检查、preview、实投和原有双重确认/任务互斥。配置检查不启动 ROS；preview 可能启动地面应用链，现场应先配置检查。独立正赛 flight 只允许真实投递，后端拒绝伪装为 mock。

现有现场/专项卡片、低空观察三卡、日志录制下载、终端和状态保持可用。取消独立电机大页入口；/observe 保留实时位姿、电机原始输出、映射与 ESC 摘要；旧 /motor 跳转 /observe。RC OUT 是输出指令，不能等同电流/RPM；浏览器片段只记录已接收数据，不启动动作。

日志录制/索引/取回只在用户点击后调用现有脚本，下载失败或超时丢弃部分文件，没有断点续传。READY 是应用状态，飞手仍须依现场流程解锁/切 OFFBOARD/接管；保留低空观察收尾保护、舵机独立确认和 probe watchdog 边界。

投递/H参数面板现在支持读取现有配置：连接板端后打开面板自动填入，支持重新读取，区分原配置、默认值和本机覆盖；只保存修改的字段。来源与H位置范围可展开查看。未连接或读取失败时明确提示，不以示例值代替。详见 FLIGHT_PARAMETER_READ.md。

2026-10-13：模块04/08新增“地图调整航点”，可点击布点、拖动或手工输入XY/走廊AGL。保存后启用本机坐标草稿并自动生成命令预览，配置检查/preview/flight沿用原坐标覆盖流程生成独立现场文件，无需手动导出复制YAML。刷新自动恢复草稿，按板端/工程/任务组隔离；“使用原现场配置”可停用。任务运行期间禁止应用。详情见 WAYPOINT_EDITOR.md。

2026-10-13：bag 下载到本机时自动命名为 `MMDD-HHMM-投递H水平模式D下降模式-H降落水平模式D下降模式.bag`，例如 `1013-1530-投递H2D1-H降落vhD2.bag`。主页面产物下载和日志页下载使用同一规则；板端原文件名不变。模式优先读取该文件祖先目录的 run_metadata.json，独立录制已封闭 bag 则尝试读取包内 /board_trials/run_metadata；不读取其他轮次或当前 UI 选项。时间优先取所属运行目录/文件名的年月日时分秒，再使用 bag 起始时间或录制 job 时间（时间戳按北京时间显示）。缺失模式写“未知”，无法确认记录时间时保留原文件名。旧 low/high H 模式名转换为 non_vh/vh；.bag.active 保留完整后缀。非 bag 文件沿用原名，同名下载由浏览器的保存机制处理。更新后重启工作台服务并刷新页面生效。

## 2026-10-09：ULog 小工具并入工作台

日志页 `/logs` 新增本地 ULog 查看器，沿用 `tools/飞控日志小工具.zip` 的列表选取与轨迹查看思路；轨迹处理改为无需 Tk 的网页图像导出，复用已有电机/姿态/RC/电池/EKF 分析。原 ZIP 的 SSH 设置和下载目录不导入本包。

离线查看：用 `-Transport local` 启动，打开日志页，选择已完整下载的 `.ulg`（可多选，单份最大 128 MiB），点击“导入并分析”。无需 SSH、ROS 或日志 ID。本机状态目录的 `ulog_library/` 保存原文件和结果；保持同一 `-ProfileDir`，下次从“已导入/下载的 ULog”直接选择。分析在独立子进程串行执行；上次服务中断的分析显示失败，可重新导入。

可查看轨迹俯视/三维/局部高度和电机诊断图，点击图像打开原图；可下载原始 ULog、CSV、摘要及分析 ZIP。轨迹以首个有效位置为原点，NED 转 ENU，位置重置、无效位置及大于 0.5 秒间隙断线。局部位置/高度是估计值；电机是指令量。分析 ZIP 仅含派生图表和数据，原始日志通过单独按钮保存。

现场取回：连接后明确点击“查询飞控日志索引”，从返回列表选择日志，ID 自动带入，再点击“下载选中飞控日志并查看”。保持页面打开，文件封闭后自动取回本机并分析。旧取回脚本无需替换；索引辅助代码通过现有 SSH 链在板端内存中执行。只接受飞控真实 `LOG_ENTRY` ID，部分索引会提示重查；手填 ID 保留为可选入口。飞控查询/下载仍要求新鲜、已连接且未解锁状态，测试只使用 mock，未执行现场取回验收。

本次已使用已有 `board_full_mission_20261008_223632_log70.ulg` 做 WSL 与 Windows 原生离线 HTTP 上传/解析/导出验证；Windows 使用随包 pyulog 副本。真实试飞日志只作为外部测试输入，不随分发包或 Git 提交。

## 包边界

白名单打包：服务、SSH 适配、配置、网页、只读探针、启动脚本和 manifest。没有板端工程、模型、密码、私钥、个人状态或运行日志。manifest 标明源码 HEAD 和未提交文件；此包不是板端发布或实飞验收。

白名单另含 `bag_replay/run.sh`、`bag_replay.py`、`video_encoder.py` 及工具分析脚本/说明；
不打包 `merge_bags.py`、原始 bag、已有回放视频或个人库。解压后把完整结果目录放在包内
`data/`，或在 `workbench.yaml` 配置 `replay.data_roots` 的本地目录后重新启动服务；只能从
这些预定根目录选取。播放器目录需保留 `index.html`、`summary.json`、`validation.json`
和所有视频，相对资源通过目录 URL 提供，支持 HTTP Range 与拖动。渲染中或缺失视频的目录
不列为可用结果。工作台作业存于个人状态目录 `replay_library/`，可从页面查看进度与日志。
普通浏览器刷新不重启任务；服务退出中断的任务不会误报完成。

本轮 Windows 原生离线 UI/HTTP、解压启动及本机 SSH fixture 的验证结果见仓库 docs/verification/workbench_release_20261008/REPORT.md。未连接真实板端，未验收真实网络、ROS、舵机、飞行或大 bag 的现场传输。


飞行前参数新增功能：参见 [FLIGHT_PARAMETERS.md](FLIGHT_PARAMETERS.md)，板端需配套支持 `--flight-config`。

舵机角度调试已接入：重启工作台后点击顶栏「舵机角度调试」，详见 [SERVO_DEBUG.md](SERVO_DEBUG.md)。三路滑块/数字输入、板端标定预设、普通/保持输出与关闭PWM均通过现有SSH操作；板端需先部署并构建新增SetServoDuty接口。本轮没有执行实机动作。
