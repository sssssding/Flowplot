# 文档索引

| 文档 | 用途 | 维护时机 |
|---|---|---|
| [PROJECT_SCOPE.md](PROJECT_SCOPE.md) | MVP 边界、支持项和非目标 | 范围变化前先更新 |
| [BLUEPRINT.md](BLUEPRINT.md) | 系统架构、数据流和里程碑 | 架构评审后更新 |
| [COLLABORATION.md](COLLABORATION.md) | Git/GitHub 多人协作流程 | 工作流变化时更新 |
| [HANDOFF.md](HANDOFF.md) | 当前功能分支拉取、运行复现、验证边界与下一位开发者待办 | 交接或集中提交时更新 |
| [PREFLIGHT.md](PREFLIGHT.md) | 只读接手预检、模型保护和运行依赖检查 | 接手或环境排查时更新 |
| [LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md) | 本机接手复现、保留的修改和未完成验收 | 本机复现或交接时更新 |
| [NOTES.md](NOTES.md) | 安全、数据、COMSOL 与建模注意事项 | 发现新风险时更新 |
| [PROGRESS.md](PROGRESS.md) | 项目任务、验收标准和当前进度 | 每次合并 PR 后更新 |
| [BASELINE_MODEL.md](BASELINE_MODEL.md) | COMSOL 基准模型 Ground Truth | 基准模型变化时更新 |
| [BASELINE_REVIEW.md](BASELINE_REVIEW.md) | 保存解速度云图、截面采样与专业复核材料 | 图像复核材料变化时更新 |
| [BASELINE_SOLVES.md](BASELINE_SOLVES.md) | 基准五次重新求解、日志采集与结果一致性 | 自动求解入口或验证证据变化时更新 |
| [DECISIONS.md](DECISIONS.md) | 重要技术决策记录 | 决策被采纳时追加 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 环境、运行命令和验证范围 | 开发入口变化时更新 |
| [MODEL_CHECK.md](MODEL_CHECK.md) | 指定 MPH 文件的只读检查入口、报告和失败处理 | 文件检查流程变化时更新 |
| [BATCH_CHECK.md](BATCH_CHECK.md) | 整组模型的只读检查、漏报误报统计与独立验收阻断 | 批量流程或评估口径变化时更新 |
| [DESKTOP.md](DESKTOP.md) | 本地桌面检查、取消、已有报告读取与功能验证范围 | 界面或会话流程变化时更新 |
| [DESKTOP_REVIEW.md](DESKTOP_REVIEW.md) | 可见工程核验、启动与布局修复及未完成验收 | 每次可见核验后更新 |
| [REPORT_COMPARISON.md](REPORT_COMPARISON.md) | 前后报告差异、比较条件及离线导出 | 对比流程或口径变化时更新 |
| [CHECK_HISTORY.md](CHECK_HISTORY.md) | 本地历史浏览、运行状态边界及重新核验 | 历史扫描或窗口流程变化时更新 |
| [MODEL_OVERVIEW.md](MODEL_OVERVIEW.md) | 模型尺寸/材料/边界概览及缺失边界证据 | 概览或解释证据变化时更新 |
| [REPORT_PACKAGE.md](REPORT_PACKAGE.md) | 离线协作报告导出、重新导入及隐私边界 | 分享格式或完整性核验变化时更新 |
| [REPORT_VALIDATION.md](REPORT_VALIDATION.md) | 统一报告读取、条目/状态一致性及快照指纹 | 报告消费者或读取限制变化时更新 |
| [BOUNDARY_CASES.md](BOUNDARY_CASES.md) | 五类异常样本、预期标签和复核清单 | 新增或审核样本时更新 |
| [REGRESSION_FAMILY.md](REGRESSION_FAMILY.md) | 14 个未求解矩形变体、真实配置差异及阈值末位保护 | 受控变体或实测证据变化时更新 |
| [RULES.md](RULES.md) | 规则 ID、证据、适用范围与 JSON 契约 | 规则变化时更新 |
| [NUMERIC_SAFETY.md](NUMERIC_SAFETY.md) | Re 数值稳定性、派生量不可用及合成反例边界 | 数值计算或输入范围变化时更新 |
| [GUI_REVIEW.md](GUI_REVIEW.md) | COMSOL 界面核对、兼容性提示和未完成项 | 每次 GUI 核对后更新 |

## 文档规则

- 文档与代码放在同一个 Pull Request 中同步更新。
- 设计变化必须说明动机、影响范围、验证方式和回滚方案。
- 不在文档中保存账号、许可证密钥、访问令牌或本机绝对路径。
- 进度只记录可验证状态；“进行中”必须关联 Issue 或负责人。
