# 原版第四栏：SMLib 对应关系

原版四栏按 **PDF / 基础模型与选边 / OCC / SMLib** 展示。只有可核对的同约束记录进入第四栏，不能用同编号但不同输入、选边、半径或构造方式的图补位。

初始只读核对得到55个可复用视图（53条独立既有SDK请求），15个仅缺同半径，59个存在协议/输入差异或不适用。15个半径已另外实际补跑：15个输入门通过并进入原生调用，11个返回候选、3个API失败候选、1个原生调用崩溃。候选仍需独立质量和人工核对。

最终有70个同约束视图：55个明确标为“既有实跑记录”，15个标为新运行。58个未表达为同协议，1个辅助叶片仅输入，分别标注；这不是SMLib内核不支持58项的结论。完整原始核对在 `original-smlib-pairing-audit.json`，发布绑定复核在 `original-smlib-column-verification.json`。

## 匹配门

- 冻结原基础几何SHA与SMLib源SHA一致；导入的部件与实际操作输入相符。
- 有限世界坐标目标集合、所给半径或物理端点半径、操作及前处理契约相同。
- 核对原生调用、实际选边、输入准入、源fixture和运行摘要身份。
- OCCT解析BREP和SMLib显式有限NURBS仍是不同表示；采样与标量指标不是全域裁剪等价证明。
- 两端变R只证明端点约束匹配，不证明内插规律一致。

原组合封口/限位、派生共边与原有限面pair、G2的alpha代理与thumbweight等不互相代替。特别35的softness标签不能直接当SMLib thumbweight，36的延伸14mm公共带也不能当原有限片体面pair。

## 复现与更新

配置好 `SMLIB_ROOT`、`SMLIB_LIBRARY` 后：

```sh
python tools/complete_original_smlib_radii.py --run --output runs/new-radius-completion
python tools/attach_original_smlib.py
python tools/audit_original_smlib_column.py
```

补跑工具只允许改变审计认可模板的常半径，源、部件、目标、公差与内核选项保持不变；使用新输出目录，失败不覆盖历史。每个第四栏详情给出其精确请求命令。默认发布索引使用 `runs/original-smlib-radius-completion/index.json`；其他运行目录的结果需先审阅再选择发布。网页已发布的补跑摘要会按原定义哈希保留，克隆仓库后无需私有运行目录即可查看。
