# 远端设备资源监视

主页“状态监视”中，在阶段状态卡之后、“自动任务”之前新增“远端资源占用”。只读数据沿用现有board_probe.py、SSH和SSE遥测，不启动新远端控制服务，不调整设备频率、不安装依赖或修改读取权限。

## 指标与显示

- CPU：根据/proc/stat两次采样差值计算全机平均占用，第一帧为采样中；保留每核心数据供后续扩展，不重复累计guest时间。
- GPU：读取Rockchip/Mali的devfreq load或utilisation/utilization。只采用负载数值，不把频率或频率档位当作占用率。
- NPU：优先读取/sys/kernel/debug/rknpu/load，兼容/proc/rknpu/load及devfreq接口。多核心显示平均负载及各核心百分比；正确区分0%与不可读。
- 内存：MemTotal-MemAvailable，显示已用/总量及百分比；显示存在的Swap。旧内核仅在有可用基础字段时估算可用内存。
- 磁盘：根分区、工程目录所在分区及/dev来源的物理挂载；按设备去重，排除内存文件系统和snap镜像。显示已用/总量及百分比，容量每10秒刷新。GB采用十进制10^9字节。
- 网络：各活动非lo网卡收发字节计数的差值，显示接收/发送Mb/s；驱动可提供有线链路速率时同时显示。无线速率不可读时仍显示实际收发速率；不将不同接口加总，以免桥接/虚拟接口重复计数。链路速率不是互联网测速结果。

采样默认约1Hz，独立线程避免文件系统或驱动读取拖慢ROS探针。资源显示不要求ROS master已启动。数据超过3秒或SSH断开后隐藏旧值并显示过期/未连接；驱动未提供指标或当前用户无读取权限则显示不可读，悬停可查看原因。

## 使用与验证

重启工作台后端并重新连接板端，使新版单文件探针上传并启动，然后强制刷新主页。旧探针缺少resources字段时显示升级提示；仅刷新网页不会升级仍在运行的远端探针。

NPU debugfs可能仅允许管理员读取。工作台不自动提权或修改权限；需由板端管理员确认驱动已启用，并按现场权限策略提供只读负载接口。不可读不能解释为设备不存在或负载为0。

新增离线回归覆盖CPU/网络差值与计数器重置、内存/磁盘容量、GPU格式、NPU多核心与零值、缺失指标、ROS master缺失时资源数据保留，以及页面容量/速率格式、断连和过期。测试不连接板端、不编译、不运行ROS或硬件；未做实机资源验收。

## 驱动格式依据

- [Rockchip devfreq load实现](https://github.com/rockchip-linux/kernel/blob/develop-6.1/drivers/devfreq/devfreq.c)：输出百分比@频率Hz。
- [Rockchip RKNPU load实现](https://github.com/rockchip-linux/kernel/blob/develop-6.1/drivers/rknpu/rknpu_debugger.c)：单核百分比或CoreN百分比；部分版本0值可能以空白精度格式输出。
