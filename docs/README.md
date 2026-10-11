# 文档索引

| 文档 | 用途 | 维护时机 |
|---|---|---|
| [PROJECT_SCOPE.md](PROJECT_SCOPE.md) | MVP 边界、支持项和非目标 | 范围变化前先更新 |
| [BLUEPRINT.md](BLUEPRINT.md) | 系统架构、数据流和里程碑 | 架构评审后更新 |
| [COLLABORATION.md](COLLABORATION.md) | Git/GitHub 多人协作流程 | 工作流变化时更新 |
| [NOTES.md](NOTES.md) | 安全、数据、COMSOL 与建模注意事项 | 发现新风险时更新 |
| [PROGRESS.md](PROGRESS.md) | 项目任务、验收标准和当前进度 | 每次合并 PR 后更新 |
| [BASELINE_MODEL.md](BASELINE_MODEL.md) | COMSOL 基准模型 Ground Truth | 基准模型变化时更新 |
| [DECISIONS.md](DECISIONS.md) | 重要技术决策记录 | 决策被采纳时追加 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 环境、运行命令和验证范围 | 开发入口变化时更新 |
| [BOUNDARY_CASES.md](BOUNDARY_CASES.md) | 五类异常样本、预期标签和复核清单 | 新增或审核样本时更新 |
| [RULES.md](RULES.md) | 规则 ID、证据、适用范围与 JSON 契约 | 规则变化时更新 |

## 文档规则

- 文档与代码放在同一个 Pull Request 中同步更新。
- 设计变化必须说明动机、影响范围、验证方式和回滚方案。
- 不在文档中保存账号、许可证密钥、访问令牌或本机绝对路径。
- 进度只记录可验证状态；“进行中”必须关联 Issue 或负责人。
