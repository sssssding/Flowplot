# 协作接手说明（更新至 2026-10-13）

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
