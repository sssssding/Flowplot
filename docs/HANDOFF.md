# 协作接手说明（更新至 2026-10-16）

## 本次 GitHub 交接（2026-10-16）

当前交接分支为 **`origin/codex/post-handoff-finish`**，包含主分支 `890af06` 之后的推荐发布保护修复 `abeba14` 和本次文档保存点；本次按用户要求发布，最终提交号及推送结果以 Git 实际记录为准。尚未合并 main，接手本轮成果应从该个人分支建立自己的分支，而不是假定 main 已包含。

同时保留并交付工作区 2026-10-15 的策划补充：[DELIVERY_PLAN.md](DELIVERY_PLAN.md)、验收计划修订、索引及进度记录。接手优先按任务书 P01–P03 核验正常环境全量回归、真实只读检查与可见界面；后续验收门槛不因上传而完成。本次仅发布，不重新运行 COMSOL 或全量测试；2026-10-14 的 533 通过/1 跳过及 23 项隐藏 Tk 是当时结果，2026-10-15 的环境阻塞记录也保留，不宣称本次远端 CI 已通过。

已有仓库先保存自己的未提交工作，再执行下列示例（个人分支名已存在时另选，不强制覆盖）：

```powershell
git fetch origin
git switch -c codex/colleague-next origin/codex/post-handoff-finish
git lfs pull
```

源码、测试、小型证据及协作文档随 Git 发布；本地用户修改版基准 MPH、`.codex` 配置、outputs、原生日志、环境及许可证均不包含。本次不创建 PR、不合并 main、不改同事分支或代发消息。下方各日期的“尚未推送/本地保存”等为历史状态，当前接手以本节为准。

## 历史策划补充与本地记录

2026-10-15 策划补充：当前执行优先级、实现方交付格式及用户验收条件见 [DELIVERY_PLAN.md](DELIVERY_PLAN.md)，本轮核验范围见 PROGRESS.md 的同日记录。跨会话连接尚未成功，任务书尚未实际送达“代码具体实现”；下文为既有代码交接，不代表本轮重新完成验证。

## 本地继续接手（2026-10-14：推荐发布保护）

已从 GitHub 拉取主分支 `890af06`，在个人分支 `codex/post-handoff-finish` 继续；没有直接修改 main 或队友分支。本节新增功能仅在本地保存，尚未推送；下面“当前接手入口”描述已发布的集成版本。用户未提交的原基准修改保持原字节，不加入本轮提交。

正常权限下复现同事版本的全量 519 项（518 通过、1 项真实符号链接权限跳过）。继续检查时，用临时合成报告发现计算期间报告替换仍能返回旧推荐，现已补上计算完成/拒绝返回/导出前复核；CLI 推荐 JSON 只能输出到输入报告树之外的未占用位置，不污染普通报告或轻量协作包。

新增合成故障测试与两项真实 CLI 路径验证见 `tests/test_recommend_publication.py`；当前真实已有六报告的 23 项隐藏 Tk 流程摘要为 `data/fixtures/ai_publication_smoke.json`，计算中变化仅在临时合成副本执行。前四份功能摘要、训练数据和原模型保留，不重新求解。最终回归结果见 `PROGRESS.md`，不把隐藏窗口或合成反例提升为专业、新用户或跨硬件验收。

剩余外部验收仍需真实专业人员、独立模型来源和另一台电脑实测，本轮不代签、不编造模型或成绩、不自动上传模型/日志。若要分享本轮新增代码，需发布这个个人分支，而不是假定 origin/main 已包含。

## 当前接手入口（2026-10-14：验收修复与 main 合并）

本节随 `codex/ai-handoff-review` 的修复 PR 进入 main；PR 合并后，新开发以 **`origin/main`** 为起点。用户已授权修复两个验收问题并合并。此前的验收工具、AI 候选推荐及本次修复一并纳入；下方旧分支命令和“尚未推送/未合并”只代表历史。实际合并/CI 状态以 GitHub 对应 PR 和提交为准，不把文档中的计划当作成功记录。

本次修复：AI 初次展示及手动刷新同时绑定当前 `run.json` 与 `diagnosis.json` 的指纹，报告/配置变化时清除推荐并要求重新读取；测量工具在建目录前拒绝输入报告树内输出，不能污染轻量报告包。建议快照新增 `run_sha256` 来源字段，原报告格式及训练文件不改；推荐模块不在正式冻结源码集合，此次修复不改变冻结集合，队友先前 AI 登记变更的版本约束仍保留。

验收基线：对方 `cc0e9c6` 在本机 506 项测试中 505 通过、1 项权限跳过；COMSOL 6.3 对原六模型各只读加载两次，6/6 匹配开发预期，离线重算一致，原件哈希不变。本次修复的新增测试、最新全量结果和 19 项隐藏 Tk 实测见 `PROGRESS.md`；新证据为 `data/fixtures/ai_review_safety_smoke.json`，前三份 AI 记录保持原字节。四项快照回归只改临时合成报告，不改真实输入。本次没有重新求解或重采训练数据。

合并后首次克隆使用 `git clone https://github.com/sssssding/Flowplot.git`，进入目录执行 `git lfs install`、`git lfs pull`，创建个人分支并按 `DEVELOPMENT.md` 安装依赖、运行只读预检和全量测试。已有仓库先保存自己的未提交工作，再操作：

```powershell
git fetch origin
git switch -c codex/your-next-task origin/main
git lfs pull
python -X utf8 src/flowpilot/preflight.py
python -X utf8 -m unittest discover -s tests -q
```

分支名只是示例，已存在时另选，不强制覆盖；需在项目依赖所在 Python 环境执行。推荐入口 `FlowPlotAI.cmd`，原入口 `FlowPlot.cmd` 保留；真实读模型需要本机 COMSOL 6.3 与适用许可证，已有核验报告可离线预览。outputs、日志、许可证/环境及新增 MPH 不上传，不整体分享本机验收目录。

下一步仍为真实专业复核、真正独立模型集及跨硬件/新用户验收。三种受控几何配置的 36 条训练观测不是独立验证；AI 仅展示需本机副本验证的候选，不自动改模型或求解。不要因本次修复合并把 T13 正式性能门槛或专业验收标为完成。

## 历史交接入口（2026-10-14：AI 推荐检验）

本次按用户要求发布到 **`origin/codex/resume-acceptance`**，供同事检验；接手以本节为准，以下各节的“尚未推送”、旧分支和测试数都是历史记录。该分支包含 `16970c5`（初始推荐）、`16ddd29`（离线预览）和 `c3cae86`（特征迁移）及本次交接文档；最新提交号与发布状态以 Git 实际记录为准。没有合并 `main`、修改队友分支、创建 PR 或代发消息。

### 拉取与启动

新电脑需要 Git/Git LFS 和带 Tcl/Tk 的 Python（已验证 3.12/3.13）。以下为 Windows 示例；个人分支已存在时另选名字，不强制覆盖：

```powershell
git lfs install
git clone --branch codex/resume-acceptance https://github.com/sssssding/Flowplot.git
cd Flowplot
git lfs pull
git switch -c codex/colleague-ai-review
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -X utf8 src/flowpilot/preflight.py
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
./FlowPlotAI.cmd
```

已有仓库：先查看 `git status` 并保存自己的未提交工作，确认干净后 `git fetch origin`，从 `origin/codex/resume-acceptance` 新建自己的检验分支，再执行 LFS、依赖与测试步骤。不要从旧 `codex/acceptance-handoff` 或 `main` 判断本轮 AI 功能。提交前本机全量 506 项：505 通过、1 项真实符号链接权限跳过；远端 Actions 状态需查看对应提交，不把本机通过当作 CI 已通过。

### 同事检验范围

- 默认使用 `data/ai/portable_ranker.json`：按尺寸、Re 和长宽比推荐相对容差/线程候选，不绑定固定文件哈希或机器；检查 CPU 数不足时过滤线程候选。
- 检查异常/不完整报告、已知严格参考失败模型、超出训练覆盖或版本不匹配时拒绝推荐；打开无效报告后不得留下旧推荐。
- 核对界面中文说明、离线报告预览和“不自动改模型、不自动求解”的行为。隐藏 Tk 的 15 项流程已通过，但可见界面/新用户检验仍需同事完成。
- 建议全部需要本机副本验证；训练仅为同一受控二维矩形层流模型族的三种几何配置、36 条实测记录，不是三种独立模型。没有第二台机器真实速度优势或独立性能验收结论。适用范围与重新采集方法见 [AI_PORTABILITY.md](AI_PORTABILITY.md)。
- 旧 0.1 文件可显式选择，仍有旧的文件/机器限制；不要用旧行为判断默认 0.2 是否生效。正式验收的程序/开发样本指纹已有更新，旧冻结须重新核验，不手改证据哈希。

本次只共享源码、文档、测试和小型学习/功能摘要；本机 `outputs`、原生日志、环境、许可证及新增 MPH 副本不上传。仓库原有六个模型通过 LFS 获取；本机原基准的未提交修改不包含在交接中。

要检验真实文件，在有 COMSOL 6.3 和适用许可证的 Windows 电脑读取仓库基准，生成自己的报告（每次使用新输出目录）：

```powershell
./.venv/Scripts/python.exe -X utf8 src/flowpilot/check_model.py models/baseline_pipe_2d_laminar.mph --comsol-root '<本机 Multiphysics 安装目录>' --output-dir outputs/colleague-ai/check-001 --loads 2
./.venv/Scripts/python.exe -X utf8 src/flowpilot/recommend.py recommend --report outputs/colleague-ai/check-001
./FlowPlotAI.cmd --report outputs/colleague-ai/check-001
```

检查入口只读、不重新求解。已有核验报告的离线推荐/预览不需 COMSOL；交出方本机报告路径不能直接在接收电脑使用。跨平台推理反例已测，但 Linux/macOS 的实际 COMSOL 驱动及跨硬件性能尚未实测。

## 历史记录说明

以下保留各轮原始状态，当前拉取分支和检验范围以顶部 2026-10-14 交接入口为准。

## 本地跨环境推荐扩展（尚未推送）

在 `codex/resume-acceptance` 继续用户要求的通用环境改进。默认升级为按 SI 模型特征与相对耗时匹配的 0.2 文件 `portable_ranker.json`，不再硬性匹配单一文件或机器；旧 0.1 文件可显式选择，历史证据保留。适用范围、原网格失败/副本细化、CPU/版本/覆盖拒绝及重新采集方法见 [AI_PORTABILITY.md](AI_PORTABILITY.md)。所有迁移建议都需本机副本验证，未宣称跨硬件加速或独立性能通过。

新开发哈希登记到正式冻结指纹中，含失败和未求解的生成样本，不能重标独立验收集。旧正式冻结/结果可能因指纹变化被阻断，应重新核验，不修改旧指纹。实际测量与最新测试状态见 `PROGRESS.md`，本轮没有推送/合并或上传 MPH/日志。

完成状态：两个新尺寸模型 24 次实际冷求解全部通过，结合旧基准共 36 条观测；默认便携文件已生成，15 项隐藏 Tk 流程通过。全量 506 项：505 通过、1 项权限跳过。仍没有第二台机器真实性能/专业/独立验收，旧可见核验定位问题也没有宣称已解决。可显式选择旧 0.1 文件回退推荐，但不要移除开发登记绕过验收门槛。

## 本地推荐功能收尾（2026-10-14，尚未推送）

当前个人分支 `codex/resume-acceptance` 基于下方远端交接的 `4a80aec`。按用户新要求，优先实现受限本地 AI 参数推荐并快速检验。新增 `FlowPlotAI.cmd`，原 `FlowPlot.cmd` 继续可用；四组容差/线程配置各三次真实基准副本校准全部通过，学习数据在 `data/ai/solver_ranker.json`，13 项隐藏 Tk 功能核对记录在 `data/fixtures/ai_functional_smoke.json`。当前测量区间重叠，保留原容差 1e-6、2 线程。

最终全量回归 485 项：484 通过、1 项符号链接权限跳过；新学习文件按仓库 LF 规则规范后重新绑定实跑记录并复测推荐专项。个人分支本地保存，不推送或合并 main；提交号以 Git 实际记录为准。

后续新增 `FlowPlotAI.cmd --report '<已有报告目录>'` 的离线预览，不需 COMSOL、窗口创建前核验、不自动开始检查。新 15 项隐藏 Tk 功能记录为 `ai_offline_preview_smoke.json`，前一份记录保持原字节。可见核验因操作工具窗口归属定位错误未完成，不以隐藏测试代替。最新全量回归 487 项：486 通过、1 项权限跳过，20 项推荐专项通过。个人分支本地保存，未推送。

使用与重新校准见 [AI_RECOMMENDATION.md](AI_RECOMMENDATION.md)。只能对同一基准与本机校准环境推荐；换机器需新校准，异常/未知/不完整报告拒绝推荐。不是通用 AI 推荐或独立性能通过；专业审核、独立集与新用户验收不因此完成。模型副本/日志/环境不共享，用户本地原基准修改保留。下方 2026-10-13 节仍描述已推送的远端交接，不包含本轮本地新增功能；后续保存点以 Git 记录为准。

## 本次交接入口（2026-10-13）

接手分支为 **`origin/codex/acceptance-handoff`**，不是 `main` 或队友的 `feat/local-acceptance`。本次按用户要求提交并推送 `dfc9ae7` 之后的全部开发成果；提交号以该分支最新的 `chore: hand off acceptance and report safety improvements` 提交为准。本次不创建 PR、不合并 main、不修改队友分支、不代发消息。下方历史记录中的“未提交/推送”、旧测试数、旧分支命令只描述当时状态，当前接手以本节为准。

### 交付范围与验证

- 新增验收草稿只读预检；通用评分复用真正冻结门槛，不让已知开发样本或不完整声明变成独立验收成绩。
- 批量发布前后核对清单、程序、模型、报告与实际产物；正式结果复核兼容新增绑定，旧缺失字段不补造证明。
- 普通/协作报告根目录链接在解析前拒绝，通用/正式批量输出不能写入输入报告树。
- 轻量协作包按接收端容量预检，写后真实重读并核对快照；最终报错即使留下完整目录也不要分享，换新目录重试。
- 提交前本机完整回归：467 项，466 通过，1 项因真实符号链接权限跳过；测试中的模拟失败和 1.500 秒求解不是新增 COMSOL 实验。
- 前几轮真实 COMSOL 隐藏功能流程保存在三份新增 `desktop_smoke_*` 摘要；最后一轮仅六份旧报告离线隐藏 Tk/直接导出重读，见 `report_export_offline_smoke.json`。四份完整旧摘要保持原字节，当前来源按未变模块与新导出模块分层核对；不是人工可见、专业或新用户验收。
- 六个仓库原始 MPH 的 SHA-256 均匹配 `data/fixtures/cases/manifest.json`；不修改模型、Java 或诊断规则。本次只上传源码、测试、文档与小型证据，不上传 outputs、运行日志、环境、许可证或新增 MPH。

当前名为 **FlowPlot**；推荐 `FlowPlot.cmd`，保留旧入口、内部 `flowpilot` 与 `FLOWPILOT_*` 配置。仍只支持已声明的二维单域稳态牛顿层流、米制轴对齐矩形通道及当前边界模式，不是通用 COMSOL 检查器，也没有训练 AI 参数推荐器。

### 新电脑首次接手

安装 Git、Git LFS、带 Tcl/Tk 的 Python（已验证 3.12/3.13）；真正读模型还需 COMSOL 6.3、适用许可证和模块（本机构建 6.3.0.290）。离线测试/读报告不需运行 COMSOL。

```powershell
git lfs install
git clone --branch codex/acceptance-handoff https://github.com/sssssding/Flowplot.git
cd Flowplot
git lfs pull
# 示例个人分支名，若已存在请另选，不强制重置
git switch -c codex/colleague-next
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -X utf8 src/flowpilot/preflight.py
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
./FlowPlot.cmd --check-env
```

已有仓库：先 `git status`，提交或另行备份自己的未提交内容，确认干净后 `git fetch origin`，再执行 `git switch -c codex/colleague-next origin/codex/acceptance-handoff`、`git lfs pull` 和上面的环境/测试步骤。个人分支名自行替换；遇到分叉先核对提交，不强推、重置或覆盖原模型。`.gitattributes` 要求源码/JSON 为 LF；来源测试失败时先核对字节换行，不直接改证据哈希。

运行窗口使用 `./FlowPlot.cmd`；COMSOL 路径在界面选择或用 `FLOWPILOT_COMSOL_ROOT` 配置，不照抄本机安装路径。若要重新生成自己的真实报告，在新目录执行：

```powershell
./.venv/Scripts/python.exe -X utf8 src/flowpilot/check_suite.py --comsol-root '<本机 Multiphysics 安装目录>' --output-dir outputs/check-suites/colleague-001 --loads 2
./.venv/Scripts/python.exe -X utf8 src/flowpilot/check_suite.py --reports-root outputs/check-suites/colleague-001 --output-dir outputs/check-suites/colleague-001-offline
```

以上目录名只是示例，每次换新目录，离线输出不能嵌在输入树中。本机 outputs 不在 Git，不能直接引用交出方电脑上的旧报告路径。14 个变体按 `REGRESSION_FAMILY.md` 在自己电脑生成，仍是开发数据，不是独立集。GitHub Actions 只运行离线测试；本机通过不代表本次远端 CI 已通过，应查看对应提交的实际 Actions 状态。

### 下一位开发者的优先事项

1. 先阅读 `PROJECT_SCOPE.md`、本文、`PROGRESS.md`、`DEVELOPMENT.md` 与 `GUI_REVIEW.md`，报告本机预检/测试结果、分支和计划，再在个人分支开发。
2. 组织真实专业人员审核基准、异常和变体的物理/标签；继续基准五次求解副本的 GUI 日志对照，不用编码代理代签。
3. 当前用户明确没有专业审核的独立模型集。先收集至少 10 个真正未用于规则调试、覆盖五条核心规则及负对照、至少两个声明来源组的模型；真实审核后按 `ACCEPTANCE_PREFLIGHT.md` → `ACCEPTANCE_FREEZE.md` → `ACCEPTANCE_RESULTS.md` 准备、冻结和评估。组名/声明不能自动证明独立性，不填造人员或日期，不拿原六个及 14 个开发变体充数。
4. 完成真实新用户和可见界面试用，记录操作耗时/错误理解；隐藏 Tk 不替代新用户五分钟验收。T13 AI 推荐未开始，范围扩展前先更新范围与决策。
5. 按 `ACCEPTANCE_ELIGIBILITY.md`、`BATCH_STABILITY.md`、`REPORT_BOUNDARIES.md`、`REPORT_PACKAGE.md` 维护本次保护。冻结源码已在前几轮变化，旧正式记录须匹配版本或重新确认，不手改哈希适配。轻量报告包不带模型/日志但不是全文脱敏；正式证据包包含模型和审核信息，必须显式 `--include-models` 并人工审查授权，不自动上传。

多人各用分支和独立输出目录，不同时修改同一 MPH；保持原基准与历史证据。请通过 PR 审阅后再决定合并，当前保存分支不是专业验收通过或已合并 main 的声明。

可直接交给接手方的任务：

> 从 `origin/codex/acceptance-handoff` 建立个人分支，先完整阅读 `docs/HANDOFF.md` 顶部本次交接、`docs/PROJECT_SCOPE.md`、`docs/PROGRESS.md`、`docs/DEVELOPMENT.md` 和 `docs/GUI_REVIEW.md`。检查 Git LFS 原模型、依赖与本机 COMSOL，运行只读预检和全部离线测试，先汇报结果及计划。保持 FlowPlot 命名，不覆盖基准/历史证据，不伪造专业审核或独立模型；优先完成真实审核、独立集准备和真实用户试用。不要未经授权推送、合并或上传模型与日志。

## 历史记录（以下不是当前接手操作入口）

### 上一个保存点及随后各轮本地记录：dfc9ae7

最新本地补 [轻量报告包导出保护](REPORT_PACKAGE.md)：创建前按接收端限制检查大小，拒绝链接/联接输出，写后真实重读并核对快照和数值类型。最终核验失败可能留下完整目录，报错时不要分享或覆盖重试。全量 467 项中 466 通过、1 项真实符号链接权限跳过；13 项新专项为模拟故障/边界。本轮未调用 COMSOL，只用六份既有真实报告做隐藏 Tk 展示、历史/对比及直接导出重读；不声称重新点击导出按钮或人工验收。当前来源分层使用旧完整 `desktop_smoke_report_boundaries.json` 中未变的 13 个模块与新 `report_export_offline_smoke.json` 的导出模块，四份完整旧记录原字节保留。六个原模型哈希不变；当前及下方新改动仍未提交推送，远端保存点仍为 `dfc9ae7`，新代码远端 CI 未运行。独立集/专业/新用户验收待办不变。

最新本地另补 [报告目录边界](REPORT_BOUNDARIES.md)：普通/协作报告根链接在解析前拒绝，通用/正式运行输出不能写入输入报告树，正式外层创建前也检查。全量 453 项中 452 通过、1 项真实符号链接权限跳过；新链路模拟测试不当作操作系统链接集成。真实 COMSOL 隐藏桌面与六报告离线 6/6 通过，无求解/原件修改；当前来源摘要为 `desktop_smoke_report_boundaries.json`，前三份记录保持原字节。本轮及下方各轮新增内容尚未提交推送，远端保存点仍是 `dfc9ae7`，未宣称新代码远端 CI 通过。

保存后本地最新还包括 [批量输入稳定性与发布保护](BATCH_STABILITY.md)：清单解析/指纹同源，发布前后复核来源及实际产物；正式复核同步验证可选绑定。全量 435 项中 434 通过、1 项真实符号链接权限跳过；六报告离线 6/6、真实 COMSOL 隐藏桌面流程重跑通过，无求解/原件修改。当前来源记录为 `desktop_smoke_batch_stability.json`，前两份桌面证据不改字节。本轮及下面两轮本地新改动尚未提交推送，远端保存点仍为 `dfc9ae7`；新代码未宣称远端 CI 通过。

保存后最新本地改动还包括 [通用评分资格修复](ACCEPTANCE_ELIGIBILITY.md)：旧条件不足的清单不能绕过真正冻结门槛声明独立验收。当前全量 413 项中 412 通过、1 项真实符号链接权限跳过；真实 COMSOL 隐藏桌面/六报告展示/取消及协作流程已重跑，新摘要为 `data/fixtures/desktop_smoke_eligibility_gate.json`，旧记录保持原字节。没有求解或改原模型，仍无真实独立验收集。本轮与下段草稿预检尚未提交推送，不宣称新代码远端 CI 已通过。

保存提交为 `dfc9ae7`，远端 [CI](https://github.com/sssssding/Flowplot/actions/runs/38361859189) 已成功。保存后本地新增 [验收草稿只读预检](ACCEPTANCE_PREFLIGHT.md)，尚未提交推送：集中查看审核/来源缺项和逐模型文件问题，不补造数据、不创建冻结集。最新本机全量 401 项中 400 通过、1 项真实符号链接权限跳过；这些新代码未宣称远端 CI 通过。原六模型预检均哈希匹配，但其开发身份等条件仍阻止正式独立验收准备。

按用户要求将当前本地成果提交并推送保存，目标为 `origin/codex/acceptance-handoff`，不合并 main、不修改队友分支、不创建 PR。本节随保存提交发布；实际提交号与推送结果以 Git 分支为准。下方历史段落中的“未提交/推送”仅代表对应开发轮次。

本次保存包含：队友 `10e9b4a` 之上的验收集冻结、正式结果绑定/离线重算、含模型证据的显式导出包，以及 FlowPlot 展示命名/新旧启动入口兼容。最近一次完整本机测试为 378 项：377 通过、1 项真实符号链接权限跳过；命名隐藏 Tk/旧报告/新包往返也通过。本次保存只更新交接文档，不宣称重新运行 COMSOL 或远端 CI。

继续开发时先保留自己的未提交改动，再从此保存分支建立个人分支；示例名称如已存在请另选，不强制重置：

```powershell
git fetch origin
git switch -c codex/resume-work origin/codex/acceptance-handoff
git lfs pull
python -X utf8 -m unittest discover -s tests -q
```

下一步仍优先：真实专业人员审核基准/异常标签、准备至少 10 个真正独立的未见模型并冻结验收、完成真实新用户试用。当前没有真实独立集，不生成替代数据或填写审核身份，T13 AI 参数推荐未开始。先阅读 `NAMING.md`、`ACCEPTANCE_FREEZE.md`、`ACCEPTANCE_RESULTS.md`、`ACCEPTANCE_BUNDLE.md` 和 `PROGRESS.md`。

本机 outputs、模型副本、运行日志、Python 环境及许可证配置不随此次 Git 保存。六个原模型未改；历史工程记录不改指纹冒充新版验收。正式冻结/结果/核验包需匹配源码版本，即使只改标题也不能手改旧哈希复用成绩。

## 历史：从哪里接手

仓库：`sssssding/Flowplot`；本批功能最初在 **`codex/local-handoff`** 分支交接，随后通过 PR #1 合并到 `main`（`cba7a12`）。新开发从最新 `origin/main` 建立自己的功能分支；旧交接分支保留作历史参考。合并不等于专业验收通过。本机接手结果见 [LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md)。

本文是当前交接入口。`PROGRESS.md` 各历史段落中的“尚未提交/推送”描述的是当时状态，不代表包含本文的交接提交仍有那些未提交文件。

## 历史：接收方后续开发（2026-10-13）

当前应用名由用户确认为 **FlowPlot**，推荐双击 `FlowPlot.cmd`；旧 `FlowPilot.cmd`、`flowpilot` 内部包与 `FLOWPILOT_*` 配置保留。最新本机全量 378 项测试中 377 通过、1 项符号链接权限跳过；新旧入口异目录实跑及新名称隐藏 Tk/六份旧报告/新包往返通过，未调用 COMSOL 或修改原模型。历史可见记录仍为改名前版本，不宣称新版本可见/新用户验收。命名、冻结版本影响及回退见 [NAMING.md](NAMING.md)；本轮仍未提交推送，以下各段测试数为对应轮次记录。

接收方已拉取本分支交接提交 `10e9b4a`，在独立本地分支 `codex/acceptance-handoff` 继续开发，没有修改 `feat/local-acceptance` 或 main。用户确认暂无专业审核的独立模型集，因此本轮只补充 [验收集冻结与核验](ACCEPTANCE_FREEZE.md)，不生成冒充独立数据的模型，不填写审核人或验收成绩。以下原交接记录保留为历史起点；本轮新增内容尚未提交或推送。

后续已补充 [正式结果复核](ACCEPTANCE_RESULTS.md)：结果/批量字节绑定、逐模型证据重算及另存中文摘要；正式运行/结果格式 0.2，旧结果不静默升级。当前本机 354 项测试中 353 通过，1 项真实符号链接测试因权限跳过；新增流程测试为模拟输入，不是独立验收。原六模型报告离线复核一致，未修改模型或诊断规则，仍未提交推送。

最新补充 [正式验收证据交接包](ACCEPTANCE_BUNDLE.md)：`acceptance_bundle.py export / verify` 将冻结模型、正式记录和必要原报告复制到新目录，接收方无需原电脑路径或 COMSOL 即可核验并重算。必须显式 `--include-models`，内容包含模型及审核声明，人工检查授权/隐私后自行分享；不自动上传，不将部分结果提升。新增 19 项模拟流程专项；当前全量 373 项测试中 372 通过，1 项真实符号链接测试因本机权限跳过。原六份实测报告再次离线复核 6/6，未重跑 COMSOL 或求解；本轮仍未提交、推送或创建 PR。

## 历史：2026-10-13 队友上次交接

本轮开发与 GUI 工程核验提交截至 `33ea57b`，交接起点为 `origin/feat/local-acceptance`，不是尚未包含这批改进的 main。此节是接手摘要，后续交接文档提交也在同一分支；不自动合并 main、创建 PR 或通知同事。

- 已完成：接手预检、启动与布局修复、基准保存解图组及五类异常关键边界 GUI/API 对照；302 项本机离线测试通过。专业审核、独立模型验收及新用户试用未完成。
- 已共享：源码、测试、协作文档、小型工程证据与仓库已有的六个 Git LFS 原模型。14 个变体和带图组复核 MPH 可按现有说明在同事电脑重新生成，不上传本机 outputs 或日志。
- 未共享：本机未提交的基准 MPH 修改、安装/许可证配置、运行目录和窗口状态。这份本地修改保留给当前用户，不自动覆盖仓库原件或改清单绕过指纹保护。
- COMSOL 窗口按用户要求保留；反向入口的保存提示未处理。它是本机查看状态，不是同事接手或仓库检查的阻塞条件。

同事已有仓库时，先保存自己的未提交改动并确认工作区干净，再从交接分支建立自己的功能分支。下面的新分支名仅为示例；若已存在，请改用自己的任务名，不强制切换或重置：

```powershell
git fetch origin
git switch -c codex/colleague-next origin/feat/local-acceptance
git lfs pull
```

优先顺序：完成实际专业人员的基准/异常标签审核和基准重复求解副本 GUI 日志对照；按 `ACCEPTANCE_PLAN.md` 冻结至少 10 个真正未见且已审核的独立模型并评估；进行真实新用户试用。仅让另一位编码代理复现，不能填写专业审核身份或宣称独立验收。T13 AI 推荐仍不提前开始。

最新未合并改进在 `feat/local-acceptance`：包括接手预检、依赖感知启动器、可读性布局修复及基准保存解图组/五个异常关键边界的 COMSOL GUI 工程核对。若要接手/审阅这批改进，从 `origin/feat/local-acceptance` 建立自己的新分支；不要直接修改队友分支。下列克隆命令以这批改进为目标；稳定 main 的环境与功能仍以 main 文件为准。可见核验及剩余事项见 [DESKTOP_REVIEW.md](DESKTOP_REVIEW.md)、[GUI_REVIEW.md](GUI_REVIEW.md) 和 [正式验收计划](ACCEPTANCE_PLAN.md)。

## 这批交付了什么

- Windows 桌面入口 `FlowPilot.cmd`：选择模型、只读检查、阶段反馈、取消、中文问题证据、模型概览与本地检查历史。
- 批量检查及离线评估：区分完整、部分、超出范围及无效报告；开发回归不能冒充独立 Recall 验收。
- 前后报告对比与离线协作报告包：核对来源、状态与文件完整性；不自动修改模型、发送文件或上传日志。
- 统一报告读取核验、Re 数值溢出/下溢保护和阈值处 4 ULP 末位保护。规则源码已变化，旧报告需要重新检查，不能手改旧指纹冒充当前结果。
- 14 个可再生、未求解的矩形通道变体：单位、阈值、零/负速度、空选择、组合问题、材料及三个尺寸组；原六个模型保持不变。
- 配套源码、测试、中文文档和三个小型实测摘要。新增 MPH、生成驱动、日志、桌面会话与本机路径配置留在忽略目录中，不随本批 Git 同步。

具体操作见 [桌面](DESKTOP.md)、[批量](BATCH_CHECK.md)、[概览](MODEL_OVERVIEW.md)、[历史](CHECK_HISTORY.md)、[对比](REPORT_COMPARISON.md)、[协作报告](REPORT_PACKAGE.md)、[读取核验](REPORT_VALIDATION.md)、[数值策略](NUMERIC_SAFETY.md)、[变体回归](REGRESSION_FAMILY.md)。

## 队友拉取与环境

需要 Git、Git LFS、带 Tcl/Tk 的 Python 和项目依赖。真实模型读取/生成还需要本机 COMSOL 6.3、适用许可证与模块；已验证版本为 6.3.0.290。开发机测试环境为 Python 3.13.5 / jsonschema 4.25.1 / Tcl/Tk 8.6.15，不代表已经验证所有 Python 或 COMSOL 版本。

首次克隆：

```powershell
git lfs install
git clone --branch feat/local-acceptance https://github.com/sssssding/Flowplot.git
cd Flowplot
git lfs pull
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
```

已有仓库：先 `git status` 保存自己的未提交内容，不直接覆盖或重置；工作区确认干净后执行 `git fetch origin`，从 `origin/main` 建立自己的新分支，例如 `git switch -c codex/your-task origin/main`（替换任务名）。若要更新现有同名分支，仅使用快进拉取；遇到分叉先核对双方提交，不强推。

审阅这批未合并改进时，将上句起点替换为 `origin/feat/local-acceptance`。本机源码或格式变化后重新生成对应验证证据，不仅修改旧摘要的哈希；2026-10-13 当前本机离线测试为 302 项，GUI 记录一致性测试不代替真实界面或专业审核。

运行前执行 [只读接手预检](PREFLIGHT.md)，使用与桌面/CLI 相同的 Python 环境，提前识别依赖缺失、LFS 指针和本地模型哈希变化。预检不自动覆盖或恢复文件。

六个原始 MPH 应完整下载，不是 Git LFS 指针；`data/fixtures/cases/manifest.json` 保存其 SHA-256。正式检查会拒绝指针；运行原六模型批量检查也会核对清单哈希。不要重新保存基准后再改 manifest 来绕过保护。

源码与 Java 入口模板按 LF 换行保存，`.gitattributes` 已覆盖 `*.java.in`，避免 Windows 克隆时换行转换使实测来源指纹失配。修改源码后应重新生成相应证据，不能直接替换摘要内的哈希。

## 如何运行与重现

双击根目录 `FlowPlot.cmd`（旧 `FlowPilot.cmd` 仍兼容），选择 COMSOL 的 `Multiphysics` 安装文件夹；不要把许可证文件、账号或本机安装路径写入仓库。桌面默认只读检查，不执行求解。

下列命令中的 `<COMSOL_ROOT>` 替换为自己的安装位置；每个输出目录必须是新的，重复执行请换名字：

```powershell
# 原六模型：真实读取，各加载两次
./.venv/Scripts/python.exe -X utf8 src/flowpilot/check_suite.py --comsol-root '<COMSOL_ROOT>' --output-dir outputs/check-suites/team-001 --loads 2

# 同一批报告：不调用 COMSOL 的离线复核
./.venv/Scripts/python.exe -X utf8 src/flowpilot/check_suite.py --reports-root outputs/check-suites/team-001 --output-dir outputs/check-suites/team-001-offline

# 生成并检查 14 个新变体：不求解
./.venv/Scripts/python.exe -X utf8 src/flowpilot/regression_family.py --comsol-root '<COMSOL_ROOT>' --output-dir outputs/regression-families/team-001 --loads 2

# 真实桌面功能测试：隐藏窗口，不是人工界面验收
./.venv/Scripts/python.exe -X utf8 scripts/smoke_desktop.py --comsol-root '<COMSOL_ROOT>' --reports-root outputs/check-suites/team-001 --output-dir outputs/desktop-smoke/team-001
```

若只想读已有协作报告，不需要调用 COMSOL；选择含 `run.json` / `diagnosis.json` 的单模型目录或完整报告包，不能选择批量汇总根目录。普通检查目录可能包含模型副本、请求和日志，分享前应使用报告包入口并人工检查参数/自由文本，不能把哈希当作者签名或全文脱敏。

14 个变体的 MPH 未提交。队友运行生成器即可得到自己的副本；COMSOL 元数据可能使重新保存的二进制哈希不同，以本次生成 manifest 为准，不要求不同电脑生成的 MPH 字节完全相同。

## 已验证的事实

- 本机离线自动测试 **274 项通过**，其中包含明确标记的模拟故障测试；测试输出中的模拟 failed/unscored 和 1.500 秒求解值不是新的真实失败或求解实验。
- 原六模型及 14 个新变体分别各加载两次，规则 code 集合符合预期；变体额外核对尺寸、SI 求值、空选择及覆盖证据，离线复核一致。未求解这些故障/变体模型。
- 最初变体回归暴露名义 Re=2000 的末位浮点误报，保留 13/14 的失败记录后修复；最终 14/14 通过，Re=2001 仍报警。该保护不是物理容差或转捩结论。
- 桌面隐藏窗口完成两次真实检查、一次批处理启动后取消，以及报告展示、概览、对比、历史和协作导出/重读；损坏或矛盾报告被拒绝。原六个模型哈希不变。
- 版本化实测摘要：`data/fixtures/batch_regression.json`、`desktop_smoke.json`、`regression_family.json`。原始日志和运行目录不随 Git 共享，摘要不是完整复现实验环境。

GitHub Actions 当前配置只运行离线测试，不运行 COMSOL 或可见窗口。本机通过不能宣称远端 CI 已通过，推送后应在 GitHub 检查实际运行结果。

## 下一位开发者优先做什么

1. 阅读 `PROJECT_SCOPE.md`、本文、`PROGRESS.md` 和 `GUI_REVIEW.md`；确认六个 LFS 模型完整、原文件未被自己改动，先运行离线测试。
2. 人工可见窗口试用，记录布局、错误理解及新用户耗时；隐藏窗口不代表完成“新用户 5 分钟”或“十个未见模型”验收。
3. 按 `BASELINE_REVIEW.md` / `BOUNDARY_CASES.md` 完成基准与异常的 GUI、物理和专业标签审核；审核人/日期仅在真实审核后填写。
4. 建立真正独立、专业审核的验收集，按 `BATCH_CHECK.md` 评估 Recall 和误报；同一基准的受控变体不能随机拆成独立验收集。
5. T12 仅开始当前矩形族的配置差异收集，还缺更多模型族和求解参数—性能实验；T13 AI 推荐未开始。范围扩大前更新范围/决策并补真实证据。

多人同时开发应各用分支、不同输出目录；不要同时修改同一个 MPH。禁止覆盖原基准、自动清理队友输出、强推覆盖提交或更改 COMSOL 安全偏好。改动后同步文档与测试，提 PR 由非作者审阅，再考虑合并；本次不自动创建 PR 或合并。
