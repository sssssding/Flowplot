# FlowPlot

FlowPlot 是一个面向 COMSOL 二维稳态层流模型的智能检查原型。第一版聚焦于读取 Inlet、Outlet 和 Wall 边界，发现边界缺失、冲突、方向异常及工况范围风险；在解析与规则检查闭环稳定后，再扩展求解参数推荐。

应用当前名称为 **FlowPlot**：来自团队决定保留的笔误，未来是否改名另行决定。FlowPilot 是历史名称；内部 `flowpilot` 包、`FLOWPILOT_*` 环境变量、旧模型及报告格式保留兼容。Windows 推荐入口为 `FlowPlot.cmd`，旧 `FlowPilot.cmd` 仍可用，见 [命名与兼容说明](docs/NAMING.md)。

## 当前阶段

- 已冻结 MVP 范围。
- 基准模型已完成实际求解、三次重新加载验证与十次只读解析；GUI 设置已核对，专业复核待完成。
- 已加入模型生成/清单脚本、实测证据和 GitHub Actions fixture 测试。
- 五类未求解异常模型已生成并各重复读取五次；首版确定性诊断与 JSON Schema 已实现。
- 已提供指定 `.mph` 路径的只读检查入口，输出结构化证据和中文诊断报告，见 [使用说明](docs/MODEL_CHECK.md)。
- 已提供 [批量检查与评估](docs/BATCH_CHECK.md)，汇总漏报、误报及检查覆盖率，开发回归结果不冒充独立验收成绩。
- 已提供 [本地桌面界面](docs/DESKTOP.md)：Windows 双击 `FlowPlot.cmd`，选择模型并查看中文诊断；人工界面试用与独立端到端验收待完成。
- 已提供 [前后报告对比](docs/REPORT_COMPARISON.md)：桌面或脚本查看新增、未再报告和证据变化；不同配置或不完整报告不直接比较，不将问题消失当作修复验收。
- 已提供 [检查历史](docs/CHECK_HISTORY.md)：找回本地报告及失败/取消记录，打开时重新核验；不自动清理文件或接管旧进程。
- 已提供 [模型概览](docs/MODEL_OVERVIEW.md)：查看报告中的尺寸、材料和声明/实际生效边界；缺少入口/出口带有具体节点与选择证据，不只给结论。
- 已提供 [离线协作报告包](docs/REPORT_PACKAGE.md)：导出诊断与概览，先检查接收端容量、写后重新导入核对快照；不带模型或运行日志，敏感参数仍需人工审阅。
- 已从基准保存解导出速度云图、截面曲线与可复现采样，见 [复核材料](docs/BASELINE_REVIEW.md)；专业审核待完成。
- 已完成基准连续五次自动重新求解，记录日志、耗时与结果一致性，见 [重复求解](docs/BASELINE_SOLVES.md)；GUI 日志对照待完成。
- 当前诊断只验证自建矩形通道模型族；专业标签审核与独立验收集待完成。
- 已加固 [Re 数值稳定性](docs/NUMERIC_SAFETY.md)：避免中间溢出/下溢导致漏报或误报，最终派生值无法表示时明确标记部分检查未完成。
- 已统一 [报告读取核验](docs/REPORT_VALIDATION.md)：缺字段或状态矛盾不展示/计分，读取有大小限制，解析与来源指纹使用同一份字节。
- 已提供 [真实变体回归](docs/REGRESSION_FAMILY.md)：从基准副本生成并检查 14 个未求解样本，覆盖单位、阈值、空选择、多问题和三个通道尺寸；开发样本不是独立验收集。
- 已提供 [验收集冻结与核验](docs/ACCEPTANCE_FREEZE.md)：接收真实已审核清单，固定模型/标签/程序版本，运行前后核对；不会生成独立数据或自动认证审核身份。
- 已提供 [验收草稿只读预检](docs/ACCEPTANCE_PREFLIGHT.md)：集中列出审核/来源缺项和逐模型文件问题，不填造信息、不创建冻结集；文件匹配不等于独立验收通过。
- 已统一 [批量评分与正式冻结门槛](docs/ACCEPTANCE_ELIGIBILITY.md)：旧条件不足、登记开发变体或来源声明缺失时保留开发统计，但不输出独立验收达标结论。
- 已加固 [批量输入稳定性](docs/BATCH_STABILITY.md)：清单解析与指纹同源，发布前后复核程序/模型/报告及实际产物；运行中变化不作为成功结果。
- 已统一 [报告目录边界](docs/REPORT_BOUNDARIES.md)：读取前拒绝报告根目录链接，批量和正式运行输出不写入输入报告树，避免意外跟随路径或污染协作包。
- 已提供 [正式结果离线复核](docs/ACCEPTANCE_RESULTS.md)：核对结果与原报告绑定并重新计算成绩，损坏或失败记录不提升为验收通过；支持另存中文复核摘要。
- 已提供 [正式验收证据交接包](docs/ACCEPTANCE_BUNDLE.md)：显式确认后复制冻结模型与证据，接收方可离线独立重算；包含模型及审核信息，不自动上传或承诺脱敏。
- 新增 [本地 AI 参数推荐原型](docs/AI_RECOMMENDATION.md)：`FlowPlotAI.cmd` 启动推荐页签，用真实副本校准学习相对容差/线程数的候选耗时。仅适用同一基准与校准环境，不自动改模型；独立性能验收未完成。

## 仓库结构

```text
FlowPlot/
├─ docs/          协作规范、设计蓝图、注意事项和进度
├─ models/        COMSOL 模型说明；二进制模型需使用 Git LFS
├─ src/           源代码
├─ tests/         自动化测试与测试说明
├─ data/          小型、可公开的结构化测试数据
├─ scope.md       初始 MVP 范围记录
└─ README.md      项目入口
```

## 快速开始

当前完整开发保存点为 `codex/acceptance-handoff`，包含尚未合并 main 的队友改进和验收工具。继续这批工作应从 `origin/codex/acceptance-handoff` 建立自己的功能分支；稳定 main 不代表已包含本页全部新功能。先阅读 [协作接手说明](docs/HANDOFF.md)，再执行 [只读接手预检](docs/PREFLIGHT.md)，确认依赖与模型文件。说明包含拉取方式、运行命令、实测证据和未完成验收事项。

1. 阅读 [项目范围](docs/PROJECT_SCOPE.md) 和 [技术蓝图](docs/BLUEPRINT.md)。
2. 按 [协作规范](docs/COLLABORATION.md) 创建 Issue 和功能分支。
3. 开发前查看 [注意事项](docs/NOTES.md) 与 [项目进度](docs/PROGRESS.md)。
4. 建立或验证 COMSOL 基准模型时，使用 [基准模型规范](docs/BASELINE_MODEL.md)。
5. 运行脚本和测试时，参照 [开发与验证](docs/DEVELOPMENT.md)。
6. 检查指定的模型文件时，使用 [只读文件检查入口](docs/MODEL_CHECK.md)。
7. 使用窗口操作时，按 [桌面界面说明](docs/DESKTOP.md) 启动 `FlowPlot.cmd`。

## 一句话目标

> FlowPlot 第一版面向 COMSOL 二维稳态层流模型，自动读取 Inlet、Outlet 和 Wall 边界条件，并对边界缺失、冲突、方向异常和工况风险进行可解释检查。
