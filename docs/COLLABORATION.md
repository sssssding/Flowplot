# 多人协作规范

## GitHub 工作流

1. 每项工作先建立 Issue，写清目标、输入、输出和验收标准。
2. 从最新 `main` 创建短生命周期分支。
3. 小步提交，提交信息说明“为什么改”，不要只写“update”。
4. 推送后创建 Pull Request，至少由一名非作者成员审查。
5. CI、测试和文档检查通过后，以 Squash Merge 合并。
6. 合并后删除远程功能分支并更新 `docs/PROGRESS.md`。

## 分支命名

```text
feat/<issue>-<short-name>
fix/<issue>-<short-name>
docs/<issue>-<short-name>
test/<issue>-<short-name>
experiment/<issue>-<short-name>
```

示例：`feat/12-boundary-parser`。

## Commit 约定

```text
feat: add COMSOL boundary parser
fix: preserve disabled boundary features
docs: record baseline model ground truth
test: add missing-outlet fixture
chore: configure lint workflow
```

一次提交只处理一个逻辑变化。禁止提交密码、令牌、COMSOL 许可证信息、个人目录和未经授权的数据。

## Pull Request 必填项

- 关联 Issue
- 变更目的与范围
- 验证命令及结果
- 对 Schema、规则、模型或文档的影响
- 必要时提供 COMSOL GUI 对照证据

## 代码评审检查

- 是否仍在 `PROJECT_SCOPE.md` 的支持范围内？
- 解析结果是否有可复现的 Ground Truth？
- 是否处理了单位、空值、禁用 feature 和版本差异？
- 是否新增或更新测试？
- 是否泄露路径、账号、密钥或受限模型？
- 文档和进度是否同步？

## 冲突与决策

- 技术争议先在 Issue 中列出事实、方案、利弊和验证结果。
- 影响架构或范围的结论追加到 `DECISIONS.md`。
- 未经评审，不直接向 `main` 强制推送。
- 紧急修复也必须保留 Issue、测试证据和事后复盘。

## 大文件策略

`.mph`、大规模求解结果和数据集不能直接以普通 Git Blob 提交。需要共享的 `.mph` 使用 Git LFS；可再生的输出只提交生成脚本、参数清单和摘要结果。
