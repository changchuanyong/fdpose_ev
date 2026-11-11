# patches

上游适配补丁。目标仓库与固定提交见 `config/upstream.json`。

| 补丁 | 目标 | 改动文件 | 用途 |
| --- | --- | --- | --- |
| `foundationpose-windows.patch` | FoundationPose `a1b694b8` | 5 个：`Utils.py`、`estimater.py`、`mycpp/CMakeLists.txt`、`mycpp/include/Utils.h`、`run_demo.py` | warp 内核缓存目录可配置、CUDA targets 头文件回退等平台适配；Windows 原生环境需要，Jetson 部署复用同一补丁 |

手工应用：

```bash
cd third_party/FoundationPose
git apply ../../patches/foundationpose-windows.patch
```

Jetson 侧由 `scripts/setup/jetson_setup.sh repo` 自动应用，并校验恰好 5 个文件被修改。
该补丁是上游的衍生修改，再分发约束见 [NOTICE.md](../NOTICE.md)。
