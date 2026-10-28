# FilletBench · 圆角观察与复现库

[打开对比网站](https://liyongzheng666.github.io/filletbench/) · [评测方法](docs/methodology.md) · [贡献案例](CONTRIBUTING.md)

默认打开此前逐项人工调教的 **原版 OCC 系列**：原 PDF / 原基础模型与选边 / OCC实际结果 / SMLib实际结果。另保留独立的 OCC–SMLib 对照实验集合。保留失败、空结果、碎片和自交；**API 成功不是功能通过**。本库目前是探索性测评集，尚未建立可用于内核排名的统一通过率。

## 快速开始

Python 3.10+，推荐独立虚拟环境。OCCT 通过固定版本的 [CadQuery/OCP](https://github.com/CadQuery/OCP) 绑定运行；SMLib 使用 [NVIDIA USD BRep](https://github.com/NVIDIA-Omniverse/usd-brep) 中的开源内核源码，需另行构建，库内不分发 SDK 或二进制。

```sh
git clone https://github.com/liyongzheng666/filletbench.git
cd filletbench
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-occt.txt
python bench.py verify
python bench.py original --case 22 --variant part01-r6
python bench.py serve
```

打开 `http://127.0.0.1:8740/`。不安装内核也能查看已发布的实际网格与测量摘要。[配置 SMLib](docs/smlib.md) 后，用 `--engine both` 在相同请求上运行两者。原生调用失败、超时及缺依赖均记录到本地 `runs/`，不覆盖已发布证据。`--engine both` 属于独立对照实验入口，不能代替下面的原版处理流程。

## 横向四栏对照

网页保持 PDF、基础模型与选边、OCC、SMLib 横向四栏；三个3D视图同步旋转与缩放，窄屏横向滚动，各栏可放大。第四栏只显示经过对应关系核对的实际SMLib记录。

目前74个原版视图有同约束SMLib证据（包含第08项4个新增半径视图，第11项3档已用修正版重新实跑）；58个协议尚未对齐、1个仅输入辅助项单独标明。原生调用失败、崩溃、无效或未验候选都不伪装成成功。[匹配与复现说明](docs/original-smlib-pairing-audit.md)

## 第08项大半径缺口验证

原版第08项现默认打开 R15，并列出 R12、R13、R14、R15、R18。基础片体与共边A保持不变。R12未触及缺口，R13是临界接触；R15的两库真实结果分开记录：OCC Build失败，无可接受的after；SMLib实测R≈15，缺口自由边从z27移到z25（下移2mm），原生回读一致。绿色线是实际返回的自由边，虚线是原位置辅助。

这是普通圆角的默认裁边结果，未传入preserve_notch专用参数。有效片体、局部接头检查与原图特殊保形/全局质量/人工外观分别验收。原129条冻结记录未改；新增4个半径视图单独登记为用户要求的扩展。

```sh
python bench.py original --case 8 --variant r15-crossing --out runs/my-case08-r15
python adapters/smlib/run.py data/case08-radius/smlib-jobs/case08.original.r15.smlib.json --output runs/my-smlib-r15
```

[独立几何审计](docs/case08-radius-audit.md) · [半径边界协议](data/case08-radius/protocol.json)

## 第11项凹凸性修正

[查看修正版四栏](https://www.goudanx.top/filletbench/#series=original&case=11&variant=part01-r3)。旧输入将目标建成约231.59°的凹根，已有窄带也是凹谷。本轮重新构建真实实体：A为90°凸肩，窄带为外凸曲面；投影视角独立设置，未剪切或镜像几何。短横舌、下台面和外折边同步调整。隐藏连接、厚度和尺寸仍属推定，整体外观等待人工核对。

| 半径 | OCC原生实际结果 | SMLib原生实际结果 |
|---|---|---|
| R1 | BREP、流形、自交及STEP回读门通过；待人工核对 | API1001失败，保留的SMB与输入相同 |
| R3 | Build返回无效自交候选，STEP门失败 | API1001失败，保留的SMB与输入相同 |
| R6 | Build返回无效自交候选，STEP门失败 | API1001失败，保留的SMB与输入相同 |

普通圆角不等同于原文的repair_fa_X专用自交修复。无组合结果冒充原生能力。[修订与复现说明](adapters/occt/case11-convexity/README.md) · [版本契约](data/case11-convexity/revision.json)。

两库对照复跑固定读取同一份修正版BREP；参数化重建单独运行和审计。平台间重新序列化的BREP字节可能不同，不把新生成的输入自动当成原冻结输入，也不放宽SHA身份检查。

```sh
python bench.py original --case 11 --out runs/my-case11
# 独立参数化重建，与同输入的圆角复跑分开
python adapters/occt/case11-convexity/build.py --revision candidate-v6 --output runs/my-case11-reconstructed
python adapters/occt/case11-convexity/audit_material.py --output runs/my-case11-audit
# 配好SMLib后，直接执行已注册的新输入请求
python adapters/smlib/run.py data/case11-convexity/smlib-candidate-v6-r3.job.json --output runs/my-case11-smlib-r3
```

## 按原版实际处理

原版系列保留 **34 组模型、1 个说明项、129 个原有参数/视图**，其中 128 个计算变体已绑定本次真实复跑，1 个仅输入的辅助叶片保持不计算。50 个原页面变体 ID、人工备注、选边/选面及参数顺序完整保留。

除第11项已登记的凸性修正版外，基础模型使用原版冻结的精确 BREP。第11项重新参数化建模，新旧输入及结果按SHA隔离；原始冻结文件保持不变。重新执行的是提取部件、必要的缝合/裁剪/延伸、原生圆角或显式组合流程。网页可切换“原基础模型”与“实际操作输入”；二者分别保存，不能互相冒充。

```sh
# 第22项：原共边、原 R6，保留 STEP 回读失败门
python bench.py original --case 22 --variant part01-r6 --out runs/my-case22
# 第18项：原片体封口组合，和原生自动封口分开
python bench.py original --case 18 --variant sheet-r8 --out runs/my-case18
# 完整原版当前请求与组合；输出到新的目录，不覆盖旧证据
python bench.py original --all --out runs/my-original-suite
# 用此次运行更新本地查看器，其他原版视图保持原记录
python bench.py build-original --suite-run runs/my-original-suite
python bench.py serve
```

原 native runner 144 次实际调用中，129 条是当前原版输入的 `from_base` 处理，15 条旧修订输入单独保留为历史 prepared replay。后者不进入当前默认展示。原组合 33 个视图绑定31次独特实际执行，另有第35项三档 G2 代理新执行。失败 BREP 候选仍展示，只有未返回结果时才用输入兜底并明确标注。

[原版数据与身份边界](data/original-occ/README.md) · [原生复跑](docs/original-occ-native.md) · [组合复跑](docs/original-occ-compositions.md) · [独立审计](docs/original-series-audit.md)

网页默认 `#series=original&case=22&variant=part01-r6`。以下普通请求及 SMLib 结果属于 **另一个实验集合**，不能替代原版人工调教协议；用 `#series=comparison` 查看。

## 独立对照实验收录范围

- **34 组模型**：编号 01–28、30–31、33–36；29 按人工意见移除，32 是说明项，保留编号空位。
- **104 个普通边圆角请求**：86 个可执行请求；18 个因当前输入/操作类型不适合这条 adapter 路线而阻塞。这不是内核“不支持”的结论。
- **174 个查看变体**：104 个普通请求，51 个 SMLib 特殊/先导协议，19 个 OCCT 衍生/组合协议。历史快照、本次重跑及不同协议均单独标记。
- 每个模型提供冻结 BREP、显式有限 NURBS/共享拓扑 JSON、目标边世界坐标、半径与任务契约。模型是从文档示意图推定的重建，**不是厂商原始 CAD**。

### 阅读结果

先选编号，再选半径/协议。主区并排显示参考图、OCCT、SMLib；拖动/缩放模型时相机同步。切换“圆角前”查看实际选边；打开详情查看输入哈希、表示差异、原始状态与复现命令。失败后仍返回的候选也会显示。

公开库不包含原始 PDF 或参考图。参考栏支持在浏览器本地载入自有 PDF/图片，仅在本机显示，不上传、不存入 Git。原 PDF 物理页号从 1 起；载入其他版次时请手动选择对应页。

## 可复现的含义

同一请求锁定源几何哈希、目标世界几何和参数；adapter 在独立进程内调用内核，保存返回值、原生文件读回、实际网格与测量。OCCT 的原解析 BREP 与 SMLib 的显式 NURBS 表示仍有差异，不能宣称二者内部表示完全一致。

普通圆角没有传入源文档的 cliff、cap、limit、rho、softness 等特殊控制。生成了模型只能说明这次具体调用的行为，不能代替该特殊功能的认证。特殊协议使用单独入口，不由普通边圆角命令替代；51 个 SMLib 特殊请求及 19 个 OCCT 衍生/组合请求均已实际重跑。各项仍说明特殊语义、参数映射和几何验收的缺口。

```sh
# 特殊协议：两条命令走不同方法，不视为同条件横向评分
python bench.py special --engine smlib --job 35/pilot-smlib-thumb10 --out runs/g2-smlib
python bench.py special --engine occt --case 35 --out runs/g2-occt
```

[OCCT 衍生/组合说明](docs/occt-special.md) · [SMLib 特殊协议说明](adapters/smlib/special/README.md)

## 仓库结构

| 目录 | 内容 |
|---|---|
| `data/models` / `data/fixtures` | 固定源 BREP / 有限 NURBS 及共享拓扑 |
| `data/jobs` / `data/contracts` | 104 个普通调用请求 / 34 项原图语义契约 |
| `adapters/occt` / `adapters/smlib` | 可执行内核调用、选边和结果记录 |
| `web/data` | 可公开的实际网格与结果摘要，不含原 PDF |
| `tools` | 完整性检查和网站数据构建 |
| `runs`（忽略） | 本地复现实验，保留完整失败日志 |

代码及本项目生成的数据采用 MIT；第三方代码/浏览器依赖按各自许可证，见 [THIRD_PARTY.md](THIRD_PARTY.md)。参考文档、商标及未分发 SDK 不受本项目许可证授权。
