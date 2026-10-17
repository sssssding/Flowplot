# 完整软件目标审计

更新：2026-10-17。用户目标是得到具备约定功能且完成检验的软件。下表保留原退出条件；工程结果及用户操作统计只在 [PROGRESS.md](PROGRESS.md) 维护，本页说明各门槛及结论。开发样本不得替代独立验收。

| 原始要求/门槛 | 当前证据 | 结论 |
|---|---|---|
| 基准稳定性：连续加载 10 次；重复自动求解 5 次并核对日志/指标 | 历史加载与求解记录见 [BASELINE_MODEL.md](BASELINE_MODEL.md)、[BASELINE_SOLVES.md](BASELINE_SOLVES.md)；保存解复核见 [BASELINE_REVIEW.md](BASELINE_REVIEW.md) | 工程技术记录具备；GUI 日志对照与专业复核仍有缺口 |
| 物理场/边界识别、单位、JSON Schema 与规则诊断 | 当前受支持矩形模型族的真实检查和 fixture 回归；见 [工程验证 JSON](validation/2026-10-17/engineering-summary.json)、[RULES.md](RULES.md)、[MODEL_CHECK.md](MODEL_CHECK.md) | 当前范围内开发验证通过；不外推任意 COMSOL 模型 |
| 五类诊断、风险等级、解释、定位与下一步建议 | 受支持开发模板及规则/真实报告回归见 [RULES.md](RULES.md)、[BOUNDARY_CASES.md](BOUNDARY_CASES.md)；专业适用性仍待审核 | 功能开发验证有记录，专业审核未完成 |
| 独立异常集 Recall > 90%，同时报告误报/覆盖及专业标签审核 | 正式冻结和重算工具已实现；无真实专业审核的至少 10 个独立来源未见模型 | 未完成 |
| 模型级数据划分且配置效果可学习 | 训练观察来自同源几何配置；模型级未见数据和独立性能证据不足；见 [AI_PORTABILITY.md](AI_PORTABILITY.md) | 未达到完整数据集退出条件 |
| 推荐优于默认、经验和随机配置；需要时验证跨硬件 | 本机副本测量见 [推荐评估 JSON](validation/2026-10-17/recommendation-evaluation.json)；质量检查完成但未证明稳定收益 | T13 未通过；不声称加速或泛化 |
| 桌面启动、证据/概览/历史/对比/协作报告流程，以及失败/取消恢复 | 用户操作原记录见 [visible-ui-record.md](validation/2026-10-17/visible-ui-record.md)；隐藏回调测试另见 [UI_VERIFICATION_BLOCKER.md](UI_VERIFICATION_BLOCKER.md) | 部分真实操作有记录；范围外/部分模型流程及完整可见验收未完成 |
| 新用户 5 分钟完成“选择—检查—理解”；至少 10 个未见模型端到端 | 未参与开发的新用户及可靠计时未收集；当前开发集不独立 | 未完成 |
| 完整软件目标 | 上述正式门槛缺少对应范围的可靠证据 | 未完成 |

## 权威的 2026-10-17 记录

- [日期摘要](validation/2026-10-17/README.md)：环境、操作和证据范围。
- [工程 JSON](validation/2026-10-17/engineering-summary.json)：测试、模型检查及输入/源码指纹。
- [推荐评估 JSON](validation/2026-10-17/recommendation-evaluation.json)：测量值、候选、质量及收益判定。
- [用户操作记录](validation/2026-10-17/visible-ui-record.md)：实际反馈和未验证项。

保留文件内容和 Git 来源；不以其认证人员或审核身份。模型副本、原生日志、截图、许可证及本机安装路径不随文档同步。

## 下一步

按 [DELIVERY_PLAN.md](DELIVERY_PLAN.md) 补齐对应的真实界面样本、专业与独立模型审核、新用户试用；如需主张跨硬件收益，另行进行按模型隔离的多机重复比较。在证据满足各自原门槛前，完整目标保持未完成。
