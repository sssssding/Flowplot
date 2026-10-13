# 批量只读检查与评估

本入口一次检查一组模型，汇总漏报、误报与未完成项。它复用 `MODEL_CHECK.md` 的只读流程，不求解、不保存原始模型，不扩展当前矩形通道支持范围。

## 真实检查

```powershell
python src/flowpilot/check_suite.py --manifest data/fixtures/cases/manifest.json --comsol-root '<COMSOL_ROOT>' --output-dir outputs/check-suites/run-001 --loads 2 --timeout 300
```

运行前校验全部模型的路径和 SHA-256；任一源文件缺失或哈希不符则不启动任何检查。模型路径相对于 `--model-root`（默认仓库根目录），不能越过该目录。清单最多 50 个模型，ID 与文件哈希不得重复，避免同一文件重复计分。

检查串行执行。某个模型读取失败时保留其错误并继续检查其他模型；用户中断则停止整组运行。每个模型独立复制、记录日志和检查重复解析一致性，详情仍在子目录的 `report.md` 中。

输出结构：

```text
run-001/
  baseline/             # 各 case_id 子目录
    input.mph / inventory.json / diagnosis.json / report.md / run.json / 日志
  missing_inlet/ ...
  summary.json          # 指标、每个模型的漏报/误报及验收阻断项
  report.md             # 中文汇总
  run.json              # completed / incomplete / failed / cancelled
```

`completed` 只代表每个模型均完成当前规则检查，不等于没有边界问题或标签完全匹配。部分检查、超出范围、模型失败、报告缺失或来源不符都会使整组状态为 `incomplete`，不会显示成干净模型。

## 无 COMSOL 的离线复核

```powershell
python src/flowpilot/check_suite.py --manifest data/fixtures/cases/manifest.json --reports-root outputs/check-suites/run-001 --output-dir outputs/check-suites/evaluation-001
```

`--comsol-root` 与 `--reports-root` 只能选择一个。离线模式不加载模型、不调用 COMSOL，只读已有报告。它核对模型哈希、成功运行状态、Re 阈值、当前规则源码与枚举源码的哈希，以及诊断文件内容哈希。旧版报告没有这些来源字段时会记为 `unscored`，请重新检查生成，不能补造完成记录。

批量复用 [统一报告读取](REPORT_VALIDATION.md)，与桌面一致检查必要问题字段及状态矛盾；只有 code、没有等级或证据的记录不计分。读取协作包时还检查包内全部文件，不能因 JSON 完整而绕过损坏的中文报告。JSON 有重复字段、非有限数值、过深嵌套或超过读取上限时记为 `unscored`，不当作无问题模型。

每次输出目录必须是新目录，已有结果不会覆盖。退出码：`0` 为所有模型完整检查且规则集合均匹配；`1` 为入口或整组处理错误；`2` 为检查覆盖不完整；`3` 为完整检查后发现规则标签不匹配。退出码 `0` 也不代表物理正确或专业验收通过。

批量运行现检查 [输入稳定性与发布保护](BATCH_STABILITY.md)：清单由同一次字节读取解析和计算指纹，发布前后重新核对程序/登记、模型/报告及实际产物。发现变化时整组失败；即使留下汇总文件，也不能绕过 failed/cancelled 终态引用成绩。需要完整程序及开发登记，运行目录新增可选稳定性/汇总绑定字段，不把这些字段当签名或独立验收凭证。

[报告目录边界](REPORT_BOUNDARIES.md) 要求离线输入根目录为实际目录，输出在其外部，不能写进任何输入报告子目录。单个链接案例不读取目标、记为 unscored；运行中根目录变化停止并记录 failed。正式外层也在创建目录前检查，不自动追踪或修复链接。

## 指标口径

- 评估单位为“模型 × 规则 code”。同一模型同一 code 出现多次只计一次；当前不评估具体边界定位、严重等级或解释质量。
- 每个完整 `checked` 报告分别计算预期和实际 code 的交集、漏报集合、误报集合，再汇总 micro Precision、Recall、F1 及逐规则指标。
- 分母为 0 时返回 JSON `null`，不把没有正例的样本集记作 Recall 100%。
- `partial`、`unsupported`、失败和来源不匹配的报告不纳入完整报告指标；另外明确显示完整检查覆盖率、未评估预期标签数，以及将未评估正例视为未发现时的 Recall 保守下界。不能仅引用完整报告上的高 Recall 隐藏失败样本。
- 模型级完全匹配比例的分母始终为全部清单模型，未完成模型不算匹配。

当前 [六模型清单](../data/fixtures/cases/manifest.json) 是开发回归集，工程标签仍待专业审核。即使逐项匹配，也不会输出独立验收达标结论。

Re 派生量超出非零有限表示范围时诊断为 `partial`，不纳入完整检查计分。修复数值稳定性后规则指纹已变化，旧报告记为来源不匹配，应重新检查，而不是手工修改哈希。极端数值反例是离线合成测试，不是新增独立验收模型，详见 [数值稳定性](NUMERIC_SAFETY.md)。

本机真实批量验证：六个模型各重复加载两次，6/6 完整检查、6/6 code 集合匹配；离线复核得到相同结果。小型可共享证据见 [批量回归摘要](../data/fixtures/batch_regression.json)。该摘要保持 `acceptance_eligible: false`，独立验收达标字段为 `null`。

## 真正的独立验收清单

复用 `case-manifest-0.1` 结构，另建清单及模型目录，不修改已有开发集。待独立模型真实建立并完成专业审核后填写：

- 顶层：`independent_acceptance_set: true`、`label_status: "expert_reviewed"`；可显式记录 `reynolds_warning`（默认 2000）。
- 顶层另有真实 `acceptance_declaration`：数据集 ID、独立性审核人/已发生日期及三项独立性确认；字段定义见 [冻结要求](ACCEPTANCE_FREEZE.md)。
- 每个案例：`case_id`、相对 `model_path`、实际 `sha256`、审核后的 `expected_codes`，以及真实的 `reviewed_by`、标准且已发生日期 `reviewed_date`、`used_for_rule_development: false`、`created_by`、`origin_reference`、`independence_group`。
- 至少 10 个案例、两个独立来源组，覆盖首批五个规则且包含负对照；不得重复文件哈希/大小写路径，不得包含已登记原六模型/14 变体，未完成求值的鲁棒性标签另行处理。

只有以上声明、审核信息、覆盖条件和全部完整检查均满足时，才提供 `meets_recall_above_90_percent`（严格大于 90%）结果；否则为 `null` 并列出阻断原因。该字段仅表示 Recall 目标，不表示精度、误报率或全部比赛验收条件达标。

通用评分现复用真正冻结门槛；只满足早期条件的清单会追加 `formal_freeze_requirements_not_met`，不会提升资格，开发统计仍保留。具体修复、历史记录与源码版本影响见 [验收门槛一致性](ACCEPTANCE_ELIGIBILITY.md)。通用入口不创建冻结凭证，正式成绩仍按冻结/运行/复核流程核验。

这些元数据不能自动证明独立性：应由未参与规则调试的团队成员建立并审核模型，记录来源，禁止只复制改名或轻改开发样本冒充独立数据；看过验收结果并据此调规则后，应另建新的独立验收集。工具能拒绝已知开发模型哈希，但无法识别所有变体泄漏。

## 验证与影响

新增入口只增加批量编排和评估，不改动规则算法、JSON 诊断契约或六个原始模型。单文件 `run.json` 增加源码与结果内容哈希；旧调用方式保持不变。摘要记录每个被评分报告及其运行记录哈希，便于核对来源。

离线测试覆盖重复计数、零分母、漏报误报、不完整覆盖、独立性与审核阻断、来源及配置不符、报告篡改、现有输出保护、单模型失败继续和用户中断。真实 COMSOL 验证与离线模拟分开记录，CI 不运行 COMSOL。

原始日志、模型副本留在忽略的 `outputs/`；失败摘要可能包含本机路径，分享前应检查。回退时撤回批量入口、相关测试与文档即可；单文件入口新增哈希字段可保留，不影响原诊断结果。
