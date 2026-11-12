# fdonpose

在 Jetson AGX Orin 上估计充电口的 6D 位姿。实时入口使用 RealSense D415 获取 RGB-D，YOLO 给 SAM2.1 提供首帧检测框，FoundationPose 根据分割轮廓初始化并跟踪。

## 快速启动

在已部署的 Jetson 上接好 D415 和显示器，在桌面终端运行下面的命令。首次部署见 [Jetson 安装与验证](docs/jetson_setup.md)。

```bash
bash ~/fdonpose/scripts/run_d415.sh
```

[启动脚本](scripts/run_d415.sh) 默认使用这台 D415 的 SDK 序列号 `349222063070`，从项目目录读取模型、坐标配置和权重，并打开桌面窗口持续跟踪。按 **Q** 或 **Esc** 退出。

| 用途 | 参数 |
| --- | --- |
| 默认取流 | 640×480、30 fps |
| 以 720p 采集 | 追加 `--stream-width 1280 --stream-height 720` |
| 更换 D415 | 追加 `--serial <SDK 序列号>` |
| 按官方默认迭代次数初始化 | 追加 `--est-refine-iter 5`，本项目默认 3 轮 |

窗口显示 `Aim at the socket` 时，让充电口正面及四个安装角完整入镜。出现 `Socket clipped` 时，把充电口移离画面边缘。

如果 `FileNotFoundError` 指向 `~/ev-charging-d415/`，请改用上面的启动脚本。YOLO 权重位于 `~/fdonpose/weights/best.pt`，SAM2 权重位于 `~/fdonpose/weights/sam2.1_hiera_small.pt`。

## 运行与输出

应用将深度对齐到彩色画面。首帧初始化后，FoundationPose 每帧精化 2 轮，窗口显示 3D 框和 XYZ 坐标轴。首个跟踪帧、之后约每 0.6 秒以及姿态突变时，都会核对投影、检测框和模型表面深度。只有完整复核通过的位姿才用于恢复缓存。失配时窗口撤掉位姿框，先尝试从最后确认位姿恢复，失败后重新检测、分割并注册。

结果保存在 `artifacts/d415-live-*`。网格 `socket_mod.PLY` 与 `config/geometry/socket_openings_ply.json` 配套使用，后者定义从网格坐标到充电口目标坐标的变换。

| 文件 | 内容 |
| --- | --- |
| `poses.jsonl` | 输出帧的 `T_camera_target_m`，将目标坐标转换到相机光学坐标，平移单位为米 |
| `initial_mask.jpg` | 首次通过注册检查的 SAM2 掩膜叠加图 |
| `first_pose.jpg`、`last_pose.jpg` | 首尾位姿叠加图 |
| `summary.json` | 首帧注册耗时、实际跟踪帧率和恢复、重置次数 |
| `drift/<帧号>/` | 复核失配时的前后 RGB-D、内参、候选/恢复位姿及验证指标 |

可用 `scripts/eval/replay_drift.py <漂移目录> --output <结果.json>` 回放同一段输入；默认在原生分辨率和 640 像素宽度下分别跟踪、复核并计时。

## 实测结果

| Jetson 测试 | 结果 |
| --- | --- |
| D415 实物充电口，1280×720，桌面窗口 | 首帧 5 轮注册约 10.1 s。连续输出 60 个跟踪位姿，约 5.9 fps。15 次投影检查通过，首尾叠加图贴合充电口 |
| 同帧注册对照，640×480，同一组 RGB-D 和 SAM2 掩膜 | 5 轮约 6–7 s，3 轮约 4.4 s，2 轮约 3.6 s。相对实时脚本的 5 轮结果，3 轮最大差异约 0.12 mm / 0.28°，2 轮最大旋转差约 1.83° |
| FoundationPose 官方 `mustard0` 序列 | 737/737 帧，单次耗时 139–142 s，见 [Jetson 验证记录](docs/jetson_setup.md#实测结果) |

同帧对照衡量不同设置之间的位姿差异。绝对 6D 精度与实物插装仍待独立验证。实物窗口与同帧对照的报告目录分别为 `d415-sam2-final-20261111-163114` 和 `d415-official-compare-20261111-172556`，位于实验环境的 `artifacts/` 下。

## 文档与目录

- [Jetson 安装与验证](docs/jetson_setup.md) · 从零部署、固定版本、平台问题和官方样例复现
- [充电口离线回放](docs/charging_replay.md) · 从 `robot-ev-charging` 数据记录运行 YOLO、SAM2 和 FoundationPose
- [标定板 v2](docs/tag_mount.md) · 双 M6 螺栓安装、两孔试装件和打印说明
- [Windows 原生验证归档](docs/env/windows-validation-20261105.md) · 历史环境、验证数据和编译排障
- [文档索引](docs/index.md) · [上游归属与许可](NOTICE.md)

```text
apps/        实时应用
scripts/     setup/ 部署 · pipeline/ 回放 · eval/ 评估 · probes/ 环境探针
config/      运行时约束、上游版本和几何配置
assets/      mesh/ 网格模型 · print/ 打印件
docs/        部署、流程和历史记录
patches/     上游适配补丁
tests/       冒烟测试
```

`third_party/` 的上游源码按 [固定版本清单](config/upstream.json) 部署，运行输出写入 `artifacts/`。两者按 `.gitignore` 管理。适配补丁见 [patches/README.md](patches/README.md)。

