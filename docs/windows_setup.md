# Windows 原生部署与验证记录

系统安装已获用户确认。VS 2022／MSVC 14.38／SDK 22621 安装成功，
原生 C++ 测试通过；补齐 C++ 基础工具的修改安装当前等待 Windows UAC。
只对本任务实例 `C:\BuildTools\Fdonpose` 操作。

## 安装范围

使用已校验的微软 VS 2022 Build Tools 引导程序，新建独立实例：

`C:\BuildTools\Fdonpose`

原计划的 Program Files 下长目录在 2026-11-05 的实际安装中被拒绝，
日志明确报告“此产品的根安装路径太长”。此次失败没有创建新实例；
改用以上短目录，组件清单不变。

仅选择以下组件及安装器要求的依赖，完整组件 ID 在
`config/windows-build-tools.vsconfig`：

- MSVC v143 14.38 x64/x86 工具集。
- Windows SDK 10.0.22621.0。
- 官方 C++ 基础工具组件 `Microsoft.VisualStudio.Component.VC.Tools.x86.x64`，
  提供 NVCC 所需的 `vcvars` 初始化文件；其默认工具集作为依赖安装，
  本项目的编译启动脚本仍明确选择 14.38。

不使用已有 VS 2026 实例作为安装目标。此阶段不安装 CUDA 系统驱动，
不创建 WSL、不修改现有 Conda 环境。后续 CUDA 12.8 优先安装在项目独立环境中。

影响：需要管理员权限、软件下载和磁盘空间；微软安装器可能维护共享安装器服务、
注册表与组件缓存。`--norestart` 禁止自动重启；返回 3010 时记录待重启状态。
原有 VS 2026 实例、现有 Python 环境和原视觉工程均保留。

## 安装包来源与校验

- 官方入口：<https://aka.ms/vs/17/release/vs_BuildTools.exe>
- 本地文件：`artifacts/installers/vs_BuildTools_2022.exe`
- 文件大小：4,473,832 字节。
- SHA256：`972d771c33c2887b13900c2052e5d2e88208531f6d5ee3c4405d7648e853009b`
- Authenticode：`Valid`，发布者 Microsoft Corporation。

安装脚本在启动前重新检查签名、哈希、组件清单和目标路径。
如果目标路径已存在则拒绝执行，避免修改既有实例。

```powershell
# 当前可以执行：只显示参数，不修改系统
powershell -NoProfile -File scripts/install_build_tools.ps1

# 仅在明确批准本步骤后，从管理员 PowerShell 执行
powershell -NoProfile -File scripts/install_build_tools.ps1 -Install
```

## 安装后的验收和回滚

1. 保存安装前后 VS 实例清单和安装返回码到新的诊断目录。
2. 安装器失败时，脚本尝试卸载本次新建的 FdonposeBuildTools 实例；
   使用微软卸载流程，不手动删除系统目录或共享组件。
3. 回滚失败时保留日志并明确报告待清理项，不声称系统已恢复。
   微软安装器自身的共享维护记录可能保留。
4. 安装成功后重新运行 `check_environment.cmd`，确认 MSVC 和 SDK 文件。
5. 随后进行真实 C++ 编译与 CUDA 扩展验证；文件存在和安装器成功均不代替构建测试。

## 后续环境步骤

- Conda 命令必须在本次进程设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`。
  一次 CUDA 安装因 GBK 解码失败留下了残缺环境，已清理并用 UTF-8 成功重建。
- 构建工具固定为 pip 的 CMake 3.31.6、Ninja 1.11.1.4；通过
  `scripts/with_build_env.cmd` 选择这些可执行文件。Conda 新版组合在实际探测中失败。
- 在 `.runtime/foundationpose` 创建独立 Python 3.11 环境。
- 使用 PyTorch 2.7.1、torchvision 0.22.1 的 cu128 版本和配套 CUDA 12.8 构建依赖。
- 分别运行 GPU 运算、PyTorch3D CUDA 算子、nvdiffrast 光栅化、Warp 核函数、mycpp 位姿聚类检查。
- mycpp 需要按 MSVC 适配 GCC 参数、POSIX 头文件、数学常量与模块输出位置；
  官方样例的 Unix 输出目录命令也需要适配。所有改动记录为针对固定提交的补丁。
- SAM 2 仅关闭可选 CUDA 后处理扩展，主分割模型仍使用 GPU。
- 官方样例实际通过后再冻结版本；随后实现充电口离线与实时流程。
- 必要扩展失败则停止该阶段并记录原因，清理本次失败环境；不会自动切换 WSL 或绕过编译器检查。

## 依据

- [CUDA 12.8 Windows 编译器要求](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-installation-guide-microsoft-windows/index.html)
- [微软 Build Tools 组件 ID](https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-build-tools?view=vs-2022)
- [PyTorch 官方历史版本组合](https://pytorch.org/get-started/previous-versions/)
- [SAM 2 可选扩展说明](https://github.com/facebookresearch/sam2/blob/main/INSTALL.md)
