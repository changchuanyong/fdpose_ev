# fdonpose

Windows 原生 FoundationPose 充电口视觉工程，目标相机为 D435，兼容 D415。

**当前状态：Windows 原生 FoundationPose、SAM2、官方样例和充电口首帧回放已通过。**
真实相机验收和绝对位姿精度仍未完成。

## 已完成

- FoundationPose 官方源码下载到 `third_party/FoundationPose`，固定提交
  `a1b694b83e633c2cb6115b9063d940a687759392`。Windows 适配保存在
  `patches/foundationpose-windows.patch`，mycpp 已编译并验证。
- 官方 refiner/scorer 权重和 mustard0 样例保存在 `third_party/FoundationPose`，
  来源、哈希和 ZIP CRC 见 `artifacts/environment/official-assets.json`。
- 项目环境自检入口、候选 Conda 配置、上游来源清单。
- VS 2022 编译工具的组件清单、安装预览和失败回滚脚本。
- VS 2022 独立实例已安装到 `C:\BuildTools\Fdonpose`，MSVC 14.38 和 SDK 22621
  已完成真实 C++ 编译、链接、运行测试。原 VS 2026 保留。
- 独立 Python 3.11、PyTorch CUDA、CUDA Toolkit 和 Python 依赖已安装。
- PyTorch CUDA 矩阵运算、torchvision CUDA NMS、Warp GPU 运算、mycpp 位姿聚类通过。
- PyTorch3D 和 nvdiffrast CUDA 扩展已构建并通过实际 GPU 算子检查。
- SAM2 官方源码已在当前 Windows 环境以关闭可选 CUDA 后处理扩展的方式安装，
  SAM2.1 Hiera Small 框提示分割通过。
- FoundationPose 官方 mustard0 demo 以 headless debug1 跑完 737 帧，生成 737 个位姿文件。
- 远程 Jetson AGX Orin（JetPack 6.2 / CUDA 12.6 / aarch64）完成同一套部署，官方
  mustard0 demo 737 帧跑通（142 s，约 0.19 s/帧），扩展检查和环境自检全部通过；
  过程与平台问题见 `docs/jetson_setup.md`，证据在 `artifacts/jetson/`。
- `scripts/charging_replay.py` 已接入原工程 RGB、Z16 深度、相机内参、深度到彩色外参、
  YOLO 检测、SAM2 框提示分割和 FoundationPose 初始化；SAM2 首帧输出见
  `artifacts/charging-replay-sam2-20261106-r4.jsonl`。

## 实测状态（2026-11-05）

| 检查 | 结果 |
| --- | --- |
| GPU 驱动查询 | RTX 5080，16303 MiB，驱动 610.88 |
| Conda | 已找到，版本 26.5.3 |
| 现有 MSVC | 14.51；VS 2026 实例状态为安装不完整 |
| MSVC 14.38／Windows SDK 22621 | 已安装，原生 C++ 测试通过 |
| 项目 Python／CUDA 环境 | Python 3.11.18、PyTorch 2.7.1+cu128、CUDA Toolkit 12.8.1 |
| PyTorch／torchvision | 实际 GPU 运算通过 |
| Warp／mycpp | 实际 GPU 前缀和／原生位姿聚类通过 |
| NVCC 编译与运行 | 通过；Windows C++ 基础组件已补齐 |
| PyTorch3D／nvdiffrast | 构建和实际 GPU 算子通过 |
| 官方样例 | mustard0 headless debug1，737/737 帧完成 |
| 充电口离线首帧 | YOLO → SAM2.1 small → FoundationPose 通过；不是精度验收 |
| D435／D415 实机 | 未测试；离线记录来自 D415 |

最新状态见 `artifacts/environment/progress-final-20261106.json`；关键证据：
`torch-gpu-after-utf8-rebuild-20261105.json`、`warp-gpu-20261105.json`、
`mycpp-runtime-20261105.json`，均位于 `artifacts/environment/`。

CUDA 安装曾触发 Conda 的 GBK 解码错误并留下残缺元数据；失败环境已清理，
在进程内启用 UTF-8 后已成功重建。CMake 4.4／Ninja 1.13 的编译探测失败；
改用 pip 安装的 CMake 3.31.6／Ninja 1.11.1.4 后，mycpp 构建通过。

## Jetson 部署（2026-11-06）

`jetson_dianjinglab`（AGX Orin 64GB，JetPack 6.2，CUDA 12.6，aarch64）已从零部署成功，
全部位于用户家目录，未修改系统组件：

| 项 | 结果 |
| --- | --- |
| 环境 | Python 3.10 venv，torch 2.9.1 / torchvision 0.24.1（NVIDIA Jetson 轮子） |
| 扩展 | pytorch3d 0.7.9、nvdiffrast 0.4.0、warp 1.9.1、mycpp，全部真实 GPU 算子通过 |
| 官方样例 | mustard0 headless debug1，737/737 帧，142 s（复跑 139 s） |
| 与 Windows 一致性 | 737 帧全部匹配；平移最大 1.65 mm、旋转最大 2.06°（Windows 侧走未滤波深度回退） |
| Jetson 重复性 | 两次运行平移完全一致，旋转最大 0.051° |
| 可视化 | `--debug 2` 出 737 张 3D 框/坐标轴叠加图，ffmpeg 编码为 737 帧、30 fps 的 mp4 |

复现入口：`scripts/jetson_fetch_wheels.sh`、`scripts/jetson_setup.sh`、
`config/runtime-jetson.txt`；步骤、版本理由和五个平台问题见
`docs/jetson_setup.md`，证据在 `artifacts/jetson/`。

演示材料（Jetson 上直接产出）：[demo-jetson-visual.mp4](artifacts/jetson/demo-jetson-visual.mp4)
（640×480、30 fps、737 帧）和关键帧
[demo-jetson-frame-000000.png](artifacts/jetson/demo-jetson-frame-000000.png)、
[demo-jetson-frame-000480.png](artifacts/jetson/demo-jetson-frame-000480.png)、
[demo-jetson-frame-000736.png](artifacts/jetson/demo-jetson-frame-000736.png)。

```powershell
# 无依赖自检；缺少前置条件时返回非零退出码
.\check_environment.cmd

# 保存一份新报告（不覆盖已有报告）
.\check_environment.cmd --output artifacts/environment/my-check.json

# 使用固定的 VS 2022／CUDA 工具链执行构建命令（环境变量仅作用于子进程）
.\scripts\with_build_env.cmd cmake --version
```

## 下一步

离线回放命令示例：

```powershell
$record = Get-ChildItem ..\robot-ev-charging\dataset\vision\records\*.json | Select-Object -First 1 -ExpandProperty FullName
.\scripts\with_build_env.cmd python scripts\charging_replay.py `
  --record "$record" `
  --weights "..\robot-ev-charging\runs\detect_split_20261104T141428Z_0ba4dbaf\weights\best.pt" `
  --mesh assets\插座改.STL `
  --mask-mode rectangle `
  --output artifacts\charging-replay.jsonl
```

`rectangle` 只验证 RGB-D、模型、坐标和 FoundationPose 链路；它不是目标分割。
`--mask-mode sam2` 使用当前工程内的 SAM2.1 small checkpoint；缺少 checkpoint 时会明确失败，
不会静默退回矩形框。

目标业务链路为 YOLO → SAM2 → FoundationPose，当前已在 Windows 原生环境跑通。
SAM2 安装时关闭了可选 CUDA 后处理扩展，主分割推理仍使用 RTX 5080 CUDA。
原 `robot-ev-charging` 仅作为数据、模型和几何定义的只读来源；本工程只复制了 CAD STL。
项目不驱动机械臂，不包含物理插装验收结论。

`environment.windows.yml` 和 `config/runtime-constraints.txt` 仍是候选配置，不是完整发布锁。
Warp 深度滤波在当前 Windows/Conda 组合中无法通过 NVRTC 找到 `builtin.h`，
FoundationPose 回放记录了明确的未滤波 CUDA 深度回退；Warp 独立 prefix-sum 检查仍通过。
上游许可证保留在 `third_party/FoundationPose/LICENSE`。

