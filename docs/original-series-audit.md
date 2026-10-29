# 原版 OCC 系列独立审计

审计结果：通过。源 review-state SHA-256：`c4e90452d792e28b1b5a0c5a5237ba7043a235c98abffde445b2dbe70c0f8fa5`。

核对 35 条原记录、34 个模型、129 个展示变体；128 个计算变体中 128 个绑定实际新执行，31 的 blade-input 仅保留输入，32 仅说明。

原生对照 144 次：native_and_step_passed 80，native_rejected 26，step_roundtrip_failed 29，native_quality_failed 9。

组合/专用展示变体 33 个，绑定 31 次独立执行；全部尝试 37 次。展示别名与组合比较不能按新的独立执行计数。

## 核对结果

- 每个 current base 与当前源文件、snapshot 和冻结 BREP 的字节哈希一致；冻结准备输入与 base 保留独立哈希。
- 实际 before.brep 上独立匹配有限选边：端点、长度、全部原始世界坐标采样与邻面归属；不依赖适配器的边选择函数。
- 24 使用当前斜向两根边，独立夹角 39.805571°；旧 batch 结果保留在独立的 historical track。
- 31 当前 packet 与 A 主体操作输入分开，clean 展示别名共享同一次实际计算，B 叶片输入不冒充重算结果。
- 33 的 a/b 两条独立反向偏距和 34 的 absolute/relative rho 分别通过独立数学剖面点到有限结果的距离核对；原生圆角仅作对照。
- 35 三档 degree9 代理保留原始控制点和 α，独立采样验证有限结果；数字 softness 映射与完整 G2/外观验收未由本次采样证明。
- 22 R6 原生 BREP 通过而 STEP 失败；独立重读新 STEP 仍出现 BOPAlgo_InvalidCurveOnSurface，旧失败记录继续保留。
- 36 当前保留原两张不相交、不等宽有限面，间距 7.071068 mm；R8原生面面基准、四种显式裁剪和SMLib原生枚举分别绑定实际新结果；旧等宽L壳及小半径前置检查留档，不能充作本轮功能通过。
- 冻结源数据、运行记录与原版网页数据进行了机器绝对路径和参考图像/PDF 扫描；结果见 JSON 的 public_scan 与 issues。

## 验证边界

读取冻结 BREP、提取子体、缝合或构造操作输入，不等于从参数重建整个 base。组合配方执行不等于原生特殊 API；BREP、STEP、G0/G1/G2 和人工外观验收互不替代。此次不对原始厂商尺寸、全局曲面等价或外观作新验收，也未重新运行所有圆角。

完整逐项证据见 [original-series-audit.json](original-series-audit.json)。
