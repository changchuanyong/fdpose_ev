# 充电口离线回放

`scripts/pipeline/charging_replay.py` 从原 `robot-ev-charging` 图库读取已绑定的 RGB、原始 Z16 深度和标定文件。
它会校验 RGB／深度文件哈希，使用深度相机内参和深度到彩色外参把深度投影到彩色分辨率，
调用当前 YOLO 权重生成目标框，再把显式掩膜交给 FoundationPose。

项目 STL 按原工程约定解释为毫米，加载时转换为米。输出矩阵是 `T_camera_target`，
表示目标坐标转换到相机光学坐标；平移单位为米。输出 JSONL 中 `status=valid_algorithm_result`
只表示算法调用产生了矩阵，不表示标定、几何或插装精度已经验收。

```powershell
$record = Get-ChildItem ..\robot-ev-charging\dataset\vision\records\*.json | Select-Object -First 1 -ExpandProperty FullName
python scripts/pipeline/charging_replay.py `
  --record "$record" `
  --weights "..\robot-ev-charging\runs\detect_split_20261104T141428Z_0ba4dbaf\weights\best.pt" `
  --mesh assets\mesh\socket_mod.STL `
  --mask-mode rectangle `
  --output artifacts\charging-replay.jsonl
```

当前 `sam2` 模式使用 YOLO 框提示 SAM2.1 Hiera Small 生成像素掩膜；
`rectangle` 模式仍保留用于隔离 FoundationPose 的快速冒烟验证。非连续图库记录逐帧初始化，
不在它们之间伪造跟踪连续性。

SAM2 首帧命令：

```powershell
$record = Get-ChildItem ..\robot-ev-charging\dataset\vision\records\*.json | Select-Object -First 1 -ExpandProperty FullName
python scripts/pipeline/charging_replay.py `
  --record "$record" `
  --weights "..\robot-ev-charging\runs\detect_split_20261104T141428Z_0ba4dbaf\weights\best.pt" `
  --mesh assets\mesh\socket_mod.STL `
  --mask-mode sam2 `
  --output artifacts\charging-replay-sam2.jsonl
```

首帧证据：`artifacts/charging-replay-sam2-20261106-r4.jsonl`。该记录使用 D415 离线图像，
YOLO 置信度约 0.976、SAM2 掩膜得分约 0.994，标定文件和几何定义仍标记为未验证。
