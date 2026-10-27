# 特殊协议重跑

这里包含 51 个冻结请求的 benchmark consumer：37 个受控特殊协议及 14 个先导请求，覆盖 11 个 case、8 个 driver。SDK 头文件和内核库由使用者提供；公开 core 构建入口在 [../core/CMakeLists.txt](../core/CMakeLists.txt)。Python 入口只使用标准库。

配置 `SMLIB_ROOT` 为 USD-BRep checkout，`SMLIB_LIBRARY` 为该 core 构建生成的共享库后，在仓库根目录运行：

```sh
python3 adapters/smlib/special/run.py --list
python3 adapters/smlib/special/run.py --job 08/pilot-r18-crossing
python3 adapters/smlib/special/run.py --job 35/pilot-smlib-thumb10 --output runs/my-thumb10
```

输出目录必须为空；默认输出自动带 UTC 时间戳。每次调用独立进程，watchdog 最长 60 秒。`CXX`、`CXXFLAGS`、`LDFLAGS` 可配置编译器和附加参数。二进制按源码、SDK、core SHA 和编译配置缓存，运行结果记录单独的 provenance。

| Case | Driver | 输入和范围 |
| --- | --- | --- |
| 07 | `case07.cpp` | 原生 box、cylinder 和布尔；默认 edge fillet，未传 transfer 开关 |
| 08 | `case08.cpp` | 原生零厚片体；R12/13/14/18 缺口接触与跨越 |
| 17/18 | `cap_bridge.cpp`、`cap_trial.py` | 原生本体及指定 cap 辅助几何；cap 未传入圆角调用 |
| 23 | `case23.cpp`、`base-helpers.hpp` | 原生 capsule、shoulder 重建；两条根棱同时处理 |
| 27/30 | `surface_pair.cpp` | 公开 exact NURBS fixture 导入完整组件，经独立采样门后按世界面采样选择有限面 |
| 28/36 | `surface_controls.cpp` | 原生有限平面；左右有符号半径与 trim/base_trim 受控参数 |
| 34 | `case34.cpp` | 原生梯形扫掠；R6 圆弧与变半径分别运行，未传 rho |
| 35 | `case35.cpp` | 原生零厚正交片；截面、continuity、thumbweight 及独立 SMB 读回 |

每个请求在 [jobs.json](jobs.json) 中有明确参数。27/30 引用仓库内 BREP 和 exact NURBS fixture 的 SHA，重新导入后才调用 fillet；输入面由世界采样选择，未向另一内核传递面索引。其余 driver 的原生构造参数直接包含在源码中。[source-provenance.json](source-provenance.json) 记录从历史 consumer 到 portable consumer 的源码 SHA 和修改范围，不包含 SDK 源码。

`outcome=native_returned` 仅表示 driver 进程返回 0；API 状态在 `execution.native_api_raw_status`，非空几何在 `execution.nonempty_result_mesh`。例如 08/R13 的 API 失败但保留实际候选，27/boss R8 的 API 成功码可同时没有非空结果，23/R2.5 返回的是开放残片，35/thumbweight10 的边界自交不会因 API 或接头 G2 而变成合格结果。

2026-10-27 已使用本仓库公开 CMake 构建的 core 在 macOS arm64 重新执行全部 51 个请求，加 34 的变半径 control：46 个 API 成功码、5 个失败码；43 个非空结果网格、8 个无非空结果。全部请求的 API 状态和结果网格可用性与历史记录一致。40 个结果的规范化网格数组完全相同；此比较不构成完整形状或特殊功能认证。Linux 构建参数已提供，本次未在 Linux 执行。

完整记录在 [../../../docs/special-reproducibility.json](../../../docs/special-reproducibility.json)。重新生成逐项覆盖记录：

```sh
python3 adapters/smlib/special/verify_replay.py --runs-root runs/special-validation/public-core-v2
```

网页保留独立的历史快照及 `fresh_replay` 证据。历史 exporter 不运行内核；可用下列方式整理已存在的私有历史 JSON 和新运行目录，只发布 sanitized JSON：

```sh
python3 tools/export_special_evidence.py --source-root /path/to/history-workspace --fresh-runs runs/special-validation/public-core-v2
```
