# Jetson AGX Orin 部署与复现记录

在远程 Jetson 上从零部署 FoundationPose（固定提交
`a1b694b83e633c2cb6115b9063d940a687759392`），并跑通官方 model-based demo。
本文件只描述 Jetson 侧。原 Windows 原生环境已于 2026-11-11 清理，版本留档在
`docs/env/conda-list-windows-20261111.txt` 与 `docs/env/pip-freeze-windows-20261111.txt`。

## 环境事实

| 项 | 实测 |
| --- | --- |
| 主机 | Jetson AGX Orin 64GB（`dianjinglab-desktop`），12 核 aarch64 |
| 系统 | Ubuntu 22.04，L4T R36.5.2（JetPack 6.2），内核 5.15.199-tegra |
| CUDA | 12.6.68（`/usr/local/cuda` → `cuda-12.6`），驱动 540.5.0 |
| 电源 | MAXN（未修改） |
| 磁盘 | NVMe 3.7 TB，可用 3.5 TB |
| Python | 系统 3.10.12；`python3.10-venv`、`python3.10-dev` 已装 |
| 编译依赖 | `build-essential`、`cmake 3.22.1`、`libboost-all-dev 1.74`、`libeigen3-dev 3.4` 已装，mycpp 不需要 conda |
| 网络 | github.com、pypi.org、`pypi.jetson-ai-lab.io/jp6/cu126` 可访问；Google Drive 与 huggingface.co 不可访问 |

Google Drive 不可访问意味着官方权重与 `demo_data` 不能直接下载。本部署改为从
Windows 侧局域网传输已有资产（来源与哈希见 `artifacts/environment/official-assets.json`）。

## 目录约定

远端全部位于 `dianjinglab` 用户家目录，未修改任何系统组件：

- `~/fdonpose/third_party/FoundationPose`：项目自身的官方源码副本，固定提交 + `patches/foundationpose-windows.patch`。
- `~/venvs/foundationpose`：Python 3.10 虚拟环境。
- `~/foundationpose-deploy/{logs,config,scripts}`：部署脚本、版本约束与日志。
- `~/fp-debug-jetson`：demo 输出（`ob_in_cam`、`track_vis`）。

## 部署步骤

Windows 侧上传补丁、版本约束与脚本：

```powershell
scp patches\foundationpose-windows.patch config\runtime-jetson.txt `
    scripts\setup\jetson_setup.sh scripts\setup\jetson_fetch_wheels.sh scripts\eval\jetson_pose_parity.py `
    scripts\probes\check_extension.py scripts\probes\check_torch_gpu.py `
    jetson_dianjinglab:~/foundationpose-deploy/staging/
```

Jetson 侧分阶段执行（可单独重跑，日志写入 `~/foundationpose-deploy/logs/`）：

```bash
export PROXY=http://127.0.0.1:7897          # 本机 Clash mixed-port，见“平台问题”第 1 条
bash ~/foundationpose-deploy/scripts/jetson_fetch_wheels.sh   # 下载并校验 torch/torchvision 轮子
bash ~/foundationpose-deploy/scripts/jetson_setup.sh repo
PROXY=$PROXY bash ~/foundationpose-deploy/scripts/jetson_setup.sh venv
PROXY=$PROXY bash ~/foundationpose-deploy/scripts/jetson_setup.sh ext
bash ~/foundationpose-deploy/scripts/jetson_setup.sh mycpp
```

- `repo`：`git checkout --force` 到固定提交后应用补丁，脚本校验恰好 5 个文件被改。
- `venv`：`/usr/bin/python3.10 -m venv`，先升级 pip，装本地 torch/torchvision 轮子、
  cuDSS 与 cuSolver 兼容垫片，最后装 `config/runtime-jetson.txt`。
- `ext`：`CUDA_HOME=/usr/local/cuda-12.6`、`TORCH_CUDA_ARCH_LIST=8.7`、`MAX_JOBS=10`，
  以 `--no-build-isolation` 从 codeload tarball 构建 pytorch3d 与 nvdiffrast。
- `mycpp`：CMake + pybind11 构建原生位姿聚类扩展。

资产传输（Windows → Jetson）：

```powershell
scp -r third_party\FoundationPose\weights third_party\FoundationPose\demo_data `
    jetson_dianjinglab:~/fdonpose/third_party/FoundationPose/
```

实测 PowerShell 的 `tar -cf - | ssh "tar -xf -"` 管道会破坏二进制流（远端 tar 报
“跳转到下一个头”），因此改用 `scp -r`。传完在 Jetson 上核对两个 `model_best.pth`
以及 `textured_simple.obj`、`cam_K.txt` 的 SHA256，均与
`artifacts/environment/official-assets.json` 一致；`demo_data` 共 2075 个文件
（rgb 737、depth 1332、masks 1），与 Windows 侧相同。

## 版本选择与理由

| 组件 | Jetson 版本 | 理由 |
| --- | --- | --- |
| torch / torchvision | 2.9.1 / 0.24.1 | `pypi.jetson-ai-lab.io/jp6/cu126` 只提供 cp310 aarch64 轮子，且没有 Windows 侧使用的 2.7.1；2.9.1 位于可用区间中部，与 pytorch3d（2026-10 提交）、nvdiffrast（2025-12 提交）时间相近。2.8.0 也可安装，但它按 numpy 1.x 编译，与 `numpy>=2` 冲突 |
| opencv | `opencv-python-headless==5.0.0.93` | 与 Windows 侧一致；**不能用 4.x**：`draw_xyz_axis` 传 `tipLength=0`，OpenCV 4.14 断言 `tipLength > 0.0` 直接崩溃 |
| PyOpenGL-accelerate | 不安装 | PyPI 无 aarch64 轮子，demo 与库调用路径不使用 |
| pytorch3d / nvdiffrast | 固定提交，源码构建 | `pypi.jetson-ai-lab.io` 无 aarch64 轮子 |
| warp-lang | 1.9.1 | 1.19.0 自带 CUDA 13.4，JetPack 6.2 驱动被判 insufficient；1.9.1 带 CUDA 12.8 工具链可正常识别 Orin |
| nvidia-cudss-cu12 | 0.8.0.10 | torch 2.9.1 的 `libtorch_cuda.so` 依赖 `libcudss.so.0`，JetPack 6.2 不自带 |
| numpy 等 | 与上游 `requirements.txt` 一致（`numpy>=2,<3`，实际 2.2.6） | Windows 侧的 conda 版本号在 PyPI 上不存在，改为按上游约束解析，并由 `artifacts/jetson/pip-freeze.txt` 冻结实际结果 |

## 平台问题与处理

部署中遇到五处平台问题，均已在 `scripts/setup/jetson_setup.sh` 中固化：

1. **Jetson 轮子源直连极慢，且不支持 HTTP Range。**
   `pypi.jetson-ai-lab.io` 直连单连接实测 20–75 KB/s，而且响应始终是
   `200 OK` + 完整 `Content-Length`，`Range` 被忽略，无法分块并行。
   改用本机已运行的 Clash mixed-port（`127.0.0.1:7897`）后达约 2 MB/s，
   228 MB 的 torch 轮子 31 秒完成。脚本用 `PROXY` 环境变量传入代理，
   并按索引页给出的 sha256 校验，代理只承担传输、不参与可信性判断。
2. **torch 2.9.1 的 `libtorch_cuda.so` 依赖 `libcudss.so.0`，JetPack 6.2 不自带 cuDSS。**
   症状是 `import torch` 直接抛 `ImportError: libcudss.so.0`。
   安装 `nvidia-cudss-cu12==0.8.0.10`（aarch64 轮子）后，把
   `nvidia/*/lib/libcudss*.so*` 软链进 `torch/lib/`，由 `RUNPATH=$ORIGIN` 解析，
   不需要在每次运行时设置 `LD_LIBRARY_PATH`。
3. **GitHub 的 git 协议在当前网络下大传输会 `GnuTLS ... TLS connection was non-properly terminated`。**
   `git clone` / `git fetch` 反复中断，改用 codeload tarball
   （`https://codeload.github.com/<org>/<repo>/tar.gz/<sha>`）下载固定提交，
   再 `pip install --no-build-isolation <解压目录>`。
4. **torch 2.9.1 的 `libtorch_cuda_linalg.so` 需要 CUDA 12.8+ 才有的
   `cusolverDnXsyevBatched*`，JetPack 6.2 的 cuSolver 11.6.4.69 没有这两个符号。**
   症状是任何 `torch.linalg` 调用（FoundationPose 的 `tf_to_crops.inverse()`）抛
   `Error in dlopen ... undefined symbol: cusolverDnXsyevBatched_bufferSize`。
   先试过装 PyPI 的 cuSolver 11.7.5（CUDA 12.9），dlopen 能过但
   `cusolverDnCreate` 在 CUDA 12.6 驱动上返回 `INTERNAL_ERROR`，因此回退到系统
   cuSolver，并编译一个只定义这两个符号的兼容垫片
   `libcusolver_jetpack_compat.so`（带 `libcusolver.so.11` 版本脚本），
   通过 venv 内的 `.pth` 在解释器启动时 `RTLD_GLOBAL` 预加载。
   FoundationPose 只用 `inv`/`solve`，不调用 batched eigh，垫片不会被真正执行。
5. **OpenCV 4.14 的 `arrowedLine` 断言 `tipLength > 0.0`，而 `draw_xyz_axis` 传 0。**
   OpenCV 5.0.0.93 接受该参数并正常绘制，因此固定 5.0.0.93，与 Windows 侧一致。

mycpp 直接用系统 `libeigen3-dev`、`libboost-all-dev`、`libomp` 和 venv 内的
pybind11 构建，不需要 conda 的 `eigen`/`boost-cpp` 包。

## 验证与复现

```bash
PY=~/venvs/foundationpose/bin/python
E=~/foundationpose-deploy/evidence
cd ~/fdonpose/third_party/FoundationPose
$PY check_env.py --demo-data
$PY ~/foundationpose-deploy/scripts/check_torch_gpu.py --expect-torch 2.9.1 \
    --expect-torchvision 0.24.1 --output "$E/torch-gpu.json"
$PY ~/foundationpose-deploy/scripts/check_extension.py pytorch3d \
    --foundationpose-dir ~/fdonpose/third_party/FoundationPose --output "$E/pytorch3d.json"
# nvdiffrast / warp / mycpp 同理
$PY run_demo.py --headless --debug 1 --debug_dir ~/fp-debug-jetson
# 出可视化图（3D 框 + 坐标轴），再编码视频：
$PY run_demo.py --headless --debug 2 --debug_dir ~/fp-debug-jetson-vis
ffmpeg -y -framerate 30 -pattern_type glob -i '~/fp-debug-jetson-vis/track_vis/*.png' \
    -c:v libx264 -pix_fmt yuv420p -crf 20 -movflags +faststart ~/demo-jetson.mp4
$PY ~/foundationpose-deploy/scripts/jetson_pose_parity.py \
    --reference ~/pose-ref-win/ob_in_cam --candidate ~/fp-debug-jetson/ob_in_cam \
    --output "$E/pose-parity.json"
```

## 实测结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Python / torch / torchvision | 3.10.12 / 2.9.1 / 0.24.1 | `artifacts/jetson/pip-freeze.txt` |
| 扩展 | pytorch3d 0.7.9、nvdiffrast 0.4.0、warp 1.9.1、mycpp（aarch64） | `artifacts/jetson/*.json` |
| CUDA 实算 | CUDA 12.6 + Orin sm_87，torch 矩阵乘与 torchvision NMS 通过 | `artifacts/jetson/torch-gpu.json` |
| 扩展实算 | pytorch3d CUDA kNN、nvdiffrast CUDA 光栅化（128 像素）、warp CUDA 前缀和、mycpp 位姿聚类全部通过 | `artifacts/jetson/{pytorch3d,nvdiffrast,warp,mycpp}.json` |
| 环境自检 | `check_env.py --demo-data` 退出码 0，权重与样例就位 | `artifacts/jetson/check-env.log` |
| 官方 demo | mustard0 全 737 帧完成，生成 737 个位姿文件；headless、`--debug 1`；耗时 142 s（复跑 139 s），约 0.19 s/帧 | `artifacts/jetson/demo.log`、`deploy.json` |
| 重复性 | Jetson 两次运行逐帧比对：平移最大偏差 0.000 m，旋转最大偏差 0.051°，基本确定 | `artifacts/jetson/pose-parity-r1-r2.json` |
| 与 Windows 一致性 | 逐帧全部匹配；平移最大 1.65 mm、均值 0.72 mm；旋转最大 2.06°、均值 0.63°；首帧 1.26 mm / 1.28° | `artifacts/jetson/pose-parity.json` |
| 可视化 | `--debug 2` 生成 737 张 640×480 的 3D 框 + 坐标轴叠加图（298 s），用 Jetson 自带 ffmpeg 编码为 30 fps、737 帧、1.23 MB 的 mp4 | `artifacts/jetson/demo-jetson-visual.mp4`、`demo-jetson-frame-*.png` |

与 Windows 的偏差略高于最初的 1 mm 预期，原因是两边的深度预处理路径不同：Windows 侧
warp 内核因 NVRTC 找不到 `builtin.h` 一直走**未滤波深度回退**（已记录在
`artifacts/environment/progress-final-20261106.json`），Jetson 侧 warp 1.9.1 正常执行
双边/腐蚀滤波。Jetson 自身两次运行几乎完全一致，说明差异是系统性的环境差异，而不是
Jetson 侧的不稳定。该偏差量级（亚 2 mm / 约 2°）与一次未滤波深度输入的位姿精化差异相当，
不构成精度结论。

汇总见 `artifacts/jetson/deploy.json`。

## 已知限制

- Google Drive 不可访问，只复现 `demo_data/mustard0`；driller 等其它官方场景未下载。
- 只覆盖模型基（model-based）推理路径；model-free 的 BundleSDF/Kaolin 路径不在范围内。
- `--debug 2` 的 scorer 可视化在 OpenCV 5 上会因 `putText` 断言 `img.depth() == CV_8U` 崩溃
  （Windows 侧早已记录同一问题）。已在共享补丁的 `cv_draw_text` 中加入非 uint8 画布的兼容转换，
  修复后 debug2 正常出图；`pose-parity-debug1-vs-debug2.json` 证明两种模式位姿完全一致
  （平移差 0，旋转差 ≤0.051°）。
- 与 Windows 的结果比对是两次运行之间的一致性检查，不是绝对位姿精度评估（无 6D 真值）。
- cuSolver 兼容垫片只补 `cusolverDnXsyevBatched*`；若将来有代码调用 batched eigh，会明确 abort，
  不会静默给出错误结果。
