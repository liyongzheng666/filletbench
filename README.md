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

第四栏分别记录普通同参 SMLib 实跑和第36项明确标注的原生面面协议。匹配、尚未执行、失败候选与生成待验分别显示；覆盖数量以当前目录和绑定核验记录为准。第36项的 OCC 显式构造与 SMLib 原生调用使用同源有限面、相同R8和明确的局部端部判据，不能据此宣称两个内核实现相同或具备通用 Parasolid 语义等价性。[匹配与复现说明](docs/original-smlib-pairing-audit.md)

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

## 第36项：原有限面上的面面圆角与端部边界

[打开第36项](https://www.goudanx.top/filletbench/#series=original&case=36&variant=trim-to_walls-r8)。基础与操作输入都保持原始 `c886…` BREP：竖面宽14、横面宽25，两有限面间距约7.071mm，不预先延伸到共边或把横面裁窄。R8是本次重建试验值；原PDF没有给出这些尺寸的标定。

当前分开提供三条实际执行路线：

| 路线 | 实际构造与边界 |
|---|---|
| OCC 显式组合，OCCT 7.9.3 | 四种圆柱面边界控制；输出独立blend patch。`to_walls`采用从原墙面边界量测得到的UV端线插值，是本例显式构造规则。 |
| OCC 低层原生面面基准，本次OCCT 7.8.1 | 从原支撑面及有限域执行滚动球walking和曲面逼近，给出一个R8基准；该选用接口没有四种trim枚举参数。 |
| SMLib 10.0.0 原生面面调用 | 分别执行NONE、MINIMAL、MAXIMAL、BEVEL四个原生枚举；保留实际SDK产物和SMB读回检查。 |

四栏中的结果是独立圆角片，不把原墙面拼进结果充当圆角成功。原有限墙面边界单独作为辅助线。SMLib的 `base_trim=0` 会分割调用副本的wall拓扑；原始输入文件保持不变，有限域面积、范围与边界另行核对，不能把“有限域保留”说成“调用副本拓扑未变”。

| 局部控制 | OCC显式结果 | SMLib实际结果 |
|---|---|---|
| `to_walls` | 窄面接触轨x±7、宽面轨x±12.5，端边非统一x平切 | BEVEL：两接触轨端部分别对应原窄/宽面边界 |
| `no` | 有限工作包络x±20 | NONE：本次返回x±14；未裁模式的工作包络由实现给定，不按两者同尺寸评分 |
| `short` | x±7，按两原面x范围交集 | MINIMAL：x±7 |
| `long` | x±12.5，按两原面x范围包络；窄面侧保留超出有限域的部分 | MAXIMAL：x±12.5 |

R8、实际接触轨、端域、局部G0/G1、半径与CAD读回的本矩形子判据分别检查。通用 Parasolid 模式等价、全域形状和人工外观仍未认证；尤其不能把 `to_walls` 的本例UV插值规则推广为通用原生算法。

**端点符合不等于整条曲线一致。** 对 `to_walls` 每端进行8193点原生只读查询，按同一物理截面角对齐，OCC组合与SMLib原生的最大观测X差约 **0.05614980mm**。这是采样对应差异，不是精确Hausdorff距离。short/long的本次端曲线差异接近数值精度；no的6mm差来自不同工作包络。[测量总览与差异图](https://www.goudanx.top/filletbench/data/case36-faceface/report.html) · [完整差异量测](docs/case36-faceface-differences.json)。

```sh
# 当前OCC suite默认执行四个显式构造；--all亦采用这条默认路线
python bench.py original --case 36 --out runs/my-case36-faceface
# 只重新执行并更新一个控制，其他已发布同源记录保留
python bench.py original --case 36 --variant trim-to_walls-r8 --out runs/my-case36-to_walls
python bench.py build-original --suite-run runs/my-case36-to_walls
# 配好SMLib后独立执行四个原生枚举；不会由OCC --all自动运行
python tools/run_case36_smlib.py --output runs/my-case36-smlib
# 先将OCCT_INCLUDE_DIR、OCCT_LIBRARY_DIR指向同一套已安装C++ SDK，再执行单独的原生面面基准
python bench.py original --case 36 --variant native-faceface-r8 --out runs/my-case36-native
# 只读比较实际SDK端曲线与OCC BREP；需要先执行对应原生/组合产物
python tools/compare_case36_faceface_boundaries.py --occ-root runs/my-case36-faceface/case36-faceface/occt-composite --sdk-root runs/my-case36-smlib --query-sdk --output runs/my-case36-boundary-differences.json
```

低层原生入口缺少SDK或编译器时输出 `dependency_missing`、不调用内核并非零退出；不会换成组合结果。`build-original`会拒绝用这类未执行的请求更新当前公开记录，诊断仍保存在该suite目录。已有运行目录拒绝覆盖。源码与运行记录分别标注实际内核版本、输入表示和方法。

此前R0.5/R1/R2普通共边前置检查和更早的共宽L壳实验仍可显式调试，均不再作为当前四模式结果：

```sh
python tools/run_case36_input.py --variant part01-r1p0 --output runs/my-case36-admission-history
python adapters/occt/original/run.py --requests adapters/occt/original/requests.json --case 36 --output runs/my-case36-derived-history
```

[面面协议与输入身份](data/case36-faceface/protocol.json) · [显式构造请求](data/case36-faceface/occt-requests.json)

## 按原版实际处理

原版系列保留 **34 组模型、1 个说明项和129份原始冻结参数/视图记录**。当前展示可增补新协议并隔离旧衍生结果：第36项现使用四种R8面面控制及独立原生基准，旧3档普通共边前置检查与更早L壳实验保留为历史调试证据。1个仅输入的辅助叶片保持不计算。原页面ID、人工备注和参数历史保持可追溯；当前视图数量或控制器退出码不等于成功构造数。

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

历史 native runner 的144次实际调用中，129条记录为 `from_base` 流程（可包含显式前处理），15条为旧修订输入的 prepared replay。该历史调用数不能作为当前同原输入的覆盖率；第11项已改为修正版固定输入复跑，第36项旧L形衍生调用已从当前展示隔离。原组合33个视图绑定31次独特实际执行，另有第35项三档G2代理执行。失败BREP候选仍展示，未调用、前置阻止与未返回结果分别标明。

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
