# 飞行前投递与 H 降落参数

重启工作台服务并刷新页面后，模块01/02/05/06/08显示投递参数，模块03/04/08显示H参数；独立正赛同时显示两组。记忆、拍摄和低空观察不提供这些参数。

1. 点击任务卡片的“投递 / H 降落参数”。所有选项默认“继承原配置”，数字留空表示继承；示例是输入提示，不是当前板端有效值。
2. 投递可选择水平补偿模式1/2、下降模式1/2/3/4；配置FC中心离地目标高度、释放高度上下限、下降速度以及模式4加速/制动参数。释放上下限须一起填写，且下限 ≤ 目标高度 ≤ 上限。投递XY仍由视觉靶心及机构杆臂补偿确定。
3. H可选择non_vh/vh水平对准、下降模式1/2/3/4、末段交接和下降速度。模式4自动选OFFBOARD；vh要求POSCTL或OFFBOARD。H坐标、目标高度和位置容差保持所选现场/航点配置。
4. 点击“保存并生成命令”，只向本机命令API提交参数，不连接飞机，不启动节点。草稿保存在当前浏览器localStorage，按板端地址、工程目录、现场目录、任务组及源文件隔离。刷新后草稿保留；换浏览器不会自动迁移。修改速度/实投选项或航点后，点击“生成参数命令”重新生成预览。
5. 使用现有“配置检查（不启动节点）”核对有效参数，随后按原preview/flight流程启动。飞行确认和实投确认仍沿用原流程。参数修改会清除此前飞行确认；任务运行中不允许应用参数。
6. “继承原飞行参数”停用并删除本浏览器的本组参数草稿。航点草稿独立保留。

本机生成命令将参数写入板端工程的独立 `logs/flight_workbench/flight_overlays/*.yaml`，启动入口通过 `--flight-config` 读取。源settings/site文件不被覆盖。参数在现场几何与速度档之后叠加，避免正赛速度档重新覆盖人工设置的投递高度；嵌套参数保留未修改值。最终设置仍经过原工程校验与配置生成，非法模式配对、高度范围和越界参数会拒绝启动。

正常释放按所选高度窗口执行。当前控制器已有的20秒下降超时兜底会绕过XY和高度限制；本功能不修改该兜底逻辑，原许可、身份绑定及有效反馈仍须满足。配置窗口不代表所有超时路径的绝对释放边界。

## 板端配套

工作台增加了启动参数，旧板端入口必须先同步配套Python改动。工作台不会自动更新板端工程。未同步时会明确报“板端入口尚未支持飞行参数”，不会继续启动。

本工作台附 `board_parameter_patch/`，含以下同路径文件：

- `deployment/board_trials_4x4/common/uav_board_trials/scripts/run_trial.py`
- `patrol_uav_ws-patrol_planner/src/uav_mission/scripts/competition_supervisor.py`
- `patrol_uav_ws-patrol_planner/src/uav_mission/src/uav_mission/flight_settings.py`

这些文件来自本次本地liftrace-controlwork工程。同步前须确认板端代码版本一致；不同分支应合入 `--flight-config` 及参数验证改动，避免用整文件覆盖其独立改动。仅Python配置入口变化，无飞行控制C++改动。本轮未部署、未飞行。

## 验证

工作台Python回归37项：36通过、1项旧航点源码路径检查因其历史路径不存在而跳过。7项新增测试全部通过，覆盖非法类型/范围、模块权限、H模式4配对、现场与速度覆盖顺序、真实配置生成、命令API、不可变覆盖文件与旧入口兼容拒绝。

前端DOM契约检查通过，覆盖模式4联动、保存、三种命令生成、浏览器草稿、板端隔离及恢复继承；JavaScript语法检查通过。这是DOM契约检查，未进行真实浏览器视觉验收。

验证命令（Python环境需有yaml和numpy，生产源码测试用LIFTRACE_SOURCE_ROOT定位）：

```bash
LIFTRACE_SOURCE_ROOT=/实际路径/liftrace-controlwork python -m unittest discover -s tests -v
node tests/flight_settings_ui_smoke.js
```
