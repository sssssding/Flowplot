# 验收集冻结与运行核验

日期：2026-10-13。实现 `acceptance_dataset.py`，衔接 [专业复核与独立验收计划](ACCEPTANCE_PLAN.md)。目前团队尚未提供真实独立模型集，因此本轮没有生成正式验收集、填写审核身份或报告独立 Recall。

## 先有真实审核，再冻结

这个工具只接受人已经准备并审核的 `case-manifest-0.1` 清单。它不会生成模型或标签，不调用 AI 填写审核人，不自动把开发集改成独立集；冻结阶段也不调用 COMSOL。

冻结前必须满足：

- 至少 10 个模型，覆盖首批五个规则，并有至少一个无预期 code 的负对照。
- `independent_acceptance_set: true`、`label_status: "expert_reviewed"`，每个案例有实际 SHA-256、审核后的 `expected_codes`、真实 `reviewed_by` / `reviewed_date` 和 `used_for_rule_development: false`。
- 每个案例额外填写 `created_by`、`origin_reference`、`independence_group`。登记至少两个来源组是最低组织要求，不意味着两个名称不同就证明数据独立或覆盖充分。
- 清单顶层增加对象 `acceptance_declaration`，包含 `dataset_id`、`independence_reviewed_by`、`independence_reviewed_date`；团队真实确认后，才将 `models_not_derived_from_development`、`labels_fixed_before_diagnosis`、`creators_and_reviewers_not_rule_developers` 三项设为 true。
- 审核日期必须是已发生的 `YYYY-MM-DD` 日期，按北京时间日期检查，不能填未来日期。身份、来源及自由文本不是程序可认证的凭据。
- 拒绝原六模型与版本化 14 变体的已知模型哈希；不同文件名、轻改参数、重新保存产生新哈希，不会自动获得独立资格。已知哈希登记不是所有派生模型的识别器。
- `EVALUATION_UNAVAILABLE` 预期样本归入另外的鲁棒性检查，不混入正式支持范围验收。其他实际 partial/unsupported/失败结果仍全部保留，不挑成功样本计分。

这里不提供已经填写好“审核通过”的示例清单。团队应真实完成上述工作后再运行；测试文件里的合成审核字符串与模拟字节不是验收数据，不可复制冒充审核证据。

## 命令

使用已安装 `requirements-dev.txt` 依赖的 Python，在项目根目录执行。冻结输出目录必须全新，且位于独立模型输入根目录之外；后续运行结果也必须位于冻结目录之外：

```powershell
# 只复制并固定已审核输入；不运行 COMSOL 或诊断
python -X utf8 src/flowpilot/acceptance_dataset.py freeze --manifest '<真实审核清单>' --model-root '<独立模型根目录>' --output-dir outputs/acceptance/frozen-001

# 只读核验冻结目录、模型、标签清单与程序版本
python -X utf8 src/flowpilot/acceptance_dataset.py verify outputs/acceptance/frozen-001

# 正式只读检查：默认每个模型重复加载两次
python -X utf8 src/flowpilot/acceptance_dataset.py run outputs/acceptance/frozen-001 --comsol-root '<COMSOL_ROOT>' --output-dir outputs/acceptance/run-001 --loads 2

# 对正式检查子目录中的同一批报告复核，不再调用 COMSOL
python -X utf8 src/flowpilot/acceptance_dataset.py run outputs/acceptance/frozen-001 --reports-root outputs/acceptance/run-001/checks --output-dir outputs/acceptance/offline-001
```

`freeze` / `verify` 退出码 0 表示输入固定/完整性核验成功，不表示模型通过。`run` 的 0 表示完整检查并满足声明资格下的 Recall > 90%；1 为准备/运行/完整性错误，2 为覆盖不完整，3 为 Recall 目标未满足。误报、严重等级、定位、物理正确性及用户理解仍应独立审核，0 不是全部比赛验收通过。

## 固定了哪些内容

冻结目录固定为 `freeze.json`、`manifest.json` 和 `models/`：

- 独立副本使用安全 case ID 保存，核对输入哈希、复制内容哈希、复制后原文件哈希。原件不保存、不恢复、不覆盖。
- 冻结清单保留审核标签、来源及独立性声明，使用目录内统一相对模型路径。不复制未知清单字段或原始绝对模型路径字段；自由文本仍可能敏感，冻结目录默认仅留本机。
- 同时固定规则、COMSOL 枚举、归一化 Schema、检查/报告读取/批量编排/冻结工具及开发集登记文件的字节指纹，记录冻结时间与运行环境信息。依赖版本只记录，源码版本必须匹配。
- `freeze.json` 最后写入。中断、存储错误、模型/清单/程序在冻结中变化时，不发布有效完成标记；残留目录保留排查，不能复用。
- 核验拒绝额外/缺失文件、模型变化、清单变化、源码变化、链接/目录联接及路径越界。JSON 有界读取并拒绝重复字段、非有限数值和过深嵌套。

哈希不是签名，目录没有设置操作系统级不可修改权限；工具不防止有权限者同时重写所有文件和哈希，也不是文件系统原子快照。真实身份、源头独立性、审核过程及是否提前看过诊断，仍由团队负责。

## 运行结果与版本变化

运行先核验冻结集，再调用现有 `check_suite.py`，结束后再次核验。正式顶层 `result.json` 绑定本次 `freeze.json` 的实际字节指纹；`run.json` 区分 completed、incomplete、failed、cancelled。

正式发布现使用 `acceptance-run-0.2` / `acceptance-result-0.2`，同时绑定结果与批量产物的字节指纹，核对批量返回值/保存汇总和完成状态。完成后用 [正式结果复核](ACCEPTANCE_RESULTS.md) 从单模型证据重新计算，不直接引用结果 JSON 内的 Recall。冻结指纹已包含复核模块，旧目录不会自动升级。

若评估中冻结集或程序发生变化，即使 `checks/` 已留下原始批量产物，也不发布正式 `result.json`，顶层记录失败。不能绕过顶层失败，拿子目录成绩宣称该冻结集正式验收通过。所有失败、缺失、partial/unsupported 仍保留在批量明细。

通用批量入口保留原来的兼容行为，其 `acceptance_eligible` 只检查既有声明条件，不等于执行过本冻结流程。当前正式流程应以冻结工具的核验和顶层结果为准。程序仍不能认证专业审核与真实独立性。

根据验收结果调试或修改规则后，该集已用于开发，必须重新准备未见验收集。不要修改旧指纹、标签或重新保存同源模型以绕过。纯工具版本变化也需团队重新确认和记录冻结过程，不能手改旧冻结文件复用成绩。

## 本轮验证与回退

新增专项测试使用明确标记的模拟 MPH 字节与合成审核声明，覆盖门槛、已知开发模型排除、日期/路径/链接、复制失败、冻结中变化、篡改、版本不符、正式运行失败/中断和不完整结果。它们不证明真实独立模型通过或专业人员完成审核。

实际交接复现另行在本机 COMSOL 6.3.0.290 对原六模型各加载两次，6/6 检查及离线复核符合工程标签，不作为冻结正式集。原始模型和旧证据不改；新工具不改变诊断规则或现有桌面入口。

撤回新模块、专项测试及文档可回退冻结流程，不影响原检查入口和模型。冻结目录默认在忽略的 outputs 中，不自动推送 MPH、审核材料或日志；如需共享，先审阅数据授权与敏感信息，再由团队决定 Git LFS 管理方式。
