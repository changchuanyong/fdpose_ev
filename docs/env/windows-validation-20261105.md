# Windows 原生验证归档

本页记录 2026-11-05 至 2026-11-06 的 Windows 原生部署与回放。该项目环境于 2026-11-11 清理，版本见 [Conda 清单](conda-list-windows-20261111.txt)、[pip 清单](pip-freeze-windows-20261111.txt) 和 [运行时约束](runtime-constraints-windows.txt)。

## 环境与构建

- FoundationPose 固定在 `a1b694b83e633c2cb6115b9063d940a687759392`，Windows 适配见 [补丁](../../patches/foundationpose-windows.patch)。mycpp 已编译并运行验证。
- 历史部署包含环境自检入口、候选 Conda 配置、上游来源清单，以及 VS 2022 组件清单、安装预览和失败回滚脚本。
- VS 2022 独立安装到 `C:\BuildTools\Fdonpose`。MSVC 14.38 与 Windows SDK 22621 通过原生 C++ 编译、链接和运行，机器同时保有原 VS 2026 实例。
- 当时安装了独立 Python 3.11 环境、PyTorch CUDA 和 CUDA Toolkit。SAM2 安装关闭了可选的 CUDA 后处理扩展，SAM2.1 Hiera Small 的分割推理在 RTX 5080 CUDA 上通过。

## 验证结果

| 检查 | 历史结果 |
| --- | --- |
| GPU | RTX 5080，16,303 MiB，驱动 610.88 |
| Conda | 26.5.3 |
| 现有 MSVC | 14.51，VS 2026 实例当时未安装完整 |
| 独立 C++ 工具链 | MSVC 14.38、Windows SDK 22621，原生 C++ 测试通过 |
| Python / CUDA | Python 3.11.18、PyTorch 2.7.1+cu128、CUDA Toolkit 12.8.1 |
| PyTorch / torchvision | CUDA 矩阵运算与 GPU NMS 通过 |
| Warp / mycpp | GPU 前缀运算与位姿聚类通过 |
| NVCC | 编译和运行通过 |
| PyTorch3D / nvdiffrast | 构建与 GPU 算子检查通过 |
| FoundationPose 官方样例 | `mustard0` 无窗口运行完成 737/737 帧，生成 737 个位姿 |
| 充电口离线首帧 | YOLO → SAM2.1 Small → FoundationPose 输出位姿。数据来自 D415，Windows 验证阶段尚未进行实机取流和精度验收 |

官方 refiner、scorer 权重与 `mustard0` 的来源、哈希和 ZIP CRC 见历史产物 `artifacts/environment/official-assets.json`。
环境和算子证据见 `artifacts/environment/` 下的 `progress-final-20261106.json`、`torch-gpu-after-utf8-rebuild-20261105.json`、`warp-gpu-20261105.json` 和 `mycpp-runtime-20261105.json`。

充电口回放读取原工程的 RGB、Z16 深度、相机内参与深度到彩色外参，使用复制的 CAD STL。分割和位姿输出见 `artifacts/charging-replay-sam2-20261106-r4.jsonl`。入口与样例见 [离线回放](../charging_replay.md)。

## 排障记录

- 安装 CUDA 时，Conda 的 GBK 解码失败并留下残缺元数据。清理失败环境后，在进程内启用 UTF-8 并重建成功。
- CMake 4.4 与 Ninja 1.13 的编译探测失败。改用 CMake 3.31.6 与 Ninja 1.11.1.4 后，mycpp 构建通过。
- Warp 在该 Windows/Conda 环境中通过 NVRTC 编译深度滤波时找不到 `builtin.h`。FoundationPose 回放记录使用未滤波 CUDA 深度，Warp 独立前缀运算仍通过。

后续 Jetson 部署和跨平台位姿对照见 [Jetson 验证记录](../jetson_setup.md)。
