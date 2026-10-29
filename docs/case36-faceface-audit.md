# 第36项独立面面圆角量测

| 内核／方法 | 模式 | 竖面接触轨 X | 横面接触轨 X | 圆拟合 R | 端部子判据 |
|---|---|---|---|---:|---|
| OCCT / explicit_occ_composition | short | [-7.0, 7.0] | [-7.0, 7.0] | 7.999999967135873 | True |
| OCCT / explicit_occ_composition | long | [-12.5, 12.5] | [-12.5, 12.5] | 7.999999967135873 | True |
| OCCT / explicit_occ_composition | no | [-20.0, 20.0] | [-20.0, 20.0] | 7.999999967135873 | True |
| OCCT / explicit_occ_composition | to_walls | [-7.0, 7.0] | [-12.5, 12.5] | 7.9999999671360005 | True |
| SMLib / native_surface_surface_fillet | no | [-13.999999999999998, 14.000000000000002] | [-13.999999999999996, 14] | 8.000000000000025 | True |
| SMLib / native_surface_surface_fillet | short | [-7, 7] | [-6.999999999999998, 7] | 8.000000000000123 | True |
| SMLib / native_surface_surface_fillet | long | [-12.500000000000002, 12.500000000000002] | [-12.5, 12.5] | 8.000000000000048 | True |
| SMLib / native_surface_surface_fillet | to_walls | [-7, 7] | [-12.5, 12.5] | 7.999999716605932 | True |
| OCCT / native_surface_surface_rolling_ball_walking_and_approximation | native-baseline | [-7.0, 7.0] | [-7.0, 7.0] | 7.999999999999857 | None |

## SMLib调用后的墙面状态

| 模式 | 原文件未变 | 调用前有限域匹配 | 调用后有限域采样保持 | 调用后拓扑保持 | 左面/边 | 右面/边 |
|---|---|---|---|---|---|---|
| no | True | True | True | False | 1/4 → 2/7 | 1/4 → 2/7 |
| short | True | True | True | False | 1/4 → 2/7 | 1/4 → 1/5 |
| long | True | True | True | False | 1/4 → 2/7 | 1/4 → 2/7 |
| to_walls | True | True | True | False | 1/4 → 2/7 | 1/4 → 2/7 |

输入及量测身份一致性：True；四模式是否齐全：True。

以上端部子判据与局部几何不等于通用原图功能或人工外观验收。原生调用与显式组合分别记录；审计器没有重新调用圆角。

SMLib base_trim=0 的实际调用副本墙面发生拓扑分割，原文件和有限域采样保持；不得笼统宣称墙面完全未变。OCCT native baseline自然端域观测也不等于四trim枚举已实现。
