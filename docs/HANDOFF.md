# 协作接手说明（2026-10-11）

## 从哪里接手

仓库：`sssssding/Flowplot`；本批功能最初在 **`codex/local-handoff`** 分支交接，随后通过 PR #1 合并到 `main`（`cba7a12`）。新开发从最新 `origin/main` 建立自己的功能分支；旧交接分支保留作历史参考。合并不等于专业验收通过。本机接手结果见 [LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md)。

本文是当前交接入口。`PROGRESS.md` 各历史段落中的“尚未提交/推送”描述的是当时状态，不代表包含本文的交接提交仍有那些未提交文件。

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
git clone --branch main https://github.com/sssssding/Flowplot.git
cd Flowplot
git lfs pull
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -q
```

已有仓库：先 `git status` 保存自己的未提交内容，不直接覆盖或重置；工作区确认干净后执行 `git fetch origin`，从 `origin/main` 建立自己的新分支，例如 `git switch -c codex/your-task origin/main`（替换任务名）。若要更新现有同名分支，仅使用快进拉取；遇到分叉先核对双方提交，不强推。

运行前执行 [只读接手预检](PREFLIGHT.md)，使用与桌面/CLI 相同的 Python 环境，提前识别依赖缺失、LFS 指针和本地模型哈希变化。预检不自动覆盖或恢复文件。

六个原始 MPH 应完整下载，不是 Git LFS 指针；`data/fixtures/cases/manifest.json` 保存其 SHA-256。正式检查会拒绝指针；运行原六模型批量检查也会核对清单哈希。不要重新保存基准后再改 manifest 来绕过保护。

源码与 Java 入口模板按 LF 换行保存，`.gitattributes` 已覆盖 `*.java.in`，避免 Windows 克隆时换行转换使实测来源指纹失配。修改源码后应重新生成相应证据，不能直接替换摘要内的哈希。

## 如何运行与重现

双击根目录 `FlowPilot.cmd`，选择 COMSOL 的 `Multiphysics` 安装文件夹；不要把许可证文件、账号或本机安装路径写入仓库。桌面默认只读检查，不执行求解。

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
