# 开发与验证

## 可复现检验与第二台电脑

新增 `scripts/verify_delivery.py --model-root '<清单原件所在根目录>' --comsol-root '<Multiphysics>' --output-dir '<输入根目录以外的新目录>'`，记录全量测试与六模型各两次只读检查、离线复算和输入稳定性。省略 COMSOL 参数时仅为离线核验，不提升真实模型/界面/许可证状态；输出不是完整项目验收结论。已有本地模型修改时，使用经过 manifest 核对的独立原件树，不恢复原文件。

第二台 Win10/COMSOL 6.3 操作见 [SECOND_PC_VALIDATION.md](SECOND_PC_VALIDATION.md)。`validate_recommendation.py` 只分析同机已有冷求解数据，本身不求解；新增十项合成专项及实际历史基准分析不作为独立性能结论。当前完整目标证据见 [COMPLETION_AUDIT.md](COMPLETION_AUDIT.md)。

后续推荐解释字段与数字显示测试位于 `test_portable_recommend.py`，最新完整 AI 来源为 `ai_explanation_smoke.json`（29 项隐藏 Tk），之前五份摘要原字节保留。旧工程摘要中的便携推荐模块指纹只说明当时版本；本次不改检查链路、训练文件或正式冻结集合。网格迁移约束见 [MESH_TRANSFER.md](MESH_TRANSFER.md)，不是新增网格识别能力。

报告按钮修复后的当前来源为 `ai_report_button_smoke.json`（30 项隐藏 Tk，外部查看器打开被拦截）；专项 `test_recommend_report_button.py` 验证零参数按钮与显式预览目录两种调用约定。父类新增按钮/回调时应核对子类签名，不只直接调用显式预览 API。前六份 AI 摘要保持原字节；可见核验仍按 [UI_VERIFICATION_BLOCKER.md](UI_VERIFICATION_BLOCKER.md) 保留未完成。

## 环境

验收修复合并 main 后，从 `origin/main` 建立个人分支，当前接手入口见 `HANDOFF.md` 顶部。AI 页签按显示快照的 run/diagnosis 指纹核对，测量输出不能位于输入报告树；变更这两条保护时运行 `test_ai_review_safety.py`、`test_benchmark_portable.py` 及全量回归。重新运行 `scripts/smoke_ai_recommendation.py` 后另存新证据，不改前三份历史 AI 摘要的指纹。

继续接手补充推荐发布前复核和 CLI 输出目录保护，专项为 `test_recommend_publication.py`。最新实跑绑定在 `ai_publication_smoke.json`（23 项隐藏 Tk），前四份 AI 摘要保持原字节。测试若因受限运行环境无法解析其自建临时目录，应在允许该测试路径的环境复测，不修改程序规则或降级来源核验来让测试通过。

- COMSOL Multiphysics 6.3，已验证构建号 290。
- PowerShell 7（Windows）。
- Python 3.12 64 位（当前验证环境），以及 `requirements-dev.txt` 中的 JSON Schema 验证依赖。
- 接手环境补充验证：Python 3.13.5 64 位、jsonschema 4.25.1；原有 Python 3.12 环境仍用于 CI。
- Git 与 Git LFS。

不在源码中写死 COMSOL 安装目录。以下 `<COMSOL_ROOT>` 指包含 `bin/win64` 的 Multiphysics 安装目录。

## 生成基准模型

在仓库根目录运行：

```powershell
./scripts/build_baseline.ps1 -ComsolRoot '<COMSOL_ROOT>'
```

脚本会编译 `src/comsol/BaselinePipe2D.java`、求解基准模型、保存 `.mph`、重新加载求解三次，并检查质量守恒、速度、壁面内部速度和结果漂移。

- 模型：`models/baseline_pipe_2d_laminar.mph`
- 本机日志与中间模型：`outputs/baseline/<运行时间>/`
- 本机验证报告：`outputs/baseline/verification.json`

为保护已经存在的基准模型，生成脚本在目标 `.mph` 已存在时停止。重新生成前，将旧模型移动到单独的存档目录。失败后 COMSOL 自动保存的中间模型不能作为已验收的基准文件。

COMSOL 的编译器或批处理有时在内部失败时仍返回退出码 0。脚本同时检查编译产物时间、验证标记与 JSON 报告，避免把退出码误当作成功证明。

## 验证加载与枚举

```powershell
./scripts/inspect_baseline.ps1 -ComsolRoot '<COMSOL_ROOT>'
```

工具通过 Java API 十次加载本地基准模型，枚举实际组件、几何、研究、物理场、feature 类型、启用状态、选择结果及一组常用边界表达式。十次 JSON 必须完全相同。

这是基准模型上的只读技术验证。该脚本固定读取基准文件；指定其他 `.mph` 文件并输出诊断报告时，使用 [指定模型的只读检查](MODEL_CHECK.md)。两者均未覆盖所有物理场、所有边界模式、嵌套 feature 和空间表达式求值。`u0` 等字段可能在当前边界模式下不生效，规则引擎必须先判断 `BoundaryCondition`，不能把所有存储属性同时视为有效设置。

`ModelInventory` 现输出 `inventory-0.2`，增加几何/材料证据、声明与有效选择、入口速度模式及 COMSOL 带单位求值。新诊断归一化输出为 `diagnostic-0.1`，对应 `schema/diagnostic-model.schema.json`。旧 `inventory-0.1` 与人工 `0.1.0` fixture 保留作历史参考，不应误认成新工具的自动输出。

新增解析还包含可选的 `rectangle_rotation_expression` 几何证据，拒绝把旋转矩形的包围盒高度用于当前通道规则。旧版 fixture 保持可读；本次真实清单通过新文件入口生成，不覆盖历史证据。

## 异常模型与只读诊断

样本生成或复核见 [异常模型](BOUNDARY_CASES.md)，规则约束见 [规则说明](RULES.md)。异常模型不运行求解器，并清除继承的解。

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
./.venv/Scripts/python.exe src/flowpilot/diagnostics.py data/fixtures/cases/baseline.json --output outputs/diagnosis/baseline.json
./.venv/Scripts/python.exe src/flowpilot/diagnostics.py data/fixtures/cases/high_reynolds.json --output outputs/diagnosis/high_reynolds.json --reynolds-warning 2000
```

输出包含归一化模型和诊断证据。已存在的报告拒绝覆盖，重复运行请换输出路径。`checked` 不是“物理通过”；需读取 findings，`partial` / `unsupported` 也不能当作正常模型。

本机系统 Python 3.14 的依赖解析曾因没有匹配的 rpds wheel 失败，已选用 64 位 Python 3.12 测试环境；虚拟环境不提交仓库。不要为安装依赖关闭证书校验。

## 无 COMSOL 的快速测试

```powershell
./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

测试核对版本化 fixture 与实际 API 清单的边界一致性，重新计算质量守恒误差及重复性指标，并检查六个真实模型清单的规则输出、Schema、不支持范围、未求值表达式、默认壁面覆盖与 CLI 不覆盖行为。GitHub Actions 安装依赖后执行这些测试，不执行需要 COMSOL 许可的真实求解；fixture 测试不能代替本机集成验证。

## 更新实验记录

重新生成模型后，将本机 JSON 报告中经审核的证据更新到 `data/fixtures/`，同步更新 `docs/BASELINE_MODEL.md` 中的指标、SHA-256 和验证范围。保留原始日志用于本机排查，但不上传含计算机信息的运行日志。

## 基准保存解的图像复核

使用 [速度场复核材料](BASELINE_REVIEW.md) 中的命令，生成原生 COMSOL 速度云图、截面曲线、采样 JSON 和独立的带图组模型副本。入口只接受 manifest 中的已提交基准，不重新求解；专业复核状态仍需团队确认。

## 基准自动重复求解

使用 [重复求解入口](BASELINE_SOLVES.md) 在独立副本上连续重新求解默认 5 次。每次先清除保存解，保留原求解器设置，记录耗时、原生日志、模型副本和指标一致性。该入口实际运行求解器，需要许可证；与只读检查及保存解图像导出分开使用，不运行异常模型。

## 批量检查与离线评估

使用 [批量检查入口](BATCH_CHECK.md) 对清单中的模型串行只读检查，或直接复核已有报告。汇总区分完整检查覆盖率、模型级 code 集合匹配和独立验收资格；未审核的开发标签不能变成独立 Recall 结论。

评分资格现在额外复用真正冻结门槛和全部开发登记，旧条件不足时保留开发指标但阻止独立达标声明，见 [资格一致性](ACCEPTANCE_ELIGIBILITY.md)。这会改变 `check_suite.py` 字节指纹；旧冻结/正式记录不能手改哈希升级。当前隐藏桌面来源绑定以 `desktop_smoke_eligibility_gate.json` 的新实测为准，旧摘要保留历史。

后续 [批量稳定性加固](BATCH_STABILITY.md) 增加同字节清单绑定、前后来源/报告核对及实际输出复核；检测到变化或写入失败不发布成功终态。当前隐藏桌面来源绑定以更新的 `desktop_smoke_batch_stability.json` 为准，前两份记录保留历史。正式读取器验证新增可选绑定，但不补造旧记录的稳定性证明。

最新 [报告目录边界](REPORT_BOUNDARIES.md) 要求收到的普通/协作报告根目录为实际目录，通用/正式运行输出在输入报告树之外，创建目录前检查；运行中目录变链接失败停止。当前来源记录为 `desktop_smoke_report_boundaries.json`，前三份桌面证据原样保留；本轮无规则、Java 或模型改动，涉及的正式源码指纹不可手改旧记录适配。

当前 [轻量协作包导出](REPORT_PACKAGE.md) 另补容量预检和最终重新导入/快照一致性检查。`report_package.py` 不属于正式冻结源码集合，本轮不改变冻结版本。此次未重跑 COMSOL；来源验证分层保留 `desktop_smoke_report_boundaries.json` 的未变模块记录，并使用 `report_export_offline_smoke.json` 核对当前导出模块和六份旧报告的离线隐藏窗口/新包往返。四份旧完整桌面摘要不改字节，不把本轮离线检查说成新 COMSOL 或按钮集成运行。

## 受控模型变体回归

使用 [真实变体入口](REGRESSION_FAMILY.md) 在新目录生成 14 个未求解 COMSOL 模型，随后走正式批量检查，核对问题集合、尺寸、SI 求值和空选择证据。输入基准固定哈希；尺寸重建后更新坐标选择，不硬编码边界编号。独立验收标记始终为 false，不能把这些开发数据用于声明独立 Recall 或 AI 推荐成绩。阈值规则变动后，应重跑原六模型及桌面流程，保留历史失败结果，不改旧指纹。

## 本地桌面检查

桌面操作见 [本地桌面界面](DESKTOP.md)：双击 `FlowPlot.cmd`（旧 `FlowPilot.cmd` 兼容）或运行 `python src/flowpilot/desktop.py`。桌面调用同一个只读入口，通过独立会话和取消请求控制自己的后台进程；新增离线测试不依赖 Tk 窗口，真实隐藏窗口集成测试另行运行。内部包与环境变量不改名，历史证据处理见 [命名约定](NAMING.md)。

阶段提示读取有大小限制的 `progress.jsonl`，忽略残缺/异常条目，不以进度事件判定成功。窗口记录保存失败按失败收尾，取消请求保存失败保持运行并允许重试；相关异常通过离线故障注入测试覆盖，不需要修改安装或目录权限。

通过 [检查历史](CHECK_HISTORY.md) 浏览桌面会话或批量结果：后台线程只读有限元数据，打开时才重新核验报告；不以磁盘 `running` 判断进程存活，不自动清理或恢复会话。离线测试不初始化 Tk，隐藏窗口验证另外检查历史选择和结果展示。

结果区的 [模型概览](MODEL_OVERVIEW.md) 读取诊断中已经归一化并通过结构验证的证据，区分声明/实际生效选择和未求值状态，不额外读取模型。缺失入口/出口补充节点与选择证据后，当前规则源码哈希变化，应重新生成真实批量与桌面证据，不能手改旧报告哈希。

## 检查报告前后对比

使用 [报告对比入口](REPORT_COMPARISON.md) 离线对比两份单模型报告，或在桌面展示本次报告后点击“与前次报告对比…”。先核对完整性及规则/模板/阈值一致性，再按规则、节点与边界分组比较，不以问题消失证明修复通过。

## 离线协作报告

协作时使用 [离线报告包](REPORT_PACKAGE.md) 单独导出诊断和概览，不直接分享含模型副本、日志和绝对路径的整个检查目录。可用桌面按钮或 `report_package.py`，不依赖 COMSOL；导出保留诊断证据但不是全文脱敏。包清单完整性核验被桌面及对比入口共同复用，新增格式或修改导出源码后应重新执行隐藏窗口往返测试并更新实测摘要，不手改证据哈希。

## 诊断数值稳定性

数值边界测试见 [诊断数值稳定性](NUMERIC_SAFETY.md)。只对已经带单位求值的数值合并 Re 比值，不执行 COMSOL 表达式。输入无效与派生量超出范围分开；后一种保留证据并标记 `partial`。修改规则后须重新生成真实批量及桌面摘要，不能用离线反例冒充 COMSOL 实模验证。

## 统一报告核验

报告消费入口统一走 [共同报告核验](REPORT_VALIDATION.md)，批量可额外限制来源，但不能降低条目结构/状态一致性或绕过协作包校验。共享字节读取在 `report_io.py`，不要解析后另读文件计算来源指纹。相应离线合成记录测试与真实隐藏窗口证据分开，改动读取模块后需更新桌面实测源码指纹。

## 正式验收集的冻结与核验

准备清单时先用 [草稿只读预检](ACCEPTANCE_PREFLIGHT.md) 的 `acceptance_preflight.py --manifest ... --model-root ... [--json]`，查看多字段缺项及逐模型状态。入口只读且复用真正冻结门槛，不产生模型/审核数据、冻结目录或验收成绩；0 仅表示可进入准备，2 为待补，1 为输入/登记无效。

按 [验收集冻结](ACCEPTANCE_FREEZE.md) 使用 `acceptance_dataset.py freeze / verify / run`。输入来自真实专业审核，至少 10 个未见模型；原六模型和已登记 14 变体不能重标为独立集。程序只固定输入并检查指纹，不认证身份/源头，也不提供填好“审核通过”的示例数据。

新增离线测试明确使用模拟字节与合成声明，不能当作真实独立模型通过的证据。缺少真实验收集时先保留验收待办，不填造人名、日期、独立 Recall 或 AI 推荐结果。通用批量入口仍兼容，正式流程应核验冻结集及顶层 `result.json` / `run.json`，不绕过失败去引用中间子目录成绩。

正式运行/结果格式为 0.2，绑定结果和批量产物；使用 [结果复核](ACCEPTANCE_RESULTS.md) 的 `acceptance_result.py` 核对来源并从单模型报告重算，不能直接读取保存分数当作通过。结果复核退出码 0 只表示完整记录有效读取，Recall 是否达标另看指标；不认证身份、物理或界面验收。复核程序也纳入冻结源码指纹，旧格式不自动升级。

## 正式验收证据交接

正式结果需要交给另一台电脑重算时，使用 [证据交接包](ACCEPTANCE_BUNDLE.md) 的 `acceptance_bundle.py export / verify`。导出须显式 `--include-models`，只复制到新目录，不自动上传；接收方先核对完整性再重算，不能只信包内中文摘要。包包含冻结 MPH 和审核信息，与桌面轻量单模型报告包严格区分；测试均为模拟输入，不补造真实独立验收集。

## 本地 AI 推荐原型

使用 `FlowPlotAI.cmd`，或 `python src/flowpilot/recommend_ui.py`，在原检查流程上增加推荐页签。独立副本校准、学习模型构建与离线推荐见 [AI_RECOMMENDATION.md](AI_RECOMMENDATION.md)。仅校准入口实际求解；训练、推理和读取报告不调用 COMSOL。不使用开发基准的重复测量宣称独立模型推荐达标。

## API 参考（原只读功能）

- [COMSOL 6.3 Named selections](https://doc.comsol.com/6.3/doc/com.comsol.help.comsol/comsol_api_general.47.56.html)
- 本机 COMSOL 帮助：Java API、Stationary solver 与 COMSOL Commands on Windows。
